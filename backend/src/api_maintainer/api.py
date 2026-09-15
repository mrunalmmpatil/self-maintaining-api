import shlex
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .config import ROOT, SCENARIOS
from .contracts import InputError
from .migration import PrerequisiteError, Service
from .schema import RunRequest
from .storage import BusyError, StateError


def create_app(service=None):
    service = service or Service()

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(service.reconcile)
        yield

    app = FastAPI(title="API Maintainer", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def guard(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin not in origins:
                return JSONResponse({"detail": "Origin is not permitted."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site mutation is not permitted."}, status_code=403)
            size = request.headers.get("content-length")
            if size and (not size.isdecimal() or int(size) > 2300000):
                return JSONResponse({"detail": "Upload exceeds the request size limit."}, status_code=413)
        return await call_next(request)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "Run or artifact not found."}, status_code=404)

    @app.exception_handler(BusyError)
    @app.exception_handler(StateError)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(PrerequisiteError)
    async def unavailable(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(ValidationError)
    async def unreadable(request, exc):
        # A saved run carrying fields this process does not know means the server is
        # older than the worker that wrote it, which happens when a detached run keeps
        # writing across an upgrade. Say so instead of returning an opaque failure.
        return JSONResponse(
            {
                "detail": "This run was saved by a newer version of the service than the "
                "running server. Restart the backend, then reload this page."
            },
            status_code=503,
        )

    @app.exception_handler(InputError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/health")
    def health():
        return service.health()

    @app.get("/api/samples")
    def samples():
        return [dict(id="bookstore", name="Python bookstore")]

    @app.get("/api/scenarios")
    def scenarios():
        return [dict(id=k, **v) for k, v in SCENARIOS.items()]

    @app.get("/api/runs")
    def runs():
        return service.store.recent()

    @app.post("/api/runs", status_code=202)
    async def create(request: Request):
        # Stream into a bounded buffer before multipart parsing, including chunked uploads.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 2300000:
                raise HTTPException(413, "Upload exceeds the request size limit.")
        request._body = bytes(body)
        form = await request.form(max_files=3, max_fields=10, max_part_size=1024 * 1024)
        try:
            parsed = RunRequest(
                sample_id=form.get("sample_id", "bookstore"),
                scenario_id=form.get("scenario_id", "endpoint-rename"),
                mode=form.get("mode", "review"),
                repository_path=form.get("repository_path") or None,
                test_command=shlex.split(str(form.get("test_command", ""))),
                test_image=form.get("test_image") or "api-maintainer-python:local",
            )
        except (ValidationError, ValueError):
            raise HTTPException(422, "Invalid sample, scenario or mode.")

        async def upload(name, limit):
            item = form.get(name)
            if item is None:
                return None
            value = await item.read(limit + 1) if hasattr(item, "read") else str(item).encode()
            if len(value) > limit:
                raise HTTPException(413, name + " exceeds its size limit.")
            return value

        old, new, notes = (
            await upload("old_spec", 1048576),
            await upload("new_spec", 1048576),
            await upload("notes", 65536),
        )
        report = await run_in_threadpool(
            service.create_run, parsed, old, new, notes, request.headers.get("idempotency-key")
        )
        return report

    @app.get("/api/runs/{run_id}")
    def get(run_id: str):
        return service.get_run(run_id)

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, after_seq: int = 0):
        return service.store.events(run_id, after_seq)

    @app.post("/api/runs/{run_id}/repair", status_code=202)
    def repair(run_id: str):
        return service.request_repair(run_id)

    @app.post("/api/runs/{run_id}/revise", status_code=202)
    async def revise(run_id: str, request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise HTTPException(413, "Review edits exceed 64 KiB.")
        import json

        try:
            values = json.loads(body)
            if not isinstance(values, dict) or any(
                not isinstance(values.get(k, ""), str) for k in ("summary", "notes")
            ):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Supply an editable summary and notes as text.")
        return await run_in_threadpool(
            service.revise_analysis, run_id, values.get("summary", ""), values.get("notes", "")
        )

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}")
    def artifact(run_id: str, artifact_id: str):
        return FileResponse(service.get_artifact(run_id, artifact_id), filename=artifact_id)

    dist = ROOT / "frontend/dist"
    if dist.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
