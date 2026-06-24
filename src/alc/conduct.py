# conduct.py — Conductor: single-interface orchestrator that turns a goal into a
# structured plan of (flow, task) items, then either runs them now or enqueues them
# for alc tick (Unattended Mode).
#
# DIP seam: the Engine is injected by the caller; no concrete adapter is imported here.
from __future__ import annotations

import json
import uuid
from pathlib import Path

import yaml

from alc.engine import Engine, EngineRequest
from alc.flow import FlowRunner
from alc.intake import load_all_flows, load_flow
from alc.models import (
    ConductorPlan,
    ConductReport,
    FlowReport,
    Manifest,
    PlannedFlow,
)


# ---------------------------------------------------------------------------
# Pure parsing helpers
# ---------------------------------------------------------------------------


def parse_plan(output_text: str, available_flows: set[str]) -> ConductorPlan:
    """Parse the Conductor's raw output into a validated ConductorPlan.

    Tries strict JSON first; if that fails, extracts the substring between the
    outermost ``[`` and ``]`` (handles markdown code fences and surrounding prose).

    Args:
        output_text: Raw text produced by the planning engine turn.
        available_flows: Set of flow names declared in the Operator Layer catalog.

    Returns:
        ConductorPlan with one PlannedFlow per item.

    Raises:
        ValueError: If the text is not parseable JSON, wrong shape, or references
                    a flow name that is not in ``available_flows``.
    """
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

    items: list[PlannedFlow] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict) or "flow" not in entry or "task" not in entry:
            raise ValueError(
                f"Item {i} in Conductor plan is missing 'flow' or 'task' keys: {entry!r}"
            )
        flow_name = entry["flow"]
        if flow_name not in available_flows:
            raise ValueError(
                f"Item {i} references unknown flow '{flow_name}'. "
                f"Available flows: {sorted(available_flows)}"
            )
        items.append(PlannedFlow(flow=flow_name, task=str(entry["task"])))

    return ConductorPlan(items=items)


# ---------------------------------------------------------------------------
# Planning turn
# ---------------------------------------------------------------------------

_CONDUCTOR_DIRECTIVE_TEMPLATE = """\
# ALC Conductor — Single Mandate

You are the ALC Conductor. Your mandate is to translate the operator's goal into
an ordered list of Flow invocations drawn exclusively from the Catalog below.

## Goal

{goal}

## Catalog (available Flows)

{catalog_text}

## Instructions

Output ONLY a JSON array — no prose, no markdown fences, no explanation.
Each element must be an object with exactly two keys:
  "flow": one of the flow names listed in the Catalog (exact match, case-sensitive)
  "task": a concise free-text task description for that Flow invocation

Example output:
[{{"flow": "ship", "task": "implement the feature"}}]
"""

_CORRECTIVE_SUFFIX = "\n\nYour previous output was invalid: {err}. Output ONLY the JSON array."


def plan_flows(
    engine: Engine,
    model: str | None,
    goal: str,
    catalog_text: str,
    available_flows: set[str],
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
        catalog_text: Human-readable list of available Flows with descriptions.
        available_flows: Set of valid flow names for validation.
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
            return parse_plan(result.output_text, available_flows)
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
    """Run each PlannedFlow immediately via FlowRunner.

    Args:
        plan: The validated ConductorPlan.
        manifest: Loaded Manifest (provides engine config, dirs).
        operator_layer: Path to the ``.alc/`` directory.
        engine_override: Optional engine name to use instead of the manifest default.

    Returns:
        List of FlowReport, one per item in the plan (in order).
    """
    flows_dir = operator_layer.parent / manifest.flows_dir
    runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
    reports: list[FlowReport] = []
    for item in plan.items:
        flow = load_flow(flows_dir, item.flow)
        report = runner.run(flow, item.task, engine_override=engine_override)
        reports.append(report)
    return reports


def dispatch_enqueue(
    plan: ConductorPlan,
    manifest: Manifest,
    operator_layer: Path,
    engine_override: str | None = None,
) -> list[str]:
    """Write one queue task YAML file per PlannedFlow item.

    Files are written under ``<project_root>/<manifest.queue_dir>/`` and are
    valid QueueTask files that ``alc tick`` can drain.

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
            "flow": item.flow,
            "task": item.task,
            "isolate": True,
        }
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
) -> ConductReport:
    """Plan and dispatch a goal via the Conductor.

    Resolves the engine, builds the Flow catalog, asks the engine for a plan,
    then either runs the plan immediately (run mode) or writes it to the queue
    (enqueue mode).

    Args:
        manifest: Loaded Manifest.
        operator_layer: Path to the ``.alc/`` directory.
        goal: The operator's high-level goal.
        engine_override: Use this engine for both planning and dispatch.
            If None, uses manifest.default_engine.
        enqueue: When True, write queue task files instead of running now.

    Returns:
        ConductReport capturing goal, mode, plan, and outcomes.
    """
    from alc.engines.registry import resolve_engine

    # Resolve engine and model for the planning turn.
    engine_name = engine_override or manifest.default_engine
    engine = resolve_engine(engine_name, manifest.engines)

    model: str | None = manifest.compute_tiers.get("standard", {}).get(engine_name)

    # Build the catalog from all available Flows.
    flows = load_all_flows(manifest, operator_layer)
    catalog_lines = [
        f"- {f.name}: {f.description} (stages: {', '.join(s.blueprint for s in f.stages)})"
        for f in flows
    ]
    catalog_text = "\n".join(catalog_lines) if catalog_lines else "(no flows available)"
    available: set[str] = {f.name for f in flows}

    plan = plan_flows(engine, model, goal, catalog_text, available)

    if enqueue:
        files = dispatch_enqueue(plan, manifest, operator_layer, engine_override=engine_override)
        return ConductReport(goal=goal, mode="enqueue", plan=plan, enqueued_files=files)

    reports = dispatch_now(plan, manifest, operator_layer, engine_override=engine_override)
    return ConductReport(goal=goal, mode="run", plan=plan, flow_reports=reports)
