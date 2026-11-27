"""Signed controller admission into the existing spawn transaction.

No CLI flag, listener or transport wiring enables this library. The separate
activation gate defaults OFF. A prepared observation is never accepted here.
"""
from __future__ import annotations

from copy import copy, deepcopy
import hashlib
import json
import os
from pathlib import Path
import time

from .actor_identity import IdentityError
from . import ephemeral, job_launch, recruit_controller, recruit_handoff
from . import recruit_request, recruiter
from .recruit_store import Store

_ISSUED = object()


class Admission:
    """In-process context, not a serializable execution receipt or authority."""
    def __init__(self, token, body, pin, context):
        if token is not _ISSUED:
            raise IdentityError('controller admission was not issued')
        self.body, self.pin, self.context = deepcopy(body), pin, dict(context)
        self.name = None
        self.uid_binding = None

    def bind(self, *, root, host, policy, actor, inside, role_of,
             native_binding, gh, quipu):
        """Use the actual spawn controller's freshly loaded identity/adapters."""
        recruit_controller.controller_authority(policy=policy, actor=actor,
                                                inside=inside, role_of=role_of)
        if (not policy.recruitment_launch_ready or not policy.unattended_uid_ready
                or policy.unattended is not True
                or str(Path(root).resolve()) != self.pin.root
                or host != self.pin.host or actor != self.context['actor']):
            raise IdentityError('controller recruitment activation or identity refused')
        self.context.update(root=root, host=host, policy=policy, actor=actor,
                            inside=inside, role_of=role_of, native_binding=native_binding,
                            gh=gh, quipu=quipu)

    def request(self, request):
        expected = ephemeral.Request(job='review', item=self.body['item'],
            repo=self.body['repo'], pr=self.body['pr'], head=self.body['head'])
        if request != expected:
            raise IdentityError('controller spawn request differs from signed request')

    def recheck(self, request, selected, *, existing=False):
        """Called under the ledger lock and again at the existing launch seam."""
        self.request(request)
        ctx = self.context
        recruit_controller.controller_authority(policy=ctx['policy'], actor=ctx['actor'],
                                                inside=ctx['inside'], role_of=ctx['role_of'])
        quiet = recruit_handoff.quiet_time.read(Path(ctx['root']))
        if (quiet.held or quiet.state == 'unknown'
                or getattr(quiet, 'launch_unknown', any(s.state == 'unknown' for _, s in quiet.entries))
                or recruit_handoff.window.active(Path(ctx['root'])) is not None):
            raise IdentityError('controller launch window held or unknown')
        if recruit_request.load_controller_binding() != self.pin:
            raise IdentityError('controller binding changed before launch')
        recruit_handoff._lease(self.body, ctx['clock'])
        recruiter.cli_admit(request, policy=ctx['policy'], gh=ctx['gh'],
                            quipu=ctx['quipu'], binding=ctx['native_binding'])
        recruiter.check_binding(request, ctx['native_binding'](request.item))
        recruit_handoff._lease(self.body, ctx['clock'])
        if selected is None:
            raise IdentityError('controller launch requires a protected job UID')
        spec, digest = selected
        if (spec['uid'] in (self.pin.uid, os.geteuid()) or spec['uid'] < 10000
                or (existing and spec['principal'] != self.name)):
            raise IdentityError('controller, recruiter and job identities must differ')
        rows = recruit_handoff._records(ctx['root'])
        if existing:
            record = next((r for r in rows if r['name'] == self.name), None)
            self.verify_record(record, live=False)
        used = {r['name'] for r in rows if not existing or r['name'] != self.name}
        fresh = job_launch.select(request, root=ctx['root'],
                                 harness=ephemeral.harness_for(request, ctx['policy']),
                                 used=used, native_probe=False)
        if fresh != selected:
            raise IdentityError('protected job capability changed before launch')
        if recruit_request.load_controller_binding() != self.pin:
            raise IdentityError('controller binding changed during launch admission')
        quiet = recruit_handoff.quiet_time.read(Path(ctx['root']))
        if (quiet.held or quiet.state == 'unknown'
                or getattr(quiet, 'launch_unknown', any(s.state == 'unknown' for _, s in quiet.entries))
                or recruit_handoff.window.active(Path(ctx['root'])) is not None):
            raise IdentityError('controller launch window changed during admission')
        recruit_handoff._lease(self.body, ctx['clock'])
        self.name = spec['principal']
        self.uid_binding = {'uid': spec['uid'], 'sha256': digest}

    def attribution(self):
        value = {k: self.body[k] for k in ('principal', 'uid', 'host', 'item', 'repo', 'pr', 'head')}
        return value | {'binding': 'chaski.github.work-request/v1'}

    def verify_record(self, record, *, live):
        if (not isinstance(record, dict) or record.get('name') != self.name
                or record.get('state') != (ephemeral.LIVE if live else ephemeral.LAUNCHING)
                or record.get('job') != 'review' or record.get('recruiter') != self.attribution()
                or record.get('uid_binding') != self.uid_binding
                or any(record.get(k) != self.body[k] for k in ('item', 'repo', 'pr', 'head', 'host'))):
            raise IdentityError('controller launch ledger does not prove this review')


def launch(envelope, *, args, clock=time.time, channel_binding=None, **context):
    """One signed attempt through native spawn; activation remains separate.

    Context and arguments belong to the verified controller, never the sender.
    Refused/unknown attempts retain their nonce and candidate key permanently.
    """
    recruit_controller.controller_authority(policy=context['policy'], actor=context['actor'],
        inside=context['inside'], role_of=context['role_of'])
    if not context['policy'].recruitment_launch_ready:
        raise IdentityError('controller recruitment activation is gated')
    pin = recruit_request.load_controller_binding()
    if channel_binding is not None and pin != channel_binding:
        raise IdentityError('controller binding changed after peer authentication')
    with Store(pin) as ledger:
        body = recruit_controller.admitted_body(envelope, ledger=ledger, clock=clock,
            admit=lambda req: recruiter.cli_admit(req, policy=context['policy'],
                gh=context['gh'], quipu=context['quipu'], binding=context['native_binding']),
            **{k: context[k] for k in ('policy', 'actor', 'inside', 'role_of', 'root', 'host', 'native_binding')})
        if body['verb'] != 'launch':
            ledger.record(body['nonce'], 'refused', 'launch-verb')
            raise IdentityError('controller bridge permits only review launch')
        operation = ledger.claim(body)
        admission = Admission(_ISSUED, body, pin, context | {'clock': clock})
        # Do not inherit a second operation or sender-selected launcher options.
        selectors = ('list', 'report', 'merge', 'reap', 'stop', 'retry', 'recruiter',
                     'recruitment_prepare', 'recruitment_request', 'dry_run',
                     'harness', 'checkout', 'evidence', 'verdict')
        try:
            if any(getattr(args, key, None) for key in selectors):
                raise IdentityError('controller launch selectors refused')
            native = copy(args)
            native.root = Path(context['root'])
            native.ephemeral, native.job = True, 'review'
            native.item, native.pr_repo = body['item'], body['repo']
            native.pr, native.head = body['pr'], body['head']
            from .cli import _cmd_spawn, OK
            result = _cmd_spawn(native, recruitment=admission)
            if result != OK:
                ledger.finish_execution(operation, state='refused')
                return {'state': 'refused', 'operation': operation, 'live': False}
            if admission.name is None or admission.uid_binding is None:
                raise IdentityError('native spawn supplied no bound job identity')
            record = ephemeral.read(context['root'], admission.name)
            admission.verify_record(record, live=True)
            digest = hashlib.sha256(json.dumps(record, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            ledger.finish_execution(operation, state='launched', job_digest=digest)
            return {'state': 'launched', 'operation': operation, 'name': admission.name,
                    'head': body['head'], 'live': True}
        except BaseException:
            # If execution or its response is uncertain, never infer no job and
            # never turn the durable claim back into a pending request.
            ledger.finish_execution(operation, state='unknown')
            raise
