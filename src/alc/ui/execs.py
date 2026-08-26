# execs.py — RunManager: run `alc` as a subprocess and stream its output.
#
# An exec spawns ``[python, -m, alc, ...]`` with cwd set to the project root
# (argv is built and whitelisted by command.build_argv — never a shell string).
# stdout/stderr are pumped on threads and published to the EventBus as
# ``exec_output`` lines; on exit an ``exec_finished`` message carries the exit
# code. State lives in memory only (no DB): the UI polls or tails via the bus.
from __future__ import annotations

import os
import subprocess
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field

from alc.ui.bus import EventBus


@dataclass
class Exec:
    """In-memory record of one subprocess run."""

    id: str
    project_id: str | None
    command: str
    argv: list[str]
    status: str = "running"  # running | finished | cancelled | error
    exit_code: int | None = None
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _output: deque[str] = field(default_factory=deque, repr=False)
    _cancelled: bool = field(default=False, repr=False)

    def view(self) -> dict:
        """Return a JSON-safe snapshot (including the buffered output tail)."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "command": self.command,
            "status": self.status,
            "exit_code": self.exit_code,
            "output": list(self._output),
        }


class RunManager:
    """Spawns and tracks `alc` subprocess execs, publishing their I/O to the bus."""

    def __init__(self, bus: EventBus, tail_lines: int = 1000) -> None:
        self._bus = bus
        self._tail_lines = tail_lines
        self._execs: dict[str, Exec] = {}
        self._lock = threading.Lock()

    def start(
        self, project_id: str | None, cwd: str, command: str, argv: list[str]
    ) -> Exec:
        """Spawn the subprocess and return its Exec record (status=running)."""
        exec_id = uuid.uuid4().hex[:12]
        ex = Exec(
            id=exec_id,
            project_id=project_id,
            command=command,
            argv=argv,
            _output=deque(maxlen=self._tail_lines),
        )

        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=os.environ.copy(),
            )
        except OSError as exc:
            ex.status = "error"
            ex.exit_code = -1
            ex._output.append(f"[exec] failed to start: {exc}")
            with self._lock:
                self._execs[exec_id] = ex
            self._bus.publish(
                {
                    "type": "exec_finished",
                    "project_id": project_id,
                    "exec_id": exec_id,
                    "exit_code": -1,
                }
            )
            return ex

        ex._proc = proc
        with self._lock:
            self._execs[exec_id] = ex

        pumps = [
            threading.Thread(target=self._pump, args=(ex, proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=self._pump, args=(ex, proc.stderr, "stderr"), daemon=True),
        ]
        for thread in pumps:
            thread.start()
        threading.Thread(target=self._wait, args=(ex, proc, pumps), daemon=True).start()
        return ex

    def _pump(self, ex: Exec, stream, name: str) -> None:
        """Forward each output line to the buffer and the bus, then close the stream."""
        for line in iter(stream.readline, ""):
            line = line.rstrip("\n")
            ex._output.append(line)
            self._bus.publish(
                {
                    "type": "exec_output",
                    "project_id": ex.project_id,
                    "exec_id": ex.id,
                    "stream": name,
                    "line": line,
                }
            )
        stream.close()

    def _wait(self, ex: Exec, proc: subprocess.Popen, pumps: list[threading.Thread]) -> None:
        """Wait for exit, drain the pumps, then publish exec_finished."""
        code = proc.wait()
        for thread in pumps:
            thread.join(timeout=5)
        with self._lock:
            if ex.status == "running":
                ex.status = "cancelled" if ex._cancelled else "finished"
            ex.exit_code = code
        self._bus.publish(
            {
                "type": "exec_finished",
                "project_id": ex.project_id,
                "exec_id": ex.id,
                "exit_code": code,
            }
        )

    def get(self, exec_id: str) -> Exec | None:
        """Return the Exec with this id, or None."""
        return self._execs.get(exec_id)

    def list(self) -> list[Exec]:
        """Return every tracked exec."""
        with self._lock:
            return list(self._execs.values())

    def cancel(self, exec_id: str, grace_s: float = 5.0) -> bool:
        """Terminate a running exec (SIGKILL after ``grace_s``); False if not running."""
        ex = self._execs.get(exec_id)
        if ex is None or ex._proc is None or ex._proc.poll() is not None:
            return False
        ex._cancelled = True
        proc = ex._proc
        proc.terminate()

        def _killer() -> None:
            try:
                proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                proc.kill()

        threading.Thread(target=_killer, daemon=True).start()
        return True
