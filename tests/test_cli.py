import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/outlook-mail/scripts'
sys.path.insert(0, str(SCRIPTS))
from outlook_mail import main


class FakeMailbox:
    """External HTTP boundary only: deterministic, synthetic Microsoft mailbox."""
    def __init__(self):
        self.messages = {
            'one': {'id': 'one', 'subject': 'Seminar', 'parentFolderId': 'inbox', 'isRead': False,
                    'isDraft': False, 'receivedDateTime': '2026-01-02T10:00:00Z',
                    'internetMessageId': '<one@example.test>', 'from': {'emailAddress': {'address': 'speaker@example.test'}},
                    'body': {'contentType': 'text', 'content': 'A synthetic invitation.'}},
            'two': {'id': 'two', 'subject': 'Library notice', 'parentFolderId': 'inbox', 'isRead': True,
                    'isDraft': False, 'receivedDateTime': '2026-01-01T10:00:00Z',
                    'internetMessageId': '<two@example.test>', 'from': {'emailAddress': {'address': 'library@example.test'}}},
        }
        self.folders = {'inbox': 'Inbox', 'drafts': 'Drafts', 'sentitems': 'Sent Items'}
        self.moves = 0
        self.calls = []
        self.fail_after_move = False
        self.next_link = None

    def __call__(self, method, url, token, payload=None):
        from urllib.parse import urlsplit, parse_qs, unquote
        self.calls.append((method, url, payload))
        u = urlsplit(url)
        path = unquote(u.path.removeprefix('/v1.0/')).strip('/')
        query = parse_qs(u.query)
        if path == 'me':
            return {'id': 'account', 'mail': 'owner@example.test', 'userPrincipalName': 'owner@example.test'}
        if path == 'me/mailFolders' and method == 'GET':
            return {'value': [{'id': i, 'displayName': n} for i, n in self.folders.items()]}
        if path == 'me/mailFolders' and method == 'POST':
            fid = 'folder-' + str(len(self.folders))
            self.folders[fid] = payload['displayName']
            return {'id': fid, 'displayName': payload['displayName']}
        parts = path.split('/')
        if len(parts) >= 4 and parts[:2] == ['me', 'mailFolders'] and parts[3] == 'messages':
            messages = [m for m in self.messages.values() if m['parentFolderId'] == parts[2]]
            if '$filter' in query:
                # Only external fake: implement exact InternetMessageId lookup used in recovery.
                f = query['$filter'][0]
                if f.startswith('internetMessageId eq '):
                    wanted = f[len('internetMessageId eq '):].strip("'").replace("''", "'")
                    messages = [m for m in messages if m.get('internetMessageId') == wanted]
            if '$search' in query:
                q = query['$search'][0].strip('"').lower()
                messages = [m for m in messages if q in m['subject'].lower()]
            if 'page' in query:
                return {'value': copy.deepcopy(messages[1:])}
            result = {'value': copy.deepcopy(messages[:1])}
            if len(messages) > 1:
                result['@odata.nextLink'] = self.next_link or url + ('&' if '?' in url else '?') + 'page=2'
            return result
        if path == 'me/messages' and method == 'POST':
            m = dict(payload, id='draft-new', isDraft=True, parentFolderId='drafts', isRead=True)
            self.messages[m['id']] = m
            return copy.deepcopy(m)
        if len(parts) >= 3 and parts[:2] == ['me', 'messages']:
            mid = parts[2]
            if mid not in self.messages:
                from outlooklib.client import MailError
                raise MailError('not_found', 'Message not found', status=404)
            m = self.messages[mid]
            action = parts[3] if len(parts) > 3 else None
            if action == 'move':
                self.moves += 1
                moved = copy.deepcopy(m)
                moved.update(id=mid + '-moved', parentFolderId=payload['destinationId'])
                del self.messages[mid]
                self.messages[moved['id']] = moved
                if self.fail_after_move:
                    self.fail_after_move = False
                    from outlooklib.client import MailError
                    raise MailError('network_error', 'Response lost; outcome unknown')
                return copy.deepcopy(moved)
            if action in ('createReply', 'createReplyAll'):
                draft = dict(m, id='reply-new', parentFolderId='drafts', isDraft=True,
                             body={'contentType': 'text', 'content': 'Quoted original'},
                             toRecipients=[{'emailAddress': {'address': 'speaker@example.test'}}])
                self.messages['reply-new'] = draft
                return copy.deepcopy(draft)
            if action == 'attachments':
                if len(parts) == 4:
                    return {'value': [{'id': 'att', 'name': '../paper.pdf', 'size': 8, '@odata.type': '#microsoft.graph.fileAttachment'}]}
                return {'id': 'att', 'name': '../paper.pdf', 'size': 8, '@odata.type': '#microsoft.graph.fileAttachment',
                        'contentBytes': 'JVBERi0xLjQ='}
            if method == 'PATCH':
                m.update(payload)
                return copy.deepcopy(m)
            return copy.deepcopy(m)
        raise AssertionError(f'Unexpected external request {method} {path}')


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'state'
        self.env = patch.dict(os.environ, {'OUTLOOK_MAIL_HOME': str(self.home)})
        self.env.start()
        self.token = Path(self.tmp.name) / 'access-token'
        self.token.write_text('synthetic-token-not-a-real-credential')
        self.token.chmod(0o600)
        self.api = FakeMailbox()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def call(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(list(argv), transport=self.api)
        return code, json.loads(out.getvalue())

    def connect(self):
        code, result = self.call('connect', '--backend', 'graph', '--token-file', str(self.token), '--account', 'owner@example.test')
        self.assertEqual(code, 0, result)
        return result

    def test_connect_and_list_received_mail_across_pages(self):
        result = self.connect()
        self.assertEqual(result['account'], 'owner@example.test')
        code, result = self.call('list', '--limit', '2')
        self.assertEqual(code, 0, result)
        self.assertEqual([m['subject'] for m in result['messages']], ['Seminar', 'Library notice'])
        self.assertFalse(self.api.messages['one']['isRead'])
        self.assertNotIn(self.token.read_text(), json.dumps(result))

    def test_search_and_read_keep_unread_state(self):
        self.connect()
        code, result = self.call('search', 'Seminar')
        self.assertEqual(code, 0, result)
        self.assertEqual(result['count'], 1)
        code, result = self.call('read', 'one')
        self.assertEqual(result['message']['body']['content'], 'A synthetic invitation.')
        self.assertFalse(self.api.messages['one']['isRead'])

    def test_rejects_wrong_account_without_saving_connection(self):
        code, result = self.call('connect', '--backend', 'graph', '--token-file', str(self.token), '--account', 'someone-else@example.test')
        self.assertEqual(code, 2)
        self.assertEqual(result['error'], 'account_mismatch')
        self.assertFalse((self.home / 'config.json').exists())

    def test_hostile_next_link_is_not_followed(self):
        self.connect()
        self.api.next_link = 'https://attacker.example.test/v1.0/steal'
        code, result = self.call('list', '--limit', '2')
        self.assertEqual(code, 2)
        self.assertEqual(result['error'], 'unsafe_url')
        self.assertFalse(any('attacker' in url for _, url, _ in self.api.calls))

    def test_attachments_download_is_safe_and_does_not_overwrite(self):
        self.connect()
        out = Path(self.tmp.name) / 'papers'
        code, result = self.call('attachments', 'list', 'one')
        self.assertEqual(code, 0, result)
        self.assertEqual(result['attachments'][0]['id'], 'att')
        code, result = self.call('attachments', 'download', 'one', 'att', '--output', str(out))
        self.assertEqual(code, 0, result)
        saved = Path(result['path'])
        self.assertEqual(saved.parent, out)
        self.assertEqual(saved.name, 'paper.pdf')
        self.assertEqual(saved.read_bytes(), b'%PDF-1.4')
        code, result = self.call('attachments', 'download', 'one', 'att', '--output', str(out))
        self.assertEqual(code, 2)
        self.assertEqual(saved.read_bytes(), b'%PDF-1.4')

    def test_new_draft_has_explicit_recipients_and_is_idempotent(self):
        self.connect()
        body = Path(self.tmp.name) / 'reply.txt'
        body.write_text('Thank you for your message.')
        args = ('draft', '--to', 'first@example.test', '--to', 'second@example.test', '--cc', 'copy@example.test',
                '--subject', 'A reply', '--body-file', str(body), '--request-id', 'new-draft-1')
        code, result = self.call(*args)
        self.assertEqual(code, 0, result)
        self.assertTrue(result['draft']['isDraft'])
        self.assertEqual(len(result['draft']['toRecipients']), 2)
        self.assertEqual(result['draft']['ccRecipients'][0]['emailAddress']['address'], 'copy@example.test')
        code, again = self.call(*args)
        self.assertEqual(code, 0, again)
        self.assertEqual(again['draft']['id'], result['draft']['id'])
        self.assertEqual(sum(m == 'POST' and u.endswith('/me/messages') for m, u, _ in self.api.calls), 1)

    def test_reply_is_threaded_and_preserves_quoted_original(self):
        self.connect()
        body = Path(self.tmp.name) / 'reply.txt'
        body.write_text('Thank you, I will check the note.')
        code, result = self.call('reply-draft', 'one', '--body-file', str(body), '--request-id', 'reply-1')
        self.assertEqual(code, 0, result)
        self.assertEqual(result['draft']['id'], 'reply-new')
        self.assertEqual(result['draft']['body']['content'], 'Thank you, I will check the note.\n\nQuoted original')
        self.assertTrue(any(u.endswith('/one/createReply') for _, u, _ in self.api.calls))
        self.assertFalse(any(u.endswith('/createReplyAll') for _, u, _ in self.api.calls))
        self.assertFalse(any('/send' in u for _, u, _ in self.api.calls))

    def test_uncertain_reply_is_not_blindly_created_twice(self):
        from outlooklib.client import MailError
        original = self.api
        def losing_response(method, url, token, payload=None):
            result = original(method, url, token, payload)
            if method == 'POST' and url.endswith('/createReply'):
                raise MailError('network_error', 'Lost response')
            return result
        self.api = losing_response
        self.connect()
        body = Path(self.tmp.name) / 'reply.txt'
        body.write_text('Thanks.')
        args = ('reply-draft', 'one', '--body-file', str(body), '--request-id', 'lost-reply')
        code, result = self.call(*args)
        self.assertEqual(code, 2)
        code, result = self.call(*args)
        self.assertEqual(code, 2)
        self.assertEqual(result['error'], 'uncertain_draft')
        self.assertEqual(sum(u.endswith('/createReply') for _, u, _ in original.calls), 1)

    def test_rest_backend_requires_explicit_experimental_opt_in(self):
        code, result = self.call('connect', '--token-file', str(self.token), '--account', 'owner@example.test', '--backend', 'outlook-rest')
        self.assertEqual(code, 2)
        self.assertFalse((self.home / 'config.json').exists())

    def test_disconnect_does_not_delete_external_credential_source(self):
        self.connect()
        code, result = self.call('disconnect')
        self.assertEqual(code, 0, result)
        self.assertTrue(self.token.exists())
        self.assertFalse((self.home / 'config.json').exists())


if __name__ == '__main__':
    unittest.main()
