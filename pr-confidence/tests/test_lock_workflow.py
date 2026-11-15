#!/usr/bin/env python3
"""Offline policy tests for the merged pull request lock workflow."""

import json
import unittest
from pathlib import Path

import yaml

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "lock-merged-pr.yml"


class LockMergedPullRequestWorkflowTests(unittest.TestCase):
    def load_workflow(self):
        with WORKFLOW_PATH.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def test_runs_from_the_trusted_base_event_on_close(self):
        workflow = self.load_workflow()
        triggers = workflow.get("on")
        if triggers is None:
            triggers = workflow.get(True)
        self.assertEqual(triggers["pull_request_target"]["types"], ["closed"])

    def test_locks_only_merged_pull_requests(self):
        workflow = self.load_workflow()
        self.assertEqual(
            workflow["jobs"]["lock"]["if"],
            "github.event.pull_request.merged == true",
        )

    def test_has_only_pull_requests_write_permission(self):
        workflow = self.load_workflow()
        self.assertEqual(workflow["permissions"], {"pull-requests": "write"})

    def test_has_no_checkout_or_third_party_actions(self):
        workflow = self.load_workflow()
        steps = workflow["jobs"]["lock"]["steps"]
        self.assertEqual(len(steps), 1)
        self.assertNotIn("uses", steps[0])
        self.assertNotIn("actions/", json.dumps(workflow))
        self.assertNotIn("secrets.", json.dumps(workflow))

    def test_locks_with_resolved_reason_and_validated_number(self):
        workflow = self.load_workflow()
        step = workflow["jobs"]["lock"]["steps"][0]
        script = step["run"]
        self.assertIn("gh api --method PUT", script)
        self.assertIn('"repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/lock"', script)
        self.assertIn("lock_reason=resolved", script)
        self.assertEqual(
            step["env"]["PR_NUMBER"],
            "${{ github.event.pull_request.number }}",
        )
        self.assertNotIn("${{ github.event.pull_request.number }}", script)
        self.assertIn('[[ ! "$PR_NUMBER" =~ ^[0-9]+$ ]]', script)


if __name__ == "__main__":
    unittest.main()
