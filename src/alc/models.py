# models.py — Pydantic models for the ALC control plane.
# Covers the Operator Layer (Manifest, Blueprint) and run-time records (RunReport, Scorecard).
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from alc.engine import Usage


class Check(BaseModel):
    """A single verification command declared by a Blueprint.

    Exactly one of ``command``, ``shell``, or ``metric`` must be set:
      - ``command``: an argv list run directly, e.g. ["pytest", "-q"].
      - ``shell``: a shell one-liner run via ``sh -c``, e.g. 'test -z "$(git diff)"'.
      - ``metric``: a command (argv list or shell one-liner, same shape rules as
        ``command``/``shell``) that prints a SINGLE NUMBER on stdout. The engine
        never judges this number — the Verifier compares it against the most
        recent measurement recorded in the project's metric ledger (see
        ``alc.metrics``, roadmap-phase-4.md T2) and decides pass/fail itself.
        ``direction`` says which way is better; ``tolerance_pct`` absorbs
        benchmark noise. A metric check with no recorded history yet always
        PASSES (its value is simply recorded as the first baseline).
    """

    name: str
    command: list[str] | None = None  # e.g. ["pytest", "-q"]
    shell: str | None = None          # e.g. 'test -z "$(git status --porcelain)"'
    metric: list[str] | str | None = None  # e.g. ["scripts/bench.py"] or "cat size.txt"
    # Which way is "better" for `metric`'s printed number. Required whenever
    # `metric` is set — enforced as a Policy Gate ERROR (policy.py), not here:
    # see roadmap-phase-4.md T1 for why this stays a lint-time diagnostic
    # (Blueprint context in the message) rather than a pydantic crash at intake.
    direction: Literal["lower_is_better", "higher_is_better"] | None = None
    # Percent slack around the baseline before a metric regression fails the
    # run — benchmarks are noisy; 0.0 (default) means "no slack at all".
    tolerance_pct: float = 0.0
    # How many times the Verifier re-runs THIS check after a FAILING attempt,
    # before the control plane spends a repair engine turn on it (roadmap-phase-3.md
    # T11) — seconds against a model call. 0 (default) = no rerun, byte-identical.
    flaky: int = 0

    @model_validator(mode="after")
    def _exactly_one_form(self) -> "Check":
        """Enforce that exactly one of command/shell/metric is declared (fail fast at intake)."""
        if sum(f is not None for f in (self.command, self.shell, self.metric)) != 1:
            raise ValueError(
                f"Check '{self.name}' must declare exactly one of "
                "'command', 'shell', or 'metric'."
            )
        return self

    @field_validator("flaky")
    @classmethod
    def _flaky_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Check.flaky must be >= 0.")
        return v

    @field_validator("tolerance_pct")
    @classmethod
    def _tolerance_pct_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Check.tolerance_pct must be >= 0.")
        return v


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
    # Advisory-only signal that this mandate is expected to REDUCE the codebase
    # (roadmap-phase-4.md T4) — the first consumer of `RunReport.diffstat`
    # (Phase 2), alongside the net-lines column on `alc runs list`. When set and
    # the run's diffstat nets positive (the codebase grew instead of shrank),
    # the control plane records a warn on `RunReport.warnings` and the run log —
    # it NEVER fails the run: simplifying sometimes means growing before
    # shrinking. None (default) -> no-op, byte-identical.
    expect: Literal["shrink"] | None = None


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


class NotifyConfig(BaseModel):
    """Push channel for unattended failure (roadmap-phase-3.md T12).

    Each field is either a command (argv list, run with the JSON payload on its
    stdin) or a webhook URL (a str, POSTed the JSON payload) — no per-service
    adapters; the operator already knows how to fan a command/URL out to Slack,
    email, or a pager. None (default) -> that hook is off, byte-identical to
    today. Fired by ``alc.notify.fire`` at the point each failure is already
    detected (``queue.py``, ``loop.py``, ``merge.py``); delivery never raises.
    """

    on_task_failed: list[str] | str | None = None
    on_loop_stopped: list[str] | str | None = None
    on_budget_exceeded: list[str] | str | None = None
    on_merge_conflict: list[str] | str | None = None


class DeliverySpec(BaseModel):
    """How `alc land` hands an already-landed branch to the remote (roadmap-phase-4.md T8).

    The local cherry-pick merge (``merge.py``) is the actual work landing —
    entirely local, and already the whole guarantee `alc land` gave before this
    existed. This is the LAST MILE on top of it, never the work itself:
      - ``mode: "local"`` (default): unchanged — `alc land` never pushes or
        opens a PR.
      - ``mode: "push"``: after a clean local land, push the current branch to
        ``remote``.
      - ``mode: "pr"``: push, then open a pull request (via the ``gh`` CLI)
        from the current branch against ``base``, for a human to review before
        it counts as delivered — the review gate the product deliberately keeps.

    ``mode`` is the manifest-declared DEFAULT; `alc land`'s ``--push``/``--pr``
    flags override it for one invocation (same override relationship as
    ``manifest.plan_tier`` and ``--tier``). A push failure or a missing ``gh``
    binary NEVER fails `alc land` — see ``alc.delivery`` (mirrors ``commit.py``'s
    never-raise contract): the local landing already succeeded.
    """

    mode: Literal["local", "push", "pr"] = "local"
    remote: str = "origin"
    base: str = "main"


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
    # Per-project JSONL ledger of metric-check measurements (roadmap-phase-4.md
    # T2) — one MetricRecord per line, appended by the Verifier. `alc metrics`
    # reads it back into a time series.
    metrics_dir: str = ".alc/metrics"
    # Declarative quarantine (roadmap-phase-3.md T11): a check named here still RUNS
    # every attempt, but a failure of it can never fail the run — the AssuranceLoop
    # excludes it from the checks that block success/trigger repair. It stays fully
    # VISIBLE (recorded as failed in the run log and the report) so quarantine is
    # never invisible debt, and the Policy Gate emits a PERMANENT warn for as long
    # as it is listed. Empty (default) -> no-op, byte-identical.
    quarantined_checks: list[str] = []
    # Push notifications for unattended failure (roadmap-phase-3.md T12): a command
    # or webhook fired where the control plane already detects the failure. None
    # (default) -> notify off, byte-identical to today.
    notify: NotifyConfig | None = None
    # Declares which growth stage the product is in (roadmap-phase-4.md T5) — the
    # essay's mix of archetypes made control-plane data. `alc.stagepolicy` compares
    # the archetypes actually hired/run against the target mix for this stage.
    # Every rule this enables is advisory (warn only — see
    # `stagepolicy.lint_stage`); the stage NEVER changes how a mandate executes,
    # only what gets warned/reported/scaffolded. None (default) -> no rule ever
    # fires, byte-identical to today (`alc init` writes no `stage`).
    stage: Literal["pre-pmf", "growth", "strong-pmf"] | None = None
    # Overrides `stagepolicy.STAGE_MIX[stage]` wholesale: {"core": [...],
    # "secondary": [...]} of archetype names. The default mix is a health
    # heuristic, not a law of physics — this is the escape hatch so it never
    # hardens into dogma. Validated (shape + archetype names) by
    # `stagepolicy.lint_stage`, advisory/error only — never crashes at parse
    # time. None (default) -> the built-in default mix for `stage`.
    stage_mix: dict[str, list[str]] | None = None
    # How `alc land` hands an already-landed branch to the remote
    # (roadmap-phase-4.md T8) — see DeliverySpec. None (default) -> DeliverySpec's
    # own default (mode: local), so `alc land` with no `--push`/`--pr` flag stays
    # byte-identical to before this field existed.
    delivery: DeliverySpec | None = None


class MetricRecord(BaseModel):
    """One line of the per-project metric ledger (``manifest.metrics_dir``).

    Written by the Verifier every time it runs a ``metric`` check (roadmap-phase-4.md
    T2), following the shape of ``loop.CycleRecord``/``loop.append_ledger``: one
    JSON object per line, appended best-effort. ``run`` is the label the caller
    supplied to the Verifier (the Blueprint name in every production call site)
    — free-text context for tracing a measurement back to what produced it, not
    interpreted by anything that reads the ledger.
    """

    check: str
    value: float
    ts: float   # epoch seconds
    run: str
    # Whether this measurement was ACCEPTED by the Verifier's tolerance check
    # at record time. Every measurement is recorded regardless — an honest
    # history — but only an ACCEPTED one may ever become the next baseline
    # (alc.metrics.latest_accepted_measurement): a value that itself failed
    # must never move the goalpost, or the gate ratchets itself open one
    # regression at a time. Defaults True so a record from before this field
    # existed still parses (the conservative "was fine" reading).
    passed: bool = True


class CheckOutcome(BaseModel):
    """Full per-check record within one AttemptRecord (roadmap-phase-3.md T9).

    Additive alongside ``AttemptRecord.failed_checks`` (kept working exactly as
    before, for its existing readers): EVERY check run in the attempt appears
    here, pass or fail, with its duration and exit code — the data `alc checks
    history` and a quarantine both need. An old report parses fine with this
    list simply empty (default ``[]``).
    """

    name: str
    passed: bool
    duration_s: float = 0.0
    exit_code: int | None = None
    timed_out: bool = False
    # True when this check is named in manifest.quarantined_checks — a failure
    # here is recorded (passed=False) but was NOT allowed to fail the run.
    quarantined: bool = False


class AttemptRecord(BaseModel):
    """Record of a single engine turn inside the Assurance Loop."""

    index: int
    engine_ok: bool
    failed_checks: list[str]
    # Every check's full outcome for this attempt (roadmap-phase-3.md T9) — additive,
    # default [] so an old report (with no `checks` key) still parses. `failed_checks`
    # above is unchanged and keeps working exactly as it does today.
    checks: list[CheckOutcome] = []


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
    # Advisory notes the control plane found about this run — human-readable,
    # NEVER a reason to fail it (roadmap-phase-4.md T4). Currently populated
    # only by `Blueprint.expect == "shrink"` finishing net-positive; a plain
    # list (rather than one field per rule) so a later advisory rule has
    # somewhere to land without a new RunReport field each time. Empty
    # (default) -> byte-identical to before this field existed.
    warnings: list[str] = []

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
    # Tie-breaker WITHIN a topological wave: the drain orders each wave by
    # (-priority, filename), higher first. Dependency ordering stays authoritative
    # — priority can never move a task ahead of one it depends on, it only decides
    # who goes first among tasks that are ALREADY ready. Default 0 = today's
    # filename-only ordering (byte-identical).
    priority: int = 0

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
    # Advisory stage-mix findings (roadmap-phase-4.md T7b) — populated only when
    # manifest.stage is declared; NEVER a reason to fail this report on its own
    # (--strict-stage instead refuses before dispatch — see conduct.py). Empty
    # (default) -> byte-identical to before this field existed, same contract as
    # RunReport.warnings.
    warnings: list[str] = []


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
