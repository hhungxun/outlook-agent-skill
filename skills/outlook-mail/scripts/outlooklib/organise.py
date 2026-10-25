"""Frozen plans and durable, independently verified move/undo journals."""
import hashlib
import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from .client import MailError
from .storage import mutation_lock, read_json, state_dir, write_json

RESERVED = {'inbox', 'drafts', 'sent', 'sent items', 'sentitems', 'deleted items', 'deleteditems',
            'junk', 'junk email', 'junkemail', 'archive', 'outbox', 'conversation history', 'sync issues', 'rss feeds'}


def topic_name(name):
    if (not isinstance(name, str) or name != name.strip() or not 1 <= len(name) <= 100 or
            re.search(r'[\x00-\x1f/\\]', name) or name.casefold() in RESERVED):
        raise ValueError('Use a clear topic name, not a built-in mailbox folder')
    return name


def now():
    return datetime.now(timezone.utc).isoformat()


def journal_path(plan_id):
    if not re.fullmatch(r'[0-9a-f]{32}', plan_id):
        raise ValueError('Invalid plan ID')
    return state_dir() / 'journals' / (plan_id + '.json')


def make_plan(client, config, folder, limit, output=None):
    messages = client.list_messages(folder, limit)
    if not messages:
        raise ValueError('No messages matched the requested scope')
    rows, skipped = [], []
    for m in messages:
        if m.get('isDraft') or not m.get('internetMessageId'):
            skipped.append({'id': m.get('id'), 'subject': m.get('subject', ''),
                            'reason': 'draft' if m.get('isDraft') else 'missing InternetMessageId'})
            continue
        rows.append({'source_id': m['id'], 'original_folder_id': m['parentFolderId'],
                     'subject': m.get('subject', ''), 'received': m.get('receivedDateTime'),
                     'internet_message_id': m['internetMessageId'], 'original_is_read': m['isRead'], 'topic': None})
    if not rows:
        raise MailError('no_eligible_messages', 'No recoverable non-draft messages matched the scope; no mailbox changes made.')
    if len({r['source_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate source IDs in mailbox snapshot')
    plan_id = uuid.uuid4().hex
    plan = {'schema': 1, 'id': plan_id, 'account': config['account'], 'backend': config['backend'],
            'created_utc': now(), 'scope': folder, 'messages': rows, 'skipped': skipped}
    path = Path(output).expanduser().absolute() if output else state_dir() / 'plans' / (plan_id + '.json')
    if path.exists():
        raise ValueError('Plan output already exists; choose a new path')
    write_json(path, plan)
    return {'plan': str(path), 'count': len(rows), 'messages': rows, 'mutations': 0,
            'requested_limit': limit, 'skipped_count': len(skipped), 'skipped': skipped}


def validate_plan(plan, config, require_topics=False):
    if plan.get('schema') != 1 or plan.get('account') != config['account'] or plan.get('backend') != config['backend']:
        raise ValueError('Plan schema, account or backend does not match this connection')
    journal_path(plan['id'])
    rows = plan['messages']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError('Invalid plan message count')
    if len({r['source_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate plan message IDs')
    for row in rows:
        if not row.get('internet_message_id') or not row.get('original_folder_id'):
            raise ValueError('Missing recovery identity/source folder')
        if row.get('topic') is not None or require_topics:
            topic_name(row.get('topic'))
    return rows


def assign(path, config, topic, ids):
    topic_name(topic)
    with mutation_lock():
        plan = read_json(path)
        rows = validate_plan(plan, config)
        if journal_path(plan['id']).exists():
            raise ValueError('Plan already started; create a new plan instead of changing its assignments')
        wanted = set(ids)
        if not wanted or wanted - {r['source_id'] for r in rows}:
            raise ValueError('Every assigned ID must be in the frozen snapshot')
        for row in rows:
            if row['source_id'] in wanted:
                row['topic'] = topic
        write_json(path, plan)
    return {'plan': str(path), 'assigned': len(wanted), 'topics': dict(Counter(r['topic'] or '(unassigned)' for r in rows))}


def same_message(message, row):
    if (message.get('isDraft') or message.get('subject', '') != row['subject'] or
            message.get('internetMessageId') != row['internet_message_id'] or
            message.get('receivedDateTime') != row['received']):
        raise MailError('conflict', 'Message identity changed; no automatic overwrite is safe.')
    return message


def maybe_message(client, mid):
    try:
        return client.message(mid) if mid else None
    except MailError as exc:
        if exc.status == 404:
            return None
        raise


def locate(client, row, ids, recovery_folder):
    for mid in dict.fromkeys(i for i in ids if i):
        m = maybe_message(client, mid)
        if m is not None:
            return same_message(m, row)
    matches = client.find_moved(recovery_folder, row['internet_message_id'])
    matches = [m for m in matches if m.get('subject', '') == row['subject'] and m.get('receivedDateTime') == row['received']]
    if len(matches) != 1:
        raise MailError('conflict', 'Could not uniquely reconcile a move; inspect the journal and mailbox before retrying.')
    return same_message(matches[0], row)


def ensure_folder(client, name, journal, path):
    item = journal['folders'].get(name)
    if item and item.get('id'):
        return item['id']
    folders = client.pages('me/mailFolders', {'$top': 100}, limit=1000)
    matches = [f for f in folders if f['displayName'].casefold() == name.casefold()]
    if len(matches) > 1:
        raise MailError('conflict', 'Topic folder name is ambiguous; resolve duplicates before applying.')
    if matches:
        fid = matches[0]['id']
        journal['folders'][name] = {'id': fid, 'created': bool(item), 'status': 'available'}
    elif item:
        raise MailError('uncertain_folder', 'Folder creation outcome is unknown; no duplicate was created by this command. Inspect folders and journal.')
    else:
        journal['folders'][name] = {'status': 'create_requested'}
        write_json(path, journal)
        result = client.call('POST', 'me/mailFolders', {'displayName': name})
        fid = result['id']
        journal['folders'][name] = {'id': fid, 'created': True, 'status': 'available'}
    write_json(path, journal)
    return fid


def apply(client, config, plan_path):
    with mutation_lock():
        plan = read_json(plan_path)
        rows = validate_plan(plan, config, require_topics=True)
        path = journal_path(plan['id'])
        digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode('utf-8')).hexdigest()
        if path.exists():
            journal = read_json(path)
            if journal['plan_digest'] != digest or journal['phase'] not in ('apply', 'verified'):
                raise ValueError('Plan changed or already undone; use a fresh plan')
        else:
            journal = {'schema': 1, 'account': config['account'], 'backend': config['backend'], 'plan_id': plan['id'],
                       'plan_digest': digest, 'phase': 'apply', 'started_utc': now(), 'folders': {},
                       'messages': [dict(r, status='pending') for r in rows]}
            write_json(path, journal)
        # Preflight ALL still-pending messages before creating folders or moving anything.
        for row in journal['messages']:
            if row['status'] == 'pending':
                m = same_message(client.message(row['source_id']), row)
                if m['parentFolderId'] != row['original_folder_id']:
                    raise MailError('conflict', 'A source message changed folders since the plan; no pending messages were moved.')
        for row in journal['messages']:
            dest = ensure_folder(client, row['topic'], journal, path)
            if dest == row['original_folder_id']:
                raise ValueError('Topic destination equals original folder; choose a different topic')
            row['destination_id'] = dest
            if row['status'] == 'move_requested':
                m = locate(client, row, [row.get('new_id'), row['source_id']], dest)
                if m['parentFolderId'] == dest:
                    row.update(new_id=m['id'], status='moved')
                    write_json(path, journal)
                elif m['parentFolderId'] != row['original_folder_id']:
                    raise MailError('conflict', 'Uncertain move is no longer in its source or destination.')
            if row['status'] in ('moved', 'verified'):
                m = same_message(client.message(row['new_id']), row)
                if m['parentFolderId'] != dest:
                    raise MailError('conflict', 'A previously moved message was changed by another operation.')
                continue
            m = same_message(client.message(row['source_id']), row)
            if m['parentFolderId'] != row['original_folder_id']:
                raise MailError('conflict', 'Source changed before move.')
            row.update(move_is_read=m['isRead'], status='move_requested')
            write_json(path, journal)
            result = client.move(m['id'], dest)
            row.update(new_id=result['id'], status='moved')
            write_json(path, journal)
            checked = same_message(client.message(result['id']), row)
            if checked['parentFolderId'] != dest or checked['isRead'] != row['move_is_read']:
                raise MailError('verification_failed', 'Move destination/read state did not verify; inspect journal.')
        # Independent final re-read, including entries recovered from an interrupted run.
        for row in journal['messages']:
            m = same_message(client.message(row['new_id']), row)
            if m['parentFolderId'] != row['destination_id']:
                raise MailError('verification_failed', 'Final move verification failed; inspect journal.')
            # Immediate verification checked each new move's read preservation.
            # Later reads by the user are legitimate and must not invalidate resume.
            row['last_verified_is_read'] = m['isRead']
        for row in journal['messages']:
            row['status'] = 'verified'
        journal.update(phase='verified', completed_utc=now())
        write_json(path, journal)
        return {'verified': len(rows), 'journal': str(path), 'folders': dict(Counter(r['topic'] for r in rows))}


def undo(client, config, path):
    with mutation_lock():
        journal = read_json(path)
        if journal.get('schema') != 1 or journal['account'] != config['account'] or journal['backend'] != config['backend']:
            raise ValueError('Journal belongs to a different account/backend or schema')
        active = [r for r in journal['messages'] if r['status'] != 'pending']
        # Preflight all active entries; never overwrite a later user folder change.
        found = []
        for row in active:
            restoring = row['status'] in ('restore_requested', 'restored')
            target = row['original_folder_id'] if restoring else row['destination_id']
            m = locate(client, row, [row.get('restored_id'), row.get('new_id'), row['source_id']], target)
            if m['parentFolderId'] not in (row['original_folder_id'], row['destination_id']):
                raise MailError('conflict', 'A journaled message was moved elsewhere after sorting; undo stopped before new moves.')
            found.append((row, m))
        journal['phase'] = 'undo'
        write_json(path, journal)
        for row, m in found:
            if m['parentFolderId'] == row['original_folder_id']:
                row.update(restored_id=m['id'], status='restored', restore_is_read=m['isRead'])
                write_json(path, journal)
                continue
            # Preserve current, not historical, read status.
            row.update(status='restore_requested', restore_is_read=m['isRead'])
            write_json(path, journal)
            result = client.move(m['id'], row['original_folder_id'])
            row.update(restored_id=result['id'], status='restored')
            write_json(path, journal)
            check = same_message(client.message(row['restored_id']), row)
            if check['parentFolderId'] != row['original_folder_id'] or check['isRead'] != row['restore_is_read']:
                raise MailError('verification_failed', 'Restore did not verify; inspect journal.')
        for row, _ in found:
            m = same_message(client.message(row['restored_id']), row)
            if m['parentFolderId'] != row['original_folder_id']:
                raise MailError('verification_failed', 'Final restore verification failed.')
            row['last_verified_is_read'] = m['isRead']
        journal.update(phase='undone', undone_utc=now())
        write_json(path, journal)
        return {'restored': len(found), 'journal': str(path), 'empty_folders_deleted': False}
