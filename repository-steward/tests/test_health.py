import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.health import analyze_health, check_github_workflows, check_markdown_links


class RepositoryHealthTests(unittest.TestCase):
    def test_markdown_links_support_titles_angles_and_directory_indexes(self):
        result = check_markdown_links(
            {
                "README.md": ('[guide](docs/guide.md "Guide") [reference](<docs/reference page.md>) [section](docs)'),
                "docs/guide.md": "Guide",
                "docs/reference page.md": "Reference",
                "docs/README.md": "Index",
            }
        )
        self.assertEqual(result, [])

    def test_markdown_missing_link_is_reported(self):
        result = check_markdown_links({"README.md": "[missing](docs/missing.md)"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "docs.link_missing")
        self.assertEqual(result[0]["line"], 1)

    def test_json_duplicate_keys_are_rejected(self):
        result = analyze_health({".github/settings.json": '{"enabled": true, "enabled": false}'})
        self.assertEqual(result["findings"][0]["code"], "config.json_invalid")
        self.assertIn("duplicate JSON key", result["findings"][0]["summary"])

    def test_workflow_yaml_syntax_and_duplicate_keys_are_checked(self):
        result = check_github_workflows(
            {
                ".github/workflows/broken.yml": "name: test\njobs: [",
                ".github/workflows/duplicate.yaml": "name: test\nname: other\n",
            }
        )
        self.assertEqual(len(result), 2)
        self.assertTrue(all(item["code"] == "config.yaml_invalid" for item in result))

    def test_missing_local_action_reference_is_reported(self):
        result = check_github_workflows(
            {
                ".github/workflows/ci.yml": ("name: test\njobs:\n  test:\n    steps:\n      - uses: ./actions/not-present\n")
            }
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "workflow.local_action_missing")

    def test_existing_local_action_metadata_is_accepted(self):
        result = check_github_workflows(
            {
                ".github/workflows/ci.yml": ("name: test\njobs:\n  test:\n    steps:\n      - uses: ./actions/example\n"),
                "actions/example/action.yml": "name: Example\nruns:\n  using: composite\n",
            }
        )
        self.assertEqual(result, [])

    def test_health_is_read_only_and_combines_findings(self):
        result = analyze_health(
            {
                "README.md": "[missing](docs/nope.md)",
                ".github/config.json": "{broken",
                ".github/workflows/ci.yml": "name: test\njobs: [",
            }
        )
        codes = {item["code"] for item in result["findings"]}
        self.assertEqual(
            codes,
            {"docs.link_missing", "config.json_invalid", "config.yaml_invalid"},
        )
        self.assertFalse(result["mutations_performed"])
        self.assertEqual(result["finding_count"], 3)


if __name__ == "__main__":
    unittest.main()
