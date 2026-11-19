import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gpu-ci-policy"))
from policy import gpu_job_authorized  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DOCS = ROOT / "docs" / "hardware.md"


class GpuCiPolicyTests(unittest.TestCase):
    def test_authorized_same_repository_pull_request(self):
        self.assertTrue(
            gpu_job_authorized(
                event_name="pull_request",
                repository="bniladridas/cuda",
                head_repository="bniladridas/cuda",
                labels={"gpu-ci:approved"},
                enabled=True,
            )
        )

    def test_fork_pull_request_is_denied_even_with_label(self):
        self.assertFalse(
            gpu_job_authorized(
                event_name="pull_request",
                repository="bniladridas/cuda",
                head_repository="contributor/cuda",
                labels={"gpu-ci:approved"},
                enabled=True,
            )
        )

    def test_same_repository_without_approval_is_denied(self):
        self.assertFalse(
            gpu_job_authorized(
                event_name="pull_request",
                repository="bniladridas/cuda",
                head_repository="bniladridas/cuda",
                labels=set(),
                enabled=True,
            )
        )

    def test_disabled_gpu_ci_is_denied(self):
        self.assertFalse(
            gpu_job_authorized(
                event_name="pull_request",
                repository="bniladridas/cuda",
                head_repository="bniladridas/cuda",
                labels={"gpu-ci:approved"},
                enabled=False,
            )
        )

    def test_push_and_manual_dispatch_are_denied(self):
        for event in ("push", "workflow_dispatch"):
            with self.subTest(event=event):
                self.assertFalse(
                    gpu_job_authorized(
                        event_name=event,
                        repository="bniladridas/cuda",
                        head_repository="bniladridas/cuda",
                        labels={"gpu-ci:approved"},
                        enabled=True,
                    )
                )

    def test_workflow_enforces_the_same_gates_and_ephemeral_runner(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        expected = (
            "github.event_name == 'pull_request'",
            "github.event.pull_request.head.repo.full_name == github.repository",
            "gpu-ci:approved",
            "vars.CUDA_CI_ENABLED == 'true'",
            "nvidia, cuda, ephemeral",
            "persist-credentials: false",
            "labeled, unlabeled",
        )
        for value in expected:
            with self.subTest(value=value):
                self.assertIn(value, source)

    def test_docs_require_one_shot_runner(self):
        docs = DOCS.read_text(encoding="utf-8")
        self.assertIn("--ephemeral", docs)
        self.assertIn("gpu-ci:approved", docs)
        self.assertIn("Fork PRs are denied", docs)


if __name__ == "__main__":
    unittest.main()
