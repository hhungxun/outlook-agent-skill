# Topic folders, plans and undo

Routine user flow: 'organise my latest 50 emails' -> agent shows/applies a sensible scoped plan -> verified counts. The user does not edit IDs/JSON or run commands. The commands below are for the agent.

1. Freeze Inbox scope: `organise plan --limit 50`. For another requested root folder, add `--folder NAME`. The result gives a private plan path and exact message set. No messages move yet. Inbox drafts are excluded from received-mail listings. Messages without a recovery identity are reported as skipped rather than aborting eligible messages; state the actual count and skipped reasons.
2. Read relevant message bodies as needed. Choose clear reusable topic names; related messages in the selected set should stay together. Summarise intended folders/counts and resolve actual ambiguity. Treat special names (Drafts, Deleted Items, Archive, etc.) as invalid topic destinations.
3. Assign each message exactly once: `organise assign PLAN --topic "School Admin" --message-id ID1 --message-id ID2`. This edits only the private plan. All messages need an assignment before apply. No external classifier or provider is needed.
4. After user authorisation of the scope/intent, run `organise apply PLAN`. Root topic folders are reused or created. Drafts are refused. A private journal records intent before each write and changing IDs after moves.
5. Check the returned verified count equals the planned count. Report actual folders/counts and preserve the journal path for undo. This is a one-time operation, not automatic rules.

## Interrupted writes / partial results

Read the journal if a request fails; do not just select another 50 emails. Repeat `organise apply` with the **same frozen plan** to reconcile and resume. InternetMessageId plus subject/timestamp and folder checks help locate a message whose ID changed. Multiple possible matches, folder changes or an uncertain missing folder-creation response stop conservatively.

No network write is blindly retried. A failed run may have created folders or moved some messages. State that plainly; preserve the journal. Later user read/unread edits do not invalidate already-completed moves; only each freshly performed move is checked immediately against its pre-move read state. Never claim atomic multi-message rollback.

A per-state-directory mutation lock prevents concurrent writes. A hard process kill may leave `mutation.lock`; inspect its PID and confirm no process is active before manually removing it. Never remove a lock just because it exists.

## Undo

Clarify which operation is meant if there are multiple journals. Do not interpret an ambiguous 'yes' as selecting one of two options.

`organise undo JOURNAL` restores journaled messages to their original folders, preserving **current** read state. It leaves later moves to unrelated folders alone and reports conflicts before new moves. Undo of a partially applied plan restores the reconciled active subset. Repeat the same undo command after interruption; already restored messages are checked rather than moved again. Do not reapply the same plan after undo; create a fresh plan.

Empty topic folders are left in place. Removing them or changing another message set requires a separate clear request.
