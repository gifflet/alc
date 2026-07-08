# loop.py — The Autonomous Loop core: plan (replenish) -> drain -> check stop -> repeat.
#
# This is a generic control structure. It knows nothing about pm/dev/qa — what runs
# each cycle is pluggable config (a LoopDefinition). Cron owns the cadence: `alc cycle`
# runs exactly ONE cycle and exits; state persists between fires. The mandatory
# max_cycles backstop guarantees the loop cannot run away.
#
# Pure and testable: no argparse here. The CLI (cmd_cycle / cmd_loop) drives run_cycle.
from __future__ import annotations

import json
import sys
from pathlib import Path

from alc.engine import Usage
from alc.intake import load_specialist
from alc.models import (
    CycleRecord,
    FlowReport,
    LoopDefinition,
    LoopState,
    Manifest,
    RunReport,
)
from alc.queue import process_queue

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def loops_dir(manifest: Manifest, operator_layer: Path) -> Path:
    """Return the loops directory (``<project_root>/<manifest.loops_dir>``)."""
    return operator_layer.parent / manifest.loops_dir


def def_path(loops: Path, name: str) -> Path:
    """Path to a loop definition YAML."""
    return loops / f"{name}.yaml"


def state_path(loops: Path, name: str) -> Path:
    """Path to a loop state JSON."""
    return loops / f"{name}.state.json"


def ledger_path(loops: Path, name: str) -> Path:
    """Path to a loop ledger JSONL."""
    return loops / f"{name}.ledger.jsonl"


# ---------------------------------------------------------------------------
# State + ledger persistence
# ---------------------------------------------------------------------------


def load_loop_state(path: Path, name: str) -> LoopState:
    """Load loop state from disk, or return a fresh pending state when absent."""
    if not path.exists():
        return LoopState(name=name)
    return LoopState.model_validate_json(path.read_text())


def save_loop_state(path: Path, state: LoopState) -> None:
    """Write loop state to disk (creating the loops dir if needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2))


def append_ledger(path: Path, record: CycleRecord) -> None:
    """Append one cycle record as a JSON line (creating the loops dir if needed).

    This write is best-effort: if the process crashes between the ledger append and
    the caller persisting state, the ledger may contain a duplicated entry for that
    cycle; the hard backstops (max_cycles/budget) are re-evaluated from persisted state
    so this cannot cause a runaway.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(record.model_dump_json() + "\n")


# ---------------------------------------------------------------------------
# Stop-condition checks
# ---------------------------------------------------------------------------


def check_pre_stop(loop_def: LoopDefinition, state: LoopState) -> str | None:
    """Stop conditions evaluated BEFORE running a cycle (on current state).

    Returns "max_cycles" or "budget" when a backstop already holds, else None.
    """
    if state.cycle >= loop_def.stop.max_cycles:
        return "max_cycles"
    budget = loop_def.stop.budget
    if budget is not None and state.budget_used.get(budget.unit, 0) >= budget.max:
        return "budget"
    return None


def check_post_stop(
    loop_def: LoopDefinition, state: LoopState, record: CycleRecord
) -> str | None:
    """Stop conditions evaluated AFTER a cycle ran (on the updated state).

    First match wins, in order: no_new_work, failures, budget, max_cycles.
    """
    if (
        loop_def.stop.on_no_new_work
        and record.replenished == 0
        and record.drained == 0
    ):
        return "no_new_work"
    if state.consecutive_no_progress >= loop_def.failure.max_consecutive:
        return "failures"
    budget = loop_def.stop.budget
    if budget is not None and state.budget_used.get(budget.unit, 0) >= budget.max:
        return "budget"
    if state.cycle >= loop_def.stop.max_cycles:
        return "max_cycles"
    return None


# ---------------------------------------------------------------------------
# Budget accounting helpers
# ---------------------------------------------------------------------------


def _run_report_calls(report: RunReport) -> int:
    """Engine calls attributed to one RunReport (its attempt count).

    NOTE: This is an approximation. Specialist Learn turns and verify-only stages
    are NOT counted — engine_calls is a safety cap, not a billing meter. The
    mandatory max_cycles backstop remains the true guarantee against runaway.
    """
    return len(report.attempts)


def _report_usage(report: RunReport, delta: dict[str, float]) -> None:
    """Fold one RunReport's engine calls + Usage into the running cycle delta."""
    delta["engine_calls"] += _run_report_calls(report)
    usage = report.usage
    if usage is None:
        return
    if usage.cost_usd is not None:
        delta["usd"] += usage.cost_usd
    tokens = (usage.input_tokens or 0) + (usage.output_tokens or 0)
    delta["tokens"] += tokens


def _flow_usage(report: FlowReport, delta: dict[str, float]) -> None:
    """Fold a FlowReport (sum across its stages) into the running cycle delta."""
    for stage in report.stages:
        _report_usage(stage, delta)


def _warn_if_budget_unmeasurable(
    loop_def: LoopDefinition, delta: dict[str, float]
) -> None:
    """Print a one-line warning to stderr when the budget unit is unmeasurable.

    Triggers only when:
    - a budget stop is configured with unit 'usd' or 'tokens', AND
    - engine work actually ran this cycle (engine_calls > 0), AND
    - the chosen unit contributed nothing to the delta (still 0).

    When none of those conditions hold — no budget, engine_calls unit, nothing ran,
    or the unit was genuinely measured — this is a silent no-op.
    """
    budget = loop_def.stop.budget
    if budget is None:
        return
    unit = budget.unit
    if unit == "engine_calls":
        return
    if delta.get("engine_calls", 0) == 0:
        # Nothing ran this cycle; zero is expected, not a reporting gap.
        return
    if delta.get(unit, 0) == 0:
        print(
            f"[WARN] budget unit '{unit}' reported nothing this cycle; "
            f"the {unit} cap is inert — max_cycles remains the backstop.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Replenish (Mode A planning step)
# ---------------------------------------------------------------------------


def _count_queue_files(manifest: Manifest, operator_layer: Path) -> int:
    """Count pending *.yaml task files at the top of the queue directory."""
    queue_dir = operator_layer.parent / manifest.queue_dir
    if not queue_dir.exists():
        return 0
    return len(list(queue_dir.glob("*.yaml")))


def run_replenish(
    manifest: Manifest,
    operator_layer: Path,
    loop_def: LoopDefinition,
    engine_override: str | None,
) -> tuple[int, dict[str, float]]:
    """Run the loop's replenish step and return (enqueued_count, budget_delta).

    Counts pending queue files before and after dispatching the configured
    replenish. In Mode B (no replenish) this is a no-op returning (0, zeros).

    - specialist: load the Specialist, run it (its Act may self-enqueue work).
    - conduct: plan the goal and enqueue the resulting units.
    - plan: run a planner Specialist, commit its roadmap change, then reuse the
      Conductor's parse + enqueue on the structured plan it returns.

    The budget_delta carries the engine calls + Usage of the replenish itself so
    the cycle can charge them against the budget.
    """
    delta: dict[str, float] = {"engine_calls": 0.0, "usd": 0.0, "tokens": 0.0}
    if loop_def.replenish is None:
        return 0, delta

    # Announce the replenish step so operator output is grouped under a header,
    # matching the ▶ style used by queue._process_task and flow.FlowRunner.
    replenish = loop_def.replenish
    if replenish.kind == "specialist":
        print(
            f"▶ replenish — specialist:{replenish.ref}",
            file=sys.stderr,
            flush=True,
        )
    elif replenish.kind == "flow":
        print(
            f"▶ replenish — flow:{replenish.ref}",
            file=sys.stderr,
            flush=True,
        )
    elif replenish.kind == "plan":
        print(
            f"▶ replenish — plan:{replenish.ref}",
            file=sys.stderr,
            flush=True,
        )
    else:
        print("▶ replenish — conduct", file=sys.stderr, flush=True)

    before = _count_queue_files(manifest, operator_layer)

    if replenish.kind == "specialist":
        from alc.specialist import run_specialist

        specialists_dir = operator_layer.parent / manifest.specialists_dir
        specialist = load_specialist(specialists_dir, replenish.ref)
        report = run_specialist(
            manifest=manifest,
            operator_layer=operator_layer,
            specialist=specialist,
            task=replenish.task,
            engine_override=engine_override,
        )
        _report_usage(report.act, delta)
    elif replenish.kind == "flow":
        from alc.flow import FlowRunner
        from alc.intake import load_flow

        flows_dir_path = operator_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir_path, replenish.ref)
        flow_report = FlowRunner(
            manifest=manifest, operator_layer=operator_layer
        ).run(flow, task=replenish.task, engine_override=engine_override, workdir=None)
        _flow_usage(flow_report, delta)
    elif replenish.kind == "plan":
        from alc.commit import commit_workdir
        from alc.conduct import dispatch_enqueue, parse_plan
        from alc.intake import load_all_flows, load_all_specialists
        from alc.specialist import run_specialist

        specialists_dir = operator_layer.parent / manifest.specialists_dir
        planner = load_specialist(specialists_dir, replenish.ref)
        report = run_specialist(
            manifest=manifest,
            operator_layer=operator_layer,
            specialist=planner,
            task=replenish.task,
            engine_override=engine_override,
            workdir=None,
        )
        _report_usage(report.act, delta)
        # Commit the planner's roadmap change so the tree is clean for the
        # demand-flows' clean-tree guard (this replaces the old plan-flow commit).
        commit_workdir(operator_layer.parent, "chore(roadmap): plan next version")
        # Reuse the Conductor: the planner only DECIDES (returns a structured plan);
        # ALC enqueues deterministically. A malformed plan or an unknown flow/specialist
        # name raises ValueError -> clean no-op (never a corrupt queue).
        available_flows = {f.name for f in load_all_flows(manifest, operator_layer)}
        available_specialists = {
            s.name for s in load_all_specialists(manifest, operator_layer)
        }
        try:
            plan = parse_plan(
                report.act.output_text, available_flows, available_specialists
            )
            dispatch_enqueue(
                plan,
                manifest,
                operator_layer,
                engine_override=engine_override,
                isolate=False,
                prefix="plan",
            )
        except ValueError as exc:
            print(
                f"▶ replenish — plan not enqueued (invalid plan): {exc}",
                file=sys.stderr,
                flush=True,
            )
    else:  # conduct
        from alc.conduct import conduct

        conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal=replenish.task,
            engine_override=engine_override,
            enqueue=True,
        )
        # The Conductor's planning turn is an engine call not captured in a
        # RunReport; count it as one for the engine_calls cap (approximate).
        delta["engine_calls"] += 1

    after = _count_queue_files(manifest, operator_layer)
    enqueued = max(0, after - before)
    return enqueued, delta


# ---------------------------------------------------------------------------
# One cycle
# ---------------------------------------------------------------------------


def run_cycle(
    manifest: Manifest,
    operator_layer: Path,
    loop_def: LoopDefinition,
    state: LoopState,
    engine_override: str | None = None,
) -> tuple[LoopState, CycleRecord]:
    """Run exactly one loop cycle and return the (new_state, ledger_record).

    Steps: pre-check stop -> replenish (Mode A) -> drain -> compute progress and
    budget delta -> update state -> post-check stop -> append ledger.

    A pre-stop short-circuits: neither replenish nor drain runs, the state is
    marked stopped, and a zeroed CycleRecord carrying the reason is returned
    (still appended to the ledger for observability).
    """
    loops = loops_dir(manifest, operator_layer)
    ledger = ledger_path(loops, loop_def.name)

    # (a) Pre-check: a backstop already holds -> no-op this cycle.
    pre = check_pre_stop(loop_def, state)
    if pre is not None:
        new_state = state.model_copy(update={"status": "stopped", "stopped_reason": pre})
        record = CycleRecord(
            cycle=state.cycle,
            replenished=0,
            drained=0,
            succeeded=0,
            failed=0,
            progress=False,
            budget_delta={"engine_calls": 0.0, "usd": 0.0, "tokens": 0.0},
            stopped_reason=pre,
        )
        append_ledger(ledger, record)
        return new_state, record

    # (b) Replenish (Mode A only).
    enqueued, delta = run_replenish(manifest, operator_layer, loop_def, engine_override)

    # (c) Drain the queue.
    results = process_queue(
        manifest, operator_layer, max_workers=loop_def.drain.concurrency
    )
    drained = len(results)
    succeeded = sum(1 for r in results if r.success)
    failed = drained - succeeded
    progress = succeeded > 0

    # (e) Budget delta: replenish + each drained unit's engine calls + Usage.
    for result in results:
        _flow_usage(result.report, delta)

    # (f) Update state: advance cycle, accumulate budget, track no-progress streak.
    # Transition pending -> running on the first completed cycle.
    budget_used = dict(state.budget_used)
    for key, value in delta.items():
        budget_used[key] = budget_used.get(key, 0.0) + value
    new_state = state.model_copy(
        update={
            "status": "running",
            "cycle": state.cycle + 1,
            "budget_used": budget_used,
            "consecutive_no_progress": (
                0 if progress else state.consecutive_no_progress + 1
            ),
        }
    )

    record = CycleRecord(
        cycle=new_state.cycle,
        replenished=enqueued,
        drained=drained,
        succeeded=succeeded,
        failed=failed,
        progress=progress,
        budget_delta=delta,
    )

    # (g-pre) Warn when a usd/tokens budget cap is configured but the chosen unit
    # reported nothing this cycle despite engine work having run.  The cap is inert
    # when the unit stays at zero forever; max_cycles is the true backstop.
    _warn_if_budget_unmeasurable(loop_def, delta)

    # (g) Post-check: did this cycle trip a stop condition?
    post = check_post_stop(loop_def, new_state, record)
    if post is not None:
        new_state = new_state.model_copy(
            update={"status": "stopped", "stopped_reason": post}
        )
        record = record.model_copy(update={"stopped_reason": post})

    # (h) Record the cycle.
    append_ledger(ledger, record)
    return new_state, record


def format_cycle_summary(record: CycleRecord) -> str:
    """Render a one-line human summary of a cycle for the CLI."""
    line = (
        f"cycle {record.cycle}: replenished={record.replenished} "
        f"drained={record.drained} succeeded={record.succeeded} "
        f"failed={record.failed}"
    )
    if record.stopped_reason is not None:
        line += f" [stopped: {record.stopped_reason}]"
    return line


def read_ledger(path: Path) -> list[CycleRecord]:
    """Read a loop ledger JSONL into CycleRecord objects (empty when absent)."""
    if not path.exists():
        return []
    records: list[CycleRecord] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            records.append(CycleRecord.model_validate(json.loads(line)))
    return records
