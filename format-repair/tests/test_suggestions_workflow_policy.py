#!/usr/bin/env python3
"""Security policy tests for the inline formatter suggestion workflow."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "format-suggestions.yml"


class SuggestionWorkflowPolicyTests(unittest.TestCase):
    def test_uses_pull_request_target_and_only_comment_permissions(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(
            triggers["pull_request_target"]["types"],
            ["opened", "synchronize", "reopened", "ready_for_review"],
        )
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["suggest"]
        self.assertEqual(job["permissions"], {"contents": "read", "pull-requests": "write"})

    def test_checks_out_trusted_default_branch_without_credentials(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = workflow["jobs"]["suggest"]["steps"]
        checkout = next(step for step in steps if step.get("name") == "Check out trusted default branch")
        self.assertIn("default_branch", checkout["with"]["ref"])
        self.assertIs(checkout["with"]["persist-credentials"], False)
        self.assertFalse(any("pull_request.head" in str(step.get("with", {})) for step in steps))

    def test_runs_trusted_formatter_script_and_pins_versions(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = workflow["jobs"]["suggest"]["steps"]
        install = next(step for step in steps if "clang-format==" in step.get("run", ""))
        run = next(step for step in steps if "format_suggestions.py" in step.get("run", ""))
        self.assertIn("clang-format==22.1.8", install["run"])
        self.assertIn("ruff==0.17.5", install["run"])
        self.assertIn("GH_TOKEN", run["env"])
        self.assertIn("PR_NUMBER", run["env"])


if __name__ == "__main__":
    unittest.main()
