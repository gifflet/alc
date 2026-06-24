# models.py — Pydantic models for the ALC control plane.
# Covers the Operator Layer (Manifest, Blueprint) and run-time records (RunReport, Scorecard).
from __future__ import annotations

from pydantic import BaseModel, Field


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


class Manifest(BaseModel):
    """Root of the Operator Layer — loaded from .alc/manifest.yaml."""

    version: int = 1
    default_engine: str
    compute_tiers: dict[str, dict[str, str]]  # tier -> {engine_name: model_id}
    engines: dict[str, dict]                  # engine_name -> {type, ...}
    blueprints_dir: str = ".alc/blueprints"
    flows_dir: str = ".alc/flows"
    queue_dir: str = ".alc/queue"


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


class FlowStage(BaseModel):
    """One stage in a Flow — references a Blueprint by name."""

    name: str
    blueprint: str             # name of an existing Blueprint
    compute_tier: str | None = None  # optional override of the Blueprint's tier


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
    """

    flow: str
    task: str
    engine: str | None = None
    isolate: bool = True


class TickResult(BaseModel):
    """Gate record produced for one queued task after ``alc tick`` processes it."""

    task_file: str          # original filename stem (e.g. "job1")
    flow: str
    success: bool
    branch: str | None = None   # set when IsolatedWorktree committed changes
    report: FlowReport
