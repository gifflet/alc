# engine.py — The Engine Protocol and its associated data types.
# This is the authoritative contract between the control plane and execution plane.
# Engines do NOT subclass anything — they only need to match this structural shape.
from __future__ import annotations

import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


def path_roots(workdir: str | Path | None) -> tuple[str, ...]:
    """Prefixes that mean "inside *workdir*", longest first.

    Both the path as given and as resolved: macOS hands out ``/var/folders/...``
    temp dirs that resolve to ``/private/var/folders/...`` and an engine may
    report either form, so matching one would leave half the notes unshortened.
    """
    if not workdir:
        return ()
    raw = Path(workdir)
    try:
        candidates = {str(raw), str(raw.resolve())}
    except OSError:  # pragma: no cover — an unresolvable cwd is still usable as text
        candidates = {str(raw)}
    return tuple(sorted((f"{c.rstrip('/')}/" for c in candidates), key=len, reverse=True))


def shorten_path(text: str, roots: Sequence[str]) -> str:
    """Strip a leading worktree prefix from *text* so the varying part survives.

    Every path an engine reports during a run lives under the same worktree, so
    the prefix is the one part that is identical on every line — and the part a
    width limit would otherwise keep, dropping the filename that distinguishes
    them. Returns *text* unchanged when it is not under any root, and when
    stripping would leave nothing (the worktree root itself).
    """
    for root in roots:
        if text.startswith(root):
            return text[len(root) :] or text
    return text


def elide(text: str, width: int) -> str:
    """Shorten *text* to *width* by removing the MIDDLE, not the tail.

    A tool-call note reads "Read: <path>": the head names the tool and the tail
    names the file. Cutting from the right keeps neither — only the shared
    directory in between.
    """
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    keep = width - 1  # one column for the ellipsis
    head = keep // 2
    return f"{text[:head]}\u2026{text[head - keep :]}"


@dataclass(frozen=True)
class Capabilities:
    """What an engine can do natively. Anything False is emulated by the control plane."""

    native_tool_scoping: bool = False       # can restrict allowed/denied tools itself
    native_system_append: bool = False      # can append to its own system prompt
    native_structured_output: bool = False  # can emit schema-constrained output
    native_subagents: bool = False          # can spawn its own sub-agents
    native_mcp: bool = False               # supports MCP servers


@dataclass(frozen=True)
class EngineRequest:
    """One Single-Mandate turn. Context is already curated by the control plane."""

    directive: str                          # the composed prompt, ready to run
    workdir: Path                           # sandbox / worktree to operate in
    model: str | None = None               # concrete model id resolved from a Compute Tier
    allowed_tools: tuple[str, ...] = ()    # best-effort; emulated if unsupported
    denied_tools: tuple[str, ...] = ()     # best-effort; emulated if unsupported
    system_append: str | None = None       # best-effort; prepended to directive if unsupported
    timeout_s: int = 1800
    env: dict[str, str] = field(default_factory=dict)
    permission_mode: str | None = None     # engine-interpreted; None means use the engine default


@dataclass(frozen=True)
class Usage:
    """Token and cost accounting — best-effort; may be empty."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class EngineResult:
    """Result of one headless engine turn."""

    ok: bool                                # did the turn run to completion?
    output_text: str                        # final message / stdout
    usage: Usage = field(default_factory=Usage)
    raw: dict = field(default_factory=dict)  # engine-specific payload


class ProgressPrinter:
    """Surface an engine's live progress lines to stderr with generic, content-agnostic
    noise control.

    Any adapter streaming a subprocess's stdout/stderr routes lines through ``emit``;
    the authoritative, full output still lives in the returned ``EngineResult`` (so the
    live view can be bounded without losing anything). Three filters, none of which
    inspect meaning — so this is engine-agnostic and error-type-agnostic, not a
    per-tool or per-error heuristic:

    - **truncate** each line to ``max_width`` from the MIDDLE (keeps the terminal
      readable without dropping the end of the line, which is the part that varies),
    - **collapse** a line identical to the one just printed (kills repeat spam),
    - **cap** the total to ``max_lines``; further lines are counted and summarised by
      ``close`` as "… (N more lines suppressed)".

    Use a generous ``max_lines`` for a real progress stream (tool calls) and a tight one
    for diagnostic stderr (verbose error dumps). Thread-safe: an adapter may feed one
    printer from both a stdout loop and a stderr drain thread.
    """

    def __init__(
        self,
        prefix: str = "    • ",
        max_width: int = 100,
        max_lines: int = 500,
        event: str | None = None,
    ) -> None:
        self._prefix = prefix
        self._max_width = max_width
        self._max_lines = max_lines
        # When set, each PRINTED line is also persisted to the bound run log as
        # emit(event, note=<full line>) — engine-agnostic: any adapter that routes
        # granular activity (tool uses, notes) through a printer with an event name
        # gets it in the run detail, with zero per-engine code.
        self._event = event
        self._lock = threading.Lock()
        self._printed = 0
        self._suppressed = 0
        self._last: str | None = None

    def emit(self, line: str) -> None:
        """Print one progress line, subject to truncate / collapse-repeat / cap.

        When constructed with an ``event`` name, the (untruncated) line is also
        appended to the bound run log — the run detail's engine-activity feed. That
        emission is best-effort and a no-op when no run log is bound.
        """
        line = line.strip()
        if not line:
            return
        truncated = elide(line, self._max_width)
        with self._lock:
            # Compare the FULL line, not the displayed one: two reads of different
            # files in the same deep directory shorten to the same text, and
            # deduping on that would show one line where two things happened.
            if line == self._last:
                return
            self._last = line
            if self._printed >= self._max_lines:
                self._suppressed += 1
                return
            self._printed += 1
        print(f"{self._prefix}{truncated}", file=sys.stderr, flush=True)
        if self._event:
            from alc.events import emit as emit_event

            emit_event(self._event, note=line)

    def close(self) -> None:
        """Emit a one-line summary if the cap suppressed any lines. Idempotent."""
        with self._lock:
            n = self._suppressed
            self._suppressed = 0
        if n:
            print(
                f"{self._prefix}… ({n} more line(s) suppressed)",
                file=sys.stderr,
                flush=True,
            )


@runtime_checkable
class Engine(Protocol):
    """Structural protocol every execution-plane adapter must satisfy."""

    name: str

    def capabilities(self) -> Capabilities:
        """Declare native capabilities so the control plane knows what to emulate."""
        ...

    def health_check(self) -> bool:
        """Is the tool installed and authenticated? Cheap, no model call."""
        ...

    def run(self, request: EngineRequest) -> EngineResult:
        """Perform exactly one headless turn in request.workdir."""
        ...
