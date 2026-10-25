# Verification evidence

Initial verification: 2026-10-26. Experimental v0.1.0; this is not a production/security certification.

## Automated

- `python3 -m unittest discover -s tests -v`: 51 executed tests passing after review fixes (the Graph and REST suites intentionally inherit the same behaviour tests).
- `python3 -m compileall -q skills tests`: passing.
- Tests exercise the public CLI against synthetic Graph and REST servers, pagination, scope/account checks, attachments, native reply drafts, request receipts, plan/apply/undo, lost-response reconciliation and later user changes.
- Real loopback HTTP tests use synthetic tokens and a controlled remote transport to exercise pairing/Host rejection, account screening before persistence, private installation links, no wildcard CORS and paired shutdown.
- No live credentials/mailbox fixtures in tests or CI. CI matrix describes environments to be tested, not evidence of a completed remote run.
- JS syntax and release/history/privacy checks run before release. See the release commit/CI for final results.

## Private live smoke test

On Linux / Python 3.14, the new skill connected to the user's **existing** private OWA mail-token file outside the repository. Microsoft profile/account verification succeeded; `doctor` identified the REST backend; Inbox listing returned 3 non-draft messages. Only read-only calls were made. No message/account identifiers, tokens, attachments or receipts from this smoke test are part of the repository.

## Browser and OAuth limitations

The earlier personal prototype's privileged Tampermonkey delivery was observed working in Zen. The newly packaged generated-script installer and owned service are tested structurally/with synthetic HTTP, **not yet through a fresh human browser installation with normal LNA settings**. Existing-token reuse works independently of that new installer.

The optional Graph OAuth path follows MSAL's public-client device/silent flows; no live Graph sign-in was performed because that tenant's admin consent is unavailable. No claim of live Windows/macOS service installation or universal browser/tenant compatibility.

## Review

Two independent read-only reviewers inspected implementation commit 6f05107 against the empty initial baseline fc7c64b. Their sandbox had file access but no shell/Git/test execution; this was source review, not independent executable verification. The parent ran the tests and fresh-clone checks.

### Standards
Initial verdict: OK WITH NOTES. Applied defence-in-depth runtime-data ignores/scanning, CI JavaScript syntax checking, explicit autostart-helper consent, stronger URL traversal/JS expiry screening, clearer uncertain-write wording and documented security test seams. The reviewer inferred test count from method definitions; the parent verified executed test counts via unittest discovery, including inherited provider suites.

### Spec
Initial verdict: BLOCK for reapplying a journal after a later user read-state edit. Reproduced it as a failing regression; fixed historical read-state comparison while retaining immediate per-move verification. Added regression tests for interrupted undo, uncertain folder creation, mixed eligible/ineligible snapshots and canonical legacy REST reply-action casing. Corrected disconnect documentation. Final automated suite: 51 passing tests. One review round; no claim that reviewers re-ran the fixes.

The main remaining limitations are the new browser install flow not yet human-tested under normal browser protections, optional Graph OAuth without a live tenant test, and no automatic startup installer beyond Linux/systemd. Technical claims are limited to the evidence above.
