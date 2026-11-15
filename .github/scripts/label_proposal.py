#!/usr/bin/env python3
"""Propose component labels for a new issue and assess whether it needs a GPU.

Component labels are a deterministic lookup: the issue text is scanned for
repository paths in backticks, each candidate is checked against `git ls-files`,
and only real paths count. No model is involved in that decision.

The model is asked one question only: does finishing this issue require an
NVIDIA device? It must quote evidence from the issue. Anything unavailable,
malformed or low confidence fails closed to "needs human classification".

`cpu-verified` and `gpu-verified` are never proposed. They record evidence that
this workflow cannot see, so no output of this script may assert them.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

# Labels this workflow may ever propose. Anything else in a model response or
# an artifact is rejected rather than trimmed, so a changed response shape is
# visible instead of silently narrowed.
COMPONENT_LABELS = (
    "ci",
    "runners",
    "build",
    "benchmark",
    "tests",
    "kernels",
    "documentation",
)
PROPOSABLE = set(COMPONENT_LABELS) | {"needs-gpu"}

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SPAN = re.compile(r"`([^`\n]{1,200})`")


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], check=True, capture_output=True, text=True
    ).stdout
    return set(out.splitlines())


def component_for(path):
    base = path.rsplit("/", 1)[-1]
    # A CMakeLists.txt is build configuration wherever it sits, including
    # tests/ and kernels/, which take precedence over the directory rule.
    if base == "CMakeLists.txt":
        return "build"
    rules = (
        (".github/workflows/", "ci"),
        ("runners/", "runners"),
        ("tests/", "tests"),
        ("benchmarks/", "benchmark"),
        ("cmake/", "build"),
        ("src/", "kernels"),
        ("include/", "kernels"),
        ("docs/", "documentation"),
    )
    for prefix, label in rules:
        if path.startswith(prefix):
            return label
    if path in ("README.md", ".github/CONTRIBUTING.md"):
        return "documentation"
    return None


def expand(token, tracked):
    token = token.strip()
    if token.startswith("./"):
        token = token[2:]
    # Symbols are often written as `path::symbol`, which names the file plus a
    # member. The file is the part that identifies an area.
    token = token.split("::", 1)[0]
    if not token or token.startswith("/") or " " in token:
        return []
    if token in tracked:
        return [token]
    if token.endswith("/") and any(f.startswith(token) for f in tracked):
        return sorted(f for f in tracked if f.startswith(token))
    return []


def propose_components(text, tracked):
    """Map explicit repository paths in the text to component labels.

    Returns {label: [paths]} sorted, or {} when the text names no real path.
    """
    found = {}
    for raw in SPAN.findall(text):
        for path in expand(raw, tracked):
            label = component_for(path)
            if label:
                found.setdefault(label, set()).add(path)
    return {k: sorted(v) for k, v in found.items()}


def prompt_for(title, body):
    return (
        "You classify a software issue. Decide only whether finishing the work "
        "genuinely requires an NVIDIA GPU to compile or run. Reading code, "
        "editing documentation or a host-only script does not.\n\n"
        "Answer with a JSON object and nothing else: "
        '{"needs_gpu": true|false, "evidence": "<verbatim quote from the issue '
        'that justifies the answer>", "reason": "<one sentence>", '
        '"confidence": "low"|"medium"|"high"}.\n\n'
        f"Title: {title}\n\nIssue:\n{body}"
    )


def call_model(title, body, api_key, use_schema=True):
    payload = {
        # Free router only. A paid model is a reviewed change to this line,
        # not a configuration toggle.
        "model": "openrouter/free",
        "messages": [{"role": "user", "content": prompt_for(title, body)}],
        "temperature": 0,
        # Fail closed if every free provider retains prompts for training.
        "provider": {"data_collection": "deny"},
    }
    if use_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "needs_gpu",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["needs_gpu", "evidence", "reason", "confidence"],
                    "properties": {
                        "needs_gpu": {"type": "boolean"},
                        "evidence": {"type": "string"},
                        "reason": {"type": "string"},
                        "confidence": {"enum": ["low", "medium", "high"]},
                    },
                },
            },
        }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def assess(title, body, api_key):
    """Return (needs_gpu, evidence, reason, confidence, model_id, note)."""
    if not api_key:
        return None, "", "", "", "", "no API key configured"
    try:
        data = call_model(title, body, api_key)
    except urllib.error.HTTPError as exc:
        # Some free models reject structured output. Retry once without the
        # schema; the response is still validated below, so this adds no trust.
        if exc.code in (400, 422):
            try:
                data = call_model(title, body, api_key, use_schema=False)
            except Exception as inner:  # noqa: BLE001
                return None, "", "", "", "", f"request failed: {inner}"
        else:
            return None, "", "", "", "", f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return None, "", "", "", "", f"request failed: {exc}"

    model_id = data.get("model", "")
    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except Exception:  # noqa: BLE001
        return None, "", "", "", model_id, "response was not JSON"

    if not isinstance(parsed, dict):
        return None, "", "", "", model_id, "response was not an object"
    verdict = parsed.get("needs_gpu")
    evidence = parsed.get("evidence") or ""
    reason = parsed.get("reason") or ""
    confidence = parsed.get("confidence")
    if not isinstance(verdict, bool):
        return None, "", "", "", model_id, "needs_gpu was not a boolean"
    if confidence not in ("low", "medium", "high"):
        return None, "", "", "", model_id, "confidence was not a known value"
    if verdict and not evidence.strip():
        return None, "", "", "", model_id, "needs_gpu was true with no evidence"
    if confidence == "low":
        return None, evidence, reason, confidence, model_id, "confidence was low"
    return verdict, evidence, reason, confidence, model_id, ""


def build_proposal(issue, title, body, components, verdict, evidence, reason,
                   confidence, model_id, note):
    labels = list(components)
    if verdict is True:
        labels.append("needs-gpu")
    lines = [f"## Label proposal for #{issue}", ""]
    lines.append("**Nothing has been applied.** Review this, then approve the "
                 "apply job in the Actions run if it is correct.")
    lines.append("")
    lines.append("### Component labels (from paths named in the issue)")
    if components:
        for label in sorted(components):
            paths = ", ".join(f"`{p}`" for p in components[label])
            lines.append(f"- `{label}` from {paths}")
    else:
        lines.append("- None: the issue text names no tracked repository path.")
    lines.append("")
    lines.append("### GPU requirement")
    if verdict is True:
        lines.append(f"- `needs-gpu`: yes, confidence {confidence}.")
        lines.append(f"- Evidence: {evidence}")
        lines.append(f"- Reason: {reason}")
    elif verdict is False:
        lines.append(f"- `needs-gpu`: no, confidence {confidence}.")
        lines.append(f"- Reason: {reason}")
    else:
        lines.append("- Needs human classification: " + (note or "no verdict."))
        lines.append("- No `needs-gpu` label will be applied.")
    if model_id:
        lines.append(f"- Model reported by the API: `{model_id}`")
    lines.append("")
    lines.append("`cpu-verified` and `gpu-verified` are never proposed here. "
                 "They are applied by hand only, with a linked test log.")
    artifact = {
        "issue": issue,
        "components": components,
        "needs_gpu": verdict,
        "evidence": evidence,
        "reason": reason,
        "confidence": confidence,
        "model": model_id,
        "note": note,
        "proposed_labels": sorted(labels),
    }
    return "\n".join(lines), artifact


def open_issue(issue, repo_token):
    url = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/issues/{issue}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {repo_token}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def verify(artifact_path, issue):
    """Revalidate after approval. Raises SystemExit on any mismatch."""
    with open(artifact_path, encoding="utf-8") as fh:
        artifact = json.load(fh)
    if artifact.get("issue") != issue:
        sys.exit(f"artifact is for issue {artifact.get('issue')}, not {issue}")

    labels = artifact.get("proposed_labels") or []
    rejected = [l for l in labels if l not in PROPOSABLE]
    if rejected:
        sys.exit(f"artifact proposes labels this workflow may not apply: {rejected}")

    live = open_issue(issue, os.environ["GITHUB_TOKEN"])
    if live.get("state") != "open":
        sys.exit(f"issue {issue} is {live.get('state')}, not open")

    # The issue may have been edited between proposal and approval. Recompute
    # the deterministic half and require it to still match.
    text = f"{live.get('title') or ''}\n{live.get('body') or ''}"
    fresh = propose_components(text, tracked_files())
    if fresh != artifact.get("components"):
        sys.exit(
            "component proposal no longer matches the issue text; "
            f"was {artifact.get('components')}, now {fresh}"
        )
    print(",".join(labels))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("propose", "verify"))
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--body-file", default="")
    ap.add_argument("--artifact", default="")
    ap.add_argument("--comment-out", default="")
    ap.add_argument("--skip-model", action="store_true")
    args = ap.parse_args()

    if args.mode == "verify":
        verify(args.artifact, args.issue)
        return

    title = args.title or os.environ.get("ISSUE_TITLE", "")
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    else:
        body = os.environ.get("ISSUE_BODY", "")

    components = propose_components(f"{title}\n{body}", tracked_files())
    if args.skip_model:
        verdict, evidence, reason, confidence, model_id, note = (
            None, "", "", "", "", "model skipped")
    else:
        verdict, evidence, reason, confidence, model_id, note = assess(
            title, body, os.environ.get("OPENROUTER_API_KEY", ""))

    comment, artifact = build_proposal(
        args.issue, title, body, components, verdict, evidence, reason,
        confidence, model_id, note)

    if args.comment_out:
        with open(args.comment_out, "w", encoding="utf-8") as fh:
            fh.write(comment)
    if args.artifact:
        with open(args.artifact, "w", encoding="utf-8") as fh:
            json.dump(artifact, fh, indent=2)
            fh.write("\n")
    print(comment)


if __name__ == "__main__":
    main()
