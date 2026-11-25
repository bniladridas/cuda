import sys
from urllib.error import HTTPError
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import title_assistant  # noqa: E402
from title_assistant import valid_title  # noqa: E402


class TitleValidationTests(unittest.TestCase):
    def setUp(self):
        self.scopes = {"kernels", "pr-title", "docs"}

    def test_rate_limit_and_server_errors_are_non_blocking(self):
        for code in (429, 500, 502, 503):
            with self.subTest(code=code):
                error = HTTPError("https://example.test", code, "error", {}, None)
                self.assertTrue(title_assistant.provider_unavailable(error))

    def test_other_provider_http_errors_remain_failures(self):
        for code in (400, 401, 403):
            with self.subTest(code=code):
                error = HTTPError("https://example.test", code, "error", {}, None)
                self.assertFalse(title_assistant.provider_unavailable(error))

    def test_accepts_registered_scope_and_action_verb(self):
        self.assertTrue(valid_title("[kernels] Add vectorized reduction", self.scopes))

    def test_rejects_unknown_scope(self):
        self.assertFalse(valid_title("[made-up] Add vectorized reduction", self.scopes))

    def test_rejects_non_action_description(self):
        self.assertFalse(valid_title("[docs] Vectorized reduction notes", self.scopes))

    def test_rejects_overlong_title(self):
        self.assertFalse(valid_title("[docs] Add " + "x" * 100, self.scopes))


if __name__ == "__main__":
    unittest.main()
