"""Scripted orchestration tests. These do not establish live-model repair ability."""

import asyncio
import difflib
import json
import shutil
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from api_maintainer.agent import CountedTransport
from api_maintainer.api import create_app
from api_maintainer.config import SAMPLE, SCENARIOS
from api_maintainer.contracts import InputError, parse_contract, structural_diff
from api_maintainer.files import apply_unified, source_diff, tree_hash
from api_maintainer.migration import Service
from api_maintainer.reports import finalize
from api_maintainer.schema import RunRequest
from api_maintainer.storage import BusyError, StateError
from api_maintainer.tools import BudgetExceeded, Tools
from api_maintainer.worker import execute


class Checks:
    def __init__(self, status="passed"):
        self.status = status

    def check(self, workspace, seconds):
        return dict(
            exit_code=0 if self.status == "passed" else 1,
            status=self.status,
            duration=0.001,
            log="scripted orchestration check",
            truncated=False,
        )


@pytest.fixture
def service(tmp_path):
    return Service(tmp_path / "data")


def create(service, mode="review", scenario="endpoint-rename"):
    return service.create_run(RunRequest(mode=mode, scenario_id=scenario), launch=False)


def analysis(disposition="repair", manual=False):
    result = dict(
        summary="Scripted analysis fixture",
        changes=[
            dict(
                id="c1",
                kind="endpoint",
                description="Endpoint moved according to supplied notes",
                disposition=disposition,
                evidence=[dict(path="inputs/notes.md", line_start=1)],
                affected_locations=[dict(path="source/client.py", line_start=8)],
            )
        ],
        manual_actions=[],
    )
    if manual:
        result["manual_actions"] = [
            dict(
                change_id="c1",
                required_work="Add and validate country at the application boundary; propagate through quote and book_details into get_book.",
                unresolved_decision="Where does customer country come from?",
                blocking_effect="Requests lack required country.",
                affected_locations=[dict(path="source/client.py", line_start=6)],
            )
        ]
    return result


def patch_for(tools):
    text = (tools.workspace / "client.py").read_text()
    return "".join(
        difflib.unified_diff(
            text.splitlines(True),
            text.replace("/books/", "/catalog/books/").splitlines(True),
            fromfile="a/client.py",
            tofile="b/client.py",
        )
    )


def scripted(stage, tools):
    if stage == "analyzing":
        tools.invoke("submit_analysis", analysis=analysis())
    else:
        tools.invoke("apply_patch", patch=patch_for(tools), rationale="Follow evidenced endpoint migration")
        tools.invoke("finish_repair", summary="Updated the endpoint")


def test_review_snapshot_resume_and_budgets(service):
    original_hash = tree_hash(SAMPLE / "consumer")
    report = create(service)
    service.store.claim(report.run_id, "analyzing")
    execute(service.store, report.run_id, "analyzing", scripted, Checks())
    service.store.release(report.run_id)
    saved = service.get_run(report.run_id)
    root = service.store.root / "runs" / report.run_id
    assert saved.lifecycle == "awaiting_review"
    assert not source_diff(root / "original", root / "workspace")[0]
    assert saved.budget.used_tools == 1
    restored = Service(service.store.root)
    restored.reconcile()
    assert restored.store.claim(report.run_id, "repairing")
    assert not restored.store.claim(report.run_id, "repairing")
    execute(restored.store, report.run_id, "repairing", scripted, Checks())
    restored.store.release(report.run_id)
    final = restored.get_run(report.run_id)
    assert final.outcome == "checks_passed"
    assert final.budget.used_tools == 3
    assert final.budget.used_patch_attempts == 1
    assert final.development_checks[-1].revision_hash == final.patch["final_hash"]
    assert tree_hash(SAMPLE / "consumer") == original_hash
    assert "catalog/books" in restored.get_artifact(report.run_id, "patch.diff").read_text()


def test_auto_uses_same_workflow(service):
    r = create(service, "auto")
    service.store.claim(r.run_id, "analyzing")
    execute(service.store, r.run_id, "analyzing", scripted, Checks())
    assert service.get_run(r.run_id).outcome == "checks_passed"


@pytest.mark.parametrize(
    "disposition,manual,outcome",
    [
        ("no_change", False, "no_change_needed"),
        ("manual", True, "manual_action_required"),
        ("uncertain", False, "verification_incomplete"),
    ],
)
def test_nonrepair_outcomes(service, disposition, manual, outcome):
    r = create(service)
    service.store.claim(r.run_id, "analyzing")
    execute(
        service.store,
        r.run_id,
        "analyzing",
        lambda stage, t: t.invoke("submit_analysis", analysis=analysis(disposition, manual)),
        Checks(),
    )
    final = service.get_run(r.run_id)
    assert final.outcome == outcome
    assert final.patch["empty"]


def test_failed_final_check_never_reports_success(service):
    r = create(service, "auto")
    service.store.claim(r.run_id, "analyzing")
    execute(service.store, r.run_id, "analyzing", scripted, Checks("failed"))
    assert service.get_run(r.run_id).outcome == "repair_failed"


def test_stale_check_not_used_for_new_revision(service):
    r = create(service)
    r.lifecycle = "repairing"
    t = Tools(service.store, r, Checks())
    t.run_checks(final=True)
    (t.workspace / "client.py").write_text((t.workspace / "client.py").read_text() + "\n# changed\n")
    finalize(service.store, r)
    assert r.development_verification == "not_run"
    assert r.outcome != "checks_passed"


def test_patch_is_atomic_and_source_only(tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\n")
    (tmp_path / "b.py").write_text("three\n")
    patch = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n-one\n+new\n two\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-wrong\n+changed\n"
    before = tree_hash(tmp_path)
    with pytest.raises(ValueError):
        apply_unified(tmp_path, patch, {"a.py", "b.py"})
    assert tree_hash(tmp_path) == before
    for name in ("../secret.py", "/secret.py", "checks.py", "..\\secret.py"):
        bad = f"--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-one\n+new\n"
        with pytest.raises(ValueError):
            apply_unified(tmp_path, bad, {"a.py"})
    (tmp_path / "link.py").symlink_to(tmp_path / "a.py")
    with pytest.raises(ValueError):
        apply_unified(
            tmp_path, "--- a/link.py\n+++ b/link.py\n@@ -1,2 +1,2 @@\n-one\n+new\n two\n", {"link.py"}
        )


def test_stage_restrictions_and_hidden_files(service):
    r = create(service)
    r.lifecycle = "analyzing"
    t = Tools(service.store, r, Checks())
    for path in (
        "../runs.sqlite3",
        "evaluation/checks/cases.json",
        "inputs/../../secret",
        "source/../artifacts/report.json",
    ):
        with pytest.raises(ValueError):
            t.invoke("read_file", path=path)
    with pytest.raises(ValueError):
        t.invoke("apply_patch", patch="invalid", rationale="no")
    assert r.budget.used_tools == 5
    r.lifecycle = "repairing"
    for _ in range(r.budget.limits["patch_attempts"]):
        with pytest.raises(ValueError):
            t.invoke("apply_patch", patch="invalid", rationale="no")
    with pytest.raises(BudgetExceeded):
        t.invoke("apply_patch", patch="invalid", rationale="no")
    assert r.budget.used_patch_attempts == r.budget.limits["patch_attempts"]


def test_fixed_request_limits_count_http_attempts(service):
    r = create(service)
    r.lifecycle = "analyzing"
    t = Tools(service.store, r, Checks())

    async def exercise():
        async with httpx.AsyncClient(
            transport=CountedTransport(
                t, httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
            )
        ) as client:
            for _ in range(5):
                await client.post("https://example.test")
            with pytest.raises(BudgetExceeded):
                await client.post("https://example.test")

    asyncio.run(exercise())
    assert service.get_run(r.run_id).budget.used_requests == 5


def test_deadline_and_final_check_reservation(service):
    r = create(service)
    t = Tools(service.store, r, Checks())
    r.budget.used_checks = 3
    with pytest.raises(BudgetExceeded):
        t.run_checks()
    t.run_checks(final=True)
    t.started -= r.budget.limits["active_seconds"] + 1
    with pytest.raises(BudgetExceeded):
        t.count("tools")


def test_lease_and_idempotency(service):
    req = RunRequest()
    r = service.create_run(req, key="same", launch=False)
    assert service.create_run(req, key="same", launch=False).run_id == r.run_id
    with pytest.raises(StateError):
        service.create_run(RunRequest(mode="auto"), key="same", launch=False)
    service.store.claim(r.run_id, "analyzing")
    with pytest.raises(BusyError):
        create(service)


def test_contract_validation_and_diff():
    old = (SAMPLE / "contracts/old.json").read_bytes()
    doc = parse_contract(old)
    for s in SCENARIOS:
        parse_contract((SAMPLE / f"contracts/{s}.json").read_bytes())
    for invalid in [
        b"openapi: 3.1.0",
        b"!!python/object:evil {}",
        old.replace(b"#/components/schemas/Book", b"https://evil.test/schema"),
        b"x" * 1048577,
    ]:
        with pytest.raises(InputError):
            parse_contract(invalid)
    new = parse_contract((SAMPLE / "contracts/endpoint-rename.json").read_bytes())
    changes = structural_diff(doc, new)
    assert {"added", "removed"} <= {c["kind"] for c in changes}
    assert not any(c["kind"] == "rename" for c in changes)


def test_api_validation_origins_and_artifact_boundary(service, monkeypatch):
    client = TestClient(create_app(service))
    assert client.get("/api/scenarios").status_code == 200
    assert client.get("/api/runs/absent").status_code == 404
    assert client.post("/api/runs", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "evil.test"}).status_code == 400
    assert client.post("/api/runs", data={"mode": "bad"}).status_code == 422
    assert (
        client.post(
            "/api/runs", files={"old_spec": ("a.json", b"x" * 1048577), "new_spec": ("b.json", b"{}")}
        ).status_code
        == 413
    )
    monkeypatch.setattr(service, "health", lambda: dict(ready=False, docker=False))
    assert client.post("/api/runs", data={"scenario_id": "endpoint-rename"}).status_code == 503
    r = create(service)
    assert client.get(f"/api/runs/{r.run_id}").json()["mode"] == "review"
    assert client.get(f"/api/runs/{r.run_id}/artifacts/runs.sqlite3").status_code == 404


def test_restart_marks_abandoned_active_run(service):
    r = create(service)
    service.store.claim(r.run_id, "analyzing")
    with service.store.connection() as db:
        db.execute("UPDATE lease SET heartbeat=?,pid=NULL", (time.time() - 30,))
    service.reconcile()
    assert service.get_run(r.run_id).lifecycle == "interrupted"


@pytest.mark.parametrize("reject_first", [False, True, "empty", "truncated"])
def test_real_strands_sdk_with_scripted_http_tools(service, monkeypatch, reject_first):
    """Exercises the pinned SDK (not a live provider): read/result/submission loop."""
    import api_maintainer.agent as adapter
    from api_maintainer.agent import run_agent

    report = create(service)
    report.lifecycle = "analyzing"
    report.model["requested_id"] = "nex-agi/nex-n2.5-pro:free"
    service.store.save(report)
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        schema = next(
            t["function"]["parameters"]
            for t in payload["tools"]
            if t["function"]["name"] == "submit_analysis"
        )
        assert schema["required"] == ["analysis"]
        assert "changes" in schema["properties"]["analysis"]["properties"]
        assert "Evidence" in schema["$defs"]
        if reject_first == "truncated" and len(calls) == 2:
            return httpx.Response(
                200,
                json={
                    "id": "truncated",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "scripted",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "length",
                            "message": {"role": "assistant", "content": "Long prose analysis that ran out"},
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )
        if reject_first == "empty" and len(calls) == 2:
            return httpx.Response(
                200,
                json={
                    "id": "empty",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "scripted",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "Analysis in progress."},
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )
        if len(calls) == 1:
            name, args = "read_file", {"path": "source/client.py"}
        elif reject_first and len(calls) == 2:
            name, args = "submit_analysis", {}
        else:
            assert any(m["role"] == "tool" and "urlopen" in str(m["content"]) for m in payload["messages"])
            name, args = "submit_analysis", {"analysis": analysis()}
        return httpx.Response(
            200,
            json={
                "id": f"completion-{len(calls)}",
                "object": "chat.completion",
                "created": 1,
                "model": "nex-agi/nex-n2.5-pro:free",
                "provider": "scripted",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"tool-{len(calls)}",
                                    "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(args)},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "scripted-test-key")
    monkeypatch.setattr(adapter.httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    tools = Tools(service.store, report, Checks())
    run_agent("analyzing", tools)
    assert tools.submitted
    expected = 3 if reject_first else 2
    assert len(calls) == expected
    assert report.budget.used_requests == expected
    assert report.budget.used_tools == (2 if reject_first in ("empty", "truncated") else expected)
    assert report.usage["input_tokens"] == 10 * expected
    if reject_first is True:
        assert any(e["kind"] == "tool_error" for e in service.store.events(report.run_id))
    if reject_first == "empty":
        assert any(e["kind"] == "submission_pending" for e in service.store.events(report.run_id))
    if reject_first == "truncated":
        # A response cut off by the output limit must resume, not abort the stage.
        assert any(e["kind"] == "response_truncated" for e in service.store.events(report.run_id))
    assert report.model["provider"] == "scripted"


def test_mixed_requires_component_evidence_and_preserves_failed_checks(service):
    class MixedChecks(Checks):
        def check(self, workspace, seconds):
            return {
                **super().check(workspace, seconds),
                "components": {"endpoint_reaches_country_validation": True},
            }

    r = create(service, "auto", "mixed")
    service.store.claim(r.run_id, "analyzing")

    def mixed(stage, t):
        if stage == "analyzing":
            t.invoke("submit_analysis", analysis=analysis("repair", True))
        else:
            scripted(stage, t)

    execute(service.store, r.run_id, "analyzing", mixed, MixedChecks("failed"))
    final = service.get_run(r.run_id)
    assert final.outcome == "partial_repair"
    assert final.development_verification == "failed"
    assert not final.patch["empty"]
    assert "country" not in (service.store.root / "runs" / r.run_id / "workspace/client.py").read_text()


def test_evaluation_never_changes_repair_budget_or_accepts_tampered_snapshot(service, monkeypatch):
    from api_maintainer.evaluation import evaluate
    from api_maintainer.runner import DockerRunner

    r = create(service, "auto")
    service.store.claim(r.run_id, "analyzing")
    execute(service.store, r.run_id, "analyzing", scripted, Checks())
    service.store.release(r.run_id)
    budget = service.get_run(r.run_id).budget.model_dump()
    monkeypatch.setattr(DockerRunner, "evaluate", lambda self, workspace, cases: [dict(passed=True)])
    result = evaluate(service, r.run_id)
    assert result["verdict"] == "passed"
    assert service.get_run(r.run_id).budget.model_dump() == budget
    root = service.store.root / "runs" / r.run_id
    (root / "workspace/client.py").write_text("tampered\n")
    result = evaluate(service, r.run_id)
    assert result["verdict"] == "invalid"
    assert (
        service.get_run(r.run_id).outcome == "checks_passed"
    )  # Frozen migration result, separate evaluation.


def test_sdk_provider_exhaustion_stops_without_retry(service, monkeypatch):
    import api_maintainer.agent as adapter
    from api_maintainer.agent import run_agent

    r = create(service)
    r.lifecycle = "analyzing"
    r.model["requested_id"] = "nex-agi/nex-n2.5-pro:free"
    t = Tools(service.store, r, Checks())
    monkeypatch.setenv("OPENROUTER_API_KEY", "scripted-test-key")
    monkeypatch.setattr(
        adapter.httpx,
        "AsyncHTTPTransport",
        lambda **kwargs: httpx.MockTransport(
            lambda request: httpx.Response(
                429, json={"error": {"message": "free quota exhausted"}}, headers={"Retry-After": "86400"}
            )
        ),
    )
    with pytest.raises(Exception):
        run_agent("analyzing", t)
    assert r.budget.used_requests == 1
    assert t.failure == "provider_rate_limited"


def test_bounded_process_logs_and_timeout():
    import subprocess
    import sys

    from api_maintainer.runner import command

    code, text, truncated = command([sys.executable, "-c", 'print("x"*100000)'])
    assert code == 0 and len(text) == 65536 and truncated
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        command([sys.executable, "-c", "import time; time.sleep(10)"], 0.05)
    assert time.monotonic() - start < 1


@pytest.mark.parametrize("source_prefix", [False, True])
def test_strands_patch_dispatch_respects_reviewed_scope(service, monkeypatch, source_prefix):
    import api_maintainer.agent as adapter
    from api_maintainer.agent import run_agent

    r = create(service)
    r.lifecycle = "analyzing"
    t = Tools(service.store, r, Checks())
    t.submit_analysis(analysis())
    r.lifecycle = "repairing"
    r.model["requested_id"] = "nex-agi/nex-n2.5-pro:free"
    t.submitted = False
    calls = []

    def respond(request):
        data = json.loads(request.content)
        calls.append(data)
        name, args = (
            (
                "apply_patch",
                {
                    "patch": patch_for(t)
                    .replace("a/client.py", "a/source/client.py")
                    .replace("b/client.py", "b/source/client.py")
                    if source_prefix
                    else patch_for(t),
                    "rationale": "Evidenced endpoint change",
                },
            )
            if len(calls) == 1
            else ("finish_repair", {"summary": "Updated endpoint"})
        )
        return httpx.Response(
            200,
            json={
                "id": str(len(calls)),
                "object": "chat.completion",
                "created": 1,
                "model": "scripted",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": str(len(calls)),
                                    "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(args)},
                                }
                            ],
                        },
                    }
                ],
            },
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "scripted-test-key")
    monkeypatch.setattr(adapter.httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    run_agent("repairing", t)
    assert t.submitted and r.budget.used_patch_attempts == 1
    assert r.budget.used_tools == 2 and r.budget.used_requests == 2
    assert "/catalog/books/" in (t.workspace / "client.py").read_text()


def test_rejected_sdk_patch_arguments_still_count_attempts(service, monkeypatch):
    import api_maintainer.agent as adapter
    from api_maintainer.agent import run_agent

    r = create(service)
    r.lifecycle = "repairing"
    r.model["requested_id"] = "nex-agi/nex-n2.5-pro:free"
    t = Tools(service.store, r, Checks())
    t.submit_analysis(analysis())
    t.submitted = False

    def respond(request):
        return httpx.Response(
            200,
            json={
                "id": "1",
                "object": "chat.completion",
                "created": 1,
                "model": "scripted",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "bad",
                                    "type": "function",
                                    "function": {"name": "apply_patch", "arguments": "{}"},
                                }
                            ],
                        },
                    }
                ],
            },
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "scripted-test-key")
    monkeypatch.setattr(adapter.httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    with pytest.raises(Exception):
        run_agent("repairing", t)
    assert r.budget.used_patch_attempts == r.budget.limits["patch_attempts"]
    assert r.budget.used_requests <= r.budget.limits["patch_attempts"] + 1
    assert t.failure == "budget_exceeded"


def test_supervisor_kills_overdue_worker_and_keeps_artifacts(service, monkeypatch):
    import sys

    from api_maintainer import supervisor

    r = create(service)
    r.budget.active_seconds = r.budget.limits["active_seconds"] - 0.01
    service.store.save(r)
    service.store.claim(r.run_id, "analyzing")
    monkeypatch.setenv("API_MAINTAINER_DATA", str(service.store.root))

    class Child:
        pid = 123456
        ended = False

        def poll(self):
            return 0 if self.ended else None

        def wait(self, timeout):
            self.ended = True
            return 0

    child = Child()
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **k: child)
    kills = []
    monkeypatch.setattr(supervisor.os, "killpg", lambda *a: kills.append(a))
    cleanup = []
    monkeypatch.setattr(supervisor, "cleanup_run", lambda run_id: cleanup.append(run_id))
    ticks = iter([100, 101])
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(sys, "argv", ["supervisor", r.run_id, "analyzing"])
    supervisor.main()
    final = service.get_run(r.run_id)
    assert len(kills) == 1 and cleanup == [r.run_id]
    assert final.termination_reason == "budget_exceeded"
    assert final.budget.active_seconds == final.budget.limits["active_seconds"]
    assert service.get_artifact(r.run_id, "report.json").is_file()
    assert not service.store.leased(r.run_id)


def test_entire_model_response_body_obeys_deadline(service, monkeypatch):
    class HangingBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(10)
            yield b"{}"

    r = create(service)
    r.lifecycle = "analyzing"
    t = Tools(service.store, r, Checks())
    monkeypatch.setattr(t, "remaining", lambda: 0.02)

    async def exercise():
        transport = CountedTransport(
            t, httpx.MockTransport(lambda req: httpx.Response(200, stream=HangingBody()))
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(TimeoutError):
                await client.post("https://example.test")

    start = time.monotonic()
    asyncio.run(exercise())
    assert time.monotonic() - start < 0.5
    assert r.budget.used_requests == 1 and t.failure == "provider_error"


def test_cli_and_api_share_saved_report_and_exit_semantics(service, monkeypatch, capsys):
    import sys

    from api_maintainer.cli import main

    r = create(service, "auto")
    service.store.claim(r.run_id, "analyzing")
    execute(service.store, r.run_id, "analyzing", scripted, Checks())
    service.store.release(r.run_id)
    monkeypatch.setenv("API_MAINTAINER_DATA", str(service.store.root))
    monkeypatch.setattr(sys, "argv", ["api-maintainer", "status", "--json", r.run_id])
    assert main() == 0
    cli_report = json.loads(capsys.readouterr().out)
    web_report = TestClient(create_app(service)).get("/api/runs/" + r.run_id).json()
    assert cli_report == web_report
    # The default view is the human summary and must lead with the same verdict.
    monkeypatch.setattr(sys, "argv", ["api-maintainer", "status", r.run_id])
    assert main() == 0
    printed = capsys.readouterr().out
    assert "PASS" in printed and web_report["result"] == "pass"
    assert web_report["result_reason"] in printed


@pytest.mark.parametrize("pointer", ["/info/version", "#/info/version", ""])
def test_analysis_accepts_standard_local_pointer_forms(service, pointer):
    r = create(service)
    r.lifecycle = "analyzing"
    t = Tools(service.store, r, Checks())
    value = analysis()
    value["changes"][0]["evidence"] = [{"path": "inputs/new.json", "pointer": pointer}]
    t.submit_analysis(value)
    assert t.submitted
    assert r.changes[0].evidence[0].pointer.startswith("#")


@pytest.mark.parametrize("pointer", ["https://example.com/spec.json#/info", "../secret", "/does-not-exist"])
def test_analysis_rejects_external_or_unresolved_pointer(service, pointer):
    r = create(service)
    r.lifecycle = "analyzing"
    t = Tools(service.store, r, Checks())
    value = analysis()
    value["changes"][0]["evidence"] = [{"path": "inputs/new.json", "pointer": pointer}]
    with pytest.raises(ValueError):
        t.submit_analysis(value)
    assert not t.submitted


def test_prefixed_patch_cannot_escape_scope_or_repeat_file(tmp_path):
    (tmp_path / "client.py").write_text("old\n")

    def patch(name):
        return f"--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-old\n+new\n"

    for name in ["source/../client.py", "source/secret.py", "inputs/client.py"]:
        with pytest.raises(ValueError):
            apply_unified(tmp_path, patch(name), {"client.py"})
    with pytest.raises(ValueError):
        apply_unified(tmp_path, patch("client.py") + patch("source/client.py"), {"client.py"})
    assert (tmp_path / "client.py").read_text() == "old\n"


def test_initial_context_excludes_private_files_and_is_bounded(service):
    from api_maintainer.agent import initial_context

    r = create(service)
    t = Tools(service.store, r, Checks())
    (t.root / "secret.txt").write_text("PRIVATE_SENTINEL")
    sections = json.loads(initial_context(t))
    assert "PRIVATE_SENTINEL" not in str(sections)
    assert {s["path"] for s in sections} == set(t.list_files()["files"])
    assert sum(len(s["numbered_text"].encode()) for s in sections) <= 48000
    assert r.budget.used_tools == 0


def test_bad_evidence_error_identifies_file_and_recovery(service):
    from api_maintainer.schema import Evidence

    t = Tools(service.store, create(service), Checks())
    with pytest.raises(ValueError, match="inputs/old.json.*numbered line_start"):
        t.validate_evidence(Evidence(path="inputs/old.json", pointer="/missing"))


OVERLOADED = {"error": {"code": 502, "message": "Upstream error from Nvidia: Service temporarily overloaded"}}
COMPLETION = {
    "model": "nvidia/nemotron-3-super-120b-a12b:free",
    "provider": "Nvidia",
    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
}


def drive(service, responses, monkeypatch):
    """Run one request through CountedTransport against a scripted response sequence."""
    monkeypatch.setattr("api_maintainer.agent.RETRY_BACKOFF", (0.0, 0.0))
    r = create(service)
    r.lifecycle = "analyzing"
    t = Tools(service.store, r, Checks())
    sent = []

    def respond(request):
        sent.append(request)
        return responses[min(len(sent) - 1, len(responses) - 1)]

    async def exercise():
        async with httpx.AsyncClient(transport=CountedTransport(t, httpx.MockTransport(respond))) as client:
            return await client.post("https://example.test")

    return t, sent, asyncio.run(exercise())


def kinds(service, run_id):
    return [e["kind"] for e in service.store.events(run_id)]


def test_transient_body_error_is_retried_without_charging_the_allowance(service, monkeypatch):
    # OpenRouter reports upstream overload as HTTP 200 with an error body and no completion.
    t, sent, response = drive(
        service, [httpx.Response(200, json=OVERLOADED), httpx.Response(200, json=COMPLETION)], monkeypatch
    )
    assert response.json() == COMPLETION
    assert len(sent) == 2
    assert t.failure is None
    assert t.report.model["actual_id"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert service.get_run(t.report.run_id).budget.used_requests == 1
    assert kinds(service, t.report.run_id).count("provider_retry") == 1


def test_transient_status_is_retried(service, monkeypatch):
    t, sent, response = drive(
        service, [httpx.Response(503), httpx.Response(200, json=COMPLETION)], monkeypatch
    )
    assert response.status_code == 200
    assert len(sent) == 2 and t.failure is None


def test_exhausted_retries_report_provider_error(service, monkeypatch):
    t, sent, response = drive(service, [httpx.Response(200, json=OVERLOADED)], monkeypatch)
    assert len(sent) == 3
    assert t.failure == "provider_error"
    assert kinds(service, t.report.run_id).count("provider_retry") == 2
    assert kinds(service, t.report.run_id).count("provider_error") == 1


def test_rate_limit_and_client_errors_are_not_retried(service, monkeypatch):
    t, sent, _ = drive(service, [httpx.Response(429)], monkeypatch)
    assert len(sent) == 1 and t.failure == "provider_rate_limited"
    t, sent, _ = drive(service, [httpx.Response(400)], monkeypatch)
    assert len(sent) == 1 and t.failure == "provider_error"


def test_request_timeout_follows_the_budget_limit(service, monkeypatch):
    t, sent, _ = drive(service, [httpx.Response(200, json=COMPLETION)], monkeypatch)
    assert sent[0].extensions["timeout"]["read"] == t.report.budget.limits["request_seconds"] == 180


# --- Single verdict, and logs that say which agent did what ------------------


@pytest.mark.parametrize(
    "disposition,manual,result,code",
    [
        ("repair", False, "pass", 0),
        ("no_change", False, "pass", 0),
        ("manual", True, "partial", 2),
        ("uncertain", False, "fail", 1),
    ],
)
def test_one_verdict_per_run_drives_the_cli_exit_code(service, disposition, manual, result, code):
    from api_maintainer.cli import exit_status

    r = create(service, "auto")
    service.store.claim(r.run_id, "analyzing")
    agent = (
        scripted
        if disposition == "repair"
        else (lambda stage, t: t.invoke("submit_analysis", analysis=analysis(disposition, manual)))
    )
    execute(service.store, r.run_id, "analyzing", agent, Checks())
    final = service.get_run(r.run_id)
    assert final.result == result
    assert final.result_reason
    assert exit_status(final) == code
    # The web payload and the saved artifact carry the same verdict as the CLI.
    served = TestClient(create_app(service)).get("/api/runs/" + r.run_id).json()
    assert served["result"] == result and served["result_reason"] == final.result_reason
    assert (
        final.result_reason in (service.store.root / "runs" / r.run_id / "artifacts/report.json").read_text()
    )


def test_awaiting_review_is_its_own_verdict_not_a_failure(service):
    r = create(service)
    service.store.claim(r.run_id, "analyzing")
    execute(service.store, r.run_id, "analyzing", scripted, Checks())
    saved = service.get_run(r.run_id)
    assert saved.result == "review" and "Approve it" in saved.result_reason


def test_events_attribute_each_step_to_a_stage_with_a_status(service):
    r = create(service, "auto")
    service.store.claim(r.run_id, "analyzing")
    execute(service.store, r.run_id, "analyzing", scripted, Checks())
    events = service.store.events(r.run_id)
    by_stage = {e["stage"] for e in events}
    assert {"analyze", "repair", "run"} <= by_stage
    assert all(e["status"] in ("ok", "error", "warn", "info") for e in events)
    # The closing line is the verdict itself, in the same words the CLI prints.
    closing = [e for e in events if e["kind"] == "finished"][-1]
    assert closing["status"] == "ok" and closing["message"].startswith("PASS")
    # Tool calls record what they achieved and how long they took.
    patched = [e for e in events if "Patch applied" in e["message"]]
    assert patched and patched[0]["stage"] == "repair" and patched[0]["duration_ms"] is not None
    assert any("Development checks passed" in e["message"] for e in events)


def test_rejected_tool_call_is_logged_as_a_failure_with_its_reason(service):
    def broken(stage, tools):
        if stage == "analyzing":
            tools.invoke("submit_analysis", analysis=analysis())
        else:
            with pytest.raises(ValueError):
                tools.invoke("apply_patch", patch="not a diff", rationale="attempt")
            tools.invoke("apply_patch", patch=patch_for(tools), rationale="corrected")
            tools.invoke("finish_repair", summary="Updated the endpoint")

    r = create(service, "auto")
    service.store.claim(r.run_id, "analyzing")
    execute(service.store, r.run_id, "analyzing", broken, Checks())
    failures = [e for e in service.store.events(r.run_id) if e["status"] == "error"]
    assert failures and failures[0]["stage"] == "repair"
    assert "apply_patch rejected" in failures[0]["message"]


def test_batch_view_rolls_up_results_across_runs(service):
    from api_maintainer import console
    from api_maintainer.status import roll_up

    reports = []
    for checks in (Checks(), Checks("failed")):
        r = create(service, "auto")
        service.store.claim(r.run_id, "analyzing")
        execute(service.store, r.run_id, "analyzing", scripted, checks)
        service.store.release(r.run_id)
        reports.append(service.get_run(r.run_id))
    assert roll_up(reports) == {"pass": 1, "partial": 0, "review": 0, "fail": 1, "running": 0}
    table = console.batch(reports)
    assert "2 run(s)" in table and "1 passed" in table and "1 failed" in table
    assert all(report.run_id[:8] in table for report in reports)


def test_logs_from_before_the_status_columns_still_render(service):
    r = create(service)
    # Simulate a row written by the previous schema: no stage, status or duration.
    with service.store.connection() as db:
        db.execute(
            "INSERT INTO events(run,kind,message,at) VALUES(?,?,?,?)",
            (r.run_id, "tool_error", "Patch rejected: check approved paths.", time.time()),
        )
    from api_maintainer import console

    event = service.store.events(r.run_id)[-1]
    assert event["status"] == "info" and event["stage"] is None
    line = console.event_line(event)
    assert "✗" in line and "Patch rejected" in line


def test_a_run_saved_by_a_newer_service_reports_how_to_fix_it(service):
    # Reproduces the version skew seen when a detached worker writes new report fields
    # while an older server process is still serving the UI.
    r = create(service)
    with service.store.connection() as db:
        stored = json.loads(db.execute("SELECT report FROM runs WHERE id=?", (r.run_id,)).fetchone()[0])
        stored["field_from_a_future_version"] = True
        db.execute("UPDATE runs SET report=? WHERE id=?", (json.dumps(stored), r.run_id))
    response = TestClient(create_app(service), raise_server_exceptions=False).get("/api/runs/" + r.run_id)
    assert response.status_code == 503
    assert "Restart the backend" in response.json()["detail"]


def test_patch_without_a_final_newline_keeps_the_file_ending(tmp_path):
    # A model that omits the newline after its last "+" line must not silently
    # rewrite the delivered file's final byte.
    (tmp_path / "a.py").write_text("one\ntwo\n")
    apply_unified(tmp_path, "--- a/a.py\n+++ b/a.py\n@@ -2,1 +2,1 @@\n-two\n+TWO", {"a.py"})
    assert (tmp_path / "a.py").read_text() == "one\nTWO\n"


def test_file_that_never_ended_with_a_newline_is_left_that_way(tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo")
    apply_unified(tmp_path, "--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-one\n+ONE\n", {"a.py"})
    assert (tmp_path / "a.py").read_text() == "ONE\ntwo"


def test_exported_multi_file_patch_is_applyable(tmp_path):
    import subprocess

    original, workspace = tmp_path / "original", tmp_path / "workspace"
    for root in (original, workspace):
        root.mkdir()
    # The second file has no trailing newline: without the standard marker its last
    # line would swallow the following "--- a/" header and break the whole patch.
    (original / "a.py").write_text("alpha\n")
    (workspace / "a.py").write_text("ALPHA\n")
    (original / "b.py").write_text("beta")
    (workspace / "b.py").write_text("BETA")
    patch, edited = source_diff(original, workspace)
    assert edited == ["a.py", "b.py"]
    assert "\\ No newline at end of file" in patch
    (tmp_path / "export.diff").write_text(patch)
    target = tmp_path / "target"
    shutil.copytree(original, target)
    subprocess.run(
        ["git", "apply", "-p1", str(tmp_path / "export.diff")], cwd=target, check=True, capture_output=True
    )
    assert (target / "a.py").read_text() == "ALPHA\n"
    assert (target / "b.py").read_text() == "BETA"
