# Setup — primary route is the user's existing Outlook Web session

Run commands as `python3 <skill>/scripts/run.py ...`. Default backend: **outlook-rest**. Use only the user's own authorised mailbox; tenant policy still applies. This skill targets users for whom Graph app consent is unavailable, not users seeking another person's credentials.

## Fast path: existing working pump/token file

If an authorised private token-file path is already known, use it without reading/printing its contents:

```text
connect --experimental --account user@example.org --token-file /private/path/to/token
doctor
```

The skill reads the token file anew each time. An existing pump can update it without reconfiguration. The file must be regular/non-symlink and 0600 or tighter on POSIX. The skill checks the actual account with Microsoft. The `--experimental` flag is a one-time setup acknowledgement, not a repeated task for the user.

## New setup: passive paired userscript + helper

Requirements: Python 3.11+, own signed-in Outlook Web mailbox, and Tampermonkey in that same browser. Use Tampermonkey's official browser-store listing if it is absent; the user approves extension installation.

Linux/systemd, agent command:

```text
pump setup --account user@example.org --start --open
```

This creates private state, installs/starts only `outlook-mail-pump.service` and opens a local userscript-install URL. Ask the user to approve installation in Tampermonkey, then reload Outlook and open a message. Run `doctor` to verify. No token paste, no manual userscript editing, no LNA/security-pref changes. Do not overwrite another tool's pump/service.

The generated installer link expires after 15 minutes and is private. Re-run setup if it expires; this renews the installer link while keeping the pairing. Never publish the link or generated script, which contains the local pairing secret. It is not the generic template in the package.

On a non-systemd platform, run `pump setup --account user@example.org`, start `pump serve` in a local terminal, and open the returned installation link in the Outlook browser. Automatic startup is not supplied for those platforms in v0.1. A conflicting local port can be changed with `--port PORT`; restart the helper after changing it.

The bridge uses a POST body and a pairing header through `GM_xmlhttpRequest` from Tampermonkey, not page fetch. The loopback helper checks Host/pairing, token shape/audience/exact scope/expiry, then calls Microsoft to verify the account **before saving**. Decoded claims are only screening, not signature validation. No wildcard CORS, token URLs or token logging.

## Reconnect and diagnostics

- `doctor`: current Microsoft mailbox access and account. This is the completion check.
- `pump status`: configured account/port/last accepted time, never credentials. Historical acceptance is not proof the helper is currently running.
- No token yet: confirm helper is active, script enabled in the correct browser, Outlook reloaded and making mail requests.
- Expired session: user signs into Outlook again, reloads, then doctor. No password enters the chat.
- 403 or endpoint unavailable: explain the actual failure; do not promise a bypass. Microsoft has deprecated/decommissioned the public Outlook REST interface; a functioning OWA session is not a general support guarantee.
- `pump stop`: stop/remove this skill's owned systemd service and generated pairing/token files. Then have the user remove the userscript in Tampermonkey.
- `disconnect`: removes connection/OAuth cache only; to stop the new bridge, use `pump stop` too or it can reconnect on the next token.

Tokens refresh only when the Outlook app makes authorised requests and the session stays valid. This is not a promise of permanently unattended mailbox access.

## Optional Graph route

Only for users with a legitimately registered/approved public-client app. It is not the main setup or a workaround for denied consent.

Run `python3 <skill>/scripts/setup.py` once if MSAL is needed; it installs into a private virtualenv. Then:

```text
login --account user@example.org --client-id APPROVED-APP-UUID --tenant organizations
```

The Microsoft device-login page opens and user instructions appear on stderr. The human signs in/consents. No client secret or borrowed app ID is supplied. Scopes: User.Read + Mail.ReadWrite, no Mail.Send; MSAL additionally handles standard OpenID/offline scopes. Silent refresh depends on tenant/session policy. If admin approval is required, stop and request that approval rather than trying a different application to evade it.

For an existing Graph token: `connect --backend graph --account user@example.org --token-file /private/path/to/token`.

## Storage and removal

Linux: `$XDG_STATE_HOME/outlook-mail`, default `~/.local/state/outlook-mail`; macOS: `~/Library/Application Support/outlook-mail`; Windows: `%LOCALAPPDATA%/outlook-mail`. `OUTLOOK_MAIL_HOME` deliberately overrides this. Generated scripts, cache, credentials and journals live there, never in the skill/repository.

POSIX files/directories are private. Windows needs private profile storage and suitable inherited ACLs; no encrypted-at-rest guarantee. Disconnect/removal does not revoke Microsoft-side consent, sessions or backups. Use Microsoft/organisation controls for server-side revocation.
