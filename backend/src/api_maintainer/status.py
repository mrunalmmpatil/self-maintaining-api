"""One verdict per run, derived from the fields the service already records.

`lifecycle`, `outcome`, `termination_reason`, `development_verification` and
`evaluation.verdict` each answer a different question and are all retained. This
module folds them into a single result plus a plain-English explanation, so the
CLI, the web UI and report.json never disagree about whether a run succeeded.
"""

# result -> (label, symbol, CLI exit code). Exit codes match the documented
# contract: 0 passed, 2 human work remains, 1 failed or never finished.
RESULTS = {
    "pass": ("PASS", "PASS", 0),
    "partial": ("PARTIAL", "PART", 2),
    "review": ("NEEDS REVIEW", "WAIT", 2),
    "fail": ("FAIL", "FAIL", 1),
    "running": ("RUNNING", "....", 1),
}

OUTCOMES = {
    "checks_passed": ("pass", "Repair applied and verified by the development checks."),
    "no_change_needed": ("pass", "No client change was required by this API migration."),
    "partial_repair": ("partial", "Part of the migration was repaired; the rest needs a person."),
    "manual_action_required": (
        "partial",
        "Nothing could be repaired automatically; every change needs a person.",
    ),
    "repair_failed": ("fail", "A patch was applied but the development checks still fail."),
    "verification_incomplete": ("fail", "No verified repair: the final revision was never proven to work."),
}

# Why a run stopped before finishing its own work. "completed" and "manual_work"
# are normal endings and add nothing to the explanation.
STOPS = {
    "budget_exceeded": "it used up its allowance (model calls, patches, checks or time)",
    "provider_error": "the model provider returned an error",
    "provider_rate_limited": "the model provider rate-limited it",
    "tool_error": "a tool call could not complete",
    "worker_interrupted": "its worker process was interrupted",
}

LIFECYCLES = {
    "created": "Queued; the analysis agent has not started.",
    "analyzing": "The analysis agent is reading the contracts and client source.",
    "awaiting_review": "Analysis is ready. Approve it to start the repair.",
    "repairing": "The repair agent is patching a disposable copy of the source.",
    "finalizing": "Running the final development checks on the delivered revision.",
    "interrupted": "The run was interrupted and never produced a final revision.",
}

STAGES = {
    "analyzing": "analyze",
    "repairing": "repair",
    "finalizing": "finalize",
    "evaluation": "evaluate",
    "awaiting_review": "review",
}


def stage_name(value):
    return STAGES.get(value or "", value or "run")


def classify(lifecycle, outcome, termination_reason=None):
    """Return (result, headline) without needing a whole Report object."""
    if lifecycle == "awaiting_review":
        return "review", LIFECYCLES["awaiting_review"]
    if lifecycle == "interrupted":
        return "fail", LIFECYCLES["interrupted"]
    if lifecycle != "finished":
        return "running", LIFECYCLES.get(lifecycle, "Running.")
    if outcome in OUTCOMES:
        result, headline = OUTCOMES[outcome]
        if termination_reason in STOPS:
            headline += " It stopped early because " + STOPS[termination_reason] + "."
        return result, headline
    return "fail", "The run finished without recording an outcome."


def apply_result(report):
    """Refresh the derived verdict fields. Called on every store read and write."""
    report.result, report.result_reason = classify(
        report.lifecycle, report.outcome, report.termination_reason
    )
    return report


def explain(report):
    """Full presentation record for one run."""
    label, symbol, code = RESULTS[report.result]
    return dict(
        result=report.result,
        label=label,
        symbol=symbol,
        exit_code=code,
        reason=report.result_reason,
    )


def roll_up(reports):
    """Counts per result for a batch, in a stable display order."""
    counts = dict.fromkeys(RESULTS, 0)
    for report in reports:
        result = report.result if hasattr(report, "result") else report.get("result", "running")
        counts[result] = counts.get(result, 0) + 1
    return counts
