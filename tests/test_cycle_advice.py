"""cycle_advice: keep-or-cycle at a handoff, from depth, cache timing and a posted signal.

The property that matters most is the unconfigured one: with nothing posted, the
advice is DEFAULT and the fleet behaves exactly as before. Every other test here
shows the advice saying something a caller would act on, including no.
"""
from __future__ import annotations

import json

import pytest

import shantytown.cli as cli
from shantytown import config
from shantytown import cycle_advice as ca

NOW = 1_800_000_000.0


def _sit(depth=80, idle=None, ttl=300, next_task="aegis-a"):
    cache = ca.Cache(None if idle is None else NOW - idle, ttl)
    return ca.Situation("ada", depth, 400.0, next_task, cache, NOW)


def _sig(related=None, decision=None, age=0, next_task="aegis-a"):
    return ca.Signal("jev", NOW - age, next_task, related, decision)


def test_no_signal_decides_nothing():
    assert ca.decide(_sit(idle=3600), None).decision == ca.DEFAULT


def test_the_cycle_line_beats_any_signal():
    advice = ca.decide(_sit(depth=410), _sig(related=0.99))
    assert advice.decision == ca.CYCLE
    assert ca.decide(_sit(depth=410), _sig(decision="keep")).decision == ca.CYCLE


def test_strong_relatedness_keeps():
    assert ca.decide(_sit(depth=200, idle=3600), _sig(related=0.9)).decision == ca.KEEP


def test_unrelated_cycles():
    assert ca.decide(_sit(depth=80, idle=10), _sig(related=0.1)).decision == ca.CYCLE


def test_a_lapsed_cache_flips_a_middling_signal_to_cycle():
    warm = ca.decide(_sit(depth=80, idle=10), _sig(related=0.6))
    lapsed = ca.decide(_sit(depth=80, idle=600), _sig(related=0.6))
    assert warm.decision == ca.KEEP, warm.render()
    assert lapsed.decision == ca.CYCLE, lapsed.render()
    assert lapsed.cache_lapsed is True and lapsed.keep_cost_k > warm.keep_cost_k


def test_the_1h_ttl_is_not_lapsed_at_ten_minutes():
    assert ca.decide(_sit(idle=600, ttl=3600), _sig(related=0.6)).cache_lapsed is False


def test_unknown_idle_is_priced_warm_not_lapsed():
    advice = ca.decide(_sit(depth=80, idle=None), _sig(related=0.6))
    assert advice.cache_lapsed is None
    assert advice.decision == ca.KEEP


def test_a_stale_signal_is_ignored():
    advice = ca.decide(_sit(), _sig(related=0.1, age=3 * 3600))
    assert advice.decision == ca.DEFAULT and "old" in advice.why


def test_a_signal_about_another_task_is_ignored():
    advice = ca.decide(_sit(next_task="aegis-b"), _sig(related=0.1))
    assert advice.decision == ca.DEFAULT and "aegis-b" in advice.why


def test_a_posted_decision_is_honoured_below_the_line():
    assert ca.decide(_sit(), _sig(decision="cycle")).decision == ca.CYCLE


def test_post_refuses_nonsense(tmp_path):
    with pytest.raises(ValueError):
        ca.post(tmp_path, "ada", ca.Signal("x", NOW, related=1.5))
    with pytest.raises(ValueError):
        ca.post(tmp_path, "ada", ca.Signal("x", NOW))
    assert ca.latest(tmp_path, "ada") is None


def test_post_latest_clear_round_trip(tmp_path):
    ca.post(tmp_path, "ada", ca.Signal("jev", NOW, "aegis-a", 0.7))
    assert ca.latest(tmp_path, "ada").related == 0.7
    ca.clear(tmp_path, "ada")
    assert ca.latest(tmp_path, "ada") is None


def _usage(ts, h1=0, m5=0, read=1000):
    return json.dumps({"timestamp": ts, "message": {"usage": {
        "input_tokens": 2, "cache_read_input_tokens": read,
        "cache_creation_input_tokens": h1 + m5,
        "cache_creation": {"ephemeral_1h_input_tokens": h1,
                           "ephemeral_5m_input_tokens": m5}}}})


def test_read_cache_finds_the_ttl_behind_a_fully_cached_turn(tmp_path):
    t = tmp_path / "s.jsonl"
    t.write_text("\n".join([_usage("2026-09-25T18:00:00Z", h1=500),
                            _usage("2026-09-25T18:05:00.500Z")]) + "\n")
    cache = ca.read_cache(t)
    assert cache.ttl_seconds == 3600
    assert cache.last_at == pytest.approx(1790359500.5)


def test_read_cache_says_unknown_rather_than_guessing(tmp_path):
    assert ca.read_cache(tmp_path / "missing.jsonl") == ca.Cache()
    t = tmp_path / "s.jsonl"
    t.write_text(_usage("2026-09-25T18:00:00Z") + "\n")
    assert ca.read_cache(t).ttl_seconds is None


def test_config_table(tmp_path):
    (tmp_path / "shantytown.toml").write_text(
        "[cycle_advice]\nkeep_at = 0.9\nexpected_turns = 5\n")
    policy = config.load(tmp_path).cycle_advice
    assert policy.keep_at == 0.9 and policy.expected_turns == 5
    assert config.load(tmp_path / "absent").cycle_advice == ca.Policy()


@pytest.mark.parametrize("body", ["bogus = 1", "keep_at = 2", "expected_turns = 2.5",
                                  "keep_at = true"])
def test_config_refuses_bad_values(tmp_path, body):
    (tmp_path / "shantytown.toml").write_text(f"[cycle_advice]\n{body}\n")
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


def test_cli_post_then_read_back(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_cycle_anchor_bead", lambda a, agent: "aegis-a")
    root = ["--root", str(tmp_path)]
    assert cli.main([*root, "agent", "advise", "ada", "--related", "0.1"]) == cli.REFUSED
    assert cli.main([*root, "agent", "advise", "ada", "--related", "0.1",
                     "--by", "jev"]) == cli.OK
    capsys.readouterr()
    assert cli.main([*root, "agent", "advise", "ada", "--json"]) == cli.OK
    out = json.loads(capsys.readouterr().out)
    assert out["signal"]["by"] == "jev" and out["signal"]["next_task"] == "aegis-a"
    # No transcript recorded: depth unknown, so a middling signal cannot be priced,
    # but a clearly unrelated one still says cycle.
    assert out["depth_k"] is None and out["advice"]["decision"] == ca.CYCLE


# --- the bounds: never ask past the line, never hand over an unbounded brief ----

def test_always_cycle_above_k_overrides_a_keep_and_says_do_not_ask():
    policy = ca.Policy(always_cycle_above_k=250)
    sit = _sit(depth=260)
    assert ca.decide(sit, _sig(related=0.99), policy).decision == ca.CYCLE
    assert ca.decide(sit, None, policy).decision == ca.CYCLE
    assert ca.should_ask(sit, policy) is False
    assert ca.should_ask(_sit(depth=100), policy) is True


def test_unknown_depth_is_not_asked_about():
    assert ca.should_ask(_sit(depth=None), ca.Policy()) is False


def test_the_brief_is_bounded_and_the_next_task_survives_a_huge_checkpoint():
    policy = ca.Policy(max_brief_chars=1000)
    out = ca.brief([("current_session", "x" * 750_000),
                    ("next_task", "aegis-b extend create_advisory")], 400, policy)
    assert sum(len(v) for v in out["parts"].values()) <= 400
    assert out["parts"]["next_task"] == "aegis-b extend create_advisory"
    assert out["truncated"] is True
    bigger = ca.brief([("current_session", "x" * 750_000)], 10**9, policy)
    assert len(bigger["parts"]["current_session"]) == 1000, "clamped to the max"


def test_a_brief_that_fits_is_not_marked_truncated():
    out = ca.brief([("next_task", "short")], 1500, ca.Policy())
    assert out["truncated"] is False and out["parts"] == {"next_task": "short"}


def test_cli_json_brief_carries_the_checkpoint_bounded(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_cycle_anchor_bead", lambda a, agent: "aegis-a")
    note = tmp_path / "handoff.md"
    note.write_text("y" * 100_000)
    assert cli.main(["--root", str(tmp_path), "agent", "advise", "ada", "--json",
                     "--checkpoint-file", str(note), "--brief-chars", "300"]) == cli.OK
    out = json.loads(capsys.readouterr().out)
    assert out["ask"] is False, "depth unknown: nothing to ask"
    assert len(out["brief"]["parts"]["current_session"]) <= 300
    assert out["brief"]["truncated"] is True


# --- predicted need: cycle at the boundary rather than mid-task -----------------

def test_a_big_next_task_cycles_now_even_when_related():
    advice = ca.decide(_sit(depth=200), ca.Signal("jev", NOW, "aegis-a", 0.95,
                                                   next_need_k=250))
    assert advice.decision == ca.CYCLE and "mid-task" in advice.why


def test_a_small_next_task_leaves_relatedness_to_decide():
    advice = ca.decide(_sit(depth=200), ca.Signal("jev", NOW, "aegis-a", 0.95,
                                                   next_need_k=80))
    assert advice.decision == ca.KEEP


def test_need_alone_that_fits_decides_nothing():
    advice = ca.decide(_sit(depth=100), ca.Signal("jev", NOW, "aegis-a", next_need_k=50))
    assert advice.decision == ca.DEFAULT


def test_the_default_hard_limit_is_350k():
    assert ca.Policy().always_cycle_above_k == 350
    assert ca.decide(_sit(depth=355), None).decision == ca.CYCLE
    assert ca.should_ask(_sit(depth=340), ca.Policy()) is True


def test_cli_posts_need(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_cycle_anchor_bead", lambda a, agent: "aegis-a")
    root = ["--root", str(tmp_path)]
    assert cli.main([*root, "agent", "advise", "ada", "--next-need-k", "-5",
                     "--by", "jev"]) == cli.REFUSED
    assert cli.main([*root, "agent", "advise", "ada", "--next-need-k", "120",
                     "--by", "jev"]) == cli.OK
    assert ca.latest(tmp_path, "ada").next_need_k == 120


def _codex_cache_log(path, model='gpt-6.1-sol'):
    records=[{'timestamp':'2026-11-04T09:00:00Z','type':'turn_context','payload':{'model':model}},
             {'timestamp':'2026-11-04T09:01:00Z','type':'event_msg','payload':{'type':'token_count',
              'info':{'last_token_usage':{'input_tokens':12000,'cached_input_tokens':11000,
                                         'cache_write_input_tokens':1000}}}}]
    path.write_text(''.join(json.dumps(r)+'\n' for r in records))


def test_codex_usage_time_and_model_window_are_explicit_assumptions(tmp_path):
    p=tmp_path/'codex.jsonl';_codex_cache_log(p)
    cache=ca.read_cache(p)
    assert cache.last_at == 1793782860
    assert cache.ttl_seconds == 1800 and cache.model == 'gpt-6.1-sol'
    assert cache.cached_input_tokens == 11000 and cache.cache_write_input_tokens == 1000
    assert cache.provider == 'codex' and cache.ttl_source.startswith('assumed')
    assert ca.cache_lapsed(ca.Situation('a',80,400,cache=cache,now=cache.last_at+1801),ca.Policy()) is True


def test_codex_unknown_model_does_not_become_generic_expired_cache(tmp_path):
    p=tmp_path/'codex.jsonl';_codex_cache_log(p,model='unlisted-model')
    cache=ca.read_cache(p)
    assert cache.last_at is not None and cache.ttl_seconds is None
    assert ca.cache_lapsed(ca.Situation('a',80,400,cache=cache,now=cache.last_at+99999),ca.Policy()) is None


def test_model_policy_is_configurable_specific_and_strict(tmp_path):
    (tmp_path/'shantytown.toml').write_text('[cycle_advice.model_cache_ttl_seconds]\n"gpt-*"=300\n"gpt-6.1-sol"=7200\n')
    policy=config.load(tmp_path).cycle_advice
    p=tmp_path/'codex.jsonl';_codex_cache_log(p)
    assert ca.read_cache(p,policy=policy).ttl_seconds == 7200
    for value in ['true','0','-1','1.5','"300"']:
        (tmp_path/'shantytown.toml').write_text('[cycle_advice.model_cache_ttl_seconds]\n"gpt-*"='+value+'\n')
        with pytest.raises(config.ConfigError):config.load(tmp_path)


def test_configured_model_fallback_is_labelled_and_not_newer_turn_context(tmp_path):
    p=tmp_path/'codex.jsonl';_codex_cache_log(p,model=None)
    # A later, unfinished turn's model must not be assigned to older usage.
    with p.open('a') as f:f.write(json.dumps({'type':'turn_context','payload':{'model':'unlisted-model'}})+'\n')
    cache=ca.read_cache(p,model='gpt-6.1-sol')
    assert cache.ttl_seconds == 1800 and 'configured model' in cache.ttl_source


def test_claude_recorded_ttl_overrides_model_policy_and_never_borrows_another_model(tmp_path):
    p=tmp_path/'claude.jsonl'
    old=json.loads(_usage('2026-11-04T09:00:00Z',h1=12));old['message']['model']='claude-old'
    new=json.loads(_usage('2026-11-04T09:01:00Z'));new['message']['model']='claude-new'
    p.write_text(json.dumps(old)+'\n'+json.dumps(new)+'\n')
    cache=ca.read_cache(p)
    assert cache.ttl_seconds == 300 and cache.ttl_source.startswith('assumed')
    p.write_text(json.dumps(old)+'\n')
    cache=ca.read_cache(p)
    assert cache.ttl_seconds == 3600 and cache.ttl_source == 'observed cache-write TTL'


def _work(item, repo, path):
    return dict(id=item,labels=['repo:'+repo] if repo else [],description=path)


def test_automatic_cold_handoff_is_unknown_and_preview_writes_nothing(tmp_path):
    sit=_sit();preview=ca.handoff_preview(tmp_path,_work('a','repo-a','src/a.py'),sit,ca.Policy())
    assert preview['signal'].related is None and preview['advice'].decision == ca.DEFAULT
    assert not (tmp_path/'notify').exists()
    ca.record_handoff(tmp_path,'ada',preview)
    assert ca.latest(tmp_path,'ada').related is None
    assert ca.previous_work(tmp_path,'ada')['item']=='a'


def test_related_work_and_elapsed_policy_window_notice(tmp_path):
    old=ca.handoff_preview(tmp_path,_work('old','repo-a','src/a.py'),_sit(),ca.Policy())
    ca.record_handoff(tmp_path,'ada',old)
    same=ca.handoff_preview(tmp_path,_work('new','repo-a','src/a.py'),_sit(),ca.Policy())
    assert same['advice'].decision==ca.KEEP and same['signal'].related==.9
    middle=_work('new','repo-a','src/b.py')
    warm=ca.handoff_preview(tmp_path,middle,_sit(depth=80,idle=10),ca.Policy())
    cold=ca.handoff_preview(tmp_path,middle,_sit(depth=80,idle=301),ca.Policy())
    assert warm['advice'].decision==ca.KEEP and cold['advice'].decision==ca.CYCLE
    assert 'relatedness=0.50' in cold['notice'] and 'idle=301s' in cold['notice']
    unrelated=ca.handoff_preview(tmp_path,_work('other','repo-b','lib/b.rs'),_sit(),ca.Policy())
    assert unrelated['advice'].decision==ca.CYCLE


def test_absent_or_merely_different_files_are_not_unrelatedness(tmp_path):
    first=ca.handoff_preview(tmp_path,_work('old',None,'alpha/a.py'),_sit(),ca.Policy())
    ca.record_handoff(tmp_path,'ada',first)
    for next_work in [_work('new',None,''),_work('new',None,'beta/b.py')]:
        assert ca.handoff_preview(tmp_path,next_work,_sit(),ca.Policy())['signal'].related is None


def test_explicit_fresh_judgement_wins_over_automatic_preview_and_commit(tmp_path):
    sit=_sit(next_task='new')
    ca.post(tmp_path,'ada',ca.Signal('human',NOW,'new',related=.95))
    preview=ca.handoff_preview(tmp_path,_work('new','repo-b','src/b.py'),sit,ca.Policy())
    assert preview['signal'].by=='human'
    # A newer manual call arriving between preview and record must also survive.
    ca.post(tmp_path,'ada',ca.Signal('jev',NOW+1,'new',related=.7))
    ca.record_handoff(tmp_path,'ada',preview)
    assert ca.latest(tmp_path,'ada').by=='jev'


def test_concurrent_posts_retain_other_agents_and_clear_is_scoped(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    def write(n):ca.post(tmp_path,str(n),ca.Signal('fixture',NOW,related=.6))
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(write,range(32)))
    assert all(ca.latest(tmp_path,str(n)) is not None for n in range(32))
    ca.clear(tmp_path,'0')
    assert ca.latest(tmp_path,'0') is None
    assert all(ca.latest(tmp_path,str(n)) is not None for n in range(1,32))


def test_advice_uses_role_or_account_model_resolution_when_card_model_is_unset(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from shantytown import harness, runtime_update
    from shantytown.protocols import Agent
    p=tmp_path/'codex.jsonl';_codex_cache_log(p,model=None)
    folder=tmp_path/'context_budget';folder.mkdir()
    (folder/'ada.json').write_text(json.dumps({'payload':{'transcript_path':str(p)}}))
    monkeypatch.setattr(harness,'resolve_model',lambda card,root=None:'gpt-6.1-sol')
    monkeypatch.setattr(runtime_update,'for_agent',lambda *args:runtime_update.Evidence('exact','2.1.317','2.1.318'))
    sit,_=cli._advise_situation(SimpleNamespace(root=tmp_path),'ada',config.Config(),
                               next_task='next',card=Agent(name='ada',role='worker'))
    assert sit.cache.model=='gpt-6.1-sol' and sit.cache.ttl_seconds==1800
    assert 'configured model' in sit.cache.ttl_source
    assert sit.next_task=='next'
    assert (sit.running_version,sit.installed_version,sit.session_id)==('2.1.317','2.1.318','exact')
