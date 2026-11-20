"""Small, dependency-free model of the GPU workflow authorization contract."""


def gpu_job_authorized(*, event_name, repository, head_repository, labels, enabled):
    """Return whether a PR may use the isolated self-hosted GPU runner."""
    return (
        enabled is True
        and event_name == "pull_request"
        and bool(repository)
        and head_repository == repository
        and "gpu-ci:approved" in set(labels)
    )
