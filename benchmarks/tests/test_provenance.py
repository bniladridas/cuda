"""Tests for benchmark result provenance."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from provenance import attach_provenance, current_commit, write_provenance


class ProvenanceTests(unittest.TestCase):
    def test_attaches_full_commit_and_utc_timestamp(self):
        data = {"gpu": "Test GPU", "results": []}
        result = attach_provenance(data, "a" * 40, "2026-11-17T12:00:00Z")
        self.assertEqual(result["git_commit"], "a" * 40)
        self.assertEqual(result["timestamp_utc"], "2026-11-17T12:00:00Z")
        self.assertNotIn("git_commit", data)

    def test_represents_missing_git_metadata_as_null(self):
        result = attach_provenance({"gpu": "Test GPU"}, None, "2026-11-17T12:00:00Z")
        self.assertIsNone(result["git_commit"])

    def test_rejects_short_or_non_hex_commit(self):
        for commit in ("abc123", "g" * 40):
            with self.subTest(commit=commit):
                with self.assertRaisesRegex(ValueError, "full hexadecimal"):
                    attach_provenance({}, commit, "2026-11-17T12:00:00Z")

    def test_rejects_non_utc_timestamp(self):
        with self.assertRaisesRegex(ValueError, "UTC"):
            attach_provenance({}, "a" * 40, "2026-11-17T12:00:00+05:30")

    def test_write_provenance_preserves_benchmark_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps({"gpu": "Test GPU", "results": []}), encoding="utf-8")
            write_provenance(path, Path(directory))
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["gpu"], "Test GPU")
            self.assertEqual(result["results"], [])
            self.assertIn("timestamp_utc", result)
            self.assertTrue(result["timestamp_utc"].endswith("Z"))
            self.assertIn("git_commit", result)

    def test_current_commit_is_full_sha_inside_repository(self):
        root = Path(__file__).resolve().parents[2]
        commit = current_commit(root)
        self.assertIsNotNone(commit)
        self.assertIn(len(commit), (40, 64))
        self.assertTrue(all(char in "0123456789abcdef" for char in commit))


if __name__ == "__main__":
    unittest.main()
