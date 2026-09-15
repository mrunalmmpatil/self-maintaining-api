import sys
import time

from .agent import run_agent
from .files import tree_hash
from .migration import Service
from .reports import finalize
from .runner import DockerRunner, RepositoryRunner
from .schema import now
from .status import STOPS, stage_name
from .tools import BudgetExceeded, Tools

INTRO = {
    "analyzing": "Analysis agent started: reading both contracts, the notes and the client source.",
    "repairing": "Repair agent started: editing a disposable copy of the source.",
    "finalizing": "Verifying the delivered revision.",
}
DONE = {
    "analyzing": "Analysis agent finished and submitted its findings.",
    "repairing": "Repair agent finished and submitted its patch summary.",
}


def execute(store, run_id, stage, agent=run_agent, runner=None):
    report = store.get(run_id)
    report.started_at = report.started_at or now()
    runner = runner or (
        RepositoryRunner(report)
        if report.sample_id == "repository"
        else DockerRunner(
            run_id, report.scenario_id, report.warnings, store.root / "runs" / run_id / "protected"
        )
    )
    tools = Tools(store, report, runner)
    reason = "completed"
    try:
        started = time.monotonic()
        tools.log("stage_started", INTRO[stage])
        agent(stage, tools)
        if not tools.submitted:
            raise RuntimeError("Stage submission missing")
        tools.log("stage_finished", DONE[stage], "ok", started)
        if stage == "analyzing":
            supported = any(c.disposition == "repair" for c in report.changes)
            if report.mode == "review" and (supported or report.sample_id == "repository"):
                report.lifecycle = "awaiting_review"
                tools.save()
                store.event(
                    run_id,
                    "awaiting_review",
                    "Analysis saved. Approve it to start the repair, or edit it and reanalyze.",
                    stage=stage_name("awaiting_review"),
                    status="warn",
                )
                return
            if supported:
                report.lifecycle = "repairing"
                tools.submitted = False
                tools.save()
                started = time.monotonic()
                tools.log("stage_started", INTRO["repairing"])
                agent("repairing", tools)
                if not tools.submitted:
                    raise RuntimeError("Repair submission missing")
                tools.log("stage_finished", DONE["repairing"], "ok", started)
        report.lifecycle = "finalizing"
        tools.save()
        tools.log("stage_started", INTRO["finalizing"])
        revision = tree_hash(tools.workspace)
        if not report.development_checks or report.development_checks[-1].revision_hash != revision:
            tools.run_checks(final=True)
    except BudgetExceeded:
        reason = "budget_exceeded"
    except Exception:
        reason = tools.failure or "tool_error"
    if reason != "completed":
        tools.log(
            "stage_stopped",
            "Stopped: " + STOPS.get(reason, reason) + ".",
            "error",
        )
        if reason == "budget_exceeded":
            b = report.budget
            report.warnings.append(
                f"Execution stopped at its allowance: analysis calls {b.analysis_requests}/5, "
                f"total model calls {b.used_requests}/{b.limits['requests']}, "
                f"patch attempts {b.used_patch_attempts}/{b.limits['patch_attempts']}, "
                f"tool calls {b.used_tools}/{b.limits['tools']}. See Execution activity for rejected tools."
            )
        else:
            report.warnings.append(
                f"Execution stopped ({reason}). See Execution activity for tool errors and check logs."
            )
    tools.save()
    if report.lifecycle != "awaiting_review":
        # Even when the model fails, check a delivered final revision if the reserved
        # check and active time remain. Do not spend another model request to finalize.
        revision = tree_hash(tools.workspace)
        if (
            revision != report.inputs["consumer_hash"]
            and (not report.development_checks or report.development_checks[-1].revision_hash != revision)
            and report.budget.used_checks < 4
            and tools.remaining() > 0
        ):
            try:
                tools.run_checks(final=True)
            except Exception:
                report.warnings.append("Final revision could not be checked within the remaining budget.")
        if (
            tree_hash(tools.root / "original") != report.inputs["consumer_hash"]
            or tree_hash(tools.root / "inputs") != report.inputs["snapshot_hash"]
            or tree_hash(tools.root / "protected") != report.inputs["protected_hash"]
        ):
            reason = "tool_error"
            report.warnings.append("Protected snapshot integrity check failed.")
        finalize(store, report, reason)


if __name__ == "__main__":
    execute(Service().store, sys.argv[1], sys.argv[2])
