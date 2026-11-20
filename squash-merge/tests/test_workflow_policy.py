import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SquashMergeWorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/squash-merge.yml").read_text()
        self.config = json.loads((ROOT / ".github/squash-merge.json").read_text())

    def test_only_approval_label_event_triggers_workflow(self):
        self.assertIn("pull_request_target:", self.workflow)
        self.assertIn("types: [labeled]", self.workflow)
        self.assertIn("github.event.action == 'labeled'", self.workflow)
        self.assertIn("github.event.label.name == 'squash-merge:approved'", self.workflow)
        self.assertNotIn("workflow_dispatch:", self.workflow)

    def test_concurrency_does_not_cancel_in_flight_merge(self):
        self.assertIn("group: squash-merge-", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_job_permissions_are_explicit_and_minimal_for_gate(self):
        for permission in (
            "checks: read",
            "contents: write",
            "issues: write",
            "pull-requests: write",
            "statuses: read",
        ):
            self.assertIn(permission, self.workflow)

    def test_only_trusted_default_branch_code_is_checked_out(self):
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)
        self.assertNotIn("github.event.pull_request.head.ref", self.workflow)

    def test_policy_requires_successful_checks_and_squash_only(self):
        self.assertEqual(self.config["merge_method"], "squash")
        self.assertEqual(
            set(self.config["required_check_runs"]),
            {"cpu", "python", "PR Confidence", "PR Scope Guard"},
        )
        self.assertNotIn("analyze (c-cpp)", self.config["required_check_runs"])
        self.assertNotIn("CodeQL", self.config["required_check_runs"])
        self.assertEqual(self.config["required_status_contexts"], [])
        self.assertIn("bniladridas", self.config["maintainers"])


if __name__ == "__main__":
    unittest.main()
