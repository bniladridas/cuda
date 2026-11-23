"""Tests for the read-only proposal dispatch authorization gate."""

import contextlib
import importlib.util
import io
import os
import unittest
from unittest.mock import patch
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "engine"
SPEC = importlib.util.spec_from_file_location("proposal_gate", ENGINE / "proposal_gate.py")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class ProposalGateTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_TOKEN": "token",
            "GITHUB_ACTOR": "maintainer",
            "GITHUB_REF": "refs/heads/main",
            "PR_NUMBER": "12",
            "EXPECTED_HEAD_SHA": "a" * 40,
            "EXPECTED_BASE_SHA": "b" * 40,
            "REPAIR_MAINTAINERS": '["maintainer"]',
        }
        self.responses = {
            "/repos/owner/repo": {"default_branch": "main"},
            "/repos/owner/repo/pulls/12": {
                "state": "open",
                "merged": False,
                "draft": True,
                "base": {
                    "repo": {"full_name": "owner/repo"},
                    "sha": "b" * 40,
                    "ref": "main",
                },
                "head": {
                    "repo": {"full_name": "owner/repo"},
                    "sha": "a" * 40,
                    "ref": "feature",
                },
            },
            "/repos/owner/repo/branches/main": {"commit": {"sha": "b" * 40}},
            "/repos/owner/repo/branches/feature": {"commit": {"sha": "a" * 40}},
        }

    def run_gate(self):
        with patch.dict(os.environ, self.env, clear=True):
            with patch.object(GATE, "api", side_effect=self.responses.get):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    GATE.main()
        return output.getvalue()

    def test_accepts_same_repository_draft_pr_without_write_configuration(self):
        output = self.run_gate()
        self.assertIn("pull_request=12", output)
        self.assertIn("head_sha=" + "a" * 40, output)

    def test_rejects_non_maintainer(self):
        self.env["GITHUB_ACTOR"] = "untrusted"
        with self.assertRaises(SystemExit):
            self.run_gate()

    def test_rejects_stale_head(self):
        self.responses["/repos/owner/repo/pulls/12"]["head"]["sha"] = "c" * 40
        with self.assertRaises(SystemExit):
            self.run_gate()

    def test_rejects_fork_pr(self):
        self.responses["/repos/owner/repo/pulls/12"]["head"]["repo"] = {
            "full_name": "contributor/fork"
        }
        with self.assertRaises(SystemExit):
            self.run_gate()

    def test_rejects_dispatch_from_non_default_branch(self):
        self.env["GITHUB_REF"] = "refs/heads/feature"
        with self.assertRaises(SystemExit):
            self.run_gate()


if __name__ == "__main__":
    unittest.main()
