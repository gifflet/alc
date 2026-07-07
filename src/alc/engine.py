# engine.py — The Engine Protocol and its associated data types.
# This is the authoritative contract between the control plane and execution plane.
# Engines do NOT subclass anything — they only need to match this structural shape.
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


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
