# test_capture_evidence.py — e2e evidence capture.
#
# Two layers: `alc.evidence.capture_evidence` unit-tested directly (never-raise
# contract, artifact discovery, env wiring), then `execute_mandate`'s wiring
# through a REAL `needs_service` run — a tiny inline http.server, exactly like
# test_runtime.py — proving a `capture:`-less run stays byte-identical and a
# `capture:`-bearing one populates RunReport.artifacts and persists the
# health-poll log.
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from alc.evidence import capture_evidence
from alc.intake import load_manifest
from alc.models import Blueprint, Check, ServiceSpec
from alc.runner import execute_mandate

# ---------------------------------------------------------------------------
# alc.evidence.capture_evidence — unit tests
# ---------------------------------------------------------------------------


class TestCaptureEvidence:
    def test_persists_health_log_and_collects_command_output(self, tmp_path: Path) -> None:
        artifacts_dir = tmp_path / ".alc" / "artifacts" / "run1"
        paths, warnings = capture_evidence(
            command='printf hi > "$ALC_ARTIFACTS_DIR/note.txt"',
            health_log="--- health poll ---\nok\n",
            workdir=tmp_path,
            artifacts_dir=artifacts_dir,
            project_root=tmp_path,
            env={},
            timeout_s=10,
        )
        assert warnings == []
        assert paths == [".alc/artifacts/run1/health-poll.log", ".alc/artifacts/run1/note.txt"]
        assert (artifacts_dir / "health-poll.log").read_text() == "--- health poll ---\nok\n"
        assert (artifacts_dir / "note.txt").read_text() == "hi"

    def test_command_sees_the_injected_env(self, tmp_path: Path) -> None:
        artifacts_dir = tmp_path / "artifacts"
        paths, warnings = capture_evidence(
            command='printf "%s" "$ALC_BASE_URL" > "$ALC_ARTIFACTS_DIR/base.txt"',
            health_log="",
            workdir=tmp_path,
            artifacts_dir=artifacts_dir,
            project_root=tmp_path,
            env={"ALC_BASE_URL": "http://127.0.0.1:9999"},
            timeout_s=10,
        )
        assert warnings == []
        assert (artifacts_dir / "base.txt").read_text() == "http://127.0.0.1:9999"
        assert "artifacts/base.txt" in paths[0] or any("base.txt" in p for p in paths)

    def test_failing_command_warns_but_keeps_the_health_log(self, tmp_path: Path) -> None:
        artifacts_dir = tmp_path / "artifacts"
        paths, warnings = capture_evidence(
            command="echo boom >&2; exit 3",
            health_log="captured\n",
            workdir=tmp_path,
            artifacts_dir=artifacts_dir,
            project_root=tmp_path,
            env={},
            timeout_s=10,
        )
        assert len(warnings) == 1
        assert "exited 3" in warnings[0]
        assert "boom" in warnings[0]
        assert paths == ["artifacts/health-poll.log"]

    def test_timeout_warns_and_never_raises(self, tmp_path: Path) -> None:
        artifacts_dir = tmp_path / "artifacts"
        paths, warnings = capture_evidence(
            command="sleep 5",
            health_log="",
            workdir=tmp_path,
            artifacts_dir=artifacts_dir,
            project_root=tmp_path,
            env={},
            timeout_s=0.2,
        )
        assert len(warnings) == 1
        assert "timed out" in warnings[0]
        # The health log was still persisted before the command ran.
        assert paths == ["artifacts/health-poll.log"]

    def test_command_launch_failure_warns_and_never_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*args: object, **kwargs: object):
            raise OSError("no shell")

        monkeypatch.setattr("alc.evidence.subprocess.run", _raise)
        artifacts_dir = tmp_path / "artifacts"
        paths, warnings = capture_evidence(
            command="echo hi",
            health_log="captured\n",
            workdir=tmp_path,
            artifacts_dir=artifacts_dir,
            project_root=tmp_path,
            env={},
            timeout_s=10,
        )
        assert len(warnings) == 1
        assert "failed to start" in warnings[0]
        # The health log write happens before the (failing) subprocess call.
        assert paths == ["artifacts/health-poll.log"]

    def test_unwritable_artifacts_dir_warns_and_returns_no_paths(self, tmp_path: Path) -> None:
        # A regular FILE occupies the path a directory needs -> mkdir fails.
        blocker = tmp_path / "blocked"
        blocker.write_text("occupied")
        paths, warnings = capture_evidence(
            command="echo hi",
            health_log="captured\n",
            workdir=tmp_path,
            artifacts_dir=blocker / "run1",
            project_root=tmp_path,
            env={},
            timeout_s=10,
        )
        assert paths == []
        assert len(warnings) == 1
        assert "could not create" in warnings[0]

    def test_no_artifacts_produced_still_returns_the_health_log_only(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        paths, warnings = capture_evidence(
            command="true",  # succeeds, writes nothing
            health_log="captured\n",
            workdir=tmp_path,
            artifacts_dir=artifacts_dir,
            project_root=tmp_path,
            env={},
            timeout_s=10,
        )
        assert warnings == []
        assert paths == ["artifacts/health-poll.log"]


# ---------------------------------------------------------------------------
# execute_mandate wiring over a REAL needs_service run — never-raise, additive
# ---------------------------------------------------------------------------

# A tiny HTTP server that binds $PORT and answers 200 on /health (verbatim
# from test_runtime.py's _HEALTHY_SERVER — kept local, tests stay self-contained).
_HEALTHY_SERVER = """\
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass

HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"""


def _write_server(tmp_path: Path) -> Path:
    script = tmp_path / "server.py"
    script.write_text(textwrap.dedent(_HEALTHY_SERVER))
    return script


def _qa_blueprint(capture: str | None) -> Blueprint:
    return Blueprint(
        name="qa",
        purpose="verify at runtime",
        checks=[Check(name="smoke", command=["true"])],
        workflow="# do it",
        needs_service=True,
        capture=capture,
    )


class TestNeedsServiceCaptureWiring:
    def test_without_capture_stays_byte_identical(
        self, tmp_path: Path, operator_layer: Path
    ) -> None:
        script = _write_server(tmp_path)
        manifest = load_manifest(operator_layer).model_copy(
            update={"service": ServiceSpec(start=f"python {script}", ready_timeout_s=5)}
        )
        report = execute_mandate(
            manifest=manifest,
            blueprint=_qa_blueprint(capture=None),
            directive="# original",
            workdir=tmp_path,
            operator_layer=operator_layer,
        )
        assert report.artifacts == []
        assert not (operator_layer.parent / manifest.artifacts_dir).exists()

    def test_with_capture_populates_artifacts_and_persists_health_log(
        self, tmp_path: Path, operator_layer: Path
    ) -> None:
        script = _write_server(tmp_path)
        manifest = load_manifest(operator_layer).model_copy(
            update={"service": ServiceSpec(start=f"python {script}", ready_timeout_s=5)}
        )
        capture = 'printf captured > "$ALC_ARTIFACTS_DIR/evidence.txt"'
        report = execute_mandate(
            manifest=manifest,
            blueprint=_qa_blueprint(capture=capture),
            directive="# original",
            workdir=tmp_path,
            operator_layer=operator_layer,
        )
        assert report.success
        names = {Path(p).name for p in report.artifacts}
        assert names == {"health-poll.log", "evidence.txt"}
        # Every recorded path is project-root-relative and actually on disk.
        for rel in report.artifacts:
            assert not Path(rel).is_absolute()
            assert (operator_layer.parent / rel).is_file()
        evidence = next(p for p in report.artifacts if p.endswith("evidence.txt"))
        assert (operator_layer.parent / evidence).read_text() == "captured"

    def test_failing_capture_warns_but_the_run_stays_green(
        self, tmp_path: Path, operator_layer: Path
    ) -> None:
        script = _write_server(tmp_path)
        manifest = load_manifest(operator_layer).model_copy(
            update={"service": ServiceSpec(start=f"python {script}", ready_timeout_s=5)}
        )
        report = execute_mandate(
            manifest=manifest,
            blueprint=_qa_blueprint(capture="exit 1"),
            directive="# original",
            workdir=tmp_path,
            operator_layer=operator_layer,
        )
        # A failed capture command never undoes a green run.
        assert report.success
        assert any("exited 1" in w for w in report.warnings)
        # The health-poll log was still persisted despite the capture failing.
        assert any(p.endswith("health-poll.log") for p in report.artifacts)

    def test_capture_without_needs_service_is_inert(
        self, tmp_path: Path, operator_layer: Path
    ) -> None:
        # `capture:` on a Blueprint that never opts into needs_service is a
        # no-op — the field alone has zero runtime effect.
        manifest = load_manifest(operator_layer)
        bp = Blueprint(
            name="plain",
            purpose="no service",
            checks=[Check(name="smoke", command=["true"])],
            workflow="# do it",
            needs_service=False,
            capture='echo hi > "$ALC_ARTIFACTS_DIR/x.txt"',
        )
        report = execute_mandate(
            manifest=manifest,
            blueprint=bp,
            directive="# original",
            workdir=tmp_path,
            operator_layer=operator_layer,
        )
        assert report.artifacts == []
        assert not (operator_layer.parent / manifest.artifacts_dir).exists()
