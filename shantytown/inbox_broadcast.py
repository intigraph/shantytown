"""Explicit, replayable durable fan-out; never claims live pane submission."""
from __future__ import annotations

from copy import copy
import json

from .attribution import attribute
from .inbox import MessageTooLong, validate_delivery_key


def command(args):
    # Use the ordinary CLI identity/store readers, not another registry or bus.
    from . import cli
    recipients = getattr(args, 'broadcast_to', [])
    key = getattr(args, 'delivery_key', None)
    try:
        validate_delivery_key(key)
        if not 1 <= len(recipients) <= 64 or len(set(recipients)) != len(recipients):
            raise ValueError('broadcast needs 1..64 distinct --to recipients')
        if not args.message or args.count or args.read or args.read_id:
            raise ValueError('broadcast needs a message and cannot read/ack inboxes')
        panes = cli._panes(args)
        sender, verified = cli._verified_sender(args, panes)
        if not verified:
            raise ValueError('message sender identity could not be verified')
        # Resolve EVERY recipient before persisting any. Unknown identity is
        # never a reason to send a partial broadcast to guessed names.
        for name in recipients:
            selected = copy(args)
            selected.agent = name
            card = cli._message_recipient(selected)
            if card.name != name:
                raise ValueError('broadcast needs exact recipient names')
        body = attribute(' '.join(args.message), sender)
    except (ValueError, LookupError) as error:
        print(f'  refused: {error}')
        return cli.REFUSED
    except Exception as error:
        print(f'  could not tell: broadcast preflight {type(error).__name__}; nothing sent')
        return cli.CANNOT_TELL
    if args.dry_run:
        result = {'schema':'inbox-broadcast/v1', 'key':key, 'writes':0,
                  'live_nudges':0, 'recipients':recipients}
        print(json.dumps(result, sort_keys=True))
        return cli.OK
    try:
        box = cli._inbox(args, default='beads')
        deliver = getattr(box, 'deliver_once')
    except Exception as error:
        print(f'  could not tell: stable broadcast backend {type(error).__name__}; nothing sent')
        return cli.CANNOT_TELL
    # Flush the operation key BEFORE the first write so interrupted human runs
    # can resume this same operation. --json leaves stdout as one receipt object.
    import sys
    print(f'  durable broadcast key={key}; no live nudges', file=sys.stderr, flush=True)
    receipts = []
    for name in recipients:
        row = {'recipient':name, 'id':None}
        try:
            message = deliver(name, body, key, frm=sender)
            if message.to != name or message.body != body or not message.id:
                raise RuntimeError('broadcast receipt identity UNKNOWN')
            row.update(id=message.id, delivery='persisted')
        except (ValueError, MessageTooLong) as error:
            row.update(delivery='refused', error=type(error).__name__)
        except Exception as error:
            # A timeout may have committed. No resend, new key, live nudge or
            # fallback store. Continue the independent recipients and report it.
            row.update(delivery='UNKNOWN', error=type(error).__name__)
        receipts.append(row)
    result = {'schema':'inbox-broadcast/v1', 'key':key, 'live_nudges':0,
              'receipts':receipts}
    if getattr(args, 'json', False):
        print(json.dumps(result, sort_keys=True))
    else:
        for row in receipts:
            print(f"  {row['recipient']}: {row['delivery']} {row['id'] or '-'}")
    return cli.OK if all(r['delivery'] == 'persisted' for r in receipts) else cli.CANNOT_TELL
