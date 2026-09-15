"""Test-only browser fixture. Never used by the production CLI or server.

Run: PYTHONPATH=backend/tests backend/.venv/bin/uvicorn ui_server:app --host 127.0.0.1 --port 8000
All repairs/checks here are SCRIPTED ORCHESTRATION EVIDENCE ONLY.
"""

import tempfile
from pathlib import Path
from threading import Thread

from test_core import Checks, analysis, scripted

from api_maintainer.api import create_app
from api_maintainer.migration import Service
from api_maintainer.worker import execute


class UIService(Service):
    def health(self):
        return dict(ready=True, docker=True, image=True, model_configured=True, key_configured=True)

    def spawn(self, run_id, stage):
        def job():
            report = self.store.get(run_id)
            report.warnings.append(
                "SCRIPTED UI TEST: model and check results are simulated, not live repair evidence."
            )
            self.store.save(report)

            def agent(stage, tools):
                if stage == "analyzing" and report.scenario_id in ("optional-field", "required-input"):
                    manual = report.scenario_id == "required-input"
                    payload = analysis("manual" if manual else "no_change", manual)
                    payload["changes"][0]["description"] = (
                        "Required country has no application input source"
                        if manual
                        else "Optional subtitle leaves current consumer behavior unchanged"
                    )
                    tools.invoke("submit_analysis", analysis=payload)
                elif stage == "analyzing" and report.scenario_id == "mixed":
                    tools.invoke("submit_analysis", analysis=analysis("repair", True))
                else:
                    scripted(stage, tools)

            class MixedChecks(Checks):
                def check(self, workspace, seconds):
                    result = super().check(workspace, seconds)
                    result["components"] = {"endpoint_reaches_country_validation": True}
                    return result

            runner = (
                MixedChecks("failed")
                if report.scenario_id == "mixed"
                else Checks("failed" if report.scenario_id == "required-input" else "passed")
            )
            try:
                execute(self.store, run_id, stage, agent, runner)
            finally:
                self.store.release(run_id)

        Thread(target=job, daemon=True).start()


app = create_app(UIService(Path(tempfile.mkdtemp(prefix="api-maintainer-ui-"))))
