import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from ai_conflict_resolver import (
    ResolutionError,
    configured_max_rounds,
    extract_message_text,
    git,
    safe_conflict_path,
    request_resolution,
    validate_replacements,
)


class ConfiguredRoundLimitTests(unittest.TestCase):
    def test_default_is_six_rounds(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(configured_max_rounds(), 6)

    def test_accepts_configured_limit(self):
        self.assertEqual(configured_max_rounds("8"), 8)

    def test_rejects_out_of_range_limit(self):
        for value in ("0", "9", "many"):
            with self.subTest(value=value):
                with self.assertRaises(ResolutionError):
                    configured_max_rounds(value)


class GitCredentialIsolationTests(unittest.TestCase):
    def test_git_subprocess_does_not_receive_model_key(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-secret"}):
            with patch(
                "ai_conflict_resolver.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as run:
                git(Path("/tmp/repo"), ["status"])
        child_env = run.call_args.kwargs["env"]
        self.assertNotIn("OPENROUTER_API_KEY", child_env)
        self.assertEqual(child_env["GIT_TERMINAL_PROMPT"], "0")


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


class MessageContentExtractionTests(unittest.TestCase):
    def test_accepts_plain_text_content(self):
        text, diagnostic = extract_message_text('{"files": []}')
        self.assertEqual(text, '{"files": []}')
        self.assertEqual(diagnostic["content_type"], "string")

    def test_accepts_text_blocks(self):
        text, diagnostic = extract_message_text(
            [
                {"type": "text", "text": '{"needs_human": false,'},
                {"type": "text", "text": '"files": []}'},
            ]
        )
        self.assertEqual(text, '{"needs_human": false,"files": []}')
        self.assertEqual(diagnostic["block_types"], ["text", "text"])

    def test_ignores_non_text_blocks_without_coercing_them(self):
        text, diagnostic = extract_message_text(
            [
                {"type": "image", "image_url": {"url": "private"}},
                {"type": "text", "text": "answer"},
            ]
        )
        self.assertEqual(text, "answer")
        self.assertEqual(diagnostic["block_types"], ["image", "text"])

    def test_reports_empty_or_unsupported_content(self):
        for content in (None, [], [{"type": "image"}], {"reasoning": "hidden"}):
            with self.subTest(content_type=type(content).__name__):
                text, diagnostic = extract_message_text(content)
                self.assertIsNone(text)
                self.assertTrue(diagnostic["content_type"])


class ProviderRetryTests(unittest.TestCase):
    def test_retries_empty_provider_response_with_provider_exclusion(self):
        responses = [
            {
                "model": "openrouter/free",
                "provider": "Nvidia",
                "choices": [{"message": {"content": None}, "finish_reason": "length"}],
            },
            {
                "model": "openrouter/free",
                "provider": "Other",
                "choices": [
                    {
                        "message": {"content": '{"needs_human": false, "summary": "resolved", "files": []}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 12},
            },
        ]
        encoded = [json.dumps(item).encode("utf-8") for item in responses]
        with patch("ai_conflict_resolver.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.side_effect = encoded
            answer, metadata = request_resolution([], "test-token")

        self.assertFalse(answer["needs_human"])
        self.assertEqual(metadata["ignored_providers"], ["nvidia"])
        self.assertEqual(len(metadata["attempts"]), 2)
        first_request = urlopen.call_args_list[0].args[0]
        first_payload = json.loads(first_request.data.decode("utf-8"))
        system_prompt = first_payload["messages"][0]["content"]
        self.assertIn("CMake add_library source lists", system_prompt)
        self.assertIn("combine independent source additions", system_prompt)
        self.assertIn("require semantic review", system_prompt)
        retry_request = urlopen.call_args_list[1].args[0]
        retry_payload = json.loads(retry_request.data.decode("utf-8"))
        self.assertEqual(retry_payload["provider"]["ignore"], ["nvidia"])


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
