import json
import os
import shutil
import subprocess
import sys
import time
import uuid

from .config import APPROVED_MODELS, ROOT, SAMPLE, SCENARIOS, data_root
from .contracts import InputError, parse_contract, structural_diff
from .files import atomic_write, digest, tree_hash
from .repository import infer_test_command, snapshot_files
from .runner import cleanup_run, prerequisites
from .schema import Report, RunRequest
from .storage import BusyError, StateError, Store


class PrerequisiteError(RuntimeError):
    pass


class Service:
    def __init__(self, root=None):
        self.store = Store(root or data_root())

    def health(self):
        model = os.environ.get("OPENROUTER_MODEL", "")
        status = {
            **prerequisites(),
            "model_configured": model in APPROVED_MODELS,
            "key_configured": bool(os.environ.get("OPENROUTER_API_KEY")),
        }
        status["ready"] = all(status.values())
        return status

    def require_ready(self):
        status = self.health()
        if not status["ready"]:
            missing = ", ".join(k for k, v in status.items() if not v and k != "ready")
            remedy = "Run api-maintainer doctor."
            if status.get("docker") and not status.get("image"):
                remedy = "From the repository root, run: docker build -t api-maintainer-python:local docker"
            raise PrerequisiteError("Unavailable prerequisites: " + missing + ". " + remedy)

    def create_run(self, request: RunRequest, old=None, new=None, notes=None, key=None, *, launch=True):
        custom = request.sample_id == "repository"
        source_files = None
        inferred = False
        if custom:
            if not request.repository_path or old is None or new is None:
                raise InputError("Provide the client repository and both previous and new OpenAPI documents.")
            request = request.model_copy(update={"scenario_id": None, "mode": "review"})
            source_files = snapshot_files(request.repository_path)
            if not request.test_command:
                suggestion = infer_test_command(source_files)
                inferred = bool(suggestion)
                request = request.model_copy(update={"test_command": suggestion})
            notes = notes if notes is not None else b""
        elif request.scenario_id not in SCENARIOS:
            raise InputError("Unknown scenario.")
        if (old is None) != (new is None):
            raise InputError("Supply both old and new contracts, or use bundled defaults.")
        old = old if old is not None else (SAMPLE / "contracts/old.json").read_bytes()
        new = new if new is not None else (SAMPLE / f"contracts/{request.scenario_id}.json").read_bytes()
        notes = notes if notes is not None else (SAMPLE / f"contracts/{request.scenario_id}.md").read_bytes()
        if len(notes) > 65536:
            raise InputError("Notes exceed 64 KiB.")
        try:
            notes_text = notes.decode("utf-8")
        except UnicodeError as exc:
            raise InputError("Notes must be UTF-8 text.") from exc
        old_doc, new_doc = parse_contract(old), parse_contract(new)
        fingerprint = digest(request.model_dump_json().encode() + old + new + notes)
        if source_files is not None:
            fingerprint = digest(
                fingerprint.encode()
                + b"".join(name.encode() + b"\0" + raw for name, raw in sorted(source_files.items()))
            )
        if key and len(key) > 128:
            raise InputError("Idempotency key exceeds 128 characters.")
        # Check persisted idempotency before prerequisites (retries must retrieve existing runs).
        with self.store.connection() as db:
            if key:
                existing = db.execute("SELECT id,fingerprint FROM runs WHERE key=?", (key,)).fetchone()
                if existing:
                    if existing["fingerprint"] != fingerprint:
                        raise StateError("Idempotency key was already used for different inputs.")
                    return Report.model_validate_json(
                        db.execute("SELECT report FROM runs WHERE id=?", (existing["id"],)).fetchone()[
                            "report"
                        ]
                    )
        if launch:
            self.require_ready()
        report = Report(run_id=uuid.uuid4().hex, **request.model_dump())
        if custom and inferred:
            report.warnings.append(
                "No test command was supplied. This repository's tests import only the standard "
                "library, so " + " ".join(report.test_command) + " was inferred and will verify "
                "the repair. Set a test command and image explicitly to override it."
            )
        elif custom and not report.test_command:
            report.warnings.append(
                "No test command is configured and none could be inferred safely, so the repair "
                "will not be verified. Supply a command and an image containing the repository's "
                "test dependencies to check it."
            )
        report.model = dict(
            requested_id=os.environ.get("OPENROUTER_MODEL"),
            actual_id=None,
            provider=None,
            settings={"temperature": 0, "max_tokens": 8192, "retries": 0, "allow_fallbacks": False},
            sdk_version=None,
        )
        root = self.store.root / "runs" / report.run_id
        try:
            with self.store.connection() as db:
                if key:
                    existing = db.execute(
                        "SELECT report,fingerprint FROM runs WHERE key=?", (key,)
                    ).fetchone()
                    if existing:
                        if existing["fingerprint"] != fingerprint:
                            raise StateError("Idempotency key reused for different inputs.")
                        return Report.model_validate_json(existing["report"])
                if db.execute("SELECT 1 FROM lease").fetchone():
                    raise BusyError("Another migration or evaluation is executing.")
                (root / "inputs").mkdir(parents=True)
                (root / "artifacts").mkdir()
                (root / "protected").mkdir()
                tree_hash(SAMPLE / "consumer")  # Reject symlinks before copytree can follow them.
                for source, name in (
                    ()
                    if custom
                    else (
                        (SAMPLE / "mock_service", "mock_service"),
                        (SAMPLE / "development_checks", "development_checks"),
                        (ROOT / "evaluation/checks", "evaluation_checks"),
                    )
                ):
                    tree_hash(source)
                    shutil.copytree(
                        source,
                        root / "protected" / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                if source_files is not None:
                    for name, raw in source_files.items():
                        target = root / "original" / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(raw)
                else:
                    shutil.copytree(
                        SAMPLE / "consumer",
                        root / "original",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                shutil.copytree(root / "original", root / "workspace")
                for name, value in [
                    ("old.json", json.dumps(old_doc, indent=2)),
                    ("new.json", json.dumps(new_doc, indent=2)),
                    ("notes.md", notes_text),
                    ("diff.json", json.dumps(structural_diff(old_doc, new_doc), indent=2)),
                ]:
                    atomic_write(root / "inputs" / name, value + "\n")
                # Preserve exact uploaded bytes as immutable input evidence as well.
                (root / "inputs/old.original").write_bytes(old)
                (root / "inputs/new.original").write_bytes(new)
                (root / "inputs/notes.original").write_bytes(notes)
                for folder in ("original", "inputs", "protected"):
                    for p in (root / folder).rglob("*"):
                        if p.is_file():
                            p.chmod(0o444)
                report.inputs = dict(
                    old_contract_hash=digest(old),
                    new_contract_hash=digest(new),
                    consumer_hash=tree_hash(root / "original"),
                    notes_hash=digest(notes),
                    snapshot_hash=tree_hash(root / "inputs"),
                    protected_hash=tree_hash(root / "protected"),
                    api_versions={"old": old_doc["info"]["version"], "new": new_doc["info"]["version"]},
                )
                db.execute(
                    "INSERT INTO runs VALUES(?,?,?,?)",
                    (report.run_id, report.model_dump_json(), key, fingerprint),
                )
                if launch:
                    report.lifecycle = "analyzing"
                    db.execute(
                        "UPDATE runs SET report=? WHERE id=?", (report.model_dump_json(), report.run_id)
                    )
                    db.execute(
                        "INSERT INTO lease(singleton,run,pid,heartbeat,kind) VALUES(1,?,NULL,?,?)",
                        (report.run_id, time.time(), "analyzing"),
                    )
        except BaseException:
            if root.exists():
                shutil.rmtree(root)
            raise
        if launch:
            self.spawn(report.run_id, "analyzing")
        return report

    def spawn(self, run_id, stage):
        try:
            env = {**os.environ, "API_MAINTAINER_DATA": str(self.store.root)}
            worker = subprocess.Popen(
                [sys.executable, "-m", "api_maintainer.supervisor", run_id, stage],
                env=env,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.store.heartbeat(run_id, worker.pid)
        except OSError:
            self.store.release(run_id)
            from .reports import finalize

            finalize(self.store, self.store.get(run_id), "worker_interrupted")
            raise PrerequisiteError("Could not launch the local worker.")

    def request_repair(self, run_id):
        report = self.store.get(run_id)
        if report.lifecycle in ("repairing", "finalizing", "finished"):
            return report
        if report.lifecycle != "awaiting_review":
            raise StateError("Run is not awaiting review.")
        self.require_ready()
        if self.store.claim(run_id, "repairing"):
            self.spawn(run_id, "repairing")
        return self.store.get(run_id)

    def request_evaluation(self, run_id):
        if self.store.get(run_id).sample_id == "repository":
            raise StateError(
                "Independent bookstore evaluation does not apply to a client repository. Use its configured tests."
            )
        if not all(prerequisites().values()):
            raise PrerequisiteError("Docker and the prebuilt execution image are required.")
        self.store.claim(run_id, "evaluation")
        report = self.store.get(run_id)
        report.evaluation = dict(
            verdict="incomplete", artifact_id=None, evaluated_revision_hash=report.patch["final_hash"]
        )
        self.store.save(report)
        self.spawn(run_id, "evaluation")

    def get_run(self, run_id):
        return self.store.get(run_id)

    def revise_analysis(self, run_id, summary, notes, *, launch=True):
        report = self.store.get(run_id)
        if report.lifecycle != "awaiting_review":
            raise StateError("Only an analysis awaiting review can be revised.")
        root = self.store.root / "runs" / run_id
        request = RunRequest(
            sample_id=report.sample_id,
            scenario_id=report.scenario_id,
            mode="review",
            repository_path=str(root / "original") if report.sample_id == "repository" else None,
            test_command=report.test_command,
            test_image=report.test_image,
        )
        revised = (
            (root / "inputs/notes.md").read_text()
            + "\nReviewer corrections to migration summary:\n"
            + summary
            + "\nReviewer notes:\n"
            + notes
        )
        result = self.create_run(
            request,
            (root / "inputs/old.original").read_bytes(),
            (root / "inputs/new.original").read_bytes(),
            revised.encode(),
            launch=False,
        )
        result.parent_run_id = run_id
        result.repository_path = report.repository_path
        self.store.save(result)
        if launch:
            self.require_ready()
            if self.store.claim(result.run_id, "analyzing"):
                self.spawn(result.run_id, "analyzing")
        return self.store.get(result.run_id)

    def get_artifact(self, run_id, artifact_id):
        report = self.store.get(run_id)
        if artifact_id not in report.artifacts or "/" in artifact_id or "\\" in artifact_id:
            raise KeyError("Unknown artifact.")
        path = self.store.root / "runs" / run_id / "artifacts" / artifact_id
        if path.is_symlink() or not path.is_file():
            raise KeyError("Artifact is unavailable.")
        return path

    def reconcile(self):
        # Startup only: an awaiting-review run has no lease and is unaffected.
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM lease").fetchone()
        if not row or time.time() - row["heartbeat"] < 15:
            return
        if row["pid"]:
            try:
                os.kill(row["pid"], 0)
                return
            except ProcessLookupError:
                pass
        if row["worker_pid"]:
            from .runner import terminate_owned_worker

            terminate_owned_worker(row["worker_pid"], row["run"])
        cleanup_run(row["run"])
        if row["kind"] != "evaluation":
            from .reports import finalize

            report = self.store.get(row["run"])
            finalize(self.store, report, "worker_interrupted")
            report.lifecycle = "interrupted"
            from .reports import write_report

            write_report(self.store, report)
        if row["kind"] == "evaluation":
            from .evaluation import record_incomplete

            record_incomplete(self, row["run"], "Evaluation worker was interrupted.")
        self.store.release(row["run"])
