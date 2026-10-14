from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from shantytown.gate_backstop import Backstop, validate_gate, steve_ask
from shantytown.dispatch import Dispatcher, DeferRefused
from shantytown.files import FilesTracker, FilesRegistry
from shantytown.tmux import NullPanes
NOW=datetime(2026,10,13,16,tzinfo=timezone.utc)
ASK='steve_quote: Give me ARM F backing data\nsteve_source: Steve 2026-10-05 retained request\nsteve_ask_at: 2026-10-05T12:00:00Z'
def rows():
 return [{'id':'aegis-s9sjf.8','status':'deferred','priority':1,'notes':'repo: paper\nresume_when: closed:aegis-i7xl1x.1'}, {'id':'aegis-i7xl1x.1','status':'deferred','notes':'repo: seeds','updated_at':'2026-10-08T00:00:00Z'}]
def test_exact_chain_delivered_once_restart_and_failed_delivery(tmp_path):
 calls=[]
 w=Backstop(tmp_path,NOW,lambda who,msg:calls.append((who,msg)) or False)
 assert w.run(rows(),lambda _:None)==[]
 assert len(calls)==1
 w=Backstop(tmp_path,NOW,lambda who,msg:calls.append((who,msg)) or who)
 assert w.run(rows(),lambda _:None)==['aegis-s9sjf.8']
 assert 'aegis-s9sjf.8 -> aegis-i7xl1x.1' in calls[-1][1]
 assert 'cross-repo/epic' in calls[-1][1]
 assert Backstop(tmp_path,NOW,lambda *args:pytest.fail('duplicate')).run(rows(),lambda _:None)==[]
def test_stale_open_target_positive_and_fresh_negative(tmp_path):
 r=rows();r[1]['status']='open';r[1]['notes']='repo: paper'
 calls=[]
 assert Backstop(tmp_path,NOW,lambda *a:calls.append(a) or True).run(r,lambda _:None)
 r[1]['updated_at']=NOW.isoformat()
 assert Backstop(tmp_path,NOW,lambda *a:pytest.fail('fresh')).run(r,lambda _:None)==[]
def test_unknown_keeps_delivery_and_never_releases(tmp_path):
 r=rows();deliver=lambda *a:True
 Backstop(tmp_path,NOW,deliver).run(r,lambda _:None)
 Backstop(tmp_path,NOW,deliver).run(r[:1],lambda _:None)
 assert Backstop(tmp_path,NOW,lambda *a:pytest.fail('replayed')).run(r,lambda _:None)==[]
def test_started_by_ordered_escalation_and_resolution(tmp_path):
 r=[{'id':'paper','status':'open','notes':ASK}];calls=[]
 def deliver(who,msg):calls.append(who);return who
 Backstop(tmp_path,NOW,deliver).run(r,lambda _:None)
 Backstop(tmp_path,NOW,deliver).run(r,lambda _:None)
 Backstop(tmp_path,NOW,deliver).run(r,lambda _:None)
 assert calls==['sattler','hammond']
 r[0]['status']='in_progress'
 assert Backstop(tmp_path,NOW,lambda *a:pytest.fail('started')).run(r,lambda _:None)==[]
def test_ask_requires_original_precise_provenance(tmp_path):
 assert steve_ask(ASK)
 assert steve_ask(ASK.replace('2026-10-05T12:00:00Z','2026-10-05')) is None
 assert steve_ask(ASK.replace('steve_source:','source:')) is None
 r=[{'id':'x','status':'open','notes':ASK.replace('2026-10-05','2026-10-12')}]
 assert Backstop(tmp_path,NOW,lambda *a:pytest.fail('early')).run(r,lambda _:None)==[]
def test_gate_priority_and_technical_reason(tmp_path):
 tr=FilesTracker(tmp_path/'items');reg=FilesRegistry(tmp_path/'crew');d=Dispatcher(reg,tr,NullPanes())
 tr.update('paper',status='open',priority=0,notes=ASK)
 tr.update('code',status='open',priority=3)
 with pytest.raises(DeferRefused):d.defer('paper','bead','resume_when: closed:code')
 with pytest.raises(DeferRefused):d.defer('paper','bead','resume_when: closed:code',dependency_reason='Paper executes code')
 assert tr.get('code').priority==3
 kwargs=dict(dependency_reason='Paper executes code',sattler_reason='Exact approved required code path',gate_authority='sattler')
 d.defer('paper','bead','resume_when: closed:code',dry_run=True,**kwargs)
 assert tr.get('code').priority==3
 d.defer('paper','bead','resume_when: closed:code',**kwargs)
 assert tr.get('code').priority==0
 assert 'dependency_reason: Paper executes code' in tr.get('paper').notes
 assert 'sattler_gate_reason:' in tr.get('paper').notes
@pytest.mark.parametrize('reason',['','two\nlines'])
def test_invalid_reason(reason):
 with pytest.raises(ValueError):validate_gate(SimpleNamespace(id='a',priority=1,notes=''),SimpleNamespace(id='b',priority=2),reason)
def test_cycle_and_chain_budget(tmp_path):
 r=rows();r[1]['notes']='resume_when: closed:aegis-s9sjf.8';calls=[]
 Backstop(tmp_path,NOW,lambda *a:calls.append(a) or True).run(r,lambda _:None)
 assert 'cycle' in calls[0][1]
def test_observed_stability_when_modified_timestamp_missing(tmp_path):
 r=rows();r[0]['notes']='repo: paper\nresume_when: closed:aegis-i7xl1x.1';r[1].update(status='open',notes='repo: paper',updated_at=None)
 assert Backstop(tmp_path,NOW,lambda *a:pytest.fail('no age')).run(r,lambda _:None)==[]
 calls=[]
 assert Backstop(tmp_path,NOW+timedelta(hours=48),lambda *a:calls.append(a) or True).run(r,lambda _:None)
 assert '48h' in calls[0][1]
def test_unproven_ask_metadata_event_once_without_age_claim(tmp_path):
 r=[{'id':'paper','status':'open','notes':'steve_quote: Please supply data'}];calls=[]
 deliver=lambda *a:calls.append(a) or True
 Backstop(tmp_path,NOW,deliver).run(r,lambda _:None)
 Backstop(tmp_path,NOW,deliver).run(r,lambda _:None)
 assert len(calls)==1 and calls[0][0]=='sattler' and 'age is UNKNOWN' in calls[0][1]
def test_closed_target_does_not_report_stall(tmp_path):
 r=rows();r[1]['status']='closed'
 assert Backstop(tmp_path,NOW,lambda *a:pytest.fail('resolved')).run(r,lambda _:None)==[]
def test_corrupt_ledger_does_not_replay(tmp_path):
 p=tmp_path/'notify';p.mkdir();(p/'gate-backstop.json').write_text('broken')
 with pytest.raises(ValueError):Backstop(tmp_path,NOW,lambda *a:pytest.fail('replay'))
def test_intermediate_gate_does_not_emit_second_chain_event(tmp_path):
 r=rows();r[1]['notes']='resume_when: closed:compiler';r.append({'id':'compiler','status':'open','updated_at':'2026-10-08T00:00:00Z'})
 calls=[]
 Backstop(tmp_path,NOW,lambda *a:calls.append(a) or True).run(r,lambda _:None)
 assert len(calls)==1 and 'aegis-s9sjf.8 -> aegis-i7xl1x.1 -> compiler' in calls[0][1]
def test_priority_timeout_not_retried_and_waiter_stays_open(tmp_path):
 from shantytown.dispatch import DeferUnconfirmed
 tr=FilesTracker(tmp_path/'items');tr.update('a',status='open',priority=0);tr.update('b',status='open',priority=3)
 original=tr.update;calls=[]
 def uncertain(identifier,**fields):
  calls.append(identifier);original(identifier,**fields);raise TimeoutError('after committed priority')
 tr.update=uncertain
 with pytest.raises(DeferUnconfirmed):Dispatcher(FilesRegistry(tmp_path/'crew'),tr,NullPanes()).defer('a','bead','resume_when: closed:b',dependency_reason='Required API')
 assert calls==['b'] and tr.get('a').status=='open' and tr.get('b').priority==0
def test_empty_quote_cannot_borrow_next_metadata_line():
 assert steve_ask(ASK.replace('steve_quote: Give me ARM F backing data','steve_quote:')) is None
def test_batch_failure_never_falls_back_to_single_reads(tmp_path):
 r=rows()[:1];r[0]['notes']='repo: paper\nresume_when: closed:other'
 def fail(ids):raise TimeoutError('batch UNKNOWN')
 assert Backstop(tmp_path,NOW,lambda *a:pytest.fail('unknown')).run(r,lambda _:pytest.fail('fallback'),lookup_many=fail)==[]
def test_bounded_reads_rotate_candidates_without_starvation(tmp_path):
 r=[{'id':f'wait-{i:03}', 'status':'deferred','notes':f'repo: paper\nresume_when: closed:target-{i:03}'} for i in range(60)]
 calls=[];reads=[];reported=[]
 def detail(identifier):
  reads.append(identifier);return {'id':identifier,'status':'open','notes':'repo: paper','updated_at':'2026-10-08T00:00:00Z'}
 def batch(ids):return {identifier:detail(identifier) for identifier in ids}
 for _ in range(12):
  before=len(reads)
  prior=len(calls)
  reported.extend(Backstop(tmp_path,NOW,lambda *a:calls.append(a) or True).run(r,detail,lookup_many=batch))
  assert len(reads)-before<=25
  assert len(calls)-prior<=1
 assert len(reported)==60
 assert len(set(reported))==60
def test_known_deferred_prefix_survives_unknown_suffix_without_duplicate(tmp_path):
 r=rows();r[1]['notes']='resume_when: closed:missing';calls=[]
 deliver=lambda *a:calls.append(a) or True
 assert Backstop(tmp_path,NOW,deliver).run(r,lambda _:None)==['aegis-s9sjf.8']
 assert 'further chain UNKNOWN' in calls[0][1] and 'gate target is deferred/blocked' in calls[0][1]
 r.append({'id':'missing','status':'open','updated_at':NOW.isoformat(),'notes':'repo: paper'})
 assert Backstop(tmp_path,NOW,lambda *a:pytest.fail('same waiting edge')).run(r,lambda _:None)==[]
def test_unknown_first_target_cannot_claim_a_stall(tmp_path):
 assert Backstop(tmp_path,NOW,lambda *a:pytest.fail('unknown target')).run(rows()[:1],lambda _:None)==[]


def test_digest_failure_preserves_all_events_and_ask_stage(tmp_path):
 r=rows()+[{'id':'ask','status':'open','notes':ASK}]
 calls=[]
 assert Backstop(tmp_path,NOW,lambda *a:calls.append(a) or False).run(r,lambda _:None)==[]
 assert len(calls)==1 and 'STALL' in calls[0][1] and 'STEVE ASK NOT STARTED' in calls[0][1]
 state=Backstop(tmp_path,NOW,lambda *a:True).state
 assert any(v.get('stage')==0 for v in state.values())
 assert not any(v.get('delivered') for v in state.values())
 delivered=[]
 assert set(Backstop(tmp_path,NOW,lambda *a:delivered.append(a) or True).run(r,lambda _:None))=={'aegis-s9sjf.8','ask'}
 assert len(delivered)==1
 # Escalation to Hammond stays a later pass, after confirmed Sattler digest.
 second=[]
 assert Backstop(tmp_path,NOW,lambda *a:second.append(a) or True).run(r,lambda _:None)==['ask']
 assert len(second)==1 and second[0][0]=='hammond'


def test_digest_exception_does_not_advance_delivery(tmp_path):
 def fail(*args):raise TimeoutError('indeterminate')
 assert Backstop(tmp_path,NOW,fail).run(rows(),lambda _:None)==[]
 assert Backstop(tmp_path,NOW,lambda *a:True).run(rows(),lambda _:None)==['aegis-s9sjf.8']


@pytest.mark.parametrize('stamp,authority,cooling',[
 ('2026-10-13T15:00:00Z','sattler',True),
 ('2026-10-12T16:00:00Z','sattler',False),
 ('2026-10-13T17:00:00Z','sattler',False),
 ('not-a-time','sattler',False),
 ('2026-10-13','sattler',False),
 ('2026-10-13T15:00:00Z','arnold',False),
])
def test_recorded_verdict_cooldown_and_expiry(tmp_path,stamp,authority,cooling):
 r=rows();r[0]['notes']+=f'\ngate_verdict: Keep this real dependency\ngate_verdict_by: {authority}\ngate_verdict_at: {stamp}'
 calls=[]
 first=Backstop(tmp_path,NOW,lambda *a:calls.append(a) or True).run(r,lambda _:None)
 assert (first==[]) is cooling
 assert len(calls)==(0 if cooling else 1)
 if cooling:
  assert Backstop(tmp_path,NOW+timedelta(hours=24),lambda *a:True).run(r,lambda _:None)==['aegis-s9sjf.8']


def test_digest_utf8_bound_and_pending_delivery(tmp_path):
 r=[]
 for i in range(24):
  r.extend([{'id':f'w{i}','status':'blocked','notes':f'resume_when: closed:t{i}'},
            {'id':f't{i}','status':'blocked','notes':''}])
 calls=[];reported=[]
 for _ in range(8):
  reported.extend(Backstop(tmp_path,NOW,lambda *a:calls.append(a) or True).run(r,lambda _:None))
 assert len(reported)==len(set(reported))==24
 assert all(len(msg.encode('utf-8'))<6100 for _,msg in calls)



def test_large_unicode_ask_remains_one_bounded_digest(tmp_path):
 note=ASK.replace('Give me ARM F backing data','界'*10000)
 calls=[]
 assert Backstop(tmp_path,NOW,lambda *a:calls.append(a) or True).run(
  [{'id':'large-ask','status':'open','notes':note}],lambda _:None)==['large-ask']
 assert len(calls)==1 and 'large-ask' in calls[0][1]
 assert len(calls[0][1].encode('utf-8'))<6100
 assert '[details on large-ask]' in calls[0][1]


def test_verdict_cools_pending_ask_escalation_without_resetting_stage(tmp_path):
 r=[{'id':'ask','status':'open','notes':ASK}]
 assert Backstop(tmp_path,NOW,lambda *a:True).run(r,lambda _:None)==['ask']
 r[0]['notes']+='\ngate_verdict: Working on it\ngate_verdict_by: sattler\ngate_verdict_at: 2026-10-13T16:00:00Z'
 assert Backstop(tmp_path,NOW,lambda *a:pytest.fail('cooldown')).run(r,lambda _:None)==[]
 calls=[]
 assert Backstop(tmp_path,NOW+timedelta(hours=24),lambda *a:calls.append(a) or True).run(r,lambda _:None)==['ask']
 assert len(calls)==1 and calls[0][0]=='hammond'
