#!/usr/bin/env python3
"""Offline policy tests for the C++ formatting and static-analysis checks."""

import json
import unittest
from pathlib import Path

import yaml

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
FORMAT_PATH = REPO_ROOT / ".clang-format"
TIDY_PATH = REPO_ROOT / ".clang-tidy"


class CppQualityWorkflowTests(unittest.TestCase):
    def load_workflow(self):
        with WORKFLOW_PATH.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def steps(self, workflow):
        return workflow["jobs"]["cpu"]["steps"]

    def step(self, workflow, name):
        for step in self.steps(workflow):
            if step.get("name") == name:
                return step
        self.fail(f"missing step: {name}")

    def test_triggers(self):
        workflow = self.load_workflow()
        triggers = workflow.get("on")
        if triggers is None:
            triggers = workflow.get(True)
        self.assertEqual(triggers["push"]["branches"], ["main"])
        self.assertIn("pull_request", triggers)
        self.assertIn("workflow_dispatch", triggers)

    def test_installs_pinned_tools(self):
        script = self.step(self.load_workflow(), "Install C++ quality tools")["run"]
        self.assertIn("clang-format==22.1.8", script)
        self.assertIn("clang-tidy==22.1.8", script)

    def test_formatting_covers_cpp_and_cuda_files(self):
        script = self.step(self.load_workflow(), "Check C++ and CUDA formatting")["run"]
        self.assertIn("git ls-files -z", script)
        for pattern in ("'*.cpp'", "'*.h'", "'*.cu'", "'*.cuh'"):
            self.assertIn(pattern, script)
        self.assertIn("xargs -0 clang-format --dry-run --Werror", script)

    def test_exports_compile_database(self):
        script = self.step(self.load_workflow(), "Configure (CPU only)")["run"]
        self.assertIn("-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", script)

    def test_tidy_uses_host_compile_database_after_build(self):
        workflow = self.load_workflow()
        script = self.step(workflow, "Static analysis (host C++ only)")["run"]
        self.assertIn("clang-tidy --config-file=.clang-tidy", script)
        self.assertIn("--warnings-as-errors='*'", script)
        self.assertIn("-p build-cpu tests/test_host.cpp", script)
        self.assertNotIn(".cu", script)
        names = [step.get("name") for step in self.steps(workflow)]
        self.assertLess(names.index("Build"), names.index("Static analysis (host C++ only)"))

    def test_workflow_has_no_secrets(self):
        self.assertNotIn("secrets.", json.dumps(self.load_workflow()))

    def test_gpu_job_remains_optional_and_self_hosted(self):
        workflow = self.load_workflow()
        gpu = workflow["jobs"]["gpu"]
        self.assertEqual(gpu["if"], "vars.CUDA_CI_ENABLED == 'true'")
        self.assertIn("self-hosted", gpu["runs-on"])
        self.assertIn("nvidia", gpu["runs-on"])
        self.assertIn("cuda", gpu["runs-on"])

    def test_clang_format_config(self):
        with FORMAT_PATH.open(encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        self.assertEqual(config["BasedOnStyle"], "LLVM")
        self.assertEqual(config["ColumnLimit"], 90)
        self.assertEqual(config["IndentWidth"], 2)
        self.assertEqual(config["PointerAlignment"], "Left")
        self.assertEqual(config["SpacesBeforeTrailingComments"], 2)
        self.assertEqual(config["SortIncludes"], "Never")

    def test_clang_tidy_config(self):
        with TIDY_PATH.open(encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        checks = config["Checks"]
        for group in ("clang-analyzer-*", "bugprone-*", "performance-*"):
            self.assertIn(group, checks)
        self.assertEqual(config["WarningsAsErrors"], "*")
        self.assertEqual(config["HeaderFilterRegex"], "(include|tests)/.*")


if __name__ == "__main__":
    unittest.main()
