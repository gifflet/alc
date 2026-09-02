# test_notify.py — never-raise push notify hooks.
#
# Coverage:
#   (1) alc.notify.fire — command (argv) and webhook (URL) delivery, both success
#       and failure paths; None/empty target is a pure no-op; never raises.
#   (2) queue.py fires `on_task_failed` at the point a task's failure is already
#       detected; a successful task fires nothing.
#   (3) loop.py fires `on_loop_stopped` (any stop reason) and additionally
#       `on_budget_exceeded` (reason == "budget"), from BOTH the pre-check and
#       post-check stop paths.
#   (4) merge.py's `auto_merge_branches` fires `on_merge_conflict` exactly once,
#       naming every branch left behind — including when git itself is missing
#       (never raises).
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from alc.intake import load_loop, load_manifest
from alc.loop import loops_dir, run_cycle
from alc.merge import auto_merge_branches
from alc.models import LoopState, Manifest, NotifyConfig
from alc.notify import fire
from alc.queue import process_queue
from alc.worktree import allocate_free_ports, release_ports

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _recording_command(tmp_path: Path, name: str) -> tuple[list[str], Path]:
    """Return (argv, record_path): argv writes its stdin verbatim to record_path."""
    record = tmp_path / f"{name}.recorded.json"
    script = tmp_path / f"{name}.record.py"
    script.write_text(
        "import sys, pathlib\n"
        f"pathlib.Path({str(record)!r}).write_text(sys.stdin.read())\n"
    )
    return [sys.executable, str(script)], record


def _failing_command(exit_code: int = 3) -> list[str]:
    """An argv that exits non-zero without recording anything."""
    return [sys.executable, "-c", f"import sys; sys.exit({exit_code})"]


class _RecordingServer:
    """A local loopback HTTP server recording every POST body it receives."""

    def __init__(self) -> None:
        self.received: list[bytes] = []
        received = self.received

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 (stdlib method name)
                length = int(self.headers.get("Content-Length", 0))
                received.append(self.rfile.read(length))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                pass  # keep test output quiet

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/hook"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def recording_server() -> "_RecordingServer":
    server = _RecordingServer()
    try:
        yield server
    finally:
        server.close()


# ---------------------------------------------------------------------------
# (1) alc.notify.fire — unit tests
# ---------------------------------------------------------------------------


class TestFireIsANoOpWhenTargetIsAbsent:
    def test_none_target_never_spawns_a_process(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "alc.notify.subprocess.run",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
        )
        fire(None, "task_failed", task="x")  # no exception -> no subprocess call

    def test_empty_list_and_empty_string_are_also_no_ops(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "alc.notify.subprocess.run",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
        )
        fire([], "task_failed", task="x")
        fire("", "task_failed", task="x")


class TestFireCommand:
    def test_success_delivers_the_json_payload_on_stdin(self, tmp_path: Path) -> None:
        argv, record = _recording_command(tmp_path, "cmd_ok")

        fire(argv, "task_failed", task="t1.yaml", flow="ship", reason="check x failed")

        payload = json.loads(record.read_text())
        assert payload == {
            "event": "task_failed",
            "task": "t1.yaml",
            "flow": "ship",
            "reason": "check x failed",
        }

    def test_nonzero_exit_is_swallowed_and_warned(self, capsys: pytest.CaptureFixture) -> None:
        fire(_failing_command(3), "task_failed", task="t1")  # must not raise

        assert "[notify]" in capsys.readouterr().err

    def test_missing_binary_is_swallowed_and_warned(self, capsys: pytest.CaptureFixture) -> None:
        fire(["/no/such/binary-xyz"], "task_failed", task="t1")  # must not raise

        assert "[notify]" in capsys.readouterr().err


class TestFireWebhook:
    def test_success_posts_the_json_body(self, recording_server: "_RecordingServer") -> None:
        fire(recording_server.url, "loop_stopped", loop="deliver", reason="budget")

        assert len(recording_server.received) == 1
        payload = json.loads(recording_server.received[0])
        assert payload == {"event": "loop_stopped", "loop": "deliver", "reason": "budget"}

    def test_unreachable_url_is_swallowed_and_warned(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        port = allocate_free_ports(1)[0]
        release_ports([port])  # freed immediately -> nothing listens there
        url = f"http://127.0.0.1:{port}/hook"

        fire(url, "task_failed", task="t1")  # must not raise

        assert "[notify]" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# (2) queue.py — on_task_failed
# ---------------------------------------------------------------------------

_FAILING_BLUEPRINT = (
    "---\nname: failing\npurpose: Always fails its check.\ncompute_tier: standard\n"
    'checks:\n  - name: nope\n    command: ["false"]\n---\n# Workflow\n1. Nothing.\n'
)
_BAD_FLOW = "name: bad\ndescription: fails.\nstages:\n  - name: b\n    blueprint: failing\n"
_FAILING_TASK = 'flow: bad\ntask: "fail me"\nengine: mock\nisolate: false\n'
_PASSING_TASK = 'flow: ship\ntask: "tidy"\nengine: mock\nisolate: false\n'


def _with_notify(manifest: Manifest, **hooks: object) -> Manifest:
    return manifest.model_copy(update={"notify": NotifyConfig(**hooks)})


class TestQueueNotifiesOnTaskFailed:
    def test_failed_task_fires_on_task_failed_with_a_useful_payload(
        self, operator_layer: Path, tmp_path: Path
    ) -> None:
        (operator_layer / "blueprints" / "failing.md").write_text(_FAILING_BLUEPRINT)
        (operator_layer / "flows" / "bad.yaml").write_text(_BAD_FLOW)
        argv, record = _recording_command(tmp_path, "task_failed")
        manifest = _with_notify(load_manifest(operator_layer), on_task_failed=argv)

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "f1.yaml").write_text(_FAILING_TASK)

        results = process_queue(manifest, operator_layer)

        assert results[0].success is False
        payload = json.loads(record.read_text())
        assert payload["event"] == "task_failed"
        assert payload["task"] == "f1.yaml"
        assert payload["flow"] == "bad"
        assert "nope" in payload["reason"]  # names the failing check

    def test_successful_task_fires_nothing(
        self, operator_layer: Path, tmp_path: Path
    ) -> None:
        argv, record = _recording_command(tmp_path, "should_not_fire")
        manifest = _with_notify(load_manifest(operator_layer), on_task_failed=argv)

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "ok.yaml").write_text(_PASSING_TASK)

        results = process_queue(manifest, operator_layer)

        assert results[0].success is True
        assert not record.exists()

    def test_absent_notify_config_is_byte_identical(
        self, operator_layer: Path
    ) -> None:
        (operator_layer / "blueprints" / "failing.md").write_text(_FAILING_BLUEPRINT)
        (operator_layer / "flows" / "bad.yaml").write_text(_BAD_FLOW)
        manifest = load_manifest(operator_layer)  # notify is None (default)
        assert manifest.notify is None

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "f1.yaml").write_text(_FAILING_TASK)

        results = process_queue(manifest, operator_layer)  # must not raise

        assert results[0].success is False


# ---------------------------------------------------------------------------
# (3) loop.py — on_loop_stopped / on_budget_exceeded
# ---------------------------------------------------------------------------

_MARKER_TASK = 'flow: ship\ntask: "tidy"\nengine: mock\nisolate: false\n'


def _write_loop(operator_layer: Path, name: str, body: str) -> None:
    loops = operator_layer / "loops"
    loops.mkdir(exist_ok=True)
    (loops / f"{name}.yaml").write_text(body)


class TestLoopNotifiesOnStop:
    def test_pre_check_stop_fires_on_loop_stopped_only(
        self, operator_layer: Path, tmp_path: Path
    ) -> None:
        # max_cycles already reached -> pre-check short-circuits with "max_cycles",
        # never "budget" -> on_budget_exceeded must stay silent.
        stopped_argv, stopped_record = _recording_command(tmp_path, "stopped")
        budget_argv, budget_record = _recording_command(tmp_path, "budget")
        manifest = _with_notify(
            load_manifest(operator_layer),
            on_loop_stopped=stopped_argv,
            on_budget_exceeded=budget_argv,
        )
        _write_loop(operator_layer, "deliver", "name: deliver\nstop:\n  max_cycles: 2\n")
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        state = LoopState(name="deliver", cycle=2)

        new_state, _record = run_cycle(
            manifest, operator_layer, loop_def, state, engine_override="mock"
        )

        assert new_state.stopped_reason == "max_cycles"
        payload = json.loads(stopped_record.read_text())
        assert payload == {"event": "loop_stopped", "loop": "deliver", "reason": "max_cycles", "cycle": 2}
        assert not budget_record.exists()

    def test_pre_check_budget_stop_fires_both_hooks(
        self, operator_layer: Path, tmp_path: Path
    ) -> None:
        stopped_argv, stopped_record = _recording_command(tmp_path, "stopped")
        budget_argv, budget_record = _recording_command(tmp_path, "budget")
        manifest = _with_notify(
            load_manifest(operator_layer),
            on_loop_stopped=stopped_argv,
            on_budget_exceeded=budget_argv,
        )
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 20\n"
            "  budget:\n    unit: usd\n    max: 1\n",
        )
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        # State already over budget -> pre-check trips "budget" immediately.
        state = LoopState(name="deliver", cycle=1, budget_used={"usd": 5.0})

        new_state, _record = run_cycle(
            manifest, operator_layer, loop_def, state, engine_override="mock"
        )

        assert new_state.stopped_reason == "budget"
        assert json.loads(stopped_record.read_text())["reason"] == "budget"
        assert json.loads(budget_record.read_text()) == {
            "event": "budget_exceeded", "loop": "deliver", "cycle": 1,
        }

    def test_post_check_budget_stop_fires_both_hooks(
        self, operator_layer: Path, tmp_path: Path
    ) -> None:
        stopped_argv, stopped_record = _recording_command(tmp_path, "stopped")
        budget_argv, budget_record = _recording_command(tmp_path, "budget")
        manifest = _with_notify(
            load_manifest(operator_layer),
            on_loop_stopped=stopped_argv,
            on_budget_exceeded=budget_argv,
        )
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 20\n  on_no_new_work: false\n"
            "  budget:\n    unit: engine_calls\n    max: 1\n",
        )
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_MARKER_TASK)

        new_state, _record = run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )

        # ship flow needs >= 2 engine calls, cap is 1 -> tripped AFTER the drain ran.
        assert new_state.stopped_reason == "budget"
        assert stopped_record.exists()
        assert budget_record.exists()

    def test_progress_cycle_fires_nothing(
        self, operator_layer: Path, tmp_path: Path
    ) -> None:
        stopped_argv, stopped_record = _recording_command(tmp_path, "stopped")
        manifest = _with_notify(load_manifest(operator_layer), on_loop_stopped=stopped_argv)
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 20\n  on_no_new_work: false\n",
        )
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_MARKER_TASK)

        new_state, _record = run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )

        assert new_state.status == "running"
        assert not stopped_record.exists()


# ---------------------------------------------------------------------------
# (4) merge.py — auto_merge_branches(..., notify=...)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _make_git_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@alc.local")
    _git(repo, "config", "user.name", "ALC Test")
    (repo / "seed.txt").write_text("line-a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _make_branch(repo: Path, branch: str, filename: str, content: str, subject: str) -> None:
    _git(repo, "checkout", "-b", branch, "main")
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", subject)
    _git(repo, "checkout", "main")


class TestMergeNotifiesOnConflict:
    def test_a_real_conflict_fires_on_merge_conflict_with_the_branch_name(
        self, tmp_path: Path
    ) -> None:
        repo = _make_git_repo(tmp_path)
        # Both branches edit the SAME line off the SAME original base.
        _make_branch(repo, "alc/tick-bbb", "seed.txt", "line-a-from-B\n", "feat(auto): B")
        _make_branch(repo, "alc/tick-ccc", "seed.txt", "line-a-from-C\n", "feat(auto): C")
        # Land B first (no notify) so C's cherry-pick, still based on the ORIGINAL
        # line, conflicts against B's already-integrated edit.
        auto_merge_branches(repo, ["alc/tick-bbb"])
        argv, record = _recording_command(tmp_path, "conflict")

        report = auto_merge_branches(repo, ["alc/tick-ccc"], notify=argv)

        assert report.conflicted == ["alc/tick-ccc"]
        payload = json.loads(record.read_text())
        assert payload == {"event": "merge_conflict", "branches": ["alc/tick-ccc"]}

    def test_a_clean_pass_fires_nothing(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): A")
        argv, record = _recording_command(tmp_path, "should_not_fire")

        report = auto_merge_branches(repo, ["alc/tick-aaa"], notify=argv)

        assert report.conflicted == []
        assert not record.exists()

    def test_git_missing_still_fires_and_never_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        recording_server: "_RecordingServer",
    ) -> None:
        # Use a webhook (urllib) target here, not a command: patching subprocess.run
        # to simulate a missing git ALSO patches the shared subprocess module a
        # command-based delivery would use.
        repo = _make_git_repo(tmp_path)

        def _raise(*args: object, **kwargs: object) -> None:
            raise FileNotFoundError("git not found")

        monkeypatch.setattr("alc.merge.subprocess.run", _raise)

        report = auto_merge_branches(
            repo, ["alc/tick-a", "alc/tick-b"], notify=recording_server.url
        )

        assert report.conflicted == ["alc/tick-a", "alc/tick-b"]
        payload = json.loads(recording_server.received[0])
        assert payload == {
            "event": "merge_conflict", "branches": ["alc/tick-a", "alc/tick-b"],
        }

    def test_no_notify_target_is_byte_identical(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-bbb", "seed.txt", "line-a-from-B\n", "feat(auto): B")
        _make_branch(repo, "alc/tick-ccc", "seed.txt", "line-a-from-C\n", "feat(auto): C")
        auto_merge_branches(repo, ["alc/tick-bbb"])

        report = auto_merge_branches(repo, ["alc/tick-ccc"])  # notify defaults to None

        assert report.conflicted == ["alc/tick-ccc"]


# ---------------------------------------------------------------------------
# NotifyConfig — model round-trip
# ---------------------------------------------------------------------------


class TestNotifyConfigModel:
    def test_absent_notify_defaults_to_none(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        assert manifest.notify is None

    def test_command_and_webhook_forms_round_trip(self) -> None:
        manifest = Manifest(
            version=1,
            default_engine="mock",
            compute_tiers={"standard": {"mock": "mock-small"}},
            engines={"mock": {"type": "mock"}},
            notify={
                "on_task_failed": ["/usr/local/bin/notify.sh"],
                "on_merge_conflict": "https://example.invalid/hook",
            },
        )
        assert manifest.notify.on_task_failed == ["/usr/local/bin/notify.sh"]
        assert manifest.notify.on_merge_conflict == "https://example.invalid/hook"
        assert manifest.notify.on_loop_stopped is None
        assert manifest.notify.on_budget_exceeded is None
