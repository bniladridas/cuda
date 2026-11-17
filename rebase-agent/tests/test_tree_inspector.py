"""Tests for complete, read-only GitHub tree inspection."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import tree_inspector


BASE = "1" * 40
HEAD = "2" * 40
MERGE = "3" * 40
TREE_BASE = "4" * 40
TREE_HEAD = "5" * 40
TREE_MERGE = "6" * 40


class FakeAPI:
    def __init__(self, responses):
        self.responses = responses
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if path not in self.responses:
            raise AssertionError("unexpected API path: " + path)
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value


def tree(sha, entries):
    return {"sha": sha, "truncated": False, "tree": entries}


def entry(path, sha):
    return {"path": path, "sha": sha, "type": "blob", "mode": "100644"}


class TreeTests(unittest.TestCase):
    def test_tree_rejects_truncated_and_wrong_sha(self):
        api = FakeAPI({
            "/repos/owner/repo/git/commits/" + BASE: {"tree": {"sha": TREE_BASE}},
            "/repos/owner/repo/git/trees/" + TREE_BASE + "?recursive=1":
                {"sha": TREE_BASE, "truncated": True, "tree": []}
        })
        with self.assertRaisesRegex(tree_inspector.InspectionError, "truncated"):
            tree_inspector.fetch_tree(api, "owner/repo", BASE)

    def test_tree_diff_and_overlap_are_path_based_not_conflict_claims(self):
        common = {"same.txt": {"sha": "a", "type": "blob", "mode": "100644"}}
        base = dict(common, **{"both.txt": {"sha": "b", "type": "blob", "mode": "100644"}})
        head = dict(common, **{"both.txt": {"sha": "c", "type": "blob", "mode": "100644"}})
        self.assertEqual(tree_inspector.compare_trees(base, head), {"both.txt"})

    def test_full_inspection_reports_overlap_and_binary_patchless_file(self):
        prefix = "/repos/owner/repo"
        paths = {
            prefix + "/pulls/7": {
                "base": {"sha": BASE, "ref": "main", "repo": {"full_name": "owner/repo"}},
                "head": {"sha": HEAD, "ref": "feature", "repo": {"full_name": "owner/repo"}},
            },
            prefix + "/compare/main..." + HEAD: {
                "status": "diverged", "merge_base_commit": {"sha": MERGE}
            },
            prefix + "/git/commits/" + BASE: {"tree": {"sha": TREE_BASE}},
            prefix + "/git/commits/" + HEAD: {"tree": {"sha": TREE_HEAD}},
            prefix + "/git/commits/" + MERGE: {"tree": {"sha": TREE_MERGE}},
            prefix + "/git/trees/" + TREE_BASE + "?recursive=1":
                tree(TREE_BASE, [entry("both.txt", "base"), entry("base-only.txt", "base")]),
            prefix + "/git/trees/" + TREE_HEAD + "?recursive=1":
                tree(TREE_HEAD, [entry("both.txt", "head"), entry("head-only.txt", "head")]),
            prefix + "/git/trees/" + TREE_MERGE + "?recursive=1":
                tree(TREE_MERGE, [entry("both.txt", "common")]),
            prefix + "/pulls/7/files?per_page=100&page=1": [
                {"filename": "both.txt", "status": "modified", "additions": 1, "deletions": 1, "patch": "@@"},
                {"filename": "head-only.txt", "status": "added", "additions": 1, "deletions": 0},
            ],
        }
        report = tree_inspector.inspect_pull_request(FakeAPI(paths), "owner/repo", 7)
        self.assertEqual(report["comparison_status"], "diverged")
        self.assertEqual(report["overlapping_paths"], ["both.txt"])
        self.assertFalse(report["overlap_is_conflict_proof"])
        self.assertEqual(report["pr_files_missing_patch"], ["head-only.txt"])
        self.assertTrue(report["tree_inventory_complete"])
        self.assertFalse(report["pr_file_inventory_matches_head_tree"])
        self.assertEqual(report["branch_mutation"], "not_attempted")

    def test_rejects_incomplete_compare_metadata(self):
        prefix = "/repos/owner/repo"
        api = FakeAPI({
            prefix + "/pulls/7": {
                "base": {"sha": BASE, "ref": "main", "repo": {"full_name": "owner/repo"}},
                "head": {"sha": HEAD, "ref": "feature", "repo": {"full_name": "owner/repo"}},
            },
            prefix + "/compare/main..." + HEAD: {"status": "diverged"},
        })
        with self.assertRaisesRegex(tree_inspector.InspectionError, "compare response"):
            tree_inspector.inspect_pull_request(api, "owner/repo", 7)


if __name__ == "__main__":
    unittest.main()
