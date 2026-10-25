# Drafts and replies

Always read the source message and requested attachment first. Separate what is in the email from what the user has actually agreed or completed. Default to a concise, truthful acknowledgement with necessary questions; do not invent scientific corrections or commitments to make a reply sound substantive.

Write body text to a private UTF-8 file. Create one request ID (for example `python3 -c "import uuid; print(uuid.uuid4().hex)"`) and retain it with the operation.

```text
reply-draft MESSAGE_ID --body-file /private/reply.txt --request-id REQUEST_ID
reply-draft MESSAGE_ID --reply-all --body-file /private/reply.txt --request-id REQUEST_ID
draft --to person@example.org --cc other@example.org --subject "Subject" --body-file /private/body.txt --request-id REQUEST_ID
```

Repeat `--to` or `--cc` for multiple recipients. Plain addresses only. For replies the backend creates the actual reply/reply-all object; the CLI prepends your text to its quoted original. No fake `Re:` new-message substitute.

A private receipt is written before creation. A repeated verified request ID returns its existing draft, not a duplicate. A reused ID with different input is rejected. If creation or update has an uncertain outcome, the same ID stops with `uncertain_draft`. Inspect the receipt and Outlook Drafts before choosing further action. A missing response is not proof that nothing happened.

Check the verified draft's To/CC, subject and content. Recipients can differ from expectations when the source has Reply-To or distribution lists; report actual returned recipients. **Human sends in Outlook.** Even if a token has broader authority, the CLI has no send command.
