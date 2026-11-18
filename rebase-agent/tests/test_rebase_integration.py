"""Real-Git integration tests for safe rebase operations."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import rebase


def git(path, *args):
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


class RebaseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "work"
        self.other = self.root / "other"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(self.remote), str(self.repo)], check=True, capture_output=True)
        git(self.repo, "config", "user.name", "Rebase Test")
        git(self.repo, "config", "user.email", "rebase-test@example.invalid")
        (self.repo / "shared.txt").write_text("initial\n", encoding="utf-8")
        git(self.repo, "add", "shared.txt")
        git(self.repo, "commit", "-m", "initial")
        git(self.repo, "branch", "-M", "main")
        git(self.repo, "push", "-u", "origin", "main")
        git(self.repo, "switch", "-c", "feature")
        (self.repo / "feature.txt").write_text("feature\n", encoding="utf-8")
        git(self.repo, "add", "feature.txt")
        git(self.repo, "commit", "-m", "feature")
        git(self.repo, "push", "-u", "origin", "feature")
        self.head_sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "main")
        (self.repo / "shared.txt").write_text("base update\n", encoding="utf-8")
        git(self.repo, "add", "shared.txt")
        git(self.repo, "commit", "-m", "base update")
        git(self.repo, "push", "origin", "main")
        self.base_sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "feature")
        git(self.repo, "reset", "--hard", "origin/feature")

    def tearDown(self):
        self.temp.cleanup()

    def request(self, **changes):
        value = {
            "repository": "owner/repo",
            "head_repository": "owner/repo",
            "branch": "feature",
            "base_branch": "main",
            "default_branch": "main",
            "protected_branches": [],
            "expected_remote_sha": self.head_sha,
            "expected_base_sha": self.base_sha,
            "authorization": True,
            "rebase_enabled": True,
        }
        value.update(changes)
        return value

    def test_clean_rebase_preserves_commit_and_updates_with_lease(self):
        result = rebase.rebase_and_push(self.repo, self.request())
        self.assertEqual(result["operation"], "rebase")
        self.assertTrue(result["force_with_lease"])
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/feature"), result["new_sha"])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD^"), self.base_sha)
        self.assertEqual(git(self.repo, "show", "HEAD:feature.txt"), "feature")

    def test_conflict_aborts_and_leaves_remote_unchanged(self):
        (self.repo / "shared.txt").write_text("feature conflict\n", encoding="utf-8")
        git(self.repo, "add", "shared.txt")
        git(self.repo, "commit", "-m", "feature conflicting edit")
        git(self.repo, "push", "origin", "feature")
        self.head_sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "main")
        (self.repo / "shared.txt").write_text("base conflicting edit\n", encoding="utf-8")
        git(self.repo, "add", "shared.txt")
        git(self.repo, "commit", "-m", "base conflicting edit")
        git(self.repo, "push", "origin", "main")
        self.base_sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "feature")
        git(self.repo, "reset", "--hard", "origin/feature")
        before = git(self.remote, "rev-parse", "refs/heads/feature")
        with self.assertRaisesRegex(rebase.RebaseError, "human resolution"):
            rebase.rebase_and_push(self.repo, self.request())
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/feature"), before)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_stale_base_stops_before_rebase(self):
        stale = self.base_sha
        git(self.repo, "switch", "main")
        (self.repo / "another.txt").write_text("new base\n", encoding="utf-8")
        git(self.repo, "add", "another.txt")
        git(self.repo, "commit", "-m", "advance base")
        git(self.repo, "push", "origin", "main")
        git(self.repo, "switch", "feature")
        with self.assertRaisesRegex(rebase.RebaseError, "base branch moved"):
            rebase.rebase_and_push(self.repo, self.request(expected_base_sha=stale))

    def test_stale_remote_head_stops_before_rebase(self):
        subprocess.run(["git", "clone", str(self.remote), str(self.other)], check=True, capture_output=True)
        git(self.other, "config", "user.name", "Concurrent")
        git(self.other, "config", "user.email", "concurrent@example.invalid")
        git(self.other, "switch", "feature")
        (self.other / "concurrent.txt").write_text("concurrent\n", encoding="utf-8")
        git(self.other, "add", "concurrent.txt")
        git(self.other, "commit", "-m", "concurrent update")
        git(self.other, "push", "origin", "feature")
        with self.assertRaisesRegex(rebase.RebaseError, "remote PR branch moved"):
            rebase.rebase_and_push(self.repo, self.request())

    def test_dirty_worktree_is_rejected(self):
        (self.repo / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(rebase.RebaseError, "not clean"):
            rebase.rebase_and_push(self.repo, self.request())


if __name__ == "__main__":
    unittest.main()
