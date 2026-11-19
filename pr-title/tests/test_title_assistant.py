import unittest

from pr_title.engine.title_assistant import valid_title


class TitleValidationTests(unittest.TestCase):
    def setUp(self):
        self.scopes = {"kernels", "pr-title", "docs"}

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
