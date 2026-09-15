"""Real Docker baseline/isolation checks. Skipped when Docker/image is unavailable."""

import shutil
import uuid

import pytest

from api_maintainer.config import SAMPLE, SCENARIOS
from api_maintainer.runner import DockerRunner, prerequisites

pytestmark = pytest.mark.skipif(
    not all(prerequisites().values()), reason="Docker daemon/prebuilt image unavailable"
)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_original_old_and_new_behavior(tmp_path, scenario):
    workspace = tmp_path / "source"
    shutil.copytree(SAMPLE / "consumer", workspace)
    runner = DockerRunner(uuid.uuid4().hex, scenario)
    assert runner.check(workspace, version="old")["status"] == "passed"
    result = runner.check(workspace, version="new")
    assert result["status"] == ("passed" if scenario == "optional-field" else "failed")


def test_container_isolation(tmp_path):
    workspace = tmp_path / "source"
    shutil.copytree(SAMPLE / "consumer", workspace)
    runner = DockerRunner(uuid.uuid4().hex, "endpoint-rename")
    with runner.context() as (run, flags, name):
        code, log, _ = run(
            [
                "run",
                "--rm",
                "--name",
                name,
                *flags,
                "--mount",
                f"type=bind,src={workspace},dst=/source,readonly",
                "api-maintainer-python:local",
                "python",
                "-c",
                'import os,socket; from pathlib import Path; assert os.getuid()!=0; assert "OPENROUTER_API_KEY" not in os.environ; '
                'assert not Path("/var/run/docker.sock").exists(); '
                'assert not Path("/evaluation").exists(); '
                '\ntry: Path("/source/app.py").write_text("bad")\nexcept OSError: pass\nelse: raise AssertionError("writable source")'
                '\ntry: socket.create_connection(("1.1.1.1",443),timeout=2)\nexcept OSError: pass\nelse: raise AssertionError("external egress")',
            ]
        )
        assert code == 0, log


@pytest.mark.parametrize(
    "scenario", ["endpoint-rename", "response-field-rename", "nested-price", "wrapper-price"]
)
def test_valid_source_prefixed_repairs_pass_real_checks(tmp_path, scenario):
    """Known repairs exercise patch-to-Docker integration, not live model quality."""
    import difflib

    from api_maintainer.files import apply_unified

    workspace = tmp_path / "source"
    shutil.copytree(SAMPLE / "consumer", workspace)
    before = (workspace / "client.py").read_text()
    if scenario == "endpoint-rename":
        after = before.replace("/books/", "/catalog/books/")
    elif scenario == "response-field-rename":
        after = before.replace("book['title']", "book['name']")
    else:
        after = "from decimal import Decimal\n" + before.replace(
            "book['price']", "Decimal(str(book['pricing']['amount_cents'])) / 100"
        )
    patch = "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile="a/source/client.py",
            tofile="b/source/client.py",
        )
    )
    apply_unified(workspace, patch, {"client.py"})
    result = DockerRunner(uuid.uuid4().hex, scenario).check(workspace)
    assert result["status"] == "passed", result["log"]


def test_repository_command_executes_actual_client_tests(tmp_path):
    from api_maintainer.runner import RepositoryRunner
    from api_maintainer.schema import Report

    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "client.py").write_text("def value(): return 2\n")
    (workspace / "test_client.py").write_text(
        "import unittest\nfrom client import value\nclass Check(unittest.TestCase):\n def test_value(self): self.assertEqual(value(), 2)\n"
    )
    report = Report(
        run_id=uuid.uuid4().hex, sample_id="repository", test_command=["python", "-m", "unittest", "discover"]
    )
    result = RepositoryRunner(report).check(workspace)
    assert result["status"] == "passed", result["log"]
    (workspace / "client.py").write_text("def value(): return 3\n")
    result = RepositoryRunner(report).check(workspace)
    assert result["status"] == "failed", result["log"]
