# Live sample rerun — September 11, 2026

Model: `nex-agi/nex-n2.5-pro:free` via OpenRouter. All seven scenarios used automatic mode and the fixed application. No independent evaluations were run.

| Scenario | Outcome | Development checks | Termination | Run |
|---|---|---|---|---|
| endpoint-rename | checks_passed | passed | completed | 84c2d3a863604593819ff280cd4ffe9f |
| response-field-rename | checks_passed | passed | completed | 511f895fe86443a2a6623f78c8c576f7 |
| nested-price | verification_incomplete | passed | provider_error | ec35fa0d013b4a03a21e9327d54b4775 |
| wrapper-price | verification_incomplete | not_run | tool_error | 5cebeccebf1342d99f1b985a634023bd |
| optional-field | no_change_needed | passed | completed | 03cef67b28394de6b4b995eb50c5f8fd |
| required-input | verification_incomplete | not_run | budget_exceeded | 57efc8c8d4b444a19de503459aff852e |
| mixed | verification_incomplete | not_run | provider_rate_limited | f0e25803c39e4bf7a95c45c824ae871a |

Three scenarios completed successfully. Nested-price delivered a revision that passed development checks, but a provider interruption prevented stage completion. Wrapper-price ended without a valid analysis submission. Required-input cited unresolved evidence pointers and exhausted its five analysis calls. Mixed hit provider rate limiting. These results do not establish reliable acceptance across all default scenarios.

The prior automatic suite passed 46 tests; that is distinct from these live-model outcomes.

## Follow-up verification

After adding bounded initial file context, missing-submission continuation, and file-specific evidence recovery guidance, the automated suite passed **49 tests, none skipped**. Ruff passed. One upstream Starlette/AnyIO deprecation warning remains.

The live nested-price retry (`36b2a585e09a439b8a4f31e6da8f7f88`) was rate-limited on its first model request. No patch or checks ran. The batch stopped; wrapped-price, required-input and mixed were not retried in this batch. Live verification of these latest changes remains pending provider availability.
