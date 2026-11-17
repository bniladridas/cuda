"""Offline tests for approval and SHA-safe PR branch rebases."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import rebase

OLD = "1" * 40
NEW = "2" * 40
BASE = "3" * 40


def request(**changes):
    value = {
        "repository": "owner/cuda",
        "head_repository": "owner/cuda",
        "branch": "feature/fix",
        "base_branch": "main",
        "default_branch": "main",
        "protected_branches": ["release"],
        "expected_remote_sha": OLD,
        "expected_base_sha": BASE,
        "authorization": True,
        "rebase_enabled": True,
    }
    value.update(changes)
    return value


def fake_runner(responses, calls):
    def run(command, **kwargs):
        calls.append(command[3:])
        code, stdout, stderr = responses.pop(0)
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)

    return run


class ValidationTests(unittest.TestCase):
    def test_accepts_explicit_same_repository_rebase(self):
        rebase.validate_request(request())

    def test_rejects_missing_approval_or_disabled_policy(self):
        for changes, message in [
            ({"authorization": False}, "authorization"),
            ({"rebase_enabled": False}, "policy"),
        ]:
            with self.subTest(changes=changes), self.assertRaisesRegex(rebase.RebaseError, message):
                rebase.validate_request(request(**changes))

    def test_rejects_fork_default_protected_and_invalid_refs(self):
        cases = [
            ({"head_repository": "contributor/cuda"}, "fork"),
            ({"branch": "main"}, "default"),
            ({"branch": "release"}, "protected"),
            ({"branch": "../main"}, "branch name"),
            ({"expected_remote_sha": "deadbeef"}, "40-character"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(rebase.RebaseError, message):
                rebase.validate_request(request(**changes))


class OperationTests(unittest.TestCase):
    def invoke(self, responses):
        calls = []
        result = rebase.rebase_and_push(".", request(), fake_runner(responses, calls))
        return result, calls

    def test_local_head_must_match_approved_sha(self):
        calls = []
        responses = [(0, "", ""), (0, "feature/fix", ""), (0, NEW, "")]
        with self.assertRaisesRegex(rebase.RebaseError, "local branch HEAD"):
            rebase.rebase_and_push(".", request(), fake_runner(responses, calls))
        self.assertFalse(any(args and args[0] == "fetch" for args in calls))

    def test_remote_movement_before_rebase_stops(self):
        calls = [(0, "", ""), (0, "feature/fix", ""), (0, OLD, ""), (0, "", ""), (0, NEW, "")]
        recorded = []
        with self.assertRaisesRegex(rebase.RebaseError, "moved before rebase"):
            rebase.rebase_and_push(".", request(), fake_runner(calls, recorded))
        self.assertFalse(any(args and args[0] in {"rebase", "push"} for args in recorded))

    def test_conflict_aborts_and_never_pushes(self):
        responses = [
            (0, "", ""),
            (0, "feature/fix", ""),
            (0, OLD, ""),
            (0, "", ""),
            (0, OLD, ""),
            (0, BASE, ""),
            (1, "", "CONFLICT"),
            (0, "", ""),
        ]
        calls = []
        with self.assertRaisesRegex(rebase.RebaseError, "human resolution"):
            rebase.rebase_and_push(".", request(), fake_runner(responses, calls))
        self.assertIn(["rebase", "--abort"], calls)
        self.assertFalse(any(args and args[0] == "push" for args in calls))

    def test_remote_movement_after_rebase_stops(self):
        responses = [
            (0, "", ""),
            (0, "feature/fix", ""),
            (0, OLD, ""),
            (0, "", ""),
            (0, OLD, ""),
            (0, BASE, ""),
            (0, "", ""),
            (0, "", ""),
            (0, NEW, ""),
            (0, BASE, ""),
        ]
        calls = []
        with self.assertRaisesRegex(rebase.RebaseError, "moved during rebase"):
            rebase.rebase_and_push(".", request(), fake_runner(responses, calls))
        self.assertFalse(any(args and args[0] == "push" for args in calls))

    def test_push_uses_exact_force_with_lease(self):
        responses = [
            (0, "", ""),
            (0, "feature/fix", ""),
            (0, OLD, ""),
            (0, "", ""),
            (0, OLD, ""),
            (0, BASE, ""),
            (0, "", ""),
            (0, "", ""),
            (0, OLD, ""),
            (0, BASE, ""),
            (0, "", ""),
            (0, NEW, ""),
        ]
        result, calls = self.invoke(responses)
        push = next(args for args in calls if args and args[0] == "push")
        self.assertIn("--force-with-lease=refs/heads/feature/fix:" + OLD, push)
        self.assertEqual(result["old_sha"], OLD)
        self.assertEqual(result["new_sha"], NEW)
        self.assertTrue(result["force_with_lease"])


if __name__ == "__main__":
    unittest.main()
