#!/usr/bin/env python3
"""Curated-source refusal controls. Lookup fixtures are not index coverage proof.

# arming: ci; release contract invokes this script.
"""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import sys

# Release source must stay clean when modules load.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("knowledge", ROOT / "scripts/build-repository-knowledge.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


builder_spec = importlib.util.spec_from_file_location("share_builder", ROOT / "scripts/build-repository-share.py")
builder = importlib.util.module_from_spec(builder_spec)
builder_spec.loader.exec_module(builder)


class ReleaseSnapshot(unittest.TestCase):
    def test_real_git_archive_excludes_untracked_key_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            (source / "README.md").write_text("tracked pointer source\n")
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "-c",
                    "user.name=fixture",
                    "-c",
                    "user.email=fixture@example.org",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            (source / "private.key").write_text("synthetic untracked sentinel")
            revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
            copied = builder.materialize_release(source, revision, root / "copied")
            self.assertEqual((copied / "README.md").read_bytes(), (source / "README.md").read_bytes())
            self.assertFalse((copied / "private.key").exists())
            self.assertEqual((source / "private.key").read_text(), "synthetic untracked sentinel")
            self.assertFalse((source / ".bobbin").exists())


class AlignmentCarrier(unittest.TestCase):
    def test_explicit_empty_positive_missing_corrupt_and_nonempty_negative(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "docs/knowledge"
            target.mkdir(parents=True)
            for name in ("alignments.ttl", "alignment-status.json"):
                shutil.copyfile(ROOT / "docs/knowledge" / name, target / name)
            self.assertIn("@prefix sssom:", builder.alignment_carrier(root))
            data = target / "alignments.ttl"
            original = data.read_text()
            data.unlink()
            with self.assertRaises(FileNotFoundError):
                builder.alignment_carrier(root)
            data.write_text(original + "<urn:x> <urn:p> <urn:y> .\n")
            with self.assertRaisesRegex(ValueError, "corrupt"):
                builder.alignment_carrier(root)
            import hashlib

            status = json.loads((target / "alignment-status.json").read_text())
            status["carrier_sha256"] = hashlib.sha256(data.read_bytes()).hexdigest()
            (target / "alignment-status.json").write_text(json.dumps(status))
            with self.assertRaisesRegex(ValueError, "mapping data"):
                builder.alignment_carrier(root)
            data.write_text("@prefix owl: <http://www.w3.org/2002/07/owl#> . <urn:x> <urn:p> <urn:y> .\n")
            status["carrier_sha256"] = hashlib.sha256(data.read_bytes()).hexdigest()
            (target / "alignment-status.json").write_text(json.dumps(status))
            with self.assertRaisesRegex(ValueError, "mapping data"):
                builder.alignment_carrier(root)


class Knowledge(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = json.loads((ROOT / "docs/knowledge/repository-knowledge.json").read_text())
        for source in {r["source"] for r in self.registry["records"]}:
            target = self.root / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)
        (self.root / "docs/knowledge").mkdir(parents=True)
        shutil.copyfile(ROOT / "docs/knowledge/cli-summary.md", self.root / "docs/knowledge/cli-summary.md")
        self.save()

    def save(self):
        (self.root / "docs/knowledge/repository-knowledge.json").write_text(json.dumps(self.registry))

    def render(self, lookup=lambda _: "actual-index-label-fixture"):
        return module.render(self.root, "1" * 40, lookup)

    def test_source_bound_nonempty_content(self):
        text = self.render()
        self.assertIn("2592000", text)
        self.assertIn("reviewAfter", text)
        self.assertIn("glossaryTerm> <https://scbrown.github.io/quechua/ns#WorkItem>", text)
        self.assertIn('knowledgeKind> "idea"', text)
        self.assertIn('interfaceKind> "file-format"', text)
        self.assertIn('supersessionStatus> "not-recorded-in-source"', text)
        self.assertIn('startHereOrder> "3"^^', text)
        self.assertNotIn("/content>", text)
        self.assertNotIn("owl#sameAs", text)

    def test_absent_or_ambiguous_index_pointer_refuses(self):
        for value in (None, False, ""):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "absent or ambiguous"):
                self.render(lambda _: value)

    def test_cli_source_edit_derives_hash_without_registry_or_review_edit(self):
        import hashlib
        registry_before = (self.root / "docs/knowledge/repository-knowledge.json").read_bytes()
        path = self.root / "shantytown/cli.py"
        path.write_text(path.read_text() + "\nPRIVATE_FIXTURE = True\n")
        text = self.render()
        self.assertIn(hashlib.sha256(path.read_bytes()).hexdigest(), text)
        self.assertEqual((self.root / "docs/knowledge/repository-knowledge.json").read_bytes(), registry_before)
        self.assertIn(self.registry["reviewed_at"], text)

    def test_changed_source_refuses(self):
        path = self.root / self.registry["records"][0]["source"]
        path.write_text(path.read_text() + "\nchanged\n")
        with self.assertRaisesRegex(ValueError, "witness changed"):
            self.render()

    def test_guessed_identity_refuses(self):
        self.registry["records"][0]["subject"] = "https://example.org/guessed"
        self.save()
        with self.assertRaisesRegex(ValueError, "source-backed"):
            self.render()

    def test_missing_required_content_refuses(self):
        self.registry["records"] = [r for r in self.registry["records"] if r["kind"] != "decision"]
        self.save()
        with self.assertRaisesRegex(ValueError, "inventory incomplete"):
            self.render()

    def test_bad_freshness_and_private_summary_refuse(self):
        self.registry["max_age_seconds"] = 0
        self.save()
        with self.assertRaisesRegex(ValueError, "freshness"):
            self.render()
        self.registry["max_age_seconds"] = 30
        self.registry["records"][0]["summary"] = "read /home/example/file"
        self.save()
        with self.assertRaisesRegex(ValueError, "private summary"):
            self.render()

    def cli_record(self):
        return next(r for r in self.registry["records"] if r["source"] == module.CLI_SOURCE)

    def test_summary_anchor_missing_changed_or_rebound_refuses(self):
        import hashlib
        anchor = self.root / module.CLI_SUMMARY
        original = anchor.read_bytes()
        anchor.unlink()
        with self.assertRaises(FileNotFoundError):
            self.render()
        anchor.write_bytes(b"Reviewed CLI scope updated explicitly.\n")
        with self.assertRaisesRegex(ValueError, "summary witness changed"):
            self.render()
        # A reviewed anchor update is explicit, and still obeys summary privacy.
        self.cli_record()["summary_sha256"] = hashlib.sha256(anchor.read_bytes()).hexdigest()
        self.save()
        self.assertIn("Reviewed CLI scope updated explicitly.", self.render())
        anchor.write_text("read /home/private/file\n")
        self.cli_record()["summary_sha256"] = hashlib.sha256(anchor.read_bytes()).hexdigest()
        self.save()
        with self.assertRaisesRegex(ValueError, "private summary"):
            self.render()

    def test_summary_anchor_path_and_symlink_escape_refuse(self):
        rec = self.cli_record()
        for path in ("../outside", "/absolute", "docs/knowledge/other.md", None):
            with self.subTest(path=path):
                rec["summary_source"] = path
                self.save()
                with self.assertRaisesRegex(ValueError, "approved stable anchor"):
                    self.render()
        rec["summary_source"] = module.CLI_SUMMARY
        self.save()
        anchor = self.root / module.CLI_SUMMARY
        anchor.unlink()
        anchor.symlink_to(ROOT / module.CLI_SUMMARY)
        with self.assertRaisesRegex(ValueError, "escaped"):
            self.render()

    def test_unknown_and_mixed_modes_refuse(self):
        import hashlib
        rec = self.cli_record()
        for mode in (None, "", "automatic", False):
            with self.subTest(mode=mode):
                rec["source_hash_mode"] = mode
                self.save()
                with self.assertRaisesRegex(ValueError, "unknown source hash mode"):
                    self.render()
        rec["source_hash_mode"] = "release-bytes"
        for key, value in (("source_sha256", None), ("source_sha256", hashlib.sha256(
                (self.root / module.CLI_SOURCE).read_bytes()).hexdigest()), ("summary", "mixed")):
            with self.subTest(key=key, value=value):
                rec[key] = value
                self.save()
                with self.assertRaisesRegex(ValueError, "mixed"):
                    self.render()
                del rec[key]

    def test_other_eight_records_remain_strict(self):
        for rec in self.registry["records"]:
            if rec is self.cli_record():
                continue
            with self.subTest(path=rec["source"]):
                path = self.root / rec["source"]
                original = path.read_bytes()
                path.write_bytes(original + b"\nchanged\n")
                with self.assertRaisesRegex(ValueError, "source witness changed"):
                    self.render()
                path.write_bytes(original)
                digest = rec.pop("source_sha256")
                self.save()
                with self.assertRaisesRegex(ValueError, "source witness changed"):
                    self.render()
                rec["source_sha256"] = digest
                rec["source_hash_mode"] = "release-bytes"
                summary = rec.pop("summary")
                del rec["source_sha256"]
                self.save()
                with self.assertRaisesRegex(ValueError, "approved CLI"):
                    self.render()
                del rec["source_hash_mode"]
                rec["summary"] = summary
                rec["source_sha256"] = digest
                self.save()

    def test_cli_missing_escape_wrong_identity_or_kind_refuse(self):
        rec = self.cli_record()
        path = self.root / rec["source"]
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.render()
        path.symlink_to(ROOT / module.CLI_SOURCE)
        with self.assertRaisesRegex(ValueError, "escaped"):
            self.render()
        path.unlink()
        path.write_bytes(original)
        for key, value in (("source", "../outside"), ("source", str(ROOT / module.CLI_SOURCE)),
                           ("subject", module.CLI_SUBJECT + "#guessed"), ("kind", "idea")):
            old = rec[key]
            rec[key] = value
            self.save()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.render()
            rec[key] = old
            self.save()

    def test_strict_record_cannot_silently_adopt_summary_anchor(self):
        rec = self.registry["records"][0]
        for key in ("summary_source", "summary_sha256"):
            rec[key] = "unexpected"
            self.save()
            with self.assertRaisesRegex(ValueError, "requires explicit"):
                self.render()
            del rec[key]

    def test_disjoint_cli_edits_merge_both_orders_without_registry_cure(self):
        import hashlib
        def merge(ours, base, theirs):
            with tempfile.TemporaryDirectory() as folder:
                paths = [Path(folder) / str(i) for i in range(3)]
                for path, content in zip(paths, (ours, base, theirs)):
                    path.write_text(content)
                return subprocess.run(["git", "merge-file", "-p", *map(str, paths)],
                                      capture_output=True, text=True)
        path = self.root / module.CLI_SOURCE
        original = path.read_text()
        first, second = "PRIVATE_A = True\n" + original, original + "\nPRIVATE_B = True\n"
        registry_before = (self.root / "docs/knowledge/repository-knowledge.json").read_bytes()
        outputs = []
        for ours, theirs in ((first, second), (second, first)):
            result = merge(ours, original, theirs)
            self.assertEqual(result.returncode, 0, result.stdout)
            path.write_text(result.stdout)
            self.assertIn(hashlib.sha256(path.read_bytes()).hexdigest(), self.render())
            self.assertEqual(registry_before,
                             (self.root / "docs/knowledge/repository-knowledge.json").read_bytes())
            outputs.append(result.stdout)
        self.assertEqual(*outputs)
        # Real semantic summary edits still conflict: never pick one silently.
        self.assertEqual(merge("Scope A\n", "Scope\n", "Scope B\n").returncode, 1)
        # Before migration the same code-only changes touched one scalar.
        old = dict(self.cli_record())
        for key in ("source_hash_mode", "summary_source", "summary_sha256"):
            old.pop(key)
        old["summary"] = (self.root / module.CLI_SUMMARY).read_text().strip()
        def committed(source):
            return json.dumps(dict(old, source_sha256=hashlib.sha256(source.encode()).hexdigest()), indent=2)
        self.assertEqual(merge(committed(first), committed(original), committed(second)).returncode, 1)

    @unittest.skipUnless(os.environ.get("QUIPU_TEST_BIN"), "native schema control requires explicit test artifact")
    def test_actual_native_schema_positive_and_missing_freshness_negative(self):
        data = self.root / "curated.ttl"
        data.write_text(self.render())
        args = [
            os.environ["QUIPU_TEST_BIN"],
            "validate",
            "--shapes",
            str(ROOT / "docs/knowledge/repository-knowledge.shapes.ttl"),
            "--data",
            str(data),
            "--format",
            "json",
        ]
        positive = subprocess.run(args, capture_output=True, text=True, cwd=self.root)
        self.assertEqual(positive.returncode, 0, positive.stderr + positive.stdout)
        data.write_text("\n".join(line for line in data.read_text().splitlines() if "/reviewAfter>" not in line))
        negative = subprocess.run(args, capture_output=True, text=True, cwd=self.root)
        self.assertNotEqual(negative.returncode, 0, negative.stdout)


class ReleaseAliases(unittest.TestCase):
    """aegis-asv: tracked agent-file aliases no longer block a release."""

    def release(self, folder, links):
        source = Path(folder) / "source"
        source.mkdir()
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        (source / "AGENTS.md").write_text("agent guide\n")
        (source / "docs").mkdir()
        (source / "docs/guide.md").write_text("guide\n")
        for name, target in links.items():
            (source / name).symlink_to(target)
        subprocess.run(["git", "-C", str(source), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(source), "-c", "user.name=fixture",
             "-c", "user.email=fixture@example.org", "commit", "-qm", "fixture"],
            check=True,
        )
        revision = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        return builder.materialize_release(source, revision, Path(folder) / "copied")

    def test_alias_of_tracked_file_is_skipped_and_target_copied_once(self):
        with tempfile.TemporaryDirectory() as folder:
            copied = self.release(folder, {"CLAUDE.md": "AGENTS.md", "GEMINI.md": "AGENTS.md",
                                           "docs/also.md": "guide.md"})
            self.assertEqual((copied / "AGENTS.md").read_text(), "agent guide\n")
            self.assertEqual((copied / "docs/guide.md").read_text(), "guide\n")
            for alias in ("CLAUDE.md", "GEMINI.md", "docs/also.md"):
                self.assertFalse((copied / alias).exists() or (copied / alias).is_symlink())

    def test_other_links_refuse(self):
        for name, target in {
            "absolute": "/etc/hostname",
            "escaping": "../outside.md",
            "dangling": "missing.md",
            "directory": "docs",
            "chained": "CLAUDE.md",
        }.items():
            links = {"CLAUDE.md": "AGENTS.md", "LINK.md": target}
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError, "unsupported tracked release member"):
                    self.release(folder, links)

if __name__ == "__main__":
    unittest.main()
