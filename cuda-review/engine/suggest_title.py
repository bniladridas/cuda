#!/usr/bin/env python3
"""Generate a conservative PR title suggestion without modifying the PR."""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_DIFF_BYTES = 120000


def build_prompt(current_title, body, guidance, diff):
    return (
        "Suggest one concise GitHub pull request title for this change. "
        "Follow the repository's title rules exactly when guidance is present. "
        "Preserve any required scope syntax. Use the actual diff, not guesses. "
        "Do not add a body, explanation, quotes, markdown, or alternatives. "
        "Prefer a clear imperative summary. Return only the title.\n\n"
        "Current title:\n" + current_title[:300] +
        "\n\nPR description:\n" + body[:5000] +
        "\n\nRepository title guidance:\n" + guidance[:12000] +
        "\n\nComplete diff (bounded):\n" + diff
    )


def validate_title(value):
    if not isinstance(value, str):
        raise ValueError("model did not return a title string")
    title = value.strip().strip("`").strip('"').strip("'")
    if not 10 <= len(title) <= 100 or "\n" in title or "\r" in title:
        raise ValueError("suggested title must be a single line of 10 to 100 characters")
    if any(ord(char) < 32 for char in title):
        raise ValueError("suggested title contains control characters")
    if title.startswith(("fixup!", "squash!", "Revert ")):
        raise ValueError("suggested title is not suitable for a PR")
    return title


def main():
    diff = Path(os.environ["PR_DIFF_PATH"]).read_text(encoding="utf-8", errors="replace")
    if not diff.strip() or len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise SystemExit("diff is empty or exceeds the title-review size limit")
    guidance_path = Path("CONTRIBUTING.md")
    guidance = guidance_path.read_text(encoding="utf-8") if guidance_path.is_file() else ""
    prompt = build_prompt(os.environ.get("PR_TITLE", ""), os.environ.get("PR_BODY", ""), guidance, diff)
    payload = {
        "model": os.environ.get("OPENROUTER_MODEL") or "openrouter/free",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 120,
    }
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/" + os.environ["GITHUB_REPOSITORY"],
            "X-Title": "CUDA Review",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit("title suggestion request failed: " + str(exc)) from exc
    try:
        title = validate_title(result["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SystemExit("invalid title suggestion: " + str(exc)) from exc
    Path("suggested-title.txt").write_text(title + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
