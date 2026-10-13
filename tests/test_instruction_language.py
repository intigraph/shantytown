"""Emitted advice uses current terminology and executable neutral work commands."""
import re
from types import SimpleNamespace

from shantytown import handoff_text, help_topics, query_first, resume_brief, untracked
from shantytown.notify import StalledAlerter


def _current(text):
    # Existing CLI flag names stay compatible. Only their exact token is exempt.
    text=re.sub(r'--[a-z][a-z0-9-]*', '', text)
    assert not re.search(r'gas ?town|\bbeads?\b|\bbd\b',text,re.I)
    assert not re.search(r'\bbr (?:show|create|update|close|comments)',text)


def test_resume_pointer_is_neutral_and_keeps_exact_id():
    text=resume_brief.compose('worker',checkpoint_bead='st-fixture')
    _current(text)
    assert 'st work item show st-fixture' in text


def test_untracked_creation_preserves_assignee_and_uses_supported_flags():
    text=untracked._how_to_hook('worker',SimpleNamespace(reports_to='lead'))
    _current(text)
    assert 'st task' in text and '--assignee worker' in text
    assert 'st work item update <id> --status in_progress' in text
    assert 'st go <id> worker' in text


def test_self_heal_close_requires_reviewable_reason_file():
    text=StalledAlerter._nudge_message(['st-fixture'],12)
    _current(text)
    assert 'st work item close st-fixture --reason-file <reason>' in text


def test_inbox_help_keeps_indeterminate_write_and_pointer_contract():
    text=help_topics.render('inbox')
    _current(text)
    assert 'st work item comment <id> --file <notes>' in text
    assert 'indeterminate' in text and 'switching stores' in text


def test_handoff_topics_and_query_first_current():
    for text in (help_topics.render('handoff'),query_first.DIRECTIVE):
        _current(text)


def _composed_text(node):
    import ast
    if isinstance(node,ast.Constant) and isinstance(node.value,str):return node.value
    if isinstance(node,ast.JoinedStr):
        parts=[]
        for value in node.values:
            if isinstance(value,ast.FormattedValue):
                text=_composed_text(value.value)
                parts.append(text if text is not None else "\x00DATA\x00")
            else:parts.append(_composed_text(value) or "")
        return ''.join(parts)
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Add):
        left,right=_composed_text(node.left),_composed_text(node.right)
        if left is not None and right is not None:return left+right
    return None


def test_composed_owned_instruction_negatives_and_api_selector_control():
    import ast
    import pytest
    for source in ("f\"Use {'beads'} for work\"", "f\"Use {'Gas'} Town for work\"", "'Use '+'beads'+' for work'"):
        with pytest.raises(AssertionError):_current(_composed_text(ast.parse(source,mode='eval').body))
    # A standalone selector remains wire/API data, not emitted instruction prose.
    assert _composed_text(ast.parse("'beads'",mode='eval').body)=='beads'


def test_legacy_command_failure_does_not_claim_seeds_executed(monkeypatch):
    from shantytown import stop_event
    import pytest
    calls=[]
    def failed(argv,**kw):
        calls.append(argv);return SimpleNamespace(returncode=1,stderr='fixture refusal')
    monkeypatch.setattr(stop_event.subprocess,'run',failed)
    with pytest.raises(RuntimeError) as exc:stop_event._bd_json(['show','st-fixture'],None)
    assert calls[0][0]=='bd'
    assert 'compatibility tracker command show st-fixture failed' in str(exc.value)
    assert 'sd show' not in str(exc.value)


def test_all_runtime_instruction_literals_use_current_language():
    import ast
    from pathlib import Path
    import shantytown
    compatibility={
        'doctor.py': {'go install github.com/steveyegge/beads/cmd/bd@latest'},
        'pr_preflight.py': {'\n\nBead: '},
        'cost.py': {'# st-bead-cost-source '},
    }
    # Separate legacy adapters retain their own protocol diagnostics. This scan
    # covers every other runtime source, including newly added composer modules.
    adapters={'beads.py','br.py','stores.py'}
    seen=0
    for path in Path(shantytown.__file__).parent.glob('*.py'):
        if path.name in adapters:continue
        tree=ast.parse(path.read_text())
        docs={id(n.body[0].value) for n in ast.walk(tree)
              if isinstance(n,(ast.Module,ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))
              and n.body and isinstance(n.body[0],ast.Expr)
              and isinstance(n.body[0].value,ast.Constant)}
        parents={id(child):parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if id(node) in docs:continue
            value=_composed_text(node)
            if value is None:continue
            parent=parents.get(id(node))
            if isinstance(parent,(ast.JoinedStr,ast.FormattedValue)) or (isinstance(parent,ast.BinOp) and _composed_text(parent) is not None):continue
            if re.search(r'\s',value) and value not in compatibility.get(path.name,set()):
                text=re.sub(r'--[a-z][a-z0-9-]*|\bbeads\.role\b','',value)
                assert not re.search(r'gas ?town|\bbeads?\b|\bbd\b',text,re.I), (path.name,node.lineno)
                seen+=1
    assert seen>100, 'a zero-coverage instruction scan is not a pass'
