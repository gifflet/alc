# Concepts & Vocabulary

ALC defines its own vocabulary for the practices it automates. These terms are used
consistently across the docs and the code. They are grounded in general
agentic-engineering practice; the names here are ALC's own.

## The two-plane model

ALC splits every unit of work into two planes.

| Plane | Owns | Determinism |
|---|---|---|
| **Control plane** | policy, context curation, single-mandate isolation, the assurance loop, scorecard, gates | Deterministic — pure orchestration code |
| **Execution plane** | one reasoning-and-editing turn | Probabilistic — the model |

The rule that makes ALC work: **push every practice that does not require the model
into the control plane.** The more a practice lives outside the model, the more
portable and guaranteed it becomes.

## Core terms

### Control Surface
The four configurable dials of any agent invocation:

- **Context** — what the agent is given to see.
- **Model** — the model behind the turn (resolved from a Compute Tier).
- **Directive** — the fully composed instruction (ALC curates this; the engine receives it ready).
- **Tools** — what the agent is allowed to do.

Everything an engine exposes is, at bottom, an abstraction over these four.

### Single Mandate
One agent, one directive, one purpose per invocation. ALC enforces this by running a
separate engine invocation per task — the engine never has to "stay focused" on its
own, because the control plane never gives it more than one mandate at a time.

### Context Budget
Disciplined management of the context window through two moves:

- **Trim** — reduce what enters the agent's context (curated directive, scoped files,
  a task-specific **Primer** instead of a large always-on memory file).
- **Offload** — delegate side work to separate invocations so it never enters the
  primary context.

### Amplifiers
Codebase properties the control plane relies on to make agents effective: structured
logging, precise types, clear entry points, local docs, and above all **tests** —
which are what the Assurance Loop runs.

### Assurance Loop
The `Act → Verify → Repair` cycle:

1. **Act** — the engine performs one turn.
2. **Verify** — the control plane runs the declared checks (lint, tests, build, e2e).
3. **Repair** — on failure, the control plane re-invokes the engine with the failure
   output, up to a bounded number of repairs.

Checks are law: nothing is reported as done until they pass or the repair budget is
exhausted.

### Blueprint
A parameterized template for a *class* of problem (chore, bug, feature, patch). A
Blueprint declares its workflow, its Compute Tier, its checks, and its report schema.
You describe a task; the Blueprint supplies the practice.

### Primitive & Blocks
A **Primitive** is a single composable prompt assembled from **Blocks** (purpose,
workflow, variables, report, …). Use only the blocks a given prompt needs.

### Flow
A deterministic pipeline that composes multiple agent invocations
(e.g. plan → build → verify → review → document). A Flow is plain orchestration code
that calls engines through the contract. Each stage is a separate Single Mandate;
the output of one stage becomes upstream context for the next.

### Compute Tier
A named compute level (`standard`, `deep`) mapped, per engine, to a concrete model id.
Blueprints pick a tier; engines resolve it. This is the compute dial without
hard-coding model names.

### Attended vs Unattended Mode
- **Attended Mode** — a human is present and iterating.
- **Unattended Mode** — Flows run without a human, via four elements: **Source**
  (where the task comes from), **Trigger** (what starts it), **Sandbox** (isolated
  environment), **Gate** (how the result is reviewed). The cron Trigger path is
  available via `alc tick` over a YAML task queue; webhook triggering is future work.

### Specialist & Knowledge File
A **Specialist** is an agent that keeps a **Knowledge File** (a working model of one
area of the codebase) and self-tunes it via an `Apply → Learn → Recall` cycle. The
Knowledge File is a working model, not a source of truth — the code is.

### Conductor
A single-interface agent that creates, commands, and retires other agents, so you talk
to one agent instead of a fleet. Invoked via `alc conduct "<goal>"`; the Conductor
plans the required Flows and either runs them immediately or enqueues them for
`alc tick`.

### Scorecard
Four health metrics, recorded per run:

| Metric | Direction | Meaning |
|---|---|---|
| **Span** | ↑ | Amount of work delivered per prompt |
| **Passes** | ↓ | Engine turns needed to reach done |
| **Streak** | ↑ | Consecutive one-shot (zero-repair) successes |
| **Touch** | ↓ | Human interventions required |

The north star is **Hands-off Delivery**: `Touch → 0`.

### Operator Layer
The declared `.alc/` layer — manifest, blueprints, policies — from which agents operate
the codebase. It is kept separate from the **Application Layer** (the product code) on
purpose: the Operator Layer acts *on* the codebase, not *inside* it.

### Policy Gate / Conformance
A lint that refuses agents and flows violating the rules (no Assurance Loop, not a
Single Mandate, missing report schema, over-budget context). This is what turns the
practices from advice into a guarantee.

## Maturity Ladder

The roadmap progression, used to place every deferred feature:

1. **Attended** — agents work with you, in the loop.
2. **Detached** — Flows run unattended (Source, Trigger, Sandbox, Gate).
3. **Conducted** — a Conductor orchestrates flows and agents on your behalf.
