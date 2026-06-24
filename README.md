# ALC — Agentic Layer Compiler & Runtime

> A control plane for agentic coding. You declare *how* work should be done once;
> ALC enforces those practices outside the model and drives any coding engine
> (Claude Code, Gemini CLI, Aider, …) as a pluggable executor.

## The thesis

Most "good agentic practices" are **process**, not **model behavior**. Process can
be lifted out of the engine and run deterministically. ALC keeps that process in a
**control plane**; the engine is a thin **execution plane** that only performs one
reasoning-and-editing turn at a time.

Because the practices live in the control plane, they are:

- **Built-in** — they are the default path, not optional discipline.
- **Portable** — the same declared layer runs on any compliant engine.
- **Enforceable** — a policy gate refuses work that violates the rules.

ALC does not promise the model writes perfect code (no tool can). It guarantees that
nothing ships unverified, by wrapping every engine turn in checks, schema validation,
and gates.

## Two planes

```
 Task ─► [ CONTROL PLANE: policy → single-mandate → assurance loop → scorecard ] ─► Report
                                   │  narrow Engine contract  ▲
                                   ▼                          │
         [ EXECUTION PLANE: claude-code | gemini | aider | mock ]  (pluggable)
```

See [`docs/architecture.md`](docs/architecture.md) for the full diagram and
[`docs/engine-contract.md`](docs/engine-contract.md) for what an engine must implement.

## Vocabulary

ALC uses its own terms throughout. They are defined in
[`docs/concepts.md`](docs/concepts.md). The most important ones:

- **Control Surface** — the four dials of any agent: Context, Model, Directive, Tools.
- **Single Mandate** — one agent, one directive, one purpose per invocation.
- **Assurance Loop** — the `Act → Verify → Repair` cycle that re-runs the engine until checks pass.
- **Blueprint** — a parameterized template for a problem class (chore, bug, feature, …).
- **Flow** — a deterministic pipeline that composes agent invocations.
- **Engine** — an adapter over a coding tool, behind a narrow contract.
- **Scorecard** — the four health metrics: Span, Passes, Streak, Touch.
- **Operator Layer** — the declared `.alc/` layer, separate from the application code.

## Status

MVP in design + initial implementation. Scope and roadmap:
[`docs/mvp.md`](docs/mvp.md).

## Quickstart (MVP)

ALC operates on a project's **Operator Layer** (`.alc/`). A runnable example lives under
`examples/demo/`; your own project would carry its own `.alc/`.

```bash
uv sync
cd examples/demo
uv run alc lint                       # check the .alc/ Operator Layer for violations
uv run alc run chore "remove the unused export endpoint" --engine mock
uv run alc flow ship "tidy up the changelog" --engine mock
```

The `mock` engine runs the full control plane without calling any real model — use it
to see the Assurance Loop, policy gate, and Scorecard in action for free.

## Design principles

- **KISS** — the MVP is one vertical slice (one Blueprint, one Assurance Loop, one real
  engine + a mock). Everything else is deferred and documented, not built.
- **SOLID** — the control plane depends only on the `Engine` abstraction; engines,
  checks, and report formats are added without touching the core.
