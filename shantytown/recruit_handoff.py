"""Protected signed-request handoff to existing launch admission; activation gated.

The controller CLI can prepare an explicitly requested durable observation.
There is no execution callback, configuration switch or live activation. The resulting plan is an observation, never a lease
that can skip the controller's existing launch gates.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from .actor_identity import IdentityError
from . import ephemeral, job_launch, quiet_time, recruit_controller, recruit_request, recruiter
from . import window
from .recruit_store import Store
from .protocols import Agent


def _lease(body, clock):
    if not body['issued_at'] <= int(clock()) < body['expires_at']:
        raise IdentityError('recruitment lease expired at launch admission')



def _records(root):
    # Existing records() skips unreadable entries. An automated handoff cannot
    # interpret that as spare capacity or an unused protected UID.
    paths = list(ephemeral.ledger_dir(root).glob('eph-*.json'))
    if len(paths) > 1024:
        raise IdentityError('controller job inventory exceeds bound')
    rows = ephemeral.records(root)
    if ({p.stem for p in paths} != {r.get('name') for r in rows}
            or any(r.get('state') not in (ephemeral.LAUNCHING, ephemeral.LIVE,
                                         ephemeral.ENDING, ephemeral.DONE) for r in rows)):
        raise IdentityError('controller job inventory incomplete')
    return rows


def prepare(envelope, *, root, host, policy, actor, inside, role_of,
            administrator, unattended, native_binding, gh, quipu, governor,
            clock=time.time):
    """Consume durable state, then enter the existing planner/UID/gate interfaces.

    governor is the existing controller's _spawn_governor_refusal adapter,
    receiving a worker Agent; it must return an empty string only on success.
    No adapter comes from the signed payload. Preparation does not reserve a
    runtime cap or prove a native UID drop, and never creates a job/card/pane.
    """
    recruit_controller.controller_authority(policy=policy, actor=actor, inside=inside,
                                             role_of=role_of)
    pin = recruit_request.load_controller_binding()
    if (pin.root != str(Path(root).resolve()) or pin.host != host
            or pin.host != recruit_controller.socket.gethostname()
            or pin.principal == actor or pin.uid == os.geteuid()):
        raise IdentityError('handoff controller differs from protected binding')
    with Store(pin) as ledger:
        body = recruit_controller.admitted_body(
            envelope, policy=policy, actor=actor, inside=inside, role_of=role_of,
            root=root, host=host, ledger=ledger, native_binding=native_binding,
            admit=lambda request: recruiter.cli_admit(request, policy=policy, gh=gh,
                                                       quipu=quipu, binding=native_binding),
            clock=clock)
        if body['verb'] != 'launch':
            ledger.record(body['nonce'], 'refused', 'handoff-verb')
            raise IdentityError('launch handoff accepts review launch only')
        operation = ledger.claim(body)
        try:
            _lease(body, clock)
            if (unattended is not True or not policy.unattended_uid_ready
                    or not policy.require_verified_identity):
                raise IdentityError('handoff requires protected unattended job identity')
            request = ephemeral.Request(job='review', item=body['item'], repo=body['repo'],
                                        pr=body['pr'], head=body['head'])
            # Use the same lock and planner as normal spawn. Prepared receipts
            # cannot spend capacity later: actual launch must re-enter this path.
            with ephemeral.lock(root):
                quiet = quiet_time.read(Path(root))
                if (quiet.held or quiet.state == 'unknown'
                        or any(status.state == 'unknown' for _, status in quiet.entries)
                        or window.active(Path(root)) is not None):
                    raise IdentityError('controller launch window is held or unknown')
                selected, digest = job_launch.select(
                    request, root=root, harness=ephemeral.harness_for(request, policy),
                    used={r['name'] for r in _records(root)}, native_probe=False)
                if (type(selected['uid']) is not int or selected['uid'] < 10000
                        or selected['uid'] in (pin.uid, os.geteuid())
                        or not re.fullmatch('eph-review-[0-9a-f]{6}', selected['principal'])
                        or not re.fullmatch('[0-9a-f]{64}', digest)):
                    raise IdentityError('recruiter, controller and review job identities must differ')
                plan = ephemeral.plan(request, root=root, policy=policy, actor=actor,
                                      administrator=administrator, host=host, now=clock(),
                                      role_of=role_of, name=selected['principal'])
                plan['uid_binding'] = {'uid': selected['uid'], 'sha256': digest}
                plan['recruiter'] = {key: body[key] for key in
                                     ('principal', 'uid', 'host', 'item', 'repo', 'pr', 'head')}
                plan['recruiter']['binding'] = 'chaski.github.work-request/v1'
                agent = Agent(name=plan['name'], role='worker', roles=('worker', 'first'),
                              harness=plan['harness'], host=host, reports_to=administrator)
                if governor(agent) != '':
                    raise IdentityError('controller governor did not admit the review')
                # The gates may read remote state; expiry/custody must still
                # match immediately before recording the prepared observation.
                recruiter.check_binding(request, native_binding(request.item))
                _lease(body, clock)
                # An independently read protected capability is not a lease
                # either: re-select and require the exact same unused manifest.
                final = job_launch.select(request, root=root, harness=plan['harness'],
                                          used={r['name'] for r in _records(root)},
                                          native_probe=False)
                if final != (selected, digest):
                    raise IdentityError('protected launch capability changed during admission')
                _lease(body, clock)
                plan_digest = hashlib.sha256(json.dumps(plan, sort_keys=True,
                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            ledger.finish(operation, prepared=True, plan_digest=plan_digest)
        except BaseException:
            # A killed process can leave claimed state; neither it nor a refused
            # plan is replayed automatically. All records survive rollback.
            ledger.finish(operation)
            ledger.record(body['nonce'], 'refused', 'launch-gates')
            raise
        return {'schema': 'shantytown.recruitment-handoff/v1', 'operation': operation,
                'plan_sha256': plan_digest, 'name': plan['name'], 'head': body['head'],
                'state': 'prepared', 'nonce_durable': True,
                'live': False, 'execution': 'refused', 'activation': 'gated'}


def cli_prepare(a, **context):
    """Explicit controller preparation: spends durable state but never launches.

    No input is read until selectors and independent authority are checked.
    A dry run here qualifies admission only; its durable audit/nonce is real.
    """
    import sys
    try:
        if (not a.dry_run or getattr(a, 'recruiter', False)
                or any(getattr(a, key, None) is not None for key in
                       ('job', 'item', 'pr_repo', 'pr', 'head', 'checkout', 'harness',
                        'evidence', 'verdict'))):
            raise IdentityError('durable preparation requires only --recruitment-prepare --dry-run')
        recruit_controller.controller_authority(
            policy=context['policy'], actor=context['actor'], inside=context['inside'],
            role_of=context['role_of'])
        receipt = prepare(recruit_controller.read_input(), root=a.root, **context)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except Exception as error:
        print('  refused: controller durable preparation unproved (' +
              type(error).__name__ + ')', file=sys.stderr)
        return 1
