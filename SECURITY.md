# Security policy and threat model

Protect: bearer/refresh tokens, mailbox contents, attachments, folder/read state and journal metadata.

Trust only the user, the installed agent runtime, the local OS account, reviewed skill code and the configured Microsoft provider. Mail, attachment names/content, linked pages, HTTP errors and continuation URLs are untrusted. A skill is guidance, not a sandbox; an assistant with arbitrary shell/network access still needs appropriate host permissions.

## Controls

- Authenticated requests use a fixed HTTPS provider origin/path and refuse redirects. No user-supplied remote API base.
- No bearer tokens in output, request URLs, subprocess arguments, fixtures or repository data. Only token-file **paths** may be passed. A short-lived local installer capability URL is intentionally shown to its user; it grants access to the generated pairing script, so keep it private and never log/publish it. OAuth device code is shown to the user on stderr; treat it as short-lived sensitive sign-in information.
- Expected account is checked against the remote profile for every command. JWT parsing is only an expiry hint, not signature verification.
- POSIX state directories use 0700 and atomic files start at 0600. Symlink state roots/token files/overwrite targets are refused. Parent-path symlinks and other processes with the same user identity are outside this protection.
- Windows relies on private per-user profile storage and inherited ACLs; no cross-platform ACL-enforcement or encrypted-at-rest claim. Use OS full-disk encryption and appropriate user separation. OAuth caches contain refresh credentials and are sensitive.
- Reads have bounded size, timeouts and limited backoff. Writes are not automatically retried.
- Draft receipts and move journals are private, persisted before writes, and retained for reconciliation/undo. They may contain message subjects/IDs; treat them like mailbox exports.
- Selected file attachments have a 20 MiB cap, safe basenames, exclusive-create writes and basic PDF signature checking. These are not malware detection or PDF validation. Do not open untrusted documents without suitable local protections.
- No send/delete/folder-delete surface. Graph OAuth requests no Mail.Send. Existing credentials may have wider authority, so safeguard them independently.
- Primary route: a user-approved passive OWA userscript copies only the user's existing mail token to a paired loopback helper. The generated script contains a pairing secret and stays in private state; the public template contains no secrets. Token POSTs require pairing and exact Host; no token GET input or wildcard CORS. Microsoft account verification happens before token persistence. The local installer URL expires in 15 minutes and is not logged. No global local-network-access/security override is installed. Existing mailbox authorisation and organisation policy remain binding; this is not another app's grant.

## Failure behaviour

Policy/401/403 errors stop with a redacted diagnostic. Uncertain draft creation stops for inspection rather than creating duplicates. Interrupted moves reconcile against IDs and unique message identity; ambiguous candidates/later folder changes stop. Partial operations are not atomic. A killed process can leave a lock that requires human/agent inspection before removal.

Disconnect stops/removes a bridge owned by this skill if configured, then removes this connection/cache. An external source token file or separately installed pump is untouched. It does not revoke server-side consent/tokens, erase backups or remove downloads/journals. Use Microsoft account/tenant controls for revocation. Local data deletion should be an explicit user action.

## Reporting

Do not open a public issue containing tokens, email content, real journal metadata, tenant/account identifiers or private attachments. Use GitHub private vulnerability reporting if enabled; otherwise report a minimal synthetic reproduction without sensitive details. Never test against someone else's mailbox.
