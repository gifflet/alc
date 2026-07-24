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

from alc.events import bind_run_log, new_run_log_path
from alc.intake import load_specialist
from alc.models import (
    CycleRecord,
    FlowReport,
    LoopDefinition,
    LoopState,
    Manifest,
    QueueTask,
    RunReport,
)
from alc.notify import fire as notify_fire
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


def reset_loop_state(path: Path, name: str) -> LoopState:
    """Replace the loop's persisted state with a fresh pending one; return it.

    Shared by `alc cycle --reset` and `alc loop --reset` so the restart semantics
    (a clean LoopState, persisted) live in one place.
    """
    state = LoopState(name=name)
    save_loop_state(path, state)
    return state


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
        and not record.replenish_failed
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
    state: LoopState | None = None,
) -> tuple[int, dict[str, float]]:
    """Run the loop's replenish step and return (enqueued_count, budget_delta).

    Counts pending queue files before and after dispatching the configured
    replenish. In Mode B (no replenish) this is a no-op returning (0, zeros).

    - specialist: load the Specialist, run it (its Act may self-enqueue work).
    - conduct: plan the goal and enqueue the resulting units.
    - plan: run a planner Specialist, commit its roadmap change, then reuse the
      Conductor's parse + enqueue on the structured plan it returns.
    - signals: read every pending signal (``alc.signals``) and dispatch-enqueue
      one demand per signal — no planning turn, the same direct write
      ``alc enqueue`` uses — then archive each consumed signal.
    - regression: read the metric ledger (``alc.metrics``) for checks with a
      ledger record this replenish hasn't considered yet; a check whose newest
      such record was REJECTED (``MetricRecord.passed`` False — the Verifier's
      own tolerance judgment at measurement time, never re-derived here) is a
      regression: dispatch-enqueue ONE fix demand carrying the check name and
      its delta from the latest ACCEPTED value (the "baseline it should be
      judged against") as failure feedback, reusing
      ``queue.build_retry_task``'s delimited-feedback text. Per-check progress
      lives in ``state.metric_cursor`` (see below) so the same ledger entry is
      never re-flagged.

    The budget_delta carries the engine calls + Usage of the replenish itself so
    the cycle can charge them against the budget.

    ``state`` is optional and used ONLY by the ``regression`` kind, to read and
    advance ``state.metric_cursor``. It is mutated IN PLACE (not returned) so
    this function's return stays the fixed (count, budget_delta, replenish_ok)
    tuple every kind returns; the caller (``run_cycle``) builds its next state
    via ``state.model_copy(...)`` on this SAME object, which naturally carries
    the mutated cursor forward. Callers that don't pass ``state`` (or kinds
    other than ``regression``) are unaffected.
    """
    delta: dict[str, float] = {"engine_calls": 0.0, "usd": 0.0, "tokens": 0.0}
    # False when the replenish engine turn FAILED (planner Act errored / plan
    # unparseable) — the caller uses this so a transient failure doesn't trip
    # no_new_work. "No replenish configured" and "conduct" are not failures.
    replenish_ok = True
    if loop_def.replenish is None:
        return 0, delta, replenish_ok

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
    elif replenish.kind == "signals":
        print(
            f"▶ replenish — signals:{replenish.ref}",
            file=sys.stderr,
            flush=True,
        )
    elif replenish.kind == "regression":
        print(
            f"▶ replenish — regression:{replenish.ref}",
            file=sys.stderr,
            flush=True,
        )
    else:
        print("▶ replenish — conduct", file=sys.stderr, flush=True)

    # Each replenish that runs a mandate/flow binds its own run log so the loop's
    # planning step is as observable as a demand drain (kind "replenish").
    runs_dir = operator_layer.parent / manifest.runs_dir
    before = _count_queue_files(manifest, operator_layer)

    if replenish.kind == "specialist":
        from alc.specialist import run_specialist

        specialists_dir = operator_layer.parent / manifest.specialists_dir
        specialist = load_specialist(specialists_dir, replenish.ref)
        with bind_run_log(
            new_run_log_path(runs_dir, "replenish", f"specialist {replenish.ref}")
        ):
            report = run_specialist(
                manifest=manifest,
                operator_layer=operator_layer,
                specialist=specialist,
                task=replenish.task,
                engine_override=engine_override,
            )
        _report_usage(report.act, delta)
        replenish_ok = report.act.success
    elif replenish.kind == "flow":
        from alc.flow import FlowRunner
        from alc.intake import load_flow

        flows_dir_path = operator_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir_path, replenish.ref)
        with bind_run_log(
            new_run_log_path(runs_dir, "replenish", f"flow {replenish.ref}")
        ):
            flow_report = FlowRunner(
                manifest=manifest, operator_layer=operator_layer
            ).run(
                flow, task=replenish.task, engine_override=engine_override, workdir=None
            )
        _flow_usage(flow_report, delta)
        replenish_ok = flow_report.success
    elif replenish.kind == "plan":
        from alc.commit import commit_workdir
        from alc.conduct import build_catalog, dispatch_enqueue, finalize_plan
        from alc.engines.registry import resolve_engine
        from alc.intake import load_blueprint
        from alc.prompts import render_plan_contract, resolve_prompt
        from alc.specialist import run_specialist

        specialists_dir = operator_layer.parent / manifest.specialists_dir
        planner = load_specialist(specialists_dir, replenish.ref)
        # Build the catalog once; it names the valid targets in the injected contract
        # and validates the plan the planner returns.
        catalog_text, available_flows, available_specialists = build_catalog(
            manifest, operator_layer
        )
        with bind_run_log(
            new_run_log_path(runs_dir, "replenish", f"plan {replenish.ref}")
        ):
            report = run_specialist(
                manifest=manifest,
                operator_layer=operator_layer,
                specialist=planner,
                task=replenish.task,
                engine_override=engine_override,
                workdir=None,
                output_contract=render_plan_contract(
                    catalog_text, operator_layer, manifest
                ),
            )
        _report_usage(report.act, delta)
        if not report.act.success:
            # The planner's Act failed (engine/API error — e.g. a 503 or a quota
            # limit). There is no plan to parse or heal, so skip the enqueue entirely.
            # This is a FAILURE (not "no work"): flag it so no_new_work won't stop the
            # loop; the failures/max_consecutive backstop bounds repeated failures.
            replenish_ok = False
            print(
                "▶ replenish — planner Act failed; nothing to enqueue.",
                file=sys.stderr,
                flush=True,
            )
        else:
            # Commit the planner's roadmap change so the tree is clean for the
            # demand-flows' clean-tree guard (this replaces the old plan-flow commit).
            # Corrective turns below are file-free, so this stays before the parse.
            commit_workdir(operator_layer.parent, "chore(roadmap): plan next version")
            # Resolve the engine + model for any format-only corrective turns. The
            # model comes from the planner blueprint's compute_tier so the retry
            # matches the planner's tier.
            engine_name = engine_override or manifest.default_engine
            engine = resolve_engine(engine_name, manifest.engines)
            blueprints_dir = operator_layer.parent / manifest.blueprints_dir
            planner_bp = load_blueprint(blueprints_dir, planner.blueprint)
            model = manifest.compute_tiers.get(planner_bp.compute_tier, {}).get(engine_name)
            corrective_template = resolve_prompt("corrective", operator_layer, manifest)
            # Reuse the Conductor: the planner only DECIDES (returns a structured
            # plan); ALC enqueues deterministically. A malformed first output
            # self-heals via cheap corrective turns; a still-invalid plan raises
            # ValueError -> clean no-op (never a corrupt queue).
            try:
                plan = finalize_plan(
                    engine,
                    model,
                    report.act.output_text,
                    available_flows,
                    available_specialists,
                    max_retries=manifest.plan_retries,
                    corrective_template=corrective_template,
                    # Corrective turns are real engine calls — charge them against
                    # the cycle's engine_calls safety cap (and usd/tokens if reported).
                    usage_sink=delta,
                )
                dispatch_enqueue(
                    plan,
                    manifest,
                    operator_layer,
                    engine_override=engine_override,
                    # Parallel demands: when the loop drains concurrently
                    # (drain.concurrency > 1) enqueue demands as isolate:true so each
                    # committing demand runs in its own provisioned, port-injected
                    # worktree and its branch is auto-merged after the batch. The
                    # default concurrency 1 keeps isolate:false -> serial shared-workdir
                    # standard cycle, byte-identical.
                    isolate=loop_def.drain.concurrency > 1,
                    prefix="plan",
                )
            except ValueError as exc:
                # The planner produced an unparseable plan (self-heal exhausted).
                # Treat like a replenish failure so no_new_work won't stop the loop.
                replenish_ok = False
                print(
                    f"▶ replenish — plan not enqueued (invalid plan): {exc}",
                    file=sys.stderr,
                    flush=True,
                )
    elif replenish.kind == "signals":
        from alc.conduct import dispatch_enqueue
        from alc.models import ConductorPlan, PlannedUnit
        from alc.signals import archive_signal, read_signals

        signals_dir = operator_layer.parent / manifest.signals_dir
        # Parallel drain -> isolated worktrees per demand (Part D); serial ->
        # shared workdir. Same rule the `plan` kind above uses.
        isolate = loop_def.drain.concurrency > 1
        for pending in read_signals(signals_dir):
            signal = pending.signal
            # The signal's title/body IS the demand; replenish.task is a
            # shared preamble/instruction an operator can use to frame every
            # signal-derived demand the same way (e.g. "Investigate and fix:").
            task_text = (
                f"{replenish.task}\n\n"
                f"## Signal ({signal.kind} via {signal.source}): {signal.title}\n\n"
                f"{signal.body}"
            ).strip()
            plan = ConductorPlan(
                items=[PlannedUnit(kind="flow", name=replenish.ref, task=task_text)]
            )
            # One signal -> one demand, dispatched through the SAME direct
            # write `alc enqueue` uses (no second enqueue path) — the
            # synthesized demand goes through the Policy Gate, isolation, and
            # retry exactly like any other queue task.
            dispatch_enqueue(
                plan,
                manifest,
                operator_layer,
                engine_override=engine_override,
                isolate=isolate,
                prefix="signal",
            )
            # Enqueue THEN archive: the worst case of a crash between the two
            # steps is a signal re-processed on the next cycle (one duplicate
            # demand) — never a lost signal, never a traceback (see
            # alc.signals.archive_signal).
            archive_signal(signals_dir, pending.path)
    elif replenish.kind == "regression":
        from alc.conduct import dispatch_enqueue
        from alc.metrics import latest_accepted_measurement, read_measurements
        from alc.metrics import ledger_path as metrics_ledger_path
        from alc.models import ConductorPlan, MetricRecord, PlannedUnit
        from alc.queue import build_retry_task

        metrics_path = metrics_ledger_path(operator_layer.parent / manifest.metrics_dir)
        # Parallel drain -> isolated worktrees per fix demand; serial -> shared
        # workdir. Same rule the `plan`/`signals` kinds above use.
        isolate = loop_def.drain.concurrency > 1
        # `state.metric_cursor` (when a state was passed) IS the cursor dict —
        # mutating it below mutates state in place (see the docstring above).
        cursor: dict[str, int] = state.metric_cursor if state is not None else {}

        by_check: dict[str, list[MetricRecord]] = {}
        for record in read_measurements(metrics_path):
            by_check.setdefault(record.check, []).append(record)

        try:
            for check_name in sorted(by_check):
                records = by_check[check_name]
                seen = cursor.get(check_name, 0)
                new_records = records[seen:]
                if not new_records:
                    continue
                # Judge the CURRENT state of the check: its newest not-yet-seen
                # record. If an earlier record in this same window regressed
                # and a later one already recovered (passed=True), there is
                # nothing left to fix — only the newest record decides. A
                # record can only be `passed=False` when a real baseline
                # existed to fail against — the FIRST measurement of a check
                # always passes (see verifier._judge_metric) — so a check with
                # a single measurement can never trip this (Wave 3's "no
                # possible regression" rule falls out for free, no special
                # case needed).
                newest = new_records[-1]
                regressed = newest if not newest.passed else None
                if regressed is not None:
                    # The "baseline it should be judged against": the latest
                    # value the Verifier actually accepted, i.e. the last
                    # known-good reading this regression moved away from.
                    baseline = latest_accepted_measurement(metrics_path, check_name)
                    baseline_value = (
                        baseline.value if baseline is not None else regressed.value
                    )
                    delta_value = regressed.value - baseline_value
                    delta_pct = (
                        (delta_value / baseline_value * 100.0) if baseline_value else 0.0
                    )
                    feedback = (
                        f"Metric check '{check_name}' regressed: baseline (latest "
                        f"accepted) = {baseline_value:g}, latest = {regressed.value:g} "
                        f"(delta={delta_value:+g}, {delta_pct:+.2f}%), recorded during "
                        f"run '{regressed.run}'."
                    )
                    # Reuse build_retry_task's delimited failure-feedback
                    # pattern (queue.py) instead of a second one: a throwaway
                    # base QueueTask carries the preamble + fix instruction,
                    # build_retry_task appends the same header/section a
                    # failed-task retry uses.
                    base_qt = QueueTask(
                        flow=replenish.ref,
                        task=(
                            f"{replenish.task}\n\n"
                            f"Fix the regression on metric check '{check_name}'."
                        ),
                        isolate=isolate,
                    )
                    retry_qt = build_retry_task(base_qt, feedback)
                    plan = ConductorPlan(
                        items=[
                            PlannedUnit(
                                kind="flow", name=replenish.ref, task=retry_qt.task
                            )
                        ]
                    )
                    # Same direct write `alc enqueue`/`signals` use — no second
                    # enqueue path. Detect and propose only: this never touches
                    # git or history, it just queues a demand for the Policy
                    # Gate, isolation, and retry to judge like any other.
                    dispatch_enqueue(
                        plan,
                        manifest,
                        operator_layer,
                        engine_override=engine_override,
                        isolate=isolate,
                        prefix="regression",
                    )
                # Advance the cursor past EVERY record considered this cycle,
                # regressed or not, so the SAME ledger entry is never
                # re-judged on a later cycle — the "must not re-fire" rule.
                cursor[check_name] = len(records)
        except Exception as exc:
            replenish_ok = False
            print(
                f"▶ replenish — regression detection failed: {exc}",
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
    return enqueued, delta, replenish_ok


# ---------------------------------------------------------------------------
# Push notify (roadmap-phase-3.md T12)
# ---------------------------------------------------------------------------


def _notify_stop(manifest: Manifest, loop_name: str, reason: str, cycle: int) -> None:
    """Fire the loop-stop notify hooks for a loop that just transitioned to stopped.

    ``on_loop_stopped`` always fires (any reason); ``on_budget_exceeded`` fires
    additionally when the reason is specifically "budget". manifest.notify absent
    (default) -> both no-op, byte-identical to today.
    """
    notify = manifest.notify
    if notify is None:
        return
    notify_fire(notify.on_loop_stopped, "loop_stopped", loop=loop_name, reason=reason, cycle=cycle)
    if reason == "budget":
        notify_fire(notify.on_budget_exceeded, "budget_exceeded", loop=loop_name, cycle=cycle)


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

    Either stop path fires ``manifest.notify.on_loop_stopped`` (and, when the
    reason is "budget", also ``on_budget_exceeded``) — see ``_notify_stop``.
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
        _notify_stop(manifest, loop_def.name, pre, new_state.cycle)
        return new_state, record

    # (b) Replenish (Mode A only).
    enqueued, delta, replenish_ok = run_replenish(
        manifest, operator_layer, loop_def, engine_override, state=state
    )

    # (c) Drain the queue.
    results = process_queue(
        manifest, operator_layer, max_workers=loop_def.drain.concurrency
    )
    drained = len(results)
    succeeded = sum(1 for r in results if r.success)
    failed = drained - succeeded
    progress = succeeded > 0
    # Honest auto-merge tally: a committing-demand branch either MERGED into main
    # or was LEFT (a conflict). None means the result had no auto-merge branch.
    merged = sum(1 for r in results if r.merged is True)
    left = sum(1 for r in results if r.merged is False)

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
        merged=merged,
        left=left,
        replenish_failed=not replenish_ok,
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
        _notify_stop(manifest, loop_def.name, post, new_state.cycle)

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
    # Surface the honest auto-merge tally only when a committing-demand branch was
    # merged or left this cycle; otherwise stay byte-identical to the old summary.
    if record.merged + record.left > 0:
        line += f" merged={record.merged} left={record.left}"
    # A failed replenish is soft by design (it must not stop the loop or change the
    # exit code) but must never read as a fully successful cycle — surface it.
    if record.replenish_failed:
        line += " replenish=failed"
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
