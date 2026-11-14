"""Read late Codex consumption proof without typing or changing custody."""
import hashlib
import math
from pathlib import Path
import re

from .claude_submission import CAP, _at, _decode, _json, _open, _uuid


def native_proof(lines, text, session, created):
    """An exact UserMessage in one started turn; quotes and queues do not count."""
    starts, messages = {}, []
    for line in lines:
        try:
            row = _decode(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get('type') != 'event_msg':
            continue
        at = _at(row.get('timestamp'), created)
        payload = row.get('payload')
        if at is None or not isinstance(payload, dict):
            continue
        turn = payload.get('turn_id')
        if not _uuid(turn):
            continue
        if payload.get('type') == 'task_started':
            if payload.get('thread_id', session) != session:
                continue
            starts.setdefault(turn, []).append(at)
        elif payload.get('type') == 'item_completed':
            if payload.get('thread_id') != session:
                continue
            item = payload.get('item')
            if not isinstance(item, dict) or item.get('type') != 'UserMessage':
                continue
            content = item.get('content')
            if (not isinstance(content, list) or len(content) != 1
                    or not isinstance(content[0], dict)
                    or content[0].get('type') != 'text'
                    or content[0].get('text') != text):
                continue
            messages.append((turn, at))
    proved = [(turn, at) for turn, at in messages
              if len(starts.get(turn, [])) == 1 and starts[turn][0] <= at]
    if len(proved) != 1:
        return None
    turn, at = proved[0]
    return dict(kind='codex-native-user', session=session, turn=turn, at=at)


def observe(root, worker, text, created, settings):
    """Bind the owned rollout to live settings, current stats and workspace."""
    try:
        if (not root or not settings or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', worker)
                or type(created) not in (float, int) or not math.isfinite(created)
                or created <= 0):
            return None
        from .files import FilesRegistry
        from . import session_budget
        card = FilesRegistry(Path(root) / 'crew').get(worker)
        context_path = Path(root) / 'context_budget' / (worker + '.json')
        context, before = _json(context_path)
        payload = context.get('payload')
        if not isinstance(payload, dict) or not card or not card.workspace:
            return None
        session = payload.get('session_id')
        if not _uuid(session) or session_budget.current_session(Path(root), worker) != session:
            return None
        path = Path(payload.get('transcript_path', ''))
        sessions = Path(settings).parent / 'sessions'
        relative = path.relative_to(sessions)
        if (len(relative.parts) != 4 or not all(p.isdecimal() for p in relative.parts[:3])
                or not re.fullmatch(r'rollout-[A-Za-z0-9T_.:-]+-' + re.escape(session) + r'\.jsonl', path.name)):
            return None
        with _open(path) as stream:
            header = _decode(stream.readline(65537))
            meta = header.get('payload') if isinstance(header, dict) else None
            if (not isinstance(header, dict) or header.get('type') != 'session_meta' or not isinstance(meta, dict)
                    or meta.get('id') != session or meta.get('cwd') != card.workspace):
                return None
            stream.seek(0, 2)
            start = max(0, stream.tell() - CAP)
            stream.seek(start)
            lines = stream.read(CAP).splitlines()
        if start:
            lines = lines[1:]
            # A bounded tail must cover preparation, not hide an earlier
            # matching consumption and turn an ambiguous body into proof.
            if not lines:
                return None
            first = _decode(lines[0])
            stamp = _at(first.get('timestamp'), 0) if isinstance(first, dict) else None
            if stamp is None or stamp > created:
                return None
        proof = native_proof(lines, text, session, created)
        if (_json(context_path)[1] != before
                or session_budget.current_session(Path(root), worker) != session):
            return None
        if proof:
            proof['body_sha256'] = hashlib.sha256(text.encode()).hexdigest()
        return proof
    except (OSError, ValueError, LookupError, TypeError):
        return None
