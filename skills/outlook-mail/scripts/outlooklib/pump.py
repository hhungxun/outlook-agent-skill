"""Paired, loopback-only passive OWA session bridge. No browser-security overrides."""
import base64
import hmac
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from .client import Client, MailError
from .storage import read_json, state_dir, write_json, write_text_private


SETTINGS = 'pump.json'
SERVICE = 'outlook-mail-pump.service'


def prepare(account, port=8769, start=False, open_browser=False):
    if not 1024 <= port <= 65535 or '@' not in account or any(c.isspace() for c in account):
        raise ValueError('Use a mailbox email address and a non-privileged loopback port')
    home = state_dir()
    path = home / SETTINGS
    if path.exists():
        config = read_json(path)
        if config['account'] != account.casefold():
            raise ValueError('Pump is paired to a different account; disconnect it explicitly first')
    else:
        config = {'account': account.casefold(), 'pairing': secrets.token_urlsafe(32)}
    config.update(port=port, install_nonce=secrets.token_urlsafe(32), install_until=time.time() + 900)
    write_json(path, config)
    script = Path(__file__).resolve().parents[1] / 'owa-pump.template.js'
    source = script.read_text(encoding='utf-8').replace('__ENDPOINT_JSON__', json.dumps(f'http://127.0.0.1:{port}/token'))
    source = source.replace('__PAIRING_JSON__', json.dumps(config['pairing']))
    write_text_private(home / 'outlook-mail-pump.user.js', source)
    started = False
    if start:
        install_service()
        started = True
    url = f"http://127.0.0.1:{port}/install/{config['install_nonce']}/outlook-mail-pump.user.js"
    if open_browser:
        if not started:
            raise ValueError('--open requires --start so the installer is actually being served')
        import webbrowser
        webbrowser.open(url)
    return {'setup': True, 'account': account.casefold(), 'backend': 'outlook-rest', 'experimental': True,
            'service_started': started, 'install_url': url, 'install_expires_minutes': 15,
            'next': 'Install Tampermonkey if absent, open install_url in the Outlook browser, approve this generated userscript, then reload Outlook. Never share this installation link.'}


def install_service():
    if sys.platform != 'linux' or not shutil.which('systemctl'):
        raise MailError('service_unavailable', 'Automatic startup currently supports Linux systemd user services only. Run pump serve in a local terminal on other systems.')
    directory = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'systemd/user'
    directory.mkdir(parents=True, exist_ok=True)
    unit = directory / SERVICE
    marker = '# Managed by outlook-agent-skill\n'
    if unit.exists() and (unit.is_symlink() or not unit.read_text(encoding='utf-8').startswith(marker)):
        raise ValueError('A foreign service with this name exists; refusing to replace it')
    # systemd quoted strings, not shell commands. Escape systemd specifiers, quotes and dollars.
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$').replace('\n', '\\n') + '"'
    run = Path(__file__).resolve().parents[1] / 'run.py'
    content = (marker + '[Unit]\nDescription=Private Outlook Mail session bridge\n'
               '[Service]\nType=simple\nExecStart=' + quote(sys.executable) + ' ' + quote(run) + ' pump serve\n'
               'Environment=' + quote('OUTLOOK_MAIL_HOME=' + str(state_dir())) + '\n'
               'Restart=on-failure\nRestartSec=3\nUMask=0077\nNoNewPrivileges=true\n'
               '[Install]\nWantedBy=default.target\n')
    write_text_private(unit, content)
    for args in (['daemon-reload'], ['enable', SERVICE], ['restart', SERVICE], ['is-active', '--quiet', SERVICE]):
        result = subprocess.run(['systemctl', '--user', *args], capture_output=True, timeout=20)
        if result.returncode:
            raise MailError('service_failed', 'User service setup failed. Inspect systemctl --user status outlook-mail-pump; no credentials were logged.')


def handler_class(home, transport=None):
    home = Path(home)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # In particular: never log the installation nonce or bearer tokens.

        def reply(self, status, data=b'', content_type='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def host_ok(self):
            expected = f'127.0.0.1:{self.server.server_address[1]}'
            return self.headers.get('Host') == expected

        def do_GET(self):
            settings = read_json(home / SETTINGS)
            expected = '/install/' + settings['install_nonce'] + '/outlook-mail-pump.user.js'
            if not self.host_ok() or not hmac.compare_digest(self.path.encode('utf-8'), expected.encode('utf-8')) or time.time() > settings['install_until']:
                self.reply(404)
                return
            self.reply(200, (home / 'outlook-mail-pump.user.js').read_bytes(), 'application/javascript; charset=utf-8')

        def do_OPTIONS(self):
            self.reply(403)  # Page-context requests are not an installation path; no wildcard CORS.

        def do_POST(self):
            settings = read_json(home / SETTINGS)
            provided = self.headers.get('X-Outlook-Pairing', '')
            if (not self.host_ok() or self.path not in ('/token', '/shutdown') or
                    not hmac.compare_digest(provided.encode('utf-8'), settings['pairing'].encode('utf-8'))):
                self.reply(403)
                return
            if self.path == '/shutdown':
                import threading
                self.reply(200, b'{"stopping":true}')
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 100 <= length <= 32768 or self.headers.get('Transfer-Encoding'):
                    self.reply(413)
                    return
                token = self.rfile.read(length).decode('ascii').strip()
                if '\n' in token or '\r' in token:
                    raise ValueError('Malformed token')
                part = token.split('.')[1]
                claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
                if (claims.get('aud') != 'https://outlook.office.com' or
                        'Mail.ReadWrite' not in str(claims.get('scp', '')).split() or
                        not isinstance(claims.get('exp'), (int, float)) or claims['exp'] < time.time() + 60):
                    raise ValueError('Wrong token audience/scope/expiry')
                # The claims above are only screening. The Microsoft API verifies the candidate
                # and returns the actual account BEFORE anything overwrites a working token.
                Client(token, 'outlook-rest', transport).check_account(settings['account'])
                token_path = home / 'session-token'
                write_text_private(token_path, token)
                write_json(home / 'config.json', {'backend': 'outlook-rest', 'account': settings['account'],
                           'mode': 'token-file', 'token_file': str(token_path)})
                write_json(home / 'pump-status.json', {'last_accepted_utc_seconds': time.time(), 'state': 'connected'})
                self.reply(200, b'{"accepted":true}')
            except (ValueError, IndexError, TypeError, UnicodeError, MailError):
                self.reply(401, b'{"accepted":false}')
            except OSError:
                self.reply(500, b'{"accepted":false}')

    return Handler


def serve():
    home = state_dir()
    settings = read_json(home / SETTINGS)
    server = HTTPServer(('127.0.0.1', settings['port']), handler_class(home))
    server.timeout = 30
    # Bound reads prevent an authorised or local peer from hanging this single-user helper indefinitely.
    original_get_request = server.get_request
    def get_request():
        sock, address = original_get_request()
        sock.settimeout(15)
        return sock, address
    server.get_request = get_request
    try:
        server.serve_forever()
    finally:
        server.server_close()


def status():
    home = state_dir()
    if not (home / SETTINGS).exists():
        return {'paired': False}
    settings = read_json(home / SETTINGS)
    health = read_json(home / 'pump-status.json') if (home / 'pump-status.json').exists() else {}
    return {'paired': True, 'account': settings['account'], 'port': settings['port'],
            'last_accepted_utc_seconds': health.get('last_accepted_utc_seconds'),
            'note': 'Last accepted token is not proof that the helper is currently running; use doctor to verify mailbox access.'}


def stop():
    # Remove only this tool's owned service/bridge state, not third-party token sources or mailbox data.
    if sys.platform == 'linux' and shutil.which('systemctl'):
        unit = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'systemd/user' / SERVICE
        if unit.exists() and not unit.is_symlink() and unit.read_text(encoding='utf-8').startswith('# Managed by outlook-agent-skill\n'):
            result = subprocess.run(['systemctl', '--user', 'disable', '--now', SERVICE], capture_output=True, timeout=20)
            if result.returncode:
                raise MailError('service_failed', 'Could not stop the owned pump service; inspect it before removing state.')
            unit.unlink()
            subprocess.run(['systemctl', '--user', 'daemon-reload'], capture_output=True, timeout=20, check=True)
    home = state_dir()
    settings_path = home / SETTINGS
    if settings_path.exists():
        from urllib import request, error
        from .client import NoRedirect
        settings = read_json(settings_path)
        req = request.Request(f"http://127.0.0.1:{settings['port']}/shutdown", data=b'',
                              headers={'X-Outlook-Pairing': settings['pairing']}, method='POST')
        try:
            opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
            with opener.open(req, timeout=5) as response:
                if response.status != 200 or response.read(100) != b'{"stopping":true}':
                    raise MailError('service_failed', 'Unexpected helper response; pairing state retained for inspection.')
        except error.HTTPError as exc:
            exc.close()
            raise MailError('service_failed', 'Helper refused shutdown; pairing state retained for inspection.') from None
        except error.URLError as exc:
            import errno
            if not isinstance(exc.reason, OSError) or exc.reason.errno != errno.ECONNREFUSED:
                raise MailError('service_failed', 'Could not confirm helper shutdown; pairing state retained for inspection.') from None
        except TimeoutError:
            raise MailError('service_failed', 'Helper shutdown timed out; pairing state retained for inspection.') from None
    token = home / 'session-token'
    config_path = home / 'config.json'
    if config_path.exists():
        config = read_json(config_path)
        if config.get('token_file') == str(token):
            config_path.unlink()
    for name in (SETTINGS, 'outlook-mail-pump.user.js', 'pump-status.json', 'session-token'):
        (home / name).unlink(missing_ok=True)
    return {'pump_removed': True, 'next': 'Remove the Outlook Mail userscript in Tampermonkey. Existing separate token sources/mail/journals were not deleted.'}
