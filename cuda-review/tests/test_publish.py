"""Tests for CUDA Review output validation and inline anchoring."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from publish import added_lines, build_review


DIFF = """diff --git a/src/kernel.cu b/src/kernel.cu
index 1111111..2222222 100644
--- a/src/kernel.cu
+++ b/src/kernel.cu
@@ -4,2 +4,3 @@
 unchanged
-old
+new
+extra
"""


def report(findings):
    return {
        "patch_applied": False,
        "complete_diff_supplied": True,
        "complete_file_inventory": True,
        "summary": "Review completed.",
        "model": "openrouter/free",
        "findings": findings,
    }


class PublishTests(unittest.TestCase):
    def test_added_lines_are_tracked(self):
        self.assertEqual(added_lines(DIFF), {"src/kernel.cu": {5, 6}})

    def test_added_line_becomes_inline_comment(self):
        finding = {
            "severity": "high",
            "path": "src/kernel.cu",
            "line": 5,
            "reason": "This branch can access an uninitialized value.",
            "confidence": "high",
        }
        result = build_review(report([finding]), DIFF, "a" * 40)
        self.assertEqual(result["event"], "COMMENT")
        self.assertEqual(result["comments"][0]["line"], 5)
        self.assertEqual(result["comments"][0]["side"], "RIGHT")

    def test_unchanged_line_is_summary_only(self):
        finding = {
            "severity": "medium",
            "path": "src/kernel.cu",
            "line": 4,
            "reason": "The surrounding contract is unclear.",
            "confidence": "medium",
        }
        result = build_review(report([finding]), DIFF, "a" * 40)
        self.assertEqual(result["comments"], [])
        self.assertIn("src/kernel.cu:4", result["body"])

    def test_clean_review_has_explicit_no_findings(self):
        result = build_review(report([]), DIFF, "a" * 40)
        self.assertIn("No actionable findings", result["body"])

    def test_incomplete_review_is_rejected(self):
        value = report([])
        value["complete_diff_supplied"] = False
        with self.assertRaisesRegex(ValueError, "complete diff"):
            build_review(value, DIFF, "a" * 40)

    def test_patch_report_is_rejected(self):
        value = report([])
        value["patch_applied"] = True
        with self.assertRaisesRegex(ValueError, "must not contain a patch"):
            build_review(value, DIFF, "a" * 40)

    def test_finding_must_reference_changed_file(self):
        finding = {
            "severity": "low",
            "path": "../outside",
            "line": 5,
            "reason": "bad",
            "confidence": "high",
        }
        with self.assertRaisesRegex(ValueError, "changed file"):
            build_review(report([finding]), DIFF, "a" * 40)


if __name__ == "__main__":
    unittest.main()
