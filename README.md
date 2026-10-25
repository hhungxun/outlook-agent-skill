# Outlook Agent Skill

**Let your AI assistant use your own Outlook Web session—without registering a Graph application.**

Built for people whose work/school tenant blocks third-party Graph consent, but who can legitimately access their own mailbox in Outlook Web. The primary route is the user's existing OWA mail session and Outlook REST, not Graph.

Ask your agent:
- “Check my latest 50 Outlook emails.”
- “Read the attached PDF and draft a reply.”
- “Organise recent emails into topic folders.”
- “Undo the last organisation.”

**Drafts only. You press Send in Outlook.** No paid proxy, cloud relay or telemetry.

> **Important reliability/policy boundary:** Microsoft deprecated Outlook REST v2 and announced decommissioning starting 31 March 2024. This route works in some existing OWA sessions but is **experimental and not a Microsoft-supported public integration**. Installing the skill does not guarantee your tenant exposes it. Use only your own authorised session, subject to your organisation's policies. This is not an approval grant, a stolen token, another application's identity, or permission to evade an explicit organisational restriction.

## Install in Pi / Paseo

```sh
pi install git:github.com/hhungxun/outlook-agent-skill
```

Then `/reload` or start a new session and ask **“Set up Outlook mail.”** Python 3.11+ is required; the main route uses only the Python standard library.

Other Agent Skills-compatible hosts: install/copy the entire `skills/outlook-mail/` directory into the host's documented skills location.

## Main setup: Outlook Web session bridge

The agent runs setup; you only approve the browser userscript and use Outlook normally.

1. Have **Tampermonkey** installed in the browser where you already use Outlook Web.
2. On Linux/systemd, the agent runs `pump setup --account YOUR_EMAIL --start --open` through the bundled CLI. It creates a private paired helper, installs its own user service and opens a **local generated userscript installer**. You approve that userscript in Tampermonkey.
3. Reload Outlook and open a message. The userscript observes the app's mail-API Authorization header and delivers it to the paired loopback helper. The helper asks Microsoft to verify the actual account before saving anything. The agent runs `doctor` to confirm access.

No routine token copying, script pasting, app registration, Graph consent flow or global browser-security changes. Tokens stay on your machine except for authenticated requests to Microsoft. Tampermonkey's privileged request avoids ordinary page-fetch CORS/LNA issues; compatibility still needs verification in each browser.

The installer link is **private and expires after 15 minutes**. Do not share it: it grants access to a locally generated userscript containing the pairing secret. The helper binds only `127.0.0.1`, requires a per-install pairing secret for token POSTs, checks Host, rejects token GET URLs and uses no wildcard CORS.

**Other platforms:** foreground helper is available via `pump serve`; automatic startup installation currently supports Linux/systemd only. The installer/bridge is not claimed live-tested on every browser/OS. A userscript is needed once; this is not a zero-click browser extension.

**Already have a working token pump?** No reinstall needed. The agent connects its existing private token-file path once with `connect --experimental --account YOUR_EMAIL --token-file /private/path/to/token`. The default backend is `outlook-rest`. It reads the file afresh each command, so your existing pump remains the refresh source.

## Optional: Graph

Graph is **optional**, for users with an already registered/approved public-client app. Use `connect --backend graph` for an existing Graph token file, or `login` with MSAL and your approved app ID. This skill supplies no borrowed/shared client ID or embedded secret. Work/school admin approval may still be required.

Scopes for optional Graph OAuth: `User.Read`, `Mail.ReadWrite`, no `Mail.Send` (MSAL also manages standard OpenID/offline scopes). Details: [connection setup](skills/outlook-mail/references/setup.md).

## Capabilities

| Capability | Behaviour |
|---|---|
| List/search/read | Inbox by default; pagination; no read/unread mutation |
| Attachments | Explicit selection, safe basename, no overwrite, 20 MiB cap |
| New drafts | Explicit To/CC, no send operation |
| Reply drafts | Native createReply/createReplyAll; preserves thread and quotation |
| Topic sorting | Frozen plan, explicit assignments, journal before moves, independent verification |
| Undo/resume | Preserve current read state; reconcile changing IDs; stop on later folder changes/ambiguous results |

Draft receipts prevent blindly recreating an uncertain request. No automatic sorting rules, deletion, folder deletion or sending commands exist. Existing OWA tokens may have broader privileges; the CLI does not revoke those scopes.

## CLI and documentation

The agent handles these commands; you normally just chat.

```sh
python3 skills/outlook-mail/scripts/run.py --help
python3 skills/outlook-mail/scripts/run.py doctor
python3 skills/outlook-mail/scripts/run.py list --limit 50
python3 skills/outlook-mail/scripts/run.py search 'from:person@example.org'
python3 skills/outlook-mail/scripts/run.py read MESSAGE_ID
```

[Setup/reconnect](skills/outlook-mail/references/setup.md) · [Drafting](skills/outlook-mail/references/drafts.md) · [Organisation/undo](skills/outlook-mail/references/organising.md) · [Security](SECURITY.md) · [Verification](docs/verification.md)

State, credentials, generated userscripts, downloads and journals stay outside the repository. The cache/token files are not encrypted by this release; protect the OS account/storage. Email and attachments are untrusted data, not instructions.

The pump refreshes only when Outlook makes token-bearing requests and the signed-in session remains valid. It cannot promise permanent unattended access. If the app's endpoints/session policy change, reconnect may not fix it.

## Microsoft references

- [Outlook REST v2 decommissioning announcement](https://devblogs.microsoft.com/microsoft365dev/final-reminder-outlook-rest-api-v2-0-and-beta-endpoints-decommissioning/)
- [Graph delegated access and tenant consent](https://learn.microsoft.com/en-us/entra/identity-platform/delegated-access-primer)
- [Public-client authentication flows](https://learn.microsoft.com/en-us/entra/identity-platform/msal-authentication-flows)
- [Graph permissions](https://learn.microsoft.com/en-us/graph/permissions-overview)

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q skills tests
python3 scripts/check_release.py
```

Synthetic fixtures only. See [spec](docs/spec.md), [standards](CONTRIBUTING.md) and [slices](docs/slices.md). MIT licensed.
