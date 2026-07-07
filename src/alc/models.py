# models.py — Pydantic models for the ALC control plane.
# Covers the Operator Layer (Manifest, Blueprint) and run-time records (RunReport, Scorecard).
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Check(BaseModel):
    """A single verification command declared by a Blueprint."""

    name: str
    command: list[str]  # e.g. ["pytest", "-q"]


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
    report: ReportSpec | None = None
    workflow: str  # markdown body parsed from the Blueprint file
    max_repairs: int | None = None  # override AssuranceLoop repair budget; None -> default (3)


class Manifest(BaseModel):
    """Root of the Operator Layer — loaded from .alc/manifest.yaml."""

    version: int = 1
    default_engine: str
    compute_tiers: dict[str, dict[str, str]]  # tier -> {engine_name: model_id}
    engines: dict[str, dict]                  # engine_name -> {type, ...}
    blueprints_dir: str = ".alc/blueprints"
    flows_dir: str = ".alc/flows"
    queue_dir: str = ".alc/queue"
    specialists_dir: str = ".alc/specialists"
    primers_dir: str = ".alc/primers"
    bundles_dir: str = ".alc/bundles"


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


class FlowStage(BaseModel):
    """One stage in a Flow — references a Blueprint by name."""

    name: str
    blueprint: str             # name of an existing Blueprint
    compute_tier: str | None = None  # optional override of the Blueprint's tier
    verify_only: bool = False  # when True: run checks as a pure gate, no engine turn


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
