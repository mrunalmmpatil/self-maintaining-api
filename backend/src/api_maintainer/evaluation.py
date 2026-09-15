"""Post-migration evaluation. Nothing here is registered as an agent tool."""

import json
import sys
import uuid

from .config import SAMPLE
from .files import atomic_write, tree_hash
from .migration import Service
from .reports import write_report
from .runner import DockerRunner


def evaluate(service, run_id):
    report = service.get_run(run_id)
    root = service.store.root / "runs" / run_id
    service.store.event(
        run_id,
        "stage_started",
        "Independent evaluator started: replaying hidden cases against the frozen revision.",
        stage="evaluate",
    )
    artifact = dict(verdict="incomplete", evaluated_revision_hash=report.patch["final_hash"], cases=[])
    protected = [
        root / "original",
        root / "inputs",
        SAMPLE / "contracts",
        SAMPLE / "development_checks",
        root / "protected",
    ]
    before = [tree_hash(p) for p in protected]
    try:
        if (
            tree_hash(root / "workspace") != report.patch["final_hash"]
            or before[0] != report.inputs["consumer_hash"]
            or before[1] != report.inputs["snapshot_hash"]
            or before[-1] != report.inputs["protected_hash"]
        ):
            artifact["verdict"] = "invalid"
        else:
            cases = json.loads((root / "protected/evaluation_checks/cases.json").read_text())
            artifact["cases"] = DockerRunner(
                run_id, report.scenario_id, fixtures=root / "protected"
            ).evaluate(root / "workspace", cases)
            artifact["verdict"] = "passed" if all(c["passed"] for c in artifact["cases"]) else "failed"
        if (
            before != [tree_hash(p) for p in protected]
            or tree_hash(root / "workspace") != report.patch["final_hash"]
        ):
            artifact["verdict"] = "invalid"
    except Exception:
        artifact["verdict"] = "incomplete"
    save_evaluation(service, report, artifact)
    return artifact


def record_incomplete(service, run_id, reason):
    report = service.get_run(run_id)
    artifact = dict(
        verdict="incomplete", evaluated_revision_hash=report.patch.get("final_hash"), cases=[], warning=reason
    )
    save_evaluation(service, report, artifact)


def save_evaluation(service, report, artifact):
    private = service.store.root / "evaluations" / uuid.uuid4().hex / "evaluation.json"
    atomic_write(private, json.dumps(artifact, indent=2))
    root = service.store.root / "runs" / report.run_id
    atomic_write(root / "artifacts/evaluation.json", json.dumps(artifact, indent=2))
    if "evaluation.json" not in report.artifacts:
        report.artifacts.append("evaluation.json")
    report.evaluation = dict(
        verdict=artifact["verdict"],
        artifact_id="evaluation.json",
        evaluated_revision_hash=artifact["evaluated_revision_hash"],
    )
    write_report(service.store, report)
    passed = sum(bool(c.get("passed")) for c in artifact.get("cases", []))
    total = len(artifact.get("cases", []))
    detail = f" ({passed} of {total} hidden cases passed)" if total else ""
    service.store.event(
        report.run_id,
        "stage_finished",
        f"Independent evaluation {artifact['verdict']}{detail}."
        + (" " + artifact["warning"] if artifact.get("warning") else ""),
        stage="evaluate",
        status={"passed": "ok", "failed": "error"}.get(artifact["verdict"], "warn"),
    )


if __name__ == "__main__":
    evaluate(Service(), sys.argv[1])
