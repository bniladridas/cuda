"""Real-Git integration tests for the separately authorized merge operation."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import merge_agent


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


class MergeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "work"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(self.remote), str(self.repo)], check=True, capture_output=True)
        git(self.repo, "config", "user.name", "Merge Test")
        git(self.repo, "config", "user.email", "merge-test@example.invalid")
        (self.repo / "base.txt").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", "base.txt")
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
        (self.repo / "base.txt").write_text("base updated\n", encoding="utf-8")
        git(self.repo, "add", "base.txt")
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
            "expected_head_sha": self.head_sha,
            "expected_base_sha": self.base_sha,
            "merge_authorization": True,
            "merge_enabled": True,
        }
        value.update(changes)
        return value

    def test_clean_merge_creates_two_parents_and_fast_forward_push(self):
        result = merge_agent.merge_and_push(self.repo, self.request())
        self.assertEqual(result["operation"], "merge")
        self.assertEqual(result["parents"], [self.head_sha, self.base_sha])
        self.assertFalse(result["force_push"])
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/feature"), result["new_sha"])
        self.assertEqual(
            git(self.repo, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:],
            [
                self.head_sha,
                self.base_sha,
            ],
        )

    def test_conflict_aborts_without_updating_remote(self):
        (self.repo / "base.txt").write_text("feature conflicting edit\n", encoding="utf-8")
        git(self.repo, "add", "base.txt")
        git(self.repo, "commit", "-m", "feature conflicting edit")
        git(self.repo, "push", "origin", "feature")
        self.head_sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "main")
        (self.repo / "base.txt").write_text("base conflicting edit\n", encoding="utf-8")
        git(self.repo, "add", "base.txt")
        git(self.repo, "commit", "-m", "base conflicting edit")
        git(self.repo, "push", "origin", "main")
        self.base_sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "feature")
        git(self.repo, "reset", "--hard", "origin/feature")
        before = git(self.remote, "rev-parse", "refs/heads/feature")
        with self.assertRaisesRegex(merge_agent.MergeError, "human resolution"):
            merge_agent.merge_and_push(self.repo, self.request())
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/feature"), before)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_requires_separate_approval_and_policy(self):
        for changes, message in [
            ({"merge_authorization": False}, "separate explicit"),
            ({"merge_enabled": False}, "not enabled"),
        ]:
            with self.subTest(changes=changes), self.assertRaisesRegex(merge_agent.MergeError, message):
                merge_agent.merge_and_push(self.repo, self.request(**changes))


if __name__ == "__main__":
    unittest.main()
