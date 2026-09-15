"""Repository-first flow: real snapshots/API, scripted model and isolated checks."""

import difflib

import pytest
from fastapi.testclient import TestClient

from api_maintainer.api import create_app
from api_maintainer.config import SAMPLE
from api_maintainer.contracts import InputError
from api_maintainer.files import source_diff
from api_maintainer.migration import Service
from api_maintainer.repository import STDLIB_TEST_COMMAND, infer_test_command, snapshot_files
from api_maintainer.runner import RepositoryRunner
from api_maintainer.schema import RunRequest
from api_maintainer.storage import StateError
from api_maintainer.tools import Tools
from api_maintainer.worker import execute


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "client"
    root.mkdir()
    (root / "client.ts").write_text('export const route = "/books";\n')
    (root / ".env").write_text("DO_NOT_COPY=true")
    (root / "credentials.json").write_text("DO_NOT_COPY")
    (root / "tests").mkdir()
    (root / "tests/client.test.ts").write_text("test fixture\n")
    (root / "node_modules").mkdir()
    (root / "node_modules/ignored.js").write_text("ignored")
    return root


def contracts():
    return (SAMPLE / "contracts/old.json").read_bytes(), (
        SAMPLE / "contracts/endpoint-rename.json"
    ).read_bytes()


def make(s, repo):
    return s.create_run(
        RunRequest(sample_id="repository", repository_path=str(repo), mode="auto"), *contracts(), launch=False
    )


def analyze(stage, t):
    if stage == "analyzing":
        t.submit_analysis(
            {
                "summary": "Endpoint moved; update the client route.",
                "changes": [
                    {
                        "id": "route",
                        "kind": "endpoint_rename",
                        "description": "Route changed",
                        "disposition": "repair",
                        "evidence": [{"path": "inputs/new.json", "pointer": "#/info"}],
                        "affected_locations": [{"path": "source/client.ts", "line_start": 1}],
                    }
                ],
            }
        )
    else:
        before = (t.workspace / "client.ts").read_text()
        after = before.replace("/books", "/catalog/books")
        patch = "".join(
            difflib.unified_diff(
                before.splitlines(True),
                after.splitlines(True),
                fromfile="a/source/client.ts",
                tofile="b/source/client.ts",
            )
        )
        t.apply_patch(patch, "Approved endpoint change")
        t.finish_repair("Updated route")


def test_repository_review_repair_and_no_false_verification(tmp_path, repo):
    s = Service(tmp_path / "data")
    r = make(s, repo)
    assert r.scenario_id is None and r.mode == "review"
    root = s.store.root / "runs" / r.run_id
    assert not (root / "original/.env").exists()
    assert not (root / "original/credentials.json").exists()
    assert not list((root / "protected").iterdir())
    s.store.claim(r.run_id, "analyzing")
    execute(s.store, r.run_id, "analyzing", agent=analyze)
    s.store.release(r.run_id)
    r = s.get_run(r.run_id)
    assert r.lifecycle == "awaiting_review" and r.analysis_summary
    assert (root / "workspace/client.ts").read_text() == (repo / "client.ts").read_text()
    s.store.claim(r.run_id, "repairing")
    execute(s.store, r.run_id, "repairing", agent=analyze)
    s.store.release(r.run_id)
    r = s.get_run(r.run_id)
    assert r.patch["edited_files"] == ["client.ts"]
    assert r.development_verification == "incomplete" and r.outcome == "verification_incomplete"
    assert "/catalog/" not in (repo / "client.ts").read_text()
    assert "/catalog/" in source_diff(root / "original", root / "workspace")[0]
    with pytest.raises(StateError):
        s.request_evaluation(r.run_id)


def test_edits_reanalyze_original_snapshot(tmp_path, repo):
    s = Service(tmp_path / "data")
    r = make(s, repo)
    t = Tools(s.store, r, RepositoryRunner(r))
    analyze("analyzing", t)
    r.lifecycle = "awaiting_review"
    s.store.save(r)
    (repo / "client.ts").write_text("unrelated later change\n")
    revised = s.revise_analysis(r.run_id, "Corrected summary", "Preserve return type", launch=False)
    root = s.store.root / "runs" / revised.run_id
    assert revised.parent_run_id == r.run_id and revised.mode == "review"
    assert "unrelated later" not in (root / "original/client.ts").read_text()
    assert "Corrected summary" in (root / "inputs/notes.md").read_text()
    assert revised.changes == [] and revised.lifecycle == "created"
    assert s.get_run(r.run_id).analysis_summary == r.analysis_summary


def test_repository_requires_all_three_inputs_and_preserves_tests(tmp_path, repo):
    s = Service(tmp_path / "data")
    with pytest.raises(InputError):
        s.create_run(RunRequest(sample_id="repository", repository_path=str(repo)), launch=False)
    r = make(s, repo)
    r.lifecycle = "repairing"
    from api_maintainer.schema import Change, Evidence

    r.changes = [
        Change(
            id="bad",
            kind="test",
            description="test",
            disposition="repair",
            evidence=[Evidence(path="source/tests/client.test.ts", line_start=1)],
            affected_locations=[Evidence(path="source/tests/client.test.ts", line_start=1)],
        )
    ]
    t = Tools(s.store, r, RepositoryRunner(r))
    with pytest.raises(ValueError):
        t.apply_patch(
            "--- a/tests/client.test.ts\n+++ b/tests/client.test.ts\n@@ -1 +1 @@\n-test fixture\n+new\n",
            "Attempt to alter tests",
        )
    (repo / "outside.ts").symlink_to(repo / ".env")
    assert "outside.ts" not in snapshot_files(str(repo))


@pytest.mark.parametrize(
    "files,expected",
    [
        ({"c.py": b"import json\n", "tests/test_c.py": b"import unittest, c\n"}, STDLIB_TEST_COMMAND),
        (
            {"pkg/__init__.py": b"", "pkg/a.py": b"from . import a\n", "t_test.py": b"import pkg\n"},
            STDLIB_TEST_COMMAND,
        ),
        # A third-party import anywhere means the default image cannot run the suite.
        ({"c.py": b"import requests\n", "tests/test_c.py": b"import c\n"}, []),
        ({"c.py": b"import json\n", "tests/test_c.py": b"import pytest\n"}, []),
        # Nothing to discover, so nothing to suggest.
        ({"c.py": b"import json\n"}, []),
        # Unparseable source could hide any import; refuse rather than guess.
        ({"c.py": b"def (\n", "tests/test_c.py": b"import unittest\n"}, []),
    ],
)
def test_infer_test_command_only_suggests_for_stdlib_only_repositories(files, expected):
    assert infer_test_command(files) == expected


@pytest.fixture
def python_repo(tmp_path):
    root = tmp_path / "py-client"
    (root / "tests").mkdir(parents=True)
    (root / "client.py").write_text('import json\n\nROUTE = "/books"\n')
    (root / "tests/__init__.py").write_text("")
    (root / "tests/test_client.py").write_text("import unittest\n\nimport client\n")
    return root


def test_create_run_infers_a_test_command_and_records_why(tmp_path, python_repo, monkeypatch):
    s = Service(tmp_path / "data")
    monkeypatch.setattr(s, "require_ready", lambda: None)
    monkeypatch.setattr(s, "spawn", lambda id, stage: None)
    old, new = contracts()
    report = s.create_run(
        RunRequest(sample_id="repository", repository_path=str(python_repo)), old=old, new=new
    )
    assert report.test_command == STDLIB_TEST_COMMAND
    assert any("was inferred" in w for w in report.warnings)


def test_create_run_warns_when_no_command_can_be_inferred(tmp_path, repo, monkeypatch):
    # The TypeScript fixture has no unittest-style suite, so nothing is safe to guess.
    s = Service(tmp_path / "data")
    monkeypatch.setattr(s, "require_ready", lambda: None)
    monkeypatch.setattr(s, "spawn", lambda id, stage: None)
    old, new = contracts()
    report = s.create_run(RunRequest(sample_id="repository", repository_path=str(repo)), old=old, new=new)
    assert report.test_command == []
    assert any("will not be verified" in w for w in report.warnings)


def test_an_explicit_test_command_is_never_overridden(tmp_path, repo, monkeypatch):
    s = Service(tmp_path / "data")
    monkeypatch.setattr(s, "require_ready", lambda: None)
    monkeypatch.setattr(s, "spawn", lambda id, stage: None)
    old, new = contracts()
    report = s.create_run(
        RunRequest(sample_id="repository", repository_path=str(repo), test_command=["pytest", "-q"]),
        old=old,
        new=new,
    )
    assert report.test_command == ["pytest", "-q"]
    assert not any("inferred" in w for w in report.warnings)


def test_repository_api_create_and_edit_review(tmp_path, repo, monkeypatch):
    s = Service(tmp_path / "data")
    monkeypatch.setattr(s, "require_ready", lambda: None)

    def spawn(id, stage):
        execute(s.store, id, stage, agent=analyze)
        s.store.release(id)

    monkeypatch.setattr(s, "spawn", spawn)
    client = TestClient(create_app(s))
    old, new = contracts()
    response = client.post(
        "/api/runs",
        data={"sample_id": "repository", "repository_path": str(repo), "test_command": "python -m unittest"},
        files={"old_spec": ("old.json", old), "new_spec": ("new.json", new)},
    )
    assert response.status_code == 202, response.text
    id = response.json()["run_id"]
    report = client.get("/api/runs/" + id).json()
    assert report["lifecycle"] == "awaiting_review" and report["scenario_id"] is None
    assert report["test_command"] == ["python", "-m", "unittest"]
    revised = client.post(
        "/api/runs/" + id + "/revise", json={"summary": "Keep existing behavior", "notes": "Check the route"}
    )
    assert revised.status_code == 202, revised.text
    assert revised.json()["parent_run_id"] == id
    assert revised.json()["lifecycle"] == "awaiting_review"
    assert client.post("/api/runs/" + id + "/revise", json={"summary": 42}).status_code == 422
