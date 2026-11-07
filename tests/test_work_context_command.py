"""The explicit reader preserves deployment selection and exact identity."""
from contextlib import nullcontext
from pathlib import Path
import tomllib

from shantytown import cli, query_first, work_context, work_context_command as command


def test_command_uses_existing_deployment_tracker(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SHANTY_ONTO_NS", "urn:fixture:")
    tracker = object()
    seen = []
    monkeypatch.setattr(command, "resolve_root", lambda root: (tmp_path, "explicit"))
    monkeypatch.setattr(command, "command_environment", lambda root, how: nullcontext())
    monkeypatch.setattr(cli, "_raw_tracker", lambda args: seen.append(args.root) or tracker)
    def read(actual, item, **kwargs):
        assert actual is tracker
        assert item == "test-123"
        assert kwargs["onto"] == "urn:fixture:"
        return work_context.Context(item)
    monkeypatch.setattr(work_context, "context", read)
    assert command.main(["--root", str(tmp_path), "test-123"]) == 0
    assert seen == [tmp_path]
    assert "EXACT CONTEXT for test-123" in capsys.readouterr().out


def test_failed_selection_is_unknown_without_fallback(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(command, "resolve_root", lambda root: (tmp_path, "explicit"))
    monkeypatch.setattr(command, "command_environment", lambda root, how: nullcontext())
    def fail(args):
        raise OSError("private diagnostic must not escape")
    monkeypatch.setattr(cli, "_raw_tracker", fail)
    assert command.main(["test-123"]) == 1
    text = capsys.readouterr().out
    assert "UNKNOWN (OSError)" in text
    assert "private diagnostic" not in text


def test_directive_places_exact_read_before_semantic_search():
    text = query_first.DIRECTIVE
    assert text.index("st-context <id>") < text.index("quipu_search")
    assert "NO CONTEXT is not absence" in text


def test_console_entry_point_targets_the_tested_reader():
    manifest = Path(__file__).resolve().parents[1] / "pyproject.toml"
    scripts = tomllib.loads(manifest.read_text())["project"]["scripts"]
    assert scripts["st-context"] == "shantytown.work_context_command:main"
