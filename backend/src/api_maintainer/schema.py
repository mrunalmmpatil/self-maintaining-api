from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def now():
    return datetime.now(timezone.utc).isoformat()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Strict):
    path: str
    pointer: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)


class Change(Strict):
    id: str
    kind: str
    description: str
    evidence: list[Evidence] = Field(min_length=1)
    affected_locations: list[Evidence] = []
    disposition: Literal["repair", "manual", "no_change", "uncertain"]
    repair_summary: str = ""
    verification_refs: list[str] = []


class ManualAction(Strict):
    change_id: str
    required_work: str
    affected_locations: list[Evidence]
    unresolved_decision: str
    blocking_effect: str


class Analysis(Strict):
    changes: list[Change]
    manual_actions: list[ManualAction] = []
    summary: str


class Budget(Strict):
    policy_version: str = "1"
    limits: dict[str, int] = Field(
        default_factory=lambda: dict(
            requests=20,
            tools=30,
            patch_attempts=6,
            checks=4,
            analysis_requests=5,
            request_seconds=180,
            check_seconds=120,
            active_seconds=1200,
        )
    )
    used_requests: int = 0
    used_tools: int = 0
    used_patch_attempts: int = 0
    used_checks: int = 0
    analysis_requests: int = 0
    active_seconds: float = 0


class Check(Strict):
    id: str
    revision_hash: str
    suite: str = "bookstore-development"
    exit_code: int | None
    status: Literal["passed", "failed", "incomplete"]
    duration: float
    log_artifact_id: str
    truncated: bool = False
    components: dict[str, bool] = {}


class Report(Strict):
    schema_version: str = "1"
    run_id: str
    mode: Literal["auto", "review"] = "review"
    sample_id: str = "bookstore"
    scenario_id: str | None = None
    repository_path: str | None = None
    test_command: list[str] = []
    test_image: str = "api-maintainer-python:local"
    analysis_summary: str = ""
    parent_run_id: str | None = None
    created_at: str = Field(default_factory=now)
    started_at: str | None = None
    finished_at: str | None = None
    lifecycle: Literal[
        "created", "analyzing", "awaiting_review", "repairing", "finalizing", "finished", "interrupted"
    ] = "created"
    termination_reason: str | None = None
    inputs: dict = {}
    model: dict = {}
    budget: Budget = Field(default_factory=Budget)
    changes: list[Change] = []
    manual_actions: list[ManualAction] = []
    patch: dict = {}
    development_checks: list[Check] = []
    outcome: str | None = None
    # Derived in status.apply_result on every store read/write: the single
    # pass/partial/review/fail/running verdict shown by the CLI and the web UI.
    result: Literal["pass", "partial", "review", "fail", "running"] = "running"
    result_reason: str = ""
    development_verification: str = "not_run"
    usage: dict = Field(
        default_factory=lambda: dict(
            input_tokens=None, output_tokens=None, other_provider_usage=None, complete=False
        )
    )
    artifacts: list[str] = []
    warnings: list[str] = []
    evaluation: dict = Field(
        default_factory=lambda: dict(verdict="not_run", artifact_id=None, evaluated_revision_hash=None)
    )


class RunRequest(Strict):
    sample_id: Literal["bookstore", "repository"] = "bookstore"
    scenario_id: str | None = "endpoint-rename"
    repository_path: str | None = None
    test_command: list[str] = Field(default_factory=list, max_length=64)
    test_image: str = Field(
        default="api-maintainer-python:local", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._/:@-]{0,200}$"
    )
    mode: Literal["auto", "review"] = "review"
