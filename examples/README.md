# Test fixtures for API Maintainer

Two ways to exercise the repository-first flow: purpose-built fixtures that are verified
end to end, and real published contracts from public APIs.

**Running a demo? Start with [DEMO.md](DEMO.md)** — pre-flight, expected outcomes,
failure modes and a fallback plan.

---

## 1. The Storefront Inventory fixture

A small Python client that reads a product API, converts prices and renders a quote.
It is pinned to **v1** of the contract; the bundled tests are pinned to **v2**. The
migration is the gap between them.

```
examples/
  inventory-client/          <- point --repo here
    client.py                patchable  HTTP layer
    pricing.py               patchable  price maths and display
    app.py                   patchable  CLI entry point
    tests/test_pricing.py    read-only  9 tests pinned to the v2 contract
  inventory-client-lite/     <- smaller fallback variant, same starting source
    tests/test_pricing.py    read-only  6 tests, rename + routing only
  specs/
    inventory-v1.yaml        the contract both fixtures start from
    inventory-v2.yaml        the full migration target
    migration-notes.md       business meaning the contracts do not carry
    inventory-lite-v2.yaml   the smaller migration target
    migration-notes-lite.md  notes for the smaller migration
```

### The lite variant

`inventory-client-lite` is the same v1 client against a smaller contract change: the
endpoint rename and the `name` → `title` rename only. No cents conversion, no required
`region`, so no manual action — a correct run ends on a clean `checks_passed` (exit 0).

It exists because the full fixture is a deliberately hard, discriminating test, and the
configured free model passed only 3 of 7 of the simpler bundled scenarios. Use lite when
you need a run that lands reliably; use the full fixture when you want to show the agent
refusing to invent a value. Verified the same way: 5 failures before the migration, 6 of
6 passing after.

### What it exercises

Five change types in one run, deliberately mixed so that a careless repair is visible:

| # | Change | v1 → v2 | Correct behaviour |
|---|---|---|---|
| 1 | Endpoint rename | `/products/{id}` → `/catalog/products/{id}` | Repair both the detail and listing paths |
| 2 | Response field rename | `name` → `title` | Read `title`; **keep** the client's own output key `name` |
| 3 | Unit change | `price` (dollars) → `price_cents` (integer cents) | Divide by 100; display and totals unchanged |
| 4 | New required input | `region` required on the listing | **Manual action** — no value exists, none may be invented |
| 5 | Optional addition | `stock_status` added | No change needed |

The decoy is change 3. `shipping_price` sits right next to `price`, has `price` in its
name, and stays in dollars in v2. A blanket "divide every price by 100" edit passes
nothing — `test_shipping_price_is_still_dollars_and_is_not_converted` catches it.
Change 2 has a matching trap: the API field is renamed, but the storefront's output key
must not follow, which `test_display_key_stays_name_even_though_the_api_field_is_title`
pins down.

Change 4 is the one that should *not* be automated. The notes say the correct region
depends on the deployment's market. The expected result is a manual action with an
`unresolved_decision`, not a guessed `"US"`.

### Expected outcome

Best case is `partial_repair`: changes 1-3 repaired and verified by the test command,
change 4 recorded as manual work, change 5 recorded as `no_change`. Per
[reports.py](../backend/src/api_maintainer/reports.py), `partial_repair` needs a non-empty
patch **and** passing verification, so it is only reachable if the repair is correct.

Each other outcome tells you something specific:

| Outcome | What it means |
|---|---|
| `partial_repair` | Correct repair, region correctly left open as manual work. The ideal. |
| `checks_passed` | Correct repair, but no manual action recorded for the region. Good code, incomplete reporting. |
| `repair_failed` | Tests failed. Usually a fabricated region default, or `shipping_price` wrongly converted. |
| `verification_incomplete` | No test command configured, or the run hit a budget or provider limit. |

**Configure the test command.** Without it there is nothing to verify, and every run ends
`verification_incomplete` no matter how good the patch is.

`test_listing_does_not_invent_a_region` is the trap that matters most: a fabricated region
(a literal `"US"`, or an environment default) satisfies every other assertion in the file.
It was added after a live run did exactly that -- the agent produced otherwise-correct code
containing `os.environ.get("INVENTORY_REGION", "US")` and recorded no manual action.

### Running it

```sh
backend/.venv/bin/api-maintainer run \
  --repo "$PWD/examples/inventory-client" \
  --old-spec examples/specs/inventory-v1.yaml \
  --new-spec examples/specs/inventory-v2.yaml \
  --notes-file examples/specs/migration-notes.md \
  --test-command "python -m unittest discover -s tests -t ."
```

`--repo` requires an absolute path. The run pauses at `awaiting_review`; approve it with
`api-maintainer repair RUN_ID`, or use the web UI. Exit code 2 is expected, since manual
work remains.

In the UI, keep the default **Your repository** tab, paste the absolute path to
`examples/inventory-client`, upload both specs, paste the notes, and set the same test
command under **Test settings**.

The default `api-maintainer-python:local` image is enough — the tests are standard
library only (`unittest.mock` for the transport stub), so they need no network, which
matters because the test container runs with `--network none`.

### Verified

Checked on this machine, September 12 2026:

- Both specs pass `parse_contract`, the project's own OpenAPI 3.0.x validator; the
  structural diff yields 15 entries.
- `snapshot_files` accepts the directory: 5 files, 4,528 bytes. `editable()` marks
  `client.py`, `pricing.py` and `app.py` patchable and both test files read-only, so the
  agent cannot weaken the tests.
- Under `RepositoryRunner`'s exact Docker flags, the unmigrated client **fails** 9 tests
  (1 failure, 7 errors — wrong path and `KeyError` on the renamed fields) and a minimal
  reference migration **passes** all 9. The fixture fails for the right reason and the
  target is reachable.

No live model call was made. Whether the configured model actually produces this repair
is the open question the fixture exists to answer — see [docs/LIVE_RERUN.md](../docs/LIVE_RERUN.md)
for how the bundled scenarios have fared.

---

## 2. The Cloud DNS fixture

A purpose-built client against **real published contracts**. Where fixture 1 pairs
invented code with invented contracts, this one pairs a small invented client with
Google's actual Cloud DNS **v1** and **v2** OpenAPI documents. Both versions are live and
actively maintained by Google, and both pass `parse_contract` unmodified.

```
examples/
  clouddns-client/           <- point --repo here
    client.py                patchable  HTTP layer, pinned to /dns/v1
    zones.py                 patchable  enum interpretation and reporting
    app.py                   patchable  CLI entry point
    tests/test_zones.py      read-only  13 tests pinned to the v2 contract
  specs/real-world/
    clouddns-v1.json         Google's Cloud DNS v1 contract (APIs.guru)
    clouddns-v2.json         Google's Cloud DNS v2 contract (APIs.guru)
    clouddns-migration-notes.md
```

### What it exercises

| # | Change | v1 → v2 | Correct behaviour |
|---|---|---|---|
| 1 | Version in path | `/dns/v1/...` → `/dns/v2/...` | Repair |
| 2 | New required segment | `/projects/{p}/managedZones` → `/projects/{p}/locations/{location}/managedZones` | Read from config; **do not invent a value** |
| 3 | Simple enum re-casing | `public` → `PUBLIC`, `done` → `DONE` | Repair |
| 4 | camelCase enum re-casing | `keySigning` → `KEY_SIGNING` | Repair — **not** a plain `.upper()` |
| 5 | Body fields | `name`, `type`, `ttl`, `rrdatas` | No change needed |

Every one of these was verified against Google's live discovery documents for both
versions, not taken from a migration guide.

### The two traps

Change 4 is the decoy. Fifteen enum fields are re-cased in v2, and eleven of them are a
plain uppercase — so `.upper()` looks like the right repair and passes most of the suite.
Four are not: `keySigning` → `KEY_SIGNING`, `zoneSigning` → `ZONE_SIGNING`,
`regionalL4ilb` → `REGIONAL_L4ILB`, `behaviorUnspecified` → `BEHAVIOR_UNSPECIFIED`.
`test_key_signing_keys_use_the_underscored_v2_enum` catches the blanket conversion.

Change 2 is the one that should *not* be resolved automatically. `global` is right for
ordinary zones and wrong for a deployment using regional zones, and neither contract says
which applies. `test_location_is_taken_from_configuration_and_not_invented` fails on a
hardcoded `global`, whether written as a literal or as a fallback default.

A further wrinkle: comparisons against re-cased enums fail *quietly*. A client testing
`status == 'done'` against a v2 response does not raise, it just never matches.

### Expected outcome

Best case is `partial_repair`: changes 1, 3 and 4 repaired and verified, change 2 recorded
as manual work, change 5 recorded as `no_change`.

### Running it

```sh
backend/.venv/bin/api-maintainer run \
  --repo "$PWD/examples/clouddns-client" \
  --old-spec examples/specs/real-world/clouddns-v1.json \
  --new-spec examples/specs/real-world/clouddns-v2.json \
  --notes-file examples/specs/real-world/clouddns-migration-notes.md \
  --test-command "python -m unittest discover -s tests -t ."
```

In the UI, keep the default **Your repository** tab, paste the absolute path to
`examples/clouddns-client`, upload both contracts, paste the notes, and set the same test
command under **Test settings**. The default `api-maintainer-python:local` image is
enough — the tests are standard library only.

### Verified

Checked on this machine, September 14 2026:

- Both contracts pass `parse_contract`; the structural diff yields 60 entries.
- `snapshot_files` accepts the directory: 5 files, 8,699 bytes. `editable()` marks
  `client.py`, `zones.py` and `app.py` patchable and both test files read-only.
- Under `RepositoryRunner`'s exact Docker flags, the unmigrated client **fails** 9 of 13
  tests and a minimal reference migration **passes** all 13.
- The traps bite: a naive `.upper()` fails 1 test, a hardcoded `global` fails 5.

One caveat worth knowing before a demo: the v1→v2 `diff.json` is roughly 245 KB, and the
agent's file read is capped at 32 KiB in [tools.py](../backend/src/api_maintainer/tools.py),
so it has to reach the enum evidence with `search` rather than by reading the diff whole.
That is a harder ask than any bundled scenario.

## 3. Real published contracts

Public APIs with two real versions both published as OpenAPI 3.0.x. Sourced from the
[APIs.guru](https://apis.guru) directory: of 2,529 APIs, 137 have two or more 3.0.x
versions, and the pairs below were each verified against this project's own
`parse_contract`.

| API | Migration | Sizes | Why it is interesting |
|---|---|---|---|
| AdSense Management API | `v1.4` → `v2` | 129 / 117 KB | A real major-version break: resources renamed and re-nested |
| Drive API | `v2` → `v3` | 346 / 238 KB | The best-known REST migration of its generation |
| Tag Manager API | `v1` → `v2` | 160 / 223 KB | Large path restructuring |
| Cloud Talent Solution API | `v3` → `v4` | 135 / 151 KB | Renamed and reshaped response objects |
| Amazon CloudSearch | `2011-02-01` → `2013-01-01` | 196 / 286 KB | Date-versioned rewrite |
| Cloud Monitoring API | `v1` → `v3` | 112 / 272 KB | Two major versions apart |
| Cloud DNS API | `v1` → `v2` | 194 / 205 KB | Small, focused delta |

Fetch a pair:

```sh
mkdir -p examples/specs/real-world
curl -H 'User-Agent: Mozilla/5.0' -o examples/specs/real-world/adsense-v1.4.json \
  https://api.apis.guru/v2/specs/googleapis.com/adsense/v1.4/openapi.json
curl -H 'User-Agent: Mozilla/5.0' -o examples/specs/real-world/adsense-v2.json \
  https://api.apis.guru/v2/specs/googleapis.com/adsense/v2/openapi.json
```

The `User-Agent` header is required; APIs.guru sits behind Cloudflare, which rejects
the default urllib agent with 403 and `HEAD` requests with 404.

### Constraints when picking your own

[contracts.py](../backend/src/api_maintainer/contracts.py) is strict, and most modern
specs fail it:

- **OpenAPI 3.0.x only.** `3.1` is rejected by an exact regex, which rules out a lot of
  current specs.
- **1 MiB per document**, plus a backstop of **30,000 nodes / 60 levels deep**. Measured
  across 313 real specs, density runs 14-29 nodes/KB (averaging 18.9), so 1 MiB lands
  near 19,400 nodes: the size limit is what you actually hit, and the node cap only bites
  on unusually dense input. Stripe, GitHub and OpenAI are all far past both.
- **Local `$ref` only** — every pointer must resolve inside the same document.
- **No YAML aliases or cycles.**

Adyen PayoutService looked promising on size but is rejected: it fails strict OpenAPI
3.0 validation.

### The honest caveat

These give you real contract *diffs*, but no client code and no tests. You would be
pointing the agent at a repository of your own that consumes the API. Without a test
command the run ends at `verification_incomplete` by design — the patch is unverified,
and [the runner says so](../backend/src/api_maintainer/runner.py) rather than implying
success. The bundled bookstore mock and its independent evaluation are never used to
claim verification of an outside repository.

For judging repair *quality*, fixture 1 is the better instrument: it has a known-correct
answer, a reachable target and traps for the two most likely wrong repairs.
