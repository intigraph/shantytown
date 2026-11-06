"""Saved launch preferences, independent of the active program or credentials."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import re
import sys


def validate(value):
    if value is None:
        return None
    if not isinstance(value, dict) or len(value) > 32:
        raise ValueError('harness_options must be a table of harness tables')
    for name, options in value.items():
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', name):
            raise ValueError('harness_options has an invalid harness name')
        if not isinstance(options, dict) or len(options) > 32:
            raise ValueError('harness_options entries must be option tables')
        for key, setting in options.items():
            if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', key):
                raise ValueError('harness_options has an invalid option name')
            if key == 'chrome':
                if type(setting) is not bool:
                    raise ValueError('harness_options chrome must be true or false')
            elif key == 'model':
                if setting is not None and (not isinstance(setting, str) or not setting.strip()
                                           or len(setting) > 256 or any(ord(c) < 32 for c in setting)):
                    raise ValueError('harness_options model must be a nonempty model ID or null')
            elif type(setting) not in (bool, str, int) or isinstance(setting, str) and len(setting) > 256:
                raise ValueError('unsupported harness_options values must be bounded scalars')
    return deepcopy(value)


def profiles(card, current):
    """Migrate legacy fields in memory only; no card is rewritten by a read."""
    result = validate(getattr(card, 'harness_options', None)) or {}
    # The old chrome field always meant Claude's browser, even on a Codex card.
    result.setdefault('claude', {}).setdefault('chrome', card.chrome)
    active = result.setdefault(current, {})
    # Flat model remains the active selection alias. Existing model/fallback and
    # account writers keep working; a harness switch archives that selection.
    if card.model is not None or 'model' not in active:
        active['model'] = card.model
    return result


def target_model(card, current, target, explicit):
    saved = profiles(card, current).get(target, {})
    return (explicit if explicit is not None else saved.get('model'), 'model' in saved)


def converted(card, current, target, model):
    saved = profiles(card, current)
    selected = saved.setdefault(target, {})
    selected['model'] = model
    chrome = selected.get('chrome', False) if target == 'claude' else False
    return replace(card, harness=target, model=model, chrome=chrome, harness_options=saved)


def chrome(card):
    saved = validate(getattr(card, 'harness_options', None)) or {}
    return saved.get('claude', {}).get('chrome', card.chrome)


def model(card, current):
    # Named-account selection and the flat active override retain their existing
    # precedence. Saved models only fill a card that has no active override.
    if card.model is not None or getattr(card, 'account', None):
        return card.model
    saved = validate(getattr(card, 'harness_options', None)) or {}
    return saved.get(current, {}).get('model')


def warn_unsupported(card, current):
    saved = validate(getattr(card, 'harness_options', None)) or {}
    options = saved.get(current, {})
    supported = {'model', 'chrome'} if current == 'claude' else {'model', 'effort'} if current == 'agy' else {'model'}
    ignored = set(options) - supported
    if current != 'claude' and card.chrome:
        ignored.add('chrome')
    if ignored:
        print(f"  notice: {card.name}: {current} ignores unsupported options "
              f"{', '.join(sorted(ignored))}; retained on the card", file=sys.stderr)
