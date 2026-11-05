"""Real temporary Seeds SDK state; the assignment callback is synthetic."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from shantytown.sd import SdTracker
from shantytown.scheduled_seed import NativeSeedPort, SeedLedger, SeedRequest, SeedUnknown


def request(slot):
    binding = dict(job='urn:fixture:job',revision='revision1',host='urn:fixture:host',
        manifest_sha256='a'*64,agent='fixture-agent',workflow='urn:fixture:workflow',
        scheduled_at=slot,version=1)
    encoded = base64.urlsafe_b64encode(json.dumps(binding,sort_keys=True,
        separators=(',',':')).encode()).decode().rstrip('=')
    return SeedRequest(job=binding['job'],run_iri='urn:shuttle:run:scheduled-v1-'+encoded,
        scheduled_at=slot,due_at=slot+600,recipient='fixture-agent',
        title='synthetic scheduled watch',body='Run the fixture watch and close the seed.')


def main():
    sdk = os.environ.get('SCHEDULE_TEST_SD_BIN')
    if not sdk or not Path(sdk).is_absolute():
        raise SystemExit('Set SCHEDULE_TEST_SD_BIN to an admitted local SDK executable.')
    original = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix='scheduled-seed-demo-') as directory:
            root = Path(directory)
            (root/'home').mkdir()
            os.environ.clear()
            os.environ.update(HOME=str(root/'home'),XDG_CONFIG_HOME=str(root/'home'/'.config'),
                              PATH=os.defpath,USER='synthetic',SHANTY_SD_BIN=sdk)
            version = subprocess.check_output([sdk,'--version'],cwd=root,text=True).strip()
            print('SDK:',version,'sha256='+hashlib.sha256(Path(sdk).read_bytes()).hexdigest())
            subprocess.run([sdk,'init','--prefix','fixture','--json'],cwd=root,
                           capture_output=True,check=True,timeout=30)
            where = json.loads(subprocess.check_output([sdk,'where','--json'],cwd=root,timeout=30))
            assert Path(where['database_path']).is_relative_to(root)
            subprocess.run([sdk,'--store',where['database_path'],'create','fixture store control','--json'],
                           cwd=root,capture_output=True,check=True,timeout=30)
            tracker = SdTracker(repo=str(root),store=where['database_path'],prefix='fixture')
            assigned = []
            def synthetic_go(argv):
                assert argv[0] == 'go'
                seed = port.read(argv[1])
                assert seed['status'] == 'open' and seed['assignee'] is None
                assigned.append(argv)
                return 0
            class Port(NativeSeedPort):
                creates = 0
                lose = False
                lost_id = None
                def create(self,fields):
                    self.creates += 1
                    item = super().create(fields)
                    if self.lose:
                        self.lost_id = item
                        raise RuntimeError('synthetic response lost AFTER actual local commit')
                    return item
            port = Port(tracker,synthetic_go)
            ledger = SeedLedger(root/'execution-ledger.db')
            req = request(1000)
            result = ledger.deliver(req,port)
            assert ledger.deliver(req,port) == result
            assert port.creates == 1 and len(assigned) == 1
            seed = port.read(result['seed'])
            assert seed['external_ref'] == req.firing and seed['workflow_run'] == req.run_iri
            print('actual SDK: one keyed seed, stable external-ref and signed-run link read back BEFORE synthetic go')
            print('duplicate firing: no second create or assignment callback')
            print('synthetic callback: submitted only; accepted Go receipt remains UNKNOWN')
            ledger.close()
            ledger = SeedLedger(root/'execution-ledger.db')
            assert ledger.deliver(req,port) == result and port.creates == 1
            port.lose = True
            req2 = request(1060)
            for _ in range(2):
                try:
                    ledger.deliver(req2,port)
                except SeedUnknown:
                    pass
                else:
                    raise AssertionError('lost creation must remain unknown')
            assert port.creates == 2 and len(assigned) == 1
            assert port.read(port.lost_id)['external_ref'] == req2.firing
            print('actual local commit + simulated lost response: seed survives; UNKNOWN, no second create/go')
            ledger.reconcile_created(req2,port.lost_id,port)
            ledger.deliver(req2,port)
            assert port.creates == 2 and len(assigned) == 2
            print('exact-ID readback reconciliation: one assignment callback, no replacement seed')
            assert ledger.for_code_outcome(request(1120),port,dict(outcome='succeeded',exit_code=0)) is None
            assert port.creates == 2
            print('pure-code success: no seed (signed run recording remains Shuttle responsibility)')
            ledger.close()
            print('FIXTURE ONLY: isolated HOME/CWD/store/identity; synthetic go, no real pane or production write')
    finally:
        os.environ.clear()
        os.environ.update(original)


if __name__ == '__main__':
    main()
