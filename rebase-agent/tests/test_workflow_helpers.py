"""Tests for trusted workflow verification helpers."""

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "engine"


def run_script(name, *args):
    return subprocess.run(
        [sys.executable, str(ENGINE / name), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


class WorkflowHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_tree_sha_verification_rejects_mismatch(self):
        report = self.write_json(
            "tree.json",
            {"head": {"sha": "a" * 40}, "base": {"sha": "b" * 40}},
        )
        result = run_script("verify_tree_inspection.py", report, "c" * 40, "b" * 40)
        self.assertNotEqual(result.returncode, 0)

    def test_final_review_gate_rejects_high_severity(self):
        report = self.write_json(
            "review.json",
            {
                "ready_for_validation": True,
                "patch_applied": False,
                "findings": [{"severity": "high"}],
            },
        )
        result = run_script("verify_agent_report.py", report, "--final")
        self.assertNotEqual(result.returncode, 0)

    def test_check_summary_records_failures(self):
        checks = self.write_json(
            "checks.json",
            {"check_runs": [{"name": "CI", "status": "completed", "conclusion": "failure"}]},
        )
        audit = self.write_json("audit.json", {})
        result = run_script("summarize_checks.py", checks, audit)
        self.assertNotEqual(result.returncode, 0)
        recorded = json.loads(audit.read_text(encoding="utf-8"))
        self.assertFalse(recorded["all_reported_checks_acceptable"])
        self.assertFalse(recorded["branch_protection_required_checks_verified"])

    def test_review_feedback_extractor_keeps_inline_context(self):
        event = {
            "action": "created",
            "comment": {
                "body": "Please handle this edge case",
                "path": "src/kernel.cu",
                "line": 42,
                "diff_hunk": "@@ -1 +1 @@",
                "commit_id": "a" * 40,
                "user": {"login": "reviewer"},
            },
            "pull_request": {
                "number": 12,
                "head": {"sha": "b" * 40},
                "base": {"sha": "c" * 40},
            },
        }
        event_path = self.root / "event.json"
        output = self.root / "feedback.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ENGINE / "extract_review_feedback.py"), str(output)],
            env=dict(os.environ, GITHUB_EVENT_PATH=str(event_path)),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        feedback = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(feedback["body"], "Please handle this edge case")
        self.assertEqual(feedback["path"], "src/kernel.cu")
        self.assertEqual(feedback["line"], 42)

    def test_archive_extractor_rejects_symlinks(self):
        archive_path = self.root / "unsafe.tar"
        with tarfile.open(archive_path, "w") as archive:
            member = tarfile.TarInfo("link")
            member.type = tarfile.SYMTYPE
            member.linkname = "../../outside"
            archive.addfile(member)
        result = run_script("extract_safe_archive.py", archive_path, self.root / "out")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
