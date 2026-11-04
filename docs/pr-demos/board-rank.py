"""Deterministic fixture; no network, tracker, graph or model calls."""
from datetime import datetime, timezone
from shantytown.board_rank import propose, table


def main():
    rows=[]
    for identifier,priority,labels,owner,deps in [
        ('urgent',0,[],'up',['prerequisite']),
        ('prerequisite',1,[],'up',[]),
        ('automation',1,['work:automation'],'down',[]),
        ('title-only',1,[],'unknown',[])]:
        rows.append(dict(id=identifier,title='automate merge P0' if identifier=='title-only' else identifier,
                         description='synthetic fixture',priority=priority,labels=labels,
                         assignee=owner,blocked_by=deps,status='open',rank=None,
                         created_at='2026-01-01T00:00:00Z'))
    print('BEFORE: declared priorities; no existing ranks')
    for row in rows:print(row['id'], 'P'+str(row['priority']), 'rank='+str(row['rank']))
    policies={kind:dict(iri='urn:reviewed-rule:'+kind) for kind in ['automation','dependency']}
    out=propose(rows,policies,{'up':'up','down':'down','unknown':'unknown'},
                now=datetime(2026,11,4,tzinfo=timezone.utc))
    print('\nAFTER: deterministic proposals')
    print(table(out))
    by_id={p['item']:p for p in out['proposals']}
    assert by_id['prerequisite']['proposed_priority']==0
    assert by_id['automation']['proposed_priority']==0 and by_id['automation']['reowner']
    assert by_id['title-only']['proposed_priority']==1 and not by_id['title-only']['reowner']
    assert out['changes_applied'] is False and out['undefer_proposed'] is False
    print('\nCONTROLS: title words did not promote; UNKNOWN did not become down; zero mutations/model calls')


if __name__=='__main__':main()
