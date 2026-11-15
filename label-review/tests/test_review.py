import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "label-review" / "engine"))

import review  # noqa: E402

TRACKED = {
    ".github/workflows/ci.yml",
    "CMakeLists.txt",
    "README.md",
    "benchmarks/bench.h",
    "cmake/CudaArch.cmake",
    "docs/methodology.md",
    "include/cuda_kernels/vecadd.cuh",
    "runners/test.sh",
    "src/reduce.cu",
    "src/vecadd.cu",
    "tests/CMakeLists.txt",
    "tests/test_reduce.cpp",
}

CONFIG = {
    "version": 1,
    "components": {
        "ci": {"paths": [".github/workflows/**"]},
        "runners": {"paths": ["runners/**"]},
        "build": {"paths": ["CMakeLists.txt", "cmake/**"]},
        "benchmark": {"paths": ["benchmarks/**"]},
        "tests": {"paths": ["tests/**"]},
        "kernels": {"paths": ["src/**", "include/**"]},
        "documentation": {"paths": ["docs/**", "README.md"]},
    },
    "model_proposed": {"needs-gpu": "the change needs an NVIDIA GPU to build or run"},
    "human_only": ["cpu-verified"],
}

KNOWN = review.applicable_labels(CONFIG) | {"cpu-verified", "bug", "enhancement"}


def make_issue(text="", labels=(), state="OPEN", number=7):
    lines = text.splitlines()
    return {
        "number": number,
        "title": lines[0] if lines else "",
        "body": "\n".join(lines[1:]) if len(lines) > 1 else "",
        "state": state,
        "labels": sorted(labels),
        "url": "",
    }


def make_artifact(issue, adds=(), removes=(), components=None, mode="propose", text=None, verdicts=None, status="ok"):
    if components is None:
        components = review.components_from_text(text or review.issue_text(issue), CONFIG, TRACKED)
    model = {"name": "openrouter/free", "status": status, "verdicts": verdicts or {}, "problems": {}}
    return review.build_artifact(mode, issue, CONFIG, adds, removes, components, model)


class GlobTests(unittest.TestCase):
    def test_star_stays_inside_one_segment(self):
        self.assertTrue(review.glob_regex("docs/*.md").match("docs/methodology.md"))
        self.assertFalse(review.glob_regex("docs/*.md").match("docs/sub/page.md"))

    def test_double_star_matches_any_depth(self):
        pattern = review.glob_regex(".github/workflows/**")
        self.assertTrue(pattern.match(".github/workflows/ci.yml"))
        self.assertTrue(pattern.match(".github/workflows/sub/x.yml"))
        self.assertFalse(pattern.match(".github/ci.yml"))

    def test_prefix_glob_needs_a_trailing_segment(self):
        self.assertTrue(review.glob_regex("src/**").match("src/vecadd.cu"))
        self.assertFalse(review.glob_regex("src/**").match("src"))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, data):
        import yaml

        path = Path(self.tmp.name) / "config.yml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return str(path)

    def test_valid_config_loads(self):
        self.assertEqual(review.load_config(self.write(CONFIG))["version"], 1)

    def test_unknown_key_is_rejected(self):
        data = dict(CONFIG, extra=1)
        with self.assertRaises(review.EngineError):
            review.load_config(self.write(data))

    def test_label_with_two_roles_is_rejected(self):
        data = dict(CONFIG, model_proposed={"kernels": "criterion"})
        with self.assertRaises(review.EngineError):
            review.load_config(self.write(data))

    def test_absolute_pattern_is_rejected(self):
        data = {
            "version": 1,
            "components": {"kernels": {"paths": ["/src/**"]}},
        }
        with self.assertRaises(review.EngineError):
            review.load_config(self.write(data))

    def test_empty_criterion_is_rejected(self):
        data = dict(CONFIG, model_proposed={"needs-gpu": "  "})
        with self.assertRaises(review.EngineError):
            review.load_config(self.write(data))

    def test_missing_label_is_rejected(self):
        with self.assertRaises(review.EngineError):
            review.check_config_labels(CONFIG, KNOWN - {"needs-gpu"})


class PathTests(unittest.TestCase):
    def test_file_path_maps_to_component(self):
        found = review.components_from_text("The bug is in `src/vecadd.cu`.", CONFIG, TRACKED)
        self.assertEqual(found, {"kernels": ["src/vecadd.cu"]})

    def test_directory_path_expands_to_tracked_files(self):
        found = review.components_from_text("Check `include/cuda_kernels`.", CONFIG, TRACKED)
        self.assertEqual(found, {"kernels": ["include/cuda_kernels/vecadd.cuh"]})

    def test_symbol_suffix_is_the_file(self):
        found = review.components_from_text("`benchmarks/bench.h::time_launches` is wrong.", CONFIG, TRACKED)
        self.assertEqual(found, {"benchmark": ["benchmarks/bench.h"]})

    def test_bare_directory_name_is_not_a_path(self):
        text = "Component labels such as `ci`, `runners`, `tests` and `kernels`."
        self.assertEqual(review.components_from_text(text, CONFIG, TRACKED), {})

    def test_trailing_slash_marks_a_directory(self):
        found = review.components_from_text("Run the `runners/` scripts.", CONFIG, TRACKED)
        self.assertEqual(found, {"runners": sorted(path for path in TRACKED if path.startswith("runners/"))})

    def test_unknown_path_proposes_nothing(self):
        self.assertEqual(review.components_from_text("See `no/such/file.py`.", CONFIG, TRACKED), {})

    def test_plain_text_proposes_nothing(self):
        self.assertEqual(review.components_from_text("The reduce kernel is slow.", CONFIG, TRACKED), {})

    def test_root_cmake_is_build_only(self):
        found = review.components_from_text("`CMakeLists.txt` needs a flag.", CONFIG, TRACKED)
        self.assertEqual(found, {"build": ["CMakeLists.txt"]})

    def test_tests_cmake_is_tests_only(self):
        found = review.components_from_text("`tests/CMakeLists.txt` registers the suite.", CONFIG, TRACKED)
        self.assertEqual(found, {"tests": ["tests/CMakeLists.txt"]})


class ModelTests(unittest.TestCase):
    TEXT = "Title\n\nThe kernel must be compiled and run on an NVIDIA GPU."

    def raw(self, **overrides):
        item = {"apply": True, "confidence": "high", "evidence": "compiled and run on an NVIDIA GPU"}
        item.update(overrides)
        return {"labels": {"needs-gpu": item}}

    def test_verbatim_quote_is_accepted(self):
        verdicts, problems = review.validate_verdicts(self.raw(), CONFIG["model_proposed"], self.TEXT)
        self.assertEqual(problems, {})
        self.assertTrue(verdicts["needs-gpu"]["apply"])

    def test_quote_not_in_issue_is_rejected(self):
        verdicts, problems = review.validate_verdicts(
            self.raw(evidence="the author asked for a label"), CONFIG["model_proposed"], self.TEXT
        )
        self.assertEqual(verdicts, {})
        self.assertIn("needs-gpu", problems)

    def test_low_confidence_becomes_uncertain(self):
        verdicts, problems = review.validate_verdicts(self.raw(confidence="low"), CONFIG["model_proposed"], self.TEXT)
        model = {"status": "ok", "verdicts": verdicts, "problems": problems}
        adds, uncertain = review.select_model_labels(CONFIG["model_proposed"], model)
        self.assertEqual(adds, [])
        self.assertEqual(uncertain, ["needs-gpu"])

    def test_not_applicable_is_not_uncertain(self):
        verdicts, problems = review.validate_verdicts(self.raw(apply=False), CONFIG["model_proposed"], self.TEXT)
        model = {"status": "ok", "verdicts": verdicts, "problems": problems}
        adds, uncertain = review.select_model_labels(CONFIG["model_proposed"], model)
        self.assertEqual((adds, uncertain), ([], []))

    def test_failed_model_makes_every_label_uncertain(self):
        model = {"status": "failed", "detail": "timeout", "verdicts": {}, "problems": {}}
        adds, uncertain = review.select_model_labels(CONFIG["model_proposed"], model)
        self.assertEqual((adds, uncertain), ([], ["needs-gpu"]))

    def test_malformed_response_is_an_error(self):
        with self.assertRaises(review.EngineError):
            review.validate_verdicts({"nope": True}, CONFIG["model_proposed"], self.TEXT)


class DiffTests(unittest.TestCase):
    def test_correction_removes_stale_taxonomy_label(self):
        adds, removes = review.correction_diff(["needs-gpu", "bug", "cpu-verified"], [], CONFIG)
        self.assertEqual(adds, [])
        self.assertEqual(removes, ["needs-gpu"])

    def test_correction_preserves_human_and_foreign_labels(self):
        adds, removes = review.correction_diff(["needs-gpu", "bug", "cpu-verified", "documentation"], ["kernels"], CONFIG)
        self.assertEqual(adds, ["kernels"])
        self.assertEqual(removes, ["documentation", "needs-gpu"])

    def test_correction_does_not_add_present_labels(self):
        adds, removes = review.correction_diff(["kernels"], ["kernels"], CONFIG)
        self.assertEqual((adds, removes), ([], []))


class VerifyTests(unittest.TestCase):
    def setUp(self):
        os.environ["GITHUB_REPOSITORY"] = "example/repo"

    def test_valid_proposal_verifies(self):
        issue = make_issue("Bug in `src/vecadd.cu`.")
        artifact = make_artifact(issue, adds=["kernels"])
        adds, removes, problems = review.verify(artifact, issue, CONFIG, "propose", TRACKED)
        self.assertEqual((adds, removes, problems), (["kernels"], [], []))

    def test_human_only_addition_is_rejected(self):
        issue = make_issue("Bug in `src/vecadd.cu`.")
        artifact = make_artifact(issue, adds=["kernels", "cpu-verified"])
        _, _, problems = review.verify(artifact, issue, CONFIG, "propose", TRACKED)
        self.assertTrue(any("human-only" in problem for problem in problems))

    def test_unknown_label_is_rejected(self):
        issue = make_issue("Bug in `src/vecadd.cu`.")
        artifact = make_artifact(issue, adds=["kernels", "bug"])
        _, _, problems = review.verify(artifact, issue, CONFIG, "propose", TRACKED)
        self.assertTrue(any("not a label this configuration manages" in problem for problem in problems))

    def test_stale_components_are_rejected(self):
        issue = make_issue("Bug in `src/vecadd.cu`.")
        artifact = make_artifact(issue, adds=["kernels"], components={"benchmark": ["benchmarks/bench.h"]})
        _, _, problems = review.verify(artifact, issue, CONFIG, "propose", TRACKED)
        self.assertTrue(any("no longer match the issue text" in problem for problem in problems))

    def test_closed_issue_is_rejected(self):
        issue = make_issue("Bug in `src/vecadd.cu`.", state="CLOSED")
        artifact = make_artifact(issue, adds=["kernels"])
        _, _, problems = review.verify(artifact, issue, CONFIG, "propose", TRACKED)
        self.assertTrue(any("not open" in problem for problem in problems))

    def test_taxonomy_drift_is_rejected(self):
        issue = make_issue("Bug in `src/vecadd.cu`.")
        artifact = make_artifact(issue, adds=["kernels"])
        artifact["taxonomy"].append("needs-review")
        _, _, problems = review.verify(artifact, issue, CONFIG, "propose", TRACKED)
        self.assertTrue(any("configuration changed" in problem for problem in problems))

    def test_model_label_evidence_must_still_match(self):
        issue = make_issue("Compile `src/vecadd.cu` on the GPU.")
        verdicts = {"needs-gpu": {"apply": True, "confidence": "high", "evidence": "on the GPU"}}
        artifact = make_artifact(issue, adds=["kernels", "needs-gpu"], verdicts=verdicts)
        _, _, problems = review.verify(artifact, issue, CONFIG, "propose", TRACKED)
        self.assertEqual(problems, [])
        edited = make_issue("Compile `src/vecadd.cu` on a laptop.")
        _, _, problems = review.verify(artifact, edited, CONFIG, "propose", TRACKED)
        self.assertTrue(any("evidence for `needs-gpu`" in problem for problem in problems))

    def test_proposal_may_not_remove(self):
        issue = make_issue("Bug in `src/vecadd.cu`.")
        artifact = make_artifact(issue, adds=["kernels"], removes=[])
        artifact["labels"]["remove"] = ["documentation"]
        _, _, problems = review.verify(artifact, issue, CONFIG, "propose", TRACKED)
        self.assertTrue(any("may not remove" in problem for problem in problems))

    def test_valid_correction_verifies(self):
        issue = make_issue("The reduce kernel is slow.", labels=["needs-gpu", "bug"])
        artifact = make_artifact(issue, adds=[], removes=["needs-gpu"], mode="correct")
        adds, removes, problems = review.verify(artifact, issue, CONFIG, "correct", TRACKED)
        self.assertEqual((adds, removes, problems), ([], ["needs-gpu"], []))

    def test_changed_labels_abort_correction(self):
        issue = make_issue("The reduce kernel is slow.", labels=["needs-gpu", "bug"])
        artifact = make_artifact(issue, adds=[], removes=["needs-gpu"], mode="correct")
        edited = make_issue("The reduce kernel is slow.", labels=["needs-gpu", "bug", "enhancement"])
        _, _, problems = review.verify(artifact, edited, CONFIG, "correct", TRACKED)
        self.assertTrue(any("labels changed after the proposal" in problem for problem in problems))
        self.assertTrue(any("label state" in problem for problem in problems))

    def test_removing_absent_label_is_rejected(self):
        issue = make_issue("The reduce kernel is slow.", labels=["bug"])
        artifact = make_artifact(issue, adds=[], removes=["needs-gpu"], mode="correct")
        _, _, problems = review.verify(artifact, issue, CONFIG, "correct", TRACKED)
        self.assertTrue(any("does not have" in problem for problem in problems))


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        os.environ["GITHUB_REPOSITORY"] = "example/repo"
        os.environ.pop("OPENROUTER_API_KEY", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        import yaml

        (self.dir / "config.yml").write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
        (self.dir / "labels.json").write_text(json.dumps(sorted(KNOWN)), encoding="utf-8")

    def write_issue(self, data):
        path = self.dir / "issue.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_propose_then_verify(self):
        issue = make_issue("Crash in `src/vecadd.cu`.\n\nIt must be compiled on an NVIDIA GPU.")
        issue_json = self.write_issue(issue)
        code = review.main(
            [
                "propose",
                "--issue", "7",
                "--config", str(self.dir / "config.yml"),
                "--comment-out", str(self.dir / "comment.md"),
                "--artifact", str(self.dir / "artifact.json"),
                "--issue-json", issue_json,
                "--labels-json", str(self.dir / "labels.json"),
            ]
        )
        self.assertEqual(code, 0)
        artifact = json.loads((self.dir / "artifact.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact["labels"]["add"], ["kernels"])
        comment = (self.dir / "comment.md").read_text(encoding="utf-8")
        self.assertIn("Needs human classification", comment)
        self.assertIn("Nothing has been applied", comment)
        code = review.main(
            [
                "verify",
                "--issue", "7",
                "--mode", "propose",
                "--artifact", str(self.dir / "artifact.json"),
                "--config", str(self.dir / "config.yml"),
                "--issue-json", issue_json,
                "--labels-json", str(self.dir / "labels.json"),
                "--github-output", str(self.dir / "output.txt"),
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn("additions=kernels", (self.dir / "output.txt").read_text(encoding="utf-8"))

    def test_correction_then_verify_after_human_edit(self):
        issue = make_issue("The reduce kernel is slow.", labels=["needs-gpu", "bug", "cpu-verified"])
        issue_json = self.write_issue(issue)
        code = review.main(
            [
                "correct",
                "--issue", "7",
                "--config", str(self.dir / "config.yml"),
                "--comment-out", str(self.dir / "comment.md"),
                "--artifact", str(self.dir / "artifact.json"),
                "--issue-json", issue_json,
                "--labels-json", str(self.dir / "labels.json"),
            ]
        )
        self.assertEqual(code, 0)
        artifact = json.loads((self.dir / "artifact.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact["labels"]["remove"], ["needs-gpu"])
        comment = (self.dir / "comment.md").read_text(encoding="utf-8")
        self.assertIn("cpu-verified", comment)
        verify_args = [
            "verify",
            "--issue", "7",
            "--mode", "correct",
            "--artifact", str(self.dir / "artifact.json"),
            "--config", str(self.dir / "config.yml"),
            "--labels-json", str(self.dir / "labels.json"),
        ]
        self.assertEqual(review.main(verify_args + ["--issue-json", issue_json]), 0)
        edited = make_issue("The reduce kernel is slow.", labels=["needs-gpu", "bug", "cpu-verified", "enhancement"])
        self.assertEqual(review.main(verify_args + ["--issue-json", self.write_issue(edited)]), 1)


if __name__ == "__main__":
    unittest.main()
