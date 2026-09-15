"""Developer-only 1-vs-3 comparison. Never synthesizes patches or raises product ceilings."""

import argparse
import json
import time
from pathlib import Path

from . import console
from .config import SCENARIOS
from .files import atomic_write
from .migration import Service
from .schema import RunRequest
from .status import RESULTS, roll_up


def main():
    parser = argparse.ArgumentParser(
        description="Run a live free-model benchmark; each case consumes real free quota."
    )
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.trials <= 3:
        parser.error("Use 1–3 trials; this is a small local benchmark.")
    service = Service()
    service.reconcile()
    service.require_ready()
    results, finals = [], []
    for trial in range(args.trials):
        for scenario in args.scenarios:
            for cap in (1, 3):
                report = service.create_run(RunRequest(scenario_id=scenario, mode="auto"), launch=False)
                report.budget.limits["patch_attempts"] = cap
                report.warnings.append("Developer benchmark: fixed patch ceiling lowered to " + str(cap))
                service.store.save(report)
                service.store.claim(report.run_id, "analyzing")
                service.spawn(report.run_id, "analyzing")
                while service.store.leased(report.run_id):
                    time.sleep(1)
                final = service.get_run(report.run_id)
                if final.lifecycle == "finished":
                    service.request_evaluation(final.run_id)
                    while service.store.leased(final.run_id):
                        time.sleep(1)
                    final = service.get_run(final.run_id)
                results.append(
                    dict(trial=trial + 1, scenario=scenario, patch_cap=cap, report=final.model_dump())
                )
                finals.append(final)
                atomic_write(
                    args.output,
                    json.dumps(
                        {
                            "evidence": "live model / actual Docker checks",
                            "trial_count": args.trials,
                            "summary": roll_up(finals),
                            "results": results,
                        },
                        indent=2,
                    ),
                )
                status = console.RESULT_STATUS[final.result]
                print(
                    f"  {console.paint(console.SYMBOLS[status], status)} "
                    f"{RESULTS[final.result][0]:<13}{scenario:<24}patch cap {cap}"
                    f"   independent evaluation: {final.evaluation['verdict']}",
                    flush=True,
                )
                if final.termination_reason in ("provider_rate_limited", "provider_error"):
                    print(console.batch(finals), flush=True)
                    raise SystemExit(
                        "Provider stopped this batch; saved partial benchmark evidence. No quota workaround attempted."
                    )
    print(console.batch(finals), flush=True)
    print(console.rule())
    print(f"  Full records  {args.output}")


if __name__ == "__main__":
    main()
