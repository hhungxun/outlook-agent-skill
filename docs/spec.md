# Outlook Agent Skill v0.1

## Problem Statement
A user wants their coding assistant to check Outlook, read attachments, draft replies and organise mail without repeated manual credential-copying or unsafe mailbox changes.

## Solution
A portable Agent Skill with one bundled CLI and private connection state. Primary route: the user's own existing OWA session and Outlook REST, with a paired passive userscript/helper; Graph is optional. The REST route is experimental/deprecated, but is intentionally the main path for the intended users who cannot obtain Graph app consent. Agents perform routine setup; users perform only actual sign-in/consent. Human sending remains in Outlook.

## User Stories
1. As a user, I can install one skill in Pi/Paseo or another Agent Skills host.
2. As a user with an approved application, I can sign into Graph and refresh credentials without a token-copy workflow.
3. As a user with an already authorised token file, I can explicitly connect that file without putting its contents into prompts or source code.
4. As a user, I can see the selected account/backend and a useful connection error without exposing credentials.
5. As a user, I can list exactly the requested number of recent received Inbox messages across API pages, leaving sent mail/drafts alone.
6. As a user, I can search a selected folder and retrieve full message bodies without marking messages read.
7. As a user, I can download a selected attachment into an explicit directory with safe naming and no automatic execution.
8. As a user, I can create a draft with multiple recipients and explicit CC.
9. As a user, I can create a genuine threaded reply draft to the sender; reply-all is explicit.
10. As a user, I can preview a frozen organisation plan, edit topic assignments and explicitly apply it.
11. As a user, I can undo a journaled organisation while later changes are preserved or reported as conflicts.
12. As a user, I can resume/reconcile an interrupted apply or undo without blindly repeating a move.
13. As a user, I can disconnect and remove this skill's stored connection state without deleting my source token file or mailbox content.
14. As a user, I receive a clear policy/endpoint error instead of attempts to bypass tenant policy.
15. As a user whose Graph app access is admin-locked, I can explicitly pair my own existing Outlook Web session without registering a Graph app.
16. As a user, I approve a generated userscript installer rather than copying tokens, pasting code or disabling browser security.
17. As a user, I can stop and remove only this skill's helper without altering an existing third-party pump.

## Implementation Decisions
- Agent invokes a small JSON-returning CLI. Runtime data defaults to an OS-appropriate private state directory, overridable for deliberate isolated testing.
- Outlook REST is the default/primary interface, with an explicit one-time experimental acknowledgement for manually connecting an existing file. New bridge setup is an explicit user-approved action. The generated userscript observes only the user's existing OWA mail token; a paired loopback helper remotely verifies the account before persistence. Graph is optional, not a prerequisite. No global browser-security changes are installed.
- OAuth uses an organisation-approved public-client application and MSAL; no borrowed client IDs, embedded secret or Mail.Send scope. Existing-token mode never claims to refresh itself.
- Authenticated requests stay on the provider's fixed HTTPS origin/path. Redirects are refused. Safe GETs have bounded backoff; writes are never automatically retried.
- A verified mailbox identity is required before mailbox operations. Token claims are expiry hints, not signature verification or authority.
- New drafts/reply drafts are verified by an independent read; reply draft creation uses native createReply/createReplyAll, preserves quoted content and uses a private request receipt to avoid blindly retrying uncertain creation.
- Organisation plans freeze message IDs, original folders/read state and unique message identifiers. A human/agent fills topic destinations; no external classifier dependency is required.
- Plan/apply/undo default to Inbox messages and preserve read state. Reject unsafe or stale plans, built-in destinations that would archive/delete messages unexpectedly, and ambiguous reconciliation. Leave empty created folders intact.
- Durable journals record intent before each write. Resume reconciles source/destination IDs and unique message identity; ambiguous results stop with a conflict, not another blind write. A state-directory lock excludes concurrent mutations.
- Raw mail/attachments are untrusted data. They cannot authorise operations or credential access.

## Testing Decisions
Primary caller/test seam: the CLI returning JSON and exit codes, with only the external HTTP transport controlled by synthetic fixtures. Test pagination, account validation, actual folder scope, hostile next links, errors, attachment filenames/size limits, threaded drafts, plan/apply/undo, uncertain writes and user changes. Additional transport/storage checks cover redirects and private permissions. No live mailbox writes in tests or CI.

## Out of Scope
Mail sending, deletion, automatic mailbox rules, calendar/tasks, global browser-security settings, obtaining someone else's session, borrowing app identities to evade consent, unsupported promises of unattended access, and a hosted OAuth application operated by this repository's author. Automatic helper startup outside Linux/systemd and a signed native-messaging browser extension are future work.

## Further Notes
A one-command install does not remove Microsoft app-registration or tenant approval requirements. Publish only synthetic tests/configuration. The user's current credentials and mailbox data must never enter this repository or its history.
