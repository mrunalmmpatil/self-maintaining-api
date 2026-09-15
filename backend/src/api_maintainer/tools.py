import json
import time

from .contracts import pointer_get
from .files import apply_edits, apply_unified, atomic_write, safe_path, tree_hash
from .repository import editable
from .schema import Analysis, Check
from .status import stage_name


class BudgetExceeded(RuntimeError):
    pass


class Tools:
    def __init__(self, store, report, runner):
        self.store, self.report, self.runner = store, report, runner
        self.root = store.root / "runs" / report.run_id
        self.workspace = self.root / "workspace"
        self.allowed = {str(p.relative_to(self.workspace)) for p in self.workspace.rglob("*") if p.is_file()}
        self.started = time.monotonic()
        self.initial_active = report.budget.active_seconds
        self.submitted = False
        self.failure = None

    def remaining(self):
        self.report.budget.active_seconds = self.initial_active + time.monotonic() - self.started
        return self.report.budget.limits.get("active_seconds", 1200) - self.report.budget.active_seconds

    def save(self):
        self.remaining()
        self.store.save(self.report)

    def count(self, counter):
        budget = self.report.budget
        if self.remaining() <= 0:
            self.failure = "budget_exceeded"
            raise BudgetExceeded("Active execution deadline reached.")
        name = "used_" + counter
        if getattr(budget, name) >= budget.limits[counter]:
            self.failure = "budget_exceeded"
            raise BudgetExceeded(f"{counter} budget exhausted.")
        if counter == "requests" and self.report.lifecycle == "analyzing":
            if budget.analysis_requests >= 5:
                self.failure = "budget_exceeded"
                raise BudgetExceeded("Analysis request allowance exhausted.")
            budget.analysis_requests += 1
        setattr(budget, name, getattr(budget, name) + 1)
        self.save()

    def log(self, kind, message, status="info", started=None):
        """Record one activity line attributed to the agent stage that produced it."""
        self.store.event(
            self.report.run_id,
            kind,
            message,
            stage=stage_name(self.report.lifecycle),
            status=status,
            duration_ms=None if started is None else int((time.monotonic() - started) * 1000),
        )

    def describe(self, name, args, result):
        """A one-line, human-readable record of what a successful tool call did."""
        if name == "list_files":
            return f"Listed {len(result['files'])} readable files."
        if name == "read_file":
            start = args.get("line_start", 1)
            return f"Read {args.get('path')} from line {start} ({len(result.splitlines())} lines)."
        if name == "search_code":
            return f"Searched for {args.get('query')!r}: {len(result)} matches."
        if name == "submit_analysis":
            manual = len(self.report.manual_actions)
            return (
                f"Submitted analysis: {len(self.report.changes)} change(s), "
                f"{sum(c.disposition == 'repair' for c in self.report.changes)} repairable, "
                f"{manual} needing a person."
            )
        if name == "apply_patch":
            return f"Patch applied; source is now at revision {result['revision_hash'][:12]}."
        if name == "finish_repair":
            return "Repair stage submitted."
        return name

    def invoke(self, name, **args):
        if not getattr(self, "hook_counts_tools", False):
            self.count("tools")
        started = time.monotonic()
        try:
            if self.submitted:
                raise ValueError("Stage already submitted.")
            reads = {"list_files", "read_file", "search_code"}
            permitted = reads | (
                {"submit_analysis"}
                if self.report.lifecycle == "analyzing"
                else {"apply_edits", "apply_patch", "run_checks", "finish_repair"}
            )
            if name not in permitted:
                raise ValueError("Tool is unavailable in this stage.")
            result = getattr(self, name)(**args)
        except BudgetExceeded as exc:
            self.log("tool", f"{name} stopped: {exc}", "error", started)
            raise
        except Exception as exc:
            # These are this service's own validation messages, not raw SDK errors;
            # the full rejected patch is already retained as a downloadable artifact.
            self.log("tool", f"{name} rejected: {str(exc)[:200]}", "error", started)
            raise
        if name != "run_checks":  # run_checks logs its own verdict, from either caller.
            self.log("tool", self.describe(name, args, result), "ok", started)
        return result

    def list_files(self, prefix="", offset=0):
        if offset < 0:
            raise ValueError("Offset must be nonnegative.")
        names = sorted(
            ["source/" + p for p in self.allowed]
            + ["inputs/old.json", "inputs/new.json", "inputs/notes.md", "inputs/diff.json"]
        )
        names = [p for p in names if p.startswith(prefix)]
        return {
            "files": names[offset : offset + 100],
            "next_offset": offset + 100 if len(names) > offset + 100 else None,
        }

    def path(self, path):
        if path.startswith("source/"):
            return safe_path(self.workspace, path[7:], self.allowed)
        return safe_path(
            self.root, path, {"inputs/old.json", "inputs/new.json", "inputs/notes.md", "inputs/diff.json"}
        )

    def read_file(self, path, line_start=1, line_count=200):
        if line_start < 1 or not 1 <= line_count <= 200:
            raise ValueError("Read 1–200 lines, starting at line 1 or later.")
        lines = self.path(path).read_text().splitlines()
        result = "\n".join(
            f"{i + 1}: {line}"
            for i, line in enumerate(lines)
            if line_start - 1 <= i < line_start - 1 + line_count
        )
        return result.encode()[:32768].decode(errors="replace")

    def search_code(self, query, prefix=""):
        if not query or len(query) > 500:
            raise ValueError("Supply a literal query of 1–500 characters.")
        found = []
        for name in sorted(self.allowed):
            if name.startswith(prefix.removeprefix("source/")):
                for number, line in enumerate((self.workspace / name).read_text().splitlines(), 1):
                    if query in line:
                        found.append(dict(path="source/" + name, line=number, text=line[:300]))
                        if len(found) == 50:
                            return found
        return found

    def validate_evidence(self, evidence):
        path = self.path(evidence.path)
        if evidence.pointer is not None:
            if evidence.path not in ("inputs/old.json", "inputs/new.json", "inputs/diff.json"):
                raise ValueError("JSON pointers must reference JSON inputs.")
            # RFC 6901 pointers also have a plain /path representation. Normalize
            # evidence only; OpenAPI $ref validation remains local-fragment-only.
            if evidence.pointer == "" or evidence.pointer.startswith("/"):
                evidence.pointer = "#" + evidence.pointer
            try:
                pointer_get(json.loads(path.read_text()), evidence.pointer)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid evidence in {evidence.path}: {exc}. "
                    "Read this exact file and cite its numbered line_start/line_end instead; "
                    "do not reuse a pointer from a different contract."
                ) from exc
        elif evidence.line_start is not None:
            end = evidence.line_end or evidence.line_start
            if end < evidence.line_start or end > len(path.read_text().splitlines()):
                raise ValueError("Evidence line range is outside the referenced file.")
        else:
            raise ValueError("Evidence needs a JSON pointer or line range.")

    def submit_analysis(self, analysis):
        parsed = Analysis.model_validate(analysis)
        ids = {c.id for c in parsed.changes}
        if len(ids) != len(parsed.changes):
            raise ValueError("Change IDs must be unique.")
        for change in parsed.changes:
            for evidence in [*change.evidence, *change.affected_locations]:
                self.validate_evidence(evidence)
        for action in parsed.manual_actions:
            if action.change_id not in ids:
                raise ValueError("Manual action must reference a detected change.")
            for evidence in action.affected_locations:
                self.validate_evidence(evidence)
        if any(
            c.disposition == "manual" and not any(a.change_id == c.id for a in parsed.manual_actions)
            for c in parsed.changes
        ):
            raise ValueError("Manual changes require actionable documentation.")
        self.report.changes, self.report.manual_actions = parsed.changes, parsed.manual_actions
        self.report.analysis_summary = parsed.summary
        self.artifact("analysis.json", parsed.model_dump_json(indent=2))
        self.submitted = True
        self.save()
        return {"accepted": True}

    def artifact(self, name, text):
        atomic_write(self.root / "artifacts" / name, text)
        if name not in self.report.artifacts:
            self.report.artifacts.append(name)
        self.save()

    def _patch_scope(self, rationale):
        if not getattr(self, "hook_counts_tools", False):
            self.count("patch_attempts")
        if not rationale.strip():
            raise ValueError("A repair rationale is required.")
        if self.report.budget.used_checks >= 4:
            raise BudgetExceeded("No check allowance remains for another revision.")
        # Restrict edits to the reviewed affected source locations.
        approved = {
            e.path.removeprefix("source/")
            for c in self.report.changes
            if c.disposition == "repair"
            for e in c.affected_locations
            if e.path.startswith("source/")
        }
        return {p for p in self.allowed & approved if editable(p)}

    def apply_patch(self, patch, rationale):
        revision = apply_unified(self.workspace, patch, self._patch_scope(rationale))
        self.artifact(f"patch-attempt-{self.report.budget.used_patch_attempts}.diff", patch)
        return {"revision_hash": revision}

    def apply_edits(self, edits, rationale):
        revision = apply_edits(self.workspace, edits, self._patch_scope(rationale))
        self.artifact(
            f"patch-attempt-{self.report.budget.used_patch_attempts}.edits.json",
            json.dumps(edits, indent=2),
        )
        return {"revision_hash": revision}

    def run_checks(self, final=False):
        if not final and self.report.budget.used_checks >= 3:
            raise BudgetExceeded("The last check slot is reserved for final verification.")
        self.count("checks")
        revision = tree_hash(self.workspace)
        cap = self.report.budget.limits.get("check_seconds", 120)
        result = self.runner.check(self.workspace, min(cap, self.remaining()))
        name = f"check-{self.report.budget.used_checks}.log"
        log = result.pop("log")
        self.artifact(name, log)
        check = Check(
            id=f"check-{self.report.budget.used_checks}",
            revision_hash=revision,
            log_artifact_id=name,
            **result,
        )
        self.report.development_checks.append(check)
        self.save()
        self.log(
            "check",
            f"Development checks {check.status} in {check.duration:.1f}s"
            f" (revision {revision[:12]}, full log in {name}).",
            {"passed": "ok", "failed": "error"}.get(check.status, "warn"),
        )
        return {**check.model_dump(), "log_excerpt": log[:8000]}

    def finish_repair(self, summary, manual_actions=None):
        if manual_actions:
            from .schema import ManualAction

            for raw in manual_actions:
                action = ManualAction.model_validate(raw)
                if action.change_id not in {c.id for c in self.report.changes}:
                    raise ValueError("Remaining work must reference a known change.")
                for evidence in action.affected_locations:
                    self.validate_evidence(evidence)
                self.report.manual_actions.append(action)
        for change in self.report.changes:
            if change.disposition == "repair":
                change.repair_summary = summary[:10000]
        self.artifact("repair-summary.txt", summary[:10000])
        self.submitted = True
        return {"accepted": True, "note": "The service derives final verification and outcome."}
