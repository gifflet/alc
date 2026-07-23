# runtime.py — RuntimeService: the CORE-owned app lifecycle for runtime validation.
#
# When ALC owns the service (a Blueprint opts in and the Manifest declares one),
# this context manager starts the app on ALC's allocated port, polls its health
# endpoint until it answers 200, hands back the base URL, and tears the process
# (and its children) down on exit. The agent never picks a port or starts the app
# — it just hits $ALC_BASE_URL. Single responsibility: process lifecycle + health
# probe. Standard library only (subprocess + urllib), no new dependencies.
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from alc.models import ServiceSpec

# How often to poll the health endpoint while waiting for the app to come up.
_POLL_INTERVAL_S = 0.2
# Chars of captured server output appended to a timeout error for diagnosis.
_OUTPUT_TAIL_CHARS = 2000


class RuntimeService:
    """Start an app, wait for health, and tear it down — CORE-owned lifecycle.

    Usage:
        with RuntimeService(spec, workdir, port, env) as base_url:
            ...  # base_url == "http://127.0.0.1:<port>", app is up

    ``__enter__`` launches ``spec.start`` in its own process group with ``PORT``
    and ``ALC_PORT`` set to ``port``, then polls ``http://127.0.0.1:<port><health>``
    until it returns HTTP 200 or ``spec.ready_timeout_s`` elapses. On timeout it
    terminates the process and raises RuntimeError with the tail of the captured
    output. ``__exit__`` is best-effort and never raises.
    """

    def __init__(
        self, spec: ServiceSpec, workdir: Path, port: int, env: dict[str, str]
    ) -> None:
        self._spec = spec
        self._workdir = workdir
        self._port = port
        self._env = env
        self._proc: subprocess.Popen | None = None
        self._log = None  # captured stdout/stderr temp file (binary)

    def __enter__(self) -> str:
        base_url = f"http://127.0.0.1:{self._port}"
        # Capture the app's stdout+stderr to a temp file so a startup failure is
        # diagnosable (its tail is embedded in the timeout error).
        self._log = tempfile.TemporaryFile(mode="w+b")
        proc_env = {
            **os.environ,
            **self._env,
            "PORT": str(self._port),
            "ALC_PORT": str(self._port),
        }
        # start_new_session=True gives the app its own process group so teardown
        # can signal the whole tree (the launcher AND any children it spawned).
        self._proc = subprocess.Popen(
            self._spec.start,
            shell=True,
            cwd=str(self._workdir),
            env=proc_env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        health_url = base_url + self._spec.health
        deadline = time.monotonic() + self._spec.ready_timeout_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                # The app exited before becoming healthy — fail fast, no waiting.
                # Capture the tail BEFORE teardown (teardown closes the log file).
                returncode = self._proc.returncode
                tail = self._output_tail()
                self._teardown()
                raise RuntimeError(
                    f"Service exited (code {returncode}) before it became "
                    f"healthy at {health_url}.\n{tail}"
                )
            if self._probe(health_url):
                return base_url
            time.sleep(_POLL_INTERVAL_S)

        # Timed out waiting for health — terminate and surface the output tail.
        # Capture the tail BEFORE teardown (teardown closes the log file).
        tail = self._output_tail()
        self._teardown()
        raise RuntimeError(
            f"Service did not become healthy at {health_url} within "
            f"{self._spec.ready_timeout_s}s.\n{tail}"
        )

    def __exit__(self, *exc) -> None:
        self._teardown()

    @staticmethod
    def _probe(health_url: str) -> bool:
        """Return True when a GET on *health_url* returns HTTP 200, else False."""
        try:
            with urllib.request.urlopen(health_url, timeout=1) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def captured_output(self) -> str:
        """Return the full captured stdout+stderr so far, without truncation.

        Safe to call any time after ``__enter__`` starts the process (including
        after a failed ``__enter__``), as long as it is called BEFORE teardown
        closes the log file. Best-effort: an unreadable log yields "" rather
        than raising — this backs e2e evidence capture (roadmap-phase-5.md T6),
        which must never fail a run.
        """
        if self._log is None:
            return ""
        try:
            self._log.seek(0)
            data = self._log.read()
        except (OSError, ValueError):
            return ""
        return data.decode("utf-8", errors="replace")

    def _output_tail(self) -> str:
        """Return the tail of the captured server output for a diagnostic message."""
        if self._log is None:
            return "(no server output captured)"
        try:
            self._log.seek(0)
            data = self._log.read()
        except (OSError, ValueError):
            return "(server output unavailable)"
        text = data.decode("utf-8", errors="replace")
        tail = text[-_OUTPUT_TAIL_CHARS:]
        return "--- server output (tail) ---\n" + tail

    def _teardown(self) -> None:
        """Best-effort: signal the process group, then close the capture file."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
                    proc.wait(timeout=5)
            except (ProcessLookupError, PermissionError, OSError, subprocess.TimeoutExpired):
                pass  # never raise from teardown
        if self._log is not None:
            try:
                self._log.close()
            except OSError:
                pass
            self._log = None
