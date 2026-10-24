#!/usr/bin/env python3
"""Packaging/readback refusal controls; synthetic data is not native acceptance.

# arming: ci; release asset publication contract invokes this script.
"""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
import os
from unittest.mock import patch

# Release source must stay clean when modules load.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publisher = load("publisher_test", ROOT / "publish_repository_share.py")
verifier = load("verifier_test", ROOT / "verify-repository-share.py")


class Publication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / "stage"
        self.stage.mkdir()
        recipe = {"model": "model.onnx", "model_sha256": "a" * 64, "tokenizer_sha256": "b" * 64, "dimension": 384}
        (self.stage / "manifest.json").write_text(json.dumps({"embedding": recipe}))
        for name in ("export.nt", "manifest.ttl", "shapes.ttl", "queries.ttl"):
            (self.stage / name).write_text("# synthetic fixture only\n")
        self.archive = self.root / "shantytown-v1.2.3-repository.pendant.tar.gz"
        self.revision = "1" * 40

    def prepare(self):
        publisher.package(self.stage, self.archive)
        sha = publisher.digest(self.archive)
        self.archive.with_name(self.archive.name + ".sha256").write_text(sha + "  " + self.archive.name + "\n")
        self.proof = {
            "schema": "quipu.repository-share-producer/v1",
            "source_repository": "scbrown/shantytown",
            "source_revision": self.revision,
            "release_tag": "v1.2.3",
            "archive_sha256": sha,
            "destination": "outward",
            "quipu_sha256": "2" * 64,
            "quipu_server_sha256": "5" * 64,
            "bobbin_sha256": "3" * 64,
            "engine_source_revision": "4" * 40,
        }
        self.proof_path = self.archive.with_name(self.archive.name + ".provenance.json")
        self.proof_path.write_text(json.dumps(self.proof))

    def test_deterministic_archive_and_exact_readback(self):
        self.prepare()
        other = self.root / "second.tar.gz"
        publisher.package(self.stage, other)
        self.assertEqual(self.archive.read_bytes(), other.read_bytes())
        self.assertEqual(verifier.verify(self.root, "v1.2.3", self.revision)["source_revision"], self.revision)

    def test_required_members_and_recipe(self):
        (self.stage / "queries.ttl").unlink()
        with self.assertRaisesRegex(ValueError, "required nonempty"):
            publisher.check_share(self.stage)
        (self.stage / "queries.ttl").write_text("# query")
        (self.stage / "manifest.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "provider-byte"):
            publisher.check_share(self.stage)

    def test_text_line_span_and_private_members_refuse(self):
        for predicate in ("content", "startLine", "endLine"):
            (self.stage / "export.nt").write_text(
                "<https://example.org/s> <http://aegis.gastown.local/ontology/" + predicate + '> "body" .\n'
            )
            with self.subTest(predicate=predicate), self.assertRaisesRegex(ValueError, "duplicates source"):
                publisher.check_share(self.stage)
        (self.stage / "export.nt").write_text("# empty synthetic")
        (self.stage / "policy-token").write_text("not a real token")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            publisher.check_share(self.stage)

    def test_foreign_repository_and_wrong_source_refuse(self):
        self.prepare()
        for field, value in [
            ("source_repository", "scbrown/quipu"),
            ("source_revision", "f" * 40),
            ("release_tag", "v9.9.9"),
            ("archive_sha256", "f" * 64),
        ]:
            self.proof_path.write_text(json.dumps({**self.proof, field: value}))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "provenance mismatch"):
                verifier.verify(self.root, "v1.2.3", self.revision)

    def test_checksum_refuses(self):
        self.prepare()
        self.archive.with_name(self.archive.name + ".sha256").write_text("wrong")
        with self.assertRaisesRegex(ValueError, "checksum"):
            verifier.verify(self.root, "v1.2.3", self.revision)

    def test_verifier_argument_refusal_leaves_checkout_clean(self):
        import shutil
        import subprocess

        source = self.root / "clean-source"
        source.mkdir()
        for name in ("verify-repository-share.py", "publish_repository_share.py"):
            shutil.copyfile(ROOT / name, source / name)
        # Isolated startup ignores inherited Python environment workarounds.
        result = subprocess.run(
            [sys.executable, "-I", str(source / "verify-repository-share.py")],
            capture_output=True, text=True, cwd=source,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("usage:", result.stderr)
        self.assertEqual(list(source.rglob("*.pyc")), [])

    def test_hold_absent_and_dangling_symlink_before_any_build(self):
        hold = self.root / "hold"
        with patch.dict(publisher.os.environ, {"QUIPU_SHARE_HOLD_FILE": str(hold)}):
            self.assertFalse(publisher.held())
            hold.symlink_to(self.root / "missing-target")
            for kind in ("dangling symlink", "regular file"):
                with self.subTest(kind=kind), patch.object(publisher, "command", side_effect=AssertionError("lookup reached")) as command:
                    self.assertTrue(publisher.held())
                    with self.assertRaisesRegex(ValueError, "held before"):
                        publisher.publish("v1.2.3", self.revision, self.root / "output")
                    command.assert_not_called()
                    self.assertFalse((self.root / "output").exists())
                hold.unlink()
                hold.write_text("synthetic hold")

    def test_unreadable_hold_fails_closed(self):
        with patch.object(Path, "lstat", side_effect=PermissionError("synthetic denied")), patch.object(publisher, "command") as command:
            with self.assertRaisesRegex(ValueError, "cannot inspect publication hold"):
                publisher.publish("v1.2.3", self.revision, self.root / "output")
            command.assert_not_called()
            self.assertFalse((self.root / "output").exists())

    def test_absent_hold_reaches_first_lookup_positive_control(self):
        hold = self.root / "absent-hold"
        with patch.dict(publisher.os.environ, {"QUIPU_SHARE_HOLD_FILE": str(hold)}), patch.object(publisher, "command", side_effect=RuntimeError("synthetic first lookup")) as command:
            with self.assertRaisesRegex(RuntimeError, "synthetic first lookup"):
                publisher.publish("v1.2.3", self.revision, self.root / "output")
            command.assert_called_once()
            self.assertFalse((self.root / "output").exists())

    def host_environment(self):
        host = self.root / "synthetic-host"
        host.mkdir()
        (host / "config-marker").write_text("fixture only")
        return {
            "HOME": str(host), "XDG_CONFIG_HOME": str(host),
            "XDG_DATA_HOME": str(host), "XDG_CACHE_HOME": str(host),
            **{key: "synthetic-fixture" for key in (
                "BOBBIN_SERVER", "BOBBIN_QUIPU_REMOTE", "BOBBIN_QUIPU_TOKEN",
                "QUIPU_SERVER", "QUIPU_DB", "QUIPU_AUTH_TOKEN",
                "QUIPU_AUTH_TOKEN_FILE", "GH_TOKEN", "GITHUB_TOKEN",
            )},
        }

    def test_command_isolates_host_configuration_and_policy_exception(self):
        builder = load("builder_environment_test", ROOT / "build-repository-share.py")
        private = self.root / "private"
        private.mkdir()
        probe = (
            "import json,os;from pathlib import Path;"
            "print(json.dumps({'host_config':(Path.home()/'config-marker').exists(),"
            "'inherited':[k for k in os.environ if k in "
            "['BOBBIN_SERVER','QUIPU_SERVER','QUIPU_DB','QUIPU_AUTH_TOKEN',"
            "'QUIPU_AUTH_TOKEN_FILE','GH_TOKEN','GITHUB_TOKEN'] or k.startswith('BOBBIN_QUIPU_')],"
            "'homes':[os.environ[k] for k in ['HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME']]}))"
        )
        with patch.dict(os.environ, self.host_environment()):
            # The explicit policy-helper exception still sees synthetic host config.
            control = json.loads(builder.command([sys.executable, "-I", "-c", probe], env=dict(os.environ), cwd=private))
            self.assertTrue(control["host_config"])
            self.assertTrue(control["inherited"])
            result = json.loads(builder.command([sys.executable, "-I", "-c", probe], cwd=private))
        self.assertFalse(result["host_config"])
        self.assertEqual(result["inherited"], [])
        self.assertEqual(len(set(result["homes"])), 4)
        for directory in result["homes"]:
            self.assertTrue(Path(directory).is_relative_to(private))
            self.assertTrue(Path(directory).is_dir())

    def test_mcp_child_isolates_host_configuration(self):
        builder = load("builder_mcp_environment_test", ROOT / "build-repository-share.py")
        child = self.root / "fixture-mcp"
        child.write_text(
            "#!" + sys.executable + "\n"
            "import json,os,sys\nfrom pathlib import Path\n"
            "for line in sys.stdin:\n"
            " r=json.loads(line)\n"
            " if 'id' not in r:continue\n"
            " isolated=not (Path.home()/'config-marker').exists() and not any(k in os.environ for k in ['QUIPU_SERVER','GH_TOKEN','BOBBIN_QUIPU_TOKEN'])\n"
            " result={} if r['id']==0 else {'content':[{'type':'text','text':json.dumps({'isolated':isolated})}]}\n"
            " print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)\n"
        )
        child.chmod(0o700)
        with patch.dict(os.environ, self.host_environment()):
            (result,) = builder.local_mcp(child, self.root / "fixture.db", [("fixture", {})])
        self.assertEqual(result, {"isolated": True})

    def test_wait_is_bounded(self):
        calls, pauses = [], []

        class Result:
            returncode = 1

        def run(args, **kwargs):
            calls.append(args)
            return Result()

        with self.assertRaisesRegex(ValueError, "bounded"):
            verifier.wait("v1.2.3", self.revision, attempts=2, pause=pauses.append, run=run)
        self.assertEqual(len(calls), 2)
        self.assertEqual(pauses, [30])


if __name__ == "__main__":
    unittest.main()
