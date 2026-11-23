import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.contracts import Evidence, State
from engine.health import analyze_health
from engine.readiness import evaluate_readiness
from engine.steward import build_report
from engine.tracking import analyze_tracking
from engine.validation import normalize_validation


class StewardTests(unittest.TestCase):
    def test_issue_tracking_finds_unlinked_and_missing_acceptance(self):
        result = analyze_tracking(
            {"issues": [{"number": 4, "title": "Add kernel", "body": "", "state": "open"}], "pull_requests": []}
        )
        codes = {item["code"] for item in result["findings"]}
        self.assertEqual(codes, {"issue.unlinked", "issue.acceptance_missing"})

    def test_linked_pr_and_dependency_are_reported(self):
        result = analyze_tracking(
            {
                "issues": [
                    {"number": 4, "title": "Parent", "body": "Depends on #5", "state": "open"},
                    {"number": 5, "title": "Child", "body": "Done", "state": "closed"},
                ],
                "pull_requests": [{"number": 12, "title": "Fixes #4", "state": "open", "head_sha": "abc"}],
            }
        )
        self.assertEqual(result["issues"][0]["dependencies"], [5])
        self.assertEqual(result["issues"][0]["linked_prs"][0]["number"], 12)

    def test_linked_pr_merge_state_distinguishes_merged_and_closed_unmerged(self):
        result = analyze_tracking(
            {
                "issues": [{"number": 4, "title": "Track landing", "body": "Acceptance criteria", "state": "open"}],
                "pull_requests": [
                    {
                        "number": 12,
                        "title": "Fixes #4",
                        "state": "closed",
                        "merged_at": "2026-11-23T10:00:00Z",
                        "merge_commit_sha": "merge123",
                        "base_ref": "main",
                        "base_sha": "base123",
                    },
                    {
                        "number": 13,
                        "title": "Also fixes #4",
                        "state": "closed",
                        "merged_at": None,
                        "merge_commit_sha": None,
                    },
                ],
            }
        )
        linked = result["issues"][0]["linked_prs"]
        self.assertEqual([item["merge_status"] for item in linked], ["merged", "closed_unmerged"])
        self.assertEqual(linked[0]["merge_commit_sha"], "merge123")
        self.assertEqual(linked[0]["base_ref"], "main")
        self.assertEqual(linked[0]["base_sha"], "base123")
        self.assertEqual(linked[1]["merge_commit_sha"], "")

    def test_readiness_requires_current_head_evidence(self):
        evidence = [
            Evidence("host_tests", State.SUCCESS, "ci", "old", "new"),
            Evidence("cuda_compile", State.SUCCESS, "ci", "new", "new"),
            Evidence("gpu_runtime", State.SKIPPED, "ci", "new", "new"),
        ]
        result = evaluate_readiness(evidence)
        self.assertFalse(result["ready"])
        self.assertEqual(result["required_evidence"]["host_tests"]["state"], "unknown")
        self.assertEqual(result["required_evidence"]["gpu_runtime"]["state"], "skipped")
        self.assertFalse(result["publication_performed"])

    def test_health_reports_broken_relative_links_and_invalid_json(self):
        result = analyze_health(
            {
                "README.md": "[missing](docs/nope.md)",
                ".github/config.json": "{broken",
                "docs/existing.md": "ok",
            }
        )
        codes = {item["code"] for item in result["findings"]}
        self.assertEqual(codes, {"docs.link_missing", "config.json_invalid"})
        self.assertFalse(result["mutations_performed"])

    def test_build_report_is_read_only_and_keeps_model_disabled(self):
        result = build_report(
            {
                "repository": "bniladridas/cuda",
                "head_sha": "abc",
                "issues": [],
                "pull_requests": [],
                "validations": [{"kind": "gpu_runtime", "state": "skipped", "head_sha": "abc", "source": "ci"}],
                "files": {"README.md": "ok"},
            }
        )
        self.assertFalse(result["modules"]["release_readiness"]["ready"])
        self.assertFalse(result["modules"]["model_integration"]["enabled"])
        self.assertEqual(result["modules"]["validation"]["evidence"][0]["state"], "skipped")

    def test_validation_metadata_is_preserved_in_report_contract(self):
        evidence = normalize_validation(
            {
                "head_sha": "abc",
                "validations": [
                    {
                        "kind": "gpu_runtime",
                        "state": "skipped",
                        "head_sha": "abc",
                        "metadata": {
                            "workflow_run_id": 42,
                            "runner_name": None,
                            "device_identity": "not_reported",
                        },
                    }
                ],
            }
        )
        self.assertEqual(evidence[0].metadata["workflow_run_id"], 42)
        self.assertEqual(evidence[0].to_dict()["metadata"]["device_identity"], "not_reported")

    def test_model_summary_is_called_only_when_explicitly_requested(self):
        snapshot = {
            "repository": "bniladridas/cuda",
            "issues": [],
            "pull_requests": [],
            "validations": [],
            "files": {},
        }
        with patch(
            "engine.model_summary.summarize_report",
            return_value={
                "enabled": True,
                "status": "advisory",
                "authorization_source": None,
                "summary": "Evidence remains incomplete.",
            },
        ) as summarize:
            result = build_report(snapshot, include_model_summary=True)
        summarize.assert_called_once()
        self.assertEqual(
            result["modules"]["model_integration"]["status"],
            "advisory",
        )
        self.assertIsNone(
            result["modules"]["model_integration"]["authorization_source"],
        )


if __name__ == "__main__":
    unittest.main()
