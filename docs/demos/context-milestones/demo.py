"""Run from the repository root; isolated source fixtures, no model or host changes."""
import contextlib
import io
import json
from pathlib import Path
import tempfile

from shantytown import context_hint as ch


def run(label, extra):
    with tempfile.TemporaryDirectory(prefix="context-milestones-") as directory:
        root = Path(directory)
        (root / "shantytown.toml").write_text(
            "[session_budget]\ncontext_window=1000000\n" + extra)
        (root / "crew").mkdir()
        (root / "crew/admin.json").write_text('{"role":"administrator"}')
        transcript = root / "usage.jsonl"
        payload = dict(session_id="synthetic-demo", transcript_path=str(transcript),
                       hook_event_name="PostToolUse")
        limits = ch.policy(root, type("Card", (), {"role": "administrator", "name": "admin"})())[0]
        print(f"{label}: first={limits.nudge_at:g}% step={limits.nudge_step_pct}")
        results = []
        for tokens in (249999, 250000, 260801, 261046, 349999, 350000, 450000):
            transcript.write_text(json.dumps({"message": {"usage": {
                "input_tokens": tokens, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0}}}) + "\n")
            with contextlib.redirect_stdout(io.StringIO()):
                emitted = ch.tool_feedback(root, "admin", payload)
            results.append(emitted)
            print(f"tokens={tokens}: {'NUDGE' if emitted else 'quiet'}")
        assert not (root / "context-decisions.jsonl").exists()
        return results


if __name__ == "__main__":
    # Both paths use the candidate consumer. Old settings retain worker cadence;
    # new settings are the administrator-only deployment change.
    before = run("previous settings", "")
    after = run("administrator settings",
                "[session_budget.context_by_role.administrator]\n"
                "context_nudge_pct=25\ncontext_nudge_step_pct=10\n")
    assert before[:4] == [False] * 4
    assert after[:4] == [False, True, False, False]
    assert after[-2:] == [True, True]
