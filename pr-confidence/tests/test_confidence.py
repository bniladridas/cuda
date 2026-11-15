#!/usr/bin/env python3
"""Offline tests for the PR Confidence engine.

Every test builds evidence dictionaries by hand. The collector tests replace the
subprocess call, so no network access or GitHub token is needed.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parents[1]
ENGINE_DIR = TESTS_DIR.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

import confidence as c  # noqa: E402


def config_data():
    return {
        "version": 1,
        "critical_checks": ["cpu", "CodeQL"],
        "security_checks": ["Socket Security: Pull Request Alerts"],
        "hard_blockers": {
            "failed_critical_checks": True,
            "changes_requested": True,
            "merge_conflict": True,
            "draft": False,
            "unresolved_threads": False,
            "security_check_failure": False,
        },
        "scope": {
            "max_files": 30,
            "max_changed_lines": 1500,
            "min_body_chars": 40,
        },
        "test_patterns": [
            "tests/**",
            "**/test_*.py",
            "**/*_test.py",
        ],
        "security_sensitive_paths": [
            ".github/workflows/**",
            "src/**",
        ],
    }


def make_config(**blockers):
    data = config_data()
    data["hard_blockers"].update(blockers)
    return c.validate_config(data)


def make_run(name, conclusion="success", status="completed", started="2026-01-01T00:00:00Z"):
    return {
        "name": name,
        "app": "github-actions",
        "status": status,
        "conclusion": conclusion,
        "details_url": "https://example.invalid/run",
        "started_at": started,
        "completed_at": started,
    }


def make_raw_run(name, conclusion="success", status="completed", started="2026-01-01T00:00:00Z"):
    return {
        "name": name,
        "app": {"slug": "github-actions"},
        "status": status,
        "conclusion": conclusion,
        "details_url": "https://example.invalid/run",
        "started_at": started,
        "completed_at": started,
    }


def default_checks():
    return [
        make_run("cpu"),
        make_run("CodeQL"),
        make_run("Socket Security: Pull Request Alerts"),
        make_run("GitGuardian Security Checks"),
    ]


def raw_default_checks():
    return [
        make_raw_run("cpu"),
        make_raw_run("CodeQL"),
        make_raw_run("Socket Security: Pull Request Alerts"),
        make_raw_run("GitGuardian Security Checks"),
    ]


def make_evidence():
    return {
        "rubric_version": c.RUBRIC_VERSION,
        "collected_at": "2026-01-01T00:00:00+00:00",
        "repo": "owner/repo",
        "head_sha": "abc123",
        "pr": {
            "number": 7,
            "title": "Add the thing",
            "body_length": 60,
            "draft": False,
            "state": "open",
            "mergeable": True,
            "mergeable_state": "clean",
            "changed_files": 2,
            "additions": 20,
            "deletions": 3,
            "commits": 1,
            "user": "octocat",
            "api_head_sha": "abc123",
            "head_mismatch": False,
        },
        "files": {
            "available": True,
            "truncated": False,
            "error": None,
            "items": [
                {
                    "filename": "tests/test_thing.py",
                    "status": "added",
                    "additions": 10,
                    "deletions": 0,
                    "changes": 10,
                },
                {
                    "filename": "src/thing.cu",
                    "status": "modified",
                    "additions": 10,
                    "deletions": 3,
                    "changes": 13,
                },
            ],
        },
        "checks": {
            "available": True,
            "truncated": False,
            "error": None,
            "items": default_checks(),
        },
        "review": {
            "available": True,
            "decision": "APPROVED",
            "unresolved": [],
            "threads_truncated": False,
            "error": None,
        },
    }


def statuses(result):
    return {item["key"]: item["status"] for item in result["categories"]}


def category(result, key):
    for item in result["categories"]:
        if item["key"] == key:
            return item
    raise AssertionError("missing category %s" % key)


class ConfigTests(unittest.TestCase):
    def test_accepts_valid_configuration(self):
        config = c.validate_config(config_data())
        self.assertEqual(config["version"], 1)
        self.assertEqual(config["critical_checks"], ["cpu", "CodeQL"])

    def test_defaults_missing_hard_blockers(self):
        data = config_data()
        del data["hard_blockers"]
        config = c.validate_config(data)
        self.assertEqual(config["hard_blockers"], c.DEFAULT_HARD_BLOCKERS)

    def test_rejects_unknown_top_level_key(self):
        data = config_data()
        data["extra"] = True
        with self.assertRaisesRegex(c.ConfidenceError, "unknown configuration keys"):
            c.validate_config(data)

    def test_rejects_wrong_version(self):
        data = config_data()
        data["version"] = 2
        with self.assertRaisesRegex(c.ConfidenceError, "version must be 1"):
            c.validate_config(data)

    def test_rejects_empty_critical_checks(self):
        data = config_data()
        data["critical_checks"] = []
        with self.assertRaisesRegex(c.ConfidenceError, "at least 1"):
            c.validate_config(data)

    def test_rejects_duplicate_checks(self):
        data = config_data()
        data["critical_checks"] = ["cpu", "cpu"]
        with self.assertRaisesRegex(c.ConfidenceError, "duplicate"):
            c.validate_config(data)

    def test_rejects_overlapping_checks(self):
        data = config_data()
        data["security_checks"] = ["cpu"]
        with self.assertRaisesRegex(c.ConfidenceError, "both critical and a security"):
            c.validate_config(data)

    def test_rejects_unknown_hard_blocker(self):
        data = config_data()
        data["hard_blockers"]["everything"] = True
        with self.assertRaisesRegex(c.ConfidenceError, "unknown hard_blockers"):
            c.validate_config(data)

    def test_rejects_non_boolean_hard_blocker(self):
        data = config_data()
        data["hard_blockers"]["draft"] = "yes"
        with self.assertRaisesRegex(c.ConfidenceError, "must be true or false"):
            c.validate_config(data)

    def test_rejects_unknown_scope_key(self):
        data = config_data()
        data["scope"]["max_bytes"] = 10
        with self.assertRaisesRegex(c.ConfidenceError, "unknown scope keys"):
            c.validate_config(data)

    def test_rejects_missing_scope_key(self):
        data = config_data()
        del data["scope"]["max_files"]
        with self.assertRaisesRegex(c.ConfidenceError, "non-negative integer"):
            c.validate_config(data)

    def test_rejects_zero_file_limit(self):
        data = config_data()
        data["scope"]["max_files"] = 0
        with self.assertRaisesRegex(c.ConfidenceError, "at least 1"):
            c.validate_config(data)

    def test_rejects_negative_line_limit(self):
        data = config_data()
        data["scope"]["max_changed_lines"] = -1
        with self.assertRaisesRegex(c.ConfidenceError, "non-negative integer"):
            c.validate_config(data)

    def test_rejects_absolute_path_pattern(self):
        data = config_data()
        data["test_patterns"] = ["/tests/**"]
        with self.assertRaisesRegex(c.ConfidenceError, "repository relative"):
            c.validate_config(data)

    def test_rejects_parent_directory_pattern(self):
        data = config_data()
        data["test_patterns"] = ["tests/../secrets/**"]
        with self.assertRaisesRegex(c.ConfidenceError, "stay inside"):
            c.validate_config(data)

    def test_rejects_backslash_pattern(self):
        data = config_data()
        data["test_patterns"] = ["tests\\**"]
        with self.assertRaisesRegex(c.ConfidenceError, "forward slashes"):
            c.validate_config(data)

    def test_repository_config_is_valid(self):
        config = c.load_config(REPO_ROOT / ".github" / "pr-confidence.yml")
        self.assertIn("cpu", config["critical_checks"])
        self.assertIn("CodeQL", config["critical_checks"])


class PathTests(unittest.TestCase):
    def test_globstar_matches_nested_paths(self):
        self.assertTrue(c.matches_any("tests/test_a.py", ["tests/**"]))
        self.assertTrue(c.matches_any("tests/unit/test_a.py", ["tests/**"]))
        self.assertFalse(c.matches_any("other/tests/test_a.py", ["tests/**"]))

    def test_globstar_prefix_matches_any_depth(self):
        self.assertTrue(c.matches_any("test_a.py", ["**/test_*.py"]))
        self.assertTrue(c.matches_any("pkg/test_a.py", ["**/test_*.py"]))
        self.assertTrue(c.matches_any("pkg/deep/test_a.py", ["**/test_*.py"]))
        self.assertFalse(c.matches_any("pkg/test_a.txt", ["**/test_*.py"]))

    def test_single_star_does_not_cross_directories(self):
        self.assertTrue(c.matches_any(".github/workflows/ci.yml", [".github/workflows/**"]))
        self.assertTrue(c.matches_any(".github/workflows/nested/ci.yml", [".github/workflows/**"]))
        self.assertFalse(c.matches_any(".github/workflows/ci.yml", [".github/*.yml"]))
        self.assertFalse(c.matches_any("runners/ci.yml", [".github/workflows/**"]))

    def test_docs_classification(self):
        self.assertTrue(c.is_docs_file("README.md"))
        self.assertTrue(c.is_docs_file("docs/notes.rst"))
        self.assertTrue(c.is_docs_file("UNLICENSE.txt"))
        self.assertTrue(c.is_docs_file("LICENSE"))
        self.assertFalse(c.is_docs_file("CMakeLists.txt"))
        self.assertFalse(c.is_docs_file("src/kernel.cu"))

    def test_code_span_uses_a_safe_fence(self):
        self.assertEqual(c.code_span("src/a`b.cu"), "``src/a`b.cu``")
        self.assertEqual(c.code_span("a``b"), "```a``b```")
        self.assertEqual(c.code_span("`lead"), "`` `lead ``")
        self.assertEqual(c.code_span("a\nb"), "`a b`")

    def test_check_line_escapes_backticks_in_check_names(self):
        line = c.check_line(
            {
                "name": "evil`check``name",
                "app": "github-actions",
                "status": "completed",
                "conclusion": "failure",
                "details_url": "",
            }
        )
        self.assertIn("```evil`check``name```", line)

    def test_latest_check_prefers_newest_start(self):
        runs = [
            make_run("cpu", conclusion="failure", started="2026-01-01T00:00:00Z"),
            make_run("cpu", conclusion="success", started="2026-01-02T00:00:00Z"),
        ]
        latest = c.latest_check(runs, "cpu")
        self.assertEqual(latest["conclusion"], "success")

    def test_check_states(self):
        cases = [
            (None, "missing"),
            (make_run("x", status="queued", conclusion=None), "pending"),
            (make_run("x"), "success"),
            (make_run("x", conclusion="failure"), "failure"),
            (make_run("x", conclusion="timed_out"), "failure"),
            (make_run("x", conclusion="action_required"), "failure"),
            (make_run("x", conclusion="startup_failure"), "failure"),
            (make_run("x", conclusion="skipped"), "incomplete"),
            (make_run("x", conclusion="cancelled"), "incomplete"),
            (make_run("x", conclusion="neutral"), "incomplete"),
            (make_run("x", conclusion="stale"), "incomplete"),
            (make_run("x", conclusion=None), "incomplete"),
            (make_run("x", conclusion="mystery"), "unknown"),
        ]
        for run, expected in cases:
            with self.subTest(run=run, expected=expected):
                self.assertEqual(c.check_state(run)[0], expected)


class ScoringTests(unittest.TestCase):
    def test_complete_evidence_scores_five(self):
        result = c.evaluate(make_evidence(), make_config())
        self.assertEqual(result["score"], 5)
        self.assertEqual(result["blockers"], [])
        self.assertEqual(
            statuses(result),
            {
                "automated_validation": "pass",
                "tests": "pass",
                "review": "pass",
                "scope": "pass",
                "security": "pass",
            },
        )

    def test_failed_critical_check_blocks_and_loses_a_point(self):
        evidence = make_evidence()
        evidence["checks"]["items"] = [
            make_run("cpu", conclusion="failure"),
            make_run("CodeQL"),
            make_run("Socket Security: Pull Request Alerts"),
        ]
        result = c.evaluate(evidence, make_config())
        self.assertEqual(result["score"], 4)
        self.assertEqual(statuses(result)["automated_validation"], "blocked")
        self.assertEqual(result["blockers"], ["Critical check `cpu` did not pass."])

    def test_failed_critical_check_can_be_non_blocking(self):
        evidence = make_evidence()
        evidence["checks"]["items"] = [
            make_run("cpu", conclusion="timed_out"),
            make_run("CodeQL"),
            make_run("Socket Security: Pull Request Alerts"),
        ]
        result = c.evaluate(evidence, make_config(failed_critical_checks=False))
        self.assertEqual(result["score"], 4)
        self.assertEqual(result["blockers"], [])

    def test_pending_critical_check_is_not_a_pass(self):
        evidence = make_evidence()
        evidence["checks"]["items"] = [
            make_run("cpu", status="in_progress", conclusion=None),
            make_run("CodeQL"),
            make_run("Socket Security: Pull Request Alerts"),
        ]
        result = c.evaluate(evidence, make_config())
        self.assertEqual(result["score"], 4)
        self.assertEqual(statuses(result)["automated_validation"], "pending")
        self.assertEqual(result["blockers"], [])

    def test_skipped_critical_check_is_not_a_pass(self):
        evidence = make_evidence()
        evidence["checks"]["items"] = [
            make_run("cpu", conclusion="skipped"),
            make_run("CodeQL"),
            make_run("Socket Security: Pull Request Alerts"),
        ]
        result = c.evaluate(evidence, make_config())
        self.assertEqual(result["score"], 4)
        self.assertEqual(statuses(result)["automated_validation"], "missing")
        self.assertEqual(result["blockers"], [])

    def test_missing_critical_check_names_the_check(self):
        evidence = make_evidence()
        evidence["checks"]["items"] = [
            make_run("CodeQL"),
            make_run("Socket Security: Pull Request Alerts"),
        ]
        result = c.evaluate(evidence, make_config())
        item = category(result, "automated_validation")
        self.assertEqual(item["status"], "missing")
        self.assertIn("`cpu`: not reported for this head.", item["evidence"])

    def test_unavailable_checks_are_unassessed(self):
        evidence = make_evidence()
        evidence["checks"] = {
            "available": False,
            "truncated": False,
            "items": [],
            "error": "forbidden",
        }
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["automated_validation"], "unassessed")
        self.assertEqual(statuses(result)["security"], "unassessed")
        self.assertEqual(result["score"], 3)
        self.assertEqual(result["blockers"], [])

    def test_truncated_checks_are_unassessed(self):
        evidence = make_evidence()
        evidence["checks"]["truncated"] = True
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["automated_validation"], "unassessed")
        self.assertEqual(statuses(result)["security"], "unassessed")

    def test_self_check_is_not_counted_as_evidence(self):
        evidence = make_evidence()
        evidence["checks"]["items"].append(make_run(c.CHECK_NAME, conclusion="failure"))
        result = c.evaluate(evidence, make_config())
        self.assertEqual(result["score"], 5)
        names = [run["name"] for run in result["observed_checks"]]
        self.assertNotIn(c.CHECK_NAME, names)

    def test_non_critical_failure_is_noted_not_scored(self):
        evidence = make_evidence()
        evidence["checks"]["items"].append(make_run("extra", conclusion="failure"))
        result = c.evaluate(evidence, make_config())
        self.assertEqual(result["score"], 5)
        self.assertTrue(any("Non-critical check `extra`" in note for note in result["notes"]))


class TestEvidenceTests(unittest.TestCase):
    def test_docs_only_change_is_not_applicable(self):
        evidence = make_evidence()
        evidence["pr"]["changed_files"] = 1
        evidence["files"]["items"] = [
            {
                "filename": "README.md",
                "status": "modified",
                "additions": 5,
                "deletions": 1,
                "changes": 6,
            }
        ]
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["tests"], "not_applicable")
        self.assertEqual(result["score"], 4)

    def test_code_without_test_change_is_missing(self):
        evidence = make_evidence()
        evidence["pr"]["changed_files"] = 1
        evidence["files"]["items"] = [
            {
                "filename": "kernels/kernel.cu",
                "status": "modified",
                "additions": 5,
                "deletions": 1,
                "changes": 6,
            }
        ]
        result = c.evaluate(evidence, make_config())
        item = category(result, "tests")
        self.assertEqual(item["status"], "missing")
        self.assertIn("not proof that tests are inadequate", item["detail"])

    def test_unavailable_files_leave_tests_unassessed(self):
        evidence = make_evidence()
        evidence["files"] = {
            "available": False,
            "truncated": False,
            "items": [],
            "error": "forbidden",
        }
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["tests"], "unassessed")
        self.assertEqual(statuses(result)["scope"], "unassessed")
        self.assertEqual(statuses(result)["security"], "unassessed")

    def test_truncated_files_leave_tests_unassessed(self):
        evidence = make_evidence()
        evidence["files"]["truncated"] = True
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["tests"], "unassessed")
        self.assertEqual(statuses(result)["scope"], "unassessed")


class ReviewTests(unittest.TestCase):
    def test_changes_requested_blocks_by_default(self):
        evidence = make_evidence()
        evidence["review"]["decision"] = "CHANGES_REQUESTED"
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["review"], "blocked")
        self.assertEqual(result["blockers"], ["The latest review requests changes."])

    def test_changes_requested_can_be_non_blocking(self):
        evidence = make_evidence()
        evidence["review"]["decision"] = "CHANGES_REQUESTED"
        result = c.evaluate(evidence, make_config(changes_requested=False))
        self.assertEqual(statuses(result)["review"], "missing")
        self.assertEqual(result["blockers"], [])

    def test_unresolved_thread_can_be_non_blocking(self):
        evidence = make_evidence()
        evidence["review"]["unresolved"] = [
            {"path": "src/thing.cu", "url": "https://example.invalid/t", "outdated": False}
        ]
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["review"], "missing")
        self.assertEqual(result["blockers"], [])

    def test_unresolved_thread_can_block(self):
        evidence = make_evidence()
        evidence["review"]["unresolved"] = [
            {"path": "src/thing.cu", "url": "https://example.invalid/t", "outdated": True}
        ]
        result = c.evaluate(evidence, make_config(unresolved_threads=True))
        self.assertEqual(statuses(result)["review"], "blocked")
        self.assertEqual(result["blockers"], ["1 unresolved review thread(s) remain."])

    def test_no_approval_is_missing(self):
        evidence = make_evidence()
        evidence["review"]["decision"] = "REVIEW_REQUIRED"
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["review"], "missing")
        self.assertEqual(result["blockers"], [])

    def test_unavailable_review_is_unassessed(self):
        evidence = make_evidence()
        evidence["review"] = {
            "available": False,
            "decision": None,
            "unresolved": [],
            "threads_truncated": False,
            "error": "graphql refused",
        }
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["review"], "unassessed")
        self.assertIn("graphql refused", category(result, "review")["detail"])

    def test_truncated_review_threads_are_unassessed(self):
        evidence = make_evidence()
        evidence["review"]["threads_truncated"] = True
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["review"], "unassessed")

    def test_changes_requested_blocks_when_threads_are_truncated(self):
        evidence = make_evidence()
        evidence["review"]["decision"] = "CHANGES_REQUESTED"
        evidence["review"]["threads_truncated"] = True
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["review"], "blocked")
        self.assertEqual(result["blockers"], ["The latest review requests changes."])

    def test_changes_requested_is_missing_when_threads_are_truncated_and_not_blocking(self):
        evidence = make_evidence()
        evidence["review"]["decision"] = "CHANGES_REQUESTED"
        evidence["review"]["threads_truncated"] = True
        result = c.evaluate(evidence, make_config(changes_requested=False))
        self.assertEqual(statuses(result)["review"], "missing")
        self.assertEqual(result["blockers"], [])

    def test_visible_unresolved_thread_can_block_when_threads_are_truncated(self):
        evidence = make_evidence()
        evidence["review"]["threads_truncated"] = True
        evidence["review"]["unresolved"] = [
            {"path": "src/thing.cu", "url": "https://example.invalid/t", "outdated": False}
        ]
        result = c.evaluate(evidence, make_config(unresolved_threads=True))
        self.assertEqual(statuses(result)["review"], "blocked")
        self.assertEqual(result["blockers"], ["1 unresolved review thread(s) remain."])


class ScopeTests(unittest.TestCase):
    def test_short_description_fails_scope(self):
        evidence = make_evidence()
        evidence["pr"]["body_length"] = 5
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["scope"], "missing")
        self.assertIn("below 40", category(result, "scope")["detail"])

    def test_description_boundary_passes(self):
        evidence = make_evidence()
        evidence["pr"]["body_length"] = 40
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["scope"], "pass")

    def test_saved_evidence_falls_back_to_raw_body(self):
        evidence = make_evidence()
        evidence["pr"].pop("body_length")
        evidence["pr"]["body"] = "x" * 40
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["scope"], "pass")

    def test_body_length_takes_precedence_over_raw_body(self):
        evidence = make_evidence()
        evidence["pr"]["body_length"] = 5
        evidence["pr"]["body"] = "x" * 40
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["scope"], "missing")

    def test_file_count_above_limit_fails_scope(self):
        evidence = make_evidence()
        evidence["pr"]["changed_files"] = 31
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["scope"], "missing")
        self.assertIn("31 files", category(result, "scope")["detail"])

    def test_file_count_boundary_passes(self):
        evidence = make_evidence()
        evidence["pr"]["changed_files"] = 30
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["scope"], "pass")

    def test_changed_line_limit_fails_scope(self):
        evidence = make_evidence()
        evidence["pr"]["additions"] = 1000
        evidence["pr"]["deletions"] = 501
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["scope"], "missing")
        self.assertIn("1501 lines", category(result, "scope")["detail"])


class SecurityTests(unittest.TestCase):
    def test_security_check_failure_is_not_a_blocker_by_default(self):
        evidence = make_evidence()
        evidence["checks"]["items"] = [
            make_run("cpu"),
            make_run("CodeQL"),
            make_run("Socket Security: Pull Request Alerts", conclusion="failure"),
        ]
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["security"], "missing")
        self.assertEqual(result["score"], 4)
        self.assertEqual(result["blockers"], [])

    def test_security_check_failure_can_block(self):
        evidence = make_evidence()
        evidence["checks"]["items"] = [
            make_run("cpu"),
            make_run("CodeQL"),
            make_run("Socket Security: Pull Request Alerts", conclusion="failure"),
        ]
        result = c.evaluate(evidence, make_config(security_check_failure=True))
        self.assertEqual(statuses(result)["security"], "blocked")
        self.assertEqual(
            result["blockers"],
            ["Security check `Socket Security: Pull Request Alerts` did not pass."],
        )

    def test_pending_security_check(self):
        evidence = make_evidence()
        evidence["checks"]["items"] = [
            make_run("cpu"),
            make_run("CodeQL"),
            make_run("Socket Security: Pull Request Alerts", status="queued", conclusion=None),
        ]
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["security"], "pending")

    def test_sensitive_path_without_tests_is_missing(self):
        evidence = make_evidence()
        evidence["pr"]["changed_files"] = 1
        evidence["files"]["items"] = [
            {
                "filename": ".github/workflows/release.yml",
                "status": "modified",
                "additions": 5,
                "deletions": 1,
                "changes": 6,
            }
        ]
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["security"], "missing")
        self.assertIn("without a test-file change", category(result, "security")["detail"])

    def test_sensitive_path_with_tests_passes(self):
        result = c.evaluate(make_evidence(), make_config())
        self.assertEqual(statuses(result)["security"], "pass")
        self.assertIn("alongside test files", category(result, "security")["detail"])

    def test_no_sensitive_path_passes(self):
        evidence = make_evidence()
        evidence["pr"]["changed_files"] = 2
        evidence["files"]["items"] = [
            {
                "filename": "README.md",
                "status": "modified",
                "additions": 5,
                "deletions": 1,
                "changes": 6,
            },
            {
                "filename": "docs/notes.md",
                "status": "modified",
                "additions": 5,
                "deletions": 1,
                "changes": 6,
            },
        ]
        result = c.evaluate(evidence, make_config())
        self.assertEqual(statuses(result)["security"], "pass")
        self.assertIn("no configured security-sensitive path", category(result, "security")["detail"])


class BlockerTests(unittest.TestCase):
    def test_high_score_can_still_have_a_blocker(self):
        evidence = make_evidence()
        evidence["pr"]["mergeable"] = False
        result = c.evaluate(evidence, make_config())
        self.assertEqual(result["score"], 5)
        self.assertEqual(result["blockers"], ["The pull request has a merge conflict."])

    def test_merge_conflict_blocker_can_be_disabled(self):
        evidence = make_evidence()
        evidence["pr"]["mergeable"] = False
        result = c.evaluate(evidence, make_config(merge_conflict=False))
        self.assertEqual(result["blockers"], [])

    def test_draft_is_not_a_default_blocker(self):
        evidence = make_evidence()
        evidence["pr"]["draft"] = True
        result = c.evaluate(evidence, make_config())
        self.assertEqual(result["blockers"], [])
        self.assertTrue(any("draft pull request" in note for note in result["notes"]))

    def test_draft_can_block(self):
        evidence = make_evidence()
        evidence["pr"]["draft"] = True
        result = c.evaluate(evidence, make_config(draft=True))
        self.assertEqual(result["blockers"], ["The pull request is a draft."])

    def test_head_mismatch_blocks_and_notes_both_heads(self):
        evidence = make_evidence()
        evidence["pr"]["head_mismatch"] = True
        evidence["pr"]["api_head_sha"] = "def456"
        result = c.evaluate(evidence, make_config())
        self.assertIn(
            "The pull request head moved during collection; this result is stale.",
            result["blockers"],
        )
        self.assertTrue(any("abc123" in note and "def456" in note for note in result["notes"]))

    def test_unknown_mergeability_is_noted(self):
        evidence = make_evidence()
        evidence["pr"]["mergeable"] = None
        result = c.evaluate(evidence, make_config())
        self.assertEqual(result["blockers"], [])
        self.assertTrue(any("mergeability" in note for note in result["notes"]))

    def test_closed_pull_request_is_noted(self):
        evidence = make_evidence()
        evidence["pr"]["state"] = "closed"
        result = c.evaluate(evidence, make_config())
        self.assertTrue(any("closed" in note for note in result["notes"]))


class SummaryTests(unittest.TestCase):
    def test_summary_names_the_score_and_limits(self):
        result = c.evaluate(make_evidence(), make_config())
        summary = c.render_summary(result)
        self.assertIn("# PR Confidence", summary)
        self.assertIn("Score: **5 / 5**", summary)
        self.assertIn("not a probability", summary)
        self.assertIn("## Hard blockers", summary)
        self.assertIn("## Limits", summary)
        self.assertIn("A low score does not fail the check", summary)

    def test_summary_lists_blockers_and_gaps(self):
        evidence = make_evidence()
        evidence["pr"]["mergeable"] = False
        evidence["pr"]["body_length"] = 5
        result = c.evaluate(evidence, make_config())
        summary = c.render_summary(result)
        self.assertIn("The pull request has a merge conflict.", summary)
        self.assertIn("below 40", summary)

    def test_summary_keeps_pipe_titles_inside_code_spans(self):
        evidence = make_evidence()
        evidence["pr"]["title"] = "a | b"
        result = c.evaluate(evidence, make_config())
        summary = c.render_summary(result)
        self.assertIn("`a | b`", summary)

    def test_summary_keeps_markdown_links_in_titles_inside_code_spans(self):
        evidence = make_evidence()
        evidence["pr"]["title"] = "[approved](https://attacker.example)"
        result = c.evaluate(evidence, make_config())
        summary = c.render_summary(result)
        self.assertIn("`[approved](https://attacker.example)`", summary)

    def test_summary_keeps_backtick_paths_inside_code_spans(self):
        evidence = make_evidence()
        evidence["files"]["items"] = [
            {
                "filename": "tests/test_`x`.py",
                "status": "added",
                "additions": 10,
                "deletions": 0,
                "changes": 10,
            },
            {
                "filename": ".github/workflows/`ci`.yml",
                "status": "modified",
                "additions": 10,
                "deletions": 3,
                "changes": 13,
            },
        ]
        result = c.evaluate(evidence, make_config())
        summary = c.render_summary(result)
        self.assertIn("``tests/test_`x`.py``", summary)
        self.assertIn("``.github/workflows/`ci`.yml``", summary)

    def test_summary_escapes_backticks_in_observed_check_names(self):
        evidence = make_evidence()
        evidence["checks"]["items"].append(
            make_run("evil`run``name", conclusion="failure")
        )
        result = c.evaluate(evidence, make_config())
        summary = c.render_summary(result)
        self.assertIn("```evil`run``name```", summary)

    def test_summary_escapes_backticks_in_configured_check_names(self):
        data = config_data()
        data["critical_checks"] = ["cpu`x"]
        evidence = make_evidence()
        result = c.evaluate(evidence, c.validate_config(data))
        summary = c.render_summary(result)
        self.assertIn("``cpu`x``", summary)


class CliTests(unittest.TestCase):
    def run_main(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = c.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def write_fixture(self, directory, config=None, evidence=None):
        config_path = Path(directory) / "config.yml"
        evidence_path = Path(directory) / "evidence.json"
        summary_path = Path(directory) / "summary.md"
        config_path.write_text(json.dumps(config or config_data()) + "\n", encoding="utf-8")
        evidence_path.write_text(json.dumps(evidence or make_evidence()), encoding="utf-8")
        return config_path, evidence_path, summary_path

    def test_clean_evidence_exits_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path, evidence_path, summary_path = self.write_fixture(directory)
            code, stdout, _ = self.run_main(
                [
                    "--config",
                    str(config_path),
                    "--evidence",
                    str(evidence_path),
                    "--summary",
                    str(summary_path),
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("PR Confidence: 5/5, 0 hard blocker(s)", stdout)
            self.assertIn("Score: **5 / 5**", summary_path.read_text(encoding="utf-8"))

    def test_blocker_exits_one(self):
        evidence = make_evidence()
        evidence["pr"]["mergeable"] = False
        with tempfile.TemporaryDirectory() as directory:
            config_path, evidence_path, summary_path = self.write_fixture(
                directory, evidence=evidence
            )
            code, stdout, _ = self.run_main(
                [
                    "--config",
                    str(config_path),
                    "--evidence",
                    str(evidence_path),
                    "--summary",
                    str(summary_path),
                ]
            )
            self.assertEqual(code, 1)
            self.assertIn("1 hard blocker(s)", stdout)
            self.assertIn("merge conflict", summary_path.read_text(encoding="utf-8"))

    def test_bad_config_exits_two_and_records_failure(self):
        config = config_data()
        config["version"] = 9
        with tempfile.TemporaryDirectory() as directory:
            config_path, evidence_path, summary_path = self.write_fixture(
                directory, config=config
            )
            code, _, stderr = self.run_main(
                [
                    "--config",
                    str(config_path),
                    "--evidence",
                    str(evidence_path),
                    "--summary",
                    str(summary_path),
                ]
            )
            self.assertEqual(code, 2)
            self.assertIn("Evidence collection failed", summary_path.read_text(encoding="utf-8"))
            self.assertIn("error:", stderr)

    def test_missing_evidence_file_exits_two(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path, _, summary_path = self.write_fixture(directory)
            code, _, _ = self.run_main(
                [
                    "--config",
                    str(config_path),
                    "--evidence",
                    str(Path(directory) / "absent.json"),
                    "--summary",
                    str(summary_path),
                ]
            )
            self.assertEqual(code, 2)

    def test_invalid_wait_settings_exit_two_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path, _, _ = self.write_fixture(directory)
            code, _, stderr = self.run_main(
                [
                    "--config",
                    str(config_path),
                    "--repo",
                    "owner/repo",
                    "--pr",
                    "7",
                    "--head-sha",
                    "abc123",
                    "--wait",
                    "--wait-timeout",
                    "-1",
                ]
            )
            self.assertEqual(code, 2)
            self.assertIn("poll interval", stderr)


class FakeProcess:
    def __init__(self, stdout="{}", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def raw_check_runs(*runs, total=None):
    return {"total_count": len(runs) if total is None else total, "check_runs": list(runs)}


class WaitTests(unittest.TestCase):
    def wait(self, responses, timeout=60, interval=15):
        clock = FakeClock()
        with mock.patch.object(c, "gh_json", side_effect=responses):
            c.wait_for_checks(
                "owner/repo",
                "abc123",
                make_config(),
                timeout,
                interval,
                clock=clock.clock,
                sleep=clock.sleep,
            )
        return clock

    def test_returns_when_all_configured_checks_complete(self):
        responses = [raw_check_runs(*raw_default_checks())]
        clock = self.wait(responses)
        self.assertEqual(clock.sleeps, [])

    def test_waits_for_pending_check(self):
        pending = make_raw_run("cpu", status="in_progress", conclusion=None)
        first = raw_check_runs(
            pending,
            make_raw_run("CodeQL"),
            make_raw_run("Socket Security: Pull Request Alerts"),
        )
        second = raw_check_runs(*raw_default_checks())
        clock = self.wait([first, second])
        self.assertEqual(clock.sleeps, [15])

    def test_times_out_while_check_is_missing(self):
        runs = raw_check_runs(make_raw_run("cpu"), make_raw_run("CodeQL"))
        clock = self.wait([runs, runs, runs, runs], timeout=30, interval=10)
        self.assertEqual(clock.sleeps, [10, 10, 10])

    def test_sleep_does_not_overshoot_the_deadline(self):
        runs = raw_check_runs(make_raw_run("cpu"))
        clock = self.wait([runs, runs], timeout=5, interval=15)
        self.assertEqual(clock.sleeps, [5])

    def test_truncated_runs_do_not_wait(self):
        runs = raw_check_runs(*raw_default_checks(), total=101)
        clock = self.wait([runs])
        self.assertEqual(clock.sleeps, [])

    def test_unconfigured_incomplete_check_is_ignored(self):
        runs = raw_check_runs(
            *raw_default_checks(),
            make_raw_run("unrelated", status="in_progress", conclusion=None),
        )
        clock = self.wait([runs])
        self.assertEqual(clock.sleeps, [])

    def test_api_error_propagates(self):
        with mock.patch.object(c, "gh_json", side_effect=c.ConfidenceError("boom")):
            with self.assertRaisesRegex(c.ConfidenceError, "boom"):
                c.wait_for_checks(
                    "owner/repo",
                    "abc123",
                    make_config(),
                    10,
                    1,
                    clock=lambda: 0,
                    sleep=lambda seconds: None,
                )


class CollectorTests(unittest.TestCase):
    def fake_run(self, responses, commands):
        def run(cmd, **kwargs):
            commands.append(cmd)
            for marker, response in responses:
                if marker in " ".join(cmd):
                    if isinstance(response, FakeProcess):
                        return response
                    return FakeProcess(json.dumps(response))
            return FakeProcess(json.dumps({}))

        return run

    def test_collects_read_only_evidence(self):
        commands = []
        pr = {
            "number": 7,
            "title": "Add the thing",
            "body": "Body",
            "draft": False,
            "state": "open",
            "mergeable": True,
            "mergeable_state": "clean",
            "changed_files": 1,
            "additions": 4,
            "deletions": 1,
            "commits": 1,
            "user": {"login": "octocat"},
            "head": {"sha": "abc123"},
        }
        files = [
            {
                "filename": "src/thing.cu",
                "status": "modified",
                "additions": 4,
                "deletions": 1,
                "changes": 5,
            }
        ]
        checks = {
            "total_count": 1,
            "check_runs": [
                {
                    "name": "cpu",
                    "status": "completed",
                    "conclusion": "success",
                    "details_url": "https://example.invalid/run",
                    "started_at": "2026-01-01T00:00:00Z",
                    "completed_at": "2026-01-01T00:01:00Z",
                    "app": {"slug": "github-actions"},
                }
            ],
        }
        graphql = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewDecision": "APPROVED",
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [],
                        },
                    }
                }
            }
        }
        responses = [
            ("pulls/7/files", files),
            ("pulls/7", pr),
            ("check-runs", checks),
            ("graphql", graphql),
        ]
        with mock.patch.object(c.subprocess, "run", self.fake_run(responses, commands)):
            evidence = c.collect_evidence("owner/repo", 7, "abc123")

        self.assertTrue(commands)
        for command in commands:
            self.assertEqual(command[:2], ["gh", "api"])
            joined = " ".join(command)
            for verb in ("--method POST", "--method PATCH", "--method PUT", "--method DELETE"):
                self.assertNotIn(verb, joined)
        self.assertEqual(evidence["pr"]["head_mismatch"], False)
        self.assertEqual(evidence["review"]["decision"], "APPROVED")
        self.assertEqual(len(evidence["checks"]["items"]), 1)
        self.assertEqual(evidence["checks"]["items"][0]["app"], "github-actions")
        self.assertFalse(evidence["files"]["truncated"])

    def test_collected_evidence_stores_only_body_length(self):
        commands = []
        secret = "ghp_example_secret_value"
        pr = {
            "number": 7,
            "changed_files": 0,
            "head": {"sha": "abc123"},
            "body": secret,
        }
        responses = [
            ("pulls/7/files", []),
            ("pulls/7", pr),
            ("check-runs", {"total_count": 0, "check_runs": []}),
            ("graphql", {"data": {"repository": {"pullRequest": {}}}}),
        ]
        with mock.patch.object(c.subprocess, "run", self.fake_run(responses, commands)):
            evidence = c.collect_evidence("owner/repo", 7, "abc123")
        self.assertEqual(evidence["pr"]["body_length"], len(secret))
        self.assertNotIn("body", evidence["pr"])
        self.assertNotIn(secret, json.dumps(evidence))

    def test_head_mismatch_is_recorded(self):
        commands = []
        pr = {
            "number": 7,
            "changed_files": 0,
            "head": {"sha": "def456"},
        }
        responses = [
            ("pulls/7/files", []),
            ("pulls/7", pr),
            ("check-runs", {"total_count": 0, "check_runs": []}),
            ("graphql", {"data": {"repository": {"pullRequest": {}}}}),
        ]
        with mock.patch.object(c.subprocess, "run", self.fake_run(responses, commands)):
            evidence = c.collect_evidence("owner/repo", 7, "abc123")
        self.assertTrue(evidence["pr"]["head_mismatch"])

    def test_more_changed_files_than_reported_marks_files_truncated(self):
        commands = []
        pr = {"number": 7, "changed_files": 150, "head": {"sha": "abc123"}}
        files = [{"filename": "f%d.txt" % index} for index in range(2)]
        responses = [
            ("pulls/7/files", files),
            ("pulls/7", pr),
            ("check-runs", {"total_count": 0, "check_runs": []}),
            ("graphql", {"data": {"repository": {"pullRequest": {}}}}),
        ]
        with mock.patch.object(c.subprocess, "run", self.fake_run(responses, commands)):
            evidence = c.collect_evidence("owner/repo", 7, "abc123")
        self.assertTrue(evidence["files"]["truncated"])

    def test_exactly_one_hundred_changed_files_is_complete(self):
        commands = []
        pr = {"number": 7, "changed_files": 100, "head": {"sha": "abc123"}}
        files = [{"filename": "f%d.txt" % index} for index in range(100)]
        responses = [
            ("pulls/7/files", files),
            ("pulls/7", pr),
            ("check-runs", {"total_count": 0, "check_runs": []}),
            ("graphql", {"data": {"repository": {"pullRequest": {}}}}),
        ]
        with mock.patch.object(c.subprocess, "run", self.fake_run(responses, commands)):
            evidence = c.collect_evidence("owner/repo", 7, "abc123")
        self.assertFalse(evidence["files"]["truncated"])

    def test_one_hundred_returned_of_one_hundred_and_one_is_truncated(self):
        commands = []
        pr = {"number": 7, "changed_files": 101, "head": {"sha": "abc123"}}
        files = [{"filename": "f%d.txt" % index} for index in range(100)]
        responses = [
            ("pulls/7/files", files),
            ("pulls/7", pr),
            ("check-runs", {"total_count": 0, "check_runs": []}),
            ("graphql", {"data": {"repository": {"pullRequest": {}}}}),
        ]
        with mock.patch.object(c.subprocess, "run", self.fake_run(responses, commands)):
            evidence = c.collect_evidence("owner/repo", 7, "abc123")
        self.assertTrue(evidence["files"]["truncated"])
        commands = []
        pr = {"number": 7, "changed_files": 0, "head": {"sha": "abc123"}}
        responses = [
            ("pulls/7/files", []),
            ("pulls/7", pr),
            ("check-runs", {"total_count": 120, "check_runs": []}),
            ("graphql", {"data": {"repository": {"pullRequest": {}}}}),
        ]
        with mock.patch.object(c.subprocess, "run", self.fake_run(responses, commands)):
            evidence = c.collect_evidence("owner/repo", 7, "abc123")
        self.assertTrue(evidence["checks"]["truncated"])

    def test_graphql_errors_leave_review_unavailable(self):
        commands = []
        pr = {"number": 7, "changed_files": 0, "head": {"sha": "abc123"}}
        responses = [
            ("pulls/7/files", []),
            ("pulls/7", pr),
            ("check-runs", {"total_count": 0, "check_runs": []}),
            ("graphql", {"errors": [{"message": "denied"}]}),
        ]
        with mock.patch.object(c.subprocess, "run", self.fake_run(responses, commands)):
            evidence = c.collect_evidence("owner/repo", 7, "abc123")
        self.assertFalse(evidence["review"]["available"])
        self.assertIn("denied", evidence["review"]["error"])

    def test_optional_json_failures_do_not_crash(self):
        commands = []
        pr = {"number": 7, "changed_files": 0, "head": {"sha": "abc123"}}
        responses = [
            ("pulls/7/files", FakeProcess(stdout="", stderr="boom", returncode=1)),
            ("pulls/7", pr),
            ("check-runs", FakeProcess(stdout="", stderr="boom", returncode=1)),
            ("graphql", {"data": {"repository": {"pullRequest": {}}}}),
        ]
        with mock.patch.object(c.subprocess, "run", self.fake_run(responses, commands)):
            evidence = c.collect_evidence("owner/repo", 7, "abc123")
        self.assertFalse(evidence["files"]["available"])
        self.assertFalse(evidence["checks"]["available"])

    def test_invalid_repository_and_sha_are_rejected(self):
        with self.assertRaisesRegex(c.ConfidenceError, "owner/name"):
            c.collect_evidence("repo", 7, "abc123")
        with self.assertRaisesRegex(c.ConfidenceError, "positive"):
            c.collect_evidence("owner/repo", 0, "abc123")
        with self.assertRaisesRegex(c.ConfidenceError, "head SHA"):
            c.collect_evidence("owner/repo", 7, "")

    def test_gh_json_rejects_invalid_json(self):
        commands = []
        with mock.patch.object(
            c.subprocess,
            "run",
            self.fake_run([("repos/owner/repo/pulls/7", FakeProcess(stdout="not json"))], commands),
        ):
            with self.assertRaisesRegex(c.ConfidenceError, "invalid JSON"):
                c.gh_json(["repos/owner/repo/pulls/7"])


class WorkflowPolicyTests(unittest.TestCase):
    WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pr-confidence.yml"

    def load_workflow(self):
        with self.WORKFLOW_PATH.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def checkout_steps(self, workflow):
        steps = workflow["jobs"]["confidence"]["steps"]
        return [
            step
            for step in steps
            if str(step.get("uses") or "").startswith("actions/checkout@")
        ]

    def test_runs_from_the_trusted_base_event(self):
        workflow = self.load_workflow()
        triggers = workflow.get("on")
        if triggers is None:
            triggers = workflow.get(True)
        self.assertIn("pull_request_target", triggers)
        self.assertNotIn("pull_request", triggers)
        self.assertNotIn("pull_request_review", triggers)
        self.assertIn("workflow_dispatch", triggers)

    def test_checks_out_only_the_default_branch(self):
        workflow = self.load_workflow()
        checkouts = self.checkout_steps(workflow)
        self.assertEqual(len(checkouts), 1)
        with_args = checkouts[0].get("with") or {}
        self.assertEqual(
            with_args.get("ref"), "${{ github.event.repository.default_branch }}"
        )
        self.assertEqual(with_args.get("persist-credentials"), False)
        for step in checkouts:
            ref = str((step.get("with") or {}).get("ref") or "")
            self.assertNotIn("pull_request.head", ref)
            self.assertNotIn("steps.target.outputs.head", ref)

    def test_permissions_are_read_only(self):
        workflow = self.load_workflow()
        self.assertEqual(
            workflow["permissions"],
            {"contents": "read", "pull-requests": "read", "checks": "read"},
        )
        for permission in workflow["permissions"].values():
            self.assertNotIn("write", permission)


if __name__ == "__main__":
    unittest.main()
