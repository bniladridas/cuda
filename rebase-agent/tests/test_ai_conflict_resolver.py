import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from ai_conflict_resolver import ResolutionError, safe_conflict_path


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


if __name__ == "__main__":
    unittest.main()
