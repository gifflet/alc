# test_exec.py — Exec dispatch end-to-end (mock engine), validation and cancel.
from __future__ import annotations

import sys
import time
from pathlib import Path

from alc.ui.bus import EventBus
from alc.ui.execs import RunManager


def _wait_status(client, exec_id: str, *, timeout: float = 30.0) -> dict:
    """Poll GET /api/execs/{id} until the exec leaves the running state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get(f"/api/execs/{exec_id}").json()
        if view["status"] != "running":
            return view
        time.sleep(0.1)
    raise AssertionError(f"exec {exec_id} did not finish within {timeout}s")


def _write_loop(project: Path, name: str) -> None:
    """Write a minimal drain-only loop definition so `alc loop` can run once."""
    loops = project / ".alc" / "loops"
    loops.mkdir(parents=True, exist_ok=True)
    (loops / f"{name}.yaml").write_text(
        "name: {name}\nstop:\n  max_cycles: 1\n  on_no_new_work: true\n"
        "drain:\n  concurrency: 1\n".format(name=name)
    )


class TestExecEndToEnd:
    def test_run_chore_finishes_and_writes_a_run_log(
        self, client, registered: str, project: Path
    ) -> None:
        resp = client.post(
            f"/api/projects/{registered}/exec",
            json={"command": "run", "args": {"blueprint": "chore", "task": "tidy"}},
        )
        assert resp.status_code == 201
        exec_id = resp.json()["exec_id"]

        view = _wait_status(client, exec_id)
        assert view["status"] == "finished"
        assert view["exit_code"] == 0
        assert any("SUCCESS" in line for line in view["output"])

        # The run emitted a structured event log under .alc/runs/.
        runs = list((project / ".alc" / "runs").glob("*.jsonl"))
        assert runs, "expected a run log to be written"

        # And the exec shows up in the global exec list.
        listed = client.get("/api/execs").json()
        assert exec_id in {e["id"] for e in listed}

    def test_loop_finishes(self, client, registered: str, project: Path) -> None:
        _write_loop(project, "deliver")
        resp = client.post(
            f"/api/projects/{registered}/exec",
            json={
                "command": "loop",
                "args": {"name": "deliver", "interval": 0, "reset": True},
            },
        )
        assert resp.status_code == 201
        exec_id = resp.json()["exec_id"]

        view = _wait_status(client, exec_id)
        assert view["status"] in {"finished", "cancelled"}


class TestExecValidation:
    def test_unknown_command_is_422(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/exec", json={"command": "rm", "args": {}}
        )
        assert resp.status_code == 422

    def test_unknown_arg_is_422(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/exec",
            json={"command": "run", "args": {"blueprint": "chore", "task": "x", "evil": "1"}},
        )
        assert resp.status_code == 422

    def test_missing_positional_is_422(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/exec",
            json={"command": "run", "args": {"blueprint": "chore"}},
        )
        assert resp.status_code == 422

    def test_loop_unknown_arg_is_422(self, client, registered: str) -> None:
        # `concurrency` belongs to cycle, not loop — it must be rejected.
        resp = client.post(
            f"/api/projects/{registered}/exec",
            json={"command": "loop", "args": {"name": "deliver", "concurrency": 2}},
        )
        assert resp.status_code == 422

    def test_cancel_unknown_exec_is_404(self, client) -> None:
        assert client.post("/api/execs/ghost/cancel").status_code == 404


class TestCancel:
    def test_cancel_terminates_running_exec(self, tmp_path: Path) -> None:
        manager = RunManager(EventBus())
        argv = [sys.executable, "-c", "import time; time.sleep(30)"]
        ex = manager.start("p1", str(tmp_path), "run", argv)
        assert ex.status == "running"

        assert manager.cancel(ex.id) is True

        deadline = time.time() + 10
        while time.time() < deadline and ex.status == "running":
            time.sleep(0.05)
        assert ex.status == "cancelled"

    def test_cancel_finished_exec_returns_false(self, tmp_path: Path) -> None:
        manager = RunManager(EventBus())
        ex = manager.start("p1", str(tmp_path), "run", [sys.executable, "-c", "pass"])
        deadline = time.time() + 10
        while time.time() < deadline and ex.status == "running":
            time.sleep(0.05)
        assert ex.status == "finished"
        assert manager.cancel(ex.id) is False
