import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).parents[1] / "engine" / "create_pr.py"
SPEC = importlib.util.spec_from_file_location("create_pr", MODULE_PATH)
create_pr = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(create_pr)


class CreatePrTests(unittest.TestCase):
    def test_title_requires_registered_scope_and_action_verb(self):
        scopes = {"automation", "docs"}
        self.assertTrue(create_pr.valid_title("[automation] Create pull requests as the bot", scopes))
        self.assertFalse(create_pr.valid_title("[unknown] Create pull requests", scopes))
        self.assertFalse(create_pr.valid_title("[docs] Better PR descriptions", scopes))

    def test_title_rejects_overlong_value(self):
        title = "[docs] Clarify " + "x" * 100
        self.assertFalse(create_pr.valid_title(title, {"docs"}))

    def test_linked_references_are_deduplicated_and_sorted(self):
        messages = ["Fixes #19", "Refs #7 and fixes #19", "Closes #12"]
        self.assertEqual(
            create_pr.linked_references(messages),
            ["#7", "#12", "#19"],
        )

    def test_body_uses_repository_template_sections(self):
        body = create_pr.render_body(
            {
                "summary": "Create a bot-authored PR from an existing branch.",
                "changes": ["Generate a scoped title from the diff."],
                "not_verified": ["The workflow has not yet run in Actions."],
            },
            ["#42"],
        )
        for heading in ("Summary", "Changes", "Verification", "Not verified", "References"):
            self.assertIn(f"## {heading}", body)
        self.assertIn("#42", body)
        self.assertIn("does not claim local test execution", body)

    def test_body_rejects_empty_change_list(self):
        with self.assertRaises(ValueError):
            create_pr.render_body(
                {"summary": "A summary", "changes": [], "not_verified": []},
                [],
            )


if __name__ == "__main__":
    unittest.main()
