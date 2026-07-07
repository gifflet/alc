# claude_code.py — ClaudeCodeEngine: translates the Engine contract to `claude --print`.
# This adapter is a thin translation layer (SRP). It performs one headless turn.
# Retries, verification, and the Assurance Loop are the control plane's responsibility.
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from alc.engine import Capabilities, EngineRequest, EngineResult, Usage


class ClaudeCodeEngine:
    """Execution-plane adapter for the Claude Code CLI (`claude`)."""

    name: str = "claude-code"

    def __init__(self, clean_config: bool = False) -> None:
        """Construct the adapter.

        Args:
            clean_config: When True, restrict the CLI to the ``user`` and
                ``local`` setting sources, so the host project's ``.claude/``
                settings and hooks are NOT inherited into the run. Opt-in; the
                default (False) leaves today's argv byte-identical.
        """
        self.clean_config = clean_config

    def capabilities(self) -> Capabilities:
        """Claude Code supports tool scoping, system-prompt append, structured output,
        subagents, and MCP natively."""
        return Capabilities(
            native_tool_scoping=True,
            native_system_append=True,
            native_structured_output=True,
            native_subagents=True,
            native_mcp=True,
        )

    def health_check(self) -> bool:
        """Return True if `claude --version` exits with code 0."""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def run(self, request: EngineRequest) -> EngineResult:
        """Stream `claude --print --output-format stream-json` and return the result.

        Reads the engine's stream-json output line by line and surfaces live
        progress (tool calls) to stderr, so the operator can see the turn is
        working instead of facing a frozen terminal. Does NOT retry — that is the
        Assurance Loop's job.
        """
        cmd = ["claude", "--print", "--output-format", "stream-json", "--verbose"]

        # Opt-in clean-config: load only the user and local setting sources,
        # excluding `project`. This stops the host project's .claude/ settings
        # and hooks from leaking into the run. Verified against `claude --help`
        # (`--setting-sources <sources>`: user, project, local).
        if self.clean_config:
            cmd += ["--setting-sources", "user,local"]

        # Headless edits need a non-interactive permission mode. The control plane
        # isolates each run (sandbox/worktree), so auto-accepting file edits is both
        # safe and required to satisfy the contract: "edit files headlessly".
        cmd += ["--permission-mode", "acceptEdits"]

        if request.model:
            cmd += ["--model", request.model]

        caps = self.capabilities()

        if caps.native_system_append and request.system_append:
            cmd += ["--append-system-prompt", request.system_append]

        if caps.native_tool_scoping:
            if request.allowed_tools:
                cmd += ["--allowedTools", ",".join(request.allowed_tools)]
            if request.denied_tools:
                cmd += ["--disallowedTools", ",".join(request.denied_tools)]

        merged_env = {**os.environ, **request.env}

        print(
            f"  → claude-code working (model={request.model or 'default'})…",
            file=sys.stderr,
            flush=True,
        )
        start = time.monotonic()

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=request.workdir,
                env=merged_env,
            )
        except FileNotFoundError:
            return EngineResult(ok=False, output_text="[claude-code] binary not found")
        except Exception as exc:  # noqa: BLE001
            return EngineResult(ok=False, output_text=f"[claude-code] error: {exc}")

        # Drain stderr in a background thread so a full stderr pipe can never
        # deadlock the stdout read loop.
        stderr_buf: list[str] = []
        stderr_thread = threading.Thread(
            target=lambda: stderr_buf.extend(proc.stderr), daemon=True
        )
        stderr_thread.start()

        # Enforce the timeout by killing the process; the stdout loop unblocks.
        timed_out = {"v": False}

        def _on_timeout() -> None:
            timed_out["v"] = True
            proc.kill()

        timer = threading.Timer(request.timeout_s, _on_timeout)
        timer.start()

        output_text = ""
        usage = Usage()
        raw: dict = {}
        try:
            try:
                proc.stdin.write(request.directive)
                proc.stdin.close()
            except BrokenPipeError:
                pass

            # iter(readline, "") yields each line as it arrives — `for line in
            # proc.stdout` would read-ahead and delay live progress.
            for line in iter(proc.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "assistant":
                    for note in self._progress_notes(event):
                        print(f"    • {note}", file=sys.stderr, flush=True)
                elif event.get("type") == "result":
                    output_text = event.get("result", "")
                    # Usage is best-effort: token counts live under "usage" and the
                    # rolled-up cost under "total_cost_usd" at the top level.
                    u = event.get("usage", {}) or {}
                    usage = Usage(
                        input_tokens=u.get("input_tokens"),
                        output_tokens=u.get("output_tokens"),
                        cost_usd=event.get("total_cost_usd"),
                    )
                    raw = event
            proc.wait()
        finally:
            timer.cancel()

        elapsed = int(time.monotonic() - start)

        if timed_out["v"]:
            return EngineResult(ok=False, output_text="[claude-code] timed out")

        if proc.returncode != 0:
            err = "".join(stderr_buf).strip()
            return EngineResult(ok=False, output_text=err or "[claude-code] non-zero exit")

        cost = f", ${usage.cost_usd:.3f}" if usage.cost_usd is not None else ""
        print(f"  → claude-code done ({elapsed}s{cost})", file=sys.stderr, flush=True)

        if not output_text:
            output_text = "[claude-code] completed"

        return EngineResult(ok=True, output_text=output_text, usage=usage, raw=raw)

    @staticmethod
    def _progress_notes(event: dict) -> list[str]:
        """Extract short progress notes (tool uses) from an assistant stream event."""
        notes: list[str] = []
        content = event.get("message", {}).get("content", [])
        if not isinstance(content, list):
            return notes
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "tool")
            inp = block.get("input", {}) or {}
            hint = (
                inp.get("file_path")
                or inp.get("path")
                or inp.get("command")
                or inp.get("pattern")
                or ""
            )
            if isinstance(hint, str) and hint.strip():
                notes.append(f"{name}: {hint.strip().splitlines()[0][:60]}")
            else:
                notes.append(name)
        return notes
