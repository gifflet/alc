# gemini.py — GeminiEngine: translates the Engine contract to the Gemini CLI (`gemini`).
# A thin translation layer (SRP) that performs one headless turn. Retries,
# verification, and the Assurance Loop are the control plane's responsibility.
#
# The Gemini CLI exposes a DIFFERENT capability surface than Claude Code. This
# adapter declares only the capabilities that are stable across CLI versions and
# lets the control plane emulate the rest (system-prompt append, structured
# output) — which is exactly the portability the Engine contract is designed for.
#
# Invocation (validated against gemini CLI 0.47): `-p/--prompt <directive>` runs
# headless (non-interactive) mode; `--skip-trust` trusts the sandbox (an untrusted
# folder otherwise forces approval back to "default", blocking edits); and
# `--approval-mode auto_edit` auto-approves edit tools so files are written without
# a prompt. The gated live smoke test exercises this once `gemini` is authenticated.
from __future__ import annotations

import os
import subprocess

from alc.engine import Capabilities, EngineRequest, EngineResult, Usage


class GeminiEngine:
    """Execution-plane adapter for the Gemini CLI (`gemini`)."""

    name: str = "gemini"

    def capabilities(self) -> Capabilities:
        """Declare only capabilities ALC relies on across CLI versions.

        Gemini supports MCP natively. Tool scoping, system-prompt append, and
        schema-constrained output are intentionally left to control-plane
        emulation so behavior matches other engines regardless of CLI version.
        """
        return Capabilities(
            native_tool_scoping=False,
            native_system_append=False,
            native_structured_output=False,
            native_subagents=False,
            native_mcp=True,
        )

    def health_check(self) -> bool:
        """Return True if `gemini --version` exits with code 0."""
        try:
            result = subprocess.run(
                ["gemini", "--version"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def run(self, request: EngineRequest) -> EngineResult:
        """Shell out to `gemini` in non-interactive mode and return the result.

        Does NOT retry — that is the Assurance Loop's job. `-p/--prompt` carries
        the directive and triggers headless mode; `--skip-trust` trusts the
        isolated sandbox; `--approval-mode auto_edit` auto-approves edit tools so
        edits happen without a prompt (the analog of Claude Code's acceptEdits).
        The control plane isolates each run, so both are safe.
        """
        cmd = [
            "gemini",
            "--skip-trust",
            "--approval-mode",
            "auto_edit",
            "--prompt",
            request.directive,
        ]

        if request.model:
            cmd += ["--model", request.model]

        # system_append and tool scoping are NOT passed: capabilities() reports
        # them as unsupported, so the control plane already folded system_append
        # into request.directive and sandboxes tool access. Honoring them here
        # would double-apply.

        merged_env = {**os.environ, **request.env}

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=request.workdir,
                timeout=request.timeout_s,
                env=merged_env,
            )
        except subprocess.TimeoutExpired:
            return EngineResult(ok=False, output_text="[gemini] timed out")
        except FileNotFoundError:
            return EngineResult(ok=False, output_text="[gemini] binary not found")
        except Exception as exc:  # noqa: BLE001
            return EngineResult(ok=False, output_text=f"[gemini] error: {exc}")

        if proc.returncode != 0:
            return EngineResult(
                ok=False,
                output_text=proc.stderr or proc.stdout or "[gemini] non-zero exit",
            )

        # Gemini emits plain text on stdout (no stream-json result envelope).
        # The control plane treats output_text generically; usage is unavailable.
        return EngineResult(
            ok=True,
            output_text=proc.stdout.strip(),
            usage=Usage(),
            raw={"stdout": proc.stdout, "stderr": proc.stderr},
        )
