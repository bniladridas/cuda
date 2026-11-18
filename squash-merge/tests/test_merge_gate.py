import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from merge_gate import (  # noqa: E402
    latest_review_states,
    outstanding_change_request_reviewers,
    validate_state,
    perform_squash_merge,
    collect_state,
)


class MergeGateTests(unittest.TestCase):
    def setUp(self):
        self.pr = {
            "state": "open",
            "draft": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "user": {"login": "contributor"},
            "head": {
                "sha": "a" * 40,
                "repo": {"full_name": "bniladridas/cuda"},
            },
            "base": {
                "ref": "main",
                "repo": {"full_name": "bniladridas/cuda"},
            },
            "labels": [{"name": "squash-merge:approved"}],
        }
        self.reviews = [
            {
                "user": {"login": "reviewer"},
                "state": "APPROVED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T10:00:00Z",
            }
        ]
        self.checks = [{"name": "CI", "status": "completed", "conclusion": "success"}]
        self.status = {"state": "success", "statuses": [{"context": "CI", "state": "success"}]}
        self.policy = {
            "repo": "bniladridas/cuda",
            "target_branch": "main",
            "expected_head": "a" * 40,
            "actor": "bniladridas",
            "maintainers": {"bniladridas"},
            "approval_label": "squash-merge:approved",
            "required_check_runs": {"CI"},
            "required_status_contexts": {"CI"},
        }

    def errors(self, **overrides):
        values = {
            "pr": self.pr,
            "reviews": self.reviews,
            "check_runs": self.checks,
            "combined_status": self.status,
            **self.policy,
        }
        values.update(overrides)
        return validate_state(**values)

    def test_valid_maintainer_approval_passes(self):
        self.assertEqual(self.errors(), [])

    def test_unauthorized_actor_fails(self):
        errors = self.errors(actor="contributor")
        self.assertTrue(any("Unauthorized" in error for error in errors))

    def test_bot_actor_fails(self):
        errors = self.errors(actor="ci[bot]")
        self.assertTrue(any("Unauthorized" in error for error in errors))

    def test_author_cannot_supply_only_approval(self):
        reviews = [
            {
                "user": {"login": "contributor"},
                "state": "APPROVED",
                "submitted_at": "2026-11-17T10:00:00Z",
            }
        ]
        errors = self.errors(reviews=reviews)
        self.assertTrue(any("non-author" in error for error in errors))

    def test_outstanding_changes_requested_blocks(self):
        reviews = self.reviews + [
            {
                "user": {"login": "reviewer"},
                "state": "CHANGES_REQUESTED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T11:00:00Z",
            }
        ]
        errors = self.errors(reviews=reviews)
        self.assertTrue(any("change-request" in error for error in errors))

    def test_old_change_request_blocks_even_when_another_reviewer_approves_current_head(self):
        reviews = [
            {
                "id": 1,
                "user": {"login": "requesting-reviewer"},
                "state": "CHANGES_REQUESTED",
                "commit_id": "b" * 40,
                "submitted_at": "2026-11-17T10:00:00Z",
            },
            {
                "id": 2,
                "user": {"login": "approving-reviewer"},
                "state": "APPROVED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T11:00:00Z",
            },
        ]
        errors = self.errors(reviews=reviews)
        self.assertTrue(any("requesting-reviewer" in error for error in errors))

    def test_comment_does_not_clear_outstanding_change_request(self):
        reviews = [
            {
                "id": 1,
                "user": {"login": "reviewer"},
                "state": "CHANGES_REQUESTED",
                "commit_id": "b" * 40,
                "submitted_at": "2026-11-17T10:00:00Z",
            },
            {
                "id": 2,
                "user": {"login": "reviewer"},
                "state": "COMMENTED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T11:00:00Z",
            },
        ]
        self.assertEqual(outstanding_change_request_reviewers(reviews), {"reviewer"})

    def test_later_approval_clears_old_change_request(self):
        reviews = [
            {
                "id": 1,
                "user": {"login": "reviewer"},
                "state": "CHANGES_REQUESTED",
                "commit_id": "b" * 40,
                "submitted_at": "2026-11-17T10:00:00Z",
            },
            {
                "id": 2,
                "user": {"login": "reviewer"},
                "state": "APPROVED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T11:00:00Z",
            },
        ]
        self.assertEqual(outstanding_change_request_reviewers(reviews), set())

    def test_dismissal_clears_old_change_request(self):
        reviews = [
            {
                "id": 1,
                "user": {"login": "reviewer"},
                "state": "CHANGES_REQUESTED",
                "commit_id": "b" * 40,
                "submitted_at": "2026-11-17T10:00:00Z",
            },
            {
                "id": 2,
                "user": {"login": "reviewer"},
                "state": "DISMISSED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T11:00:00Z",
            },
        ]
        self.assertEqual(outstanding_change_request_reviewers(reviews), set())

    def test_dismissed_approval_does_not_count(self):
        reviews = [
            {
                "user": {"login": "reviewer"},
                "state": "APPROVED",
                "submitted_at": "2026-11-17T10:00:00Z",
            },
            {
                "user": {"login": "reviewer"},
                "state": "DISMISSED",
                "submitted_at": "2026-11-17T11:00:00Z",
            },
        ]
        errors = self.errors(reviews=reviews)
        self.assertTrue(any("non-author" in error for error in errors))

    def test_latest_approval_supersedes_older_request(self):
        reviews = [
            {
                "user": {"login": "reviewer"},
                "state": "CHANGES_REQUESTED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T10:00:00Z",
            },
            {
                "user": {"login": "reviewer"},
                "state": "APPROVED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T11:00:00Z",
            },
        ]
        self.assertEqual(latest_review_states(reviews, "a" * 40)["reviewer"], "APPROVED")

    def test_comment_after_approval_does_not_revoke_approval(self):
        reviews = [
            {
                "user": {"login": "reviewer"},
                "state": "APPROVED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T10:00:00Z",
            },
            {
                "user": {"login": "reviewer"},
                "state": "COMMENTED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T11:00:00Z",
            },
        ]
        self.assertEqual(latest_review_states(reviews, "a" * 40)["reviewer"], "APPROVED")
        self.assertEqual(self.errors(reviews=reviews), [])

    def test_comment_without_approval_does_not_count(self):
        reviews = [
            {
                "user": {"login": "reviewer"},
                "state": "COMMENTED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T11:00:00Z",
            }
        ]
        errors = self.errors(reviews=reviews)
        self.assertTrue(any("non-author" in error for error in errors))

    def test_later_change_request_supersedes_approval(self):
        reviews = [
            {
                "user": {"login": "reviewer"},
                "state": "APPROVED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T10:00:00Z",
            },
            {
                "user": {"login": "reviewer"},
                "state": "CHANGES_REQUESTED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T11:00:00Z",
            },
        ]
        errors = self.errors(reviews=reviews)
        self.assertTrue(any("change-request" in error for error in errors))
        self.assertTrue(any("non-author" in error for error in errors))

    def test_stale_approval_for_previous_head_does_not_count(self):
        reviews = [
            {
                "user": {"login": "reviewer"},
                "state": "APPROVED",
                "commit_id": "b" * 40,
                "submitted_at": "2026-11-17T10:00:00Z",
            }
        ]
        errors = self.errors(reviews=reviews)
        self.assertTrue(any("non-author" in error for error in errors))

    def test_approval_for_current_head_counts(self):
        reviews = [
            {
                "user": {"login": "reviewer"},
                "state": "APPROVED",
                "commit_id": "a" * 40,
                "submitted_at": "2026-11-17T10:00:00Z",
            }
        ]
        self.assertEqual(self.errors(reviews=reviews), [])

    def test_fork_pr_fails(self):
        head = {"sha": "a" * 40, "repo": {"full_name": "someone/fork"}}
        errors = self.errors(pr={**self.pr, "head": head})
        self.assertTrue(any("Fork" in error for error in errors))

    def test_stale_head_fails(self):
        errors = self.errors(expected_head="b" * 40)
        self.assertTrue(any("head changed" in error for error in errors))

    def test_draft_and_conflict_fail(self):
        draft_errors = self.errors(pr={**self.pr, "draft": True})
        conflict_errors = self.errors(pr={**self.pr, "mergeable_state": "dirty"})
        self.assertTrue(any("Draft" in error for error in draft_errors))
        self.assertTrue(any("mergeable state" in error for error in conflict_errors))

    def test_running_or_failed_checks_fail(self):
        running = [{"name": "CI", "status": "in_progress", "conclusion": None}]
        failed = [{"name": "CI", "status": "completed", "conclusion": "failure"}]
        running_errors = self.errors(check_runs=running)
        failed_errors = self.errors(check_runs=failed)
        self.assertTrue(any("Required checks are not successful" in error for error in running_errors))
        self.assertTrue(any("Required checks are not successful" in error for error in failed_errors))

    def test_optional_skipped_check_is_allowed(self):
        errors = self.errors(
            check_runs=self.checks
            + [
                {
                    "name": "gpu",
                    "status": "completed",
                    "conclusion": "skipped",
                }
            ]
        )
        self.assertEqual(errors, [])

    def test_optional_neutral_check_is_allowed(self):
        errors = self.errors(
            check_runs=self.checks
            + [
                {
                    "name": "docs-preview",
                    "status": "completed",
                    "conclusion": "neutral",
                }
            ]
        )
        self.assertEqual(errors, [])

    def test_missing_approval_label_fails(self):
        errors = self.errors(pr={**self.pr, "labels": []})
        self.assertTrue(any("label" in error for error in errors))

    def test_skipped_neutral_and_pending_required_checks_fail(self):
        for status, conclusion in [
            ("completed", "skipped"),
            ("completed", "neutral"),
            ("in_progress", None),
        ]:
            with self.subTest(status=status, conclusion=conclusion):
                errors = self.errors(
                    check_runs=[
                        {
                            "name": "CI",
                            "status": status,
                            "conclusion": conclusion,
                        }
                    ]
                )
                self.assertTrue(any("Required checks are not successful" in error for error in errors))

    def test_missing_required_check_fails(self):
        errors = self.errors(check_runs=[])
        self.assertTrue(any("Required check runs are missing" in error for error in errors))

    def test_missing_required_status_context_fails(self):
        errors = self.errors(combined_status={"state": "success", "statuses": []})
        self.assertTrue(any("Required commit status contexts are missing" in error for error in errors))

    def test_unconfigured_combined_status_does_not_block_actions_only_head(self):
        errors = self.errors(
            combined_status={"state": "failure", "statuses": []},
            required_status_contexts=set(),
        )
        self.assertEqual(errors, [])

    def test_actions_only_head_with_no_legacy_statuses_passes(self):
        errors = self.errors(
            combined_status={"state": "pending", "statuses": []},
            required_status_contexts=set(),
        )
        self.assertEqual(errors, [])

    def test_duplicate_label_event_after_merge_is_rejected(self):
        errors = self.errors(pr={**self.pr, "state": "closed", "merged": True})
        self.assertTrue(any("not open" in error for error in errors))

    def test_merge_api_failure_is_actionable_and_does_not_report_success(self):
        from unittest.mock import Mock
        import subprocess

        api = Mock(side_effect=subprocess.CalledProcessError(405, ["gh", "api"], stderr="Merge method not allowed"))
        result, error = perform_squash_merge("bniladridas/cuda", 76, "a" * 40, api=api)
        self.assertIsNone(result)
        self.assertIn("GitHub rejected the squash merge request", error)
        self.assertIn("Merge method not allowed", error)
        api.assert_called_once()


class CollectStatePaginationTests(unittest.TestCase):
    def test_collect_state_flattens_every_page(self):
        head = "a" * 40
        pr = {"number": 76}
        review_pages = [
            [{"id": 1, "state": "APPROVED"}],
            [{"id": 2, "state": "COMMENTED"}],
        ]
        check_pages = [
            {"check_runs": [{"name": "cpu"}]},
            {"check_runs": [{"name": "python"}, {"name": "squash-merge approval gate"}]},
        ]
        status_pages = [
            {"state": "success", "statuses": [{"context": "legacy-a", "state": "success"}]},
            {"state": "success", "statuses": [{"context": "legacy-b", "state": "success"}]},
        ]
        from unittest.mock import patch

        with patch(
            "merge_gate.gh_json",
            side_effect=[pr, review_pages, check_pages, status_pages],
        ) as api:
            result_pr, reviews, checks, status = collect_state("bniladridas/cuda", 76, head)

        self.assertEqual(result_pr, pr)
        self.assertEqual([review["id"] for review in reviews], [1, 2])
        self.assertEqual([run["name"] for run in checks], ["cpu", "python"])
        self.assertEqual(
            [item["context"] for item in status["statuses"]],
            ["legacy-a", "legacy-b"],
        )
        self.assertEqual(api.call_count, 4)


if __name__ == "__main__":
    unittest.main()
