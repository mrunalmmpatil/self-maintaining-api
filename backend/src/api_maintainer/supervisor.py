"""Detached supervisor keeps request handlers short and enforces the wall deadline."""

import os
import signal
import subprocess
import sys
import time

from .migration import Service
from .reports import finalize
from .runner import cleanup_run


def main():
    run_id, stage = sys.argv[1:3]
    store = Service().store
    report = store.get(run_id)
    started = time.monotonic()
    active_limit = report.budget.limits.get("active_seconds", 1200)
    remaining = 120 if stage == "evaluation" else active_limit - report.budget.active_seconds
    child = None
    try:
        module = "api_maintainer.evaluation" if stage == "evaluation" else "api_maintainer.worker"
        child = subprocess.Popen(
            [sys.executable, "-m", module, run_id, stage],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        store.set_worker(run_id, child.pid)
        while child.poll() is None:
            store.heartbeat(run_id, os.getpid())
            if time.monotonic() - started >= remaining:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)
                if stage != "evaluation":
                    report = store.get(run_id)
                    report.budget.active_seconds = report.budget.limits.get("active_seconds", 1200)
                    finalize(store, report, "budget_exceeded")
                else:
                    from .evaluation import record_incomplete

                    record_incomplete(Service(), run_id, "Independent evaluation exceeded its deadline.")
                break
            time.sleep(0.25)
        if stage != "evaluation":
            report = store.get(run_id)
            if report.lifecycle not in ("finished", "awaiting_review", "interrupted"):
                finalize(store, report, "worker_interrupted")
        else:
            current = store.get(run_id)
            if current.evaluation.get("artifact_id") is None:
                from .evaluation import record_incomplete

                record_incomplete(Service(), run_id, "Evaluation did not produce a final result.")
    finally:
        if child and child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)
        cleanup_run(run_id)
        store.release(run_id)


if __name__ == "__main__":
    main()
