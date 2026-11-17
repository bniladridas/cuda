"""Tests for atomic benchmark result publication."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "runners" / "benchmark.sh"
PROBE = {"gpu": "Test GPU", "results": [{"kernel": "vecadd", "n": 16, "gb_per_s": 1.0}]}
FAKE_BINARY = """#!/usr/bin/env python3
import json
import os
import signal
import sys
import time

if "--iterations" in sys.argv:
    print(json.dumps({"gpu": "Test GPU"}))
    raise SystemExit(0)

mode = os.environ.get("BENCH_MODE", "success")
if mode == "fail":
    print("{")
    raise SystemExit(7)
if mode == "invalid":
    print("{")
    raise SystemExit(0)
if mode == "interrupt":
    os.kill(os.getppid(), signal.SIGTERM)
    time.sleep(2)
if os.environ.get("BENCH_SLEEP"):
    time.sleep(float(os.environ["BENCH_SLEEP"]))
print(json.dumps({"gpu": "Test GPU", "results": [{"kernel": "vecadd", "n": 16, "gb_per_s": 1.0}]}))
"""


class BenchmarkPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.build = root / "build"
        self.bin_dir = root / "bin"
        self.results = root / "results"
        self.build.mkdir()
        self.bin_dir.mkdir()
        binary = self.build / "cuda_benchmarks"
        binary.write_text(FAKE_BINARY, encoding="utf-8")
        binary.chmod(0o755)
        nvidia_smi = self.bin_dir / "nvidia-smi"
        nvidia_smi.write_text("#!/bin/sh\necho 'GPU 0: Test GPU'\n", encoding="utf-8")
        nvidia_smi.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(
            {
                "BUILD_DIR": str(self.build),
                "RESULTS_DIR": str(self.results),
                "PATH": str(self.bin_dir) + os.pathsep + self.env["PATH"],
            }
        )

    def run_script(self, **extra_env):
        env = self.env.copy()
        env.update(extra_env)
        return subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def final_results(self):
        return list(self.results.glob("*.json"))

    def temporary_results(self):
        return list(self.results.glob(".*.tmp.*"))

    def test_success_publishes_one_complete_json_file(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        files = self.final_results()
        self.assertEqual(len(files), 1)
        self.assertIn("Test-GPU", files[0].name)
        self.assertTrue(files[0].name.endswith(".json"))
        self.assertEqual(json.loads(files[0].read_text(encoding="utf-8"))["gpu"], "Test GPU")
        self.assertEqual(self.temporary_results(), [])

    def test_failed_benchmark_does_not_publish_result(self):
        result = self.run_script(BENCH_MODE="fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.final_results(), [])
        self.assertEqual(self.temporary_results(), [])

    def test_invalid_json_does_not_publish_result(self):
        result = self.run_script(BENCH_MODE="invalid")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid benchmark JSON", result.stderr)
        self.assertEqual(self.final_results(), [])
        self.assertEqual(self.temporary_results(), [])

    def test_interruption_cleans_up_temporary_file(self):
        result = self.run_script(BENCH_MODE="interrupt")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.final_results(), [])
        self.assertEqual(self.temporary_results(), [])

    def test_repeated_runs_do_not_overwrite_each_other(self):
        processes = [
            subprocess.Popen(
                ["bash", str(SCRIPT)],
                env={**self.env, "BENCH_SLEEP": "0.2"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(2)
        ]
        outcomes = [process.communicate(timeout=10) + (process.returncode,) for process in processes]
        self.assertEqual([outcome[2] for outcome in outcomes], [0, 0], outcomes)
        files = self.final_results()
        self.assertEqual(len(files), 2)
        self.assertEqual(len({path.name for path in files}), 2)
        for path in files:
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["gpu"], "Test GPU")
        self.assertEqual(self.temporary_results(), [])


if __name__ == "__main__":
    unittest.main()
