"""Codex 0.161 framed, wrapped input; no private message bodies or live keys."""
import pytest

from shantytown import input_box, triage, tmux


PROMPT = '\x1b[0;1m›\x1b[0m '
FOOTER = '\n\x1b[2mGPT-6.1\x1b[0m\n\x1b[1m? for shortcuts\x1b[0m\n'


def frame(body):
    return PROMPT + body + '\n' + FOOTER


def test_wrapped_typed_composer_is_visible_to_input_work_and_ownership():
    text = 'reviewer fixture\n' + '  wrapped fixture continuation\n' * 8
    screen = frame(text)
    assert triage.input_state(screen) == triage.INPUT_QUEUED
    assert triage.work_state(screen, True) == triage.QUEUED
    assert input_box._classify(screen)[0] == input_box.TYPED
    assert 'wrapped fixture continuation' in triage.input_evidence(screen)
    assert tmux._codex_owned_input(screen, text)
    assert not tmux._codex_owned_input(screen, text + ' foreign suffix')
    assert not tmux._codex_owned_input(frame(text + ' foreign suffix'), text)


@pytest.mark.parametrize('colour', ['38;2;123;45;67', '48;2;2;0;22', '38;5;2',
                                   '38:2::123:45:67', '58;5;2'])
def test_colour_subparameters_are_not_dim_or_reset(colour):
    assert triage.input_state(frame(f'\x1b[{colour}mtyped fixture\x1b[0m')) == triage.INPUT_QUEUED
    ghost = frame(f'\x1b[2m\x1b[{colour}mghost fixture\x1b[0m')
    assert triage.input_state(ghost) == triage.INPUT_PLACEHOLDER


def test_wrapped_ghost_and_empty_remain_non_submittable():
    ghost = '\n'.join('\x1b[2mghost fixture\x1b[0m' for _ in range(10))
    assert triage.input_state(frame(ghost)) == triage.INPUT_PLACEHOLDER
    assert triage.input_state(frame('')) == triage.INPUT_EMPTY
    assert not tmux._codex_owned_input(frame(ghost), 'ghost fixture')


def test_unframed_history_and_attribute_stripped_text_are_not_typed():
    body = 'wrapped fixture\n' * 10
    assert triage.input_state(PROMPT + body + '\n'.join('history row' for _ in range(10))) == triage.INPUT_ABSENT
    stripped = triage.strip_attrs(frame(body))
    assert triage.input_state(stripped) != triage.INPUT_QUEUED
    assert triage.input_state('› plain fixture\n') == triage.INPUT_UNKNOWN


def test_newest_composer_wins_and_footer_looking_body_cannot_hide_foreign_text():
    text = 'owned fixture\nGPT-6.1\n? for shortcuts\nforeign suffix'
    screen = frame(text)
    assert not tmux._codex_owned_input(screen, 'owned fixture')
    assert tmux._codex_owned_input(screen, text)
    assert triage.input_state(frame('old typed') + frame('')) == triage.INPUT_EMPTY


def test_framed_scan_is_bounded():
    assert triage.codex_composer(frame('row\n' * 100)) is None
