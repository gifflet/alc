# claude_code.py — ClaudeCodeEngine: translates the Engine contract to `claude --print`.
# This adapter is a thin translation layer (SRP). It performs one headless turn.
# Retries, verification, and the Assurance Loop are the control plane's responsibility.
from __future__ import annotations

import json
import subprocess

from alc.engine import Capabilities, EngineRequest, EngineResult, Usage


class ClaudeCodeEngine:
    """Execution-plane adapter for the Claude Code CLI (`claude`)."""

    name: str = "claude-code"

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
        """Shell out to `claude --print --output-format stream-json --verbose` and
        return the result. Does NOT retry — that is the Assurance Loop's job."""
        cmd = ["claude", "--print", "--output-format", "stream-json", "--verbose"]

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

        import os

        merged_env = {**os.environ, **request.env}

        try:
            proc = subprocess.run(
                cmd,
                input=request.directive,
                capture_output=True,
                text=True,
                cwd=request.workdir,
                timeout=request.timeout_s,
                env=merged_env,
            )
        except subprocess.TimeoutExpired:
            return EngineResult(ok=False, output_text="[claude-code] timed out")
        except FileNotFoundError:
            return EngineResult(ok=False, output_text="[claude-code] binary not found")
        except Exception as exc:  # noqa: BLE001
            return EngineResult(ok=False, output_text=f"[claude-code] error: {exc}")

        if proc.returncode != 0:
            return EngineResult(
                ok=False,
                output_text=proc.stderr or proc.stdout or "[claude-code] non-zero exit",
            )

        # Parse the final result line from stream-json output.
        output_text = ""
        usage = Usage()
        raw: dict = {}
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                output_text = event.get("result", "")
                # Usage is best-effort: token counts live under "usage" and the
                # rolled-up cost under "total_cost_usd" at the top level.
                u = event.get("usage", {})
                usage = Usage(
                    input_tokens=u.get("input_tokens"),
                    output_tokens=u.get("output_tokens"),
                    cost_usd=event.get("total_cost_usd"),
                )
                raw = event

        if not output_text:
            output_text = proc.stdout

        return EngineResult(ok=True, output_text=output_text, usage=usage, raw=raw)
