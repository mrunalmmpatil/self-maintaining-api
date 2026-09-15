# API Maintainer

A local tool-driven agent for migrating client repositories between OpenAPI contracts. The main flow takes a local repository and previous/new API documents, identifies changes automatically, and pauses for review. Bookstore scenarios are optional demos. It analyzes evidence, edits a disposable copy, runs Docker development checks, and exports a patch and reports. A separate evaluator checks the frozen result.

**Implementation status:** Repository-first inputs, editable analysis review, isolated source patches, and configurable Docker checks are implemented. Live model availability and quality remain subject to provider limits. See [validation evidence](docs/VALIDATION.md).

## Setup

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 20.19+ or 22.12+, npm, and a running Docker Engine/Desktop. Run from the repository root:

```sh
uv sync --project backend --frozen
npm --prefix frontend ci
npm --prefix frontend run build
docker build -t api-maintainer-python:local docker
```

No dependencies are downloaded inside migration checks. The runtime image contains Python's standard library; the consumer and mock need no additional packages. Build the image before running migrations.

Copy `.env.example` to `.env` if `.env` does not exist, then add your key to `OPENROUTER_API_KEY` in that file. The backend loads `.env` on startup. Alternatively, set the variables in your backend shell:

```sh
export OPENROUTER_MODEL=nvidia/nemotron-3.5-lightning:free
```

The repository-root `.env` is automatically loaded by the CLI, server and workers. Exported shell variables take precedence. Restart a running backend after editing `.env`. Keep the key out of frontend configuration. The exact model is allowlisted in `backend/src/api_maintainer/config.py`. Its public catalog advertises zero input/output pricing and tools; **the live tool/edit gate is pending**. Availability can change. Paid IDs, the random free router, and provider fallbacks are not enabled. Both SDK and transport retries are disabled; a provider error stops honestly.

```sh
backend/.venv/bin/api-maintainer doctor
backend/.venv/bin/api-maintainer scenarios
backend/.venv/bin/api-maintainer run --scenario endpoint-rename --mode review
backend/.venv/bin/api-maintainer repair RUN_ID
backend/.venv/bin/api-maintainer status RUN_ID
backend/.venv/bin/api-maintainer logs RUN_ID
backend/.venv/bin/api-maintainer runs
backend/.venv/bin/api-maintainer export RUN_ID --output ./migration-output
backend/.venv/bin/api-maintainer evaluate RUN_ID
```

`runs` prints one table for every recent run, `status` explains a single run, and `logs`
replays its full activity. Every command takes `--json` to print the exact saved record
instead of the readable view, and `run`/`repair` take `--quiet` to skip the live stream.
Set `NO_COLOR=1` for uncolored output.

`run` defaults to Review first. Use `--mode auto` explicitly for automatic repair. Custom contracts use `--sample bookstore --old-spec old.yaml --new-spec new.yaml --notes-file notes.md`; supply both contracts. Checks still exercise the selected bundled scenario, so arbitrary custom APIs are not validated by these fixtures.

## Reading results

Every run ends with one verdict, derived in `backend/src/api_maintainer/status.py` and used
verbatim by the CLI, the web UI and `report.json`:

| Verdict | Meaning | Exit code |
|---|---|---|
| `pass` | The repair was applied and verified, or nothing needed changing | `0` |
| `partial` | Real work was done but some of it still needs a person | `2` |
| `review` | The analysis is ready and paused for your approval | `2` |
| `fail` | No verified repair was produced | `1` |
| `running` | Not finished yet | `1` |

The detailed fields behind the verdict are all retained: `lifecycle` (where the run is),
`outcome` (what it produced), `development_verification` (whether the configured checks
passed), `termination_reason` (why it stopped) and `evaluation.verdict` (the separate
independent result). `result_reason` states the verdict in one sentence.

Every activity log line records the stage that produced it (`analyze`, `repair`,
`finalize`, `evaluate`), whether that step succeeded, how long it took, and what it
achieved, so a run involving several agents reads as one timeline. Evaluation returns `0`
only when independent checks pass. Ctrl+C stops following events; the detached supervisor
retains control of the run and enforces its deadline.

## Local web UI

```sh
backend/.venv/bin/uvicorn api_maintainer.api:app --host 127.0.0.1 --port 8000
```

Open [the local app](http://127.0.0.1:8000). Build the frontend before starting this server; packaged assets are served from `frontend/dist`. For frontend development, run `npm --prefix frontend run dev` in a second shell and use [Vite](http://127.0.0.1:5173). Vite proxies `/api` to port 8000.

The UI provides a form, persistent run history, evidence and affected locations, review approval, the source diff, check results, manual actions, and artifact downloads. Each run opens with the same verdict and per-stage breakdown the CLI prints, and the activity log shows every step with its stage, status and duration. Run URLs use a hash so refresh works with static hosting. Evaluation is invoked through the CLI; its separate verdict appears when loading the saved run.

## Execution and data

CLI and API share `.local-data` by default. Set `API_MAINTAINER_DATA` to the same absolute location for both if overriding it. SQLite transactions control one migration/evaluation lease. A detached supervisor launches the worker, records heartbeats, and enforces the active deadline. Review checkpoints release the lease and survive restarts; a fresh repair-stage Strands agent uses the saved analysis. Counters do not reset.

Limits: 20 outbound requests (5 for analysis), 30 tool executions, 6 patch submissions, 4 development checks, 180 seconds/request, 120 seconds/check, and 1,200 active seconds/run. One check is reserved for the final revision. Review waiting time is excluded. Independent evaluation has its own 120-second limit. These are not normal-user configuration options.

Inputs, original source, and protected mock/check/evaluation fixtures are snapshotted and hashed. Only supported existing source files in approved affected locations can be patched; test and fixture files are excluded. The patch parser accepts exact unified hunks; creation/deletion, renames, binary patches, symlinks and fuzzy matching are unsupported. Final export is always a diff against the original snapshot.

Consumer execution is Docker-only: non-root, read-only filesystems and mounts, dropped capabilities, no privilege escalation, 1 CPU, 512 MiB RAM, 128 PIDs, bounded temporary space and output. Each execution has a private internal network with its HTTP mock, no published ports and no model key. Hidden evaluation definitions stay on the host and exercise the consumer's command output. The repository flow supports local client snapshots and explicitly configured isolated tests; it does not execute repository code on the host.

A passing development check is not an independent evaluation verdict. Final results refer to source hashes. For the mixed case, a narrow endpoint-only patch plus an actual wrapper response reaching required-country validation establishes a partial repair; the full failing checks remain visible. Broader edits with uncertain attribution remain `verification_incomplete`.

## Verification

```sh
backend/.venv/bin/pytest backend/tests -q
backend/.venv/bin/ruff check backend/src backend/tests
npm --prefix frontend run build
```

Tests mock the provider/checks for orchestration and explicitly label that evidence. A pinned Strands SDK test exercises actual tool dispatch and HTTP result handling against scripted responses. Docker baseline/isolation tests automatically skip when the daemon/image is absent. Do not interpret skips as acceptance success.

The test-only browser fixture is `backend/tests/ui_server.py`. It uses temporary storage and scripted actions; it is never selected by the production server or CLI. See [browser test procedure](docs/BROWSER_TESTS.md).

After live model read/edit validation and Docker setup, run a deliberate small comparison:

```sh
backend/.venv/bin/python -m api_maintainer.benchmark \
  --scenarios endpoint-rename --trials 1 --output ./benchmark-results.json
```

Omit `--scenarios` for all seven cases when free quota permits. Each case runs once with a one-patch cap and once with three; other limits and model settings are held constant. The harness records actual counts, outcomes, usage and independent verdicts, saves after each case, and stops on provider failure. It never selects a prewritten scenario patch. No live benchmark results are included yet.

## Repository-first workflow

Open New migration and provide an absolute local client directory plus previous/new OpenAPI 3.0.x JSON or YAML documents (1 MiB each). Optional notes explain business meaning. Change types are LLM analysis output; no scenario selection is needed. Select “Try a demo instead” only for bundled bookstore tests.

The analysis shows detected change types, evidence, affected files and an editable summary. Editing the summary or review notes requires “Reanalyze edits,” which creates a linked run from the original snapshot and corrected notes. It pauses for a new review. Approving an unchanged analysis starts repair in the disposable copy. Earlier runs and original client files are preserved.

Repository snapshots include up to 1,000 supported UTF-8 text/source files (10 MiB total; 1 MiB per file). Hidden files, Git metadata, common credential filenames, symlinks, dependencies and build directories are excluded. This is not a comprehensive secret scanner: choose a client directory without embedded secrets. Source and documents are sent to the configured model. Tests, fixtures and non-source configuration files cannot be patched. Arbitrary file creation/deletion remains unsupported.

Optional test settings specify a command (parsed into arguments, no host shell) and a prebuilt Docker image with the project's dependencies. Tests run at `/source`, with a read-only snapshot and no network, host credentials, or Docker socket. The default image provides Python standard-library tests only. No configured command means verification is incomplete. Bookstore mocks and independent evaluation are never used to claim verification of a custom repository.

CLI equivalent:

```sh
backend/.venv/bin/api-maintainer run --repo /absolute/path/to/client --old-spec old.yaml --new-spec new.yaml --test-command "python -m unittest discover -s tests"
```

Remote Git cloning, PDF/prose documentation, automatic dependency installation, and automatic discovery of a trustworthy test command are not included.
