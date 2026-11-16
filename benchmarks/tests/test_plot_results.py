"""Tests for benchmark result validation and CLI errors."""

import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import plot_results


class LoadResultsTests(unittest.TestCase):
    def write_json(self, value):
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
        with handle:
            json.dump(value, handle, allow_nan=True)
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def valid_data(self):
        return {
            "gpu": "Test GPU",
            "results": [{"kernel": "vecadd", "n": 1024, "gb_per_s": 12.5}],
        }

    def test_accepts_valid_results(self):
        path = self.write_json(self.valid_data())
        self.assertEqual(plot_results.load(path), self.valid_data())

    def test_rejects_non_object_top_level(self):
        path = self.write_json([])
        with self.assertRaisesRegex(ValueError, "expected a JSON object"):
            plot_results.load(path)

    def test_rejects_missing_top_level_key(self):
        path = self.write_json({"gpu": "Test GPU"})
        with self.assertRaisesRegex(ValueError, "missing top-level"):
            plot_results.load(path)

    def test_rejects_empty_gpu_label(self):
        data = self.valid_data()
        data["gpu"] = "  "
        with self.assertRaisesRegex(ValueError, "field 'gpu'"):
            plot_results.load(self.write_json(data))

    def test_rejects_non_list_or_empty_results(self):
        for results in (None, {}, "bad", []):
            with self.subTest(results=results):
                data = self.valid_data()
                data["results"] = results
                with self.assertRaisesRegex(ValueError, "results.*non-empty list"):
                    plot_results.load(self.write_json(data))

    def test_rejects_non_object_point(self):
        data = self.valid_data()
        data["results"] = [None]
        with self.assertRaisesRegex(ValueError, r"results\[0\] must be an object"):
            plot_results.load(self.write_json(data))

    def test_rejects_missing_point_field(self):
        data = self.valid_data()
        data["results"] = [{"kernel": "vecadd", "n": 1}]
        with self.assertRaisesRegex(ValueError, r"results\[0\] missing"):
            plot_results.load(self.write_json(data))

    def test_rejects_empty_kernel_label(self):
        data = self.valid_data()
        data["results"][0]["kernel"] = ""
        with self.assertRaisesRegex(ValueError, r"results\[0\]\.kernel"):
            plot_results.load(self.write_json(data))

    def test_rejects_invalid_element_counts(self):
        for n in (True, False, 0, -1, 1.5, "1024", None):
            with self.subTest(n=n):
                data = self.valid_data()
                data["results"][0]["n"] = n
                with self.assertRaisesRegex(ValueError, r"results\[0\]\.n"):
                    plot_results.load(self.write_json(data))

    def test_rejects_invalid_bandwidth(self):
        values = (True, False, -0.1, "12.5", None, math.nan, math.inf, -math.inf, 10**1000)
        for bandwidth in values:
            with self.subTest(bandwidth=str(bandwidth)[:20]):
                data = self.valid_data()
                data["results"][0]["gb_per_s"] = bandwidth
                with self.assertRaisesRegex(ValueError, r"results\[0\]\.gb_per_s"):
                    plot_results.load(self.write_json(data))

    def test_reports_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as handle:
            handle.write("{")
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        with self.assertRaisesRegex(ValueError, "not a benchmark JSON file"):
            plot_results.load(handle.name)


class CliValidationTests(unittest.TestCase):
    def test_rejects_non_finite_or_non_positive_peak(self):
        for peak in ("0", "-1", "nan", "inf", "-inf"):
            with self.subTest(peak=peak):
                stderr = io.StringIO()
                argv = ["plot_results.py", "missing.json", f"--peak-gbps={peak}"]
                with mock.patch.object(sys, "argv", argv):
                    with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                        plot_results.main()
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("--peak-gbps must be finite and strictly positive", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_expected_file_errors_do_not_print_traceback(self):
        stderr = io.StringIO()
        argv = ["plot_results.py", "missing.json", "--peak-gbps", "1"]
        with mock.patch.object(sys, "argv", argv):
            with contextlib.redirect_stderr(stderr):
                result = plot_results.main()
        self.assertEqual(result, 1)
        self.assertIn("error:", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
