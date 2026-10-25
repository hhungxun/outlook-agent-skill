"""Fixed-origin transport and one normalised mailbox interface."""
import json
import time
from urllib import error, parse, request

BASES = {"graph": "https://graph.microsoft.com/v1.0",
         "outlook-rest": "https://outlook.office.com/api/v2.0"}


class MailError(Exception):
    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code, self.status = code, status


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpTransport:
    def __call__(self, method, url, token, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, method=method,
                              headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                                       "Content-Type": "application/json"})
        opener = request.build_opener(NoRedirect())
        for attempt in range(3 if method == "GET" else 1):
            try:
                with opener.open(req, timeout=30) as response:
                    raw = response.read(40 * 1024 * 1024 + 1)
                    if len(raw) > 40 * 1024 * 1024:
                        raise MailError("response_too_large", "Response exceeds 40 MiB")
                    return json.loads(raw) if raw else {}
            except error.HTTPError as exc:
                status = exc.code
                if method == "GET" and status in (429, 503) and attempt < 2:
                    retry = exc.headers.get("Retry-After", "1")
                    time.sleep(min(int(retry) if retry.isdigit() else 1, 5))
                    exc.close()
                    continue
                exc.close()
                codes = {401: ("reauth_required", "Connection expired or rejected; reconnect Outlook."),
                         403: ("consent_required", "Mailbox access denied. Check granted permissions and tenant policy; ask the administrator if required."),
                         404: ("not_found", "Message or folder not found."),
                         429: ("throttled", "Mailbox throttled; retry later.")}
                code, message = codes.get(status, ("http_error", "Mailbox request failed; no response body logged."))
                raise MailError(code, message, status) from None
            except (error.URLError, TimeoutError, OSError):
                raise MailError("network_error", "Network request failed; a write may have succeeded. Reconcile its journal/receipt before retrying.") from None
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise MailError("invalid_response", "Mailbox returned an invalid response.") from None


def normalise(value):
    if isinstance(value, list):
        return [normalise(v) for v in value]
    if isinstance(value, dict):
        return {(k[:1].lower() + k[1:] if not k.startswith("@") else k): normalise(v)
                for k, v in value.items()}
    return value


def rest_payload(value):
    if isinstance(value, list):
        return [rest_payload(v) for v in value]
    if isinstance(value, dict):
        return {(k[:1].upper() + k[1:] if not k.startswith("@") else k): rest_payload(v)
                for k, v in value.items()}
    return value


class Client:
    def __init__(self, token, backend="graph", transport=None):
        if backend not in BASES:
            raise ValueError("Unknown mailbox backend")
        self.base = BASES[backend]
        self.backend = backend
        self.token = token
        self.transport = transport or HttpTransport()

    def url(self, path, params=None):
        url = self.base + "/" + path.lstrip("/")
        return url + ("?" + parse.urlencode(params) if params else "")

    def safe_url(self, url):
        candidate, base = parse.urlsplit(url), parse.urlsplit(self.base)
        if (candidate.scheme != base.scheme or candidate.netloc != base.netloc or
                candidate.username or candidate.password or candidate.fragment or
                not candidate.path.startswith(base.path + "/")):
            raise MailError("unsafe_url", "Refusing an authenticated request outside the configured HTTPS provider.")
        return url

    def call(self, method, path, payload=None, params=None, absolute=False):
        url = self.safe_url(path if absolute else self.url(path, params))
        if self.backend == "outlook-rest" and payload is not None:
            payload = rest_payload(payload)
        return normalise(self.transport(method, url, self.token, payload))

    def pages(self, path, params=None, limit=50):
        if not 1 <= limit <= 1000:
            raise ValueError("Limit must be between 1 and 1000")
        result, seen = [], set()
        url = self.url(path, params)
        while url and len(result) < limit:
            if url in seen:
                raise MailError("pagination_loop", "Mailbox repeated a page link.")
            seen.add(url)
            if len(seen) > 1000:
                raise MailError("pagination_limit", "Too many mailbox pages.")
            page = self.call("GET", url, absolute=True)
            result.extend(page.get("value", []))
            url = page.get("@odata.nextLink")
        return result[:limit]

    def identity(self):
        profile = self.call("GET", "me")
        addresses = [profile.get(k, "") for k in ("mail", "userPrincipalName", "emailAddress")]
        return profile, [a.casefold() for a in addresses if isinstance(a, str) and a]

    def check_account(self, expected):
        _, addresses = self.identity()
        if expected.casefold() not in addresses:
            raise MailError("account_mismatch", "Connected mailbox does not match the expected account.")
        return expected.casefold()

    def message(self, mid):
        return self.call("GET", "me/messages/" + parse.quote(mid, safe=""))

    def folder(self, name):
        known = {"inbox": "inbox", "drafts": "drafts", "sent": "sentitems", "sentitems": "sentitems"}
        if name.lower() in known:
            return known[name.lower()]
        folders = self.pages("me/mailFolders", {"$top": 100}, limit=1000)
        matches = [f for f in folders if name in (f["id"], f["displayName"])]
        if len(matches) != 1:
            raise ValueError("Folder not found or ambiguous; use a root folder name or exact ID")
        return matches[0]["id"]

    def list_messages(self, folder="inbox", limit=50, query=None):
        fid = self.folder(folder)
        field = "ReceivedDateTime" if self.backend == "outlook-rest" else "receivedDateTime"
        params = {"$top": min(limit, 100), "$orderby": field + " desc"}
        if query:
            params.pop("$orderby")
            params["$search"] = json.dumps(query, ensure_ascii=False)
        items = self.pages("me/mailFolders/" + parse.quote(fid, safe="") + "/messages",
                           params, limit=limit)
        return items

    def move(self, mid, destination):
        return self.call("POST", "me/messages/" + parse.quote(mid, safe="") + "/move",
                         {"destinationId": destination})

    def find_moved(self, folder_id, internet_id):
        field = "InternetMessageId" if self.backend == "outlook-rest" else "internetMessageId"
        expr = field + " eq '" + internet_id.replace("'", "''") + "'"
        return self.pages("me/mailFolders/" + parse.quote(folder_id, safe="") + "/messages",
                          {"$filter": expr, "$top": 3}, limit=3)
