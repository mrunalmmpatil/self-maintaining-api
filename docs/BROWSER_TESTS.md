# Browser verification

Production prerequisite flow: start the regular backend, load the form, select both modes, and verify an unavailable Docker/key returns an actionable error without creating a migration.

For UI orchestration without inference, start this **test-only** fixture on the normal local port:

```sh
PYTHONPATH=backend/tests backend/.venv/bin/uvicorn ui_server:app --host 127.0.0.1 --port 8000
```

It uses new temporary storage and explicitly warns that its agent/checks are scripted. Stop any existing port-8000 server first. Never use its results as real model or Docker evidence.

1. Endpoint rename / Review first: analyze; confirm no patch or check before approval; refresh; Generate repair; confirm final patch/check and independent evaluation remains not run.
2. Download patch and report; compare the displayed diff and final revision with report metadata.
3. Endpoint rename / Automatic: start; confirm it finishes without an approval click.
4. Optional field: expect no change and empty patch, no repair button.
5. Required country: expect manual action documentation and empty patch, no repair button.
6. Mixed: expect a partial endpoint patch, prominent country work, and failed full development checks.
7. Open Run history and reload a saved run URL; confirm persistent content.
8. Check desktop/mobile layout and console errors.

API automated tests separately cover invalid contracts, oversized uploads, origin/host rejection, idempotency, unknown artifacts and unavailable prerequisites. Scripted transport tests cover provider exhaustion. Live full-flow acceptance must be repeated with the production service and actual Docker/model.
