import argparse
import json
import shlex
import shutil
import sys
import time
from pathlib import Path

from . import console
from .config import SCENARIOS
from .migration import Service
from .schema import RunRequest
from .status import RESULTS

PAGE = 100


def exit_status(report):
    return RESULTS[report.result][2]


def header(report, divider=True):
    target = report.scenario_id or report.repository_path or report.sample_id
    mode = "automatic" if report.mode == "auto" else "review first"
    return (
        f"Run {report.run_id}\n"
        f"  target {target}\n"
        f"  mode {mode}   model {report.model.get('requested_id') or 'unset'}"
        + ("\n" + console.rule() if divider else "")
    )


def drain(service, run_id, cursor, show=True):
    """Print every event newer than the cursor, following the store's page size."""
    while True:
        events = service.store.events(run_id, cursor, PAGE)
        for event in events:
            if show:
                print(console.event_line(event), flush=True)
            cursor = event["seq"]
        if len(events) < PAGE:
            return cursor


def artifacts_path(service, run_id):
    return service.store.root / "runs" / run_id / "artifacts"


def follow(service, run_id, quiet=False, as_json=False):
    show = not quiet and not as_json
    if show:
        print(header(report := service.get_run(run_id)), flush=True)
    cursor = 0
    while True:
        cursor = drain(service, run_id, cursor, show)
        report = service.get_run(run_id)
        if report.lifecycle in ("finished", "interrupted", "awaiting_review"):
            time.sleep(0.3)  # The closing verdict event is written just after the save.
            drain(service, run_id, cursor, show)
            if as_json:
                print(report.model_dump_json(indent=2))
            else:
                print(console.summary(report, artifacts_path(service, run_id)), flush=True)
            return exit_status(report)
        time.sleep(1)


def show_status(service, run_id, as_json):
    report = service.get_run(run_id)
    if as_json:
        print(report.model_dump_json(indent=2))
    else:
        print(header(report, divider=False))
        print(console.summary(report, artifacts_path(service, run_id)))
    return exit_status(report)


def show_logs(service, run_id, as_json, watch):
    report = service.get_run(run_id)
    if as_json:
        events, cursor = [], 0
        while True:
            page = service.store.events(run_id, cursor, PAGE)
            events += page
            if len(page) < PAGE:
                break
            cursor = page[-1]["seq"]
        print(json.dumps(events, indent=2))
        return exit_status(report)
    if watch and report.lifecycle not in ("finished", "interrupted", "awaiting_review"):
        return follow(service, run_id)
    print(header(report))
    drain(service, run_id, 0)
    print(console.summary(report, artifacts_path(service, run_id)))
    return exit_status(report)


def list_runs(service, limit, as_json):
    from .schema import Report

    rows = service.store.recent(limit)
    if as_json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No runs yet. Start one with: api-maintainer run --scenario endpoint-rename")
        return 0
    reports = [Report.model_validate(row) for row in rows]
    print(console.batch(reports))
    print(console.rule())
    print("  Details for one run:  api-maintainer status RUN_ID")
    print("  Full activity log:    api-maintainer logs RUN_ID")
    return 0


def show_doctor(service, as_json):
    status = service.health()
    if as_json:
        print(json.dumps(status, indent=2))
        return 0 if status["ready"] else 1
    labels = {
        "docker": "Docker engine reachable",
        "image": "Execution image api-maintainer-python:local built",
        "model_configured": "OPENROUTER_MODEL set to an approved free model",
        "key_configured": "OPENROUTER_API_KEY present",
    }
    for key, value in status.items():
        if key == "ready":
            continue
        mark = console.SYMBOLS["ok" if value else "error"]
        print(f"  {console.paint(mark, 'ok' if value else 'error')} {labels.get(key, key)}")
    print(console.rule())
    if status["ready"]:
        print(console.paint(console.SYMBOLS["ok"] + " READY", "ok") + "  All prerequisites are in place.")
        return 0
    print(console.paint(console.SYMBOLS["error"] + " NOT READY", "error") + "  Fix the items marked above.")
    return 1


def show_evaluation(service, run_id, as_json):
    service.request_evaluation(run_id)
    while service.store.leased(run_id):
        time.sleep(1)
    report = service.get_run(run_id)
    result = report.evaluation
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        passed = result["verdict"] == "passed"
        status = "ok" if passed else ("error" if result["verdict"] == "failed" else "warn")
        print(
            console.paint(
                f"{console.SYMBOLS[status]} INDEPENDENT EVALUATION {result['verdict'].upper()}", status
            )
        )
        print(f"  revision {result.get('evaluated_revision_hash')}")
        print(f"  full record  {artifacts_path(service, run_id) / 'evaluation.json'}")
    return 0 if result["verdict"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(
        description="Migrate a client repository between OpenAPI contracts in a disposable copy."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def with_json(sub):
        sub.add_argument("--json", action="store_true", help="Print the exact saved record instead")
        return sub

    with_json(commands.add_parser("doctor", help="Check prerequisites"))
    commands.add_parser("scenarios", help="List bundled demo scenarios")
    listing = with_json(commands.add_parser("runs", help="Summarize recent runs, newest first"))
    listing.add_argument("--limit", type=int, default=20)
    run = with_json(commands.add_parser("run", help="Start a migration and stream its activity"))
    run.add_argument("--scenario", default="endpoint-rename", choices=SCENARIOS)
    run.add_argument("--sample", default="bookstore", choices=["bookstore"])
    run.add_argument("--mode", choices=["auto", "review"], default="review")
    run.add_argument("--quiet", action="store_true", help="Print only the final summary")
    run.add_argument(
        "--repo",
        type=Path,
        help="Local client repository; requires both API documents and always pauses for review",
    )
    run.add_argument("--test-command", default="")
    run.add_argument("--test-image", default="api-maintainer-python:local")
    for name in ("old-spec", "new-spec", "notes-file"):
        run.add_argument("--" + name, type=Path)
    repair = with_json(commands.add_parser("repair", help="Approve an analysis and stream the repair"))
    repair.add_argument("run_id")
    repair.add_argument("--quiet", action="store_true")
    status = with_json(commands.add_parser("status", help="Show one run's verdict and supporting facts"))
    status.add_argument("run_id")
    logs = with_json(commands.add_parser("logs", help="Replay one run's full activity log"))
    logs.add_argument("run_id")
    logs.add_argument("--follow", action="store_true", help="Stream new activity if the run is live")
    evaluate = with_json(commands.add_parser("evaluate", help="Run the independent evaluator"))
    evaluate.add_argument("run_id")
    export = commands.add_parser("export", help="Copy a run's artifacts to a directory")
    export.add_argument("run_id")
    export.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    as_json = getattr(args, "json", False)
    service = Service()
    service.reconcile()
    try:
        if args.command == "doctor":
            return show_doctor(service, as_json)
        if args.command == "scenarios":
            print(json.dumps([dict(id=k, **v) for k, v in SCENARIOS.items()], indent=2))
            return 0
        if args.command == "runs":
            return list_runs(service, args.limit, as_json)
        if args.command == "run":
            report = service.create_run(
                RunRequest(
                    sample_id="repository" if args.repo else args.sample,
                    scenario_id=None if args.repo else args.scenario,
                    mode=args.mode,
                    repository_path=str(args.repo.resolve()) if args.repo else None,
                    test_command=shlex.split(args.test_command),
                    test_image=args.test_image,
                ),
                old=args.old_spec.read_bytes() if args.old_spec else None,
                new=args.new_spec.read_bytes() if args.new_spec else None,
                notes=args.notes_file.read_bytes() if args.notes_file else None,
            )
            return follow(service, report.run_id, args.quiet, as_json)
        if args.command == "repair":
            service.request_repair(args.run_id)
            return follow(service, args.run_id, args.quiet, as_json)
        if args.command == "status":
            return show_status(service, args.run_id, as_json)
        if args.command == "logs":
            return show_logs(service, args.run_id, as_json, args.follow)
        if args.command == "evaluate":
            return show_evaluation(service, args.run_id, as_json)
        if args.command == "export":
            report = service.get_run(args.run_id)
            args.output.mkdir(parents=True, exist_ok=True)
            for name in report.artifacts:
                if (args.output / name).exists():
                    raise ValueError("Output contains existing artifacts; choose an empty directory.")
            for name in report.artifacts:
                shutil.copyfile(service.get_artifact(args.run_id, name), args.output / name)
            print(f"Exported {len(report.artifacts)} artifact(s) to {args.output}")
            return 0
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        print(console.paint(console.SYMBOLS["error"] + " " + str(exc), "error", sys.stderr), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
