#!/usr/bin/env python3
"""Offline workflow security and permission policy tests."""

import json
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "format-repair.yml"
CONFIG = ROOT / ".github" / "format-repair.yml"


class WorkflowPolicyTests(unittest.TestCase):
    def read(self, path):
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def triggers(self, workflow):
        return workflow.get("on", workflow.get(True))

    def test_pull_request_target_and_manual_report(self):
        triggers = self.triggers(self.read(WORKFLOW))
        self.assertNotIn("pull_request", triggers)
        self.assertIn("labeled", triggers["pull_request_target"]["types"])
        self.assertIn("pr_number", triggers["workflow_dispatch"]["inputs"])

    def test_report_permissions_are_read_only(self):
        report = self.read(WORKFLOW)["jobs"]["report"]
        self.assertEqual(report["permissions"], {"contents": "read", "pull-requests": "read"})
        self.assertNotIn("write", json.dumps(report))
        self.assertNotIn("secrets.", json.dumps(report))

    def test_repair_requires_the_exact_approval_label_event(self):
        repair = self.read(WORKFLOW)["jobs"]["repair"]
        self.assertIn("github.event.action == 'labeled'", repair["if"])
        self.assertIn("github.event.label.name == 'format-fix:approved'", repair["if"])
        self.assertEqual(repair["permissions"], {
            "contents": "write", "issues": "write", "pull-requests": "read"
        })

    def test_default_branch_code_is_checked_out_without_credentials(self):
        workflow = self.read(WORKFLOW)
        for name in ("report", "repair"):
            step = next(x for x in workflow["jobs"][name]["steps"]
                        if x.get("name") == "Check out trusted default branch")
            self.assertIn("default_branch", step["with"]["ref"])
            self.assertIs(step["with"]["persist-credentials"], False)

    def test_same_repo_and_head_are_checked_before_pr_checkout(self):
        steps = self.read(WORKFLOW)["jobs"]["repair"]["steps"]
        preflight = next(x for x in steps if x.get("name") == "Revalidate same-repository head before checkout")
        checkout = next(i for i, x in enumerate(steps)
                        if x.get("name") == "Check out the approved PR head as data")
        self.assertLess(steps.index(preflight), checkout)
        self.assertIn("HEAD_REPO", preflight["run"])
        self.assertIn("EVENT_HEAD_SHA", preflight["run"])
        self.assertIn("HAS_LABEL", preflight["run"])

    def test_pr_checkout_is_data_only_and_credentials_are_disabled(self):
        step = next(x for x in self.read(WORKFLOW)["jobs"]["repair"]["steps"]
                    if x.get("name") == "Check out the approved PR head as data")
        self.assertEqual(step["with"]["path"], "work")
        self.assertIs(step["with"]["persist-credentials"], False)

    def test_engine_runs_from_trusted_checkout(self):
        workflow = self.read(WORKFLOW)
        self.assertTrue(any("format_repair.py report" in x.get("run", "")
                            for x in workflow["jobs"]["report"]["steps"]))
        self.assertTrue(any("steward/format-repair/engine/format_repair.py repair" in x.get("run", "")
                            for x in workflow["jobs"]["repair"]["steps"]))

    def test_formatter_uses_trusted_base_branch_style_file(self):
        workflow = self.read(WORKFLOW)
        report_run = next(x["run"] for x in workflow["jobs"]["report"]["steps"]
                          if "format_repair.py report" in x.get("run", ""))
        repair_run = next(x["run"] for x in workflow["jobs"]["repair"]["steps"]
                          if "format_repair.py repair" in x.get("run", ""))
        self.assertIn("--style-file .clang-format", report_run)
        self.assertIn("--style-file steward/.clang-format", repair_run)

    def test_formatter_pin_matches_configuration(self):
        version = self.read(CONFIG)["formatter_version"]
        for job in ("report", "repair"):
            step = next(x for x in self.read(WORKFLOW)["jobs"][job]["steps"]
                        if "clang-format==" in x.get("run", ""))
            self.assertIn("clang-format==" + version, step["run"])

    def test_success_removes_only_approval_label_and_acknowledges(self):
        steps = self.read(WORKFLOW)["jobs"]["repair"]["steps"]
        step = next(x for x in steps if x.get("name") == "Remove approval label and acknowledge result")
        self.assertIn("gh pr edit", step["run"])
        self.assertIn("format-fix:approved", step["run"])
        self.assertIn("commit_sha", step["run"])
        self.assertIn("gh pr comment", step["run"])


if __name__ == "__main__":
    unittest.main()
