"""Maintenance command for abandoned work after workers are stopped."""
import argparse

from backend.jobs import lookup, recover_failed, transition


def reconcile(job_id, workers_stopped):
    if not workers_stopped:
        raise ValueError("Stop every worker that can process this job before reconciliation.")
    row = lookup(job_id)
    if not row or row["state"] not in {"RUNNING", "RENDERING"}:
        raise ValueError("Select an abandoned RUNNING or RENDERING job.")
    if not transition(job_id, row["state"], "FAILED", error="Worker interrupted; reconciliation required."):
        raise ValueError("The job changed during reconciliation.")
    return recover_failed(job_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--workers-stopped", action="store_true")
    args = parser.parse_args()
    try:
        queued = reconcile(args.job_id, args.workers_stopped)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    print("Requeued existing job." if queued else "Marked failed. Reconcile the provider request before retrying.")


if __name__ == "__main__":
    main()
