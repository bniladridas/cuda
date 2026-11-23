"""Tests for fail-closed tree inspection verification."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from verify_tree_inspection import verify_report


class VerifyTreeInspectionTests(unittest.TestCase):
    def setUp(self):
        self.report = {
            "head": {"sha": "a" * 40},
            "base": {"sha": "b" * 40},
            "tree_inventory_complete": True,
            "pr_file_inventory_matches_head_tree": True,
        }

    def test_accepts_complete_matching_inventory(self):
        verify_report(self.report, "a" * 40, "b" * 40)

    def test_rejects_unexpected_head_or_base(self):
        with self.assertRaisesRegex(ValueError, "head SHA"):
            verify_report(self.report, "c" * 40, "b" * 40)
        with self.assertRaisesRegex(ValueError, "base SHA"):
            verify_report(self.report, "a" * 40, "c" * 40)

    def test_rejects_incomplete_tree_inventory(self):
        self.report["tree_inventory_complete"] = False
        with self.assertRaisesRegex(ValueError, "inventory is incomplete"):
            verify_report(self.report, "a" * 40, "b" * 40)

    def test_rejects_mismatched_pr_file_inventory(self):
        self.report["pr_file_inventory_matches_head_tree"] = False
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify_report(self.report, "a" * 40, "b" * 40)


if __name__ == "__main__":
    unittest.main()
