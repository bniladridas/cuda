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
        self.assertEqual(codes, {"issue.unlinked", "issue.acceptance_missing", "issue.unowned"})

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

    def test_release_readiness_checks_docs_health_benchmarks_and_versions(self):
        evidence = [
            Evidence("host_tests", State.SUCCESS, "ci", "head", "head"),
            Evidence("cuda_compile", State.SUCCESS, "ci", "head", "head"),
            Evidence("gpu_runtime", State.SUCCESS, "gpu-ci", "head", "head"),
        ]
        complete = evaluate_readiness(
            evidence,
            health={"findings": []},
            benchmark={"reports": [{"state": "valid"}], "valid_count": 1},
            files={"README.md": "", "LICENSE": "", "docs/methodology.md": ""},
            version_evidence={"declared_version": "0.1.0", "release_version": "v0.1.0"},
        )
        self.assertTrue(complete["ready"])
        self.assertEqual(complete["required_evidence"]["version_consistency"]["state"], "success")
        self.assertFalse(complete["publication_performed"])

        incomplete = evaluate_readiness(
            evidence,
            health={"findings": [{"severity": "error", "code": "config.invalid"}]},
            benchmark={"reports": [], "valid_count": 0},
            files={"README.md": ""},
            version_evidence={"declared_version": "0.1.0", "release_version": "v0.2.0"},
        )
        self.assertFalse(incomplete["ready"])
        states = {item["kind"]: item["state"] for item in incomplete["blockers"]}
        self.assertEqual(states["documentation"], "failure")
        self.assertEqual(states["repository_health"], "failure")
        self.assertEqual(states["benchmark_integrity"], "unavailable")
        self.assertEqual(states["version_consistency"], "failure")

    def test_repository_health_warnings_are_reported_without_blocking_by_default(self):
        evidence = [
            Evidence("host_tests", State.SUCCESS, "ci", "head", "head"),
            Evidence("cuda_compile", State.SUCCESS, "ci", "head", "head"),
            Evidence("gpu_runtime", State.SUCCESS, "gpu-ci", "head", "head"),
        ]
        result = evaluate_readiness(
            evidence,
            {"require_benchmark_evidence": False, "require_version_consistency": False},
            health={"findings": [{"severity": "warning", "code": "docs.link_missing"}]},
            files={"README.md": "", "LICENSE": "", "docs/methodology.md": ""},
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["required_evidence"]["repository_health"]["warning_count"], 1)

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


    def test_issue_ownership_activity_and_closure_candidate_are_evidence_based(self):
        result = analyze_tracking(
            {
                "generated_at": "2026-11-23T12:00:00+00:00",
                "issues": [
                    {
                        "number": 4,
                        "title": "Ship feature",
                        "body": "Done",
                        "state": "open",
                        "assignees": ["maintainer"],
                        "updated_at": "2026-11-20T12:00:00Z",
                        "acceptance_criteria": ["CPU tests", "review"],
                        "acceptance_criteria_status": [True, True],
                        "dependency_numbers": [5],
                        "linked_pr_numbers": [12],
                    },
                    {"number": 5, "title": "Dependency", "body": "Done", "state": "closed"},
                    {
                        "number": 6,
                        "title": "Unowned stale issue",
                        "body": "Investigate",
                        "state": "open",
                        "assignees": [],
                        "updated_at": "2026-10-01T12:00:00Z",
                        "acceptance_criteria": ["Investigate"],
                        "acceptance_criteria_status": [False],
                    },
                ],
                "pull_requests": [
                    {
                        "number": 12,
                        "title": "Implement #4",
                        "state": "closed",
                        "merged": True,
                        "merge_state": "merged",
                    }
                ],
            }
        )
        by_number = {item["number"]: item for item in result["issues"]}
        self.assertTrue(by_number[4]["closure_readiness"]["candidate"])
        self.assertTrue(by_number[4]["closure_readiness"]["human_review_required"])
        self.assertFalse(by_number[4]["closure_readiness"]["issue_mutation_performed"])
        self.assertEqual(by_number[4]["activity_state"], "recent")
        self.assertEqual(by_number[6]["activity_state"], "stale")
        self.assertFalse(by_number[6]["owner_present"])
        self.assertEqual(result["unowned_open_issue_count"], 1)
        self.assertEqual(result["stale_open_issue_count"], 1)
        self.assertEqual(result["closure_candidate_count"], 1)
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("issue.unowned", codes)
        self.assertIn("issue.stale_activity", codes)

    def test_closure_readiness_rejects_unverified_criteria_and_unmerged_prs(self):
        result = analyze_tracking(
            {
                "generated_at": "2026-11-23T12:00:00Z",
                "issues": [
                    {
                        "number": 7,
                        "title": "Work",
                        "body": "Done",
                        "state": "open",
                        "updated_at": "2026-11-22T12:00:00Z",
                        "acceptance_criteria": ["tests", "review"],
                        "acceptance_criteria_status": [True, None],
                        "linked_pr_numbers": [8],
                    }
                ],
                "pull_requests": [{"number": 8, "title": "PR", "state": "closed", "merged": False}],
            }
        )
        readiness = result["issues"][0]["closure_readiness"]
        self.assertFalse(readiness["candidate"])
        self.assertIn("acceptance criteria are not all explicitly checked", readiness["blockers"])
        self.assertIn("one or more linked pull requests are not verified merged", readiness["blockers"])

    def test_activity_age_is_unknown_without_timezone_aware_snapshot_time(self):
        result = analyze_tracking(
            {
                "issues": [
                    {
                        "number": 1,
                        "title": "Issue",
                        "body": "Body",
                        "state": "open",
                        "updated_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "pull_requests": [],
            }
        )
        self.assertEqual(result["issues"][0]["activity_state"], "unknown")


if __name__ == "__main__":
    unittest.main()
