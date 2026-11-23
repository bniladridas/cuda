import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.github_snapshot import (
    SnapshotError,
    acceptance_criteria_status_from_body,
    criteria_from_body,
    issue_dependencies,
    load_benchmark_results,
    pull_request_review_decision,
    run_gh,
    validation_run_metadata,
    workflow_evidence,
)


class SnapshotAdapterTests(unittest.TestCase):
    def test_acceptance_criteria_extraction(self):
        body = """## Overview
text
## Acceptance Criteria
- [ ] CPU tests
- GPU evidence
## Notes
- not included"""
        self.assertEqual(criteria_from_body(body), ["CPU tests", "GPU evidence"])

    def test_dependency_extraction_is_sorted_and_excludes_self(self):
        self.assertEqual(issue_dependencies("Depends on #8 and #3, also #8", 3), [8])

    def test_benchmark_results_are_loaded_from_results_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "benchmarks" / "results"
            results.mkdir(parents=True)
            record = {"git_commit": "a" * 40, "gpu": "test"}
            (results / "run.json").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(load_benchmark_results(root), [record])

    def test_invalid_benchmark_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "benchmarks" / "results"
            results.mkdir(parents=True)
            (results / "broken.json").write_text("{", encoding="utf-8")
            with self.assertRaises(SnapshotError):
                load_benchmark_results(root)

    def test_workflow_run_success_is_not_approval_evidence(self):
        payload = {
            "workflow_runs": [
                {
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": "abc",
                    "name": "Label Review",
                    "html_url": "https://example.invalid/run/1",
                }
            ]
        }

        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        result = workflow_evidence("example/repo", "label-review.yml", runner=runner)
        self.assertEqual(result["state"], "success")
        self.assertEqual(result["head_sha"], "abc")
        self.assertIn("Approval is not inferred", result["details"])

    def test_missing_workflow_run_is_unavailable(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout='{"workflow_runs": []}', stderr="")

        result = workflow_evidence("example/repo", "issue-landing.yml", runner=runner)
        self.assertEqual(result["state"], "unavailable")

    def test_validation_metadata_is_bound_to_exact_commit_and_runner(self):
        responses = [
            {
                "workflow_runs": [
                    {
                        "id": 42,
                        "run_attempt": 2,
                        "head_sha": "abc",
                        "name": "ci",
                        "event": "push",
                        "html_url": "https://example.invalid/actions/runs/42",
                    }
                ]
            },
            {
                "jobs": [
                    {
                        "id": 99,
                        "name": "gpu",
                        "runner_name": "ephemeral-gpu-1",
                        "runner_id": 7,
                        "runner_group_name": "NVIDIA",
                        "labels": ["self-hosted", "linux", "nvidia"],
                    }
                ]
            },
        ]

        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=json.dumps(responses.pop(0)), stderr="")

        result = validation_run_metadata("example/repo", "abc", runner=runner)
        gpu = result["gpu_runtime"]
        self.assertEqual(gpu["workflow_run_id"], 42)
        self.assertEqual(gpu["workflow_run_attempt"], 2)
        self.assertEqual(gpu["runner_name"], "ephemeral-gpu-1")
        self.assertEqual(gpu["runner_labels"], ["self-hosted", "linux", "nvidia"])
        self.assertEqual(gpu["device_identity"], "not_reported")

    def test_validation_metadata_ignores_runs_for_other_commits(self):
        payload = {
            "workflow_runs": [
                {
                    "id": 41,
                    "head_sha": "different",
                }
            ]
        }

        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        self.assertEqual(validation_run_metadata("example/repo", "abc", runner=runner), {})

    def test_gh_errors_fail_closed(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="denied")

        with self.assertRaises(SnapshotError):
            run_gh("repos/example/repo", runner=runner)

    def test_invalid_json_fails_closed(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout="not-json", stderr="")

        with self.assertRaises(SnapshotError):
            run_gh("repos/example/repo", runner=runner)

    def test_acceptance_criteria_status_preserves_unchecked_and_unmarked_items(self):
        body = """## Acceptance Criteria
- [x] CPU tests
- [ ] GPU runtime
- ordinary documentation bullet
## Notes
- ignored"""
        self.assertEqual(acceptance_criteria_status_from_body(body), [True, False, None])

    def test_workflow_evidence_requires_exact_head_when_requested(self):
        payload = {
            "workflow_runs": [
                {"status": "completed", "conclusion": "success", "head_sha": "old", "run_number": 9},
                {"status": "completed", "conclusion": "failure", "head_sha": "new", "run_number": 8},
            ]
        }
        calls = []

        def runner(command, **kwargs):
            calls.append(command[-1])
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        result = workflow_evidence("example/repo", "label-review.yml", "new", runner=runner)
        self.assertEqual(result["head_sha"], "new")
        self.assertEqual(result["expected_sha"], "new")
        self.assertEqual(result["state"], "failure")
        self.assertIn("head_sha=new", calls[0])

    def test_workflow_evidence_does_not_fall_back_to_an_old_success(self):
        payload = {"workflow_runs": [{"status": "completed", "conclusion": "success", "head_sha": "old"}]}

        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        result = workflow_evidence("example/repo", "issue-landing.yml", "new", runner=runner)
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["expected_sha"], "new")

    def test_review_decision_uses_github_graphql_and_fails_closed(self):
        payload = {"data": {"repository": {"pullRequest": {"reviewDecision": "CHANGES_REQUESTED"}}}}

        def runner(command, **kwargs):
            self.assertEqual(command[2], "graphql")
            self.assertIn("reviewDecision", command[4])
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        self.assertEqual(pull_request_review_decision("example/repo", 12, runner=runner), "changes_requested")

        def denied(*args, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="denied")

        self.assertEqual(pull_request_review_decision("example/repo", 12, runner=denied), "unknown")


if __name__ == "__main__":
    unittest.main()
