# Architecture

ALC is a **control plane** that drives pluggable **execution planes** (engines) through
a narrow contract. Best-practice enforcement lives entirely in the control plane.

## The diagram

```
                         INPUT                                                    OUTPUT
                  task + blueprint                                          report + scorecard
                         │                                                         ▲
                         ▼                                                         │
 ┌───────────────────────────────────────── ALC CONTROL PLANE ─────────────────────────────────────────┐
 │                                                                                                       │
 │   ┌──────────┐   ┌──────────────┐   ┌───────────────┐   ┌───────────────────────────┐   ┌─────────┐  │
 │   │  Intake  │──►│ Policy Gate  │──►│   Mandate     │──►│      Assurance Loop        │──►│Scorecard│  │
 │   │ load     │   │ conformance  │   │   Runner      │   │   Act → Verify → Repair    │   │ + logs  │  │
 │   │ manifest │   │ lint (refuse │   │ (Single       │   │                            │   │ Span    │  │
 │   │+blueprint│   │  violations) │   │  Mandate,     │   │  ┌──────┐   ┌───────────┐  │   │ Passes  │  │
 │   │          │   │              │   │  Context      │   │  │ Act  │   │  Verify   │  │   │ Streak  │  │
 │   │          │   │              │   │  Budget,      │   │  │engine│   │ run checks│  │   │ Touch   │  │
 │   │          │   │              │   │  Compute Tier)│   │  │ turn │   │ (the law) │  │   │         │  │
 │   └──────────┘   └──────────────┘   └───────┬───────┘   │  └──┬───┘   └─────┬─────┘  │   └─────────┘  │
 │                                             │           │     │  ◄─Repair─  │ fail   │                │
 │                                             │           │     ▼      on     ▼        │                │
 │                                             │           │   compose repair directive │                │
 │                                             │           └────────────┬───────────────┘                │
 └─────────────────────────────────────────────┼────────────────────────┼──────────────────────────────┘
                                                │   EngineRequest        │   EngineResult
                                                │   (the contract)       │
                                                ▼                        │
 ┌──────────────────────────────────── EXECUTION PLANE (pluggable) ──────┴──────────────────────────────┐
 │                                                                                                       │
 │   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────────┐  │
 │   │ Claude Code      │   │ Gemini CLI       │   │ Aider            │   │ Mock (free, hermetic)    │  │
 │   │ adapter          │   │ adapter          │   │ adapter          │   │ adapter                  │  │
 │   │ caps: tools,     │   │ caps: mcp,       │   │ caps: minimal    │   │ caps: none — exercises   │  │
 │   │ hooks, subagents │   │ headless         │   │ headless         │   │ the loop with no model   │  │
 │   └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘   └────────────┬─────────────┘  │
 └────────────┼──────────────────────┼──────────────────────┼───────────────────────────┼───────────────┘
              └──────────────────────┴──────────┬───────────┴───────────────────────────┘
                                                 ▼
                                       Codebase (sandbox / worktree)
```

### What the diagram says

- The control plane runs **left to right** and is fully deterministic.
- The only door between the planes is the **Engine contract**
  (`EngineRequest` in, `EngineResult` out) — see
  [`engine-contract.md`](engine-contract.md).
- Engines are **swappable**. The same task on `claude-code` or `gemini` follows the
  identical control-plane path; only the quality of the `Act` step changes.
- Capability gaps in an engine are filled by the control plane (capability emulation),
  not by the caller.

## Components

| Component | Responsibility (single) | Depends on |
|---|---|---|
| **Intake** | Load and parse the manifest + the requested Blueprint | models |
| **Policy Gate** | Refuse a run whose Operator Layer violates the rules | models |
| **Mandate Runner** | Compose one Single-Mandate directive, resolve engine + Compute Tier, build the `EngineRequest` | `Engine` abstraction |
| **Assurance Loop** | `Act → Verify → Repair` until checks pass or repair budget runs out | `Engine`, `Verifier` |
| **Verifier** | Run the declared checks, return pass/fail + output | none (subprocess) |
| **Scorecard** | Record Span / Passes / Streak / Touch for the run | models |
| **Engine (Protocol)** | Perform one headless turn; declare capabilities; health-check | none |
| **Engine adapters** | Translate the contract to a concrete tool | `Engine` |
| **Registry** | Resolve an engine name to an adapter instance | `Engine` |

Each component has exactly one reason to change (SRP). The control plane never imports a
concrete engine — only the `Engine` abstraction (DIP).

## Data flow (one `alc run`)

1. **Intake** loads `.alc/manifest.yaml` and the named Blueprint.
2. **Policy Gate** lints both; on an `error` violation the run stops here.
3. **Mandate Runner** composes the directive (Blueprint workflow + task + curated
   context), resolves the engine and the model for the Blueprint's Compute Tier, and
   builds one `EngineRequest`.
4. **Assurance Loop**:
   - **Act** — `engine.run(request)`.
   - **Verify** — `Verifier` runs the Blueprint's checks in the sandbox.
   - **Repair** — if any check fails and the repair budget allows, compose a repair
     directive (original + failure output) and loop back to Act.
5. **Scorecard** records the attempt history; the run returns a report.

## Capability emulation

The control plane inspects `engine.capabilities()` and fills any gap so behavior is
uniform across engines:

| Capability absent | Control-plane fallback |
|---|---|
| Tool scoping | Sandbox the working directory / restrict the environment |
| System-prompt append | Prepend the text to the `directive` |
| Structured output | Validate the output against the schema and re-ask on mismatch |
| Subagents | Run additional engine invocations and route between them |

This is why the minimum bar for an engine is low (see the contract): *accept a directive
headlessly and edit files.* Everything else, ALC supplies.
