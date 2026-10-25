"""Download an explicitly selected file attachment without trusting its filename."""
import base64
import binascii
import os
import re
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

MAX_ATTACHMENT = 20 * 1024 * 1024


def attachments(client, message_id):
    return client.pages('me/messages/' + quote(message_id, safe='') + '/attachments', {'$top': 100}, limit=1000)


def download(client, message_id, attachment_id, output):
    item = client.call('GET', 'me/messages/' + quote(message_id, safe='') + '/attachments/' + quote(attachment_id, safe=''))
    if not item.get('@odata.type', '').lower().endswith('fileattachment'):
        raise ValueError('Only file attachments are supported; reference/item attachments are not downloaded')
    encoded = item.get('contentBytes', '')
    if not isinstance(encoded, str) or len(encoded) > (MAX_ATTACHMENT + 2) * 4 // 3 + 4:
        raise ValueError('Attachment exceeds size limit')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('Invalid attachment encoding') from None
    if not data or len(data) > MAX_ATTACHMENT:
        raise ValueError('Attachment is empty or exceeds the 20 MiB limit')
    name = PureWindowsPath(str(item.get('name', 'attachment'))).name
    name = re.sub(r'[^\w.\-]', '_', Path(name).name).lstrip('.')[:160] or 'attachment'
    if name.lower().endswith('.pdf') and not data.startswith(b'%PDF-'):
        raise ValueError('Attachment named PDF does not have a PDF signature')
    directory = Path(output).expanduser().absolute()
    if directory.is_symlink():
        raise ValueError('Output directory cannot be a symlink')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / name
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {'path': str(target), 'bytes': len(data), 'attachment_id': attachment_id}
