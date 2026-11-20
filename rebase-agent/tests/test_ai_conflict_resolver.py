import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from ai_conflict_resolver import (
    ResolutionError,
    safe_conflict_path,
    validate_replacements,
)


class SafeConflictPathTests(unittest.TestCase):
    def test_accepts_repository_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.assertEqual(safe_conflict_path(root, "src/kernel.cu"), root / "src/kernel.cu")

    def test_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ResolutionError):
                safe_conflict_path(Path(directory).resolve(), "../outside")

    def test_rejects_absolute_path(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ResolutionError):
                safe_conflict_path(Path(directory).resolve(), "/tmp/outside")

    def test_rejects_git_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ResolutionError):
                safe_conflict_path(Path(directory).resolve(), ".git/config")

    def test_rejects_symlink_component(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            outside = root.parent / (root.name + "-outside")
            outside.mkdir()
            try:
                (root / "linked").symlink_to(outside, target_is_directory=True)
                with self.assertRaises(ResolutionError):
                    safe_conflict_path(root, "linked/file.txt")
            finally:
                outside.rmdir()


class ModelReplacementValidationTests(unittest.TestCase):
    def test_requires_exact_conflict_path_coverage(self):
        answer = {
            "needs_human": False,
            "files": [{"path": "src/kernel.cu", "content": "int main() {}\\n"}],
        }
        self.assertEqual(
            validate_replacements(["src/kernel.cu"], answer),
            {"src/kernel.cu": "int main() {}\\n"},
        )

    def test_rejects_unrequested_path(self):
        answer = {
            "needs_human": False,
            "files": [{"path": "../outside", "content": "bad"}],
        }
        with self.assertRaises(ResolutionError):
            validate_replacements(["src/kernel.cu"], answer)

    def test_rejects_remaining_conflict_markers(self):
        answer = {
            "needs_human": False,
            "files": [
                {
                    "path": "src/kernel.cu",
                    "content": "<<<<<<< ours\\nleft\\n=======\\nright\\n>>>>>>> theirs\\n",
                }
            ],
        }
        with self.assertRaises(ResolutionError):
            validate_replacements(["src/kernel.cu"], answer)

    def test_requires_human_on_ambiguous_model_response(self):
        answer = {"needs_human": True, "files": []}
        with self.assertRaises(ResolutionError):
            validate_replacements(["src/kernel.cu"], answer)


if __name__ == "__main__":
    unittest.main()
