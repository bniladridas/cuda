import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.integrations import integration_status


class IntegrationAdapterTests(unittest.TestCase):
    def test_missing_evidence_is_unavailable(self):
        result = integration_status({"head_sha": "abc"})
        self.assertEqual(result["integrations"]["label_review"]["state"], "unavailable")
        self.assertEqual(result["integrations"]["issue_landing"]["state"], "unavailable")
        self.assertFalse(result["mutations_performed"])

    def test_current_workflow_evidence_does_not_imply_approval(self):
        result = integration_status(
            {
                "head_sha": "abc",
                "integration_evidence": {
                    "label_review": {
                        "state": "success",
                        "head_sha": "abc",
                        "source": "workflow run 12",
                        "url": "https://example.invalid/run/12",
                    },
                    "issue_landing": {
                        "state": "pending",
                        "head_sha": "abc",
                        "source": "workflow run 13",
                    },
                },
            }
        )
        label = result["integrations"]["label_review"]
        landing = result["integrations"]["issue_landing"]
        self.assertEqual(label["state"], "success")
        self.assertEqual(label["approval_status"], "not_asserted")
        self.assertIsNone(label["revision_match"])
        self.assertEqual(label["approval_environment"], "label-review")
        self.assertEqual(landing["state"], "pending")
        self.assertEqual(landing["approval_environment"], "issue-landing-close")
        self.assertFalse(label["coordinator_write_performed"])
        self.assertFalse(result["mutations_performed"])

    def test_stale_evidence_is_unknown_not_success(self):
        result = integration_status(
            {
                "head_sha": "new",
                "integration_evidence": {
                    "label_review": {
                        "state": "success",
                        "head_sha": "old",
                        "expected_sha": "new",
                    },
                },
            }
        )
        item = result["integrations"]["label_review"]
        self.assertEqual(item["state"], "unknown")
        self.assertFalse(item["revision_match"])

    def test_unknown_states_remain_unknown(self):
        result = integration_status(
            {
                "head_sha": "abc",
                "integration_evidence": {
                    "issue_landing": {"state": "something-new", "head_sha": "abc"},
                },
            }
        )
        self.assertEqual(result["integrations"]["issue_landing"]["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
