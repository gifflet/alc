# models.py — Pydantic models for the ALC control plane.
# Covers the Operator Layer (Manifest, Blueprint) and run-time records (RunReport, Scorecard).
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from alc.engine import Usage


class Check(BaseModel):
    """A single verification command declared by a Blueprint.

    Exactly one of ``command`` or ``shell`` must be set:
      - ``command``: an argv list run directly, e.g. ["pytest", "-q"].
      - ``shell``: a shell one-liner run via ``sh -c``, e.g. 'test -z "$(git diff)"'.
    """

    name: str
    command: list[str] | None = None  # e.g. ["pytest", "-q"]
    shell: str | None = None          # e.g. 'test -z "$(git status --porcelain)"'

    @model_validator(mode="after")
    def _exactly_one_form(self) -> "Check":
        """Enforce that exactly one of command/shell is declared (fail fast at intake)."""
        if (self.command is None) == (self.shell is None):
            raise ValueError(
                f"Check '{self.name}' must declare exactly one of 'command' or 'shell'."
            )
        return self


class ReportSpec(BaseModel):
    """Schema declaration for the structured output a Blueprint expects."""

    format: str = "json"
    schema_: dict = Field(default_factory=dict, alias="schema")

    model_config = {"populate_by_name": True}


class Blueprint(BaseModel):
    """Parameterized template for a class of work (chore, bug, feature, …)."""

    name: str
    purpose: str
    compute_tier: str = "standard"
    checks: list[Check] = []
    check_set: str | None = None  # name of a reusable check set declared in the Manifest
    report: ReportSpec | None = None
    workflow: str  # markdown body parsed from the Blueprint file
    max_repairs: int | None = None  # override AssuranceLoop repair budget; None -> default (3)
    permission_mode: str | None = None  # opt-in engine permission mode; None -> engine default


class Manifest(BaseModel):
    """Root of the Operator Layer — loaded from .alc/manifest.yaml."""

    version: int = 1
    default_engine: str
    compute_tiers: dict[str, dict[str, str]]  # tier -> {engine_name: model_id}
    engines: dict[str, dict]                  # engine_name -> {type, ...}
    check_sets: dict[str, list[Check]] = {}   # reusable named check sets a Blueprint may reference
    blueprints_dir: str = ".alc/blueprints"
    flows_dir: str = ".alc/flows"
    queue_dir: str = ".alc/queue"
    specialists_dir: str = ".alc/specialists"
    primers_dir: str = ".alc/primers"
    bundles_dir: str = ".alc/bundles"
    loops_dir: str = ".alc/loops"       # Autonomous Loop definitions/state/ledgers


class AttemptRecord(BaseModel):
    """Record of a single engine turn inside the Assurance Loop."""

    index: int
    engine_ok: bool
    failed_checks: list[str]


class Scorecard(BaseModel):
    """Four health metrics recorded per run — the north-star is Touch -> 0."""

    span: int    # checks satisfied (proxy for work delivered)
    passes: int  # engine turns used
    streak: int  # 1 if one-shot (zero repairs), else 0
    touch: int   # human interventions (always 0 in unattended MVP runs)


class RunReport(BaseModel):
    """Full record of one alc run invocation."""

    blueprint: str
    engine: str
    success: bool
    attempts: list[AttemptRecord]
    scorecard: Scorecard
    output_text: str
    changed_files: list[str] = []  # paths that changed or appeared during this run
    # Cumulative engine Usage across every attempt in this run (None when the
    # engine reported nothing at all). The Autonomous Loop reads this to enforce
    # usd/tokens budgets. Usage is a frozen dataclass; Pydantic serialises it via
    # arbitrary_types_allowed.
    usage: Usage | None = None

    model_config = {"arbitrary_types_allowed": True}


class FlowStage(BaseModel):
    """One stage in a Flow — runs either a Blueprint or a Specialist.

    Exactly one of ``blueprint`` or ``specialist`` must be set. A blueprint stage
    runs a Single Mandate; a specialist stage runs the Specialist's Recall -> Act
    -> Learn cycle (keeping its Knowledge File). A ``verify_only`` stage runs the
    named Blueprint's checks as a pure gate, so it MUST reference a blueprint.
    """

    name: str
    blueprint: str | None = None     # name of an existing Blueprint
    specialist: str | None = None    # name of an existing Specialist
    compute_tier: str | None = None  # optional override of the Blueprint's tier
    verify_only: bool = False  # when True: run checks as a pure gate, no engine turn

    @model_validator(mode="after")
    def _exactly_one_ref(self) -> "FlowStage":
        """Enforce exactly one of blueprint/specialist; verify_only needs a blueprint."""
        if (self.blueprint is None) == (self.specialist is None):
            raise ValueError(
                f"FlowStage '{self.name}' must set exactly one of "
                "'blueprint' or 'specialist'."
            )
        if self.verify_only and self.specialist is not None:
            raise ValueError(
                f"FlowStage '{self.name}' is verify_only and must reference a "
                "'blueprint' (it runs that blueprint's checks), not a 'specialist'."
            )
        return self


class FlowDefinition(BaseModel):
    """Declares an ordered pipeline of Single-Mandate stages."""

    name: str
    description: str = ""
    stages: list[FlowStage]


class FlowReport(BaseModel):
    """Full record of one alc flow invocation."""

    flow: str
    engine: str
    success: bool
    stages: list[RunReport]    # one RunReport per executed stage
    scorecard: Scorecard       # aggregate across all stages


# ---------------------------------------------------------------------------
# Unattended Mode (Source / Trigger / Sandbox / Gate)
# ---------------------------------------------------------------------------


class QueueTask(BaseModel):
    """One entry in the task queue (the Source for Unattended Mode).

    Stored as a YAML file under queue_dir. The Trigger (``alc tick``) reads
    and drains these files; each is archived to done/ after processing.

    Legacy files that only set ``flow:`` keep working: when ``name`` is None and
    ``kind`` is "flow", the ``flow`` field is treated as the unit name.
    """

    flow: str = ""
    task: str
    engine: str | None = None
    isolate: bool = True
    kind: Literal["flow", "specialist"] = "flow"
    name: str | None = None

    def unit_name(self) -> str:
        """Return the unit name to dispatch: ``name`` when set, else ``flow``."""
        return self.name if self.name is not None else self.flow


class TickResult(BaseModel):
    """Gate record produced for one queued task after ``alc tick`` processes it."""

    task_file: str          # original filename stem (e.g. "job1")
    flow: str
    success: bool
    branch: str | None = None   # set when IsolatedWorktree committed changes
    report: FlowReport


# ---------------------------------------------------------------------------
# Concurrent fan-out (run isolated units in parallel)
# ---------------------------------------------------------------------------


class UnitResult(BaseModel):
    """Outcome of one fan-out unit — a Flow, Blueprint, or Specialist run in isolation.

    Exactly one of ``run_report`` / ``flow_report`` / ``specialist_report`` is
    populated on success, matching ``kind``; on failure all are None and
    ``error`` holds the message.
    """

    kind: str                              # "flow", "blueprint", or "specialist"
    name: str                              # unit name (used for the worktree label)
    task: str
    success: bool
    branch: str | None = None              # set when the IsolatedWorktree committed changes
    run_report: RunReport | None = None    # populated when kind == "blueprint"
    flow_report: FlowReport | None = None  # populated when kind == "flow"
    specialist_report: "SpecialistReport | None" = None  # populated when kind == "specialist"
    error: str | None = None               # populated when the unit raised


class FanoutReport(BaseModel):
    """Aggregate record of one fan-out invocation, preserving input order."""

    units: list[UnitResult]
    success: bool


# ---------------------------------------------------------------------------
# Conductor (single-interface orchestrator)
# ---------------------------------------------------------------------------


class PlannedUnit(BaseModel):
    """One (kind, name, task) triple produced by the Conductor's planning turn.

    ``kind`` selects the dispatch target: a Flow or a Specialist. ``name`` is
    validated against the catalog. ``task`` is the free-text task for that unit.

    Legacy constructor shape ``PlannedUnit(flow="ship", task="x")`` (no kind/name)
    is accepted via the before-validator and mapped to kind="flow", name=<flow value>.
    This keeps the ``PlannedFlow`` alias constructible with keyword argument ``flow=``.
    """

    kind: Literal["flow", "specialist"]
    name: str          # validated against the catalog (Flow or Specialist name)
    task: str

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_flow_shape(cls, values: object) -> object:
        """Map legacy ``{"flow": X, ...}`` input to ``{"kind": "flow", "name": X, ...}``.

        Only applied when the input is a dict that has ``flow`` but lacks ``kind``
        and ``name``.  All other shapes pass through unchanged.
        """
        if isinstance(values, dict) and "flow" in values and "kind" not in values and "name" not in values:
            values = dict(values)   # avoid mutating caller's dict
            values["kind"] = "flow"
            values["name"] = values.pop("flow")
        return values

    @property
    def flow(self) -> str:
        """Back-compat accessor: the unit name (historically ``item.flow``)."""
        return self.name


# Back-compat alias: earlier code/tests referred to plan items as PlannedFlow.
PlannedFlow = PlannedUnit


class ConductorPlan(BaseModel):
    """Structured plan returned by the Conductor: an ordered list of PlannedUnit items."""

    items: list[PlannedUnit]


class ConductReport(BaseModel):
    """Full record of one ``alc conduct`` invocation."""

    goal: str
    mode: str                           # "run" or "enqueue"
    plan: ConductorPlan
    flow_reports: list[FlowReport] = []  # populated for flow dispatches (serial run mode)
    units: list[UnitResult] = []         # populated by parallel dispatch
    enqueued_files: list[str] = []       # populated in enqueue mode
    success: bool | None = None          # overall run outcome (None in enqueue mode)


# ---------------------------------------------------------------------------
# Specialists (Recall -> Act -> Learn)
# ---------------------------------------------------------------------------


class Specialist(BaseModel):
    """Declares an agent tied to one area of the codebase.

    The Specialist keeps a Knowledge File (a working model of its area) and
    self-tunes it via the Recall -> Act -> Learn cycle.
    """

    name: str
    area: str = ""                  # human description of the area this Specialist covers
    blueprint: str                  # name of the Blueprint used for the Act step
    knowledge_path: str             # path to the Knowledge File, relative to the project root


class SpecialistReport(BaseModel):
    """Full record of one ``alc specialist`` invocation."""

    specialist: str
    act: RunReport
    knowledge_updated: bool


# Resolve UnitResult's forward reference to SpecialistReport (defined above).
UnitResult.model_rebuild()


# ---------------------------------------------------------------------------
# Autonomous Loop (plan -> drain -> check stop -> repeat, driven by cron)
# ---------------------------------------------------------------------------


class Replenish(BaseModel):
    """The replenish (planning) step run at the start of each Mode A cycle.

    ``kind`` selects the dispatch target: a Specialist run or a Conductor goal.
    NOTE: flow-replenish is NOT part of v1 — a Flow's enqueue semantics under
    the loop are unclear, so it is deliberately trimmed here.
    """

    kind: Literal["specialist", "conduct"]
    ref: str | None = None   # specialist name; None allowed for a conduct replenish
    task: str


class LoopBudget(BaseModel):
    """A finer, best-effort cap on cumulative usage across cycles."""

    unit: Literal["engine_calls", "usd", "tokens"]
    max: float

    @field_validator("max")
    @classmethod
    def _max_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("LoopBudget.max must be > 0.")
        return v


class LoopStop(BaseModel):
    """Stop conditions for a loop. ``max_cycles`` is the mandatory hard backstop."""

    max_cycles: int
    on_no_new_work: bool = True
    budget: LoopBudget | None = None

    @field_validator("max_cycles")
    @classmethod
    def _max_cycles_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("LoopStop.max_cycles must be > 0.")
        return v


class LoopFailure(BaseModel):
    """Failure policy: stop after N consecutive no-progress cycles."""

    max_consecutive: int = 5

    @field_validator("max_consecutive")
    @classmethod
    def _max_consecutive_valid(cls, v: int) -> int:
        if v < 1:
            raise ValueError("LoopFailure.max_consecutive must be >= 1.")
        return v


class LoopDrain(BaseModel):
    """Drain options: how many queued tasks to process per cycle."""

    concurrency: int = 1

    @field_validator("concurrency")
    @classmethod
    def _concurrency_valid(cls, v: int) -> int:
        if v < 1:
            raise ValueError("LoopDrain.concurrency must be >= 1.")
        return v


class LoopDefinition(BaseModel):
    """Declares one Autonomous Loop — loaded from .alc/loops/<name>.yaml."""

    name: str
    replenish: Replenish | None = None   # None -> Mode B (drain-only)
    stop: LoopStop
    failure: LoopFailure = LoopFailure()
    drain: LoopDrain = LoopDrain()


class LoopState(BaseModel):
    """Persisted loop state — .alc/loops/<name>.state.json.

    Status transitions: pending -> running -> stopped.
    A loop is "pending" when it has never completed a cycle. Once at least one
    cycle finishes without triggering a stop condition the status becomes
    "running". "stopped" is terminal until an explicit --reset.
    """

    name: str
    status: Literal["pending", "running", "stopped"] = "pending"
    cycle: int = 0
    consecutive_no_progress: int = 0
    # Cumulative usage per unit; keys among engine_calls / usd / tokens.
    budget_used: dict[str, float] = {}
    stopped_reason: str | None = None


class CycleRecord(BaseModel):
    """One line of the per-cycle ledger — .alc/loops/<name>.ledger.jsonl."""

    cycle: int
    replenished: int
    drained: int
    succeeded: int
    failed: int
    progress: bool
    budget_delta: dict[str, float]
    stopped_reason: str | None = None
