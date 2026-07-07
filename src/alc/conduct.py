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
from pathlib import Path

import yaml

from alc.engine import Engine, EngineRequest
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

        # Build via model_validate so the before-validator normalises any
        # legacy shape; the catalog check above has already run by this point.
        items.append(PlannedUnit.model_validate({
            "kind": kind, "name": name, "task": str(entry["task"])
        }))

    return ConductorPlan(items=items)


# ---------------------------------------------------------------------------
# Planning turn
# ---------------------------------------------------------------------------

_CONDUCTOR_DIRECTIVE_TEMPLATE = """\
# ALC Conductor — Single Mandate

You are the ALC Conductor. Your mandate is to decompose the operator's goal into
independent units of work, assigning each to the best-matching target drawn
exclusively from the Catalog below. Prefer a Specialist for area-scoped work; use
a Flow for multi-stage pipelines.

## Goal

{goal}

## Catalog

{catalog_text}

## Instructions

Break the goal into independent parts. Output ONLY a JSON array — no prose, no
markdown fences, no explanation. Each element must be an object with exactly
three keys:
  "kind": either "flow" or "specialist"
  "name": one of the names listed in the Catalog (exact match, case-sensitive)
  "task": a concise free-text task description for that unit

Example output:
[{{"kind": "flow", "name": "ship", "task": "implement the feature"}}]
"""

_CORRECTIVE_SUFFIX = "\n\nYour previous output was invalid: {err}. Output ONLY the JSON array."


def plan_flows(
    engine: Engine,
    model: str | None,
    goal: str,
    catalog_text: str,
    available_flows: set[str],
    available_specialists: set[str] | None = None,
    max_retries: int = 2,
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

    Returns:
        Validated ConductorPlan.

    Raises:
        ValueError: If all attempts (1 + max_retries) are exhausted without a
                    valid plan.
    """
    directive = _CONDUCTOR_DIRECTIVE_TEMPLATE.format(
        goal=goal,
        catalog_text=catalog_text,
    )

    last_err: ValueError | None = None
    for attempt in range(1 + max_retries):
        if attempt > 0 and last_err is not None:
            directive += _CORRECTIVE_SUFFIX.format(err=str(last_err))

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
    runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
    reports: list[FlowReport] = []
    for item in plan.items:
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
                _specialist_flow_report(item.name, engine_name, specialist_report.act)
            )
            continue
        flow = load_flow(flows_dir, item.name)
        report = runner.run(flow, item.task, engine_override=engine_override)
        reports.append(report)
    return reports


def dispatch_enqueue(
    plan: ConductorPlan,
    manifest: Manifest,
    operator_layer: Path,
    engine_override: str | None = None,
) -> list[str]:
    """Write one queue task YAML file per PlannedUnit item.

    Files are written under ``<project_root>/<manifest.queue_dir>/`` and are
    valid QueueTask files that ``alc tick`` can drain. Flow units keep the legacy
    ``flow:`` field for compatibility; specialist units carry ``kind`` and ``name``.

    Args:
        plan: The validated ConductorPlan.
        manifest: Loaded Manifest (provides queue_dir).
        operator_layer: Path to the ``.alc/`` directory.
        engine_override: If set, written as the ``engine`` field in the task file.

    Returns:
        Sorted list of filenames (stems only, not full paths) that were written.
    """
    queue_dir = operator_layer.parent / manifest.queue_dir
    queue_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for i, item in enumerate(plan.items):
        uid = uuid.uuid4().hex[:8]
        filename = f"conduct-{uid}-{i}.yaml"
        task_data: dict = {
            "task": item.task,
            "isolate": True,
        }
        if item.kind == "specialist":
            task_data["kind"] = "specialist"
            task_data["name"] = item.name
        else:
            # Legacy-compatible flow task: only the `flow:` field.
            task_data["flow"] = item.name
        if engine_override is not None:
            task_data["engine"] = engine_override

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

    Returns:
        ConductReport capturing goal, mode, plan, and outcomes.
    """
    from alc.engines.registry import resolve_engine

    # Resolve engine and model for the planning turn.
    engine_name = engine_override or manifest.default_engine
    engine = resolve_engine(engine_name, manifest.engines)

    model: str | None = manifest.compute_tiers.get("standard", {}).get(engine_name)

    # Build the catalog from all available Flows and Specialists.
    flows = load_all_flows(manifest, operator_layer)
    specialists = load_all_specialists(manifest, operator_layer)
    catalog_lines = [
        f"- {f.name} (flow): {f.description} "
        f"(stages: {', '.join(s.blueprint for s in f.stages)})"
        for f in flows
    ]
    catalog_lines += [f"- {s.name} (specialist): {s.area}" for s in specialists]
    catalog_text = "\n".join(catalog_lines) if catalog_lines else "(no targets available)"
    available_flows: set[str] = {f.name for f in flows}
    available_specialists: set[str] = {s.name for s in specialists}

    plan = plan_flows(
        engine, model, goal, catalog_text, available_flows, available_specialists
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
            fanout = run_fanout(
                manifest, operator_layer, units, engine_override=engine_override
            )
            return ConductReport(
                goal=goal,
                mode="run",
                plan=plan,
                units=fanout.units,
                success=fanout.success,
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
