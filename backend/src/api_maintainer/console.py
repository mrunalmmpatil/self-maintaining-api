"""Plain-text rendering of run status and activity logs for the terminal.

Everything printed by the CLI comes from here, so a single run, a live stream and
a batch of runs all describe success and failure with the same words and symbols.
"""

import os
import shutil
import sys
import textwrap
from datetime import datetime

from .status import RESULTS, stage_name

SYMBOLS = {"ok": "✓", "error": "✗", "warn": "!", "info": "·"}
COLORS = dict(
    ok="\033[32m", error="\033[31m", warn="\033[33m", info="\033[90m", head="\033[1m", off="\033[0m"
)
RESULT_STATUS = {"pass": "ok", "partial": "warn", "review": "warn", "fail": "error", "running": "info"}
TALLY = {
    "pass": "passed",
    "partial": "partial",
    "review": "needs review",
    "fail": "failed",
    "running": "still running",
}
RESULT_WIDTH = 16
# Runs recorded before events carried a status still read correctly.
LEGACY_STATUS = {
    "tool_error": "error",
    "provider_error": "error",
    "provider_retry": "warn",
    "response_truncated": "warn",
    "submission_pending": "warn",
    "awaiting_review": "warn",
}


def color_enabled(stream=None):
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") or os.environ.get("API_MAINTAINER_PLAIN"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def paint(text, status, stream=None):
    if not color_enabled(stream):
        return text
    return COLORS.get(status, "") + text + COLORS["off"]


def width():
    return max(60, min(shutil.get_terminal_size((100, 24)).columns, 120))


def rule(char="─"):
    return char * width()


def human(seconds):
    """Durations a person can read at a glance."""
    if seconds is None:
        return ""
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{int(seconds)}s"
    return f"{int(seconds) // 60}m{int(seconds) % 60:02d}s"


def elapsed(report):
    """Wall time for a finished run; otherwise the active seconds actually charged."""
    if report.finished_at and report.started_at:
        try:
            return (
                datetime.fromisoformat(report.finished_at) - datetime.fromisoformat(report.started_at)
            ).total_seconds()
        except ValueError:
            pass
    return report.budget.active_seconds or None


def event_line(event, stream=None):
    """One activity line: when, which agent, whether it worked, what it did."""
    clock = datetime.fromtimestamp(event["at"]).strftime("%H:%M:%S")
    status = event.get("status") or "info"
    if status == "info":
        status = LEGACY_STATUS.get(event.get("kind"), "info")
    stage = (event.get("stage") or stage_name(event.get("kind")))[:8].ljust(8)
    took = event.get("duration_ms")
    suffix = f"  ({human(took / 1000)})" if took else ""
    body = f"{event['message']}{suffix}"
    room = width() - 24
    if len(body) > room:
        body = body[: room - 1] + "…"
    mark = paint(SYMBOLS.get(status, "·"), status, stream)
    return f"{paint(clock, 'info', stream)}  {paint(stage, 'info', stream)} {mark}  {body}"


def stage_rows(report):
    """What each participant in the run actually produced."""
    repairable = sum(c.disposition == "repair" for c in report.changes)
    manual = len(report.manual_actions)
    rows = []
    if report.changes or report.lifecycle != "created":
        detail = (
            f"{len(report.changes)} change(s): {repairable} repairable, {manual} needing a person"
            if report.changes
            else "no changes recorded"
        )
        rows.append(("analyze", "ok" if report.changes else "warn", detail))
    if report.patch:
        files = len(report.patch.get("edited_files") or [])
        attempts = report.budget.used_patch_attempts
        detail = (
            f"{files} file(s) patched in {attempts} attempt(s)"
            if files
            else f"no file changed ({attempts} patch attempt(s))"
        )
        rows.append(("repair", "ok" if files else "warn", detail))
    if report.lifecycle in ("finished", "interrupted") or report.development_checks:
        verification = report.development_verification
        rows.append(
            (
                "checks",
                {"passed": "ok", "failed": "error"}.get(verification, "warn"),
                f"{verification.replace('_', ' ')} ({len(report.development_checks)} run)",
            )
        )
    verdict = report.evaluation.get("verdict", "not_run")
    rows.append(
        (
            "evaluate",
            {"passed": "ok", "failed": "error", "not_run": "info"}.get(verdict, "warn"),
            verdict.replace("_", " "),
        )
    )
    return rows


def headline(report, stream=None):
    label = RESULTS[report.result][0]
    status = RESULT_STATUS[report.result]
    return paint(f"{SYMBOLS[status]} {label}", status, stream) + "  " + report.result_reason


def summary(report, artifacts=None, stream=None, divider=True):
    """The block printed when a run stops: verdict first, then the supporting facts."""
    budget = report.budget
    lines = ([rule()] if divider else []) + [headline(report, stream), ""]
    for stage, status, detail in stage_rows(report):
        lines.append(f"  {paint(SYMBOLS[status], status, stream)} {stage.ljust(10)} {detail}")
    lines.append("")
    if report.termination_reason and report.termination_reason not in ("completed", "manual_work"):
        lines.append(f"  {'Stopped'.ljust(12)} {report.termination_reason.replace('_', ' ')}")
    lines.append(
        f"  {'Budget'.ljust(12)} model calls {budget.used_requests}/{budget.limits['requests']}"
        f" · patches {budget.used_patch_attempts}/{budget.limits['patch_attempts']}"
        f" · checks {budget.used_checks}/{budget.limits['checks']}"
        f" · tools {budget.used_tools}/{budget.limits['tools']}"
    )
    duration = elapsed(report)
    if duration is not None:
        lines.append(f"  {'Duration'.ljust(12)} {human(duration)}")
    if report.model.get("actual_id"):
        lines.append(f"  {'Model'.ljust(12)} {report.model['actual_id']}")
    for warning in report.warnings:
        wrapped = textwrap.wrap(warning, max(40, width() - 6)) or [""]
        lines.append(f"  {paint('!', 'warn', stream)} {wrapped[0]}")
        lines += [f"    {line}" for line in wrapped[1:]]
    if report.manual_actions:
        lines.append("")
        lines.append(f"  Work left for a person ({len(report.manual_actions)}):")
        for action in report.manual_actions:
            lines.append(f"    · {action.required_work}")
    if artifacts:
        lines.append(f"  {'Artifacts'.ljust(12)} {artifacts}")
    lines.append(f"  {'Next'.ljust(12)} {next_step(report)}")
    return "\n".join(lines)


def next_step(report):
    """Tell the reader what to actually do about this result."""
    short = report.run_id[:8]
    if report.result == "review":
        return f"api-maintainer repair {short}…   (or edit the analysis in the web UI first)"
    if report.result == "running":
        return f"api-maintainer status {report.run_id}"
    if report.result == "fail":
        return f"api-maintainer logs {report.run_id}   to see which step failed"
    return f"api-maintainer export {report.run_id} --output ./migration-output"


def batch(reports, stream=None):
    """One table for a set of runs, with a roll-up of how many passed."""
    counts = {}
    for report in reports:
        counts[report.result] = counts.get(report.result, 0) + 1
    tally = "   ".join(
        paint(f"{SYMBOLS[RESULT_STATUS[key]]} {counts[key]} {TALLY[key]}", RESULT_STATUS[key], stream)
        for key in RESULTS
        if counts.get(key)
    )
    lines = [
        rule(),
        f"{len(reports)} run(s)   {tally}" if tally else f"{len(reports)} run(s)",
        rule(),
        f"  {'RESULT'.ljust(RESULT_WIDTH)}{'TARGET'.ljust(24)}{'TIME'.ljust(8)}{'RUN'.ljust(10)}WHY",
    ]
    for report in reports:
        status = RESULT_STATUS[report.result]
        mark = f"{SYMBOLS[status]} {RESULTS[report.result][0]}"
        target = (
            report.scenario_id or ((report.repository_path or "repository").rstrip("/").rsplit("/", 1)[-1])
        )
        why = report.result_reason
        room = max(20, width() - (RESULT_WIDTH + 44))
        if len(why) > room:
            why = why[: room - 1] + "…"
        lines.append(
            f"  {paint(mark.ljust(RESULT_WIDTH), status, stream)}{target[:23].ljust(24)}"
            f"{human(elapsed(report)).ljust(8)}{report.run_id[:8].ljust(10)}{why}"
        )
    return "\n".join(lines)
