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

import json
import os
import subprocess
import sys
import threading
import time

from alc.engine import (
    Capabilities,
    EngineRequest,
    EngineResult,
    ProgressPrinter,
    Usage,
)

# Map ALC's (claude-code-flavored) permission_mode intent onto the Gemini CLI's
# --approval-mode. Keeps a Blueprint's permission_mode portable across engines:
# `bypassPermissions` (auto-approve everything, incl. shell) -> `yolo`;
# `acceptEdits` / unset (auto-approve edits only) -> `auto_edit` (the default).
_APPROVAL_MODE_MAP = {
    "bypassPermissions": "yolo",
    "acceptEdits": "auto_edit",
}
# Gemini's own --approval-mode values (verified against the CLI docs), accepted
# verbatim so an operator may also name a Gemini mode directly (e.g. "plan").
_GEMINI_APPROVAL_MODES = {"default", "auto_edit", "yolo", "plan"}


def _approval_mode(permission_mode: str | None) -> str:
    """Resolve the Gemini --approval-mode for a request's permission_mode.

    None -> "auto_edit" (byte-identical to the former hardcoded default); a known
    ALC intent is mapped; a raw Gemini mode passes through; anything else falls
    back to the safe "auto_edit" (edits allowed, no interactive prompt).
    """
    if permission_mode is None:
        return "auto_edit"
    if permission_mode in _APPROVAL_MODE_MAP:
        return _APPROVAL_MODE_MAP[permission_mode]
    if permission_mode in _GEMINI_APPROVAL_MODES:
        return permission_mode
    return "auto_edit"


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
        """Stream `gemini -p … --output-format stream-json` and return the result.

        Reads the CLI's newline-delimited JSON events line by line and surfaces
        live progress to stderr (so the operator sees the turn working instead of a
        frozen terminal), and surfaces gemini's own stderr (retries, 503s, warnings)
        too. `stdin` is DEVNULL so a run can never block waiting for interactive
        input. `--approval-mode` comes from the Blueprint's permission_mode (unset ->
        `auto_edit`; `bypassPermissions` -> `yolo`). Does NOT retry — that is the
        Assurance Loop's job. A `result` event with status "error" (e.g. a 503) is
        surfaced as a failed EngineResult rather than a silent success.
        """
        cmd = [
            "gemini",
            "--skip-trust",
            "--approval-mode",
            _approval_mode(request.permission_mode),
            "--output-format",
            "stream-json",
            "--prompt",
            request.directive,
        ]
        if request.model:
            cmd += ["--model", request.model]

        # system_append and tool scoping are NOT passed: capabilities() reports
        # them as unsupported, so the control plane already folded system_append
        # into request.directive and sandboxes tool access.

        merged_env = {**os.environ, **request.env}

        print(
            f"  → gemini working (model={request.model or 'default'})…",
            file=sys.stderr,
            flush=True,
        )
        start = time.monotonic()
        # Diagnostic stderr is bounded tightly (a verbose error dump collapses to a
        # few lines + a summary); the stdout progress stream gets a generous cap.
        # Both collapse consecutive repeats and truncate — generic, content-agnostic.
        err_printer = ProgressPrinter(max_lines=6)
        note_printer = ProgressPrinter()

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=request.workdir,
                env=merged_env,
            )
        except FileNotFoundError:
            return EngineResult(ok=False, output_text="[gemini] binary not found")
        except Exception as exc:  # noqa: BLE001
            return EngineResult(ok=False, output_text=f"[gemini] error: {exc}")

        # Drain stderr in a background thread (so a full stderr pipe can't deadlock
        # the stdout loop), surfacing meaningful lines live — gemini logs retries
        # and 503s there, which are otherwise invisible.
        stderr_buf: list[str] = []

        def _drain_stderr() -> None:
            for raw_line in proc.stderr:
                text = raw_line.rstrip()
                if not text:
                    continue
                stderr_buf.append(text)
                # Skip JS stack frames — keep the human-meaningful lines.
                if text.lstrip().startswith("at "):
                    continue
                err_printer.emit(text)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        timed_out = {"v": False}

        def _on_timeout() -> None:
            timed_out["v"] = True
            proc.kill()

        timer = threading.Timer(request.timeout_s, _on_timeout)
        timer.start()

        assistant_text: list[str] = []
        result_response: str | None = None
        result_status: str | None = None
        result_error: str | None = None
        usage = Usage()
        raw: dict = {}
        try:
            for line in iter(proc.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # A non-JSON stdout line (e.g. a warning) — surface it.
                    note_printer.emit(line)
                    continue
                if not isinstance(event, dict):
                    continue
                etype = event.get("type")
                if etype == "message":
                    if event.get("role") == "assistant":
                        content = event.get("content")
                        if isinstance(content, str) and content.strip():
                            assistant_text.append(content)
                            note_printer.emit(content.strip().splitlines()[0])
                elif etype == "result":
                    result_status = event.get("status")
                    resp = event.get("response")
                    if isinstance(resp, str):
                        result_response = resp
                    err = event.get("error")
                    if isinstance(err, dict):
                        result_error = err.get("message")
                    stats = event.get("stats") or {}
                    usage = Usage(
                        input_tokens=stats.get("input_tokens"),
                        output_tokens=stats.get("output_tokens"),
                        cost_usd=None,
                    )
                    raw = event
            proc.wait()
        finally:
            timer.cancel()

        elapsed = int(time.monotonic() - start)
        err_printer.close()
        note_printer.close()

        if timed_out["v"]:
            return EngineResult(ok=False, output_text="[gemini] timed out")

        # An explicit error result (503, cancellation, …) is a failure, not a silent
        # success — surface the message so the Assurance Loop and operator see it.
        if result_status == "error":
            msg = result_error or "[gemini] run ended with an error"
            print(f"  → gemini failed ({elapsed}s): {msg[:120]}", file=sys.stderr, flush=True)
            return EngineResult(ok=False, output_text=msg, usage=usage, raw=raw)

        if proc.returncode != 0:
            err = "\n".join(stderr_buf).strip()
            return EngineResult(ok=False, output_text=err or "[gemini] non-zero exit", usage=usage)

        print(f"  → gemini done ({elapsed}s)", file=sys.stderr, flush=True)

        # Prefer the result's response field; else the accumulated assistant text.
        output_text = (result_response or "\n".join(assistant_text)).strip()
        if not output_text:
            output_text = "[gemini] completed"
        return EngineResult(ok=True, output_text=output_text, usage=usage, raw=raw)
