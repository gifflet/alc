# models.py — Pydantic models for the ALC control plane.
# Covers the Operator Layer (Manifest, Blueprint) and run-time records (RunReport, Scorecard).
from __future__ import annotations

from pathlib import Path
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


class ServiceSpec(BaseModel):
    """Declares an app the CORE runs for the duration of a runtime-validation run.

    When a Blueprint opts in (``needs_service``) and the Manifest sets a
    ``service``, ALC — not the agent — starts the app on its allocated port,
    waits for ``health`` to return 200, exposes ``$ALC_BASE_URL`` to the engine
    env, and tears it down after the run. The agent only hits ``$ALC_BASE_URL``.
    """

    start: str                    # shell command that launches the app
    health: str = "/health"       # health path polled until it returns HTTP 200
    ready_timeout_s: int = 30     # seconds to wait for health before giving up


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
    timeout_s: int | None = None  # per-turn engine kill timeout; None -> manifest.default_timeout_s
    # Opt-in per Blueprint: when True AND the Manifest declares a `service`, ALC owns
    # the app lifecycle for this run (starts it on the allocated port, waits for health,
    # exposes $ALC_BASE_URL, tears it down). Default False -> byte-identical to today.
    needs_service: bool = False
    # Descriptive team-metaphor label (prototyper/builder/sweeper/grower/maintainer).
    # ZERO runtime effect — reporting only (copied to RunReport.archetype) and input
    # to the Mix Health work of a later phase. Behavior always lives in a named field,
    # never behind this string (see roadmap-phase-2.md's scope decisions).
    archetype: str | None = None
    # `mode: spike` is the ONE relaxation of the checks gate (roadmap-phase-3.md
    # T1) — a fenced exception, never a second policy language: Policy Gate rule 1
    # drops from error to warn ONLY in this mode; the runner forces isolation,
    # zero repair turns, and forbids commit/auto-merge; RunReport.spike is True and
    # the run is excluded from the Scorecard streak. None (default) -> today's
    # gate untouched, byte-identical.
    mode: Literal["spike"] | None = None
    # Glob patterns (fnmatch, workdir-relative) an Act must never touch. After each
    # attempt, the control plane crosses the paths changed so far against these
    # globs; any hit becomes a synthetic failed check (`protected-paths`) that
    # feeds the same repair addendum as a real check failure (see assurance.py).
    # Empty (default) -> no-op, byte-identical.
    protect: list[str] = []


class ProvisionSpec(BaseModel):
    """Declares one gitignored runtime dependency to provision into a worktree.

    Exactly one of ``link`` / ``copy`` / ``clone`` must be set; its value is a
    path relative to the project root, choosing the isolation/cost trade-off:
      - ``link``: symlink the project-root path in (SHARED across worktrees —
        read-only-safe only; a mutation corrupts siblings).
      - ``copy``: a full, isolated deep copy per worktree.
      - ``clone``: a copy-on-write clone (fast AND isolated), falling back to a
        plain deep copy when the filesystem has no COW support.
    """

    link: str | None = None
    # `copy_`/alias="copy": the YAML key stays `copy`, but the field name avoids
    # shadowing the deprecated BaseModel.copy (the ReportSpec.schema_ precedent).
    copy_: str | None = Field(default=None, alias="copy")
    clone: str | None = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> "ProvisionSpec":
        """Exactly one of link/copy/clone; the path stays inside the project tree."""
        set_count = sum(v is not None for v in (self.link, self.copy_, self.clone))
        if set_count != 1:
            raise ValueError(
                "ProvisionSpec must declare exactly one of 'link', 'copy', or 'clone'."
            )
        parts = Path(self.path).parts
        if Path(self.path).is_absolute() or ".." in parts:
            raise ValueError(
                f"ProvisionSpec path '{self.path}' must be a relative path within the "
                "project (no absolute paths, no '..') — it is provisioned INTO a worktree."
            )
        return self

    @property
    def kind(self) -> str:
        """Return the provisioning mode: 'link', 'copy', or 'clone'."""
        if self.link is not None:
            return "link"
        if self.copy_ is not None:
            return "copy"
        return "clone"

    @property
    def path(self) -> str:
        """Return the project-root-relative path this spec provisions."""
        return self.link or self.copy_ or self.clone  # type: ignore[return-value]


class Manifest(BaseModel):
    """Root of the Operator Layer — loaded from .alc/manifest.yaml."""

    version: int = 1
    default_engine: str
    compute_tiers: dict[str, dict[str, str]]  # tier -> {engine_name: model_id}
    engines: dict[str, dict]                  # engine_name -> {type, ...}
    check_sets: dict[str, list[Check]] = {}   # reusable named check sets a Blueprint may reference
    # Behavioral knobs — defaults equal the former hardcoded values (unset = identical).
    default_timeout_s: int = 1800   # per-turn engine kill timeout when a Blueprint sets none
    plan_retries: int = 2           # corrective retries for a malformed Conductor/plan output
    fanout_concurrency: int = 4     # parallel workers for `alc conduct --parallel`
    plan_tier: str = "standard"     # compute tier for Conductor planning turns
    check_output_chars: int = 4096  # chars captured from a check's output into repair context
    # Per-check wall-clock kill deadline. A hung check (e.g. a test leaving an open
    # handle) would otherwise freeze the whole drain forever; ALC kills it (and its
    # child process group) after this and reports the check as timed out.
    check_timeout_s: int = 600
    bundle_output_chars: int = 1500  # chars of output_text kept in a bundle replay summary
    # Per-task retry cap for the queue drain. 0 = OFF = current behavior: a failed
    # task is re-enqueued with the failure feedback only while qt.retries < this.
    max_task_retries: int = 0
    # WHEN a re-enqueued retry is drained (inert unless max_task_retries > 0):
    #   "immediate" (default) — drained in the SAME drain pass (drain-until-dry,
    #     bounded by max_task_retries), so a retry runs promptly and works on `alc tick`.
    #   "deferred" — drained by the NEXT drain pass (next cycle / next tick).
    retry_strategy: Literal["immediate", "deferred"] = "immediate"
    # When True, ALC calls the engine to generate a Conventional Commits subject
    # from the staged diff for every control-plane commit; the static template is
    # the fallback when generation fails or the engine output is invalid.
    generate_commit_messages: bool = True
    worktree_commit_message: str = "alc: {branch}"  # exit-commit template ({branch} placeholder)
    # Gitignored runtime deps provisioned INTO each worktree before the engine turn
    # (node_modules/.env/data). Empty = today's behavior (a worktree carries only
    # tracked files). Each entry declares a link/copy/clone mode per path.
    worktree_provision: list[ProvisionSpec] = []
    # How many free TCP ports to allocate per worktree run so N parallel dev
    # servers (a full-stack demand runs a frontend AND a backend) don't collide.
    # The ports are injected as ALC_PORT / ALC_PORT_2.. / ALC_PORTS into the
    # engine's env. 0 = OFF = today's behavior (no ports injected -> byte-identical).
    worktree_ports: int = 0
    # The app ALC starts for runtime validation (see ServiceSpec). None = OFF =
    # today's behavior: ALC never owns a service, so runs stay byte-identical.
    service: ServiceSpec | None = None
    blueprints_dir: str = ".alc/blueprints"
    flows_dir: str = ".alc/flows"
    queue_dir: str = ".alc/queue"
    specialists_dir: str = ".alc/specialists"
    primers_dir: str = ".alc/primers"
    prompts_dir: str = ".alc/prompts"
    bundles_dir: str = ".alc/bundles"
    loops_dir: str = ".alc/loops"       # Autonomous Loop definitions/state/ledgers
    runs_dir: str = ".alc/runs"         # Structured per-run event logs (observability)
    variants_dir: str = ".alc/variants"  # Archived `alc explore` variant reports (`compare`/`adopt`)


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


class Diffstat(BaseModel):
    """Line-level summary of a run's git diff — the number that rewards deletion.

    Derived from ``git diff --numstat HEAD`` plus the porcelain status the runner
    already snapshots for ``changed_files``. Absent (None on RunReport) whenever
    it cannot be computed (no git repo, git missing, no commits yet) or there is
    nothing to report — never a reason to fail a run.
    """

    adds: int
    dels: int
    files_deleted: int


class RunReport(BaseModel):
    """Full record of one alc run invocation."""

    blueprint: str
    engine: str
    success: bool
    attempts: list[AttemptRecord]
    scorecard: Scorecard
    output_text: str
    changed_files: list[str] = []  # paths that changed or appeared during this run
    diffstat: Diffstat | None = None  # None -> not computable or nothing changed
    # Cumulative engine Usage across every attempt in this run (None when the
    # engine reported nothing at all). The Autonomous Loop reads this to enforce
    # usd/tokens budgets. Usage is a frozen dataclass; Pydantic serialises it via
    # arbitrary_types_allowed.
    usage: Usage | None = None
    # Copied from Blueprint.archetype — reporting only, same zero-runtime-effect
    # contract as the field it mirrors.
    archetype: str | None = None
    # True when Blueprint.mode == "spike" (roadmap-phase-3.md T1) — the fenced
    # exception to the checks gate. Marks the run so downstream aggregation
    # (Scorecard streak, `alc audit`, …) can tell a spike apart from a real demand.
    spike: bool = False

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


class CommitSpec(BaseModel):
    """Declares a Flow's terminal commit (workdir-scoped, on success only).

    The message is a template: ``{name}`` = flow name, ``{task}`` = flow task
    (first line). The rendered message is passed to git verbatim and MUST NOT
    contain a Co-Authored-By trailer — this is a deterministic control-plane
    commit, not the engine's.
    """

    enabled: bool = True
    message: str = "chore(cycle): {name}"
    # Extra path prefixes to keep out of the terminal commit / revert. ``.alc/`` is
    # ALWAYS protected regardless — these only ADD to it (effective = (".alc/",) + these).
    exclude: list[str] = []


class FlowDefinition(BaseModel):
    """Declares an ordered pipeline of Single-Mandate stages."""

    name: str
    description: str = ""
    stages: list[FlowStage]
    commit: CommitSpec | None = None  # None -> no terminal commit (default, unchanged)


class FlowReport(BaseModel):
    """Full record of one alc flow invocation."""

    flow: str
    engine: str
    success: bool
    stages: list[RunReport]    # one RunReport per executed stage
    scorecard: Scorecard       # aggregate across all stages
    commit_sha: str | None = None  # set when a terminal commit was created on success


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
    # How many times THIS task lineage has already been retried. Legacy task
    # files omit this and default to 0 (backward compat).
    retries: int = 0
    # Root stem this task's retry lineage descends from. None for an original
    # task; a retry carries the root of the whole lineage so every attempt in a
    # retry chain shares ONE root. Legacy files omit it -> None (backward compat).
    retry_of: str | None = None
    # Optional short slug identifying this task so another task may depend on it.
    # Legacy files omit both id and depends_on -> defaults (backward compat).
    id: str | None = None
    # ids of pending tasks this one builds on / shares files with; the waved drain
    # runs it only AFTER each precedent has merged. Empty = no blocking dependency.
    depends_on: list[str] = []

    def unit_name(self) -> str:
        """Return the unit name to dispatch: ``name`` when set, else ``flow``."""
        return self.name if self.name is not None else self.flow


class TickResult(BaseModel):
    """Gate record produced for one queued task after ``alc tick`` processes it."""

    task_file: str          # original filename stem (e.g. "job1")
    flow: str
    success: bool
    branch: str | None = None   # set when IsolatedWorktree committed changes
    # True only when this result's ``branch`` is a SUCCESSFUL committing-demand
    # branch eligible for the post-batch auto-merge (Part D); a non-committing
    # isolate branch stays False and is left for the operator to review.
    auto_merge: bool = False
    # Auto-merge outcome for this result's branch: None = not an auto-merge task
    # (or not yet merged); True = its branch merged into main; False = its branch
    # was LEFT (a conflict). Read by the honest merged/left cycle metric.
    merged: bool | None = None
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


class Impact(BaseModel):
    """Optional evidence-based justification a planner may attach to a plan item.

    ``score`` is an operator-defined numeric scale — ALC does not interpret or
    act on it. ``rationale`` is the free-text evidence behind the score (e.g.
    "12 issue reports this week reference this flow"). Populated by a planner
    with real signal to draw on (e.g. the Grower pack's `listen` Specialist,
    once wired to a `kind: plan` replenish — Phases 4-5); ZERO runtime effect
    today, the same reporting-only contract as ``Blueprint.archetype``
    (roadmap-phase-2.md T12).
    """

    score: float
    rationale: str


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
    # Optional short slug identifying this unit so another unit may depend on it.
    id: str | None = None
    # ids of units in the SAME plan this one builds on / shares files with; it runs
    # only AFTER each precedent has merged. Empty = independent (runs in parallel).
    depends_on: list[str] = []
    # File paths/globs this unit will create or edit. The CORE derives depends_on from
    # touches OVERLAP (serializing demands that share files) so interdependency safety
    # does NOT rely on the planner declaring depends_on. Empty = not declared.
    touches: list[str] = []
    # Optional evidence-based justification (roadmap-phase-2.md T12) — see Impact.
    # ZERO runtime effect; not persisted onto the QueueTask (see conduct.py).
    impact: Impact | None = None

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
    merged: list[str] = []               # parallel run: branches integrated into HEAD
    left: list[str] = []                 # parallel run: branches left for manual resolution


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

    ``kind`` selects the dispatch target:
    - ``specialist``: run a Specialist (Recall -> Act -> Learn); ``ref`` is the
      specialist name and is required.
    - ``conduct``: plan a Conductor goal and enqueue the resulting units; ``ref``
      is not used.
    - ``flow``: run a named Flow directly as the planning step (e.g. a committing
      pm Flow that writes the roadmap and commits it before demand-flows run);
      ``ref`` is the flow name and is required.
    - ``plan``: run a planner Specialist (keeps ROADMAP + Knowledge File), then
      reuse the Conductor's parse + enqueue on the structured plan it returns;
      ``ref`` is the specialist name and is required.
    """

    kind: Literal["specialist", "conduct", "flow", "plan"]
    ref: str | None = None   # specialist/flow name; None allowed for a conduct replenish
    task: str

    @model_validator(mode="after")
    def _ref_required_for_specialist_and_flow(self) -> "Replenish":
        """Enforce that ``ref`` is set when kind is 'specialist', 'flow', or 'plan'."""
        if self.kind in ("specialist", "flow", "plan") and not self.ref:
            raise ValueError(
                f"Replenish with kind='{self.kind}' requires a non-empty 'ref'."
            )
        return self


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
    # Honest auto-merge tally: how many of this cycle's committing-demand branches
    # merged into main vs were LEFT (a conflict). Both default 0 so old ledger
    # lines stay valid and a cycle with no auto-merge branch is byte-identical.
    merged: int = 0
    left: int = 0
    # True when the replenish step's engine turn FAILED (planner Act errored, or the
    # plan was unparseable) — distinct from "replenish produced no work". A failed
    # replenish must NOT trip the no_new_work stop (a transient hiccup, not "done");
    # the failures/max_consecutive backstop bounds repeated failures.
    replenish_failed: bool = False
    progress: bool
    budget_delta: dict[str, float]
    stopped_reason: str | None = None
