# Verification evidence and open acceptance gates

Recorded during implementation on September 10–11, 2026. The original repository contained only PRD.md, TECHNICAL_PRD.md, ignore rules and skill metadata. Existing specification edits were preserved.

## Verified

- Python 3.12.10 environment resolved successfully; `backend/uv.lock` records exact dependencies, including Strands Agents 1.55.1 and OpenAI SDK 2.54.0.
- Frontend dependencies locked in `frontend/package-lock.json`; TypeScript and Vite production build pass. npm reported zero known vulnerabilities at installation.
- `pytest backend/tests -q`: **46 passed, none skipped** (34 core tests and 12 real Docker tests, run in full-suite and targeted follow-up passes). The single warning is an upstream Starlette/AnyIO deprecated alias.
- Ruff checks and formatting pass.
- All seven bundled OpenAPI contracts pass strict OpenAPI 3.0 validation.
- Scripted tests cover review checkpoint persistence, no edits before approval, shared stage counters, idempotency/lease exclusion, protected files and symlinks, atomic validation failure, stale-check rejection, no-op/manual/partial outcomes, immutable final evaluation hashes, provider exhaustion with zero retries, bounded process output, model-body timeouts, supervisor termination, and CLI/API report equivalence.
- The actual pinned Strands SDK dispatches read and patch tools using scripted OpenAI HTTP responses. Tool results return through the SDK; analysis submission cancels subsequent model calls through its supported hook. Rejected patch arguments consume the patch allowance. These are SDK integration tests, **not live-model repairs**.
- Browser verification against the production server confirms the form loads, all seven scenarios appear, Review first is the default, and absent prerequisites produce an actionable error without a run.
- Browser verification against a separate test-only server covers review → refresh → repair, automatic completion, no-change/empty patch, manual-work/empty patch, partial patch with failed full checks, saved history, and a patch download event. Every fixture run displays a scripted-evidence warning.
- Mobile form inspected at 390 × 844; document width and scroll width both 390, with no horizontal overflow. Desktop layout and browser console inspected. No JavaScript errors observed in the successful workflow.
- The public OpenRouter catalog currently lists `nex-agi/nex-n2.5-pro:free` with zero prompt/completion pricing and tool support. Exact catalog evidence is in `model-catalog-check.json`. Earlier candidates were absent and were removed from the allowlist.

## Live testing fixes (September 11)

- Analysis tool now advertises the full nested schema, including its required `analysis` wrapper. SDK tests verify the transmitted schema and recovery from a missing wrapper.
- Evidence accepts both plain RFC 6901 pointers (`/info/version`) and fragment pointers (`#/info/version`). External and unresolved references remain rejected.
- Patches accept displayed `source/` paths while retaining scope, traversal, duplicate-file and atomicity restrictions.
- Rejected SDK tools produce safe execution events; failures show counters and termination categories. Raw tool arguments are not published.
- Missing-image errors include the exact build command. The image was rebuilt and all Docker tests executed; the reason for its repeated disappearance has not been established.
- Four known repairs pass actual Docker checks. These are deterministic integration tests, not evidence of live model quality.
- Existing failed live runs remain preserved; they are not rewritten as successes.

## Remaining acceptance work

The configured live model previously completed analysis but failed subsequent runs on patch paths and evidence formats. New live acceptance runs for all seven scenarios and independent evaluation remain pending explicit authorization to send sample code/contracts/notes to OpenRouter after automatic approval review blocked a retry. The one-vs-three live benchmark is also pending. No new live-model success is claimed.

An upstream Starlette/AnyIO deprecation warning remains; it does not fail tests.

## Deliberate implementation limits

- Existing allowlisted Python files only; no new files, deletions, renames, binary hunks or fuzzy patch matching.
- Consumer/fixture family is shared across the scenarios and includes the wrapper and unrelated membership price. S4 is not yet a separately calibrated difficulty benchmark.
- Custom specs remain tied to a bundled mock scenario; a passing fixture suite is not validation of an arbitrary external API.
- A fresh repair-stage agent receives saved analysis and source context, rather than replaying the analysis agent's full private transcript. Counters and run identity are preserved.
- Provider retries are disabled, within the specification's “up to two” allowance. Rate limits stop immediately with a report.
- For S7, partial success attribution is deliberately narrow: an endpoint-only source change plus recorded required-country HTTP validation. More extensive unverified changes remain incomplete.

The technical PRD's overall completion gate has **not** been met until the pending live/Docker evidence exists.

## Repository-first implementation verification

The primary UI now accepts a local repository and previous/new OpenAPI documents, automatically identifies change types, and pauses for editable review. Reanalysis creates a linked run from the original snapshot. Demos are optional. **54 tests passed, none skipped**, including real repository Docker tests that demonstrate both a passing and failing client test. TypeScript/Vite build and Ruff pass. Browser DOM checks confirm the repository form is default and the scenario dropdown appears only in demo mode. No external model calls were made for this implementation verification; live provider reliability remains a separate gate.
