"""Read-only GitHub CLI adapter that builds the Steward snapshot format."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ISSUE_REF = re.compile(r"(?<![\w/])#(\d+)\b")
DEPENDENCY_REF = re.compile(r"\b(?:depends on|blocked by|requires|dependency on)\s+#?(\d+)\b", re.I)
CRITERIA = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(?:\[[ xX]\]\s*)?(.+?)\s*$")


class SnapshotError(RuntimeError):
    pass


def run_gh(path: str, *, paginate: bool = False, runner=subprocess.run):
    command = ["gh", "api", "-H", "Accept: application/vnd.github+json"]
    if paginate:
        command += ["--paginate", "--slurp"]
    command.append(path)
    try:
        result = runner(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise SnapshotError(f"cannot execute gh: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "unknown error").strip()[:500]
        raise SnapshotError(f"GitHub API request failed for {path}: {detail}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"GitHub API returned invalid JSON for {path}") from exc
    if paginate:
        if not isinstance(value, list):
            raise SnapshotError("paginated GitHub response was not a list")
        return [item for page in value if isinstance(page, list) for item in page]
    return value


def criteria_from_body(body: str) -> list[str]:
    criteria = []
    active = False
    for line in (body or "").splitlines():
        if re.match(r"^\s*#{1,6}\s+", line):
            if active:
                break
            active = bool(re.search(r"acceptance criteria", line, re.I))
            continue
        if active:
            match = CRITERIA.match(line)
            if match:
                criteria.append(match.group(1))
    return criteria


def issue_dependencies(body: str, current: int) -> list[int]:
    return sorted({int(value) for value in DEPENDENCY_REF.findall(body or "") if int(value) != current})


def load_repository_files(root: Path) -> dict[str, str]:
    try:
        tracked = (
            subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z"],
                capture_output=True,
                text=False,
                check=True,
            )
            .stdout.decode("utf-8")
            .split("\0")
        )
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise SnapshotError(f"cannot list tracked repository files: {exc}") from exc
    result = {}
    for relative in tracked:
        if not relative or not (
            relative.endswith(".md") or (relative.startswith(".github/") and relative.endswith(".json"))
        ):
            continue
        path = root / relative
        try:
            if path.is_file() and path.stat().st_size <= 1_000_000:
                result[relative] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
    return result


def load_benchmark_results(root: Path) -> list[dict]:
    """Load recorded benchmark JSON without treating missing GPU data as success."""
    directory = root / "benchmarks" / "results"
    if not directory.exists():
        return []
    results = []
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SnapshotError(f"cannot read benchmark result {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise SnapshotError(f"benchmark result {path} must contain a JSON object")
        results.append(value)
    return results


def _labels(items):
    return sorted(item.get("name", "") for item in items or [] if item.get("name"))


def validation_run_metadata(repository: str, head_sha: str, *, runner=subprocess.run) -> dict:
    """Collect runner identity for the CI run tied to the exact validation commit."""
    if not head_sha:
        return {}
    response = run_gh(
        f"repos/{repository}/actions/workflows/ci.yml/runs?head_sha={head_sha}&per_page=5",
        runner=runner,
    )
    runs = [item for item in response.get("workflow_runs", []) if item.get("head_sha") == head_sha]
    if not runs:
        return {}
    run = runs[0]
    run_id = run.get("id")
    if not run_id:
        return {}
    jobs_response = run_gh(
        f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
        runner=runner,
    )
    base = {
        "workflow_run_id": run_id,
        "workflow_run_attempt": run.get("run_attempt"),
        "workflow": run.get("name") or "ci",
        "event": run.get("event") or "unknown",
        "workflow_run_url": run.get("html_url") or "",
    }
    result = {}
    for job in jobs_response.get("jobs", []):
        name = (job.get("name") or "").lower()
        if name == "gpu":
            kind = "gpu_runtime"
        elif name in {"cuda-compile", "cuda compile"}:
            kind = "cuda_compile"
        elif name in {"cpu", "host tests", "host-tests"}:
            kind = "host_tests"
        else:
            continue
        result[kind] = {
            **base,
            "job_id": job.get("id"),
            "job_name": job.get("name") or "",
            "runner_name": job.get("runner_name"),
            "runner_id": job.get("runner_id"),
            "runner_group_name": job.get("runner_group_name"),
            "runner_labels": list(job.get("labels") or []),
            "device_identity": "not_reported",
        }
    return result


def workflow_evidence(repository: str, workflow_file: str, *, runner=subprocess.run) -> dict:
    """Read the latest workflow run; this is execution evidence, not approval evidence."""
    response = run_gh(
        f"repos/{repository}/actions/workflows/{workflow_file}/runs?per_page=1",
        runner=runner,
    )
    runs = response.get("workflow_runs", [])
    if not runs:
        return {"state": "unavailable", "details": "No workflow run was found."}
    run = runs[0]
    status = run.get("status") or "unknown"
    conclusion = run.get("conclusion")
    if status != "completed":
        state = "pending"
    elif conclusion == "success":
        state = "success"
    elif conclusion == "skipped":
        state = "skipped"
    elif conclusion in {"failure", "cancelled", "timed_out", "action_required"}:
        state = "failure"
    else:
        state = "unknown"
    return {
        "state": state,
        "head_sha": run.get("head_sha") or "",
        "source": run.get("name") or workflow_file,
        "url": run.get("html_url") or "",
        "details": f"Workflow run status={status}, conclusion={conclusion or 'none'}. Approval is not inferred.",
    }



def pull_request_workflow_evidence(repository: str, pr_number: int, head_sha: str, workflow_file: str,
                                   artifact_name: str, *, runner=subprocess.run) -> dict:
    """Read an artifact only from a workflow run associated with this PR and exact head."""
    missing = {
        "state": "missing",
        "details": "No workflow run associated with this pull request head was found.",
    }
    if not head_sha:
        return missing
    response = run_gh(
        f"repos/{repository}/actions/workflows/{workflow_file}/runs"
        f"?event=pull_request_target&head_sha={head_sha}&per_page=100",
        runner=runner,
    )
    runs = [
        item for item in response.get("workflow_runs", [])
        if item.get("head_sha") == head_sha
        and any(int(link.get("number") or 0) == pr_number for link in item.get("pull_requests") or [])
    ]
    if not runs:
        return missing
    runs.sort(key=lambda item: (int(item.get("run_number") or 0), int(item.get("run_attempt") or 0)), reverse=True)
    run = runs[0]
    source = run.get("name") or workflow_file
    url = run.get("html_url") or ""
    result_base = {"source": f"{source} run {run.get('id')}", "url": url}
    if run.get("status") != "completed":
        return {**result_base, "state": "pending", "details": "The matching workflow run is still in progress."}
    if run.get("conclusion") != "success":
        return {**result_base, "state": "failed",
                "details": f"Matching workflow run concluded {run.get('conclusion') or 'without a conclusion'}."}

    run_id = run.get("id")
    if not isinstance(run_id, int):
        return {**result_base, "state": "malformed", "details": "Matching workflow run has no numeric ID."}
    artifacts = run_gh(f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100", runner=runner)
    matches = [
        item for item in artifacts.get("artifacts", [])
        if item.get("name") == artifact_name and not item.get("expired")
    ]
    if not matches:
        return {**result_base, "state": "missing", "details": "The matching workflow run has no retained evidence artifact."}
    artifact_id = matches[0].get("id")
    if not isinstance(artifact_id, int):
        return {**result_base, "state": "malformed", "details": "Evidence artifact has no numeric ID."}

    # gh run download follows GitHub's signed artifact redirect and extracts
    # the ZIP. No repository code from the pull request is executed.
    with tempfile.TemporaryDirectory(prefix="steward-evidence-") as temporary:
        command = ["gh", "run", "download", str(run_id), "--name", artifact_name, "--dir", temporary]
        try:
            downloaded = runner(command, capture_output=True, text=True, check=False)
        except OSError as exc:
            return {**result_base, "state": "missing", "details": f"Artifact download unavailable: {exc}"}
        if downloaded.returncode:
            detail = (downloaded.stderr or downloaded.stdout or "download failed").strip()[:300]
            return {**result_base, "state": "missing", "details": f"Artifact download failed: {detail}"}
        candidates = sorted(Path(temporary).glob("*.json"))
        if len(candidates) != 1:
            return {**result_base, "state": "malformed",
                    "details": "Expected exactly one JSON evidence file in the artifact."}
        try:
            evidence = json.loads(candidates[0].read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {**result_base, "state": "malformed", "details": f"Evidence JSON could not be read: {exc}"}
    return {**result_base, "state": "success", "evidence": evidence}



def build_snapshot(repository: str, root: Path, *, runner=subprocess.run) -> dict:
    if not re.fullmatch(r"[^/]+/[^/]+", repository):
        raise SnapshotError("repository must use owner/name form")
    repo = run_gh(f"repos/{repository}", runner=runner)
    issue_rows = run_gh(
        f"repos/{repository}/issues?state=all&per_page=100",
        paginate=True,
        runner=runner,
    )
    pr_rows = run_gh(
        f"repos/{repository}/pulls?state=all&per_page=100",
        paginate=True,
        runner=runner,
    )

    issues = []
    for item in issue_rows:
        if item.get("pull_request"):
            continue
        number = int(item["number"])
        body = item.get("body") or ""
        issues.append(
            {
                "number": number,
                "title": item.get("title") or "",
                "body": body,
                "state": item.get("state") or "unknown",
                "url": item.get("html_url") or "",
                "labels": _labels(item.get("labels")),
                "assignees": sorted(user.get("login", "") for user in item.get("assignees") or []),
                "updated_at": item.get("updated_at") or "",
                "dependency_numbers": issue_dependencies(body, number),
                "acceptance_criteria": criteria_from_body(body),
            }
        )

    pull_requests = []
    for item in pr_rows:
        number = int(item["number"])
        head_sha = (item.get("head") or {}).get("sha") or ""
        body = item.get("body") or ""
        linked = sorted({int(value) for value in ISSUE_REF.findall((item.get("title") or "") + "\n" + body)})
        checks = []
        if head_sha:
            response = run_gh(
                f"repos/{repository}/commits/{head_sha}/check-runs?per_page=100",
                runner=runner,
            )
            for check in response.get("check_runs", []):
                checks.append(
                    {
                        "name": check.get("name") or "",
                        "status": check.get("status") or "unknown",
                        "conclusion": check.get("conclusion"),
                        "head_sha": head_sha,
                        "url": check.get("html_url") or "",
                    }
                )
        pull_requests.append(
            {
                "number": number,
                "title": item.get("title") or "",
                "body": body,
                "state": item.get("state") or "unknown",
                "draft": bool(item.get("draft")),
                "url": item.get("html_url") or "",
                "head_sha": head_sha,
                "linked_issue_numbers": linked,
                "checks": checks,
                "review_decision": "unknown",
                "updated_at": item.get("updated_at") or "",
            }
        )

    default_branch = repo.get("default_branch") or ""
    branch = run_gh(f"repos/{repository}/branches/{default_branch}", runner=runner) if default_branch else {}
    observed_sha = (branch.get("commit") or {}).get("sha") or ""
    validations = []
    if observed_sha:
        response = run_gh(
            f"repos/{repository}/commits/{observed_sha}/check-runs?per_page=100",
            runner=runner,
        )
        for check in response.get("check_runs", []):
            name = (check.get("name") or "").lower()
            kind = None
            if name in {"cpu", "host tests", "host-tests"}:
                kind = "host_tests"
            elif name in {"cuda-compile", "cuda compile"}:
                kind = "cuda_compile"
            elif name == "gpu":
                kind = "gpu_runtime"
            if kind:
                conclusion = check.get("conclusion")
                state = (
                    "pending"
                    if check.get("status") != "completed"
                    else "success"
                    if conclusion == "success"
                    else "skipped"
                    if conclusion == "skipped"
                    else "failure"
                    if conclusion in {"failure", "timed_out", "action_required"}
                    else "unknown"
                )
                validations.append(
                    {
                        "kind": kind,
                        "state": state,
                        "head_sha": observed_sha,
                        "source": f"default branch {check.get('name')}",
                        "url": check.get("html_url") or "",
                        "details": conclusion or check.get("status") or "",
                    }
                )

    run_metadata = validation_run_metadata(repository, observed_sha, runner=runner) if observed_sha else {}
    for item in validations:
        item["metadata"] = run_metadata.get(item["kind"], {})

    integration_evidence = {
        "label_review": workflow_evidence(repository, "label-review.yml", runner=runner),
        "issue_landing": workflow_evidence(repository, "issue-landing.yml", runner=runner),
    }
    pull_request_integrations = {}
    for pr in pull_requests:
        number = pr["number"]
        head_sha = pr["head_sha"]
        pull_request_integrations[str(number)] = {
            "pr_confidence": pull_request_workflow_evidence(
                repository, number, head_sha, "pr-confidence.yml", "pr-confidence-evidence", runner=runner
            ),
            "pr_scope_guard": pull_request_workflow_evidence(
                repository, number, head_sha, "pr-scope-guard.yml", "pr-scope-guard-evidence", runner=runner
            ),
        }
    return {
        "repository": repository,
        "head_sha": observed_sha,
        "integration_evidence": integration_evidence,
        "pull_request_integrations": pull_request_integrations,
        "issues": issues,
        "pull_requests": pull_requests,
        "validations": validations,
        "benchmark_results": load_benchmark_results(root),
        "files": load_repository_files(root),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("steward-snapshot.json"))
    args = parser.parse_args(argv)
    if not args.repository:
        parser.error("--repository or GITHUB_REPOSITORY is required")
    try:
        snapshot = build_snapshot(args.repository, args.root)
        args.output.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, SnapshotError, ValueError) as exc:
        print(f"steward snapshot: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
