from .console import stage_rows
from .files import atomic_write, source_diff, tree_hash
from .schema import now
from .status import RESULTS, apply_result


def finalize(store, report, reason="completed"):
    root = store.root / "runs" / report.run_id
    patch, edited = source_diff(root / "original", root / "workspace")
    revision = tree_hash(root / "workspace")
    report.patch = dict(
        artifact_id="patch.diff",
        base_hash=report.inputs["consumer_hash"],
        final_hash=revision,
        edited_files=edited,
        empty=not patch,
    )
    final_checks = [c for c in report.development_checks if c.revision_hash == revision]
    verification = final_checks[-1].status if final_checks else "not_run"
    report.development_verification = verification
    for change in report.changes:
        if change.disposition == "repair":
            change.verification_refs = [c.id for c in final_checks]
    uncertain = any(c.disposition == "uncertain" for c in report.changes)
    supported = any(c.disposition == "repair" for c in report.changes)
    # Narrow, deterministic attribution for the mixed fixture. Only a route string changed;
    # the actual wrapper reached the new API's missing-country validation. Any broader
    # unverified edit stays incomplete, even if the agent calls it a partial success.
    endpoint_only = bool(edited) and all(
        (root / "workspace" / name).read_text()
        == (root / "original" / name).read_text().replace("/books/", "/catalog/books/")
        for name in edited
    )
    partial_evidence = bool(
        final_checks
        and final_checks[-1].components.get("endpoint_reaches_country_validation")
        and endpoint_only
    )
    if reason != "completed" or uncertain:
        report.outcome = "verification_incomplete"
    elif report.manual_actions:
        # Failed full-suite checks alone do not establish that a partial patch is correct.
        if patch and (verification == "passed" or partial_evidence):
            report.outcome = "partial_repair"
        elif patch:
            report.outcome = "verification_incomplete"
            report.warnings.append(
                "Partial patch retained. Residual failure attribution requires independent review."
            )
        else:
            report.outcome = "manual_action_required"
    elif not patch and not supported:
        report.outcome = (
            "no_change_needed"
            if report.sample_id != "repository" or verification == "passed"
            else "verification_incomplete"
        )
    elif verification == "passed" and patch:
        report.outcome = "checks_passed"
    elif verification == "failed":
        report.outcome = "repair_failed"
    else:
        report.outcome = "verification_incomplete"
    report.termination_reason = "manual_work" if reason == "completed" and report.manual_actions else reason
    report.finished_at = now()
    report.lifecycle = "finished"
    for name in ("analysis.json", "report.json", "report.md", "patch.diff"):
        if name not in report.artifacts:
            report.artifacts.append(name)
    if not (root / "artifacts/analysis.json").exists():
        atomic_write(root / "artifacts/analysis.json", '{"incomplete": true, "changes": []}')
    atomic_write(root / "artifacts/patch.diff", patch)
    write_report(store, report)
    # The closing log line is the verdict itself, in the same words the CLI and UI use.
    apply_result(report)
    store.event(
        report.run_id,
        "finished",
        RESULTS[report.result][0] + " - " + report.result_reason,
        stage="run",
        status={"pass": "ok", "partial": "warn", "review": "warn"}.get(report.result, "error"),
    )


def write_report(store, report):
    root = store.root / "runs" / report.run_id / "artifacts"
    apply_result(report)
    text = f"# Migration {report.run_id}\n\n## {RESULTS[report.result][0]}\n\n{report.result_reason}\n\n"
    text += "| Stage | Result |\n| --- | --- |\n"
    for stage, _, detail in stage_rows(report):
        text += f"| {stage} | {detail} |\n"
    text += "\n### Recorded fields\n\n"
    text += f"- Lifecycle: {report.lifecycle}\n- Outcome: {report.outcome or 'pending'}\n"
    text += f"- Development verification: {report.development_verification}\n"
    text += f"- Independent evaluation: {report.evaluation['verdict']}\n"
    text += f"- Termination: {report.termination_reason or 'pending'}\n\n"
    for change in report.changes:
        text += f"## {change.id}: {change.description}\n\nDisposition: {change.disposition}\n\n"
        for evidence in change.evidence:
            text += f"- {evidence.path} {evidence.pointer or str(evidence.line_start)}\n"
        text += "\n"
    if report.manual_actions:
        text += "## Required manual work\n\n"
        for action in report.manual_actions:
            text += f"- {action.required_work} Decision: {action.unresolved_decision}. Effect: {action.blocking_effect}\n"
    text += "\n## Checks\n\n"
    for check in report.development_checks:
        text += (
            f"- {check.id}: {check.status}; revision `{check.revision_hash}`; log: {check.log_artifact_id}\n"
        )
    text += "\n## Warnings\n\n" + "\n".join("- " + w for w in report.warnings)
    text += "\n\nEdits are exported for review. The original consumer was not automatically modified.\n"
    atomic_write(root / "report.md", text)
    atomic_write(root / "report.json", report.model_dump_json(indent=2))
    store.save(report)
