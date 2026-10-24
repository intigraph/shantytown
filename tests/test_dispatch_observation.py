import json
from shantytown import tmux
from shantytown.dispatch import Dispatcher
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes

def test_actual_codex_submission_survives_missing_scrollback(tmp_path, monkeypatch):
    ready='\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m\n gpt-6 high · /workspace'
    busy='Working (1s • esc to interrupt)\n'+ready
    crew=tmp_path/'crew';crew.mkdir()
    (crew/'worker.json').write_text(json.dumps({'role':'worker','pane':'%5'}))
    tracker=FilesTracker(tmp_path/'items');tracker.update('item-1',title='Repair',status='open')
    calls=[]
    monkeypatch.setattr(tmux,'_journal_send',lambda *_:None)
    monkeypatch.setattr(tmux.time,'sleep',lambda _:None)
    monkeypatch.setattr(tmux.subprocess,'run',lambda argv,**kw:calls.append(argv))
    adapter=tmux.Tmux(root=tmp_path/'runtime')
    monkeypatch.setattr(adapter,'session_created',lambda _:1)
    frames=iter([ready,busy])
    monkeypatch.setattr(adapter,'capture',lambda *a,**kw:next(frames,busy))
    monkeypatch.setattr(adapter,'foreground',lambda _:'codex')
    class Panes(NullPanes):
        def send(self,pane,text):
            self.screen=busy
            return adapter.send(pane,text)
    panes=Panes(screen=ready)
    Dispatcher(FilesRegistry(crew),tracker,panes).go('item-1','worker')
    assert tracker.get('item-1').status=='in_progress'
    assert sum(c[-1]=='Enter' for c in calls)==1

import pytest
from shantytown.protocols import SubmissionObserved
from shantytown.dispatch import SendUnverified, TriageRefused

@pytest.mark.parametrize('evidence', [None, True, {'delivered': True},
    SubmissionObserved('%other', 'bad'), SubmissionObserved('%5', 'bad'), 'wrong-pane'])
def test_unknown_or_mismatched_evidence_never_assigns(tmp_path, monkeypatch, evidence):
    crew=tmp_path/'crew';crew.mkdir()
    (crew/'worker.json').write_text(json.dumps({'role':'worker','pane':'%5'}))
    tracker=FilesTracker(tmp_path/'items');tracker.update('item-1',title='Repair',status='open')
    monkeypatch.setattr('shantytown.dispatch.time.sleep',lambda _:None)
    class Panes(NullPanes):
        def send(self,pane,text):
            self.sent.append((pane,text))
            if evidence == 'wrong-pane':
                import hashlib
                return SubmissionObserved('%other', hashlib.sha256(text.encode()).hexdigest())
            return evidence
    panes=Panes()
    with pytest.raises(SendUnverified):
        Dispatcher(FilesRegistry(crew),tracker,panes).go('item-1','worker')
    assert len(panes.sent)==1
    assert tracker.get('item-1').status=='open'


def test_busy_receiver_still_refuses_before_send(tmp_path):
    crew=tmp_path/'crew';crew.mkdir()
    (crew/'worker.json').write_text(json.dumps({'role':'worker','pane':'%5'}))
    tracker=FilesTracker(tmp_path/'items');tracker.update('item-1',title='Repair',status='open')
    panes=NullPanes(screen='Working (1s • esc to interrupt)')
    with pytest.raises(TriageRefused):
        Dispatcher(FilesRegistry(crew),tracker,panes).go('item-1','worker')
    assert not panes.sent
    assert tracker.get('item-1').status=='open'
