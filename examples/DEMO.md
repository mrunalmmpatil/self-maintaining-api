# Demo runbook

Two fixtures, both verified to fail before the migration and pass after it. Neither has
been run against the live model — that is the step you are doing.

| | Fixture | Changes | Target outcome | Use when |
|---|---|---|---|---|
| **A** | `examples/inventory-client` | 5 | `partial_repair`, exit 2 | The real demo. Shows the agent refusing to invent a value. |
| **B** | `examples/inventory-client-lite` | 2 | `checks_passed`, exit 0 | Fallback. Much smaller ask of the model. |

Both start from the same `inventory-v1.yaml`.

---

## 1. Pre-flight

```sh
cd "/Users/mrunalpatil/Desktop/MrunalPatil/Study/Project /09 Sept 2026"
backend/.venv/bin/api-maintainer doctor
```

You need `"ready": true`. If it reports `"image": false`, **run it again before rebuilding** —
this reports a false negative occasionally (20 consecutive checks passed here, so a single
failure is not evidence the image is gone). Confirm with `docker images api-maintainer-python:local`.
Only if it is genuinely absent:

```sh
docker build -t api-maintainer-python:local docker
```

For the web UI:

```sh
npm --prefix frontend run build
backend/.venv/bin/uvicorn api_maintainer.api:app --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000>.

**Only one migration runs at a time.** A single SQLite lease enforces it, so a second
start returns HTTP 409. Do not drive the CLI and the UI at once.

---

## 2. Rehearse fixture A (do this before demo day)

```sh
backend/.venv/bin/api-maintainer run \
  --repo "$PWD/examples/inventory-client" \
  --old-spec examples/specs/inventory-v1.yaml \
  --new-spec examples/specs/inventory-v2.yaml \
  --notes-file examples/specs/migration-notes.md \
  --test-command "python -m unittest discover -s tests -t ."
```

It streams events, then **stops at `awaiting_review` and exits 2**. That pause is a
feature, not a hang — it is the review checkpoint. Note the run id, then:

```sh
backend/.venv/bin/api-maintainer repair <RUN_ID>
backend/.venv/bin/api-maintainer status <RUN_ID>
```

For fixture B, swap `--repo` to `examples/inventory-client-lite`, `--new-spec` to
`examples/specs/inventory-lite-v2.yaml`, and `--notes-file` to
`examples/specs/migration-notes-lite.md`.

---

## 3. What a good run looks like

At the review checkpoint, the analysis should list roughly five changes:

1. Endpoint rename `/products/{id}` → `/catalog/products/{id}` — `repair`
2. Field rename `name` → `title` — `repair`
3. `price` dollars → `price_cents` integer — `repair`
4. New required `region` on the listing — **`manual`**, with a manual action
5. `stock_status` added — `no_change`

Change 4 is the one to narrate. The notes state the correct region depends on the
deployment's market, so the honest result is a documented decision for a human, not a
guessed `"US"`.

After repair, the tests should pass and the outcome should be **`partial_repair`** —
reachable per [reports.py](../backend/src/api_maintainer/reports.py) only with a non-empty
patch *and* passing verification, so it cannot be faked.

Two traps worth showing in the diff if they come up:

- `shipping_price` must stay dollars. A blanket "divide every price by 100" fails
  `test_shipping_price_is_still_dollars_and_is_not_converted`.
- The output key must stay `name` even though the API field is now `title`.

---

## 4. Failure modes you may hit

From [docs/LIVE_RERUN.md](../docs/LIVE_RERUN.md), the configured free model passed 3 of 7
bundled scenarios. Fixture A is a bigger ask than any of them. Expect one of:

| Symptom | Termination | What it means |
|---|---|---|
| Stops on the first model call | `provider_rate_limited` | Free quota. Wait and retry; no automatic retry by design. |
| Stops mid-stage | `provider_error` | Provider dropped the request. Saved patches and checks are kept. |
| Ends without an analysis | `tool_error` | Model never submitted a valid analysis. |
| Counters maxed out | `budget_exceeded` | 5 analysis calls / 20 requests / 6 patches / 1,200s exhausted. |

None of these are bugs — the tool is built to stop honestly rather than retry around a
provider. But they do ruin a live demo, which is why you rehearse.

**If fixture A fails repeatedly, demo fixture B.** Two changes, no cents maths, no manual
action — a much smaller ask, and it ends on a clean green `checks_passed`.

---

## 5. The safety net

Every run persists and replays in full from **Run history** at a stable `#run/<id>` URL —
evidence, diff, check results, artifacts. So:

1. Rehearse until you get a run you like.
2. Write down its run id.
3. If the live run stumbles mid-demo, open the saved one from Run history and keep going.

Your history already holds two known-good bookstore runs from the September 11 batch:
`84c2d3a8...` (endpoint-rename) and `511f895f...` (response-field-rename), both
`checks_passed`.

---

## 6. Reading the result honestly

This is worth saying out loud in the demo, because it is the project's actual thesis:

- `checks_passed` means *the listed development checks passed*. It is not a claim of
  universal correctness.
- Development checks and independent evaluation are **separate verdicts**.
- Independent bookstore evaluation does not apply to a client repository — it is refused
  by design. For fixture A and B the test command is the verification.
- With no test command configured, a run ends `verification_incomplete` on purpose. The
  patch is unverified, and the tool says so rather than implying success.

---

## 7. Resetting between rehearsals

Runs accumulate; nothing needs cleaning for correctness. The originals under
`examples/` are never modified — edits happen in a disposable copy under
`.local-data/runs/<id>/workspace`. To confirm your fixture is still pristine:

```sh
cd examples/inventory-client && python3 -m unittest discover -s tests -t .   # expect failures
```

If a worker is ever killed mid-run, the next CLI or server start reconciles the stale
lease automatically.
