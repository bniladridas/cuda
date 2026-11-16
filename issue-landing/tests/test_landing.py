"""Offline tests for the issue landing report and approval boundary."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import landing


class CriteriaTests(unittest.TestCase):
    def test_checked_and_unchecked_items_still_require_human_review(self):
        body = """## Summary
- Not a criterion.

## Acceptance criteria
- [x] Merge SHA is reported.
- [ ] Closing requires approval.
1. Stale reports fail closed.

## Non-goals
- Do not auto-merge.
"""
        criteria = landing.extract_acceptance_criteria(body)
        self.assertEqual(
            [item["text"] for item in criteria],
            [
                "Merge SHA is reported.",
                "Closing requires approval.",
                "Stale reports fail closed.",
            ],
        )
        self.assertTrue(all(item["status"] == "human review required" for item in criteria))
        self.assertTrue(all(item["evidence"] == [] for item in criteria))

    def test_criteria_in_comments_are_included_with_source(self):
        comments = [
            {
                "body": "## Acceptance criteria\n- The audit comment links the report.",
                "html_url": "https://github.com/acme/cuda/issues/7#issuecomment-9",
                "user": {"login": "reviewer"},
            }
        ]
        result = landing.extract_acceptance_criteria("## Summary", comments)
        self.assertEqual(result[0]["source"], "issue comment")
        self.assertEqual(result[0]["author"], "reviewer")
        self.assertEqual(result[0]["url"], comments[0]["html_url"])
        self.assertEqual(result[0]["status"], "human review required")

    def test_missing_criteria_section_requires_manual_review(self):
        result = landing.extract_acceptance_criteria("## Summary\n- Some work")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "human review required")


class CrossReferenceTests(unittest.TestCase):
    def test_issue_timeline_only_returns_explicit_pr_cross_references(self):
        timeline = [
            {"event": "cross-referenced", "source": {"issue": {"number": 8, "pull_request": {"url": "x"}}}},
            {"event": "mentioned", "source": {"issue": {"number": 9, "pull_request": {"url": "y"}}}},
            {"event": "cross-referenced", "source": {"issue": {"number": 8, "pull_request": {"url": "x"}}}},
        ]
        self.assertEqual(landing.linked_pull_request_numbers(timeline), [8])

    def test_merged_pr_only_selects_same_repo_issue_references(self):
        timeline = [
            {
                "event": "cross-referenced",
                "source": {
                    "issue": {
                        "number": 12,
                        "html_url": "https://github.com/acme/cuda/issues/12",
                        "repository": {"full_name": "acme/cuda"},
                    }
                },
            },
            {
                "event": "cross-referenced",
                "source": {
                    "issue": {
                        "number": 13,
                        "html_url": "https://github.com/other/repo/issues/13",
                        "repository": {"full_name": "other/repo"},
                    }
                },
            },
            {
                "event": "cross-referenced",
                "source": {
                    "issue": {
                        "number": 14,
                        "html_url": "https://github.com/acme/cuda/issues/14",
                        "pull_request": {"url": "pr"},
                        "repository": {"full_name": "acme/cuda"},
                    }
                },
            },
        ]
        self.assertEqual(landing.explicit_issue_numbers(timeline, "acme/cuda"), [12])

    def test_issue_references_are_deduplicated(self):
        issue = {"number": 5, "html_url": "url", "repository": {"full_name": "acme/cuda"}}
        timeline = [
            {"event": "cross-referenced", "source": {"issue": issue}},
            {"event": "cross-referenced", "source": {"issue": issue}},
        ]
        self.assertEqual(landing.explicit_issue_numbers(timeline, "acme/cuda"), [5])


class IssueCommentEvidenceTests(unittest.TestCase):
    def test_generated_report_comments_do_not_invalidate_approval(self):
        comments = [
            {
                "user": {"login": "github-actions[bot]"},
                "body": "## Issue landing report\\nReport digest: abc",
            },
            {
                "user": {"login": "reviewer"},
                "body": "The implementation was tested.",
            },
        ]
        self.assertEqual(landing.source_issue_comments(comments), [comments[1]])

    def test_only_relevant_comment_language_is_surfaced_as_unverified_evidence(self):
        comments = [
            {
                "body": "The fix was implemented in commit abc and tested on CPU.",
                "html_url": "https://github.com/acme/cuda/issues/7#issuecomment-1",
                "created_at": "2026-01-01T00:00:00Z",
                "user": {"login": "contributor"},
            },
            {
                "body": "Thanks!",
                "html_url": "https://github.com/acme/cuda/issues/7#issuecomment-2",
                "user": {"login": "reviewer"},
            },
        ]
        result = landing.relevant_comment_evidence(comments)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["author"], "contributor")
        self.assertEqual(result[0]["status"], "human review required")
        self.assertIn("tested on CPU", result[0]["excerpt"])

    def test_comment_digest_changes_when_comment_body_changes(self):
        comments = [{"id": 1, "updated_at": "2026-01-01T00:00:00Z", "body": "first"}]
        first = landing.issue_comment_digest(comments)
        comments[0]["body"] = "second"
        self.assertNotEqual(landing.issue_comment_digest(comments), first)


class ReportDigestTests(unittest.TestCase):
    def setUp(self):
        self.report = {
            "repo": "acme/cuda",
            "issue": {"number": 7, "digest": "issue-sha"},
            "default_branch": {"name": "main", "sha": "abc"},
            "pull_requests": [{"number": 4, "landed": False}],
            "acceptance_criteria": [],
        }

    def test_timestamp_and_digest_field_do_not_change_revision(self):
        self.report["generated_at"] = "2026-01-01T00:00:00+00:00"
        first = landing.report_digest(self.report)
        self.report["generated_at"] = "2026-01-02T00:00:00+00:00"
        self.report["report_digest"] = "ignored"
        self.assertEqual(landing.report_digest(self.report), first)

    def test_default_branch_or_pr_change_invalidates_revision(self):
        first = landing.report_digest(self.report)
        changed = dict(self.report, default_branch={"name": "main", "sha": "def"})
        self.assertNotEqual(landing.report_digest(changed), first)
        changed = dict(self.report, pull_requests=[{"number": 4, "landed": True}])
        self.assertNotEqual(landing.report_digest(changed), first)


class PullRequestEvidenceTests(unittest.TestCase):
    def test_merged_commit_reachable_from_default_branch_is_landed(self):
        pr = {
            "number": 4,
            "merged_at": "2026-01-01T00:00:00Z",
            "merge_commit_sha": "merge-sha",
            "head": {"sha": "head-sha"},
            "base": {"ref": "main", "sha": "base-sha"},
            "state": "closed",
            "html_url": "https://github.com/acme/cuda/pull/4",
        }
        with patch.object(landing, "gh_json", side_effect=[pr, {"status": "ahead"}]):
            result = landing.pull_request_snapshot("acme/cuda", 4, "main")
        self.assertTrue(result["landed"])
        self.assertEqual(result["default_branch_reachability"], "reachable")

    def test_merged_but_unreachable_commit_is_not_landed(self):
        pr = {
            "number": 4,
            "merged_at": "2026-01-01T00:00:00Z",
            "merge_commit_sha": "merge-sha",
            "head": {"sha": "head-sha"},
            "base": {"ref": "main", "sha": "base-sha"},
            "state": "closed",
        }
        with patch.object(landing, "gh_json", side_effect=[pr, {"status": "diverged"}]):
            result = landing.pull_request_snapshot("acme/cuda", 4, "main")
        self.assertFalse(result["landed"])

    def test_open_pr_is_not_landed(self):
        pr = {
            "number": 4,
            "merged_at": None,
            "merge_commit_sha": None,
            "head": {"sha": "head-sha"},
            "base": {"ref": "main", "sha": "base-sha"},
            "state": "open",
        }
        with patch.object(landing, "gh_json", return_value=pr):
            result = landing.pull_request_snapshot("acme/cuda", 4, "main")
        self.assertFalse(result["landed"])
        self.assertEqual(result["default_branch_reachability"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
