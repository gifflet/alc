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

### Spike — the fenced exception
`mode: spike` on a Blueprint is the **one** relaxation of the checks gate ALC allows
— not a general escape hatch, a single named field that is grepable and auditable by
itself, never a side effect of a descriptive label like `archetype`. In this mode
Policy Gate rule 1 (`blueprint_has_checks`) drops from error to warn, but every other
guarantee tightens rather than loosens: the runner forces isolation, sets
`max_repairs` to `0`, and forbids both commit and auto-merge; the run's
`RunReport.spike` is `True` and it is excluded from the Scorecard `streak` (a
one-shot spike proves nothing about repeatable delivery). Declaring `mode: spike`
together with an enabled `CommitSpec` is itself a Policy Gate **error** — the
exception can never become a delivery path. `alc spike "<task>"` is the entry point:
sugar over `alc run` against the Prototyper pack's `spike` Blueprint, no blueprint
name to remember and no isolation/commit flags to opt into.

### `protect:` — deterministic behavior-preservation
A Blueprint's `protect: [globs]` is the half of "don't touch what you're not
supposed to" that does not depend on the model remembering an instruction. After
every Act, the control plane diffs the paths changed so far (inside the Assurance
Loop, per attempt — not once for the whole run) against the declared globs
(`fnmatch`); any hit becomes a synthetic failed check (`protected-paths`) that feeds
the same repair addendum a real check failure would ("you edited a protected path;
revert it") — no new mechanism, the existing Act → Verify → Repair cycle does the
work. Outside a git repository, or when git itself is unavailable, `protect`
degrades to a silent no-op rather than raising — a guard that cannot compute its
answer must never be the reason a run fails. The Sweeper pack's `refactor` Blueprint
declares `protect: ["tests/**", "test/**"]`, turning "a refactor must not touch
tests" from workflow prose an agent could ignore into something the control plane
itself enforces.

### Archetype Pack & the Team metaphor
An **Archetype Pack** is scaffolded content — Blueprints, Flows, Specialists, Loops —
for one of the five roles a codebase moves through over its life. `alc team hire
<archetype>` writes a pack's files (refusing to overwrite existing ones without
`--force`) and lints the result; `alc team list`/`status` rosters what is hired and
the state of any Loops a member brought; `alc team retire <member>` archives — never
deletes — a member's Loop definitions. Packs are the implementation; `team` is the
only verb an operator sees.

| Archetype | Role | What the pack ships |
|---|---|---|
| **Prototyper** | Churns out new ideas; most don't ship | a `spike` Blueprint (`mode: spike`) fencing the checks gate; `alc spike "<task>"` is the entry point |
| **Builder** | Turns a prototype into production-quality product/infra | `test` (test authoring) and `qa` (live e2e) Blueprints, a hardened `ship-hardened` Flow |
| **Sweeper** | Cleans the UI, simplifies code, removes features (*unship*) | a `janitor` Specialist naming the real dead-code command per detected stack, a `refactor` Blueprint, a `sweep` Loop, an `unship` Flow |
| **Grower** | Iterates a built product to improve Product-Market Fit | **partial**: a DIY issue/error-sweep Specialist (`listen`) only — real signal intake, metric checks, and the `regression` replenish kind are later-phase work |
| **Maintainer** | Keeps a mature system safe, reliable, fast, and efficient at scale | a `patrol` Flow gated by the `security` check_set, a `deps` Specialist, a `deps-refresh` Loop |

`alc init --stage pre-pmf|growth|strong-pmf` is sugar over `alc team hire` — it
installs a stage's pack combo in one shot and has no effect beyond that selection.

`archetype:` — set on a Blueprint's front-matter, copied to `RunReport.archetype` —
is a **descriptive label with zero runtime effect**. It exists for reporting and
future Mix Health work; behavior always lives in a named field (`check_set`,
`needs_service`, …), never behind this string.

## Maturity Ladder

The roadmap progression, used to place every deferred feature:

1. **Attended** — agents work with you, in the loop.
2. **Detached** — Flows run unattended (Source, Trigger, Sandbox, Gate).
3. **Conducted** — a Conductor orchestrates flows and agents on your behalf.
