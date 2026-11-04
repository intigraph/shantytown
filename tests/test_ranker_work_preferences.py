from shantytown.work_class import preferred_labels, lane_refusal
from types import SimpleNamespace


def test_declared_quipu_and_design_work_get_preference_labels_without_replacing_labels():
    labels = ['interop', 'quipu']
    assert preferred_labels(labels) == ('work:claude-authorized', 'work:important-quipu-code')
    assert labels == ['interop', 'quipu']
    assert preferred_labels(['design']) == ('work:claude-authorized', 'work:design')
    assert preferred_labels(['work:design', 'work:claude-authorized']) == ()


def test_review_and_unknown_metadata_are_not_auto_authorized():
    assert preferred_labels(['quipu', 'work:review']) == ()
    assert preferred_labels(None) == ()
    assert preferred_labels(['documentation', 'quipu']) == ()
    assert preferred_labels(['misc']) == ()


def test_preference_does_not_restore_the_removed_claude_authoring_restriction():
    assert lane_refusal(SimpleNamespace(labels=[]), 'claude', 'author') == ''
    assert 'reviews require codex' in lane_refusal(
        SimpleNamespace(labels=['work:review']), 'claude', 'author')
