"""Legitimate credential sources: existing private token or approved Graph public client."""
import base64
import json
import os
import time
from pathlib import Path
from .client import Client, MailError
from .storage import read_json, state_dir, write_json


def read_token(path):
    path = Path(path).expanduser()
    if not path.is_file() or path.is_symlink():
        raise ValueError("Token file must be an existing regular, non-symlink file")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise ValueError("Token file is not private; set its permissions to 0600")
    token = path.read_text(encoding="utf-8").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token or "\n" in token or "\r" in token or len(token) > 32768:
        raise ValueError("Invalid token file")
    # Unverified expiry hint only. The remote API authenticates credentials.
    try:
        segment = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        exp = claims.get("exp")
    except (IndexError, ValueError, TypeError):
        exp = None
    if isinstance(exp, (int, float)) and exp < time.time() + 60:
        raise MailError("reauth_required", "Token expired or expires within a minute; refresh its source or reconnect.")
    return token


def connect_token(path, account, backend, experimental=False, transport=None):
    if backend == "outlook-rest" and not experimental:
        raise ValueError("Outlook REST is deprecated/experimental; explicit --experimental is required")
    config = {"backend": backend, "account": account.casefold(), "mode": "token-file",
              "token_file": str(Path(path).expanduser().absolute())}
    client = Client(read_token(config["token_file"]), backend, transport)
    client.check_account(account)
    write_json(state_dir() / "config.json", config)
    return {"connected": True, "account": config["account"], "backend": backend,
            "refresh": "managed by token-file source; skill does not refresh this token"}


def load_connection(transport=None):
    path = state_dir() / "config.json"
    if not path.exists():
        raise MailError("not_connected", "Outlook is not connected. Use connect with an existing authorised token file or login with an approved Graph public-client application.")
    config = read_json(path)
    token = read_token(config["token_file"]) if config["mode"] == "token-file" else oauth_token(config)
    client = Client(token, config["backend"], transport)
    client.check_account(config["account"])
    return client, config


def oauth_app(client_id, tenant):
    import re
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", client_id):
        raise ValueError("Client ID must be the registered public application's UUID")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", tenant):
        raise ValueError("Invalid tenant identifier")
    try:
        import msal
    except ImportError:
        raise MailError("missing_dependency", "Graph login needs MSAL. Run scripts/setup.py once, then use the printed runtime command.") from None
    cache = msal.SerializableTokenCache()
    path = state_dir() / "oauth-cache.json"
    if path.exists():
        cache.deserialize(path.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(client_id, authority="https://login.microsoftonline.com/" + tenant,
                                       token_cache=cache, enable_pii_log=False)
    return app, cache


def save_cache(cache):
    if cache.has_state_changed:
        # SerializableTokenCache.serialize returns JSON.
        write_json(state_dir() / "oauth-cache.json", json.loads(cache.serialize()))


def oauth_token(config):
    app, cache = oauth_app(config["client_id"], config["tenant"])
    accounts = app.get_accounts(username=config["account"])
    if not accounts:
        raise MailError("reauth_required", "No cached Graph account; run login again.")
    result = app.acquire_token_silent(["User.Read", "Mail.ReadWrite"], account=accounts[0])
    save_cache(cache)
    if not result or "access_token" not in result:
        raise MailError("reauth_required", "Graph sign-in/consent is required. Run login again; tenant approval may be needed.")
    return result["access_token"]


def login(client_id, tenant, account, transport=None):
    import sys
    import webbrowser
    app, cache = oauth_app(client_id, tenant)
    flow = app.initiate_device_flow(scopes=["User.Read", "Mail.ReadWrite"])
    if "user_code" not in flow:
        raise MailError("login_failed", "Device login unavailable. Check app registration and tenant policy.")
    # Only the user-facing device code/instructions, never bearer tokens.
    print(flow.get("message", "Open the Microsoft device sign-in page and use the displayed code."), file=sys.stderr)
    webbrowser.open(flow.get("verification_uri", "https://microsoft.com/devicelogin"))
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise MailError("login_failed", "Microsoft login/consent failed. Check public-client registration and tenant policy; admin approval may be required.")
    client = Client(result["access_token"], "graph", transport)
    client.check_account(account)
    save_cache(cache)
    write_json(state_dir() / "config.json", {"backend": "graph", "mode": "oauth", "account": account.casefold(),
                                            "client_id": client_id, "tenant": tenant})
    return {"connected": True, "account": account.casefold(), "backend": "graph", "refresh": "MSAL silent refresh when permitted"}
