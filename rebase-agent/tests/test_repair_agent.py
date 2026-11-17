"""Offline safety tests for the bounded repair agent tools."""

import sys
import tempfile
import subprocess
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import repair_agent


class RepairAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.diff = self.root / "input.diff"
        self.report = self.root / "report.json"
        self.diff.write_text(
            "diff --git a/src/example.cpp b/src/example.cpp\n"
            "--- a/src/example.cpp\n+++ b/src/example.cpp\n"
            "@@ -1 +1 @@\n-old\n+new\n",
            encoding="utf-8",
        )
        (self.root / "src").mkdir()
        (self.root / "src/example.cpp").write_text("old\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base"],
            check=True,
        )
        self.agent = repair_agent.Agent(self.root, self.diff, self.report)

    def tearDown(self):
        self.temp.cleanup()

    def test_rejects_traversal_and_symlink_paths(self):
        with self.assertRaisesRegex(repair_agent.AgentError, "escapes"):
            repair_agent.safe_path(self.root, "../outside")
        (self.root / "escape").symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaisesRegex(repair_agent.AgentError, "symlink"):
            repair_agent.safe_path(self.root, "escape/file")

    def test_patch_paths_reject_traversal_and_absolute_paths(self):
        with self.assertRaisesRegex(repair_agent.AgentError, "unsafe path"):
            repair_agent.validate_patch_paths(
                "diff --git a/../../outside b/../../outside\n--- a/../../outside\n+++ b/../../outside\n"
            )
        with self.assertRaisesRegex(repair_agent.AgentError, "unsafe path"):
            repair_agent.validate_patch_paths(
                "diff --git a/etc/passwd b/etc/passwd\n--- a/etc/passwd\n+++ /etc/passwd\n"
            )

    def test_patch_tool_applies_only_in_snapshot(self):
        patch = (
            "diff --git a/src/example.cpp b/src/example.cpp\n"
            "--- a/src/example.cpp\n+++ b/src/example.cpp\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        )
        result = self.agent.execute("apply_patch", {"patch": patch})
        self.assertTrue(result["applied"])
        self.assertEqual((self.root / "src/example.cpp").read_text(encoding="utf-8"), "new\n")
        self.assertTrue(self.agent.applied)

    def test_final_review_disables_patch_tool(self):
        final = repair_agent.Agent(self.root, self.diff, self.report, allow_patch=False)
        self.assertNotIn("apply_patch", [x["function"]["name"] for x in final.tools()])
        with self.assertRaisesRegex(repair_agent.AgentError, "not allowlisted"):
            final.execute("apply_patch", {"patch": "anything"})

    def test_review_cannot_finish_before_full_diff_is_read(self):
        with self.assertRaisesRegex(repair_agent.AgentError, "complete diff coverage"):
            self.agent.execute("submit_review", {
                "summary": "reviewed",
                "ready_for_validation": False,
                "findings": [],
            })
        chunk = self.agent.execute("get_diff", {"offset": 0, "limit": 8000})
        self.assertTrue(chunk["complete"])
        self.agent.execute("read_file", {"path": "src/example.cpp", "offset": 0, "limit": 12000})
        result = self.agent.execute("submit_review", {
            "summary": "reviewed",
            "ready_for_validation": False,
            "findings": [],
        })
        self.assertTrue(result["review_saved"])

    def test_tool_allowlist_rejects_arbitrary_commands(self):
        with self.assertRaisesRegex(repair_agent.AgentError, "not allowlisted"):
            self.agent.execute("shell", {"command": "rm -rf /"})


if __name__ == "__main__":
    unittest.main()
