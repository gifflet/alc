# The Minimum Engine Contract

An **Engine** is an adapter over a coding tool (Claude Code, Gemini CLI, Aider, …).
The contract is intentionally narrow: it is the smallest surface that lets ALC drive a
tool while keeping every best practice in the control plane.

## The bar

To be pluggable, an engine MUST be able to:

1. **Accept a fully composed directive headlessly** (no interactive session), and
2. **Edit files** in a given working directory,

and report whether the turn ran. That is the whole bar. ALC supplies single-mandate
isolation, context curation, the assurance loop, scorecard, and gating — none of which
the engine has to know about.

## The interface

The contract is expressed as a Python `Protocol` (structural typing — an engine does
not need to subclass anything, only match the shape). This is the authoritative
signature the MVP implements.

```python
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
    native_subagents: bool = False           # can spawn its own sub-agents
    native_mcp: bool = False                 # supports MCP servers


@dataclass(frozen=True)
class EngineRequest:
    """One Single-Mandate turn. Context is already curated by the control plane."""
    directive: str                           # the composed prompt, ready to run
    workdir: Path                            # sandbox / worktree to operate in
    model: str | None = None                 # concrete model id resolved from a Compute Tier
    allowed_tools: tuple[str, ...] = ()      # best-effort; emulated if unsupported
    denied_tools: tuple[str, ...] = ()       # best-effort; emulated if unsupported
    system_append: str | None = None         # best-effort; prepended to directive if unsupported
    timeout_s: int = 1800
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class EngineResult:
    ok: bool                                  # did the turn run to completion?
    output_text: str                          # final message / stdout
    usage: Usage = Usage()                    # best-effort; may be empty
    raw: dict = field(default_factory=dict)   # engine-specific payload


@runtime_checkable
class Engine(Protocol):
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
```

### Notes

- **Changed files are not in the contract.** ALC derives them with `git diff` in the
  `workdir`. Engines do not have to track edits — KISS, and it works for every tool.
- `run()` performs **one turn**. Multi-step orchestration is the control plane's job
  (Assurance Loop, Flows), never the engine's.
- `EngineResult.ok` means *the process ran*, not *the work is correct*. Correctness is
  decided by the Verifier, outside the engine.

## Required vs optional

| Method / field | Requirement | If absent / unsupported |
|---|---|---|
| `run()` | MUST | — (no fallback; engine is unusable) |
| `capabilities()` | MUST | — |
| `health_check()` | MUST | — |
| `model` resolution | SHOULD | Engine uses its own default model |
| `native_tool_scoping` | OPTIONAL | Control plane sandboxes the workdir |
| `native_system_append` | OPTIONAL | Control plane prepends to the directive |
| `native_structured_output` | OPTIONAL | Control plane validates + re-asks |
| `native_subagents` | OPTIONAL | Control plane runs extra invocations |
| `usage` reporting | OPTIONAL | Scorecard omits cost/token figures |

## Capability matrix (reference)

Indicative native support; gaps are emulated by the control plane.

| Capability | Claude Code | Gemini CLI | Aider | Mock |
|---|---|---|---|---|
| Headless directive | ✅ | ✅ | ✅ | ✅ |
| Tool scoping | ✅ | ⚠️ | ❌ | ❌ |
| System append | ✅ | ✅ | ⚠️ | ❌ |
| Structured output | ✅ | ✅ | ⚠️ | ❌ |
| Subagents | ✅ | ⚠️ | ❌ | ❌ |
| MCP | ✅ | ✅ | ⚠️ | ❌ |

The **Mock** engine declares no capabilities on purpose: it exercises the full control
plane (loop, gate, scorecard) with no model call, so the practices can be tested for
free and hermetically.

## Conformance checklist (adding an engine)

1. Implement `name`, `capabilities()`, `health_check()`, `run()`.
2. Map ALC Compute Tiers to the tool's model ids in the manifest.
3. In `run()`, invoke the tool **headlessly** in `request.workdir` and return an
   `EngineResult`. Do not implement loops, retries, or verification — those belong to
   the control plane.
4. Honor `allowed_tools` / `denied_tools` / `system_append` **only if** the
   corresponding capability is `True`; otherwise leave them for emulation.
5. Register the adapter in the engine registry under a stable `type` name.

If you find yourself adding orchestration logic to an adapter, it belongs in the
control plane instead. The adapter stays a thin translation layer (SRP).

## Reference adapter: Claude Code

Sketch of the first real adapter (implemented in the MVP):

```python
# claude_code.py — translates the contract to `claude -p` (headless).
# capabilities(): tool scoping, system append, structured output, subagents, mcp = True
# run(): shells out to `claude --print --output-format stream-json
#        [--model <model>] [--append-system-prompt <system_append>]
#        [--allowedTools ...] [--disallowedTools ...]`
#        in request.workdir, parses the final result, returns EngineResult.
# health_check(): `claude --version` exits 0.
```
