"""Keep-or-cycle advice from depth, bounded cache evidence and work overlap.

Normal dispatch previews deterministic repository/file/scope overlap against the
previous verified handoff, then records a signal only after delivery and custody
readback. Missing prior facts stay UNKNOWN. Explicit caller judgements override
fresh automatic overlap. The hard context ceilings remain authoritative.

Claude cache writes name their observed five-minute or one-hour TTL. Codex usage
names request timing and counters; per-model policy windows are explicit
assumptions, not cache-eviction observations or account entitlement claims.

The configurable cost model estimates input-equivalent work. It cannot price
reasoning retained in context or measure a subscription's actual consumption.
"""
from __future__ import annotations

import json
import fnmatch
import fcntl
import re
from contextlib import contextmanager
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path

KEEP = "keep"
CYCLE = "cycle"
#: No opinion: the caller does exactly what it did before this module existed.
DEFAULT = "default"
DECISIONS = (KEEP, CYCLE)
#: How far back read_cache looks for a turn that wrote cache and so names its TTL.
TTL_SCAN_RECORDS = 50


@dataclass(frozen=True)
class Policy:
    """[cycle_advice] in shantytown.toml. Every field has a default, so the table
    is optional. Automatic overlap is local; external judges remain optional."""
    # THE FLOOR UNDER EVERYTHING (Stiwi: "there needs to be a configurable
    # threshold where we always decide to just clear context"). At or above it the
    # answer is CYCLE and nobody is asked: `--json` says ask=false, so a caller
    # never ships a request judging a context nobody would keep anyway.
    always_cycle_above_k: int = 350
    # What a caller is handed to judge from, bounded (Stiwi: "we dont want to
    # dump like 750k tokens on this request"). A judge that needs more asks for
    # it with --brief-chars, never past the max.
    brief_chars: int = 1500
    max_brief_chars: int = 6000
    keep_at: float = 0.8
    cycle_below: float = 0.3
    signal_max_age_minutes: int = 120
    # Used only when the transcript names no TTL (a harness that does not
    # record it). Claude Code records it per write; see read_cache.
    cache_ttl_seconds: int = 300
    read_multiplier: float = 0.1
    write_multiplier_5m: float = 1.25
    write_multiplier_1h: float = 2.0
    fresh_floor_k: int = 40
    rebuild_fraction: float = 0.3
    expected_turns: int = 10
    # Advisory windows, not cache-eviction measurements. Explicit transcript
    # TTLs win. API defaults need not describe a Codex subscription's routing.
    model_cache_ttl_seconds: dict[str, int] = field(default_factory=lambda: {
        'gpt-6*': 1800, 'gpt-5.6*': 1800, 'gpt-5.5*': 1800,
        'gpt-5*': 300, 'claude-*': 300,
    })


@dataclass(frozen=True)
class Signal:
    """What something outside st said about this handoff."""
    by: str
    at: float
    next_task: str = ""
    related: float | None = None
    decision: str | None = None
    reason: str = ""
    # How much context the NEXT task is predicted to consume, in k tokens, from a
    # fresh session. Post a high estimate (the upper edge of a judge's likely
    # band), not the mean: this only ever moves a cycle EARLIER.
    next_need_k: float | None = None


@dataclass(frozen=True)
class Cache:
    """The transcript's last usage record, read for TIMING, not occupancy."""
    last_at: float | None = None
    ttl_seconds: int | None = None
    provider: str | None = None
    model: str | None = None
    ttl_source: str | None = None
    cached_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None


@dataclass(frozen=True)
class Situation:
    agent: str
    depth_k: float | None
    cycle_line_k: float
    next_task: str = ""
    cache: Cache = field(default_factory=Cache)
    now: float = field(default_factory=time.time)

    @property
    def idle_seconds(self) -> float | None:
        return None if self.cache.last_at is None else max(0.0, self.now - self.cache.last_at)


@dataclass(frozen=True)
class Advice:
    decision: str
    why: str
    keep_cost_k: float | None = None
    cycle_cost_k: float | None = None
    cache_lapsed: bool | None = None

    def render(self) -> str:
        costs = ""
        if self.keep_cost_k is not None and self.cycle_cost_k is not None:
            costs = (f" [keep ~{self.keep_cost_k:.0f}k vs cycle "
                     f"~{self.cycle_cost_k:.0f}k input-equivalent]")
        return f"{self.decision}: {self.why}{costs}"


def cache_lapsed(sit: Situation, policy: Policy) -> bool | None:
    idle = sit.idle_seconds
    if idle is None:
        return None
    if sit.cache.ttl_source is not None and sit.cache.ttl_seconds is None:
        return None  # An identified but unsupported model is not the legacy fallback.
    return idle >= (sit.cache.ttl_seconds or policy.cache_ttl_seconds)


def costs(sit: Situation, related: float, policy: Policy) -> tuple[float, float]:
    """(keep, cycle) in thousands of base-input-equivalent tokens over the next
    task's expected turns. Unknown lapse is priced as warm — the direction that
    does not cycle on missing data."""
    depth = sit.depth_k or 0.0
    floor = min(policy.fresh_floor_k, depth)
    turns = max(1, policy.expected_turns)
    write = (policy.write_multiplier_1h if (sit.cache.ttl_seconds or 0) >= 3600
             else policy.write_multiplier_5m)
    read = policy.read_multiplier
    first = write if cache_lapsed(sit, policy) else read
    keep = first * depth + read * depth * (turns - 1)
    rebuild = related * policy.rebuild_fraction * (depth - floor)
    cycle = write * (floor + rebuild) + read * (floor + rebuild) * (turns - 1)
    return keep, cycle


def decide(sit: Situation, signal: Signal | None, policy: Policy = Policy()) -> Advice:
    lapsed = cache_lapsed(sit, policy)
    if sit.depth_k is not None and sit.depth_k >= sit.cycle_line_k:
        return Advice(CYCLE, f"{sit.depth_k:.0f}k is past the {sit.cycle_line_k:.0f}k "
                             "cycle line; no signal keeps a saturated context",
                      cache_lapsed=lapsed)
    if sit.depth_k is not None and sit.depth_k >= policy.always_cycle_above_k:
        return Advice(CYCLE, f"{sit.depth_k:.0f}k is at or past always_cycle_above_k "
                             f"({policy.always_cycle_above_k}k); not asking",
                      cache_lapsed=lapsed)
    if signal is None:
        return Advice(DEFAULT, "no signal posted; depth lines decide", cache_lapsed=lapsed)
    age_min = (sit.now - signal.at) / 60
    if age_min > policy.signal_max_age_minutes:
        return Advice(DEFAULT, f"signal from {signal.by} is {age_min:.0f}m old "
                               f"(max {policy.signal_max_age_minutes}m); ignored",
                      cache_lapsed=lapsed)
    if signal.next_task and sit.next_task and signal.next_task != sit.next_task:
        return Advice(DEFAULT, f"signal from {signal.by} is about {signal.next_task}, "
                               f"but the plate says {sit.next_task}; ignored",
                      cache_lapsed=lapsed)
    if (signal.next_need_k is not None and sit.depth_k is not None
            and sit.depth_k + signal.next_need_k >= sit.cycle_line_k):
        return Advice(CYCLE, f"{signal.by} predicts the next task needs "
                             f"~{signal.next_need_k:.0f}k; {sit.depth_k:.0f}k + that "
                             f"crosses the {sit.cycle_line_k:.0f}k cycle line mid-task, "
                             "so cycle at the boundary instead", cache_lapsed=lapsed)
    if signal.decision in DECISIONS:
        return Advice(signal.decision, f"{signal.by} decided {signal.decision}"
                      + (f": {signal.reason}" if signal.reason else ""),
                      cache_lapsed=lapsed)
    if signal.related is None:
        why = ("the predicted need fits under the cycle line; no relatedness to "
               "weigh" if signal.next_need_k is not None
               else "carries neither a decision nor a relatedness")
        return Advice(DEFAULT, f"signal from {signal.by}: {why}", cache_lapsed=lapsed)
    p = signal.related
    if p >= policy.keep_at:
        return Advice(KEEP, f"{signal.by} rates the next task {p:.2f} related "
                            f"(keep at >= {policy.keep_at:.2f})", cache_lapsed=lapsed)
    if p < policy.cycle_below:
        return Advice(CYCLE, f"{signal.by} rates the next task {p:.2f} related "
                             f"(cycle below {policy.cycle_below:.2f}): unrelated work",
                      cache_lapsed=lapsed)
    if sit.depth_k is None:
        return Advice(DEFAULT, "depth unreadable; cannot price keep vs cycle",
                      cache_lapsed=lapsed)
    keep, cycle = costs(sit, p, policy)
    state = {True: "cache lapsed", False: "cache warm", None: "cache state unknown"}[lapsed]
    if sit.cache.ttl_source and sit.cache.ttl_source.startswith('assumed'):
        state += ' (model-window estimate; eviction unmeasured)'
    if cycle < keep:
        return Advice(CYCLE, f"{signal.by} rates relatedness {p:.2f}; {state}; "
                             "cycling is cheaper", keep, cycle, lapsed)
    return Advice(KEEP, f"{signal.by} rates relatedness {p:.2f}; {state}; keeping is cheaper",
                  keep, cycle, lapsed)


def should_ask(sit: Situation, policy: Policy) -> bool:
    """Is there anything for an outside judge to decide? False past either line,
    and False when depth is unreadable: a judge asked about a context of unknown
    size is the request this bound exists to prevent."""
    return (sit.depth_k is not None and sit.depth_k < sit.cycle_line_k
            and sit.depth_k < policy.always_cycle_above_k)


def brief(parts: list[tuple[str, str]], chars: int, policy: Policy) -> dict:
    """The judge's input: labelled parts cut to `chars` in total (clamped to
    max_brief_chars). Each part gets a FAIR SHARE, with what a short part leaves
    unused passed on, so a long checkpoint can never crowd out the next task — a
    prefix cut would drop exactly the half the question is about. `truncated`
    tells the caller more exists, so it can ask again with a larger
    --brief-chars rather than guess."""
    limit = max(0, min(chars, policy.max_brief_chars))
    parts = [(label, body.strip()) for label, body in parts if body and body.strip()]
    budget, out = limit, {}
    for i, (label, body) in enumerate(sorted(parts, key=lambda p: len(p[1]))):
        share = budget // (len(parts) - i)
        out[label] = body[:share]
        budget -= len(out[label])
    full = sum(len(body) for _, body in parts)
    return dict(parts={label: out[label] for label, _ in parts},
                truncated=full > sum(len(v) for v in out.values()),
                chars=limit, full_chars=full, max_chars=policy.max_brief_chars)


# --- the call-in surface ------------------------------------------------------

def _signals_path(root) -> Path:
    return Path(root) / "notify" / "cycle_signals.json"


def _load(root) -> dict:
    try:
        data = json.loads(_signals_path(root).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@contextmanager
def _signal_lock(root):
    parent = _signals_path(root).parent
    parent.mkdir(parents=True, exist_ok=True)
    with (parent / 'cycle_signals.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _write_signals(root, data):
    path = _signals_path(root)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as fh:
        json.dump(data, fh, indent=1)
        tmp = fh.name
    try:
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def post(root, agent: str, signal: Signal, *, allow_unknown=False, preserve_after=None) -> None:
    if signal.related is not None and not 0.0 <= signal.related <= 1.0:
        raise ValueError('related must be between 0 and 1')
    if signal.decision is not None and signal.decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    if signal.next_need_k is not None and signal.next_need_k < 0:
        raise ValueError('next_need_k must be non-negative')
    if signal.related is None and signal.decision is None and signal.next_need_k is None and not allow_unknown:
        raise ValueError('a signal needs --related, --decision or --next-need-k')
    with _signal_lock(root):
        data = _load(root)
        old = data.get(agent)
        if (preserve_after is not None and isinstance(old, dict)
                and old.get('by') != signal.by and old.get('next_task') in ('', signal.next_task)
                and type(old.get('at')) in (int, float) and old['at'] >= preserve_after):
            return  # A fresh explicit human/caller judgement wins over automatic overlap.
        data[agent] = asdict(signal)
        _write_signals(root, data)


def latest(root, agent: str) -> Signal | None:
    raw = _load(root).get(agent)
    if not isinstance(raw, dict):
        return None
    try:
        return Signal(**{k: raw[k] for k in Signal.__dataclass_fields__ if k in raw})
    except TypeError:
        return None


def clear(root, agent: str) -> None:
    """A cycle consumes its signal; concurrent handoffs retain theirs."""
    with _signal_lock(root):
        data = _load(root)
        if data.pop(agent, None) is not None:
            _write_signals(root, data)


def _cache_window(model, policy):
    if not isinstance(model, str):
        return None
    # More specific configured patterns win, independently of TOML key order.
    matches = [(len(key.replace('*', '').replace('?', '')), key, value)
               for key, value in policy.model_cache_ttl_seconds.items()
               if fnmatch.fnmatchcase(model, key)]
    return max(matches)[2] if matches else None


def read_cache(transcript: str | Path | None, *, policy: Policy | None = None,
               model: str | None = None) -> Cache:
    """Read measured request timing; name every unmeasured retention estimate.

    Claude TTL writes are direct evidence. Codex token_count records describe
    usage, not retention; configured model windows are labelled assumptions.
    Reference: https://developers.openai.com/api/docs/guides/prompt-caching
    A minimum API lifetime is not an eviction deadline or subscription promise.
    """
    if not transcript:
        return Cache()
    from .context_spend import _reverse_lines
    policy = policy or Policy()
    last = ttl = provider = observed_model = cached = written = None
    seen = scanned = byte_count = 0

    def count(value):
        return value if type(value) is int and value >= 0 else None

    try:
        with Path(transcript).open('rb') as fh:
            for line in _reverse_lines(fh):
                scanned += 1
                byte_count += len(line)
                if scanned > 2000 or byte_count > 2 * 1024 * 1024:
                    break
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict) or rec.get('isSidechain'):
                    continue
                payload = rec.get('payload')
                payload = payload if isinstance(payload, dict) else {}
                if provider == 'codex' and rec.get('type') == 'turn_context':
                    candidate = payload.get('model')
                    if isinstance(candidate, str) and candidate:
                        observed_model = candidate
                        break
                msg = rec.get('message')
                msg = msg if isinstance(msg, dict) else {}
                usage = msg.get('usage')
                kind = 'claude'
                if (rec.get('type') == 'event_msg' and payload.get('type') == 'token_count'):
                    info = payload.get('info')
                    usage = info.get('last_token_usage') if isinstance(info, dict) else None
                    kind = 'codex'
                if not isinstance(usage, dict) or count(usage.get('input_tokens')) is None:
                    continue
                if provider is None:
                    provider = kind
                    candidate = msg.get('model') if kind == 'claude' else payload.get('model')
                    observed_model = candidate if isinstance(candidate, str) and candidate else None
                    try:
                        stamp = datetime.fromisoformat(rec['timestamp'].replace('Z', '+00:00'))
                        last = stamp.timestamp() if stamp.tzinfo is not None else None
                    except (KeyError, AttributeError, ValueError, OverflowError):
                        pass
                    cached = count(usage.get('cached_input_tokens' if kind == 'codex' else 'cache_read_input_tokens'))
                    written = count(usage.get('cache_write_input_tokens' if kind == 'codex' else 'cache_creation_input_tokens'))
                if kind != provider:
                    break
                if provider == 'codex':
                    if observed_model:
                        break
                    continue  # Only the context preceding the newest usage names its model.
                candidate = msg.get('model')
                if observed_model and candidate and candidate != observed_model:
                    break  # Never borrow a different model's older cache-write TTL.
                seen += 1
                split = usage.get('cache_creation')
                if isinstance(split, dict):
                    if (count(split.get('ephemeral_1h_input_tokens')) or 0) > 0:
                        ttl = 3600
                    elif (count(split.get('ephemeral_5m_input_tokens')) or 0) > 0:
                        ttl = 300
                if ttl is not None or seen >= TTL_SCAN_RECORDS:
                    break
    except OSError:
        return Cache()
    if provider is None:
        return Cache()
    resolved_model = observed_model or (model if isinstance(model, str) and model else None)
    basis = 'observed cache-write TTL' if ttl is not None else 'unknown'
    if ttl is None:
        ttl = _cache_window(resolved_model, policy)
        if ttl is not None:
            origin = 'transcript model' if observed_model else 'configured model'
            basis = 'assumed model policy (' + origin + '); eviction unmeasured'
    return Cache(last, ttl, provider, resolved_model, basis, cached, written)


# Only structured work evidence goes here; never compare whole conversations.
_WORK_PATH = re.compile(r'(?<![\w/])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:py|rs|go|js|ts|tsx|sh|toml|yaml|yml|json|md)\b')


def work_facts(item):
    def get(key, default=None):
        return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)
    labels = get('labels', ())
    labels = [v for v in labels if isinstance(v, str)] if isinstance(labels, (list,tuple,set)) else []
    repos = [v.split(':',1)[1] for v in labels if v.startswith(('repo:', 'project:'))]
    for key in ('repo', 'repository'):
        if isinstance(get(key), str) and get(key):
            repos.append(get(key))
    text = re.sub(r'https?://\S+', '', str(get('description', '') or '')[:16000])
    paths = {v for v in _WORK_PATH.findall(text)
             if v.split('/')[0] not in {'home','tmp','run','etc','var'}}
    files = get('files', ())
    if isinstance(files, (list,tuple)):
        paths.update(v for v in files if isinstance(v,str) and _WORK_PATH.fullmatch(v))
    return dict(item=str(get('id','')), repos=sorted(set(repos))[:32],
                paths=sorted(paths)[:64], labels=sorted(set(labels))[:64])


def _facts_path(root, agent):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', agent):
        raise ValueError('invalid work-facts agent')
    return Path(root) / 'notify' / 'work_facts' / (agent + '.json')


def previous_work(root, agent):
    try:
        path = _facts_path(root, agent)
        if path.stat().st_size > 32768:
            return None
        value = json.loads(path.read_text())
        if (not isinstance(value,dict) or not isinstance(value.get('item'),str)
                or not all(isinstance(value.get(k),list) and all(isinstance(v,str) for v in value[k])
                           for k in ('repos','paths','labels'))):
            return None
        return value
    except (OSError, ValueError):
        return None


def overlap(previous, current):
    """An overlap score, not a calibrated probability or semantic verdict."""
    if not previous:
        return None, 'previous verified work facts unavailable'
    if previous['item'] and previous['item'] == current['item']:
        return 1.0, 'same work item'
    shared_paths = set(previous['paths']) & set(current['paths'])
    if shared_paths:
        return 0.9, 'shared files: ' + ', '.join(sorted(shared_paths)[:3])
    shared_repos = set(previous['repos']) & set(current['repos'])
    if shared_repos:
        return 0.5, 'shared repository; file overlap unmeasured'
    scopes = lambda facts: {v for v in facts['labels'] if v.startswith(('area:', 'b:', 'scope:'))}
    if scopes(previous) & scopes(current):
        return 0.5, 'shared named work scope; file overlap unmeasured'
    roots = lambda facts: {p.split('/')[0] for p in facts['paths']} - {'src','lib','docs','tests','scripts','ansible','include'}
    if roots(previous) & roots(current):
        return 0.5, 'shared named source package; exact file overlap absent'
    if previous['repos'] and current['repos']:
        return 0.2, 'different explicit repositories'
    return None, 'insufficient repository/file facts; absence is not unrelatedness'


def handoff_preview(root, item, sit, policy):
    facts = work_facts(item)
    sit = replace(sit, next_task=facts['item'])
    related, reason = overlap(previous_work(root, sit.agent), facts)
    signal = Signal('st-handoff-overlap', sit.now, facts['item'], related=related, reason=reason)
    explicit = latest(root, sit.agent)
    if (explicit and explicit.by != signal.by and explicit.next_task in ('', facts['item'])
            and 0 <= sit.now-explicit.at <= policy.signal_max_age_minutes*60):
        signal = explicit
    advice = decide(sit, signal, policy)
    score = 'UNKNOWN' if signal.related is None else f'{signal.related:.2f}'
    idle = 'UNKNOWN' if sit.idle_seconds is None else f'{sit.idle_seconds:.0f}s'
    ttl = 'UNKNOWN' if sit.cache.ttl_seconds is None else f'{sit.cache.ttl_seconds}s'
    basis = sit.cache.ttl_source or 'legacy configured window'
    notice = (f'cycle advice {advice.decision}: relatedness={score}, idle={idle}, '
              f'TTL={ttl} ({basis}); {signal.reason}; {advice.why}')
    return dict(signal=signal, facts=facts, advice=advice, notice=notice,
                preserve_after=sit.now-policy.signal_max_age_minutes*60)


def record_handoff(root, agent, preview):
    """Only called after a verified dispatch and assignment readback."""
    path = _facts_path(root, agent)
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as f:
        json.dump(preview['facts'], f)
        temp = f.name
    try:
        os.replace(temp,path)
    finally:
        Path(temp).unlink(missing_ok=True)
    if preview['signal'].by == 'st-handoff-overlap':
        post(root, agent, preview['signal'], allow_unknown=True,
             preserve_after=preview['preserve_after'])
