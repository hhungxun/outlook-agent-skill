import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib import error, request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/outlook-mail/scripts'))
from outlook_mail import main
from outlooklib.client import Client, HttpTransport, MailError, NoRedirect
from outlooklib.pump import handler_class, prepare
from outlooklib.storage import read_json, write_json


class SecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'state'
        self.env = patch.dict(os.environ, {'OUTLOOK_MAIL_HOME': str(self.home)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_private_atomic_state_does_not_change_parent_permissions(self):
        parent = Path(self.tmp.name)
        if os.name == 'posix':
            parent.chmod(0o755)
        p = parent / 'plan.json'
        write_json(p, {'synthetic': True})
        self.assertEqual(read_json(p), {'synthetic': True})
        if os.name == 'posix':
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(parent.stat().st_mode & 0o777, 0o755)

    def test_state_write_refuses_symlink(self):
        if os.name != 'posix':
            self.skipTest('Symlink privileges are platform-dependent')
        p = Path(self.tmp.name) / 'link'
        target = Path(self.tmp.name) / 'target'
        target.write_text('untouched')
        p.symlink_to(target)
        with self.assertRaises(ValueError):
            write_json(p, {'bad': True})
        self.assertEqual(target.read_text(), 'untouched')

    def test_provider_refuses_host_port_scheme_and_prefix_escapes(self):
        client = Client('synthetic')
        for bad in ['http://graph.microsoft.com/v1.0/me', 'https://evil.test/v1.0/me',
                    'https://graph.microsoft.com:444/v1.0/me', 'https://graph.microsoft.com/v1.0evil/me',
                    'https://evil@graph.microsoft.com/v1.0/me', 'https://graph.microsoft.com/v1.0/me#fragment']:
            with self.subTest(url=bad), self.assertRaises(MailError):
                client.safe_url(bad)

    def test_http_errors_are_redacted_and_writes_not_retried(self):
        transport = HttpTransport()
        class Broken:
            calls = 0
            def open(self, *_args, **_kwargs):
                self.calls += 1
                raise error.HTTPError('https://graph.microsoft.com/v1.0/me/messages', 403,
                                      'sensitive-body', {}, io.BytesIO(b'secret-value'))
        broken = Broken()
        with patch('outlooklib.client.request.build_opener', return_value=broken):
            with self.assertRaises(MailError) as caught:
                transport('POST', 'https://graph.microsoft.com/v1.0/me/messages', 'secret-value', {})
        self.assertEqual(broken.calls, 1)
        self.assertNotIn('secret-value', str(caught.exception))
        self.assertEqual(caught.exception.code, 'consent_required')

    def test_redirect_handler_refuses_redirect(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, 'Found', {}, 'https://evil.test'))

    def test_pump_setup_generates_private_paired_userscript_without_browser_changes(self):
        result = prepare('owner@example.test')
        config = read_json(self.home / 'pump.json')
        self.assertIn('/install/', result['install_url'])
        script = (self.home / 'outlook-mail-pump.user.js').read_text()
        self.assertIn(config['pairing'], script)
        self.assertIn('GM_xmlhttpRequest', script)
        self.assertNotIn('?t=', script)
        self.assertNotIn('network.lna', script)
        self.assertNotIn('session-token', json.dumps(result))
        self.assertFalse(result['service_started'])
        if os.name == 'posix':
            self.assertEqual((self.home / 'pump.json').stat().st_mode & 0o777, 0o600)

    def test_pump_http_pairing_identity_and_no_cors(self):
        prepare('owner@example.test')
        settings = read_json(self.home / 'pump.json')
        calls = []
        remote_account = ['owner@example.test']
        def remote(method, url, token, payload=None):
            calls.append(url)
            return {'EmailAddress': remote_account[0]}
        server = HTTPServer(('127.0.0.1', 0), handler_class(self.home, remote))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_address[1])
        claims = {'aud': 'https://outlook.office.com', 'scp': 'Mail.ReadWrite', 'exp': time.time() + 3600}
        part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
        token = 'synthetic.' + part + '.not-a-real-signature'
        def send(pairing, host=None, path='/token'):
            headers = {'X-Outlook-Pairing': pairing}
            if host:
                headers['Host'] = host
            req = request.Request(base + path, data=token.encode(), headers=headers, method='POST')
            try:
                with request.urlopen(req, timeout=5) as response:
                    return response.status, response.headers, response.read()
            except error.HTTPError as exc:
                body = exc.read()
                result = (exc.code, exc.headers, body)
                exc.close()
                return result
        try:
            self.assertEqual(send('wrong')[0], 403)
            self.assertEqual(send(settings['pairing'], 'evil.test')[0], 403)
            self.assertEqual(calls, [])
            code, headers, body = send(settings['pairing'])
            self.assertEqual(code, 200)
            self.assertNotIn('Access-Control-Allow-Origin', headers)
            self.assertEqual((self.home / 'session-token').read_text(), token)
            self.assertEqual(read_json(self.home / 'config.json')['backend'], 'outlook-rest')
            accepted_mtime = (self.home / 'session-token').stat().st_mtime_ns
            remote_account[0] = 'stranger@example.test'
            self.assertEqual(send(settings['pairing'])[0], 401)
            self.assertEqual((self.home / 'session-token').stat().st_mtime_ns, accepted_mtime)
            self.assertEqual(send('non-ascii-\u00e9')[0], 403)
            try:
                request.urlopen(base + '/?t=' + token, timeout=5)
                self.fail('GET token ingestion must be refused')
            except error.HTTPError as exc:
                self.assertEqual(exc.code, 404)
                exc.close()
            install = base + '/install/' + settings['install_nonce'] + '/outlook-mail-pump.user.js'
            with request.urlopen(install, timeout=5) as r:
                self.assertIn(settings['pairing'].encode(), r.read())
            self.assertEqual(send(settings['pairing'], path='/shutdown')[0], 200)
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

    def test_rest_case_normalisation_in_both_directions(self):
        calls = []
        def remote(method, url, token, payload=None):
            calls.append(payload)
            return {'Id': 'draft', 'IsDraft': True, 'ToRecipients': [{'EmailAddress': {'Address': 'x@example.test'}}]}
        client = Client('synthetic', 'outlook-rest', remote)
        draft = client.call('POST', 'me/messages', {'toRecipients': [{'emailAddress': {'address': 'x@example.test'}}]})
        self.assertTrue(draft['isDraft'])
        self.assertEqual(calls[0]['ToRecipients'][0]['EmailAddress']['Address'], 'x@example.test')


if __name__ == '__main__':
    unittest.main()
