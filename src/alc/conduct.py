# conduct.py — Conductor: single-interface orchestrator that turns a goal into a
# structured plan of units (each a Flow or a Specialist), then either runs them
# now or enqueues them for alc tick (Unattended Mode). With --parallel the plan
# is dispatched concurrently, each unit in its own isolated git worktree.
#
# DIP seam: the Engine is injected by the caller; no concrete adapter is imported here.
from __future__ import annotations

import json
import sys
import uuid
from fnmatch import fnmatch
from pathlib import Path

import yaml

from alc.engine import Engine, EngineRequest
from alc.events import bind_run_log, new_run_log_path
from alc.flow import FlowRunner
from alc.intake import (
    load_all_flows,
    load_all_specialists,
    load_flow,
    load_specialist,
)
from alc.models import (
    ConductorPlan,
    ConductReport,
    FlowReport,
    Manifest,
    PlannedUnit,
)
from alc.prompts import (
    _CONDUCTOR_DIRECTIVE_TEMPLATE,
    _CORRECTIVE_SUFFIX,
    resolve_prompt,
)
from alc.textutil import slugify as _slugify


# ---------------------------------------------------------------------------
# Pure parsing helpers
# ---------------------------------------------------------------------------


def parse_plan(
    output_text: str,
    available_flows: set[str],
    available_specialists: set[str] | None = None,
) -> ConductorPlan:
    """Parse the Conductor's raw output into a validated ConductorPlan.

    Tries strict JSON first; if that fails, extracts the substring between the
    outermost ``[`` and ``]`` (handles markdown code fences and surrounding prose).

    Accepts two item shapes:
      - ``{"kind": "flow"|"specialist", "name": ..., "task": ...}`` (current)
      - ``{"flow": ..., "task": ...}`` (legacy — parsed as a flow unit)

    Args:
        output_text: Raw text produced by the planning engine turn.
        available_flows: Set of flow names declared in the Operator Layer catalog.
        available_specialists: Set of specialist names in the catalog (empty when None).

    Returns:
        ConductorPlan with one PlannedUnit per item.

    Raises:
        ValueError: If the text is not parseable JSON, wrong shape, or references
                    a name that is not in the matching catalog set.
    """
    specialists = available_specialists or set()

    # First attempt: the whole text is valid JSON.
    raw: object = None
    try:
        raw = json.loads(output_text)
    except json.JSONDecodeError:
        # Second attempt: extract the outermost JSON array from the text.
        start = output_text.find("[")
        end = output_text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(
                f"No JSON array found in Conductor output. Output was:\n{output_text!r}"
            )
        try:
            raw = json.loads(output_text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Malformed JSON in Conductor output: {exc}. Output was:\n{output_text!r}"
            ) from exc

    if not isinstance(raw, list):
        raise ValueError(
            f"Conductor output must be a JSON array; got {type(raw).__name__}. "
            f"Output was:\n{output_text!r}"
        )

    items: list[PlannedUnit] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(
                f"Item {i} in Conductor plan is not an object: {entry!r}"
            )

        # Resolve kind/name from either the current shape or the legacy shape.
        # The legacy shape {"flow": X, "task": Y} is also accepted by PlannedUnit's
        # model_validator, but we need kind/name here for catalog validation first.
        if "flow" in entry and "kind" not in entry:
            # Legacy shape: {"flow": X, "task": Y}
            if "task" not in entry:
                raise ValueError(
                    f"Item {i} in Conductor plan is missing 'task' key: {entry!r}"
                )
            kind: str = "flow"
            name: str = entry["flow"]
        else:
            if "kind" not in entry or "name" not in entry or "task" not in entry:
                raise ValueError(
                    f"Item {i} in Conductor plan is missing 'kind', 'name', or 'task' "
                    f"keys: {entry!r}"
                )
            kind = entry["kind"]
            name = entry["name"]

        if kind == "flow":
            if name not in available_flows:
                raise ValueError(
                    f"Item {i} references unknown flow '{name}'. "
                    f"Available flows: {sorted(available_flows)}"
                )
        elif kind == "specialist":
            if name not in specialists:
                raise ValueError(
                    f"Item {i} references unknown specialist '{name}'. "
                    f"Available specialists: {sorted(specialists)}"
                )
        else:
            raise ValueError(
                f"Item {i} has invalid kind '{kind}'; expected 'flow' or 'specialist'."
            )

        # Optional dependency wiring: `id` names this unit, `depends_on` lists the
        # ids of same-plan units it builds on / shares files with. Validated below.
        unit_id = entry.get("id")
        if unit_id is not None and not isinstance(unit_id, str):
            raise ValueError(
                f"Item {i} 'id' must be a string; got {type(unit_id).__name__}."
            )
        depends_on = entry.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(
            isinstance(d, str) for d in depends_on
        ):
            raise ValueError(
                f"Item {i} 'depends_on' must be a list of strings; got {depends_on!r}."
            )
        # `touches` — files this unit will edit; the core derives depends_on from their
        # overlap (derive_dependencies). Optional at parse time (mandated by the
        # plan-contract prompt); a legacy plan without it parses unchanged.
        touches = entry.get("touches", [])
        if not isinstance(touches, list) or not all(isinstance(t, str) for t in touches):
            raise ValueError(
                f"Item {i} 'touches' must be a list of strings; got {touches!r}."
            )

        # Optional evidence-based justification (roadmap-phase-2.md T12) — the
        # `plan-contract` prompt documents this to a planner with real signal to
        # draw on. ZERO runtime effect; validated up front like touches/depends_on
        # so a malformed entry fails with a clear "Item N" message, not a raw
        # pydantic error.
        impact = entry.get("impact")
        if impact is not None and (
            not isinstance(impact, dict)
            or not isinstance(impact.get("score"), (int, float))
            or not isinstance(impact.get("rationale"), str)
        ):
            raise ValueError(
                f"Item {i} 'impact' must be an object with a numeric 'score' and a "
                f"string 'rationale'; got {impact!r}."
            )

        # Build via model_validate so the before-validator normalises any
        # legacy shape; the catalog check above has already run by this point.
        item_data: dict = {"kind": kind, "name": name, "task": str(entry["task"])}
        if unit_id is not None:
            item_data["id"] = unit_id
        if depends_on:
            item_data["depends_on"] = depends_on
        if touches:
            item_data["touches"] = touches
        if impact is not None:
            item_data["impact"] = impact
        items.append(PlannedUnit.model_validate(item_data))

    # Every referenced dependency id must match some item's id in the SAME plan;
    # dependencies are declared within one plan (no cross-plan / unknown ids).
    known_ids = {item.id for item in items if item.id is not None}
    for i, item in enumerate(items):
        for dep in item.depends_on:
            if dep not in known_ids:
                raise ValueError(
                    f"Item {i} depends_on unknown id '{dep}'. "
                    f"Known ids in this plan: {sorted(known_ids)}"
                )

    return ConductorPlan(items=items)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def build_catalog(
    manifest: Manifest, operator_layer: Path
) -> tuple[str, set[str], set[str]]:
    """Build the Conductor catalog from all available Flows and Specialists.

    Args:
        manifest: Loaded Manifest.
        operator_layer: Path to the ``.alc/`` directory.

    Returns:
        Tuple of (catalog_text, available_flows, available_specialists): the
        human-readable catalog listing and the two name sets used for validation.
    """
    flows = load_all_flows(manifest, operator_layer)
    specialists = load_all_specialists(manifest, operator_layer)
    # A FlowStage sets exactly one of blueprint/specialist, so render whichever
    # is present (a specialist stage has blueprint=None).
    catalog_lines = [
        f"- {f.name} (flow): {f.description} "
        f"(stages: {', '.join(s.blueprint or s.specialist for s in f.stages)})"
        for f in flows
    ]
    catalog_lines += [f"- {s.name} (specialist): {s.area}" for s in specialists]
    catalog_text = "\n".join(catalog_lines) if catalog_lines else "(no targets available)"
    available_flows: set[str] = {f.name for f in flows}
    available_specialists: set[str] = {s.name for s in specialists}
    return catalog_text, available_flows, available_specialists


# ---------------------------------------------------------------------------
# Planning turn
# ---------------------------------------------------------------------------


def plan_flows(
    engine: Engine,
    model: str | None,
    goal: str,
    catalog_text: str,
    available_flows: set[str],
    available_specialists: set[str] | None = None,
    max_retries: int = 2,
    directive_template: str = _CONDUCTOR_DIRECTIVE_TEMPLATE,
    corrective_template: str = _CORRECTIVE_SUFFIX,
) -> ConductorPlan:
    """Ask the engine to produce a ConductorPlan for the given goal.

    Composes a Conductor directive, calls the engine, and parses the output.
    On parse failure, appends a corrective instruction and retries up to
    ``max_retries`` times before raising.

    Args:
        engine: Injected Engine instance (DIP — no concrete import here).
        model: Concrete model id resolved from the Compute Tier (may be None).
        goal: The operator's high-level goal string.
        catalog_text: Human-readable list of available Flows and Specialists.
        available_flows: Set of valid flow names for validation.
        available_specialists: Set of valid specialist names for validation.
        max_retries: Number of corrective retries after an initial parse failure.
        directive_template: The Conductor directive template. Defaults to the
            embedded ``conductor`` prompt; ``conduct()`` passes the resolved
            override (if any) so an operator can replace it.
        corrective_template: The corrective-retry suffix template. Defaults to the
            embedded ``corrective`` prompt; ``conduct()`` passes the resolved
            override when present.

    Returns:
        Validated ConductorPlan.

    Raises:
        ValueError: If all attempts (1 + max_retries) are exhausted without a
                    valid plan.
    """
    directive = directive_template.format(
        goal=goal,
        catalog_text=catalog_text,
    )

    last_err: ValueError | None = None
    for attempt in range(1 + max_retries):
        if attempt > 0 and last_err is not None:
            directive += corrective_template.format(err=str(last_err))

        request = EngineRequest(
            directive=directive,
            workdir=Path.cwd(),
            model=model,
        )
        result = engine.run(request)
        try:
            return parse_plan(result.output_text, available_flows, available_specialists)
        except ValueError as exc:
            last_err = exc

    # Exhausted all retries.
    raise ValueError(
        f"Conductor could not produce a valid plan after {1 + max_retries} attempt(s). "
        f"Last error: {last_err}"
    )


def finalize_plan(
    engine: Engine,
    model: str | None,
    first_output: str,
    available_flows: set[str],
    available_specialists: set[str],
    max_retries: int = 2,
    corrective_template: str = _CORRECTIVE_SUFFIX,
    usage_sink: dict | None = None,
) -> ConductorPlan:
    """Parse a planner's first output, self-healing a malformed one via cheap retries.

    Tries to parse ``first_output`` directly. On ``ValueError``, runs up to
    ``max_retries`` FORMAT-ONLY corrective engine turns — each turn re-feeds the prior
    bad output plus the corrective instruction and re-parses. A corrective turn is a
    pure reformat: no checks, knowledge, or roadmap re-run, so it is cheap and does not
    disturb the already-committed roadmap.

    Args:
        engine: Injected Engine instance (DIP — no concrete import here).
        model: Concrete model id resolved from the Compute Tier (may be None).
        first_output: The planner Specialist's raw Act output.
        available_flows: Set of valid flow names for validation.
        available_specialists: Set of valid specialist names for validation.
        max_retries: Number of corrective retries after the initial parse failure.
        corrective_template: The corrective-retry suffix template. Defaults to the
            embedded ``corrective`` prompt; the plan branch passes the resolved
            override when present.
        usage_sink: Optional running budget delta. When not None, each corrective
            ``engine.run`` folds its cost into it — ``engine_calls`` incremented per
            turn, and ``usd``/``tokens`` accumulated from the EngineResult's Usage —
            the same shape ``loop._report_usage`` uses. Default None leaves it
            untouched (behavior identical to before).

    Returns:
        Validated ConductorPlan.

    Raises:
        ValueError: If the first output and every corrective retry fail to parse.
    """
    try:
        return parse_plan(first_output, available_flows, available_specialists)
    except ValueError as exc:
        last_err: ValueError = exc

    prior_output = first_output
    for _ in range(max_retries):
        directive = prior_output + corrective_template.format(err=str(last_err))
        result = engine.run(
            EngineRequest(directive=directive, workdir=Path.cwd(), model=model)
        )
        # A corrective turn is a real engine call — count it (and its Usage) against
        # the loop's budget so these turns are not silently uncounted.
        if usage_sink is not None:
            usage_sink["engine_calls"] = usage_sink.get("engine_calls", 0) + 1
            usage = getattr(result, "usage", None)
            if usage is not None:
                if usage.cost_usd is not None:
                    usage_sink["usd"] = usage_sink.get("usd", 0.0) + usage.cost_usd
                tokens = (usage.input_tokens or 0) + (usage.output_tokens or 0)
                usage_sink["tokens"] = usage_sink.get("tokens", 0.0) + tokens
        if not result.ok:
            # The engine itself failed (API error, quota, timeout) — a reformat can't
            # succeed against a down engine; stop retrying rather than hammer it.
            raise ValueError(
                f"engine failed during a corrective plan retry: {result.output_text}"
            )
        try:
            return parse_plan(
                result.output_text, available_flows, available_specialists
            )
        except ValueError as exc:
            last_err = exc
            prior_output = result.output_text

    raise ValueError(
        f"Plan could not be parsed after {1 + max_retries} attempt(s). "
        f"Last error: {last_err}"
    )


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------


def dispatch_now(
    plan: ConductorPlan,
    manifest: Manifest,
    operator_layer: Path,
    engine_override: str | None = None,
) -> list[FlowReport]:
    """Run each PlannedUnit immediately, routing by kind (serial).

    Flow units run via FlowRunner. Specialist units run via run_specialist; their
    Act outcome is wrapped into a FlowReport (via queue.py's _specialist_flow_report)
    so every unit — flow or specialist — contributes to the returned list and to
    the overall success computation.

    Args:
        plan: The validated ConductorPlan.
        manifest: Loaded Manifest (provides engine config, dirs).
        operator_layer: Path to the ``.alc/`` directory.
        engine_override: Optional engine name to use instead of the manifest default.

    Returns:
        List of FlowReport, one per plan item (in order): a flow's own report or a
        specialist's Act outcome wrapped as a FlowReport.
    """
    from alc.queue import _specialist_flow_report
    from alc.specialist import run_specialist

    flows_dir = operator_layer.parent / manifest.flows_dir
    specialists_dir = operator_layer.parent / manifest.specialists_dir
    runs_dir = operator_layer.parent / manifest.runs_dir
    runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
    reports: list[FlowReport] = []
    for item in plan.items:
        # Bind ONE run log per unit — parity with the parallel path (fanout.run_unit),
        # so a serial conduct dispatch is just as observable as a concurrent one.
        run_log = new_run_log_path(runs_dir, "unit", f"{item.name} {item.task}")
        with bind_run_log(run_log):
            if item.kind == "specialist":
                specialist = load_specialist(specialists_dir, item.name)
                specialist_report = run_specialist(
                    manifest=manifest,
                    operator_layer=operator_layer,
                    specialist=specialist,
                    task=item.task,
                    engine_override=engine_override,
                )
                engine_name = engine_override or manifest.default_engine
                reports.append(
                    _specialist_flow_report(
                        item.name, engine_name, specialist_report.act
                    )
                )
                continue
            flow = load_flow(flows_dir, item.name)
            report = runner.run(flow, item.task, engine_override=engine_override)
            reports.append(report)
    return reports


def _touch_overlap(a: list[str], b: list[str]) -> bool:
    """True if two touch-sets could edit a common path (conservative glob match)."""
    for pa in a:
        for pb in b:
            if pa == pb or fnmatch(pa, pb) or fnmatch(pb, pa):
                return True
    return False


def derive_dependencies(plan: ConductorPlan) -> ConductorPlan:
    """Augment each item's depends_on with FILE-OVERLAP dependencies the CORE derives
    from ``touches`` — so serializing demands that share files does NOT rely on the
    planner declaring depends_on. This is the mechanical interdependency guarantee.

    Gated on the plan actually declaring ``touches``: a plan with NONE is returned
    UNCHANGED (byte-identical — the Conductor, or a legacy plan — relying on explicit
    depends_on only). In a touches-aware plan, an item that declares NO touches is
    treated CONSERVATIVELY (overlaps everything) so it is serialized, never run blind.

    Deterministic: an item depends on every EARLIER item (plan order) it overlaps, so a
    stable order breaks ties. A stable id (``d0``, ``d1``, …) is assigned to items
    missing one so a derived dependency can reference them.
    """
    items = list(plan.items)
    if not any(item.touches for item in items):
        return plan  # no touches declared -> unchanged (explicit deps only)

    withid = [
        item if item.id else item.model_copy(update={"id": f"d{i}"})
        for i, item in enumerate(items)
    ]
    result: list[PlannedUnit] = []
    for i, item in enumerate(withid):
        deps = set(item.depends_on)
        for j in range(i):
            prior = withid[j]
            # No touches on either side -> can't prove disjoint -> conservative overlap.
            if (
                not item.touches
                or not prior.touches
                or _touch_overlap(item.touches, prior.touches)
            ):
                deps.add(prior.id)
        result.append(item.model_copy(update={"depends_on": sorted(deps)}))
    return ConductorPlan(items=result)


def dispatch_enqueue(
    plan: ConductorPlan,
    manifest: Manifest,
    operator_layer: Path,
    engine_override: str | None = None,
    isolate: bool = True,
    prefix: str = "conduct",
    priority: int = 0,
) -> list[str]:
    """Write one queue task YAML file per PlannedUnit item.

    Files are written under ``<project_root>/<manifest.queue_dir>/`` and are
    valid QueueTask files that ``alc tick`` can drain. Flow units keep the legacy
    ``flow:`` field for compatibility; specialist units carry ``kind`` and ``name``.

    Filenames are index-first and carry a slug of the task's first line
    (``<prefix>-<NN>-<slug>-<uid>.yaml``) so the drain order (process_queue sorts
    ``*.yaml`` by name) follows plan order AND the queue header / archived report
    name (``▶ <file> — …``) is human-readable instead of an opaque uid.

    Args:
        plan: The validated ConductorPlan.
        manifest: Loaded Manifest (provides queue_dir).
        operator_layer: Path to the ``.alc/`` directory.
        engine_override: If set, written as the ``engine`` field in the task file.
        isolate: Value written as each task's ``isolate`` field. Default True keeps
            the Conductor byte-identical; the ``kind: plan`` replenish passes False
            so demand tasks share the workdir.
        prefix: Filename prefix that records provenance. Default ``conduct`` (the
            Conductor); the ``kind: plan`` replenish passes ``plan``.
        priority: Value written as each task's ``priority`` field (0 = omitted,
            keeping files legacy-clean and the drain order byte-identical).

    Returns:
        Sorted list of filenames (stems only, not full paths) that were written.
    """
    # The CORE derives file-overlap dependencies from each unit's `touches` (union with
    # explicit depends_on) so overlapping demands serialize automatically — the
    # interdependency guarantee does not depend on the planner. No-touches plans (e.g.
    # the Conductor) pass through unchanged.
    plan = derive_dependencies(plan)

    queue_dir = operator_layer.parent / manifest.queue_dir
    queue_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for i, item in enumerate(plan.items):
        uid = uuid.uuid4().hex[:8]
        lines = item.task.splitlines()
        slug = _slugify(lines[0]) if lines else ""
        stem = f"{prefix}-{i:03d}-{slug}-{uid}" if slug else f"{prefix}-{i:03d}-{uid}"
        filename = f"{stem}.yaml"
        task_data: dict = {
            "task": item.task,
            "isolate": isolate,
        }
        if item.kind == "specialist":
            task_data["kind"] = "specialist"
            task_data["name"] = item.name
        else:
            # Legacy-compatible flow task: only the `flow:` field.
            task_data["flow"] = item.name
        if engine_override is not None:
            task_data["engine"] = engine_override
        # Carry the dependency wiring into the QueueTask so the waved drain can
        # schedule topologically. Omitted when absent to keep files legacy-clean.
        if item.id is not None:
            task_data["id"] = item.id
        if item.depends_on:
            task_data["depends_on"] = item.depends_on
        if priority:
            task_data["priority"] = priority

        (queue_dir / filename).write_text(yaml.safe_dump(task_data, sort_keys=True))
        written.append(filename)

    return written


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def conduct(
    manifest: Manifest,
    operator_layer: Path,
    goal: str,
    engine_override: str | None = None,
    enqueue: bool = False,
    parallel: bool = False,
    concurrency: int | None = None,
    tier: str | None = None,
) -> ConductReport:
    """Plan and dispatch a goal via the Conductor.

    Resolves the engine, builds the catalog (Flows and Specialists), asks the
    engine for a plan, then either runs the plan (run mode) or writes it to the
    queue (enqueue mode).

    When ``parallel`` is True and the project root is a git repo, the whole plan
    is dispatched concurrently via ``run_fanout`` (each unit in its own isolated
    worktree); the outcomes land in ``ConductReport.units``. Outside a git repo,
    ``parallel`` prints a note to stderr and falls back to serial dispatch.

    Args:
        manifest: Loaded Manifest.
        operator_layer: Path to the ``.alc/`` directory.
        goal: The operator's high-level goal.
        engine_override: Use this engine for both planning and dispatch.
            If None, uses manifest.default_engine.
        enqueue: When True, write queue task files instead of running now.
        parallel: When True, dispatch independent units concurrently (requires git).
        concurrency: Parallel fan-out width; None -> manifest.fanout_concurrency.
        tier: Compute tier for the planning turn; None -> manifest.plan_tier.

    Returns:
        ConductReport capturing goal, mode, plan, and outcomes.
    """
    from alc.engines.registry import resolve_engine

    # Resolve engine and model for the planning turn (a configurable tier).
    engine_name = engine_override or manifest.default_engine
    engine = resolve_engine(engine_name, manifest.engines)

    plan_tier = tier or manifest.plan_tier
    model: str | None = manifest.compute_tiers.get(plan_tier, {}).get(engine_name)

    # Build the catalog from all available Flows and Specialists.
    catalog_text, available_flows, available_specialists = build_catalog(
        manifest, operator_layer
    )

    # Resolve the reserved planning prompts through the override registry so an
    # operator override transparently replaces the built-in defaults.
    directive_template = resolve_prompt("conductor", operator_layer, manifest)
    corrective_template = resolve_prompt("corrective", operator_layer, manifest)

    plan = plan_flows(
        engine,
        model,
        goal,
        catalog_text,
        available_flows,
        available_specialists,
        max_retries=manifest.plan_retries,
        directive_template=directive_template,
        corrective_template=corrective_template,
    )

    if enqueue:
        files = dispatch_enqueue(plan, manifest, operator_layer, engine_override=engine_override)
        return ConductReport(goal=goal, mode="enqueue", plan=plan, enqueued_files=files)

    if parallel:
        from alc.worktree import is_git_repo

        project_root = operator_layer.parent
        if is_git_repo(project_root):
            from alc.fanout import run_fanout

            units = [
                {"kind": item.kind, "name": item.name, "task": item.task}
                for item in plan.items
            ]
            max_workers = (
                concurrency if concurrency is not None else manifest.fanout_concurrency
            )
            fanout = run_fanout(
                manifest,
                operator_layer,
                units,
                engine_override=engine_override,
                max_workers=max_workers,
            )
            # A `run` conduct must APPLY its work, not strand it on per-unit
            # branches: integrate every successful unit's branch into the current
            # branch, exactly as the queue drain does. Conflicting branches are
            # left intact for manual resolution (surfaced as merged/left).
            from alc.merge import auto_merge_branches
            from alc.worktree import git_toplevel

            branches = [u.branch for u in fanout.units if u.success and u.branch]
            merged: list[str] = []
            left: list[str] = []
            if branches:
                merge_report = auto_merge_branches(git_toplevel(project_root), branches)
                merged, left = merge_report.merged, merge_report.conflicted
                print(f"▶ conduct: {merge_report.summary()}", file=sys.stderr, flush=True)
            return ConductReport(
                goal=goal,
                mode="run",
                plan=plan,
                units=fanout.units,
                success=fanout.success,
                merged=merged,
                left=left,
            )
        print(
            "--parallel ignored: not inside a git repository; running serially.",
            file=sys.stderr,
        )

    reports = dispatch_now(plan, manifest, operator_layer, engine_override=engine_override)
    success = all(r.success for r in reports)
    return ConductReport(
        goal=goal, mode="run", plan=plan, flow_reports=reports, success=success
    )
