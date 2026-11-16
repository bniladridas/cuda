#!/usr/bin/env python3
"""Offline tests for the read-only PR Scope Guard."""

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
sys.path.insert(0, str(REPO_ROOT / "pr-scope-guard" / "engine"))

import scope_guard

CONFIG_PATH = REPO_ROOT / ".github" / "pr-scope-guard.yml"
REGISTRY_PATH = REPO_ROOT / ".github" / "pr-scopes.json"
CLEAN_FIXTURE = TESTS_DIR / "fixtures" / "clean.json"
MIXED_FIXTURE = TESTS_DIR / "fixtures" / "mixed.json"
HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def make_fixture(number, title, files):
    return {
        "pull_request": {
            "number": number,
            "title": title,
            "head": {"sha": HEAD_SHA},
            "base": {"sha": BASE_SHA},
        },
        "files": files,
    }


class ScopeGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.artifact = self.dir / "artifact.json"
        self.summary = self.dir / "summary.md"
        self.stderr = ""

    def run_engine(self, fixture_path, config=CONFIG_PATH, registry=REGISTRY_PATH, pr=101, repo="owner/repo"):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = scope_guard.main(
                [
                    "--repo",
                    repo,
                    "--pr",
                    str(pr),
                    "--config",
                    str(config),
                    "--registry",
                    str(registry),
                    "--fixture",
                    str(fixture_path),
                    "--summary",
                    str(self.summary),
                    "--artifact-out",
                    str(self.artifact),
                ]
            )
        self.stderr = stderr.getvalue()
        return code

    def read_artifact(self):
        return json.loads(self.artifact.read_text(encoding="utf-8"))

    def copy_config(self):
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    def write_config(self, config, name="config.yml"):
        path = self.dir / name
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        return path

    def test_title_parsing(self):
        self.assertEqual(scope_guard.parse_title("[kernels] Add a kernel"), ("kernels", "ok"))
        self.assertEqual(scope_guard.parse_title("kernels add a kernel"), (None, "missing"))
        self.assertEqual(scope_guard.parse_title("[kernels]"), (None, "malformed"))
        self.assertEqual(scope_guard.parse_title("[ kernels ] Add"), (None, "malformed"))
        self.assertEqual(scope_guard.parse_title("[Kernels] Add"), (None, "malformed"))

    def test_glob_patterns(self):
        self.assertTrue(scope_guard.matches("docs/a.md", "docs/*.md"))
        self.assertFalse(scope_guard.matches("docs/a/b.md", "docs/*.md"))
        self.assertTrue(scope_guard.matches("docs/a/b.md", "docs/**"))
        self.assertTrue(scope_guard.matches("CMakeLists.txt", "**/CMakeLists.txt"))
        self.assertTrue(scope_guard.matches("kernels/CMakeLists.txt", "**/CMakeLists.txt"))
        self.assertTrue(scope_guard.matches("src/a.cu", "src/?.cu"))
        self.assertFalse(scope_guard.matches("src/ab.cu", "src/?.cu"))

    def test_pattern_validation(self):
        for pattern in ("/docs/**", "../docs/**", "docs\\**", "", "docs//x"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(scope_guard.EngineError):
                    scope_guard.check_pattern(pattern, "test")

    def test_code_span(self):
        self.assertEqual(scope_guard.code_span("plain"), "`plain`")
        self.assertEqual(scope_guard.code_span("a`b"), "``a`b``")
        self.assertEqual(scope_guard.code_span("`x`"), "`` `x` ``")
        self.assertEqual(
            scope_guard.code_span("[x](https://attacker.example)"),
            "`[x](https://attacker.example)`",
        )

    def test_clean_fixture(self):
        self.assertEqual(self.run_engine(CLEAN_FIXTURE), 0)
        artifact = self.read_artifact()
        self.assertEqual(artifact["declared_scope"], "kernels")
        self.assertEqual(artifact["findings"], [])
        self.assertEqual(artifact["counts"]["files"], 2)
        self.assertEqual(artifact["counts"]["matched"], 2)
        self.assertEqual(artifact["counts"]["outside"], 0)
        self.assertIn("No scope mismatches found.", self.summary.read_text(encoding="utf-8"))

    def test_mixed_fixture(self):
        self.assertEqual(self.run_engine(MIXED_FIXTURE, pr=102), 0)
        artifact = self.read_artifact()
        codes = [finding["code"] for finding in artifact["findings"]]
        self.assertIn("files_outside_scope", codes)
        self.assertIn("files_matching_no_scope", codes)
        self.assertEqual(artifact["counts"]["files"], 3)
        self.assertEqual(artifact["counts"]["outside"], 2)
        self.assertEqual(artifact["counts"]["unmapped"], 1)
        self.assertEqual(artifact["files"][1]["previous_filename"], "src/old_tiled.cu")

    def test_unknown_scope(self):
        path = self.dir / "unknown.json"
        write_json(path, make_fixture(101, "[nope] Add a kernel", [{"filename": "src/a.cu", "status": "added"}]))
        self.assertEqual(self.run_engine(path), 0)
        artifact = self.read_artifact()
        self.assertEqual(artifact["title_status"], "unknown")
        self.assertIn("unknown_scope", [finding["code"] for finding in artifact["findings"]])
        self.assertEqual(artifact["candidates"], [{"scope": "kernels", "files": 1}])

    def test_scope_matches_no_files(self):
        path = self.dir / "no-match.json"
        write_json(path, make_fixture(101, "[tests] Touch a kernel", [{"filename": "src/a.cu", "status": "added"}]))
        self.assertEqual(self.run_engine(path), 0)
        artifact = self.read_artifact()
        self.assertIn("scope_matches_no_changed_files", [finding["code"] for finding in artifact["findings"]])
        self.assertEqual(artifact["counts"]["matched"], 0)
        self.assertEqual(artifact["counts"]["outside"], 1)

    def test_missing_title_scope(self):
        path = self.dir / "missing.json"
        write_json(path, make_fixture(101, "Add a kernel", [{"filename": "src/a.cu", "status": "added"}]))
        self.assertEqual(self.run_engine(path), 0)
        artifact = self.read_artifact()
        self.assertEqual(artifact["title_status"], "missing")
        self.assertIn("title_missing_scope", [finding["code"] for finding in artifact["findings"]])

    def test_ignored_file(self):
        path = self.dir / "ignored.json"
        write_json(
            path,
            make_fixture(
                101,
                "[kernels] Add a kernel",
                [
                    {"filename": "src/a.cu", "status": "added"},
                    {"filename": "LICENSE", "status": "modified"},
                ],
            ),
        )
        self.assertEqual(self.run_engine(path), 0)
        artifact = self.read_artifact()
        self.assertEqual(artifact["counts"]["ignored"], 1)
        self.assertEqual(artifact["counts"]["files"], 1)
        self.assertEqual(artifact["findings"], [])

    def test_summary_escapes_markdown_title(self):
        path = self.dir / "markdown.json"
        write_json(
            path,
            make_fixture(
                101,
                "[docs] [approved](https://attacker.example)",
                [{"filename": "docs/a.md", "status": "modified"}],
            ),
        )
        self.assertEqual(self.run_engine(path), 0)
        summary = self.summary.read_text(encoding="utf-8")
        self.assertIn("`[docs] [approved](https://attacker.example)`", summary)

    def test_summary_lists_outside_files(self):
        self.run_engine(MIXED_FIXTURE, pr=102)
        summary = self.summary.read_text(encoding="utf-8")
        self.assertIn("`src/tiled.cu`", summary)
        self.assertIn("`notes.bin`", summary)

    def test_artifact_shape(self):
        self.run_engine(CLEAN_FIXTURE)
        artifact = self.read_artifact()
        self.assertEqual(artifact["version"], 1)
        self.assertEqual(artifact["repo"], "owner/repo")
        self.assertEqual(artifact["pr_number"], 101)
        self.assertEqual(artifact["head_sha"], HEAD_SHA)
        self.assertEqual(artifact["base_sha"], BASE_SHA)
        self.assertIn("generated_at", artifact)
        self.assertIn("files", artifact)
        self.assertIn("counts", artifact)

    def test_config_must_match_registry(self):
        config = self.copy_config()
        del config["scopes"]["kernels"]
        path = self.write_config(config)
        self.assertEqual(self.run_engine(CLEAN_FIXTURE, config=path), 1)
        self.assertIn("missing kernels", self.stderr)

    def test_config_rejects_unknown_scope(self):
        config = self.copy_config()
        config["scopes"]["made-up"] = ["made-up/**"]
        path = self.write_config(config)
        self.assertEqual(self.run_engine(CLEAN_FIXTURE, config=path), 1)
        self.assertIn("unknown made-up", self.stderr)

    def test_config_rejects_unknown_key(self):
        config = self.copy_config()
        config["unexpected"] = True
        path = self.write_config(config)
        self.assertEqual(self.run_engine(CLEAN_FIXTURE, config=path), 1)
        self.assertIn("Additional properties are not allowed", self.stderr)

    def test_registry_rejects_duplicate(self):
        registry = {
            "scopes": [
                {"name": "docs", "description": "One"},
                {"name": "docs", "description": "Two"},
            ]
        }
        path = self.dir / "registry.json"
        write_json(path, registry)
        with self.assertRaises(scope_guard.EngineError):
            scope_guard.load_registry(path)

    def test_invalid_repo_is_rejected(self):
        self.assertEqual(self.run_engine(CLEAN_FIXTURE, repo="bad repo"), 1)
        self.assertIn("repository must be owner/name", self.stderr)

    def test_dot_segment_repo_is_rejected(self):
        self.assertEqual(self.run_engine(CLEAN_FIXTURE, repo="owner/.."), 1)
        self.assertIn("dot segments", self.stderr)

    def test_zero_pr_is_rejected(self):
        self.assertEqual(self.run_engine(CLEAN_FIXTURE, pr=0), 1)
        self.assertIn("must be positive", self.stderr)

    def test_fixture_number_must_match(self):
        self.assertEqual(self.run_engine(CLEAN_FIXTURE, pr=999), 1)
        self.assertIn("does not match", self.stderr)

    def test_fixture_needs_pull_request_and_files(self):
        path = self.dir / "broken.json"
        write_json(path, {"files": []})
        with self.assertRaises(scope_guard.EngineError):
            scope_guard.load_fixture(path)

    def test_pagination_follows_next_link(self):
        pages = {
            "https://api.github.com/one": (
                [{"filename": "a"}],
                '<https://api.github.com/two>; rel="next"',
            ),
            "https://api.github.com/two": ([{"filename": "b"}], ""),
        }

        def fake(url, token):
            return pages[url]

        with mock.patch.object(scope_guard, "fetch_json", side_effect=fake):
            items = scope_guard.fetch_pages("https://api.github.com/one", "token")
        self.assertEqual(items, [{"filename": "a"}, {"filename": "b"}])

    def test_pagination_rejects_foreign_host(self):
        with mock.patch.object(
            scope_guard,
            "fetch_json",
            return_value=([], '<https://evil.example/next>; rel="next"'),
        ):
            with self.assertRaises(scope_guard.EngineError):
                scope_guard.fetch_pages("https://api.github.com/one", "token")


if __name__ == "__main__":
    unittest.main()
