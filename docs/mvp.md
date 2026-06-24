# MVP Design

The MVP is the **smallest vertical slice that proves the thesis**: best practices are
enforced in the control plane and the engine is pluggable. Everything not needed for
that proof is deferred and listed at the bottom.

## What the MVP proves

Running one task end to end shows, with no real model required (via the Mock engine):

- a task flows through **Policy Gate → Mandate Runner → Assurance Loop → Scorecard**;
- the **Assurance Loop** re-invokes the engine when checks fail (practice enforced
  outside the model);
- swapping `--engine mock` for `--engine claude-code` changes only the executor, not
  the control-plane path (portability).

## In scope

- `.alc/` **Operator Layer**: one `manifest.yaml` + one Blueprint (`chore`).
- **Engine contract** (`Engine` Protocol) + two adapters: **Mock** (default, hermetic)
  and **Claude Code** (`claude -p`).
- **Engine registry** resolving a name/type to an adapter.
- **Mandate Runner** — composes one Single-Mandate directive and one `EngineRequest`.
- **Assurance Loop** — `Act → Verify → Repair`, bounded repair budget.
- **Verifier** — runs the Blueprint's checks via subprocess, returns pass/fail + output.
- **Scorecard** — records Span / Passes / Streak / Touch for the run (in-memory + JSON).
- **Policy Gate** — `alc lint`: a small set of conformance rules.
- **CLI** — `alc lint` and `alc run <blueprint> "<task>" [--engine NAME]`.
- Tests proving the loop and the gate with the Mock engine.

## Out of scope (deferred — mapped to the Maturity Ladder)

| Deferred feature | Ladder stage |
|---|---|
| Flows (multi-step pipelines), `plan → build → verify → review → document` | Attended |
| Specialists + Knowledge File (`Apply → Learn → Recall`) | Attended |
| Context Budget automation (Primer generation, bundle replay) | Attended |
| Compile to native artifacts (`.claude/commands`, Cursor rules) | Attended |
| Worktree/sandbox isolation per run | Detached |
| Unattended Mode: Source / Trigger (webhook, cron) / Sandbox / Gate | Detached |
| Observability dashboard, screenshots/e2e evidence | Detached |
| Conductor (orchestrator) + agent CRUD | Conducted |

Deferring these is deliberate (KISS). The MVP's interfaces are the seams they plug into.

## Module map

```
alc/
  pyproject.toml
  .alc/
    manifest.yaml
    blueprints/
      chore.md                 # front-matter (name, tier, checks, report) + workflow body
  src/alc/
    __init__.py
    models.py                  # pydantic: Manifest, Blueprint, Check, RunReport, Scorecard
    engine.py                  # Engine Protocol + EngineRequest/EngineResult/Capabilities/Usage
    engines/
      __init__.py
      registry.py              # name/type -> Engine instance
      mock.py                  # MockEngine: no model, deterministic, for tests/demos
      claude_code.py           # ClaudeCodeEngine: `claude -p` headless
    intake.py                  # load + parse manifest and blueprints
    policy.py                  # Policy Gate: conformance rules -> [Violation]
    verifier.py                # run checks -> [CheckResult]
    assurance.py               # AssuranceLoop: Act -> Verify -> Repair
    runner.py                  # MandateRunner: ties it together for one task
    cli.py                     # argparse entrypoint: `lint`, `run`
  tests/
    test_policy.py
    test_assurance.py
    test_runner.py
```

## Key types (authoritative for implementation)

```python
# models.py
class Check(BaseModel):
    name: str
    command: list[str]          # e.g. ["pytest", "-q"]

class ReportSpec(BaseModel):
    format: str = "json"
    schema_: dict = Field(default_factory=dict, alias="schema")

class Blueprint(BaseModel):
    name: str
    purpose: str
    compute_tier: str = "standard"
    checks: list[Check] = []
    report: ReportSpec | None = None
    workflow: str               # markdown body

class Manifest(BaseModel):
    version: int = 1
    default_engine: str
    compute_tiers: dict[str, dict[str, str]]   # tier -> {engine_name: model_id}
    engines: dict[str, dict]                    # engine_name -> {type, ...}
    blueprints_dir: str = ".alc/blueprints"

class AttemptRecord(BaseModel):
    index: int
    engine_ok: bool
    failed_checks: list[str]

class RunReport(BaseModel):
    blueprint: str
    engine: str
    success: bool
    attempts: list[AttemptRecord]
    scorecard: "Scorecard"
    output_text: str

class Scorecard(BaseModel):
    span: int                   # checks satisfied (proxy for work delivered)
    passes: int                 # engine turns used (attempts)
    streak: int                 # 1 if one-shot (zero repairs) else 0, for this run
    touch: int                  # human interventions (0 in unattended MVP runs)
```

```python
# assurance.py
class AssuranceLoop:
    def __init__(self, engine: Engine, verifier: Verifier, max_repairs: int = 3): ...
    def run(self, request: EngineRequest, checks: list[Check]) -> RunReport: ...
    # attempt 0: engine.run(request); verify; if pass -> success
    # else compose repair directive (original + failure output); repeat up to max_repairs
```

## Policy Gate rules (MVP)

`alc lint` returns violations with severity `error` (blocks `run`) or `warn`.

| Rule | Severity | Rationale |
|---|---|---|
| Blueprint declares ≥ 1 check | `error` | No Assurance Loop ⇒ no guarantee |
| Blueprint has a single `name`/purpose (one class per file) | `error` | Single Mandate |
| Blueprint declares a `report` spec | `warn` | Structured, parseable output |
| Manifest `default_engine` exists in `engines` | `error` | Resolvable execution plane |
| Every Compute Tier maps the referenced engine | `error` | Model resolvable |

## SOLID & KISS mapping

- **SRP** — each module has one job (Intake parses, Policy lints, Verifier checks,
  Assurance loops, Runner composes). Table in `architecture.md`.
- **OCP** — new engines, checks, and report formats are added without editing the core.
- **LSP** — any `Engine` is substitutable behind the Protocol; the Mock proves it.
- **ISP** — the `Engine` contract is three methods; nothing more is demanded of a tool.
- **DIP** — the control plane imports `engine.Engine` (abstraction), never a concrete
  adapter; the registry injects the concrete one at the edge.
- **KISS** — one Blueprint, one loop, two adapters, argparse CLI, two runtime deps
  (`pydantic`, `pyyaml`). No queue, no DB, no daemon in the MVP.

## Milestones

- **M0** — package skeleton + `models.py` + `engine.py` (contract) + Mock adapter.
- **M1** — Intake + Policy Gate + `alc lint` (+ tests).
- **M2** — Verifier + Assurance Loop + Mandate Runner + `alc run --engine mock`
  (+ tests proving repair-on-failure).
- **M3** — Claude Code adapter behind the same contract; `alc run --engine claude-code`.

Acceptance: `uv run alc run chore "<task>" --engine mock` completes, the Scorecard shows
the attempt count, and a Blueprint with a failing check causes a repair attempt — all
without a real model.
