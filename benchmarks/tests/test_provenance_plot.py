"""Tests for embedded benchmark provenance validation and legacy inputs."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import plot_results


class ProvenanceValidationTests(unittest.TestCase):
    def load_data(self, extra):
        data = {
            "gpu": "Test GPU",
            "results": [{"kernel": "vecadd", "n": 1024, "gb_per_s": 12.5}],
            **extra,
        }
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
        with handle:
            json.dump(data, handle)
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return plot_results.load(handle.name)

    def test_accepts_legacy_results_without_embedded_provenance(self):
        result = self.load_data({})
        self.assertNotIn("git_commit", result)
        self.assertNotIn("timestamp_utc", result)

    def test_accepts_full_commit_and_utc_timestamp(self):
        result = self.load_data({
            "git_commit": "a" * 40,
            "timestamp_utc": "2026-11-17T12:00:00Z",
        })
        self.assertEqual(result["git_commit"], "a" * 40)

    def test_accepts_missing_git_metadata_as_null(self):
        result = self.load_data({
            "git_commit": None,
            "timestamp_utc": "2026-11-17T12:00:00Z",
        })
        self.assertIsNone(result["git_commit"])

    def test_rejects_partial_provenance(self):
        with self.assertRaisesRegex(ValueError, "requires both"):
            self.load_data({"git_commit": "a" * 40})

    def test_rejects_invalid_commit(self):
        with self.assertRaisesRegex(ValueError, "full hexadecimal"):
            self.load_data({
                "git_commit": "short",
                "timestamp_utc": "2026-11-17T12:00:00Z",
            })

    def test_rejects_invalid_timestamp(self):
        for timestamp in ("not-a-dateZ", "2026-11-17T12:00:00+05:30", 123):
            with self.subTest(timestamp=timestamp):
                with self.assertRaisesRegex(ValueError, "timestamp_utc"):
                    self.load_data({
                        "git_commit": "a" * 40,
                        "timestamp_utc": timestamp,
                    })


if __name__ == "__main__":
    unittest.main()
