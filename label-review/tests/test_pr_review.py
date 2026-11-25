import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "label-review" / "engine"))
import pr_review


class PRReviewTests(unittest.TestCase):
    def test_digest_is_order_independent_for_mapping_keys(self):
        self.assertEqual(pr_review.digest({"a": 1, "b": 2}), pr_review.digest({"b": 2, "a": 1}))

    def test_proposal_comment_formats_identifiers_as_inline_code(self):
        data = {
            "repo": "owner/repo",
            "number": 12,
            "title": "title",
            "body": "body",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "diff": "diff",
            "files": [{"filename": ".github/workflows/pr-label-review.yml"}],
            "labels": ["bug"],
            "milestone": None,
            "known_labels": ["bug", "github_actions"],
            "milestones": [{"number": 4, "title": "Automation"}],
        }
        answer = {
            "labels": ["bug", "github_actions"],
            "milestone": 4,
            "confidence": "high",
            "rationale": "The workflow change supports this classification.",
            "evidence": [
                {"file": ".github/workflows/pr-label-review.yml", "quote": "actions/create-github-app-token@v2"}
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "proposal.json"
            comment = Path(directory) / "proposal.md"
            with (
                patch.object(pr_review, "snapshot", return_value=data),
                patch.object(pr_review, "ask_model", return_value=answer),
            ):
                pr_review.propose(12, str(artifact), str(comment))
            body = comment.read_text(encoding="utf-8")

        self.assertIn("Current labels: `bug`", body)
        self.assertIn("Proposed label additions: `github_actions`", body)
        self.assertIn("Proposed milestone: 4", body)
        self.assertIn("- `.github/workflows/pr-label-review.yml`:", body)
        self.assertIn("protected `pr-label-review` Environment", body)

    def test_inline_code_uses_a_longer_fence_when_needed(self):
        self.assertEqual(pr_review.inline_code("name"), "`name`")
        self.assertEqual(pr_review.inline_code("`name`"), "`` `name` ``")

    def test_missing_provider_key_fails_without_fallback(self):
        data = {"known_labels": [], "milestones": [], "title": "", "body": "", "files": [], "diff": ""}
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(pr_review.ReviewError, "no fallback provider"):
                pr_review.ask_model(data)

    def test_stale_diff_aborts_before_write(self):
        data = {
            "repo": "owner/repo",
            "number": 12,
            "title": "new",
            "body": "body",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "diff": "new diff",
            "files": [{"filename": "src/a.py", "status": "modified", "additions": 1, "deletions": 0}],
            "labels": ["bug"],
            "milestone": 2,
            "known_labels": ["bug", "enhancement"],
            "milestones": [{"number": 2, "title": "Current"}],
        }
        artifact = {
            "version": 1,
            "repo": "owner/repo",
            "number": 12,
            "identity": "stale",
            "metadata": pr_review.digest({"labels": ["bug"], "milestone": 2}),
            "current_labels": ["bug"],
            "current_milestone": 2,
            "add_labels": ["enhancement"],
            "milestone": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            with patch.object(pr_review, "snapshot", return_value=data), patch.object(pr_review, "gh") as write:
                with self.assertRaisesRegex(pr_review.ReviewError, "changed after proposal"):
                    pr_review.verify_and_apply(12, str(path))
                write.assert_not_called()

    def test_verify_accepts_original_proposal_without_applying(self):
        data = {
            "repo": "owner/repo",
            "number": 12,
            "title": "title",
            "body": "body",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "diff": "diff",
            "files": [{"filename": "src/a.py", "status": "modified", "additions": 1, "deletions": 0}],
            "labels": ["bug"],
            "milestone": 2,
            "known_labels": ["bug", "enhancement"],
            "milestones": [{"number": 2, "title": "Current"}],
        }
        identity = pr_review.digest(
            {
                "title": data["title"],
                "body": data["body"],
                "head_sha": data["head_sha"],
                "base_sha": data["base_sha"],
                "diff": data["diff"],
                "files": data["files"],
            }
        )
        artifact = {
            "version": 1,
            "repo": "owner/repo",
            "number": 12,
            "identity": identity,
            "metadata": pr_review.digest({"labels": ["bug"], "milestone": 2}),
            "current_labels": ["bug"],
            "current_milestone": 2,
            "add_labels": ["enhancement"],
            "milestone": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            with patch.object(pr_review, "snapshot", return_value=data), patch.object(pr_review, "gh") as write:
                pr_review.verify_proposal(12, str(path))
                write.assert_not_called()

    def test_approved_apply_preserves_existing_labels(self):
        data = {
            "repo": "owner/repo",
            "number": 12,
            "title": "title",
            "body": "body",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "diff": "diff",
            "files": [{"filename": "src/a.py", "status": "modified", "additions": 1, "deletions": 0}],
            "labels": ["bug"],
            "milestone": 2,
            "known_labels": ["bug", "enhancement"],
            "milestones": [{"number": 2, "title": "Current"}],
        }
        identity = pr_review.digest(
            {
                "title": data["title"],
                "body": data["body"],
                "head_sha": data["head_sha"],
                "base_sha": data["base_sha"],
                "diff": data["diff"],
                "files": data["files"],
            }
        )
        artifact = {
            "version": 1,
            "repo": "owner/repo",
            "number": 12,
            "identity": identity,
            "metadata": pr_review.digest({"labels": ["bug"], "milestone": 2}),
            "current_labels": ["bug"],
            "current_milestone": 2,
            "add_labels": ["enhancement"],
            "milestone": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            with patch.object(pr_review, "snapshot", return_value=data), patch.object(pr_review, "gh") as write:
                pr_review.verify_and_apply(12, str(path))
        payload = write.call_args.kwargs["payload"]
        self.assertEqual(payload, {"labels": ["bug", "enhancement"], "milestone": 2})

    def test_model_evidence_must_name_a_changed_file_and_quote_diff(self):
        data = {
            "known_labels": ["bug"],
            "milestones": [],
            "title": "t",
            "body": "b",
            "files": [{"filename": "src/a.py"}],
            "diff": "+return True",
        }
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "labels": ["bug"],
                                "milestone": None,
                                "confidence": "high",
                                "rationale": "Supported",
                                "evidence": [{"file": "src/a.py", "quote": "return False"}],
                            }
                        )
                    }
                }
            ]
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(response).encode()

        with (
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}),
            patch.object(pr_review.urllib.request, "urlopen", return_value=FakeResponse()),
        ):
            with self.assertRaisesRegex(pr_review.ReviewError, "not grounded"):
                pr_review.ask_model(data)

    def test_workflow_keeps_proposal_read_only_and_apply_approval_gated(self):
        workflow = (ROOT / ".github" / "workflows" / "pr-label-review.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", workflow)
        self.assertIn("ready_for_review", workflow)
        self.assertIn("pull-requests: read", workflow)
        self.assertIn("issues: read", workflow)
        self.assertIn("environment: pr-label-review", workflow)
        self.assertIn("PR_LABEL_REVIEW_APPLY == 'true'", workflow)
        self.assertIn("issues: write", workflow)
        self.assertIn("proposal_hash:", workflow)
        self.assertIn("sha256sum pr-proposal.json", workflow)
        self.assertIn("EXPECTED_PROPOSAL_HASH", workflow)
        self.assertIn("actions/upload-artifact@v7", workflow)
        self.assertIn("actions/download-artifact@v7", workflow)
        self.assertIn("pr_review.py verify --pr", workflow)
        self.assertIn("comment_id: ${{ steps.post.outputs.comment_id }}", workflow)
        self.assertIn("<!-- cuda-pr-label-review-proposal -->", workflow)
        self.assertIn("existing_id=", workflow)
        self.assertIn("gh api --method POST", workflow)
        self.assertIn("gh api --method PATCH", workflow)
        self.assertIn("needs.comment.outputs.comment_id", workflow)
        self.assertIn("Applied label additions:", workflow)
        self.assertIn("Applied milestone:", workflow)
        self.assertNotIn("Rebuild and verify proposal", workflow)
        self.assertIn("environment: pr-label-review", workflow)
        self.assertNotIn("pr-metadata-proposal", workflow)
        propose_job, remaining_jobs = workflow.split("  comment:", 1)
        comment_job, apply_job = remaining_jobs.split("  apply:", 1)
        self.assertNotIn("pull-requests: write", propose_job)
        self.assertIn("pull-requests: write", comment_job)
        self.assertNotIn("pull-requests: write", apply_job)
        self.assertNotIn("contents: write", workflow)

    def test_snapshot_rejects_malformed_diff(self):
        pull_request = {
            "state": "open",
            "draft": False,
            "head": {"sha": "a" * 40},
            "base": {"sha": "b" * 40},
            "labels": [],
            "milestone": None,
        }
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            with patch.object(pr_review, "gh", side_effect=[pull_request, [[]], "not a unified diff"]):
                with self.assertRaisesRegex(pr_review.ReviewError, "malformed"):
                    pr_review.snapshot(12)

    def test_snapshot_accepts_diff_above_previous_limit(self):
        pull_request = {
            "state": "open",
            "draft": False,
            "head": {"sha": "a" * 40},
            "base": {"sha": "b" * 40},
            "labels": [],
            "milestone": None,
        }
        accepted = "diff --git a/a b/a\\n" + ("x" * 45_500)
        pages = [[{"filename": "a", "status": "modified", "additions": 1, "deletions": 0}]]
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            with patch.object(pr_review, "gh", side_effect=[pull_request, pages, accepted, [[]], [[]]]):
                data = pr_review.snapshot(12)
        self.assertEqual(data["diff"], accepted)

    def test_snapshot_rejects_oversized_diff(self):
        pull_request = {
            "state": "open",
            "draft": False,
            "head": {"sha": "a" * 40},
            "base": {"sha": "b" * 40},
            "labels": [],
            "milestone": None,
        }
        oversized = "diff --git a/a b/a\n" + ("x" * (pr_review.MAX_DIFF + 1))
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            with patch.object(pr_review, "gh", side_effect=[pull_request, [[]], oversized]):
                with self.assertRaisesRegex(pr_review.ReviewError, "exceeds the review limit"):
                    pr_review.snapshot(12)

    def test_unknown_taxonomy_is_rejected_and_low_confidence_abstains(self):
        data = {
            "known_labels": ["bug"],
            "milestones": [{"number": 2, "title": "Current"}],
            "title": "t",
            "body": "b",
            "files": [{"filename": "src/a.py"}],
            "diff": "+return True",
        }

        def run_answer(answer):
            response = {"choices": [{"message": {"content": json.dumps(answer)}}]}

            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return json.dumps(response).encode()

            with (
                patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}),
                patch.object(pr_review.urllib.request, "urlopen", return_value=FakeResponse()),
            ):
                return pr_review.ask_model(data)

        base = {
            "labels": ["bug"],
            "milestone": 2,
            "confidence": "high",
            "rationale": "Supported",
            "evidence": [{"file": "src/a.py", "quote": "return True"}],
        }
        with self.assertRaisesRegex(pr_review.ReviewError, "outside the live repository taxonomy"):
            run_answer({**base, "labels": ["unknown"]})
        with self.assertRaisesRegex(pr_review.ReviewError, "outside the live open milestones"):
            run_answer({**base, "milestone": 99})
        abstained = run_answer({**base, "confidence": "low"})
        self.assertEqual(abstained["labels"], [])
        self.assertIsNone(abstained["milestone"])

    def test_stale_labels_and_milestone_abort_before_write(self):
        data = {
            "repo": "owner/repo",
            "number": 12,
            "title": "title",
            "body": "body",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "diff": "diff",
            "files": [
                {
                    "filename": "src/a.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                }
            ],
            "labels": ["bug"],
            "milestone": 2,
            "known_labels": ["bug", "enhancement"],
            "milestones": [
                {"number": 2, "title": "Current"},
                {"number": 3, "title": "Next"},
            ],
        }
        identity = pr_review.digest(
            {
                "title": data["title"],
                "body": data["body"],
                "head_sha": data["head_sha"],
                "base_sha": data["base_sha"],
                "diff": data["diff"],
                "files": data["files"],
            }
        )
        artifact = {
            "version": 1,
            "repo": "owner/repo",
            "number": 12,
            "identity": identity,
            "metadata": pr_review.digest({"labels": ["bug"], "milestone": 2}),
            "current_labels": ["bug"],
            "current_milestone": 2,
            "add_labels": ["enhancement"],
            "milestone": 3,
        }

        for changed_field, changed_value in (
            ("labels", ["bug", "documentation"]),
            ("milestone", 3),
        ):
            with self.subTest(changed_field=changed_field):
                changed_data = {**data, changed_field: changed_value}
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "proposal.json"
                    path.write_text(json.dumps(artifact), encoding="utf-8")
                    with (
                        patch.object(pr_review, "snapshot", return_value=changed_data),
                        patch.object(pr_review, "gh") as write,
                    ):
                        with self.assertRaisesRegex(pr_review.ReviewError, "changed after proposal"):
                            pr_review.verify_and_apply(12, str(path))
                        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
