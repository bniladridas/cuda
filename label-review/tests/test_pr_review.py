import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from label_review import pr_review


class PRReviewTests(unittest.TestCase):
    def test_digest_is_order_independent_for_mapping_keys(self):
        self.assertEqual(pr_review.digest({"a": 1, "b": 2}), pr_review.digest({"b": 2, "a": 1}))

    def test_missing_provider_key_fails_without_fallback(self):
        data = {"known_labels": [], "milestones": [], "title": "", "body": "", "files": [], "diff": ""}
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(pr_review.ReviewError, "no fallback provider"):
                pr_review.ask_model(data)

    def test_stale_diff_aborts_before_write(self):
        data = {
            "repo": "owner/repo", "number": 12, "title": "new", "body": "body",
            "head_sha": "a" * 40, "base_sha": "b" * 40, "diff": "new diff",
            "files": [{"filename": "src/a.py", "status": "modified", "additions": 1, "deletions": 0}],
            "labels": ["bug"], "milestone": 2, "known_labels": ["bug", "enhancement"],
            "milestones": [{"number": 2, "title": "Current"}],
        }
        artifact = {
            "version": 1, "repo": "owner/repo", "number": 12,
            "identity": "stale", "metadata": pr_review.digest({"labels": ["bug"], "milestone": 2}),
            "current_labels": ["bug"], "current_milestone": 2,
            "add_labels": ["enhancement"], "milestone": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            with patch.object(pr_review, "snapshot", return_value=data), patch.object(pr_review, "gh") as write:
                with self.assertRaisesRegex(pr_review.ReviewError, "changed after proposal"):
                    pr_review.verify_and_apply(12, str(path))
                write.assert_not_called()

    def test_approved_apply_preserves_existing_labels(self):
        data = {
            "repo": "owner/repo", "number": 12, "title": "title", "body": "body",
            "head_sha": "a" * 40, "base_sha": "b" * 40, "diff": "diff",
            "files": [{"filename": "src/a.py", "status": "modified", "additions": 1, "deletions": 0}],
            "labels": ["bug"], "milestone": 2, "known_labels": ["bug", "enhancement"],
            "milestones": [{"number": 2, "title": "Current"}],
        }
        identity = pr_review.digest({"title": data["title"], "body": data["body"],
            "head_sha": data["head_sha"], "base_sha": data["base_sha"],
            "diff": data["diff"], "files": data["files"]})
        artifact = {
            "version": 1, "repo": "owner/repo", "number": 12, "identity": identity,
            "metadata": pr_review.digest({"labels": ["bug"], "milestone": 2}),
            "current_labels": ["bug"], "current_milestone": 2,
            "add_labels": ["enhancement"], "milestone": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            with patch.object(pr_review, "snapshot", return_value=data), patch.object(pr_review, "gh") as write:
                pr_review.verify_and_apply(12, str(path))
        payload = write.call_args.kwargs["payload"]
        self.assertEqual(payload, {"labels": ["bug", "enhancement"], "milestone": 2})

    def test_model_evidence_must_name_a_changed_file_and_quote_diff(self):
        data = {"known_labels": ["bug"], "milestones": [], "title": "t", "body": "b",
                "files": [{"filename": "src/a.py"}], "diff": "+return True"}
        response = {"choices": [{"message": {"content": json.dumps({
            "labels": ["bug"], "milestone": None, "confidence": "high",
            "rationale": "Supported", "evidence": [{"file": "src/a.py", "quote": "return False"}]
        })}}]}
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(response).encode()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}), patch.object(pr_review.urllib.request, "urlopen", return_value=FakeResponse()):
            with self.assertRaisesRegex(pr_review.ReviewError, "not grounded"):
                pr_review.ask_model(data)


if __name__ == "__main__":
    unittest.main()
