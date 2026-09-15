# Self-Maintaining API — MVP

Status: Original product brief. See [TECHNICAL_PRD.md](TECHNICAL_PRD.md) for the implementation specification incorporating the subsequent design decisions. The technical PRD takes precedence where they differ, including stack, fixed limits, repair modes, manual work, and partial repairs. Historical publication notes below describe the workspace before GitHub setup.

## Problem Statement

When an API changes, a developer must understand the change, locate affected application code, implement a migration, and verify that application behavior still works. An endpoint can keep returning successful responses while downstream calculations or displays become incorrect. This project investigates whether an agent can perform a small, reproducible migration and provide useful evidence about its correctness.

## Solution

Build an API-maintenance agent with both a command-line interface (CLI) and a local web UI. Both interfaces use the same agent and accept a local Python consumer application, old and new API specifications, and optional migration notes. It identifies supported changes, locates affected code, generates a patch in an isolated working copy, runs permitted development checks, and returns a reviewable patch and structured report.

Demonstrate the workflow against a real local HTTP mock service with controlled API versions. Show the consumer working against the old version, failing against the changed version, and recovering after a successful repair. Use independent evaluation checks to assess the final patch. Report uncertainty or failure instead of treating every generated patch as a successful migration.

## User Stories

1. As a developer, I want to start a migration from the CLI or web UI using a supported application, old/new API specifications, and optional notes, so that I can use the interface I prefer.
2. As a developer, I want to see API changes and affected code with supporting evidence, so that I understand what needs repair.
3. As a developer, I want the agent to generate a patch in a separate copy, so that I can review a repair without changing my original application.
4. As a developer, I want the agent to run checks and retry within a limit, so that it can improve a failed repair without running indefinitely.
5. As a developer, I want to see progress, test results, and unresolved information, so that I know whether the migration succeeded or needs my attention.
6. As a developer, I want to inspect and export the patch and report, so that I can review and apply the result myself.
7. As a developer, I want harmless changes to produce no edits and missing information to produce a clear explanation, so that the agent avoids unnecessary or invented repairs.
8. As a project author, I want repeatable mock scenarios and independent evaluation checks, so that I can demonstrate and measure repair correctness.

## Implementation Decisions

- The following technical choices are proposed MVP defaults synthesized from the discussion, not previously confirmed stack decisions.
- Scope the initial consumer to Python and the API to a local bookstore HTTP service. Use a small application with request handling, a wrapper, and downstream price calculations/display. No existing application code, domain glossary, ADRs, or test conventions were found in the workspace.
- Use explicit old/new OpenAPI contracts and optional migration notes as inputs. Continuous discovery is deferred. Semantic facts such as cents versus dollars must come from supplied evidence, not field-name guesses.
- Use four functional components: scenario/mock service runner, change and impact analysis, bounded patch/repair orchestration, and report/evaluation runner. Keep them in a single application; separate deployed services are unnecessary.
- Use one shared migration-run interface as the integration boundary. Both the CLI and the web backend invoke the same agent workflow. Inputs include the supported consumer location, contracts, optional notes, scenario identifier, and repair budget. Outputs include a run identifier, progress, a patch, a machine-readable report, and a readable summary.
- Provide a local web UI with a run form and a run-details view. The form selects a bundled scenario or supported local sample application and accepts old/new specifications and optional notes. The details view shows progress, change evidence, affected files, the proposed diff, check results, unresolved information, and patch/report downloads.
- Have the local web backend start runs asynchronously and expose run status and artifacts by identifier. Store run metadata and artifacts locally so refreshing the page can recover the current run view. The CLI exposes equivalent inputs and results; migration logic is not duplicated in the browser.
- Bind the web service to the local machine. Keep model credentials in the backend and constrain application selection to supported local samples. Hosting, authentication, and arbitrary repository uploads are deferred.
- The report records source and target versions, changes and evidence, affected locations, unresolved assumptions, attempts, check results, elapsed time, model identifier, available token usage, and final status. Unavailable usage data remains explicitly unavailable.
- Keep migration status separate from independent evaluation verdict. Migration statuses are no change needed, needs clarification, checks passed, repair failed, and verification incomplete. Checks passed means only the listed development checks passed; it does not claim universal correctness. The evaluation runner adds its independent verdict after the agent finishes.
- Implement a single model adapter and configure model access outside source control. Model/provider selection remains an implementation choice. Do not expand the MVP into provider routing or a generic agent framework.
- Generate patches against a disposable copy. Restrict edits to consumer source; exclude development/evaluation tests, contracts, fixtures, and runner configuration from permitted patch targets. Validate patch paths before applying them.
- Execute repository code only in a constrained disposable runner without model credentials or evaluation files. Set explicit process timeouts and terminate timed-out process groups. An isolated directory alone is not a security sandbox. Only the project's trusted sample consumer is supported initially; arbitrary untrusted repositories are out of scope.
- Development checks may provide feedback to the agent. Independent evaluation runs afterward in a separate context and never feeds hidden failures into repair attempts for that run.
- Default to at most three patch attempts per run, with configurable bounded process and overall run timeouts. Preserve the final patch and failure evidence when the budget expires.
- Require an explicit clarification result when the migration needs a value the application does not have. Do not silently supply a country, currency, or other business default.
- Produce local artifacts only. Creating migration pull requests, merging changes, and deploying repaired applications are deferred.
- Use six initial scenarios: endpoint rename; response-field rename; nested price with documented cents conversion; the same price change through a wrapper with an unrelated price field present; optional-field addition requiring no change; and a new required request value requiring clarification. Reuse one service and consumer fixture family.

## Testing Decisions

- Proposed primary testing boundary: invoke the shared migration-run interface on a clean consumer and supplied API contracts, then inspect its report and patch and run the resulting application against the target mock service. Cover the agent behavior once at this shared boundary, with interface checks for CLI invocation and the browser flow.
- Prefer externally visible behavior over prompts, internal helper calls, exact patch text, or a prescribed list of modified files. Several different repairs can preserve the same behavior.
- Exercise change analysis, impact analysis, patch generation, and orchestration together through this boundary. Add focused tests only where needed for patch-path restrictions and execution budget enforcement.
- Establish each repair fixture by proving the starting consumer passes against the old service and fails for the intended reason against the new service. Keep no-op and clarification scenarios separate from repair scenarios.
- Keep independent evaluation checks outside the agent's accessible repair context. Verify calculations, displayed values, representative edge cases, and previously working behavior. A documented 2,000-cent price must display as 20 dollars, and two copies must total 40 dollars.
- Include an unrelated field with the same name to expose overly broad replacements. Check behavior rather than insisting that the agent use a particular internal architecture.
- Ensure no-op input produces no source changes. Ensure missing required business information produces an actionable clarification and is not counted as a failed automatic repair merely because no patch was produced.
- Inspect final source changes to confirm protected files were not altered. A run that changes evaluation inputs or weakens tests is invalid.
- Compare one patch attempt with a maximum-three-attempt development-test-guided loop, using identical fixtures, model settings, and starting inputs. Record the different budgets rather than implying equal compute.
- Report per-scenario outcomes, automatic repair successes among repairable cases, regressions, correct no-op/clarification outcomes, attempts, time, and available usage. Repeat runs if time permits and state the run count; avoid broad statistical claims from this small benchmark.
- Verify the web flow from input selection through starting a run, viewing progress, inspecting the final diff/check results, and downloading artifacts. Verify invalid inputs, failure and clarification states, and recovering the run view after refresh. Verify the CLI returns the same report structure for equivalent inputs.
- There is no existing testing prior art in this workspace. The proposed shared migration-run boundary is new.

## Out of Scope

- Automatic monitoring of external providers, web scraping, or changelog subscriptions.
- Real provider migration support in the initial version.
- Arbitrary languages, large repositories, or general-purpose static code analysis.
- Production credentials, account migrations, database migrations, or application deployment.
- Autonomous merging, GitHub application installation, and migration PR creation.
- Authentication, collaboration, multi-tenancy, or a hosted service. The local web UI is included.
- General pagination, authentication-flow, streaming, and asynchronous API migrations beyond the defined fixtures.
- Claims that passing tests proves correctness for all inputs or that a small local benchmark establishes broad API migration reliability.

## Further Notes

### Implementation milestones

1. Scaffold the mock service, consumer, contracts, and reproducible old/new behavior checks.
2. Implement the shared migration-run interface, CLI, change report, and impact analysis for the first two scenarios.
3. Connect the model adapter, isolated patch workspace, and reviewable patch output; complete one real generated repair end to end.
4. Add the bounded development-test repair loop and honest failure/clarification reporting.
5. Build the local web UI and backend for starting runs, viewing progress and results, and exporting artifacts.
6. Finish the six scenarios and separate evaluation runner; compare the single-attempt and repair-loop approaches.
7. Verify both interfaces, repair observed defects, document setup and limits, and prepare the repeatable demonstration.

### Acceptance criteria

- A fresh setup can run the documented baseline and migration workflow through both the CLI and local web UI.
- The web UI supports starting a run, displaying progress, inspecting the diff and check results, and downloading the patch and report. Refreshing recovers the run view, and failed or clarification-needed runs are clearly explained.
- Both interfaces use the same agent workflow and report format.
- At least the endpoint, field-rename, and nested-price scenarios demonstrate a model-generated patch that passes independent behavior checks, with no hardcoded scenario-specific patch selection.
- The wrapper scenario has a recorded outcome, including an honest failure if unresolved; regressions are visible.
- The no-op and missing-information cases produce their appropriate outcomes without invented business values.
- Failed or timed-out runs stop within their configured budgets and retain useful reports.
- A results artifact records every benchmark case and distinguishes development checks from independent evaluation.
- No source edits are applied to the original consumer automatically, and protected test inputs remain unchanged.

### Publication and open confirmations

- The workspace is not a Git repository and contains no application code or tracker configuration. The referenced setup-matt-pocock-skills workflow was not found in the local skill locations inspected.
- Publish this PRD to the user's selected project issue tracker with the ready-for-agent label once the destination is identified and the proposed testing boundary is confirmed.
- Deliver both the CLI and web UI as part of the MVP.
