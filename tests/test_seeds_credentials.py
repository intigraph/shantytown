"""Private/inert strict launcher controls; no provider or network access."""
import hashlib
import json
import os
import stat
import subprocess

import pytest

from shantytown import crew_credentials as C
from shantytown import seeds_credentials as S

pytestmark = pytest.mark.skipif(not hasattr(os, "memfd_create"),
                                reason="sealed anonymous Linux descriptors required")


@pytest.fixture
def chosen(tmp_path):
    directory = tmp_path / "provision"
    directory.mkdir()
    principal = "urn:crew:alice"
    value = "own-inert-fixture"
    ref = dict(audience="quipu", project="fixture", path="/mcp-crew/alice",
               key="CREW_" + hashlib.sha256(principal.encode()).hexdigest()[:24].upper() + "_QUIPU",
               secret_id="id", secret_version=1,
               token_sha256=hashlib.sha256(value.encode()).hexdigest(), shared_key="SHARED")
    config = dict(version=1, enabled=True, agents={
        "alice": dict(principal=principal, servers={}, quipu_cli=ref)})
    path = directory / "crew-credentials.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    return tmp_path, value, config, path


def admitted():
    return subprocess.CompletedProcess([], 0, json.dumps(dict(
        contract="seeds-credential-admission/v1", admitted=True,
        destination="https://example.org", destination_binding=True)).encode(), b"")


def test_admission_before_fetch_private_fd_and_parent_unchanged(chosen):
    root, value, _, _ = chosen
    parent = {key: "foreign-inert" for key in S._INPUTS}
    parent["PATH"] = os.environ["PATH"]
    before = dict(parent)
    order, fds = [], []

    def runner(command, **kwargs):
        assert value not in json.dumps(command) + json.dumps(kwargs["env"])
        assert not any(kwargs["env"].get(k) == "foreign-inert" for k in S._INPUTS)
        if "--credential-admission" in command:
            order.append("admit")
            assert "pass_fds" not in kwargs
            return admitted()
        order.append("execute")
        fd, = kwargs["pass_fds"]
        fds.append(fd)
        meta = os.fstat(fd)
        assert stat.S_ISREG(meta.st_mode) and meta.st_nlink == 0
        assert stat.S_IMODE(meta.st_mode) == 0o600
        assert os.pread(fd, 4096, 0).decode() == value
        assert kwargs["env"]["SEEDS_QUIPU_CREDENTIAL_DESTINATION"] == "https://example.org"
        with pytest.raises(OSError):
            os.write(fd, b"mutation")
        return subprocess.CompletedProcess(command, 0, b"ok", b"")

    def fetch(*_):
        order.append("fetch")
        return value

    result = S.run(["show", "fixture"], root=root, agent="alice", env=parent,
                   runner=runner, fetch=fetch)
    assert result.returncode == 0 and order == ["admit", "fetch", "execute"]
    assert parent == before
    with pytest.raises(OSError):
        os.fstat(fds[0])


@pytest.mark.parametrize("proof", [
    subprocess.CompletedProcess([], 2, b"", b"unsupported"),
    subprocess.CompletedProcess([], 0, b"not-json", b""),
    subprocess.CompletedProcess([], 0, b'{"admitted":true}', b""),
    subprocess.CompletedProcess([], 0, b'null', b""),
])
def test_refused_unsupported_or_malformed_admission_never_fetches(chosen, proof):
    root, _, _, _ = chosen
    calls = []
    with pytest.raises(C.Unavailable):
        S.run(["show", "fixture"], root=root, agent="alice",
              runner=lambda *a, **k: proof,
              fetch=lambda *a: calls.append(1))
    assert calls == []


@pytest.mark.parametrize("value", [None, "wrong", "bad\nvalue", "x" * 4097])
def test_provider_refusal_or_bad_value_never_executes_or_falls_back(chosen, value):
    root, _, _, _ = chosen
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        assert "--credential-admission" in command
        return admitted()
    def fetch(*args):
        if value is None:
            raise RuntimeError("private-body-must-not-escape")
        return value
    with pytest.raises(C.Unavailable) as error:
        S.run(["show", "fixture"], root=root, agent="alice", runner=runner, fetch=fetch)
    assert "private-body" not in str(error.value) and len(calls) == 1


@pytest.mark.parametrize("failure", [KeyboardInterrupt, subprocess.TimeoutExpired])
def test_final_failure_closes_fd(chosen, failure):
    root, value, _, _ = chosen
    fds = []
    def runner(command, **kwargs):
        if "--credential-admission" in command:
            return admitted()
        fds.extend(kwargs["pass_fds"])
        if failure is subprocess.TimeoutExpired:
            raise failure("fixture", 1)
        raise failure
    with pytest.raises(failure):
        S.run(["show", "fixture"], root=root, agent="alice", runner=runner,
              fetch=lambda *a: value)
    with pytest.raises(OSError):
        os.fstat(fds[0])


def test_next_deselected_command_uses_native_defaults_not_inherited_identity(chosen):
    root, _, config, path = chosen
    config["enabled"] = False
    path.write_text(json.dumps(config))
    env = {key: "foreign-inert" for key in S._INPUTS}
    env["XDG_CONFIG_HOME"] = "/fixture/user-config"
    def runner(command, **kwargs):
        assert command == ["sd", "show", "fixture"]
        assert all(key not in kwargs["env"] for key in S._INPUTS)
        assert kwargs["env"]["XDG_CONFIG_HOME"] == env["XDG_CONFIG_HOME"]
        assert "pass_fds" not in kwargs
        return subprocess.CompletedProcess(command, 0, b"native-default-positive", b"")
    assert S.run(["show", "fixture"], root=root, agent="alice", env=env,
                 runner=runner, fetch=lambda *a: pytest.fail("deselected fetch")).returncode == 0


def test_unsupported_descriptor_platform_never_fetches(chosen, monkeypatch):
    root, _, _, _ = chosen
    monkeypatch.delattr(os, "memfd_create")
    with pytest.raises(C.Unavailable):
        S.run(["show", "fixture"], root=root, agent="alice",
              runner=lambda *a, **k: pytest.fail("unsupported platform executed"),
              fetch=lambda *a: pytest.fail("unsupported platform fetched"))


@pytest.mark.parametrize("value", ["own-inert-fixture", 'quote"slash\\fixture'])
def test_child_echo_is_redacted_without_changing_operation_status(chosen, value):
    root, _, config, path = chosen
    config["agents"]["alice"]["quipu_cli"]["token_sha256"] = hashlib.sha256(value.encode()).hexdigest()
    path.write_text(json.dumps(config))
    forms = [value, json.dumps(value)[1:-1]]
    forms.append(json.dumps(forms[-1])[1:-1])
    def runner(command, **kwargs):
        if "--credential-admission" in command:
            return admitted()
        return subprocess.CompletedProcess(command, 7, "|".join(forms).encode(), "|".join(forms).encode())
    result = S.run(["show", "fixture"], root=root, agent="alice", runner=runner,
                   fetch=lambda *a: value)
    assert all(form.encode() not in result.stdout + result.stderr for form in forms)
    assert b"[REDACTED]" in result.stdout
    assert result.returncode == 7  # Never turn an uncertain/failed write into a retry signal.


@pytest.mark.parametrize("principal", ["urn:crew:alice", "https://example.org/ontology/alice"])
def test_canonical_principal_opaque_declaration_keeps_provider_binding(chosen, principal):
    root, value, config, path = chosen
    row = config["agents"]["alice"]
    row["principal"] = principal
    row["quipu_cli"]["key"] = "CREW_" + hashlib.sha256(principal.encode()).hexdigest()[:24].upper() + "_QUIPU"
    path.write_text(json.dumps(config))
    before = path.read_bytes()
    provider, declarations = [], []
    def fetch(provider_config, ref):
        provider.append(ref["key"])
        return value
    def runner(command, **kwargs):
        if "--credential-admission" in command:
            assert provider == []
            return admitted()
        declarations.append(kwargs["env"]["SEEDS_QUIPU_CREDENTIAL_PRINCIPAL"])
        assert declarations[-1] == (
            "principal-sha256:" + hashlib.sha256(principal.encode()).hexdigest())
        return subprocess.CompletedProcess(command, 0, b"ok", b"")
    for _ in range(2):
        # Each command admits before its own fetch; repeated identity is stable.
        provider.clear()
        assert S.run(["show", "fixture"], root=root, agent="alice", runner=runner,
                     fetch=fetch).returncode == 0
        assert provider == [row["quipu_cli"]["key"]]
    assert declarations[0] == declarations[1]
    other = principal + "-distinct"
    assert declarations[0] != "principal-sha256:" + hashlib.sha256(other.encode()).hexdigest()
    assert path.read_bytes() == before
