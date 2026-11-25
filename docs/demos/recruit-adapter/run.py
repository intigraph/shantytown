"""Small source-entrypoint demonstration; all enrollment/readiness/transport fixture-only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

source=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(source))
if importlib.util.find_spec('shantytown.recruit_adapter') is None:
    print('BEFORE: no source entrypoint for verified wake -> native custody -> signed handoff')
    raise SystemExit(0)
from shantytown import recruit_adapter as module, recruiter, recruit_request as rr
from shantytown.actor_identity import IdentityError

with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);calls=[]
    custody=dict(schema='chaski.github.work-request/v1',kind='review',repo='intigraph/widget',revision='a'*40,facts={'pr':42})
    class Tracker:
        def get(self,item):
            calls.append('native-item')
            return SimpleNamespace(id=item,description=json.dumps(custody))
    policy=SimpleNamespace(recruitment_launch_ready=False)
    pin=rr.Binding('fixture-requester',10001,'fixture-host',('intigraph/widget',),b'x'*32,str(root))
    scope=recruiter.Scope(pin.principal,pin.uid,pin.root,pin.host,pin.repos,('review',))
    def admit(req,**options):
        recruiter.check_binding(req,options['binding'](req.item));calls.append('fixture-readiness')
    def sign(body,*_):
        calls.append('fixture-sign');return {'body':body,'signature':'0'*128}
    def exchange(envelope,**_):
        calls.append('fixture-controller')
        return dict(state='launched',live=True,head=envelope['body']['head'],name='eph-review-abcdef',operation=hashlib.sha256(rr.message(envelope['body'])).hexdigest())
    adapter=module.ReviewAdapter(root=root,host=pin.host,policy=policy,tracker=Tracker(),items={('intigraph/widget',42):'task-1'},candidate=lambda **kw:SimpleNamespace(**kw),gh=None,quipu=None,private_key=root/'unused',clock=lambda:110)
    event={'repository':{'full_name':'intigraph/widget'},'pull_request':{'number':42,'head':{'sha':'a'*40}}}
    try:adapter.resolve_ready('pull_request',event)
    except IdentityError as error:print('OFF:',str(error),'; IO calls=',len(calls))
    assert not calls
    policy.recruitment_launch_ready=True  # isolated object, never production configuration
    with patch.object(recruiter,'load',return_value=scope),patch.object(rr,'load_controller_binding',return_value=pin),patch.object(module,'_caller_uid',return_value=10001),patch.object(recruiter.socket,'gethostname',return_value=pin.host),patch.object(recruiter,'cli_admit',side_effect=admit),patch.object(module,'sign_request',side_effect=sign),patch.object(module.recruit_endpoint,'exchange',side_effect=exchange):
        candidate=adapter.resolve_ready('pull_request',event);adapter.admit(candidate)
        print('FIXTURE:',json.loads(adapter.spawn(candidate))['state'],'; stages=',','.join(calls))
        calls.clear();custody['revision']='b'*40
        try:adapter.resolve_ready('pull_request',event)
        except IdentityError as error:print('MISMATCH:',str(error),'; stages=',','.join(calls))
        assert calls==['native-item']
print('No production key, HTTP call, listener, sudo, configuration change or job. Fixture receipt is not live acceptance.')
