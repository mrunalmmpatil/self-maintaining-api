# Implementation plan

TECHNICAL_PRD.md governs this build. The existing PRD edits are preserved.

1. Scaffold locked Python 3.12 / React TypeScript projects, typed reports and fixed budgets.
2. Add seven bookstore contracts, a versioned HTTP mock, baseline consumer, development checks and separate evaluation assertions.
3. Implement contract validation, immutable snapshots, bounded read tools and atomic source-only patching.
4. Persist runs, events, review checkpoints and a single execution lease in SQLite; run agents in supervised subprocesses.
5. Integrate Strands with an explicitly allowlisted free OpenRouter model, counted HTTP attempts and serial restricted tools.
6. Implement hardened Docker execution, final-revision checks, deterministic outcome derivation and artifacts.
7. Expose the shared service through CLI and loopback FastAPI, then implement form/history/details with durable polling and downloads.
8. Exercise orchestration, security boundaries, lifecycle and UI; document fresh setup and remaining live acceptance gates.

## Acceptance evidence

Deterministic scripted-agent tests establish orchestration only. Live Strands tool-read/edit evidence, Docker isolation, S1–S3 real repairs, S4 outcome and a 1-vs-3 benchmark require actual executions. Never substitute canned patches for live-model evidence.

Initial environment: repository contains specifications only; Python 3.11 on PATH; Docker CLI installed but daemon unavailable; Node available in Codex bundled runtime. Exact verification results and unresolved gates are recorded in VALIDATION.md.

## Implemented in this change

- [x] Locked backend/frontend scaffold, typed report schema and CLI doctor.
- [x] Seven contracts, shared bookstore consumer and versioned HTTP mock.
- [x] Contract validation/diff, immutable snapshots and restricted atomic patches.
- [x] SQLite runs/events/lease, worker supervisor and restart reconciliation.
- [x] Strands adapter, free-model allowlist, counted requests and serial stage tools.
- [x] Docker development runner, separate evaluation and deterministic reports.
- [x] CLI/API and React form/history/details with polling and downloads.
- [x] Deterministic tests, pinned-SDK integration tests, build and browser verification.
- [ ] Real Docker baseline/isolation checks — runtime unavailable.
- [ ] Live model tool/edit gate and S1–S7 acceptance — backend key absent.
- [ ] Live one-vs-three benchmark and fresh-machine release verification.

See VALIDATION.md for exact evidence and limits. Checked implementation items do not imply that the live acceptance gates passed.
