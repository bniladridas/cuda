import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.contracts import Evidence, State
from engine.health import analyze_health
from engine.readiness import evaluate_readiness
from engine.steward import build_report
from engine.tracking import analyze_tracking


class StewardTests(unittest.TestCase):
    def test_issue_tracking_finds_unlinked_and_missing_acceptance(self):
        result = analyze_tracking(
            {
                "issues": [
                    {
                        "number": 4,
                        "title": "Add kernel",
                        "body": "",
                        "state": "open",
                    }
                ],
                "pull_requests": [],
            }
        )
        codes = {item["code"] for item in result["findings"]}
        self.assertEqual(codes, {"issue.unlinked", "issue.acceptance_missing"})

    def test_linked_pr_and_dependency_are_reported(self):
        result = analyze_tracking(
            {
                "issues": [
                    {"number": 4, "title": "Parent", "body": "Depends on #5", "state": "open"},
                    {"number": 5, "title": "Child", "body": "Done", "state": "closed"},
                ],
                "pull_requests": [{"number": 12, "title": "Fixes #4", "state": "open", "head_sha": "abc"}],
            }
        )
        self.assertEqual(result["issues"][0]["dependencies"], [5])
        self.assertEqual(result["issues"][0]["linked_prs"][0]["number"], 12)

    def test_readiness_requires_current_head_evidence(self):
        evidence = [
            Evidence("host_tests", State.SUCCESS, "ci", "old", "new"),
            Evidence("cuda_compile", State.SUCCESS, "ci", "new", "new"),
            Evidence("gpu_runtime", State.SKIPPED, "ci", "new", "new"),
        ]
        result = evaluate_readiness(evidence)
        self.assertFalse(result["ready"])
        self.assertEqual(result["required_evidence"]["host_tests"]["state"], "unknown")
        self.assertEqual(result["required_evidence"]["gpu_runtime"]["state"], "skipped")
        self.assertFalse(result["publication_performed"])

    def test_health_reports_broken_relative_links_and_invalid_json(self):
        result = analyze_health(
            {
                "README.md": "[missing](docs/nope.md)",
                ".github/config.json": "{broken",
                "docs/existing.md": "ok",
            }
        )
        codes = {item["code"] for item in result["findings"]}
        self.assertEqual(codes, {"docs.link_missing", "config.json_invalid"})
        self.assertFalse(result["mutations_performed"])

    def test_build_report_is_read_only_and_keeps_model_disabled(self):
        result = build_report(
            {
                "repository": "bniladridas/cuda",
                "head_sha": "abc",
                "issues": [],
                "pull_requests": [],
                "validations": [
                    {
                        "kind": "gpu_runtime",
                        "state": "skipped",
                        "head_sha": "abc",
                        "source": "ci",
                    }
                ],
                "files": {"README.md": "ok"},
            }
        )
        self.assertFalse(result["modules"]["release_readiness"]["ready"])
        self.assertFalse(result["modules"]["model_integration"]["enabled"])
        self.assertEqual(result["modules"]["validation"]["evidence"][0]["state"], "skipped")


if __name__ == "__main__":
    unittest.main()
