import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.model_summary import ModelSummaryError, configured_provider, summarize_report


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ModelSummaryTests(unittest.TestCase):
    def test_missing_configuration_disables_model(self):
        self.assertIsNone(configured_provider({}))
        result = summarize_report({}, environ={})
        self.assertFalse(result["enabled"])

    def test_http_endpoint_must_be_https(self):
        with self.assertRaises(ModelSummaryError):
            configured_provider(
                {
                    "STEWARD_MODEL_ENDPOINT": "http://localhost",
                    "STEWARD_MODEL_NAME": "model",
                    "STEWARD_MODEL_API_KEY": "secret",
                }
            )

    def test_summary_is_advisory_and_has_no_authority(self):
        env = {
            "STEWARD_MODEL_ENDPOINT": "https://example.invalid/v1/chat/completions",
            "STEWARD_MODEL_NAME": "configured-model",
            "STEWARD_MODEL_API_KEY": "secret",
        }

        def opener(request, timeout):
            body = json.loads(request.data)
            self.assertEqual(body["model"], "configured-model")
            return FakeResponse(
                {"id": "req_test_123", "choices": [{"message": {"content": "Evidence is incomplete."}}]}
            )

        result = summarize_report({"gpu": "skipped"}, environ=env, opener=opener)
        self.assertEqual(result["status"], "advisory")
        self.assertIsNone(result["authorization_source"])
        self.assertEqual(result["summary"], "Evidence is incomplete.")
        evidence = result["evidence"]
        self.assertEqual(evidence["kind"], "model_recommendation")
        self.assertEqual(evidence["model"], "configured-model")
        self.assertEqual(evidence["endpoint_host"], "example.invalid")
        self.assertEqual(evidence["request_id"], "req_test_123")
        self.assertEqual(len(evidence["input_report_sha256"]), 64)
        self.assertEqual(len(evidence["output_sha256"]), 64)
        self.assertTrue(evidence["advisory_only"])
        self.assertIsNone(evidence["authorization_source"])


if __name__ == "__main__":
    unittest.main()
