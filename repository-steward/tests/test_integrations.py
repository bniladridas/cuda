import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.integrations import integration_status


class IntegrationAdapterTests(unittest.TestCase):
    def test_missing_evidence_is_unavailable(self):
        result = integration_status({"head_sha": "abc"})
        self.assertEqual(result["integrations"]["label_review"]["state"], "unavailable")
        self.assertEqual(result["integrations"]["issue_landing"]["state"], "unavailable")
        self.assertFalse(result["mutations_performed"])

    def test_current_workflow_evidence_does_not_imply_approval(self):
        result = integration_status(
            {
                "head_sha": "abc",
                "integration_evidence": {
                    "label_review": {
                        "state": "success",
                        "head_sha": "abc",
                        "source": "workflow run 12",
                        "url": "https://example.invalid/run/12",
                    },
                    "issue_landing": {
                        "state": "pending",
                        "head_sha": "abc",
                        "source": "workflow run 13",
                    },
                },
            }
        )
        label = result["integrations"]["label_review"]
        landing = result["integrations"]["issue_landing"]
        self.assertEqual(label["state"], "success")
        self.assertEqual(label["approval_status"], "not_asserted")
        self.assertIsNone(label["revision_match"])
        self.assertEqual(label["approval_environment"], "label-review")
        self.assertEqual(landing["state"], "pending")
        self.assertEqual(landing["approval_environment"], "issue-landing-close")
        self.assertFalse(label["coordinator_write_performed"])
        self.assertFalse(result["mutations_performed"])

    def test_stale_evidence_is_unknown_not_success(self):
        result = integration_status(
            {
                "head_sha": "new",
                "integration_evidence": {
                    "label_review": {
                        "state": "success",
                        "head_sha": "old",
                        "expected_sha": "new",
                    },
                },
            }
        )
        item = result["integrations"]["label_review"]
        self.assertEqual(item["state"], "unknown")
        self.assertFalse(item["revision_match"])

    def test_unknown_states_remain_unknown(self):
        result = integration_status(
            {
                "head_sha": "abc",
                "integration_evidence": {
                    "issue_landing": {"state": "something-new", "head_sha": "abc"},
                },
            }
        )
        self.assertEqual(result["integrations"]["issue_landing"]["state"], "unknown")


    def test_pr_artifacts_are_bound_to_exact_pr_head_and_preserved(self):
        confidence = {
            "rubric_version": 1,
            "head_sha": "abc",
            "score": 4,
            "categories": [],
            "blockers": [],
            "notes": [],
            "pr": {"number": 7},
            "files": {"available": True, "truncated": False},
            "checks": {"available": True, "truncated": False},
            "review": {"available": True},
        }
        scope = {
            "version": 1,
            "pr_number": 7,
            "head_sha": "abc",
            "coverage": {"complete": True, "expected_files": 2, "fetched_files": 2},
            "files": [],
            "findings": [{"code": "advisory"}],
            "counts": {},
        }
        result = integration_status(
            {
                "pull_requests": [{"number": 7, "head_sha": "abc"}],
                "pull_request_integrations": {
                    "7": {
                        "pr_confidence": {"state": "success", "evidence": confidence},
                        "pr_scope_guard": {"state": "success", "evidence": scope},
                    }
                },
            }
        )
        integrations = result["integrations"]
        self.assertEqual(integrations["pr_confidence"]["pull_requests"]["7"]["state"], "current")
        self.assertEqual(integrations["pr_confidence"]["pull_requests"]["7"]["evidence"]["score"], 4)
        self.assertEqual(integrations["pr_scope_guard"]["pull_requests"]["7"]["state"], "current")
        self.assertEqual(
            integrations["pr_scope_guard"]["pull_requests"]["7"]["evidence"]["findings"],
            [{"code": "advisory"}],
        )
        self.assertFalse(integrations["pr_confidence"]["approval_required"])
        self.assertFalse(result["mutations_performed"])

    def test_pr_evidence_distinguishes_stale_incomplete_and_malformed(self):
        confidence = {
            "rubric_version": 1,
            "head_sha": "old",
            "score": 2,
            "categories": [],
            "blockers": [],
            "notes": [],
            "pr": {"number": 8},
            "files": {"available": True},
            "checks": {"available": True},
            "review": {"available": True},
        }
        scope = {
            "version": 1,
            "pr_number": 8,
            "head_sha": "new",
            "coverage": {"complete": False},
            "files": [],
            "findings": [],
            "counts": {},
        }
        result = integration_status(
            {
                "pull_requests": [{"number": 8, "head_sha": "new"}],
                "pull_request_integrations": {
                    "8": {
                        "pr_confidence": {"state": "success", "evidence": confidence},
                        "pr_scope_guard": {"state": "success", "evidence": scope},
                    }
                },
            }
        )["integrations"]
        self.assertEqual(result["pr_confidence"]["pull_requests"]["8"]["state"], "stale")
        self.assertEqual(result["pr_scope_guard"]["pull_requests"]["8"]["state"], "incomplete")

    def test_pr_workflow_pending_and_failed_are_distinct(self):
        result = integration_status(
            {
                "pull_requests": [{"number": 9, "head_sha": "abc"}],
                "pull_request_integrations": {
                    "9": {
                        "pr_confidence": {"workflow_state": "pending"},
                        "pr_scope_guard": {"workflow_state": "failed"},
                    }
                },
            }
        )["integrations"]
        self.assertEqual(result["pr_confidence"]["pull_requests"]["9"]["state"], "pending")
        self.assertEqual(result["pr_scope_guard"]["pull_requests"]["9"]["state"], "failed")

    def test_missing_pr_artifacts_are_explicit(self):
        result = integration_status(
            {
                "pull_requests": [{"number": 10, "head_sha": "abc"}],
            }
        )["integrations"]
        self.assertEqual(result["pr_confidence"]["pull_requests"]["10"]["state"], "missing")
        self.assertEqual(result["pr_scope_guard"]["pull_requests"]["10"]["state"], "missing")

if __name__ == "__main__":
    unittest.main()
