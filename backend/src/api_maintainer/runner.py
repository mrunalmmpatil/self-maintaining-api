"""Only this module launches consumer code. All such execution is in Docker."""

import json
import subprocess
import time
import uuid
from contextlib import contextmanager

from .config import IMAGE, SAMPLE

LOG_CAP = 65536


def command(args, timeout=10):
    """Bound pipe output while draining it, preventing unbounded memory/log growth."""
    import os
    import selectors

    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = bytearray()
    truncated = False
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args[0], timeout)
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    available = LOG_CAP - len(output)
                    output.extend(chunk[:available])
                    truncated |= len(chunk) > available
        return (
            process.wait(timeout=max(0.01, deadline - time.monotonic())),
            output.decode(errors="replace"),
            truncated,
        )
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def prerequisites():
    try:
        code, _, _ = command(["docker", "info", "--format", "{{.ServerVersion}}"], 5)
        if code:
            return {"docker": False, "image": False}
        code, _, _ = command(["docker", "image", "inspect", IMAGE], 5)
        if code:
            # A momentary daemon stall exits nonzero exactly like a missing image, and the
            # remedy printed for that is a pointless rebuild. Confirm once before claiming it.
            code, _, _ = command(["docker", "image", "inspect", IMAGE], 5)
        return {"docker": True, "image": code == 0}
    except (OSError, subprocess.TimeoutExpired):
        return {"docker": False, "image": False}


class DockerRunner:
    def __init__(self, run_id, scenario, warnings=None, fixtures=None):
        self.run_id, self.scenario = run_id, scenario
        self.fixtures = fixtures or SAMPLE
        self.warnings = warnings if warnings is not None else []

    @contextmanager
    def context(self, seconds=120, version="new"):
        suffix = uuid.uuid4().hex[:10]
        network, mock, consumer = [f"apim-{suffix}-{name}" for name in ("net", "mock", "consumer")]
        deadline = time.monotonic() + seconds

        def run(args):
            return command(["docker", *args], max(0.01, min(120, deadline - time.monotonic())))

        hardening = [
            "--user",
            "65534:65534",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--cpus",
            "1",
            "--memory",
            "512m",
            "--pids-limit",
            "128",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m",
            "--label",
            f"api-maintainer.run={self.run_id}",
            "--network",
            network,
            "--log-driver",
            "none",
        ]
        try:
            code, _, _ = run(
                ["network", "create", "--internal", "--label", f"api-maintainer.run={self.run_id}", network]
            )
            if code:
                raise RuntimeError("Cannot create isolated Docker network.")
            code, _, _ = run(
                [
                    "run",
                    "-d",
                    "--name",
                    mock,
                    "--network-alias",
                    "mock",
                    *hardening,
                    "--mount",
                    f"type=bind,src={self.fixtures / 'mock_service'},dst=/mock,readonly",
                    "-e",
                    f"SCENARIO={self.scenario}",
                    "-e",
                    f"API_VERSION={version}",
                    IMAGE,
                    "python",
                    "/mock/server.py",
                ]
            )
            if code:
                raise RuntimeError("Cannot start bookstore mock.")
            ready = False
            for _ in range(30):
                code, _, _ = run(
                    [
                        "exec",
                        mock,
                        "python",
                        "-c",
                        'from urllib.request import urlopen; urlopen("http://localhost:8080/health", timeout=1).read()',
                    ]
                )
                if code == 0:
                    ready = True
                    break
                time.sleep(0.1)
            if not ready:
                raise RuntimeError("Bookstore mock did not become ready.")
            yield run, hardening, consumer
        finally:
            cleanup_deadline = time.monotonic() + 10
            for args in (["rm", "-f", consumer, mock], ["network", "rm", network]):
                try:
                    code, _, _ = command(["docker", *args], max(0.01, cleanup_deadline - time.monotonic()))
                    if code and args[0] == "network":
                        self.warnings.append("Docker network cleanup failed; run doctor before retrying.")
                except (OSError, subprocess.TimeoutExpired):
                    self.warnings.append("Docker cleanup did not finish within grace period.")

    def check(self, workspace, seconds=120, version="new"):
        start = time.monotonic()
        try:
            with self.context(seconds, version) as (run, flags, name):
                code, log, truncated = run(
                    [
                        "run",
                        "--name",
                        name,
                        *flags,
                        "--mount",
                        f"type=bind,src={workspace},dst=/source,readonly",
                        "--mount",
                        f"type=bind,src={self.fixtures / 'development_checks'},dst=/checks,readonly",
                        IMAGE,
                        "python",
                        "/checks/check.py",
                    ]
                )
            return dict(
                exit_code=code,
                status="passed" if code == 0 else "failed",
                duration=time.monotonic() - start,
                log=log,
                truncated=truncated,
                components=self.components(log),
            )
        except (subprocess.TimeoutExpired, OSError, RuntimeError):
            return dict(
                exit_code=None,
                status="incomplete",
                duration=time.monotonic() - start,
                log="Docker check could not finish. Verify Docker readiness and execution timeout.",
                truncated=False,
            )

    @staticmethod
    def components(log):
        for line in reversed(log.splitlines()):
            try:
                value = json.loads(line)
                if value.get("component") == "endpoint_reaches_country_validation":
                    return {"endpoint_reaches_country_validation": value.get("passed") is True}
            except (ValueError, AttributeError):
                continue
        return {}

    def evaluate(self, workspace, cases):
        results = []
        with self.context(120) as (run, flags, name):
            for index, case in enumerate(cases):
                code, output, truncated = run(
                    [
                        "run",
                        "--rm",
                        "--name",
                        name,
                        *flags,
                        "--mount",
                        f"type=bind,src={workspace},dst=/source,readonly",
                        IMAGE,
                        "python",
                        "/source/app.py",
                        str(case["book_id"]),
                        str(case["quantity"]),
                    ]
                )
                try:
                    observed = json.loads(output)
                except ValueError:
                    observed = None
                results.append(
                    dict(
                        case=index + 1,
                        passed=code == 0 and observed == case["expected"],
                        observed=observed,
                        exit_code=code,
                        truncated=truncated,
                    )
                )
        return results


def cleanup_run(run_id):
    for kind in ("container", "network"):
        try:
            code, output, _ = command(
                ["docker", kind, "ls", "-q", "--filter", f"label=api-maintainer.run={run_id}"], 2
            )
            ids = output.split() if code == 0 else []
            if ids:
                command(["docker", kind, "rm", *(["-f"] if kind == "container" else []), *ids], 3)
        except (OSError, subprocess.TimeoutExpired):
            pass


def terminate_owned_worker(pid, run_id):
    """Avoid killing a reused PID: verify this exact project's worker command first."""
    import os
    import signal

    try:
        code, cmdline, _ = command(["ps", "-p", str(pid), "-o", "command="], 2)
        if (
            code == 0
            and run_id in cmdline
            and any(
                module in cmdline for module in ("-m api_maintainer.worker", "-m api_maintainer.evaluation")
            )
        ):
            os.killpg(pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        pass


class RepositoryRunner:
    """User-configured checks, executed without host credentials or network access."""

    def __init__(self, report):
        self.report = report

    def check(self, workspace, seconds=120):
        start = time.monotonic()
        result = dict(
            exit_code=None, status="incomplete", duration=0, truncated=False, suite="repository-tests"
        )
        argv = self.report.test_command
        if not argv:
            return {
                **result,
                "log": "No repository test command was configured. The patch has not been verified.",
            }
        name = "apim-repo-" + uuid.uuid4().hex[:12]
        try:
            code, _, _ = command(["docker", "image", "inspect", self.report.test_image], 5)
            if code:
                return {
                    **result,
                    "log": "Configured test image is unavailable. Build it locally with the project dependencies before running checks.",
                }
            code, log, truncated = command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull=never",
                    "--name",
                    name,
                    "--label",
                    f"api-maintainer.run={self.report.run_id}",
                    "--network",
                    "none",
                    "--user",
                    "65534:65534",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--cpus",
                    "1",
                    "--memory",
                    "512m",
                    "--pids-limit",
                    "128",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=32m",
                    "--mount",
                    f"type=bind,src={workspace},dst=/source,readonly",
                    "--workdir",
                    "/source",
                    "--env",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "--entrypoint",
                    argv[0],
                    self.report.test_image,
                    *argv[1:],
                ],
                seconds,
            )
            result.update(
                exit_code=code, status="passed" if code == 0 else "failed", log=log, truncated=truncated
            )
        except (OSError, subprocess.TimeoutExpired):
            result["log"] = "Repository tests could not finish within the Docker execution limit."
        finally:
            try:
                command(["docker", "rm", "-f", name], 5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        result["duration"] = time.monotonic() - start
        return result
