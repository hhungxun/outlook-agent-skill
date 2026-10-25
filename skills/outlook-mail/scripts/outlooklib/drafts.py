"""Create only drafts, with private receipts and native reply-thread association."""
import hashlib
import html
import json
import re
from urllib.parse import quote
from .client import MailError
from .storage import mutation_lock, read_json, state_dir, write_json


def recipients(addresses):
    result = []
    for address in addresses:
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+', address):
            raise ValueError('Use one plain email address per recipient flag')
        result.append({'emailAddress': {'address': address}})
    return result


def create(client, account, request_id, text, *, to=None, cc=None, subject=None, source=None, reply_all=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id):
        raise ValueError('Request ID must be 1–100 letters/numbers/underscores/hyphens')
    if not text.strip() or len(text.encode('utf-8')) > 1024 * 1024:
        raise ValueError('Draft body must be non-empty and at most 1 MiB')
    if subject is not None and ('\r' in subject or '\n' in subject or len(subject) > 998):
        raise ValueError('Invalid subject')
    to_recipients, cc_recipients = recipients(to or []), recipients(cc or [])
    if source is None and (not to_recipients or subject is None):
        raise ValueError('New drafts require recipients and a subject')
    inputs = {'account': account, 'backend': client.backend, 'source': source, 'reply_all': reply_all,
              'to': to_recipients, 'cc': cc_recipients, 'subject': subject, 'body': text}
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode('utf-8')).hexdigest()
    path = state_dir() / 'receipts' / (request_id + '.json')
    with mutation_lock():
        if path.exists():
            receipt = read_json(path)
            if receipt['fingerprint'] != digest:
                raise ValueError('Request ID already used for different input/account; choose a new ID')
            if receipt['status'] != 'verified':
                raise MailError('uncertain_draft', 'This request is incomplete/uncertain. Inspect the receipt and Outlook Drafts before retrying; no duplicate was created.')
            draft = client.message(receipt['draft_id'])
            if not draft.get('isDraft'):
                raise MailError('draft_changed', 'The prior draft is no longer a draft; no new message created.')
            return {'draft': draft, 'receipt': str(path), 'reused': True}
        if source:
            original = client.message(source)
            if original.get('isDraft'):
                raise ValueError('Reply source is a draft, not a received message')
        receipt = {'fingerprint': digest, 'account': account, 'backend': client.backend,
                   'request_id': request_id, 'status': 'create_requested'}
        write_json(path, receipt)
        if source:
            action = 'createReplyAll' if reply_all else 'createReply'
            draft = client.call('POST', 'me/messages/' + quote(source, safe='') + '/' + action, {})
        else:
            draft = client.call('POST', 'me/messages', {'subject': subject, 'toRecipients': to_recipients,
                                'ccRecipients': cc_recipients, 'body': {'contentType': 'text', 'content': text}})
        receipt.update(draft_id=draft['id'], status='created')
        write_json(path, receipt)
        if not draft.get('isDraft'):
            raise MailError('invalid_response', 'Creation response did not identify an unsent draft.')
        if source:
            # The actual reply object preserves thread metadata and original quoted content.
            body = draft.get('body') or {}
            content_type = body.get('contentType', 'text').lower()
            original_body = body.get('content', '')
            content = (html.escape(text).replace('\n', '<br>') + '<br><br>' + original_body
                       if content_type == 'html' else text + '\n\n' + original_body)
            receipt['status'] = 'update_requested'
            write_json(path, receipt)
            client.call('PATCH', 'me/messages/' + quote(draft['id'], safe=''),
                        {'body': {'contentType': content_type, 'content': content}})
        verified = client.message(draft['id'])
        if not verified.get('isDraft'):
            raise MailError('verification_failed', 'Created message is not an unsent draft.')
        # Providers may normalise HTML/text, so content presence plus server draft status is the gate.
        verified_body = (verified.get('body') or {}).get('content', '')
        needle = html.escape(text).replace('\n', '<br>') if source and content_type == 'html' else text
        if needle not in verified_body:
            raise MailError('verification_failed', 'Draft body did not match the requested reply; inspect receipt and Drafts.')
        receipt['status'] = 'verified'
        write_json(path, receipt)
        return {'draft': verified, 'receipt': str(path), 'reused': False}
