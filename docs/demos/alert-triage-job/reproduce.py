"""Offline synthetic example; no account allocation or live alert access."""
import hashlib
import json
from pathlib import Path
import tempfile

from shantytown import alert_triage_job as job


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    name = 'eph-triage-000001'
    home = '/var/lib/shantytown/agents/crew-' + name
    identity = dict(version=1, principal=name, controller_uid=60000, uid=60001,
                    gid=60001, username='_stjobs_000001', home=home,
                    root='/var/lib/shantytown/job-stores/' + name)
    launch = dict(controller_root='/synthetic/controller', workspace=home+'/workspace',
                  settings=home+'/settings.json', harness='claude',
                  request=dict(job='triage', item='demo-alert', repo=None, pr=None,
                               checkout=None, head=None, request_id=None),
                  argv=['/synthetic/immutable/claude', '-p', job.PROMPT_MARKER],
                  environment={}, review=None)
    alert = dict(version=1, item='demo-alert', fingerprint_kind='escalation-bridge',
                 fingerprint='0123456789ab', onset_utc='2026-11-14T12:00:00Z')
    args = []
    for key, value in [('identity', identity), ('launch', launch), ('input', alert)]:
        path = root/(key+'.json');path.write_bytes(job.encoded(value))
        args.extend(['--'+key,str(path),'--'+key+'-sha256',job.digest(path.read_bytes())])
    print('Synthetic reviewed input: one fingerprint and its original demo-alert item.')
    print('Compile with exact input pins:')
    assert job.main(args+['--output',str(root/'output')]) == 0
    bindings = json.loads((root/'output/bindings.json').read_bytes())
    prompt = bindings[name]['argv'][-1]
    print('Original item:',bindings[name]['request']['item'])
    print('Fingerprint frozen:',alert['fingerprint'] in prompt)
    print('Runtime admitted:',False)
    print('Mutate input after pinning; expect refusal and no output:')
    (root/'input.json').write_bytes(job.encoded(dict(alert,item='different-item')))
    assert job.main(args+['--output',str(root/'rejected')]) == 1
    assert not (root/'rejected').exists()
    print('No rejected artifacts; no launch, network, accounts or credentials used.')
