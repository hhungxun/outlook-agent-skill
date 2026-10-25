# Domain glossary

- **Connection**: a configured mailbox identity and authorised credential source; not a promise of permanent access.
- **Received mail**: messages in Inbox unless the user explicitly selects another folder; not sent mail or drafts.
- **Reply draft**: an unsent response linked to its original message, not merely a new message with a Re: subject.
- **Organisation plan**: a frozen set of messages with intended topic-folder assignments; contains private mailbox metadata.
- **Journal**: durable evidence of requested, completed and uncertain moves, including old/new identifiers and read state.
- **Undo**: restoration of journaled messages still in the expected destination, preserving their current read status and reporting conflicts.
- **Uncertain write**: a request whose response was lost; it must be reconciled rather than blindly repeated.
