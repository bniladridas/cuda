import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.github_snapshot import (
    SnapshotError,
    criteria_from_body,
    issue_dependencies,
    run_gh,
)


class SnapshotAdapterTests(unittest.TestCase):
    def test_acceptance_criteria_extraction(self):
        body = "## Overview\ntext\n## Acceptance Criteria\n- [ ] CPU tests\n- GPU evidence\n## Notes\n- not included"
        self.assertEqual(criteria_from_body(body), ["CPU tests", "GPU evidence"])

    def test_issue_reference_extraction(self):
        from engine.github_snapshot import ISSUE_REF

        self.assertEqual(ISSUE_REF.findall("Fixes #12 and #3, not path/#4"), ["12", "3"])

    def test_dependency_extraction_is_sorted_and_excludes_self(self):
        self.assertEqual(issue_dependencies("Depends on #8 and #3, also #8", 3), [8])

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
