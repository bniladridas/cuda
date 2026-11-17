#!/usr/bin/env python3
"""Offline tests for deterministic GitHub formatter suggestions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import format_suggestions as fs


class SuggestionTests(unittest.TestCase):
    def test_patch_parser_tracks_added_lines_only(self):
        patch = "@@ -1,2 +1,3 @@\n old\n+new\n context\n"
        self.assertEqual(fs.changed_right_lines(patch), {2})

    def test_patch_parser_handles_multiple_hunks(self):
        patch = "@@ -1 +1,2 @@\n-old\n+new\n keep\n@@ -8 +9 @@\n-old\n+newer\n"
        self.assertEqual(fs.changed_right_lines(patch), {1, 9})

    def test_changed_files_fetches_all_pages(self):
        first_page = [{"filename": "file-%03d.py" % index} for index in range(100)]
        second_page = [{"filename": "file-100.py"}]
        with mock.patch.object(fs, "request_json", side_effect=[first_page, second_page]) as request:
            files = fs.changed_files("owner/repo", 7, "token", 101)
        self.assertEqual(len(files), 101)
        self.assertIn("page=1", request.call_args_list[0].args[0])
        self.assertIn("page=2", request.call_args_list[1].args[0])

    def test_changed_files_rejects_incomplete_pagination(self):
        with unittest.mock.patch.object(fs, "request_json", return_value=[{"filename": "one.py"}]):
            with self.assertRaises(fs.SuggestionError):
                fs.changed_files("owner/repo", 7, "token", 2)

    def test_suggestion_is_limited_to_changed_lines(self):
        source = b"answer=42\nkeep = 1\n"
        formatted = b"answer = 42\nkeep = 1\n"
        comments = fs.suggestions_for("benchmarks/check.py", source, formatted, {1}, "a" * 40)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["line"], 1)
        self.assertIn("```suggestion\nanswer = 42\n```", comments[0]["body"])

    def test_context_only_formatting_is_not_commented(self):
        source = b"keep=1\nanswer=42\n"
        formatted = b"keep = 1\nanswer = 42\n"
        self.assertEqual(fs.suggestions_for("benchmarks/check.py", source, formatted, {2}, "a" * 40), [])

    def test_multiline_replacement_uses_review_range(self):
        source = b"if x: y=1\n"
        formatted = b"if x:\n    y = 1\n"
        comments = fs.suggestions_for("src/example.py", source, formatted, {1}, "a" * 40)
        self.assertEqual(len(comments), 1)
        self.assertNotIn("start_line", comments[0])
        self.assertEqual(comments[0]["line"], 1)


if __name__ == "__main__":
    unittest.main()
