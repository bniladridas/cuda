import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.github_snapshot import build_snapshot
from engine.steward import build_report


class StewardEndToEndTests(unittest.TestCase):
    def test_snapshot_to_report_preserves_evidence_and_read_only_boundaries(self):
        head_sha = "a" * 40
        issue = {
            "number": 12,
            "title": "Add a deterministic integration test",
            "body": "## Acceptance Criteria\n- CPU tests pass",
            "state": "open",
            "html_url": "https://example.invalid/issues/12",
            "labels": [{"name": "enhancement"}],
            "assignees": [{"login": "maintainer"}],
            "updated_at": "2026-11-23T10:00:00Z",
        }
        responses = {
            "repos/example/cuda": {"default_branch": "main"},
            "repos/example/cuda/issues?state=all&per_page=100": [[issue]],
            "repos/example/cuda/pulls?state=all&per_page=100": [[]],
            "repos/example/cuda/branches/main": {"commit": {"sha": head_sha}},
            f"repos/example/cuda/commits/{head_sha}/check-runs?per_page=100": {
                "check_runs": [
                    {"name": "CPU", "status": "completed", "conclusion": "success"},
                    {"name": "GPU", "status": "completed", "conclusion": "skipped"},
                ]
            },
            f"repos/example/cuda/actions/workflows/ci.yml/runs?head_sha={head_sha}&per_page=5": {
                "workflow_runs": [
                    {"id": 7, "run_attempt": 1, "head_sha": head_sha, "name": "CI", "event": "push"}
                ]
            },
            "repos/example/cuda/actions/runs/7/jobs?per_page=100": {
                "jobs": [
                    {"id": 70, "name": "CPU", "runner_name": "ubuntu", "labels": ["ubuntu-latest"]},
                    {"id": 71, "name": "GPU", "runner_name": None, "labels": ["ubuntu-latest"]},
                ]
            },
            "repos/example/cuda/actions/workflows/label-review.yml/runs?per_page=1": {
                "workflow_runs": [
                    {"status": "completed", "conclusion": "success", "head_sha": head_sha, "name": "Label Review"}
                ]
            },
            "repos/example/cuda/actions/workflows/issue-landing.yml/runs?per_page=1": {
                "workflow_runs": [
                    {"status": "completed", "conclusion": "success", "head_sha": head_sha, "name": "Issue Landing"}
                ]
            },
        }

        def runner(command, **kwargs):
            path = command[-1]
            if path not in responses:
                self.fail(f"Unexpected GitHub CLI request: {path}")
            value = responses[path]
            return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            with patch("engine.github_snapshot.load_repository_files", return_value={"README.md": "# Example\n"}), patch(
                "engine.github_snapshot.load_benchmark_results", return_value=[]
            ):
                snapshot = build_snapshot("example/cuda", Path(temporary), runner=runner)

        report = build_report(snapshot)
        self.assertEqual(snapshot["head_sha"], head_sha)
        self.assertEqual(snapshot["issues"][0]["number"], 12)
        self.assertEqual(report["modules"]["validation"]["evidence"][0]["state"], "success")
        gpu = next(item for item in report["modules"]["validation"]["evidence"] if item["kind"] == "gpu_runtime")
        self.assertEqual(gpu["state"], "skipped")
        self.assertEqual(gpu["head_sha"], head_sha)
        self.assertEqual(report["modules"]["integrations"]["mode"], "read_only")
        self.assertFalse(report["modules"]["integrations"]["mutations_performed"])
        label_review = report["modules"]["integrations"]["integrations"]["label_review"]
        self.assertEqual(label_review["state"], "success")
        self.assertEqual(label_review["approval_status"], "not_asserted")
        self.assertFalse(label_review["coordinator_write_performed"])
        self.assertFalse(report["modules"]["release_readiness"]["ready"])
        self.assertFalse(report["modules"]["model_integration"]["enabled"])

    def test_scheduled_workflow_has_read_only_permissions_and_artifact_output(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github" / "workflows" / "repository-steward.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read", workflow)
        self.assertIn("issues: read", workflow)
        self.assertIn("pull-requests: read", workflow)
        self.assertIn("checks: read", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("actions/upload-artifact@v7", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("issues: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)


if __name__ == "__main__":
    unittest.main()
