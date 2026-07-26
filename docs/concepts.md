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

### Metric Checks — the law extended to numbers
A `Check` can declare `metric` instead of `command`/`shell`: a command that prints ONE
number on stdout. The engine never judges that number — the control plane does, the
same way it judges any other check's exit code. The Verifier runs the command, parses
the number (non-numeric stdout is itself a failed check, never a crash), and compares
it against the most recent ACCEPTED measurement recorded in the project's metric
ledger (one JSON line per measurement, the same append-only shape the Loop ledger
uses). `direction` (`lower_is_better`/`higher_is_better`) says which way is a
regression; `tolerance_pct` absorbs benchmark noise. A metric with no history yet
always PASSES — it becomes the first baseline, never a phantom failure; a metric that
DOES regress fails like any other check and can be repaired like any other failure.
`alc metrics [--check NAME] [--json]` reads the ledger back as a time series: value,
delta against the previous measurement, and trend.

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
  environment), **Gate** (how the result is reviewed). Two Trigger paths ship today:
  cron, via `alc tick` over a YAML task queue, and a webhook, via `alc serve --webhook`
  (a minimal HTTP door onto signal intake and the enqueue path — see below).

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

The same idiom guards the checks themselves. A run's checks are its *law* — the bar
the work must clear — and an engine that cannot make the code pass can make the law
pass instead: widen an eslint ignore, delete a `[tool.ruff]` rule, rewrite a `test`
script to `true`. The `check-config-integrity` guard closes that door. After every
Act it crosses the paths changed so far against a curated set of check-defining
files (linter/formatter/type-checker configs, `make`/`just`/`Taskfile` recipes,
`pre-commit`/`tox`/`pytest`/`mypy` config, and — content-aware, so a plain dependency
bump stays clean — a `package.json` `scripts` map, a `pyproject.toml` `[tool]` table,
and any script a check's own command names); any hit becomes a synthetic failed
check (`check-config-integrity`) feeding the same repair addendum (revert the config,
fix the code). This makes the law tamper-*evident* — the run is always recorded as
having touched check config (`RunReport.check_config_edits` plus a warning) — and
tamper-*resistant* — a run that silently weakens a check fails, and a failed run
never auto-lands. A maintenance Blueprint whose whole job is to edit that config sets
`allow_check_config: true` to waive the guard; the edit is then permitted but the
evidence still fires, and a Policy Gate warn keeps the standing exception visible.
Outside a git repository the guard degrades to a silent no-op, exactly like
`protect:`.

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
| **Sweeper** | Cleans the UI, simplifies code, removes features (*unship*) | a `janitor` Specialist naming the real dead-code command per detected stack, a `refactor` Blueprint, a `sweep` Loop, an `unship` Flow whose gate verifies the removal against the project's **real** `check_set` — the codebase must still hold together without the feature, not merely be declared gone (see [The Sweeper's `unship` gate](#the-sweepers-unship-gate--verify-a-removal-dont-just-declare-it) below) |
| **Grower** | Iterates a built product to improve Product-Market Fit | **partial**: a DIY issue/error-sweep Specialist (`listen`) only — real signal intake and a `regression` replenish kind are later-phase work; metric checks (above) are a general control-plane primitive already available to any Blueprint |
| **Maintainer** | Keeps a mature system safe, reliable, fast, and efficient at scale | a `patrol` Flow gated by the `security` check_set, a `deps` Specialist, a `deps-refresh` Loop |

`alc init --stage pre-pmf|growth|strong-pmf` is sugar over `alc team hire` — it
installs a stage's pack combo in one shot and has no effect beyond that selection.

`archetype:` — set on a Blueprint's front-matter, copied to `RunReport.archetype` —
is a **descriptive label with zero runtime effect**. It exists for reporting and as
the input Mix Health (below) aggregates by; behavior always lives in a named field
(`check_set`, `needs_service`, …), never behind this string.

### The Sweeper's `unship` gate — verify a removal, don't just declare it
Removing a feature is only *done* when the codebase still holds together without it,
so the `unship` Flow ends in a pure verification gate. The `remove` stage does the
deletion; the `gate` stage (`verify_only: true`) then re-runs the project's **real**
`check_set` and passes only if it still goes green. Checks are law here as everywhere —
a removal is judged by the same build/test/lint that guards every other change, not by
a bespoke rule the Sweeper invents.

- **`expect: shrink` is advisory.** The `refactor` Blueprint declares it to state that
  this mandate should reduce the codebase, and Mix Health reports when a shrink run
  finishes net-positive — but it **never fails a run**. It is a signal, not a gate.
- **Prove-absence by text search is an opt-in, off by default.** An earlier design
  proved each removed symbol gone by grepping for it: a `map` stage lists the symbols
  and the gate's `derive_checks` turns each into a `! grep …` check. Text search is only
  a heuristic — a name that is not unique can never be proven absent — so real checks are
  preferred and this is no longer the default. The scaffolded `unship.yaml` carries the
  `map` + `derive_checks` recipe as a commented block you can uncomment, and the `map`
  Blueprint still ships for that purpose.
- **A project with only placeholder checks is reported INCONCLUSIVE.** When the only
  resolvable check is the `["true"]` smoke placeholder, the gate has nothing real to
  verify against, so `require_real_checks` reports the removal as *inconclusive*
  (honestly unverified) rather than fabricating a green pass or a red fail. The fix is
  the one the Checks view nudges you toward: give the project a real `check_set` in the
  Manifest's `check_sets`.

**Migration.** Existing projects keep their current `.alc/flows/unship.yaml` untouched —
`alc team hire` never overwrites a file you already have. To adopt the real-checks gate,
re-scaffold with `alc team hire sweeper --force`, which rewrites the Sweeper pack's files
(`unship.yaml`, `refactor.md`, `map.md`, the `janitor` Specialist, the `sweep` Loop) with
the new versions. A Specialist's Knowledge File is not a pack file and is never touched by
hiring — only the scaffolded pack content is.

### Stage & Mix Health — the mix as a measure of the team's health
`Manifest.stage` (`pre-pmf` / `growth` / `strong-pmf`) declares which phase of
product life the codebase is in. Each stage has a target archetype mix — pre-PMF
centers on prototyper+builder+sweeper; growth on builder+sweeper+grower (plus some
maintainer); strong-PMF on sweeper+grower+maintainer (plus some builder) — a health
**heuristic**, not a law of physics: the default lives in code but a manifest can
replace it wholesale with `stage_mix:`. Every rule the stage drives is **advisory**:
a core archetype with no Blueprint hiring it warns with an `alc team hire <archetype>`
hint; a `compute_tier: deep` Blueprint whose archetype sits outside the mix warns
too; a Blueprint (or a Conductor plan's unit) with no `archetype` is **never**
penalised. The stage never changes how a mandate executes — its authority stops at
warnings, reports, and scaffolds.

**Mix Health** (`alc team status`) is the answer to the question the mix exists to
ask: is the autonomous work actually the RIGHT work for this product's stage? It
aggregates every archived `RunReport` by `archetype` — runs, span, cost, net-lines —
and sets the real spend against the stage's target mix. With no `stage` declared it
still shows the breakdown, just never judges it against anything.

The **Conductor** is stage-aware in two parts with deliberately different
guarantees: a prose briefing nudges the planning model toward the mix (probabilistic
— the model may ignore it), while a deterministic check runs AFTER the plan comes
back and warns when the planned units drift from the mix — that second part is the
actual guarantee; `--strict-stage` turns its warning into a refusal. With no `stage`
declared, neither part changes anything.

Opt-in throughout: no `stage` in the Manifest means no mix rule anywhere, exactly as
before this existed.

### Signal intake & the closed loop — the Grower's loop, completed

Every demand so far started in the operator's head — a goal, a roadmap, a hand-written
YAML. A **Signal** is how real usage gets in instead: a typed JSON file (`kind` ∈
`error`/`feedback`/`issue`/`review`, plus `source`, `title`, `body`, `ts`) dropped into
`manifest.signals_dir` (default `.alc/signals`), written by `alc signal ingest` or
received over `alc serve --webhook`'s `POST /signal` — an error tracker, a user report,
an issue, a code review comment, whatever the operator can turn into that shape. No
per-SaaS connector: one typed intake, any source that can format JSON.

A signal is DATA, not a command — on its own it does nothing. A `signals` replenish
kind on an Autonomous Loop reads every pending signal and turns each into a demand
(the signal's title/body become the task) through `dispatch_enqueue` — the exact write
`alc enqueue` uses — so it clears the Policy Gate, isolates, and retries like any other
demand; the consumed signal moves to `signals_dir/done/`, mirroring the queue's own
archive. External signal never bypasses the control plane.

That demand becomes a change the Assurance Loop verifies. When the Blueprint carries a
`metric` check, verifying it also records a measurement in the project's ledger — the
loop's **measurement** leg closes as a byproduct of checks that were already running,
no separate instrumentation step. A `needs_service` Blueprint that also declares
`capture:` (a shell command — a screenshot script, a curl into a file, whatever the
operator supplies) goes one step further: once the health poll has proven the app
reachable, ALC runs it and collects whatever it wrote — plus the health-poll log,
persisted instead of discarded — into `RunReport.artifacts`. `alc artifacts [<stem>]`
reads them back: the difference between "the checks exited 0" and an actual screenshot
of the golden path having worked.

A second replenish kind, `regression`, closes the last leg. Each cycle it reads the
metric ledger for any check whose newest measurement the Verifier itself REJECTED (its
own tolerance judgment, not re-derived) and auto-enqueues ONE fix demand carrying the
delta as failure feedback — the same delimited-feedback shape a failed check's retry
already uses. The control plane only detects and proposes; it never rolls back on its
own — the fix demand is verified by the Policy Gate, isolation, and checks like any
other, same as everything upstream of it.

Chained together, this is the Grower's loop from the essay that inspired this roadmap,
closed in code rather than left as aspiration:

**signal → demand → change → measurement → regression → demand**

Every step reuses a primitive that already existed — the queue, the Policy Gate, the
Assurance Loop, the metric ledger — so closing the loop added exactly two replenish
kinds and one typed intake, never a second execution path.

## Maturity Ladder

The roadmap progression, used to place every deferred feature:

1. **Attended** — agents work with you, in the loop.
2. **Detached** — Flows run unattended (Source, Trigger, Sandbox, Gate).
3. **Conducted** — a Conductor orchestrates flows and agents on your behalf.
