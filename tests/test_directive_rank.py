from types import SimpleNamespace
from itertools import permutations
import pytest
from shantytown import directive_rank as dr
from shantytown.protocols import plate_key

PROOF = SimpleNamespace(graph="urn:project")
def response(ids, **extra):
    return dict(rows=[{"id": i} for i in ids], count=len(ids), truncated=False, **extra)
def key(row):
    return plate_key(row.get("status","open"), row.get("priority",2), row["id"],
                     rank=row.get("rank"), due_at=row.get("due_at"),
                     created_at=row.get("created_at"), lane=row.get("lane"),
                     operator_directive=row.get("operator_directive",False))
def test_operator_breaks_only_incidental_ties():
    old={"id":"old","rank":"1","created_at":"2020-01-01T00:00:00Z"}
    new={"id":"new","rank":"1","created_at":"2021-01-01T00:00:00Z","operator_directive":True}
    assert key(new)<key(old)
    assert key(dict(old,rank="0"))<key(new)
    assert key(dict(old,priority=1))<key(new)
    assert key(dict(old,status="in_progress"))<key(new)
    assert key(dict(old,lane="now"))<key(new)
@pytest.mark.parametrize("lane",["now","next"])
def test_lane_never_reintroduces_priority(lane):
    operator={"id":"operator","lane":lane,"rank":"1","priority":4,"operator_directive":True}
    plain={"id":"plain","lane":lane,"rank":"1","priority":0}
    assert key(operator)<key(plain)
    assert key(dict(plain,rank="0"))<key(operator)
def test_unknown_does_not_change_order_for_any_permutation():
    rows=[{"id":"a"},{"id":"b","rank":"1"},{"id":"c","priority":1}]
    for order in permutations(rows):
        before=sorted(order,key=key)
        after=dr.annotate(PROOF,list(order),reader=lambda *a: (_ for _ in ()).throw(ValueError("unknown")))
        assert sorted(after,key=key)==before
@pytest.mark.parametrize("bad",[response(["foreign"]), response(["one"],partial=True),
    dict(rows=[{"id":"one"}],count=1,truncated=True),
    dict(rows=[{"id":"one"}],count=2,truncated=False), response([{"value":"one","language":"en"}]),
    response(["one"]*257)])
def test_incomplete_response_never_leaves_a_partial_boost(bad):
    rows=[{"id":"one","operator_directive":True}]
    assert dr.annotate(PROOF,rows,reader=lambda *a:bad)==[{"id":"one"}]
def test_one_bounded_read_carries_only_explicit_evidence():
    seen=[]
    def read(proof,q,timeout):
        seen.append((q,timeout));return response(["one"])
    rows=dr.annotate(PROOF,[{"id":"one"},{"id":"two"}],timeout=30,reader=read)
    assert len(seen)==1 and seen[0][1]==2
    assert '<'+dr.A+'directiveKind> "operator"' in seen[0][0]
    assert 'isPartOf>+' in seen[0][0] and '"epic"' in seen[0][0]
    assert rows==[{"id":"one","operator_directive":True},{"id":"two"}]
def test_over_bound_does_not_read():
    rows=[{"id":f"id-{i}"} for i in range(257)]
    assert dr.annotate(PROOF,rows,reader=lambda *a:pytest.fail("over-bound read"))==rows
@pytest.mark.parametrize("cell",["one",{"type":"literal","value":"one"},
    {"value":"one","datatype":"http://www.w3.org/2001/XMLSchema#string"}])
def test_typed_and_compact_cells(cell):
    assert dr.decode(response([cell]),{"one"})=={"one"}


def test_advisory_flag_never_replaces_due_order_when_false():
    assert key({"id":"one","operator_directive":"operator"}) == key({"id":"one"})
