import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.github_snapshot import (
    SnapshotError,
    criteria_from_body,
    issue_dependencies,
    load_benchmark_results,
    run_gh,
)


class SnapshotAdapterTests(unittest.TestCase):
    def test_acceptance_criteria_extraction(self):
        body = """## Overview
text
## Acceptance Criteria
- [ ] CPU tests
- GPU evidence
## Notes
- not included"""
        self.assertEqual(criteria_from_body(body), ["CPU tests", "GPU evidence"])

    def test_dependency_extraction_is_sorted_and_excludes_self(self):
        self.assertEqual(issue_dependencies("Depends on #8 and #3, also #8", 3), [8])

    def test_benchmark_results_are_loaded_from_results_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "benchmarks" / "results"
            results.mkdir(parents=True)
            record = {"git_commit": "a" * 40, "gpu": "test"}
            (results / "run.json").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(load_benchmark_results(root), [record])

    def test_invalid_benchmark_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "benchmarks" / "results"
            results.mkdir(parents=True)
            (results / "broken.json").write_text("{", encoding="utf-8")
            with self.assertRaises(SnapshotError):
                load_benchmark_results(root)

    def test_gh_errors_fail_closed(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="denied")

        with self.assertRaises(SnapshotError):
            run_gh("repos/example/repo", runner=runner)

    def test_invalid_json_fails_closed(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout="not-json", stderr="")

        with self.assertRaises(SnapshotError):
            run_gh("repos/example/repo", runner=runner)


if __name__ == "__main__":
    unittest.main()
