#!/usr/bin/env python3
"""Offline tests for the format-repair engine."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ENGINE = Path(__file__).resolve().parents[1] / "engine"
sys.path.insert(0, str(ENGINE))
import format_repair as fr

REPO = "owner/repo"
HEAD = "a" * 40
BASE = "b" * 40


def config():
    return {
        "version": 1,
        "formatter_version": "22.1.8",
        "python_formatter_version": "0.17.5",
        "approval_label": "format-fix:approved",
        "maintainers": {"maintainer"},
        "allowed_extensions": [".cpp", ".h", ".cu", ".cuh", ".py"],
        "allowed_paths": ["src/**", "include/**", "kernels/**", "tests/**", "benchmarks/**", "format-repair/**", "pr-confidence/**", "pr-scope-guard/**", "label-review/**", "issue-landing/**", "runners/**"],
    }


def pr(**changes):
    value = {
        "number": 12,
        "state": "open",
        "changed_files": 1,
        "head": {"sha": HEAD, "ref": "feature/format", "repo": {"full_name": REPO}},
        "base": {"sha": BASE, "ref": "main", "repo": {"full_name": REPO}},
        "labels": [{"name": "format-fix:approved"}],
    }
    value.update(changes)
    return value


class PolicyTests(unittest.TestCase):
    def test_path_and_extension_allowlist(self):
        cfg = config()
        self.assertTrue(fr.allowed("src/vector.cu", cfg))
        self.assertFalse(fr.allowed("docs/example.cpp", cfg))
        self.assertTrue(fr.allowed("format-repair/engine/format_repair.py", cfg))
        self.assertTrue(fr.allowed("benchmarks/plot.py", cfg))
        self.assertFalse(fr.allowed("docs/example.py", cfg))

    def test_rejects_unsafe_paths(self):
        for path in ("/tmp/a.cpp", "../a.cpp", "src/../a.cpp", "src\\a.cpp", "src/a.cpp\nother.cpp"):
            with self.subTest(path=path), self.assertRaises(fr.RepairError):
                fr.require_path(path)

    def test_removed_files_are_not_eligible(self):
        selected = [
            x
            for x in [{"filename": "src/a.cpp", "status": "removed"}, {"filename": "src/b.cu", "status": "modified"}]
            if x["status"] != "removed" and fr.allowed(x["filename"], config())
        ]
        self.assertEqual(selected, [{"filename": "src/b.cu", "status": "modified"}])

    def test_authorized_actor_is_exact(self):
        self.assertIn("maintainer", config()["maintainers"])
        self.assertNotIn("contributor", config()["maintainers"])

    def test_authorized_repair_requires_maintainer_label_and_default_branch(self):
        info = fr.authorize_repair(pr(), REPO, "maintainer", HEAD, config(), "main")
        self.assertEqual(info["sha"], HEAD)
        with self.assertRaisesRegex(fr.RepairError, "not authorized"):
            fr.authorize_repair(pr(), REPO, "contributor", HEAD, config(), "main")

    def test_rejects_fork_for_repair_but_allows_report_metadata(self):
        fork = pr()
        fork["head"]["repo"]["full_name"] = "contributor/repo"
        self.assertEqual(fr.pr_info(fork, REPO)["head_repo"], "contributor/repo")
        with self.assertRaisesRegex(fr.RepairError, "fork"):
            fr.pr_info(fork, REPO, same_repo=True)

    def test_rejects_stale_head(self):
        with self.assertRaisesRegex(fr.RepairError, "head changed"):
            fr.pr_info(pr(), REPO, expected=BASE, same_repo=True)

    def test_accepts_valid_git_branch_characters(self):
        value = pr()
        value["head"]["ref"] = "feature/foo+bar"
        self.assertEqual(fr.pr_info(value, REPO)["branch"], "feature/foo+bar")

    def test_rejects_invalid_git_branch_names(self):
        for branch in ("bad..name", "bad name", "bad\\\\name", "bad@{name}", "bad/"):
            with self.subTest(branch=branch), self.assertRaisesRegex(fr.RepairError, "invalid pull request branch"):
                value = pr()
                value["head"]["ref"] = branch
                fr.pr_info(value, REPO)

    def test_rejects_unauthorized_actor(self):
        with self.assertRaisesRegex(fr.RepairError, "not authorized"):
            fr.authorize_repair(pr(), REPO, "contributor", HEAD, config(), "main")

    def test_rejects_missing_approval_label(self):
        with self.assertRaisesRegex(fr.RepairError, "approval label"):
            fr.authorize_repair(pr(labels=[]), REPO, "maintainer", HEAD, config(), "main")

    def test_rejects_non_default_base(self):
        value = pr()
        value["base"]["ref"] = "release"
        with self.assertRaisesRegex(fr.RepairError, "default-branch"):
            fr.authorize_repair(value, REPO, "maintainer", HEAD, config(), "main")

    def test_changed_paths_must_be_subset_of_allowlist(self):
        with self.assertRaisesRegex(fr.RepairError, "unapproved path"):
            fr.validate_changed_paths(["src/a.cpp", "README.md"], ["src/a.cpp"])


class ReportTests(unittest.TestCase):
    def test_source_bytes_rejects_contents_api_encoding_none(self):
        payload = {"type": "file", "encoding": "none", "content": ""}
        with mock.patch.object(fr, "api_json", return_value=(payload, "")):
            with self.assertRaisesRegex(fr.RepairError, "did not return base64 source content"):
                fr.source_bytes(REPO, "src/large.cpp", HEAD, "token")

    def test_source_bytes_decodes_base64_payload(self):
        payload = {"type": "file", "encoding": "base64", "content": "aW50IG1haW4oKSB7fQ=="}
        with mock.patch.object(fr, "api_json", return_value=(payload, "")):
            self.assertEqual(fr.source_bytes(REPO, "src/a.cpp", HEAD, "token"), b"int main() {}")

    def test_source_bytes_rejects_invalid_base64(self):
        payload = {"type": "file", "encoding": "base64", "content": "not base64!"}
        with mock.patch.object(fr, "api_json", return_value=(payload, "")):
            with self.assertRaisesRegex(fr.RepairError, "invalid base64"):
                fr.source_bytes(REPO, "src/a.cpp", HEAD, "token")

    def test_replacement_offsets_become_line_numbers(self):
        source = b"int main() {\n  return 0;\n}\n"
        xml = '<replacements><replacement offset="14" length="1" replacement=""/><replacement offset="25" length="1" replacement=""/></replacements>'
        self.assertEqual(fr.line_numbers(source, xml), [2, 3])

    def test_invalid_replacement_xml_fails(self):
        with self.assertRaises(fr.RepairError):
            fr.line_numbers(b"x", "<broken>")

    def test_formatter_failure_fails_closed(self):
        failed = mock.Mock(returncode=2, stdout=b"", stderr=b"formatter failed")
        with mock.patch.object(fr.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(fr.RepairError, "clang-format failed"):
                fr.inspect("src/a.cpp", b"source", ".clang-format")

    def test_python_formatter_uses_ruff_and_reports_changed_lines(self):
        source = b"answer=42\n"
        formatted = b"answer = 42\n"
        with mock.patch.object(fr, "formatted_python", return_value=formatted) as formatter:
            result = fr.inspect_python("benchmarks/plot.py", source, "pyproject.toml")
        formatter.assert_called_once_with(source, "benchmarks/plot.py", "pyproject.toml")
        self.assertFalse(result["formatted"])
        self.assertEqual(result["lines"], [1])

    def test_clean_formatter_output_is_reported_clean(self):
        clean = mock.Mock(returncode=0, stdout=b"<replacements/>", stderr=b"")
        with mock.patch.object(fr.subprocess, "run", return_value=clean):
            result = fr.inspect("src/a.cpp", b"source", ".clang-format")
        self.assertTrue(result["formatted"])
        self.assertEqual(result["lines"], [])

    def test_duplicate_label_event_after_removal_fails_closed(self):
        with self.assertRaisesRegex(fr.RepairError, "approval label"):
            fr.authorize_repair(pr(labels=[]), REPO, "maintainer", HEAD, config(), "main")

    def test_report_checks_only_allowlisted_files(self):
        files = [{"filename": "src/a.cpp", "status": "modified"}, {"filename": "docs/readme.cpp", "status": "modified"}]
        result = {"path": "src/a.cpp", "lines": [4], "formatted": False}
        with mock.patch.object(fr, "source_bytes", return_value=b"source") as source:
            with mock.patch.object(fr, "inspect", return_value=result):
                report = fr.make_report(REPO, pr(changed_files=2), files, config(), "token", ".clang-format", "pyproject.toml")
        source.assert_called_once()
        self.assertEqual(report["files_skipped"], ["docs/readme.cpp"])
        self.assertEqual(report["violations"], [result])
        self.assertFalse(report["clean"])

    def test_incomplete_changed_file_list_fails_closed(self):
        with self.assertRaisesRegex(fr.RepairError, "coverage is incomplete"):
            fr.make_report(REPO, pr(changed_files=2), [{"filename": "src/a.cpp"}], config(), "token", ".clang-format", "pyproject.toml")

    def test_fork_report_is_explicitly_read_only(self):
        value = pr()
        value["head"]["repo"]["full_name"] = "contributor/repo"
        report = {
            "formatter_version": "22.1.8",
            "formatter_versions": {"clang-format": "22.1.8", "ruff": "0.17.5"},
            "files_checked": [],
            "files_skipped": [],
            "violations": [],
            "clean": True,
            "repair_eligible": False,
        }
        self.assertIn("Fork pull request", fr.report_markdown(report))


if __name__ == "__main__":
    unittest.main()
