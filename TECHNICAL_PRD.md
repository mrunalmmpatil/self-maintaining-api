# Self-Maintaining API — Technical PRD

Status: Implementation specification for the local MVP.

This document combines the original [product PRD](PRD.md) with the subsequent technical-design discussion. It takes precedence where the documents conflict. It describes the application to build; proposed interfaces, schemas, paths, and commands below are implementation targets, not existing functionality.

## 1. Objective and scope

Build a local tool-driven AI agent that helps migrate a small Python consumer application from one API version to another. Given old/new OpenAPI contracts, source code, and optional migration notes, it identifies changes, traces their impact, repairs supported cases in a disposable copy, runs development checks, and produces a patch and report.

Deliver both a CLI and a local web UI backed by the same Python migration service. Demonstrate behavior against a versioned local bookstore HTTP mock service. Verify the completed patch using a separate evaluation runner whose feedback is never returned to the repairing agent.

Success means preserving application behavior, including calculations and displayed values. A successful HTTP response or a syntactically valid patch alone is insufficient.

### 1.1 Decisions established in the discussion

| Area | Decision |
|---|---|
| Backend | Python |
| Frontend | TypeScript |
| AI access | OpenRouter, free models only; no paid fallback |
| Agent architecture | Tool-driven: the model chooses investigative and repair actions |
| Agent framework | Strands Agents |
| Execution isolation | Docker for the consumer and checks |
| Repair modes | Automatic and Review first |
| Missing required business input | Document the required application changes; do not invent a value or build an interactive clarification conversation |
| Mixed migrations | Repair supported changes and report remaining manual work |
| Limits | Fixed product limits rather than user-adjustable controls |
| Original application | Never modify it automatically; export a reviewable patch |

### 1.2 Implementation defaults

These resolve remaining engineering choices so coding can proceed. They are recommendations from the design discussion or defaults introduced by this specification, not separate claims of user confirmation.

- React + TypeScript + Vite for the frontend; FastAPI for the web backend.
- One Strands agent per active migration stage, with custom restricted tools.
- Review first is the default mode; Automatic must be explicitly selected.
- SQLite for run metadata/events and local files for immutable inputs, workspaces, logs, and artifacts.
- A single active migration or evaluation execution across the local installation. Additional execution requests return a clear busy response; no queue in the MVP.
- UI progress uses polling rather than requiring WebSockets.
- Use a Python CLI built with `argparse`, Pydantic for schemas, and pytest for Python behavior checks. Use browser automation for the complete UI flow.
- Python 3.12 is the initial development target, subject to dependency compatibility verification. Resolve compatible stable dependencies and commit Python and frontend lockfiles during scaffolding.

### 1.3 Explicit changes from the original PRD

- Model access is now OpenRouter through Strands, rather than an unspecified provider/adapter.
- Runtime budgets are fixed, rather than exposed as user configuration.
- Required inputs whose source is unspecified produce documented manual work, rather than a paused question-and-answer workflow.
- A partial repair is a valid delivery outcome; it is not a claim that the full migration works.
- Review first adds an analysis checkpoint before any source edits.
- The project already has a private GitHub repository: <https://github.com/mrunalmmpatil/self-maintaining-api>. Publishing this specification does not require creating migration PRs or an issue-tracker integration.

## 2. Product behavior

### 2.1 Inputs

Each migration receives:

- A registered sample consumer ID. The server maps this ID to a trusted source root; the UI does not accept arbitrary filesystem paths or repositories.
- Old and new OpenAPI contracts, defaulting to a bundled scenario's files.
- Optional migration notes containing explicit semantic instructions.
- A mode: `auto` or `review`.
- An optional bundled scenario ID for fixture selection and reporting.

Custom contracts may be provided for supported consumers. Initially accept JSON/YAML OpenAPI 3.0.x documents, using safe YAML parsing and local references inside the supplied document only. Reject external references and unsupported versions with an actionable validation message. File uploads are capped at 1 MiB per contract and 64 KiB for notes. These are implementation defaults for small fixtures.

Snapshot inputs and consumer source at run creation. Store content hashes. Never silently switch a saved run to a later version of the user's files.

### 2.2 Automatic

1. Validate inputs, Docker readiness, model configuration, and available local execution slot.
2. Snapshot inputs and prepare a disposable workspace.
3. Run analysis with read-only tools.
4. If supported repairs exist, enter repair automatically.
5. Let the agent propose edits and request development checks within the fixed budget.
6. Run a final development check on the final source revision if that revision has not been checked.
7. Finalize a patch and structured report, including remaining work.

### 2.3 Review first

Steps 1–3 match Automatic. Persist an analysis artifact describing detected changes, evidence, affected code, proposed repair scope, and manual actions. If repairable work exists, transition to `awaiting_review` and release the execution slot.

The UI shows **Generate repair**. The CLI provides an equivalent `repair <run_id>` command. That action resumes from the saved snapshot and analysis with the remaining budget. It must not repeat analysis unnecessarily or reset counters.

No agent process or model request remains alive while waiting for the click. An awaiting-review run must survive a backend restart. Persist the analysis, model conversation needed for continuity, budget counters, and immutable snapshot. If conversation replay is unsupported by the pinned SDK, create a repair-stage agent using the saved source context and analysis; preserve the same run ID and budget and record this behavior.

No-op and manual-only analyses finish without offering Generate repair. A partial migration offers repair for its supported subset while showing the manual actions alongside it. Approval authorizes the documented automatic repair scope; newly discovered business decisions become manual work rather than silently expanding that scope.

### 2.4 Required fields and partial repairs

Example: the new API both renames `/books` to `/catalog/books` and requires a `country` parameter whose source is absent from the consumer and migration notes.

Expected behavior:

- Repair supported endpoint references.
- Document the new required field and affected functions/call sites.
- Explain that a developer must decide where country comes from, accept/validate it at the relevant application boundary, and pass it through the callers to the API wrapper.
- Do not insert a hardcoded country or claim the full migration now works.
- Preserve failed/blocked checks caused by the missing country. Never suppress those failures to make the report green.
- Export the partial patch and remaining-work documentation.

In the initial phase, implementing a new user-input flow for a required business field is out of scope. Straightforward propagation of an already available, explicitly relevant value can be treated as supported only when its source is evidenced and covered by checks. The bundled missing-input scenario must require documentation, not a fabricated value.

## 3. System architecture

```text
React / TypeScript UI ──HTTP──> FastAPI
                                  │
Python CLI ────────────────────────┤
                                  ▼
                         Shared migration service
                         │        │           │
                         │        │           └── SQLite + artifacts
                         │        └── Strands agent ↔ OpenRouter free model
                         │                    │
                         │              Restricted Python tools
                         ▼
                    Docker runner
                    ├── Consumer + development checks
                    └── Local versioned mock API

Completed patch ──> Separate evaluation runner ──> Independent verdict
                         (no feedback into the agent)
```

### 3.1 Module responsibilities

| Module | Responsibilities |
|---|---|
| `contracts` | Validate/normalize contracts, resolve allowed references, produce structural differences with evidence pointers |
| `agent` | Configure Strands and OpenRouter, instructions, stage-specific tools, event hooks, conversation persistence |
| `tools` | Restricted file discovery/reads/search, atomic patches, predefined development checks, structured stage submission |
| `migration` | Shared run lifecycle, review checkpoint, workspace ownership, budget enforcement, outcome derivation |
| `runner` | Docker lifecycle, internal networking, resource limits, check execution, timeouts, cleanup |
| `reports` | Deterministic JSON/Markdown reports, patch export, evidence and log references |
| `storage` | SQLite transactions, events, counters, input hashes, artifact records, execution lease |
| `api` / `cli` | Thin adapters calling the shared migration service |
| `evaluation` | Separate evaluation orchestration and benchmark results; inaccessible through agent tools |

The model reasons about semantics and impact; deterministic code enforces permissions and records facts. A structural diff can identify a removed path and an added path, but must not label them a semantic rename without evidence. Migration notes or compatible schemas/source usage may support an interpretation; otherwise report uncertainty.

### 3.2 Local execution model

Use a local supervisor shared by CLI and API adapters. It claims an execution lease in SQLite and launches a worker subprocess. The FastAPI request returns a run ID without waiting for completion. The CLI can follow persisted events until the worker finishes.

Persist worker identity/heartbeat and tag Docker resources with run IDs. On startup, reconcile stale leases and containers. Runs interrupted during active execution become `interrupted`, preserving artifacts; automatic mid-tool crash resumption is out of scope. Runs awaiting review remain resumable because they have no active execution.

The CLI and server must resolve the same data directory and execution lease. Do not run Strands directly inside a request handler or depend on an in-memory background task to preserve run history.

## 4. Agent and model integration

### 4.1 Model configuration

- Use Strands' OpenAI-compatible model integration with OpenRouter's API base URL, `https://openrouter.ai/api/v1`.
- Read `OPENROUTER_API_KEY` from backend environment configuration. Never send it to the frontend, logs, model tools, or execution containers.
- Select one specific free model supporting tool calling, configured as `OPENROUTER_MODEL`. Pin that model for a benchmark batch.
- Allow only explicitly approved free model IDs; reject paid IDs. Do not enable paid fallbacks or paid auxiliary tools.
- Do not use the randomly selecting `openrouter/free` router for comparison benchmarks. Record requested and returned model identifiers and provider metadata where available.
- The exact model is an implementation gate: first verify availability and a real file-read/tool-result/final-response round trip through Strands. Then verify a generated edit. Free availability can change; do not claim a model has been validated until this succeeds.
- Fix model generation settings for benchmark comparisons and record them. Use low temperature if supported; do not treat it as a reproducibility guarantee.
- SDK/provider retries must be explicitly controlled so every outbound request attempt passes through the budget counter.

OpenRouter's documented baseline is 50 free-model requests/day for accounts below its credit-purchase threshold, and 20 requests/minute. These are external service policies, not guarantees or hardcoded assumptions about remaining quota. Surface throttling and exhaustion honestly; never purchase credits automatically.

### 4.2 Agent instructions

The system instructions must require evidence-backed changes, bounded exploration, source-only edits, preservation of existing unrelated behavior, and explicit remaining-work documentation. File content and migration notes are task data, not authority to override tool restrictions or request credentials.

The agent cannot directly set trusted check results, budget counters, overall success, or evaluation verdicts. It submits analysis and proposed conclusions; the service validates them against actual artifacts and check executions.

### 4.3 Tool contracts

All paths are logical workspace-relative paths. No tool accepts an unrestricted shell command or host path.

| Tool | Arguments / result | Constraints |
|---|---|---|
| `list_files` | Optional directory prefix; returns allowed files | Consumer source and supplied inputs only; bounded/paginated output |
| `read_file` | Path, optional line window; returns numbered text | Allowed text files only; 200 lines and 32 KiB maximum per response by default |
| `search_code` | Literal query, optional source prefix; returns paths/line references | Consumer source only; bounded matches; no shell execution |
| `apply_patch` | Unified diff plus short rationale; returns revision/hash or validation failure | Repair stage only; one atomic multi-file submission counts as one patch attempt |
| `run_checks` | No arbitrary command; returns predefined suite outcome and bounded log references | Repair stage only; Docker runner; no independent evaluation access |
| `submit_analysis` | Structured changes, evidence, affected locations, repair scope, manual work | Analysis stage only; persists validated checkpoint |
| `finish_repair` | Structured change summary and remaining work | Repair stage only; service performs finalization and derives outcome |

Expose only read tools and `submit_analysis` during analysis. Repair enables edit/check tools. Serialize tool executions that touch workspace state; do not run patches and checks concurrently even if the model requests them together.

Patch validation rejects absolute paths, traversal, symlink escapes, protected files, binary patches, and edits outside the allowlisted consumer source. Count rejected patch submissions against the attempt limit. Validate the full patch before changing any files, and associate every accepted revision and check run with a content hash.

Development and evaluation tests, contracts, fixtures, runner configuration, and secrets are never editable. Independent evaluation files/results are not readable by agent tools. Development check outputs may be returned; development test source is not part of the default read surface.

## 5. Fixed budgets and termination

These are proposed engineering starting values from the discussion, not industry standards. Implement them centrally as versioned product policy. No UI field, CLI flag, model tool, or environment variable may raise them for ordinary migrations.

| Budget | Fixed starting limit |
|---|---:|
| Outbound model request attempts, including retries | 12 per migration |
| Tool executions, including rejected calls and stage-submission tools | 30 per migration |
| Patch submissions, including rejected patches | 3 per migration |
| Each model request | 90 seconds |
| Each development check execution | 60 seconds |
| Total active migration duration | 10 minutes |

Additional implementation defaults: cap analysis at 5 model requests within the shared 12-request limit, leaving room for repair; cap development check executions at 4, reserving one if a final changed revision remains unchecked. Up to two transient request retries are allowed within the overall 12-request budget. Respect `Retry-After` when it fits the remaining deadline; daily exhaustion and authentication errors stop rather than repeatedly retrying.

- Budget accounting spans analysis and repair. Review waiting time is excluded; provisioning, model waits, tool execution, and retry delays during active stages are included.
- A patch submission can change multiple files. Three tool edits are three attempts even if the model describes them as one conceptual repair.
- Before each operation, check counters and deadline. Its timeout is the smaller of its own cap and remaining run time.
- Enforce deadlines in the supervisor and runner, not just in prompts. Stop/kill timed-out containers and terminate worker process groups as required. Allow a bounded cleanup grace of at most 10 seconds; report cleanup failures.
- On exhaustion, generate reports from saved state without an extra model call. If the final revision was not checked, mark verification incomplete. Preserve prior check results with their revision hashes.
- Independent evaluation has a separate maximum of 2 minutes per case, with 60 seconds per test process and bounded cleanup. It uses no model requests and must never resume repair.
- A dedicated developer benchmark harness may lower the patch cap to 1 for the specified single-attempt comparison. It cannot raise product ceilings; this is not a user-facing budget setting.

At 12 requests/run, 50 daily requests permit approximately four full-budget migrations if no other usage occurs. Live testing must therefore be deliberate; deterministic development tests use scripted model responses and are clearly distinguished from live-model evidence.

## 6. Docker runner and workspaces

Run the backend and agent on the host for the initial local setup. Run consumer code and its local HTTP mock service in disposable containers.

- Build dependency images ahead of migration execution. No package installation or dependency fetching during checks.
- Run containers as non-root, without privileged mode or the Docker socket, with capabilities dropped and `no-new-privileges` enabled.
- Default per consumer/test container: 1 CPU, 512 MiB memory, 128-process limit, read-only root filesystem, and bounded temporary writable storage. Make source/test mounts read-only to executed consumer code.
- Patch operations occur in the host-managed disposable source copy; test containers execute its current revision. Never mount the original consumer into execution containers.
- Give each run an internal Docker network containing only its consumer/test container and mock API. No external egress, host networking, or published mock-service ports. The backend can use container health checks/exec for readiness.
- Mount only the source snapshot and development checks needed for that execution. Do not mount the project root, backend configuration, model key, or evaluation files.
- For independent evaluation, use fresh containers and a separate runner context. The evaluation harness holds its check definitions outside the consumer container and exercises the consumer through its defined command/HTTP behavior. Hidden check definitions and reports remain unavailable to the agent and consumer filesystem.
- Collect bounded stdout/stderr, exit codes, timestamps, timeout flags, and source revision hashes. Store full logs only within configured size caps and mark truncation.
- Use run labels for deterministic cleanup and restart reconciliation. Persist report/patch artifacts before workspace cleanup.

Only trusted bundled consumers are supported. These controls reduce execution exposure; the MVP must not claim to safely execute arbitrary untrusted repositories.

## 7. Run state and report semantics

Keep lifecycle, repair outcome, development verification, and independent evaluation as separate fields.

### 7.1 Lifecycle

```text
created → analyzing → awaiting_review → repairing → finalizing → finished
                    └────────────────→ repairing  (auto)
          analyzing ─────────────────→ finalizing  (no-op/manual-only)

Any active stage → finalizing → finished            (budget/provider/tool failure)
Any active stage → interrupted                      (unrecoverable worker interruption)
```

Implementation transitions must use database transactions. A second Generate repair click must never start a second worker. Return the existing run state when that transition was already accepted. A separate completed evaluation updates evaluation metadata, not the frozen migration lifecycle or budget.

### 7.2 Repair outcomes

| Outcome | Meaning |
|---|---|
| `no_change_needed` | Analysis found no required consumer edits; patch is empty. Verification is reported separately. |
| `manual_action_required` | Required work is documented, with no automatic edits delivered. |
| `checks_passed` | Final changed revision passed required development checks and no known manual work remains. This does not imply independent evaluation passed. |
| `partial_repair` | A patch implements supported work and documented manual work remains. Report evidence and residual check failures; do not imply end-to-end success. |
| `repair_failed` | Supported repair attempts failed or produced a known regression without a defensible partial result. |
| `verification_incomplete` | Available evidence is insufficient to classify the final work because checks/analysis were interrupted or could not finish. |

Development verification: `not_run`, `passed`, `failed`, or `incomplete`. Independent evaluation: `not_run`, `passed`, `failed`, `incomplete`, or `invalid` (e.g. protected inputs changed).

Also record a termination reason such as `completed`, `manual_work`, `budget_exceeded`, `provider_rate_limited`, `provider_error`, `tool_error`, or `worker_interrupted`.

A partial patch whose full suite fails because of documented remaining work may be retained. A known unrelated regression must be exposed and must prevent classification as a successful repair. When attribution is uncertain, say so and use `verification_incomplete` rather than inventing evidence.

### 7.3 Persistent report schema

Use a versioned Pydantic schema and generate its JSON schema. Required top-level fields:

```text
schema_version, run_id, mode, sample_id, scenario_id
created_at, started_at, finished_at, lifecycle, termination_reason
inputs: old/new contract hashes, consumer hash, notes hash, API versions
model: requested_id, actual_id, provider, settings, SDK version
budget: policy_version, limits, used_requests, used_tools,
        used_patch_attempts, used_checks, active_seconds
changes[]: id, kind, description, evidence[], affected_locations[],
           disposition, repair_summary, verification_refs[]
manual_actions[]: change_id, required_work, affected_locations[],
                  unresolved_decision, blocking_effect
patch: artifact_id, base_hash, final_hash, edited_files[], empty
development_checks[]: id, revision_hash, suite, exit_code,
                      status, duration, log_artifact_id, truncated
outcome, development_verification
usage: input_tokens, output_tokens, other_provider_usage, complete
artifacts[], warnings[]
evaluation: verdict, artifact_id, evaluated_revision_hash
```

Unavailable usage values are `null`, not zero. Where only some requests return usage, mark it partial. Evidence must reference actual input paths/JSON pointers or source line ranges. Check results come from runner records, not model claims. The report generator must work when the model never produces a final answer.

Required artifacts: `analysis.json`, `report.json`, `report.md`, `patch.diff` (possibly empty), development logs, and independent `evaluation.json` after evaluation. Keep per-revision patch/check metadata for diagnosis. Generate the final diff against the original snapshot, not merely the latest attempt.

## 8. API, CLI, and UI contracts

### 8.1 Shared Python service

Provide equivalent operations to `create_run(request)`, `start_analysis(run_id)`, `request_repair(run_id)`, `get_run(run_id)`, `list_events(run_id, after_seq)`, and `get_artifact(run_id, artifact_id)`. Both adapters use these operations and the same schemas/state transitions.

### 8.2 HTTP API

| Endpoint | Behavior |
|---|---|
| `GET /api/health` | Backend readiness and non-secret prerequisite status |
| `GET /api/samples` | Registered consumer choices |
| `GET /api/scenarios` | Bundled scenarios and contract defaults |
| `POST /api/runs` | Multipart request with `sample_id`, optional `scenario_id`, `mode`, optional old/new contract files, and notes; snapshots inputs and returns `202` with run ID |
| `GET /api/runs` | Recent saved runs |
| `GET /api/runs/{id}` | Lifecycle, analysis, outcomes, budget summary, artifact references |
| `GET /api/runs/{id}/events?after_seq=N` | Ordered persisted progress/tool-summary events after a cursor |
| `POST /api/runs/{id}/repair` | Transactionally accepts the review checkpoint; `202`, or current state if already accepted |
| `GET /api/runs/{id}/artifacts/{artifact_id}` | Download only a registered artifact belonging to the run |

Use `404` for unknown IDs, `409` for incompatible lifecycle/busy execution, `413` for oversized uploads, `422` for invalid input, and `503` for unavailable prerequisites. Do not expose stack traces or credentials. Browser retries of creation should use a persisted idempotency key to avoid duplicate runs.

Bind FastAPI to loopback. During development, permit only the expected local Vite origin; validate host/origin on mutation requests and accept no wildcard CORS. For packaged local use, serve built frontend assets from FastAPI.

### 8.3 CLI target

```bash
api-maintainer doctor
api-maintainer scenarios
api-maintainer run --scenario endpoint-rename --mode review
api-maintainer run --scenario endpoint-rename --mode auto
api-maintainer repair <run-id>
api-maintainer status <run-id>
api-maintainer export <run-id> --output ./migration-output
api-maintainer evaluate <run-id>
```

Also accept `--sample`, `--old-spec`, `--new-spec`, and `--notes-file` for supported custom inputs. There are no normal-user budget flags. `run` and `repair` stream persisted progress until a checkpoint or terminal state; print run ID and artifact locations. Define documented exit codes: 0 for checks-passed/no-change, 2 for awaiting review/manual/partial work, 1 for failure/incomplete execution. Independent evaluation has its own exit status.

### 8.4 Web UI

Implement three views:

1. **Run form:** sample/scenario, old/new specifications, optional notes, and Review first/Automatic selector. Explain that generated edits remain in a copy. Fixed limits can appear in a concise informational help area, without editable controls.
2. **Run details:** lifecycle/progress, evidence-backed changes, affected files, analysis and manual work, Generate repair when applicable, source diff, actual check results, evaluation verdict if present, and downloads.
3. **Run history:** recent runs with mode, outcome, timestamps, and links.

Poll events/state approximately once per second while active and stop at a terminal state or review checkpoint. On page refresh, load by run ID from persistent storage. Disable duplicate action clicks and handle server-side idempotency. Show partial repair and manual work prominently; do not use an overall success badge merely because a patch exists.

Display concise tool actions and evidence summaries, not private model reasoning. Never expose raw credentials, backend internals, or host paths in product messages.

## 9. Data layout and repository structure

Suggested source layout:

```text
backend/
  pyproject.toml
  src/api_maintainer/
    api/  cli/  migration/  agent/  tools/
    contracts/  runner/  reports/  storage/  evaluation/
  tests/
frontend/
  package.json
  src/
samples/bookstore/
  consumer/  contracts/  mock_service/  development_checks/
evaluation/
  checks/  benchmark_cases/
docker/
docs/
PRD.md
TECHNICAL_PRD.md
```

Local runtime data goes under an ignored `.local-data/` root by default:

```text
.local-data/
  runs.sqlite3
  runs/<run-id>/
    inputs/  original/  workspace/  artifacts/  logs/
  private-agent-state/<run-id>/
  evaluations/<evaluation-id>/
```

SQLite stores lifecycle/events/counters and artifact references. Use atomic file writes and transactions so a completed state never points to a partially written report. Source snapshots and inputs are immutable; only allowlisted files in `workspace` change.

Persist awaiting-review snapshots until explicitly cleaned up. Retain completed reports, patches, and logs by default. A developer cleanup operation can remove disposable resources but must not silently delete reviewable artifacts. Git-ignore local data, keys, environments, dependencies, and generated build outputs.

## 10. Scenarios and evaluation

Use the original six scenarios plus one mixed acceptance case needed by the partial-repair decision:

| ID | Scenario | Expected behavior |
|---|---|---|
| S1 | Endpoint rename | Generated source repair; independent behavior checks pass |
| S2 | Response-field rename | Generated source repair; independent behavior checks pass |
| S3 | Nested price with documented cents conversion | Correct extraction/conversion; 2,000 cents displays as 20 dollars and two copies total 40 dollars |
| S4 | S3 through a wrapper plus unrelated same-name field | Trace relevant callers and preserve unrelated behavior; record honest failure if unresolved |
| S5 | Optional-field addition | Empty patch and correct no-change outcome |
| S6 | New required field with no supplied input source | Actionable manual-work documentation and no fabricated value |
| S7 | Endpoint rename plus S6 | Supported endpoint repair, retained patch, documented remaining input work, transparent residual verification failures |

For repair cases, establish that the original consumer passes against the old mock service and fails for the intended reason against the new one. For S5 verify compatibility without changes. For S6 verify the missing-input failure and expected documentation. S7 requires component-level evidence that the endpoint change was addressed while full migration remains incomplete.

Run independent evaluation only after freezing a final revision. Its results attach to that hash. Do not reopen the repairing agent based on hidden failures. Protected-source/test/contract hashes are checked before and after execution; violations invalidate evaluation.

The benchmark compares 1 patch attempt with up to 3, holding fixtures, model ID/settings, initial inputs, and other ceilings constant. Report actual request/tool counts rather than claiming equal compute. Report each case, regressions, repair success among fully repairable cases, correct no-op/manual outcomes, partial outcomes, time, available usage, and trial count. Provider outages are execution failures/incomplete results, not evidence that code reasoning was incorrect.

## 11. Verification strategy

Primary integration tests invoke the shared migration service on clean fixtures, inspect reports/patches, and execute the resulting consumer against the target mock API. Avoid tests that require an exact generated diff or mirror internal prompts.

Use scripted model responses for deterministic tests of tool execution, patch restrictions, retries, lifecycle transitions, report derivation, and API/UI behavior. Label these as orchestration tests; they do not establish real model repair capability.

Required focused checks:

- Patches cannot traverse paths, follow symlinks, edit protected files, or partially apply after validation failure.
- Review first performs no source edits before Generate repair; duplicate clicks cannot duplicate execution.
- Budgets span both stages and count SDK retries; review wait does not consume active time.
- Hanging checks/model calls stop within limits and cleanup grace; partial artifacts survive.
- Final check results correspond to the final source hash; stale success never labels a later unchecked patch as passed.
- Restart preserves awaiting-review runs and marks abandoned active workers interrupted.
- Original consumer, contracts, fixtures, and test inputs remain unchanged.
- Independent evaluation data is unavailable to the agent and never becomes repair feedback.
- API and CLI return equivalent outcomes/report structure.
- Browser flow covers both modes, refresh recovery, invalid input, no-op, manual-only, partial repair, provider exhaustion, and artifact downloads.

Live-model acceptance must demonstrate actual model-generated successful repairs for S1–S3. Do not substitute scenario-ID-based patch selection. Record S4 even if unsuccessful. Complete S5–S7 with the required outcomes and retain benchmark artifacts.

## 12. Implementation milestones and completion gates

| Milestone | Deliverable | Completion evidence |
|---|---|---|
| 1. Foundation | Repository scaffold, dependency locks, schemas, CLI doctor, mock API, Docker images, baseline consumer | Clean setup runs old/new behavior checks; isolation and prerequisites are verified |
| 2. Model integration | Strands/OpenRouter adapter, free model selected, read tool, request accounting | Real tool-call round trip and an actual generated edit; model/settings recorded |
| 3. Analysis and persistence | Contract diff, source tools, SQLite/events, immutable snapshots, analysis report | CLI produces evidence-backed analysis; review checkpoint survives restart |
| 4. Repair | Patch tool, check tool, budgets, final diff/report, automatic/review transitions | S1 real generated repair passes independent checks; original remains unchanged |
| 5. Outcomes | Manual work, partial repair, timeout/failure reporting, restart cleanup | Deterministic S5–S7 and failure-path tests pass; no invented required value |
| 6. Web UI | FastAPI endpoints, React views, polling, diff/downloads | End-to-end browser flow works in both modes and across refresh |
| 7. Evaluation and release | All scenarios, separate evaluator, 1-vs-3 benchmark, setup/demo docs | Live S1–S3 succeed; every case has recorded evidence; required tests pass |

The implementation is complete only when a fresh local setup can run documented CLI and UI workflows; both modes and partial/manual outcomes work; artifacts remain reviewable; and the stated live-model and independent-evaluation requirements are satisfied. No quota workaround or fabricated benchmark result may replace those checks.

## 13. Deferred work

Hosting, authentication, multiple users, arbitrary repositories/languages, live provider monitoring, production API migrations, automatic application of patches to originals, migration PR creation/merging, deployment, interactive clarification chats, multi-agent collaboration, model routing, paid fallbacks, vector databases, and distributed task queues are out of scope.

## 14. Remaining implementation gates

These do not require reopening the settled architecture:

1. Choose and verify a currently available free tool-calling model through Strands; record the exact model and compatible dependency versions.
2. Implement and verify the selected Strands hooks/state-restoration APIs against the pinned SDK; do not assume framework defaults enforce our budgets.
3. Confirm Docker networking/resource behavior on the development machine and record clean-setup instructions.
4. Measure the proposed 12-request/30-tool/3-patch limits on the fixtures. If they consistently prevent meaningful repairs, propose an evidence-backed policy revision rather than silently raising them.

## 15. Reference documentation

These references informed the technical discussion. They describe external capabilities and policies that must be rechecked when dependencies/model IDs are pinned.

- [Strands integrations, including OpenRouter](https://strandsagents.com/integrations/)
- [Strands setup and provider selection](https://strandsagents.com/docs/user-guide/quickstart/overview/)
- [Strands tools](https://strandsagents.com/docs/user-guide/concepts/tools/)
- [Strands hooks](https://strandsagents.com/docs/user-guide/concepts/agents/hooks/)
- [OpenRouter free model variants](https://openrouter.ai/docs/guides/routing/model-variants/free)
- [OpenRouter free router behavior](https://openrouter.ai/docs/guides/routing/routers/free-router)
- [OpenRouter FAQ and free request limits](https://openrouter.ai/docs/faq)
- [OpenRouter rate-limit guidance](https://openrouter.zendesk.com/hc/en-us/articles/39501163636379-OpenRouter-Rate-Limits-What-You-Need-to-Know)
- [Vite setup and React/TypeScript template](https://vite.dev/guide/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)

Framework examples such as [OpenAI's 10-turn default](https://openai.github.io/openai-agents-python/ref/result/) and [LangChain classic's 15-iteration default](https://reference.langchain.com/python/langchain-classic/agents/agent/AgentExecutor/max_iterations) are reference points, not an industry standard or a substitute for measuring this application.
