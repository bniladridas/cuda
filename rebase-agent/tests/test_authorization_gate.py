"""Tests for the trusted workflow dispatch ref gate."""

import contextlib
import importlib.util
import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch


ENGINE = Path(__file__).resolve().parents[1] / "engine"
SPEC = importlib.util.spec_from_file_location("authorization_gate", ENGINE / "authorization_gate.py")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class AuthorizationGateTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_TOKEN": "test-token",
            "GITHUB_ACTOR": "maintainer",
            "GITHUB_REF": "refs/heads/main",
            "PR_NUMBER": "12",
            "OPERATION": "merge",
            "EXPECTED_HEAD_SHA": "a" * 40,
            "EXPECTED_BASE_SHA": "b" * 40,
            "APPROVAL": "UPDATE 12 " + "a" * 40 + " " + "b" * 40 + " merge",
            "REPAIR_MAINTAINERS": '["maintainer"]',
            "REPAIR_REBASE_ENABLED": "false",
            "REPAIR_MERGE_ENABLED": "true",
            "REPAIR_WRITE_ENVIRONMENT_CONFIRMED": "true",
        }
        self.api_responses = {
            "/repos/owner/repo": {"default_branch": "main"},
            "/repos/owner/repo/pulls/12": {
                "state": "open",
                "merged": False,
                "draft": False,
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
            "/repos/owner/repo/branches/feature": {"protected": False},
        }

    def test_rejects_dispatch_from_non_default_branch(self):
        self.environment["GITHUB_REF"] = "refs/heads/attacker-branch"
        with patch.dict(os.environ, self.environment, clear=True):
            with patch.object(GATE, "api", side_effect=self.api_responses.get) as api:
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        GATE.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("trusted default branch", stderr.getvalue())
        self.assertEqual(api.call_count, 1)

    def test_accepts_dispatch_from_default_branch_with_stale_pr_base_snapshot(self):
        self.api_responses["/repos/owner/repo/pulls/12"]["base"]["sha"] = "c" * 40
        with patch.dict(os.environ, self.environment, clear=True):
            with patch.object(GATE, "api", side_effect=self.api_responses.get):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    GATE.main()
        self.assertIn("branch=feature", stdout.getvalue())
        self.assertIn("default_branch=main", stdout.getvalue())

    def test_rejects_when_live_base_branch_moves(self):
        self.api_responses["/repos/owner/repo/branches/main"]["commit"]["sha"] = "c" * 40
        with patch.dict(os.environ, self.environment, clear=True):
            with patch.object(GATE, "api", side_effect=self.api_responses.get):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        GATE.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("live base branch head changed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
