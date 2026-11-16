#!/usr/bin/env python3
"""Offline policy tests for the PR Scope Guard workflow."""

import json
import unittest
from pathlib import Path

import yaml

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pr-scope-guard.yml"


class ScopeGuardWorkflowTests(unittest.TestCase):
    def load_workflow(self):
        with WORKFLOW_PATH.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def triggers(self, workflow):
        triggers = workflow.get("on")
        if triggers is None:
            triggers = workflow.get(True)
        return triggers

    def test_triggers_on_the_base_side(self):
        triggers = self.triggers(self.load_workflow())
        self.assertNotIn("pull_request", triggers)
        self.assertEqual(
            triggers["pull_request_target"]["types"],
            ["opened", "edited", "synchronize", "reopened", "ready_for_review"],
        )
        self.assertIn("pr_number", triggers["workflow_dispatch"]["inputs"])

    def test_permissions_are_read_only(self):
        workflow = self.load_workflow()
        self.assertEqual(workflow["permissions"], {"contents": "read", "pull-requests": "read"})

    def test_checks_out_the_default_branch_without_credentials(self):
        workflow = self.load_workflow()
        checkout = next(
            step
            for step in workflow["jobs"]["scope-guard"]["steps"]
            if step.get("uses", "").startswith("actions/checkout")
        )
        self.assertIn("default_branch", checkout["with"]["ref"])
        self.assertIs(checkout["with"]["persist-credentials"], False)

    def test_uses_only_official_actions(self):
        workflow = self.load_workflow()
        for step in workflow["jobs"]["scope-guard"]["steps"]:
            if "uses" in step:
                self.assertTrue(step["uses"].startswith("actions/"), step["uses"])

    def test_references_no_secret_and_no_write_permission(self):
        dumped = json.dumps(self.load_workflow())
        self.assertNotIn("secrets.", dumped)
        self.assertNotIn("write", dumped)

    def test_invokes_the_engine_with_validated_inputs(self):
        workflow = self.load_workflow()
        steps = workflow["jobs"]["scope-guard"]["steps"]
        resolve = next(step for step in steps if step.get("id") == "target")
        self.assertIn("${{ github.event.pull_request.number", resolve["env"]["PR_NUMBER"])
        self.assertIn('[[ ! "$PR_NUMBER" =~ ^[0-9]+$ ]]', resolve["run"])
        run = next(step for step in steps if "scope_guard.py" in step.get("run", ""))["run"]
        self.assertIn("--repo", run)
        self.assertIn("--pr", run)
        self.assertIn("--artifact-out", run)
        self.assertIn("$GITHUB_STEP_SUMMARY", run)


if __name__ == "__main__":
    unittest.main()
