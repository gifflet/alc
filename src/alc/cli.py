# cli.py — argparse entrypoint for ALC.
# Provides subcommands: `alc init` (supports --setup and --stage), `alc lint`,
# `alc run`, `alc spike`, `alc flow`, `alc tick`, `alc retry`, `alc land`,
# `alc discard`, `alc explore`, `alc compare`, `alc adopt`, `alc conduct`,
# `alc enqueue`, `alc primer`, `alc new`, `alc team`, `alc prompts`, `alc cycle`,
# `alc loop`, `alc specialist`, `alc setup`, `alc status`, `alc runs`,
# `alc audit`, `alc checks`, `alc schedule`, `alc ui`.
from __future__ import annotations

import argparse
import sys
from pathlib import Path


class _ResilientStderr:
    """Wrap a stream so PROGRESS writes never crash the work on a closed reader.

    When ALC runs as a subprocess (the web IDE's exec, a cron drain) and the read
    end of stderr closes mid-run — a cancelled exec, a disconnected client — a
    plain ``print(..., file=sys.stderr)`` raises BrokenPipeError. Unguarded, that
    propagates out of an engine turn and fails the task with a spurious traceback
    (which then becomes a retry's "feedback"). Swallowing the write error keeps a
    broken progress pipe from ever failing the actual work.
    """

    def __init__(self, wrapped: object) -> None:
        self._wrapped = wrapped

    def write(self, s: str) -> int:
        try:
            return self._wrapped.write(s)
        except (BrokenPipeError, OSError):
            return len(s)

    def flush(self) -> None:
        try:
            self._wrapped.flush()
        except (BrokenPipeError, OSError):
            pass

    def __getattr__(self, name: str) -> object:
        return getattr(self._wrapped, name)


def _find_operator_layer() -> Path:
    """Return the .alc/ directory, searching from cwd upward."""
    cwd = Path.cwd()
    for candidate in [cwd, *cwd.parents]:
        alc_dir = candidate / ".alc"
        if alc_dir.is_dir():
            return alc_dir
    # Fall back to cwd/.alc (will fail with a clear error if it does not exist).
    return cwd / ".alc"


def _validate_tier(manifest, tier: str | None) -> str | None:
    """Validate that *tier* exists in manifest.compute_tiers.

    Returns an error message string when the tier is unknown, or None when
    the tier is valid (or when tier is None, meaning no override was requested).
    """
    if tier is None:
        return None
    if tier not in manifest.compute_tiers:
        available = ", ".join(sorted(manifest.compute_tiers))
        return f"unknown compute tier '{tier}'; available: {available}"
    return None


def _print_run_report(report) -> None:
    """Print the human-readable summary and full JSON for a RunReport."""
    status = "SUCCESS" if report.success else "FAILED"
    print(f"Status:   {status}")
    print(f"Engine:   {report.engine}")
    print(f"Attempts: {report.scorecard.passes}")
    print(
        f"Scorecard: span={report.scorecard.span} passes={report.scorecard.passes} "
        f"streak={report.scorecard.streak} touch={report.scorecard.touch}"
    )
    if report.changed_files:
        print("Changed files:")
        for path in report.changed_files:
            print(f"  {path}")
    if report.warnings:
        print("Warnings:")
        for w in report.warnings:
            print(f"  [WARN] {w}")
    print()
    print(report.model_dump_json(indent=2))


def _print_flow_report(report) -> None:
    """Print the human-readable summary and full JSON for a FlowReport."""
    status = "SUCCESS" if report.success else "FAILED"
    print(f"Flow:     {report.flow}")
    print(f"Status:   {status}")
    print(f"Engine:   {report.engine}")
    print(
        f"Scorecard: span={report.scorecard.span} passes={report.scorecard.passes} "
        f"streak={report.scorecard.streak} touch={report.scorecard.touch}"
    )
    print()
    for stage_report in report.stages:
        stage_status = "SUCCESS" if stage_report.success else "FAILED"
        print(
            f"  {stage_report.blueprint} -> {stage_status} "
            f"(passes={stage_report.scorecard.passes})"
        )
        for w in stage_report.warnings:
            print(f"    [WARN] {w}")
    print()
    print(report.model_dump_json(indent=2))


def _print_isolation_result(wt) -> None:
    """Print the post-run isolation summary (committed branch or no-op)."""
    if wt.committed:
        print(
            f"Isolated changes committed on branch: {wt.branch} "
            f"(review and merge from {wt._repo_root})"
        )
    else:
        print("No changes were made; nothing to isolate.")


def _print_skill_result(path: "Path", changed: bool, version: str, engine: str) -> None:
    """Print the outcome of an install_skill() call to stdout."""
    if changed:
        print(f"Installed/updated the ALC skill for {engine} at {path} (alc {version})")
    else:
        print(f"ALC skill for {engine} already up to date at {path} (alc {version})")


def _print_variant_table(rows: list[dict]) -> None:
    """Print one block per variant (`alc explore` / `alc compare`): branch, checks,
    scorecard, cost/usage, and diffstat — the shape ``variant_row`` builds.
    """
    for i, row in enumerate(rows, start=1):
        status = "SUCCESS" if row["success"] else "FAILED"
        header = f"Variant {i}  branch={row['branch']}"
        if row["engine"]:
            header += f"  engine={row['engine']}"
        if row["tier"]:
            header += f"  tier={row['tier']}"
        print(header)
        print(f"  Status:    {status}")
        print(f"  Checks:    {row['checks']}")
        sc = row["scorecard"]
        if sc:
            print(
                f"  Scorecard: span={sc['span']} passes={sc['passes']} "
                f"streak={sc['streak']} touch={sc['touch']}"
            )
        usage = row["usage"]
        if usage:
            print(
                f"  Usage:     input={usage['input_tokens']} output={usage['output_tokens']} "
                f"cost_usd={usage['cost_usd']}"
            )
        ds = row["diffstat"]
        if ds:
            print(
                f"  Diffstat:  +{ds['adds']}/-{ds['dels']} ({ds['files_deleted']} file(s) deleted)"
            )
        print()


def cmd_setup(args: argparse.Namespace) -> int:
    """Run `alc setup [--engine NAME]`: install/update the user-level editor skill."""
    from alc.setup_skill import _resolve_version, install_skill

    try:
        path, changed = install_skill(engine=args.engine)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] could not install the ALC skill: {exc}", file=sys.stderr)
        return 1

    _print_skill_result(path, changed, _resolve_version(), args.engine)
    return 0


# Pack combo `alc init --stage NAME` hires — sugar over `alc team hire`, not a
# new install path. `stage` itself has ZERO runtime effect; it only selects
# which packs get hired at init time (see roadmap-phase-2.md's scope decisions).
_STAGE_PACKS: dict[str, list[str]] = {
    "pre-pmf": ["prototyper", "builder", "sweeper"],
    "growth": ["builder", "sweeper", "grower", "maintainer"],
    "strong-pmf": ["sweeper", "grower", "maintainer", "builder"],
}


def _install_stage_packs(project_root: Path, stage: str, force: bool) -> None:
    """Hire every pack in `_STAGE_PACKS[stage]`; never hard-fails.

    A pack not yet shipped (a later wave) is reported plainly and skipped rather
    than raising. A pack whose files already exist on disk is also skipped
    (reported) unless `force` is set, mirroring `alc team hire`'s own contract.
    """
    from alc.packs import PACKS, pack_files
    from alc.scaffold import detect_stacks

    stacks = detect_stacks(project_root)
    print(f"Stage '{stage}':")
    for archetype in _STAGE_PACKS[stage]:
        if archetype not in PACKS:
            print(f"  {archetype}: not available yet (a later wave adds this pack).")
            continue

        files = pack_files(archetype, stacks)
        existing = sorted(rel for rel in files if (project_root / rel).exists())
        if existing and not force:
            print(
                f"  {archetype}: already has file(s) on disk "
                f"({', '.join(existing)}); pass --force to overwrite."
            )
            continue

        for rel_path, content in sorted(files.items()):
            target = project_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        print(f"  {archetype}: hired ({', '.join(sorted(files))})")


def cmd_init(args: argparse.Namespace) -> int:
    """Run `alc init [--force] [--setup] [--stage pre-pmf|growth|strong-pmf]`.

    Scaffolds a default Operator Layer into cwd. `--stage` additionally hires the
    pack combo for that stage's mix (`_STAGE_PACKS`) via the same file-writing
    contract as `alc team hire`. Without it, only a discovery hint is printed —
    no pack is installed unless explicitly asked (opt-in byte-identical `init`).
    """
    from alc.scaffold import detect_stack, scaffold

    project_root = Path.cwd()
    try:
        created = scaffold(project_root, force=args.force)
    except FileExistsError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print("Initialised Operator Layer:")
    for path in created:
        print(f"  {path}")

    stack_label, _checks_block = detect_stack(project_root)
    if stack_label is not None:
        # Derive a short description of the real checks from the stack label.
        _stack_checks = {
            "Go": "go build, go vet",
            "Python": "pytest",
            "Node": "npm test",
            "Rust": "cargo check",
        }
        checks_desc = _stack_checks.get(stack_label, "real checks")
        print(f"Detected {stack_label} — scaffolded real checks ({checks_desc}).")

    if args.stage:
        _install_stage_packs(project_root, args.stage, args.force)
    else:
        print(
            "Archetype Packs (test authoring, dead-code sweeps, dependency "
            "patrol, …) are available via `alc team hire <archetype>`. "
            "See: alc team list"
        )

    if args.setup:
        from alc.setup_skill import _resolve_version, install_skill

        try:
            skill_path, changed = install_skill(engine=args.engine)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"[ERROR] could not install the ALC skill: {exc}", file=sys.stderr)
            return 1
        _print_skill_result(skill_path, changed, _resolve_version(), args.engine)

    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    """Run `alc lint`: check the Operator Layer for Policy Gate violations."""
    from alc.intake import load_all_blueprints, load_manifest
    from alc.policy import has_errors, lint, validate_provisions, validate_prompts
    from alc.stagepolicy import lint_stage

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    blueprints = load_all_blueprints(manifest, operator_layer)
    violations = lint(manifest, blueprints)
    violations += validate_prompts(manifest, operator_layer, blueprints)
    violations += validate_provisions(manifest, operator_layer.parent)
    violations += lint_stage(manifest, blueprints)

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json([
            {"rule": v.rule, "severity": v.severity, "message": v.message}
            for v in violations
        ])
        return 1 if has_errors(violations) else 0

    if not violations:
        print("No violations found. Operator Layer is conformant.")
        return 0

    for v in violations:
        tag = "[ERROR]" if v.severity == "error" else "[WARN] "
        print(f"{tag} [{v.rule}] {v.message}")

    if has_errors(violations):
        return 1
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run `alc run <blueprint> "<task>" [--engine NAME] [--isolate]`."""
    from alc.bundle import summarize_bundle, write_bundle
    from alc.commitmsg import make_commit_message_provider
    from alc.events import bind_run_log, new_run_log_path
    from alc.intake import load_blueprint, load_manifest
    from alc.primer import load_primer
    from alc.runner import MandateRunner, PolicyViolationError
    from alc.worktree import IsolatedWorktree, git_toplevel, is_git_repo

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    blueprints_dir = operator_layer.parent / manifest.blueprints_dir
    blueprint = load_blueprint(blueprints_dir, args.blueprint)

    # Validate --tier early before any work is done.
    tier_err = _validate_tier(manifest, args.tier)
    if tier_err:
        print(f"[ERROR] {tier_err}", file=sys.stderr)
        return 1

    if args.tier:
        blueprint = blueprint.model_copy(update={"compute_tier": args.tier})

    runner = MandateRunner(manifest=manifest, operator_layer=operator_layer)

    # Per-run event log, resolved against the original project BEFORE any worktree.
    run_log = new_run_log_path(
        operator_layer.parent / manifest.runs_dir, "run", f"{args.blueprint} {args.task}"
    )

    # Build extra_context from --primer and/or --from-bundle before branching.
    parts: list[str] = []
    if args.primer:
        primers_dir = operator_layer.parent / manifest.primers_dir
        try:
            parts.append(f"### Primer: {args.primer}\n" + load_primer(primers_dir, args.primer))
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    if args.from_bundle:
        bundles_dir = operator_layer.parent / manifest.bundles_dir
        ref = Path(args.from_bundle)
        if not ref.exists():
            ref = bundles_dir / f"{args.from_bundle}.jsonl"
        try:
            parts.append(
                "### Prior run (bundle)\n"
                + summarize_bundle(ref, max_output_chars=manifest.bundle_output_chars)
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    extra_context: str | None = "\n\n".join(parts) if parts else None

    use_isolate = args.isolate
    if blueprint.mode == "spike":
        # T1: the ONE relaxation of the checks gate comes fenced — force
        # isolation regardless of --isolate so a spike's edits are never made
        # directly against the operator's working tree.
        use_isolate = True
    if use_isolate and not is_git_repo(Path.cwd()):
        print("--isolate ignored: not inside a git repository", file=sys.stderr)
        use_isolate = False

    if use_isolate:
        repo_root = git_toplevel(Path.cwd())
        wt = IsolatedWorktree(
            repo_root,
            label="run",
            commit_message=manifest.worktree_commit_message,
            message_provider=make_commit_message_provider(
                manifest=manifest,
                operator_layer=operator_layer,
                workdir=repo_root,
                fallback=manifest.worktree_commit_message,
                engine_override=args.engine,
            ),
        )
        # Use the context manager manually so we can inspect wt after __exit__.
        wt_path = wt.__enter__()
        exc_info = (None, None, None)
        report = None
        try:
            with bind_run_log(run_log):
                report = runner.run(
                    blueprint=blueprint,
                    task=args.task,
                    engine_override=args.engine,
                    workdir=wt_path,
                    extra_context=extra_context,
                )
        except PolicyViolationError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            exc_info = (type(exc), exc, exc.__traceback__)
        except BaseException as exc:
            exc_info = (type(exc), exc, exc.__traceback__)
        finally:
            if blueprint.mode == "spike":
                # The exception must never become a delivery path: never commit,
                # discard the branch regardless of outcome.
                wt.commit_on_exit = False
            wt.__exit__(*exc_info)

        # Re-raise non-PolicyViolation exceptions after cleanup.
        if exc_info[1] is not None and not isinstance(exc_info[1], PolicyViolationError):
            raise exc_info[1]

        if report is None:
            # PolicyViolationError path.
            return 1

        _print_run_report(report)
        _print_isolation_result(wt)
        if args.bundle:
            bundles_dir = operator_layer.parent / manifest.bundles_dir
            path = write_bundle(bundles_dir, args.blueprint, args.task, report)
            print(f"Bundle written: {path}")
        return 0 if report.success else 1

    # Non-isolated path (default).
    try:
        with bind_run_log(run_log):
            report = runner.run(
                blueprint=blueprint,
                task=args.task,
                engine_override=args.engine,
                extra_context=extra_context,
            )
    except PolicyViolationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    _print_run_report(report)
    if args.bundle:
        bundles_dir = operator_layer.parent / manifest.bundles_dir
        path = write_bundle(bundles_dir, args.blueprint, args.task, report)
        print(f"Bundle written: {path}")
    return 0 if report.success else 1


def cmd_spike(args: argparse.Namespace) -> int:
    """Run `alc spike "<task>" [--engine NAME]`.

    Sugar over `alc run spike "<task>"`: no blueprint name to remember, no
    isolate/commit ceremony to opt into — the Prototyper pack's `spike`
    Blueprint declares `mode: spike`, which cmd_run itself fences (forced
    isolation, zero repairs, no commit; see runner.py). This wrapper only
    fills in the Blueprint name and the flags `alc run` exposes that a spike
    has no use for.
    """
    args.blueprint = "spike"
    args.isolate = False  # irrelevant: mode: spike forces isolation in cmd_run
    args.primer = None
    args.bundle = False
    args.from_bundle = None
    args.tier = None
    return cmd_run(args)


def _failure_reason(result, queue_dir) -> str:
    """Build a human-readable explanation string for a failed TickResult.

    Extracts the tail of the last executed stage's output_text (up to 400
    characters, prefixed with '…' when truncated) and appends a pointer to
    the Gate report JSON.  Used in cmd_tick to surface WHY a unit failed.

    Args:
        result: A TickResult whose ``success`` is False.
        queue_dir: The queue directory Path (used to build the report pointer).

    Returns:
        A multi-line string with indented tail output and the report pointer.
    """
    report = result.report
    pointer = f"    see: {queue_dir}/done/{Path(result.task_file).stem}.report.json"

    if not report.stages:
        return pointer

    last_stage = report.stages[-1]
    if not last_stage.output_text:
        return pointer

    text = last_stage.output_text
    if len(text) > 400:
        tail = "…" + text[-400:]
    else:
        tail = text

    # Indent every line of the tail by 4 spaces.
    indented = "\n".join("    " + line for line in tail.splitlines())
    return indented + "\n" + pointer


def cmd_tick(args: argparse.Namespace) -> int:
    """Run `alc tick`: drain the task queue (Unattended Mode Trigger).

    Processes every pending *.yaml file in queue_dir once and exits. Designed
    to be called by cron or launchd — cron provides the cadence; this command
    provides one drain pass. Exit code is 0 for all task outcomes (cron-friendly);
    per-task outcomes live in the Gate reports under done/. Exit code is 1 only
    for invalid usage (e.g. --concurrency < 1).
    """
    if args.concurrency < 1:
        print("[ERROR] --concurrency must be >= 1", file=sys.stderr)
        return 1

    from alc.intake import load_manifest
    from alc.lock import tick_lock
    from alc.queue import process_queue

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    queue_dir = operator_layer.parent / manifest.queue_dir
    if not queue_dir.exists():
        print("No pending tasks.")
        return 0

    # Serialise overlapping ticks (e.g. cron firing again before the prior run
    # finished) so a task is never processed twice.
    with tick_lock(queue_dir / ".lock") as acquired:
        if not acquired:
            print("Another tick is already in progress; skipping.")
            return 0
        results = process_queue(manifest, operator_layer, max_workers=args.concurrency)

    if not results:
        print("No pending tasks.")
        return 0

    for result in results:
        status = "SUCCESS" if result.success else "FAILED"
        line = f"{result.task_file}: {result.flow} -> {status}"
        if result.branch:
            line += f" (branch {result.branch})"
        print(line)
        if not result.success:
            print(_failure_reason(result, queue_dir))

    return 0


def cmd_conduct(args: argparse.Namespace) -> int:
    """Run `alc conduct "<goal>" [--engine NAME] [--enqueue] [--strict-stage]`."""
    import sys

    from alc.conduct import conduct
    from alc.intake import load_manifest
    from alc.runner import PolicyViolationError

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    try:
        report = conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal=args.goal,
            engine_override=args.engine,
            enqueue=args.enqueue,
            parallel=args.parallel,
            concurrency=args.concurrency,
            tier=args.tier,
            strict_stage=getattr(args, "strict_stage", False),
        )
    except ValueError as exc:
        print(f"[ERROR] Conductor could not produce a valid plan: {exc}", file=sys.stderr)
        return 1
    except PolicyViolationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Summary header.
    print(f"Goal: {report.goal}")
    print()
    print("Plan:")
    for item in report.plan.items:
        print(f"  -> {item.name} ({item.kind}): {item.task}")
    print()
    for warning in report.warnings:
        print(f"[WARN] {warning}", file=sys.stderr)

    if report.mode == "run":
        # Parallel dispatch reports per-unit outcomes; serial reports flow outcomes.
        for unit in report.units:
            status = "SUCCESS" if unit.success else "FAILED"
            print(f"  {unit.name} ({unit.kind}) -> {status}")
        for flow_report in report.flow_reports:
            status = "SUCCESS" if flow_report.success else "FAILED"
            print(f"  {flow_report.flow} -> {status}")
        print()
        print(report.model_dump_json(indent=2))
        return 0 if report.success else 1

    # Enqueue mode.
    n = len(report.enqueued_files)
    files_str = ", ".join(report.enqueued_files)
    print(f"Enqueued {n} task(s): {files_str}")
    print()
    print(report.model_dump_json(indent=2))
    return 0


def _resolve_loop(args: argparse.Namespace):
    """Shared cycle/loop setup: resolve operator layer, manifest, loop def, and paths.

    Returns a (manifest, operator_layer, loop_def, loops, spath, error_code) tuple.
    ``error_code`` is an int exit code when setup failed (loop file missing or a
    Policy Gate violation), else None. When error_code is set, the other fields
    may be partially populated and must not be used.
    """
    from alc.intake import load_loop, load_manifest
    from alc.loop import loops_dir, state_path
    from alc.policy import validate_loop

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    loops = loops_dir(manifest, operator_layer)

    try:
        loop_def = load_loop(loops, args.name)
    except FileNotFoundError:
        print(f"[ERROR] No loop named '{args.name}' in {loops}", file=sys.stderr)
        return None, None, None, None, None, 1

    violations = validate_loop(manifest, operator_layer, loop_def)
    if violations:
        for v in violations:
            print(f"[ERROR] [{v.rule}] {v.message}", file=sys.stderr)
        return None, None, None, None, None, 1

    return manifest, operator_layer, loop_def, loops, state_path(loops, args.name), None


def cmd_cycle(args: argparse.Namespace) -> int:
    """Run `alc cycle <name>`: run exactly ONE autonomous loop cycle (cron target)."""
    from alc.loop import (
        format_cycle_summary,
        load_loop_state,
        reset_loop_state,
        run_cycle,
        save_loop_state,
    )

    manifest, operator_layer, loop_def, _loops, spath, err = _resolve_loop(args)
    if err is not None:
        return err

    state = load_loop_state(spath, args.name)

    if args.status:
        if getattr(args, "json", False):
            from alc.output import emit_json

            emit_json(state.model_dump())
            return 0
        print(f"Loop:                    {state.name}")
        print(f"Status:                  {state.status}")
        print(f"Cycle:                   {state.cycle}")
        print(f"Consecutive no-progress: {state.consecutive_no_progress}")
        if state.budget_used:
            used = ", ".join(f"{k}={v}" for k, v in state.budget_used.items())
            print(f"Budget used:             {used}")
        if state.stopped_reason:
            print(f"Stopped reason:          {state.stopped_reason}")
        return 0

    if args.reset:
        # Reset THEN run: replace the state with a fresh pending one and fall through
        # so this invocation runs one cycle on the fresh state (from pending).
        state = reset_loop_state(spath, args.name)
        print(f"Loop '{args.name}' reset.")

    if state.status == "stopped":
        print(
            f"Loop '{args.name}' already stopped: {state.stopped_reason}. "
            "Use --reset to restart."
        )
        return 0

    # A per-invocation --concurrency > 0 overrides the definition's drain concurrency.
    if args.concurrency and args.concurrency > 0:
        loop_def = loop_def.model_copy(
            update={"drain": loop_def.drain.model_copy(update={"concurrency": args.concurrency})}
        )

    state, record = run_cycle(
        manifest, operator_layer, loop_def, state, engine_override=args.engine
    )
    save_loop_state(spath, state)
    print(format_cycle_summary(record))
    return 0


def cmd_loop(args: argparse.Namespace) -> int:
    """Run `alc loop <name> [--interval S]`: foreground wrapper repeating cycles."""
    import time

    from alc.loop import (
        format_cycle_summary,
        load_loop_state,
        reset_loop_state,
        run_cycle,
        save_loop_state,
    )

    manifest, operator_layer, loop_def, _loops, spath, err = _resolve_loop(args)
    if err is not None:
        return err

    state = load_loop_state(spath, args.name)
    if args.reset:
        # Reset THEN loop: start the repeating drain from a fresh pending state,
        # symmetric with `alc cycle --reset` (both share reset_loop_state).
        state = reset_loop_state(spath, args.name)
        print(f"Loop '{args.name}' reset.")
    if state.status == "stopped":
        print(
            f"Loop '{args.name}' already stopped: {state.stopped_reason}. "
            "Use --reset to restart."
        )
        return 0

    while True:
        state, record = run_cycle(
            manifest, operator_layer, loop_def, state, engine_override=args.engine
        )
        save_loop_state(spath, state)
        print(format_cycle_summary(record))
        if state.status == "stopped":
            break
        if args.interval > 0:
            time.sleep(args.interval)

    print(f"Loop '{args.name}' stopped: {state.stopped_reason}")
    return 0


def cmd_primer(args: argparse.Namespace) -> int:
    """Run `alc primer new <name> [--force]`: scaffold a new Primer file."""
    from alc.intake import load_manifest
    from alc.primer import new_primer

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    primers_dir = operator_layer.parent / manifest.primers_dir

    try:
        path = new_primer(primers_dir, args.name, force=args.force)
    except FileExistsError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(path)
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    """Run `alc new <kind> <name> [--force] [--from NAME]`: author a unit from a core scaffold.

    ``kind`` is one of blueprint/flow/specialist/loop/primer; the target
    directory comes from the manifest. Refuses to overwrite an existing unit
    without ``--force``. The payload is validated through the collection's real
    loader (same temp-dir trick as ``alc.ui.collections._parse_raw``) BEFORE
    anything is written, so an invalid payload never touches disk — primers have
    no structured loader, so any text is valid for them, same as in the UI.
    ``--from NAME`` clones an existing unit of the same kind, replacing its
    ``name:`` field.
    """
    import re
    import tempfile

    from alc.authoring import scaffold_text
    from alc.intake import (
        load_blueprint,
        load_flow,
        load_loop,
        load_manifest,
        load_specialist,
    )

    dir_attr = {
        "blueprint": "blueprints_dir",
        "flow": "flows_dir",
        "specialist": "specialists_dir",
        "loop": "loops_dir",
        "primer": "primers_dir",
    }[args.kind]
    suffix = ".md" if args.kind in ("blueprint", "primer") else ".yaml"
    loader = {
        "blueprint": load_blueprint,
        "flow": load_flow,
        "specialist": load_specialist,
        "loop": load_loop,
    }.get(args.kind)

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    directory = operator_layer.parent / getattr(manifest, dir_attr)
    path = directory / f"{args.name}{suffix}"

    if path.exists() and not args.force:
        print(
            f"[ERROR] {args.kind} '{args.name}' already exists: {path}; "
            "pass --force to overwrite",
            file=sys.stderr,
        )
        return 1

    if args.from_name:
        source = directory / f"{args.from_name}{suffix}"
        if not source.is_file():
            print(
                f"[ERROR] no {args.kind} named '{args.from_name}' to clone from",
                file=sys.stderr,
            )
            return 1
        raw = re.sub(
            r"^name:.*$", f"name: {args.name}", source.read_text(), count=1, flags=re.MULTILINE
        )
    else:
        raw = scaffold_text(f"{args.kind}s", args.name)

    if loader is not None:
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / f"{args.name}{suffix}").write_text(raw)
            try:
                loader(Path(td), args.name)
            except Exception as exc:  # noqa: BLE001 — surface any parse/validation error
                print(f"[ERROR] invalid {args.kind} '{args.name}': {exc}", file=sys.stderr)
                return 1

    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(raw)
    print(path)
    return 0


def cmd_team(args: argparse.Namespace) -> int:
    """Run `alc team hire|list|retire|status`: the operator verb over Archetype Packs.

    Packs (``alc.packs``) are the implementation; ``team`` is the only verb an
    operator sees — ``hire`` scaffolds a pack's files then lints, ``list``/
    ``status`` show the hired roster (and the state of any loops a member
    brought), ``retire`` archives a member's loop definition(s) instead of
    deleting them.
    """
    if args.team_action == "hire":
        return _team_hire(args)
    if args.team_action == "retire":
        return _team_retire(args)
    return _team_roster(args)  # 'list' and 'status' share the same roster output


def _team_hire(args: argparse.Namespace) -> int:
    """`alc team hire <archetype> [--force]`: scaffold a pack's files, then lint."""
    from alc.intake import load_all_blueprints, load_manifest
    from alc.packs import PACKS, pack_files
    from alc.policy import has_errors, lint, validate_prompts, validate_provisions
    from alc.scaffold import detect_stacks
    from alc.stagepolicy import lint_stage

    if args.archetype not in PACKS:
        available = ", ".join(sorted(PACKS)) or "none yet"
        print(
            f"[ERROR] no pack named '{args.archetype}' yet (available: {available})",
            file=sys.stderr,
        )
        return 1

    operator_layer = _find_operator_layer()
    project_root = operator_layer.parent
    manifest = load_manifest(operator_layer)

    files = pack_files(args.archetype, detect_stacks(project_root))

    if not args.force:
        existing = sorted(rel for rel in files if (project_root / rel).exists())
        if existing:
            print(
                f"[ERROR] '{args.archetype}' already has file(s) on disk: "
                f"{', '.join(existing)}; pass --force to overwrite",
                file=sys.stderr,
            )
            return 1

    for rel_path, content in sorted(files.items()):
        target = project_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    print(f"Hired '{args.archetype}':")
    for rel_path in sorted(files):
        print(f"  {rel_path}")

    blueprints = load_all_blueprints(manifest, operator_layer)
    violations = lint(manifest, blueprints)
    violations += validate_prompts(manifest, operator_layer, blueprints)
    violations += validate_provisions(manifest, project_root)
    violations += lint_stage(manifest, blueprints)

    if not violations:
        print("No violations found. Operator Layer is conformant.")
    else:
        for v in violations:
            tag = "[ERROR]" if v.severity == "error" else "[WARN] "
            print(f"{tag} [{v.rule}] {v.message}")

    return 1 if has_errors(violations) else 0


def _print_mix_health(health) -> None:
    """Print `alc team status`'s Mix Health section (roadmap-phase-4.md T6).

    `total_runs == 0` renders as "no data yet" — never a division by zero or a
    misleading all-zero table. With no `stage` declared, the breakdown is
    printed but never judged (no core/secondary/off-mix labels).
    """
    print()
    if health.total_runs == 0:
        print(
            "Mix Health: no data yet — drain the queue (`alc tick`) to populate "
            "archived reports."
        )
        return

    if health.stage is None:
        print("Mix Health (no stage declared — breakdown only, not judged):")
    else:
        print(
            f"Mix Health (stage: {health.stage}; "
            f"core={health.core} secondary={health.secondary}):"
        )

    seen: set[str | None] = set()
    for entry in health.by_archetype:
        label = ""
        if health.stage is not None:
            if entry.archetype in health.core:
                label = "  [core]"
            elif entry.archetype in health.secondary:
                label = "  [secondary]"
            elif entry.archetype is not None:
                label = "  [off-mix]"
        name = entry.archetype or "(none)"
        seen.add(entry.archetype)
        print(
            f"  {name:<12} runs={entry.runs} span={entry.span} "
            f"cost_usd={entry.cost_usd:.4f} net_lines={entry.net_lines:+d}{label}"
        )

    if health.stage is not None:
        for archetype in health.core:
            if archetype not in seen:
                print(
                    f"  {archetype:<12} runs=0 — core archetype never exercised yet; "
                    f"hint: alc team hire {archetype}"
                )


def _team_roster(args: argparse.Namespace) -> int:
    """`alc team list|status`: the hired roster and the state of loops each member
    brought. `status` additionally reports Mix Health (roadmap-phase-4.md T6):
    archived reports' real archetype spend against the declared stage's target
    mix — `list` stays roster-only.
    """
    from alc.intake import load_manifest
    from alc.loop import load_loop_state, loops_dir, state_path
    from alc.packs import PACKS, pack_files
    from alc.scaffold import detect_stacks

    operator_layer = _find_operator_layer()
    project_root = operator_layer.parent
    manifest = load_manifest(operator_layer)
    stacks = detect_stacks(project_root)
    loops_directory = loops_dir(manifest, operator_layer)
    loops_prefix = f"{manifest.loops_dir}/"

    roster = []
    for archetype in sorted(PACKS):
        files = pack_files(archetype, stacks)
        present = sorted(rel for rel in files if (project_root / rel).exists())
        if not present:
            continue  # not hired

        member_loops = []
        for rel_path in sorted(files):
            if rel_path.startswith(loops_prefix) and rel_path.endswith(".yaml"):
                loop_name = Path(rel_path).stem
                state = load_loop_state(state_path(loops_directory, loop_name), loop_name)
                member_loops.append(
                    {
                        "name": state.name,
                        "status": state.status,
                        "cycle": state.cycle,
                        "stopped_reason": state.stopped_reason,
                    }
                )
        roster.append({"archetype": archetype, "files": present, "loops": member_loops})

    health = None
    if args.team_action == "status":
        from alc.stagepolicy import mix_health

        done_dir = project_root / manifest.queue_dir / "done"
        health = mix_health(done_dir, manifest)

    if getattr(args, "json", False):
        from dataclasses import asdict

        from alc.output import emit_json

        if health is not None:
            emit_json({"roster": roster, "mix_health": asdict(health)})
        else:
            emit_json(roster)
        return 0

    if not roster:
        print("No members hired yet. Run: alc team hire <archetype>")
    else:
        print("Hired members:")
        for member in roster:
            print(f"  {member['archetype']}")
            for rel_path in member["files"]:
                print(f"    {rel_path}")
            if member["loops"]:
                for loop in member["loops"]:
                    line = f"    loop {loop['name']}: {loop['status']} (cycle {loop['cycle']})"
                    if loop["status"] == "stopped":
                        line += f", stopped_reason={loop['stopped_reason']}"
                    print(line)
            else:
                print("    loops: (none)")

    if health is not None:
        _print_mix_health(health)

    return 0


def _team_retire(args: argparse.Namespace) -> int:
    """`alc team retire <member>`: archive that member's loop definition(s), never delete."""
    from alc.intake import load_manifest
    from alc.loop import loops_dir
    from alc.packs import PACKS, pack_files
    from alc.scaffold import detect_stacks

    if args.member not in PACKS:
        available = ", ".join(sorted(PACKS)) or "none yet"
        print(
            f"[ERROR] no pack named '{args.member}' yet (available: {available})",
            file=sys.stderr,
        )
        return 1

    operator_layer = _find_operator_layer()
    project_root = operator_layer.parent
    manifest = load_manifest(operator_layer)
    loops_prefix = f"{manifest.loops_dir}/"

    files = pack_files(args.member, detect_stacks(project_root))
    loop_files = sorted(
        rel for rel in files if rel.startswith(loops_prefix) and rel.endswith(".yaml")
    )

    retired_dir = loops_dir(manifest, operator_layer) / "retired"
    moved: list[str] = []
    for rel_path in loop_files:
        src = project_root / rel_path
        if not src.exists():
            continue
        retired_dir.mkdir(parents=True, exist_ok=True)
        dest = retired_dir / src.name
        src.rename(dest)
        moved.append(str(dest.relative_to(project_root)))

    if not moved:
        print(f"'{args.member}' has no loop(s) on disk to retire.")
        return 0

    print(f"Retired '{args.member}':")
    for rel_path in moved:
        print(f"  {rel_path}")
    return 0


def cmd_prompts(args: argparse.Namespace) -> int:
    """Run `alc prompts <action>`: list or eject keyed prompt overrides."""
    from alc.intake import load_manifest
    from alc.prompts import eject_prompt, list_prompts

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    if args.action == "list":
        entries = list_prompts(operator_layer, manifest)
        if getattr(args, "json", False):
            from dataclasses import asdict

            from alc.output import emit_json

            emit_json([asdict(e) for e in entries])
            return 0
        reserved = [e for e in entries if e.kind == "reserved"]
        free = [e for e in entries if e.kind == "free"]
        print("Reserved prompts:")
        for e in reserved:
            print(f"  {e.name}: {e.source}")
        print("Free prompts:")
        if free:
            for e in free:
                print(f"  {e.name}")
        else:
            print("  (none)")
        return 0

    # action == "eject"
    try:
        path = eject_prompt(args.name, operator_layer, manifest, force=args.force)
    except KeyError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except FileExistsError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(path)
    return 0


def cmd_specialist(args: argparse.Namespace) -> int:
    """Run `alc specialist <name> "<task>" [--engine NAME]`."""
    from alc.events import bind_run_log, new_run_log_path
    from alc.intake import load_manifest, load_specialist
    from alc.specialist import run_specialist

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    specialists_dir = operator_layer.parent / manifest.specialists_dir
    specialist = load_specialist(specialists_dir, args.name)

    run_log = new_run_log_path(
        operator_layer.parent / manifest.runs_dir, "specialist", f"{args.name} {args.task}"
    )
    with bind_run_log(run_log):
        report = run_specialist(
            manifest=manifest,
            operator_layer=operator_layer,
            specialist=specialist,
            task=args.task,
            engine_override=args.engine,
        )

    act_status = "SUCCESS" if report.act.success else "FAILED"
    knowledge_status = "yes" if report.knowledge_updated else "no"
    print(f"Specialist: {report.specialist}")
    print(f"Act: {act_status}")
    print(f"Knowledge updated: {knowledge_status}")
    print()
    print(report.model_dump_json(indent=2))

    return 0 if report.act.success else 1


def cmd_flow(args: argparse.Namespace) -> int:
    """Run `alc flow <flow_name> "<task>" [--engine NAME] [--isolate]`."""
    from alc.bundle import summarize_bundle, write_bundle
    from alc.commitmsg import make_commit_message_provider
    from alc.events import bind_run_log, new_run_log_path
    from alc.flow import FlowRunner
    from alc.intake import load_flow, load_manifest
    from alc.primer import load_primer
    from alc.runner import PolicyViolationError
    from alc.worktree import IsolatedWorktree, git_toplevel, is_git_repo

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    flows_dir = operator_layer.parent / manifest.flows_dir
    flow = load_flow(flows_dir, args.flow_name)

    # Validate --tier early before any work is done.
    tier_err = _validate_tier(manifest, args.tier)
    if tier_err:
        print(f"[ERROR] {tier_err}", file=sys.stderr)
        return 1

    runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)

    # Per-run event log, resolved against the original project BEFORE any worktree.
    run_log = new_run_log_path(
        operator_layer.parent / manifest.runs_dir, "flow", f"{args.flow_name} {args.task}"
    )

    # Build extra_context from --primer and/or --from-bundle before branching.
    parts: list[str] = []
    if args.primer:
        primers_dir = operator_layer.parent / manifest.primers_dir
        try:
            parts.append(f"### Primer: {args.primer}\n" + load_primer(primers_dir, args.primer))
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    if args.from_bundle:
        bundles_dir = operator_layer.parent / manifest.bundles_dir
        ref = Path(args.from_bundle)
        if not ref.exists():
            ref = bundles_dir / f"{args.from_bundle}.jsonl"
        try:
            parts.append(
                "### Prior run (bundle)\n"
                + summarize_bundle(ref, max_output_chars=manifest.bundle_output_chars)
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    extra_context: str | None = "\n\n".join(parts) if parts else None

    use_isolate = args.isolate
    if use_isolate and not is_git_repo(Path.cwd()):
        print("--isolate ignored: not inside a git repository", file=sys.stderr)
        use_isolate = False

    # A committing flow (flow.commit.enabled) run under worktree isolation is
    # committed ONCE by the worktree exit-commit — using the demand's own
    # rendered message, excluding `.alc/` — instead of also firing the
    # FlowRunner's terminal commit (skip_commit=True below reconciles the two).
    # This mirrors the committing-demand path `queue.py` already runs in
    # production (queue.py:345-424). A flow with no commit block takes the
    # `else` branch below, byte-identical to before.
    is_committing_demand = use_isolate and flow.commit is not None and flow.commit.enabled
    demand_message = manifest.worktree_commit_message
    if is_committing_demand:
        try:
            demand_message = flow.commit.message.format(
                name=flow.name,
                task=(args.task.splitlines()[0] if args.task else ""),
            )
        except (KeyError, IndexError, ValueError):
            demand_message = f"chore(cycle): {flow.name}"

    if use_isolate:
        repo_root = git_toplevel(Path.cwd())
        wt = IsolatedWorktree(
            repo_root,
            label="flow",
            commit_message=demand_message,
            exclude_paths=((".alc/",) if is_committing_demand else ()),
            message_provider=make_commit_message_provider(
                manifest=manifest,
                operator_layer=operator_layer,
                workdir=repo_root,
                fallback=demand_message,
                engine_override=args.engine,
            ),
        )
        wt_path = wt.__enter__()
        exc_info = (None, None, None)
        report = None
        try:
            with bind_run_log(run_log):
                report = runner.run(
                    flow=flow,
                    task=args.task,
                    engine_override=args.engine,
                    workdir=wt_path,
                    extra_context=extra_context,
                    tier_override=args.tier,
                    skip_commit=is_committing_demand,
                )
        except PolicyViolationError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            exc_info = (type(exc), exc, exc.__traceback__)
        except BaseException as exc:
            exc_info = (type(exc), exc, exc.__traceback__)
        finally:
            # For a committing demand the worktree owns the single commit: keep
            # it only on flow SUCCESS, otherwise discard the branch (a failed or
            # exception-raising run leaves report None/unsuccessful -> discard).
            # A non-committing isolate flow leaves commit_on_exit at its True
            # default -> today's behavior (commit iff changes).
            if is_committing_demand:
                wt.commit_on_exit = report is not None and report.success
            wt.__exit__(*exc_info)

        if exc_info[1] is not None and not isinstance(exc_info[1], PolicyViolationError):
            raise exc_info[1]

        if report is None:
            return 1

        _print_flow_report(report)
        _print_isolation_result(wt)
        if args.bundle:
            bundles_dir = operator_layer.parent / manifest.bundles_dir
            path = write_bundle(bundles_dir, args.flow_name, args.task, report)
            print(f"Bundle written: {path}")
        return 0 if report.success else 1

    # Non-isolated path (default).
    try:
        with bind_run_log(run_log):
            report = runner.run(
                flow=flow,
                task=args.task,
                engine_override=args.engine,
                extra_context=extra_context,
                tier_override=args.tier,
            )
    except PolicyViolationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    _print_flow_report(report)
    if args.bundle:
        bundles_dir = operator_layer.parent / manifest.bundles_dir
        path = write_bundle(bundles_dir, args.flow_name, args.task, report)
        print(f"Bundle written: {path}")
    return 0 if report.success else 1


def _retry_one(stem: str, manifest, operator_layer: Path) -> int:
    """Re-enqueue one failed task by its done/ filename stem; return an exit code.

    Reads the archived task + report under ``<queue_dir>/done/``, appends the
    failing stage's output to the task, and writes a new pending queue file.
    Shared by the single-stem (`alc retry <stem>`) and `--all` paths.
    """
    import yaml

    from alc.models import FlowReport, QueueTask
    from alc.queue import build_retry_task, failure_feedback, write_retry_task

    done_dir = operator_layer.parent / manifest.queue_dir / "done"

    for suffix in (".report.json", ".yaml"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]

    task_file = done_dir / f"{stem}.yaml"
    report_file = done_dir / f"{stem}.report.json"
    if not task_file.exists() or not report_file.exists():
        print(
            f"[ERROR] no archived task + report for '{stem}' under {done_dir}",
            file=sys.stderr,
        )
        return 1

    qt = QueueTask.model_validate(yaml.safe_load(task_file.read_text()))
    report = FlowReport.model_validate_json(report_file.read_text())
    if report.success:
        print(f"[ERROR] task '{stem}' succeeded; nothing to retry.", file=sys.stderr)
        return 1

    queue_dir = operator_layer.parent / manifest.queue_dir
    retry_qt = build_retry_task(qt, failure_feedback(report))
    path = write_retry_task(retry_qt, queue_dir, stem)
    print(
        f"Re-enqueued '{stem}' as {path.name} (attempt {retry_qt.retries}) with the "
        f"failure feedback. Run 'alc tick' or 'alc cycle <name>' to execute it."
    )
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    """Run `alc retry [stem] [--all]`: retry failed tasks carrying their feedback.

    - ``<stem>`` given: re-enqueue that single archived failure (unchanged).
    - ``--all`` (no stem): re-enqueue every outstanding failure at once.
    - neither: LIST the outstanding failures (unresolved lineages) so an operator
      doesn't have to know the opaque stem.

    Run `alc tick` / `alc cycle <name>` afterwards to execute re-enqueued tasks.
    """
    from alc.intake import load_manifest
    from alc.queue import outstanding_failures

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    # Single-stem path — the original behavior, unchanged.
    if args.stem:
        return _retry_one(args.stem, manifest, operator_layer)

    done_dir = operator_layer.parent / manifest.queue_dir / "done"
    failures = outstanding_failures(done_dir)

    # --all path — re-enqueue every outstanding failure (even if none, harmless).
    if args.all:
        if not failures:
            print("No failed tasks to retry.")
            return 0
        for failure in failures:
            _retry_one(failure.stem, manifest, operator_layer)
        return 0

    # List path — machine-readable (--json) or human-readable (default).
    if getattr(args, "json", False):
        from dataclasses import asdict

        from alc.output import emit_json

        emit_json([asdict(f) for f in failures])
        return 0

    if not failures:
        print("No failed tasks to retry.")
        return 0
    # One clean block per outstanding failure (most recent first).
    for failure in failures:
        print(f"{failure.stem}   (attempt {failure.retries})")
        print(f"  {failure.title}")
        print(f"  {failure.reason}")
        print()
    print("Run: alc retry <stem>   (or: alc retry --all)")
    return 0


def _enqueue_entries_from_file(path: Path) -> list[dict]:
    """Read batch entries for `alc enqueue --from-file`.

    A ``.jsonl`` file holds one JSON object per line (``task`` required; ``kind``,
    ``name``, ``id``, ``depends_on``, ``touches`` optional — each entry falls back
    to the CLI's own flags when absent). Any other extension is plain text, one
    task per line; blank lines and ``#`` comments are skipped.
    """
    import json

    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path}")

    lines = path.read_text().splitlines()
    if path.suffix == ".jsonl":
        entries: list[dict] = []
        for lineno, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(entry, dict) or "task" not in entry:
                raise ValueError(f"{path}:{lineno}: missing 'task' key")
            entries.append(entry)
        return entries

    return [
        {"task": line.strip()}
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def cmd_enqueue(args: argparse.Namespace) -> int:
    """Run `alc enqueue <name> "<task>" [--kind flow|specialist] [--engine NAME] \
[--isolate/--no-isolate] [--id ID] [--depends-on ID] [--touches PATH] \
[--priority N] [--from-file PATH] [--json]`.

    Writes queue task file(s) straight to disk — no planner turn. Each item's
    target unit is validated (``load_flow`` / ``load_specialist``) BEFORE
    anything is written, so a typo never leaves a half-written batch behind.
    Delegates to ``dispatch_enqueue`` (``conduct.py:488``), which already applies
    ``derive_dependencies`` (serializing units whose ``touches`` overlap).

    ``--from-file`` batches multiple tasks: a ``.jsonl`` file supplies one item
    per line (each may override ``kind``/``name``/``id``/``depends_on``/
    ``touches``); any other extension is plain text, one task per line, against
    the single ``--kind``/``<name>``/``--id``/``--depends-on``/``--touches``
    given on the command line.
    """
    from pydantic import ValidationError

    from alc.conduct import dispatch_enqueue
    from alc.intake import load_flow, load_manifest, load_specialist
    from alc.models import ConductorPlan, PlannedUnit

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    if args.from_file:
        try:
            entries = _enqueue_entries_from_file(Path(args.from_file))
        except (FileNotFoundError, ValueError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    else:
        if not args.task:
            print("[ERROR] TASK is required unless --from-file is given", file=sys.stderr)
            return 1
        entries = [{"task": args.task}]

    try:
        items = [
            PlannedUnit(
                kind=entry.get("kind", args.kind),
                name=entry.get("name", args.name),
                task=entry["task"],
                id=entry.get("id", args.id),
                depends_on=entry.get("depends_on", list(args.depends_on)),
                touches=entry.get("touches", list(args.touches)),
            )
            for entry in entries
        ]
    except ValidationError as exc:
        print(f"[ERROR] invalid enqueue entry: {exc}", file=sys.stderr)
        return 1

    flows_dir = operator_layer.parent / manifest.flows_dir
    specialists_dir = operator_layer.parent / manifest.specialists_dir
    for item in items:
        try:
            if item.kind == "specialist":
                load_specialist(specialists_dir, item.name)
            else:
                load_flow(flows_dir, item.name)
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1

    files = dispatch_enqueue(
        ConductorPlan(items=items),
        manifest,
        operator_layer,
        engine_override=args.engine,
        isolate=args.isolate,
        prefix="enqueue",
        priority=getattr(args, "priority", 0),
    )

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(files)
        return 0

    print(f"Enqueued {len(files)} task(s):")
    for f in files:
        print(f"  {f}")
    print("Run: alc tick")
    return 0


def _resolve_delivery(args: argparse.Namespace):
    """Resolve the effective DeliverySpec for `alc land`: CLI flags override the
    manifest's declared default (same override relationship as `--tier` over
    `manifest.plan_tier`).

    Never raises: `alc land` works with no Operator Layer at all (test_land.py) —
    an unreadable/missing manifest just falls back to `DeliverySpec()`'s own
    default (mode: local), so `--push`/`--pr` still work standalone off git alone.
    """
    from alc.intake import load_manifest
    from alc.models import DeliverySpec

    try:
        manifest = load_manifest(_find_operator_layer())
        delivery = manifest.delivery or DeliverySpec()
    except Exception:
        delivery = DeliverySpec()

    if getattr(args, "pr", False):
        delivery = delivery.model_copy(update={"mode": "pr"})
    elif getattr(args, "push", False):
        delivery = delivery.model_copy(update={"mode": "push"})
    return delivery


def _deliver(repo_root: Path, delivery, report) -> None:
    """The last mile (roadmap-phase-4.md T8): push the landed branch, optionally
    open a PR. No-op for ``mode: "local"``. NEVER raises and NEVER changes
    `alc land`'s exit code — a push/PR failure is warned about, not fatal,
    because the local land this runs after already succeeded.
    """
    from alc.delivery import build_pr_body, changed_files, current_branch, open_pr, push_branch

    branch = current_branch(repo_root)
    if branch is None:
        print("[land] could not resolve the current branch; skipping delivery.", file=sys.stderr)
        return

    ok, message = push_branch(repo_root, delivery.remote, branch)
    print(f"[land] {message}", file=sys.stdout if ok else sys.stderr)
    if not ok or delivery.mode != "pr":
        return

    files = changed_files(repo_root, delivery.base, branch)
    body = build_pr_body(report, files)
    ok, message = open_pr(repo_root, delivery.base, branch, f"alc land: {branch}", body)
    print(f"[land] {message}", file=sys.stdout if ok else sys.stderr)


def cmd_land(args: argparse.Namespace) -> int:
    """Run `alc land [branch...] [--all] [--json] [--push|--pr]`: thin shell over
    auto_merge_branches, plus the optional remote last mile (DeliverySpec, T8).

    - No branch names and no ``--all``: LIST the unmerged ``alc/*`` branches,
      same listing convention as ``alc retry`` with no stem.
    - ``--all``: integrate every unmerged ``alc/*`` branch.
    - Explicit branch names: each must carry the ``alc/`` prefix — validated
      before anything is touched.
    - ``--push``/``--pr`` (or a manifest ``delivery: {mode: push|pr}``): after a
      successful local merge, push the current branch to the delivery remote,
      and for ``--pr`` also open a PR via `gh`. Additive only — with neither
      flag AND no non-default `delivery` declared, behavior is byte-identical
      to before this existed. A push failure or a missing `gh` never changes
      the exit code below (see `_deliver`).

    Prints ``MergeReport.summary()`` and exits 1 when anything conflicted (0
    otherwise). Outside a git repository this is a clear error, exit 1.
    """
    from alc.branches import list_alc_branches
    from alc.merge import auto_merge_branches
    from alc.worktree import git_toplevel, is_git_repo

    if args.branch:
        invalid = [b for b in args.branch if not b.startswith("alc/")]
        if invalid:
            print(f"[ERROR] not an alc/ branch: {', '.join(invalid)}", file=sys.stderr)
            return 1

    if not is_git_repo(Path.cwd()):
        print("[ERROR] not inside a git repository", file=sys.stderr)
        return 1
    repo_root = git_toplevel(Path.cwd())

    if args.branch:
        branches = args.branch
    elif args.all:
        branches = [b.name for b in list_alc_branches(repo_root) if not b.merged]
    else:
        # List path — machine-readable (--json) or human-readable (default).
        unmerged = [b for b in list_alc_branches(repo_root) if not b.merged]
        if getattr(args, "json", False):
            from dataclasses import asdict

            from alc.output import emit_json

            emit_json([asdict(b) for b in unmerged])
            return 0
        if not unmerged:
            print("No unmerged alc/ branches.")
            return 0
        for b in unmerged:
            print(f"{b.name}   ({b.label})")
        print("Run: alc land --all")
        return 0

    report = auto_merge_branches(repo_root, branches)
    print(report.summary())

    delivery = _resolve_delivery(args)
    if delivery.mode != "local":
        _deliver(repo_root, delivery, report)

    return 1 if report.conflicted else 0


def _confirm_delete(assume_yes: bool) -> bool:
    """Return True when a destructive `alc discard` action is confirmed.

    ``--yes`` always confirms. Otherwise prompt interactively when stdin is a
    TTY; a non-TTY invocation without ``--yes`` is never confirmed — never
    delete silently (e.g. from cron or a script).
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    reply = input("Proceed? [y/N] ").strip().lower()
    return reply in ("y", "yes")


def _discard_list(args: argparse.Namespace) -> int:
    """The no-argument path of `alc discard`: list the unmerged `alc/*` branches."""
    import time

    from alc.branches import list_alc_branches
    from alc.worktree import git_toplevel, is_git_repo

    if not is_git_repo(Path.cwd()):
        print("[ERROR] not inside a git repository", file=sys.stderr)
        return 1
    repo_root = git_toplevel(Path.cwd())
    unmerged = [b for b in list_alc_branches(repo_root) if not b.merged]

    if getattr(args, "json", False):
        from dataclasses import asdict

        from alc.output import emit_json

        emit_json([asdict(b) for b in unmerged])
        return 0

    if not unmerged:
        print("No unmerged alc/ branches.")
        return 0
    now = time.time()
    for b in unmerged:
        age_days = (now - b.committed_at) / 86400
        print(f"{b.name}   ({b.label}, {age_days:.1f}d old)")
    print("Run: alc discard --all-unmerged   (or pass branch names)")
    return 0


def cmd_discard(args: argparse.Namespace) -> int:
    """Run `alc discard [branch...] [--all-unmerged] [--worktrees] \
[--bundles --older-than N] [--yes] [--json]`.

    - No branch names and no flag: LIST the unmerged ``alc/*`` branches with
      their age and provenance (``AlcBranch.label``).
    - Branch names or ``--all-unmerged``: force-delete those ``alc/*`` branches
      via `delete_branches` (already refuses a non-``alc/`` ref and the
      current branch).
    - ``--worktrees``: prune stale worktree admin entries.
    - ``--bundles --older-than N``: delete bundle files older than N days from
      the manifest's ``bundles_dir``.

    Any actual deletion (branches, bundles) requires confirmation: ``--yes``,
    or an interactive "y" at a TTY prompt — refuses otherwise, never deleting
    silently.
    """
    import time

    from alc.branches import delete_branches, list_alc_branches, prune_worktrees
    from alc.worktree import git_toplevel, is_git_repo

    wants_branches = bool(args.branch) or args.all_unmerged
    if not (wants_branches or args.worktrees or args.bundles):
        return _discard_list(args)

    if args.branch:
        invalid = [b for b in args.branch if not b.startswith("alc/")]
        if invalid:
            print(f"[ERROR] not an alc/ branch: {', '.join(invalid)}", file=sys.stderr)
            return 1

    if args.bundles and args.older_than is None:
        print("[ERROR] --bundles requires --older-than N", file=sys.stderr)
        return 1

    repo_root = None
    if wants_branches or args.worktrees:
        if not is_git_repo(Path.cwd()):
            print("[ERROR] not inside a git repository", file=sys.stderr)
            return 1
        repo_root = git_toplevel(Path.cwd())

    branch_targets: list[str] = []
    if wants_branches:
        if args.branch:
            branch_targets = args.branch
        else:
            branch_targets = [b.name for b in list_alc_branches(repo_root) if not b.merged]

    bundle_targets: list[Path] = []
    if args.bundles:
        from alc.intake import load_manifest

        operator_layer = _find_operator_layer()
        manifest = load_manifest(operator_layer)
        bundles_dir = operator_layer.parent / manifest.bundles_dir
        if bundles_dir.is_dir():
            cutoff = time.time() - args.older_than * 86400
            bundle_targets = [
                p for p in bundles_dir.glob("*.jsonl") if p.stat().st_mtime < cutoff
            ]

    if (branch_targets or bundle_targets) and not _confirm_delete(args.yes):
        print(
            "[ERROR] refusing to delete without confirmation; pass --yes or "
            "confirm interactively",
            file=sys.stderr,
        )
        return 1

    if wants_branches:
        deleted = delete_branches(repo_root, branch_targets) if branch_targets else []
        if deleted:
            print(f"Deleted {len(deleted)} branch(es): {', '.join(deleted)}")
        else:
            print("Deleted 0 branches.")

    if args.worktrees:
        pruned = prune_worktrees(repo_root)
        print(f"Pruned {pruned} stale worktree(s).")

    if args.bundles:
        for p in bundle_targets:
            p.unlink()
        print(f"Deleted {len(bundle_targets)} bundle file(s) older than {args.older_than}d.")

    return 0


def cmd_explore(args: argparse.Namespace) -> int:
    """Run `alc explore <blueprint> "<task>" --variants N [--engine ...] [--tier ...]`.

    N copies of the SAME Blueprint+task, each dispatched via ``run_fanout`` into
    its own isolated worktree, branched ``alc/variant-<n>-<hex8>``. Repeating
    ``--engine`` and/or ``--tier`` produces their cartesian product (crossed with
    ``--variants``); with neither, ``--variants N`` alone repeats the manifest's
    default engine and the Blueprint's own tier N times.

    NEVER auto-merges — that is the whole point of exploring variants side by
    side, a property of this command itself (no flag turns it on). Run
    `alc compare` then `alc adopt` to close the loop.
    """
    from alc.fanout import run_fanout
    from alc.intake import load_manifest
    from alc.variants import variant_row, write_variant

    if args.variants < 1:
        print("[ERROR] --variants must be >= 1", file=sys.stderr)
        return 1

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    tiers = args.tier or [None]
    for t in tiers:
        tier_err = _validate_tier(manifest, t)
        if tier_err:
            print(f"[ERROR] {tier_err}", file=sys.stderr)
            return 1
    engines = args.engine or [None]

    units: list[dict] = []
    for _ in range(args.variants):
        for engine in engines:
            for tier in tiers:
                n = len(units) + 1
                units.append({
                    "kind": "blueprint",
                    "name": args.blueprint,
                    "task": args.task,
                    "engine": engine,
                    "tier": tier,
                    "label": f"variant-{n}",
                })

    try:
        fanout = run_fanout(
            manifest, operator_layer, units, max_workers=manifest.fanout_concurrency
        )
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Archive every variant that actually committed, so a later (separate) `alc
    # compare`/`alc adopt` invocation can read it back by branch name.
    variants_dir = operator_layer.parent / manifest.variants_dir
    rows = []
    for unit_spec, unit_result in zip(units, fanout.units):
        rows.append(variant_row(unit_result, unit_spec["engine"], unit_spec["tier"]))
        if unit_result.branch:
            write_variant(
                variants_dir,
                unit_result.branch,
                unit_spec["engine"],
                unit_spec["tier"],
                unit_result,
            )

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(rows)
        return 0 if fanout.success else 1

    _print_variant_table(rows)
    return 0 if fanout.success else 1


def cmd_compare(args: argparse.Namespace) -> int:
    """Run `alc compare <branch|stem>...`: variants side by side (T6's columns).

    Reads each ref's archive from ``manifest.variants_dir`` (written by `alc
    explore`) — either the full ``alc/variant-…`` branch name or its bare stem.
    A ref with no archive is reported on stderr and the command exits 1.
    """
    from alc.intake import load_manifest
    from alc.variants import read_variant, variant_row

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    variants_dir = operator_layer.parent / manifest.variants_dir

    rows = []
    missing = []
    for ref in args.refs:
        found = read_variant(variants_dir, ref)
        if found is None:
            missing.append(ref)
            continue
        unit, engine, tier = found
        rows.append(variant_row(unit, engine, tier))

    if missing:
        print(f"[ERROR] no archived variant for: {', '.join(missing)}", file=sys.stderr)

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(rows)
        return 1 if missing else 0

    _print_variant_table(rows)
    return 1 if missing else 0


def cmd_adopt(args: argparse.Namespace) -> int:
    """Run `alc adopt <branch> [--yes] [--json]`.

    Integrates the chosen variant branch (reusing ``auto_merge_branches``) and
    discards every OTHER unmerged ``alc/variant-*`` branch (via
    ``delete_branches``) — closing the explore -> compare -> adopt loop.
    `explore` never merges; this is the one place a variant becomes real.

    Requires the same confirmation `alc discard` does: ``--yes``, or an
    interactive "y" at a TTY prompt (see ``_confirm_delete``). Without it,
    refuses outright — nothing is merged, nothing is deleted, never a partial
    adopt.
    """
    import re

    from alc.branches import delete_branches, list_alc_branches
    from alc.merge import auto_merge_branches
    from alc.worktree import git_toplevel, is_git_repo

    if not args.branch.startswith("alc/"):
        print(f"[ERROR] not an alc/ branch: {args.branch}", file=sys.stderr)
        return 1

    if not is_git_repo(Path.cwd()):
        print("[ERROR] not inside a git repository", file=sys.stderr)
        return 1
    repo_root = git_toplevel(Path.cwd())

    if not _confirm_delete(args.yes):
        print(
            "[ERROR] refusing to adopt without confirmation; pass --yes or "
            "confirm interactively",
            file=sys.stderr,
        )
        return 1

    variant_re = re.compile(r"^alc/variant-\d+-[0-9a-f]{8}$")
    losers = [
        b.name
        for b in list_alc_branches(repo_root)
        if not b.merged and b.name != args.branch and variant_re.match(b.name)
    ]

    merge_report = auto_merge_branches(repo_root, [args.branch])
    discarded = delete_branches(repo_root, losers) if losers else []

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json({
            "merged": merge_report.merged,
            "conflicted": merge_report.conflicted,
            "discarded": discarded,
        })
        return 1 if merge_report.conflicted else 0

    print(merge_report.summary())
    if discarded:
        print(f"Discarded {len(discarded)} losing variant(s): {', '.join(discarded)}")
    else:
        print("Discarded 0 losing variant(s).")
    return 1 if merge_report.conflicted else 0


def cmd_status(args: argparse.Namespace) -> int:
    """Run `alc status [--json]`: aggregate health signals for external monitoring.

    Reports pending queue tasks, outstanding (retryable) failures, every
    Autonomous Loop's persisted state — flagging any 'stopped' one with its
    ``stopped_reason`` — and the count of unmerged ``alc/*`` branches (0 outside
    a git repository).

    This command NEVER fails on what it finds: it always exits 0. It is meant
    as the target of external monitoring — the CONSUMER (a monitoring script, a
    dashboard poll) decides what in the payload counts as unhealthy.
    """
    from alc.branches import list_alc_branches
    from alc.intake import load_manifest
    from alc.loop import load_loop_state, loops_dir, state_path
    from alc.queue import outstanding_failures
    from alc.worktree import git_toplevel, is_git_repo

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    project_root = operator_layer.parent

    queue_dir = project_root / manifest.queue_dir
    pending = len(list(queue_dir.glob("*.yaml"))) if queue_dir.is_dir() else 0

    failures = outstanding_failures(queue_dir / "done")

    loops_directory = loops_dir(manifest, operator_layer)
    loops: list[dict] = []
    if loops_directory.is_dir():
        for path in sorted(loops_directory.glob("*.yaml")):
            state = load_loop_state(state_path(loops_directory, path.stem), path.stem)
            loops.append(
                {
                    "name": state.name,
                    "status": state.status,
                    "cycle": state.cycle,
                    "stopped_reason": state.stopped_reason,
                }
            )

    branches = 0
    if is_git_repo(project_root):
        branches = len(
            [b for b in list_alc_branches(git_toplevel(project_root)) if not b.merged]
        )

    payload = {
        "pending": pending,
        "outstanding_failures": len(failures),
        "loops": loops,
        "unmerged_branches": branches,
    }

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(payload)
        return 0

    print(f"Pending queue tasks:     {pending}")
    print(f"Outstanding failures:    {len(failures)}")
    print(f"Unmerged alc/ branches:  {branches}")
    if loops:
        print("Loops:")
        for loop in loops:
            line = f"  {loop['name']}: {loop['status']} (cycle {loop['cycle']})"
            if loop["status"] == "stopped":
                line += f", stopped_reason={loop['stopped_reason']}"
            print(line)
    else:
        print("Loops:                   (none)")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    """Run `alc runs list|show|tail`: inspect run logs (``.alc/runs/*.jsonl``).

    - ``list [--limit N] [--offset N] [--json]``: newest-first page of run summaries.
    - ``show <stem> [--json]``: every parsed event for one run.
    - ``tail <stem> [-n N]``: the last N events of one run (default 20).

    No ``--follow``: the web IDE already streams a live run over WebSocket, so a
    polling loop here would only duplicate it.
    """
    import json

    from alc.intake import load_manifest
    from alc.runs import STALE_MARGIN_S, list_runs, read_run

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    runs_dir = operator_layer.parent / manifest.runs_dir
    stale_after = manifest.default_timeout_s + STALE_MARGIN_S

    if args.runs_action == "list":
        result = list_runs(runs_dir, stale_after, limit=args.limit, offset=args.offset)
        if getattr(args, "json", False):
            from alc.output import emit_json

            emit_json(result)
            return 0
        if not result["runs"]:
            print("No runs.")
            return 0
        for run in result["runs"]:
            status = "finished" if run["finished"] else ("stale" if run["stale"] else "running")
            net = run["net_lines"]
            net_str = f"{net:+d}" if net is not None else "n/a"
            print(f"{run['stem']}   ({run['kind']}, {status})   net-lines={net_str}")
        print(f"Showing {len(result['runs'])} of {result['total']} run(s).")
        return 0

    # show / tail both resolve one run by stem.
    try:
        result = read_run(runs_dir, args.stem, stale_after)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.runs_action == "show":
        if getattr(args, "json", False):
            from alc.output import emit_json

            emit_json(result)
            return 0
        events = result["events"]
    else:  # tail
        events = result["events"][-args.lines :] if args.lines > 0 else result["events"]

    for event in events:
        print(json.dumps(event, default=str))
    return 0


def cmd_checks(args: argparse.Namespace) -> int:
    """Run `alc checks <action>`: dispatch to `audit` or `history`."""
    if args.checks_action == "history":
        return _checks_history(args)
    return _checks_audit(args)


def _checks_audit(args: argparse.Namespace) -> int:
    """`alc checks audit [--json]`: re-detect stacks and PROPOSE check upgrades.

    Never writes — compares the Manifest's current check_sets (and each
    Blueprint's resolved checks) against what `detect_stacks()` finds today,
    including live binary availability, and prints the diff for the operator
    to apply by hand (or reconcile via `alc team hire --force`).
    """
    from alc.checks import audit_checks
    from alc.intake import load_all_blueprints, load_manifest

    operator_layer = _find_operator_layer()
    project_root = operator_layer.parent
    manifest = load_manifest(operator_layer)
    blueprints = load_all_blueprints(manifest, operator_layer)

    report = audit_checks(manifest, project_root, blueprints)

    if getattr(args, "json", False):
        from dataclasses import asdict

        from alc.output import emit_json

        emit_json(asdict(report))
        return 0

    if not report.has_proposals:
        print("No upgrades proposed — check_sets are current with the detected stack(s).")

    for cs in report.check_sets:
        status = "NEW" if cs.is_new else "existing"
        print(f"check_set '{cs.set_name}' ({status}):")
        for name, command in cs.add:
            print(f"  + {name}: {' '.join(command)}  (binary available — propose adding)")
        for name, command in cs.unavailable:
            print(f"  - {name}: {' '.join(command)}  (binary not on PATH — stays commented out)")

    for bp in report.smoke_only_blueprints:
        stacks_desc = ", ".join(bp.stacks)
        print(
            f"Blueprint '{bp.blueprint}' resolves to only the smoke placeholder while "
            f"{stacks_desc} is detected — consider wiring real checks."
        )

    return 0


def _checks_history(args: argparse.Namespace) -> int:
    """`alc checks history [--json]`: pass-rate, mean duration and a flake score
    per check, aggregated from the run logs' `check_finished` events.

    Sibling action to `audit` (roadmap-phase-3.md T10) — never writes.
    """
    from dataclasses import asdict

    from alc.checks import check_history
    from alc.intake import load_manifest

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    runs_dir = operator_layer.parent / manifest.runs_dir

    history = check_history(runs_dir)

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json([asdict(h) for h in history])
        return 0

    if not history:
        print("No check history yet — run `alc run`/`alc tick` to populate the run logs.")
        return 0

    for h in history:
        print(
            f"{h.name}: pass_rate={h.pass_rate:.0%} runs={h.runs} "
            f"mean_duration={h.mean_duration_s:.2f}s flake_score={h.flake_score:.2f}"
        )

    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    """Run `alc metrics [--check NAME] [--json]`: the metric-check time series
    recorded in the project's ledger (roadmap-phase-4.md T3).

    Read-only — a metric's baseline is only ever recorded by the Verifier while
    running a Blueprint's checks (`alc run`/`alc flow`/`alc tick`/…).
    """
    from dataclasses import asdict
    from datetime import datetime, timezone

    from alc.intake import load_manifest
    from alc.metrics import ledger_path, metric_series

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    path = ledger_path(operator_layer.parent / manifest.metrics_dir)

    series = metric_series(path, check=args.check)

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json({name: [asdict(p) for p in points] for name, points in series.items()})
        return 0

    if not series:
        print(
            "No metric history yet — run a Blueprint with a `metric` check to "
            "populate the ledger."
        )
        return 0

    for name in sorted(series):
        print(f"{name}:")
        for point in series[name]:
            ts = datetime.fromtimestamp(point.ts, tz=timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
            # A rejected point never became the check's baseline (see
            # alc.metrics.latest_accepted_measurement) — flagged here so a
            # reader can tell which points the gate actually accepted.
            status = "accepted" if point.passed else "REJECTED"
            if point.delta is None:
                print(
                    f"  {ts}  value={point.value:g}  run={point.run}  "
                    f"(first measurement, {status})"
                )
            else:
                print(
                    f"  {ts}  value={point.value:g}  delta={point.delta:+g}  "
                    f"trend={point.trend}  run={point.run}  status={status}"
                )

    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    """Run `alc schedule install|list|remove <tick|cycle NAME> --every 15m`.

    Generates and manages the crontab entry that fires `alc tick` or
    `alc cycle NAME` on a cadence (roadmap-phase-3.md T13) — the first cron
    line an operator would otherwise have to compose by hand.
    """
    if args.schedule_action == "install":
        return _schedule_install(args)
    if args.schedule_action == "remove":
        return _schedule_remove(args)
    return _schedule_list(args)


def _schedule_target(args: argparse.Namespace) -> tuple[str, str | None] | None:
    """Validate target/name and return (target, name), or None (prints the error).

    'cycle' requires a loop NAME; 'tick' takes none — a NAME given to 'tick' is
    almost certainly a typo for 'cycle', so it is rejected rather than ignored.
    """
    target = args.target
    name = args.name
    if target == "cycle" and not name:
        print("[ERROR] `schedule ... cycle` requires a loop NAME", file=sys.stderr)
        return None
    if target == "tick" and name:
        print(f"[ERROR] `schedule ... tick` takes no NAME (got '{name}')", file=sys.stderr)
        return None
    return target, (name if target == "cycle" else None)


def _schedule_label(target: str, name: str | None) -> str:
    """Human label for a target/name pair, e.g. 'cycle deliver' or 'tick'."""
    return f"{target} {name}" if name else target


def _schedule_install(args: argparse.Namespace) -> int:
    from alc.schedule import (
        build_line,
        has_crontab,
        parse_every,
        read_crontab,
        resolve_binary,
        upsert,
        write_crontab,
    )

    resolved = _schedule_target(args)
    if resolved is None:
        return 1
    target, name = resolved

    try:
        cron_expr = parse_every(args.every)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    project_root = _find_operator_layer().parent
    line = build_line(target, name, project_root, cron_expr, resolve_binary())

    if not has_crontab():
        print("No `crontab` on this platform — add this line to your scheduler:")
        print(f"  {line}")
        return 0

    if not write_crontab(upsert(read_crontab(), target, name, line)):
        print("[ERROR] could not write the crontab — add this line yourself (crontab -e):")
        print(f"  {line}")
        return 1

    print(f"Installed: {line}")
    return 0


def _schedule_remove(args: argparse.Namespace) -> int:
    from alc.schedule import has_crontab, marker, read_crontab, remove, write_crontab

    resolved = _schedule_target(args)
    if resolved is None:
        return 1
    target, name = resolved
    label = _schedule_label(target, name)

    if not has_crontab():
        print("No `crontab` on this platform — nothing to remove.")
        return 0

    lines = read_crontab()
    tag = marker(target, name)
    matched = [line for line in lines if tag in line]
    if not matched:
        print(f"No scheduled entry for '{label}'.")
        return 0

    if not write_crontab(remove(lines, target, name)):
        print(
            "[ERROR] could not update the crontab — remove this line yourself "
            "(crontab -e):",
            file=sys.stderr,
        )
        for line in matched:
            print(f"  {line}", file=sys.stderr)
        return 1

    print(f"Removed the scheduled entry for '{label}'.")
    return 0


def _schedule_list(args: argparse.Namespace) -> int:
    from alc.schedule import has_crontab, list_entries, read_crontab

    if not has_crontab():
        print("No `crontab` on this platform.")
        return 0

    entries = list_entries(read_crontab())

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(entries)
        return 0

    if not entries:
        print("No ALC-scheduled entries. Run: alc schedule install tick --every 15m")
        return 0
    for line in entries:
        print(line)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Run `alc audit --since 7d|24h|30m [--json]`: aggregate archived queue reports.

    Rolls up every ``done/*.report.json`` archived at/after the trailing window
    into task counts, Scorecard totals/averages, changed files, and accumulated
    engine Usage (input/output tokens, cost). An unparseable ``--since`` is a
    clear error, not a traceback.
    """
    import time
    from dataclasses import asdict

    from alc.audit import audit_window, parse_since
    from alc.intake import load_manifest

    try:
        seconds = parse_since(args.since)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    done_dir = operator_layer.parent / manifest.queue_dir / "done"

    window = audit_window(done_dir, time.time() - seconds)

    if getattr(args, "json", False):
        from alc.output import emit_json

        emit_json(asdict(window))
        return 0

    print(f"Since:            {args.since} ago")
    print(
        f"Tasks:            {window.tasks_total} total, "
        f"{window.tasks_ok} ok, {window.tasks_failed} failed"
    )
    print(
        f"Scorecard (avg):  span={window.span_avg:.2f} passes={window.passes_avg:.2f} "
        f"streak={window.streak_avg:.2f} touch={window.touch_avg:.2f}"
    )
    print(f"Changed files:    {window.changed_files_total}")
    print(
        f"Usage:            input={window.input_tokens_total} "
        f"output={window.output_tokens_total} cost_usd={window.cost_usd_total:.4f}"
    )
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    """Run `alc ui [--host H] [--port P] [--ui-dist PATH] [--no-ui]`: serve the web IDE.

    The web backend lives behind the optional ``ui`` extra (fastapi/uvicorn/
    watchfiles). When it is not installed, print a clear install hint and exit 1
    rather than raising an ImportError traceback.

    The frontend is served BY DEFAULT. Resolution order (unless --no-ui): an
    explicit --ui-dist (error + exit 1 if it has no index.html), then
    ALC_UI_DIST (a warning + skip when invalid), then the bundled build shipped
    inside the package, else API-only with a hint on how to obtain the UI.
    """
    import os

    try:
        import uvicorn

        from alc.ui.frontend import FrontendError, resolve_frontend
        from alc.ui.registry import default_registry_path
        from alc.ui.server import create_app
    except ModuleNotFoundError:
        print(
            "[ERROR] `alc ui` requires the 'ui' extra (fastapi, uvicorn, watchfiles). "
            'Install it with: uv tool install "alc[ui]"',
            file=sys.stderr,
        )
        return 1

    try:
        frontend = resolve_frontend(
            args.ui_dist, os.environ.get("ALC_UI_DIST"), no_ui=args.no_ui
        )
    except FrontendError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if frontend is not None:
        location = f"frontend: {frontend}"
    else:
        location = "API only"
        if not args.no_ui:
            print(
                "No frontend build found. Build the alc-ui frontend "
                "(npm run build:alc) or pass --ui-dist PATH to serve it; "
                "running API-only for now.",
                file=sys.stderr,
            )

    app = create_app(default_registry_path(), ui_dist=frontend)
    print(f"Serving alc ui on http://{args.host}:{args.port} ({location})")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main() -> None:
    """Console-script entrypoint."""
    # A broken stderr pipe (cancelled exec / disconnected client) must never crash
    # the work — only the progress output is lost. Guard every stderr write once.
    sys.stderr = _ResilientStderr(sys.stderr)  # type: ignore[assignment]
    parser = argparse.ArgumentParser(
        prog="alc",
        description="ALC — Agentic Layer Compiler & Runtime",
    )
    from alc.setup_skill import _resolve_version

    parser.add_argument(
        "--version", action="version", version=f"alc {_resolve_version()}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # alc init [--force] [--setup] [--stage pre-pmf|growth|strong-pmf]
    init_parser = subparsers.add_parser(
        "init",
        help="Scaffold a default Operator Layer (.alc/) into the current directory.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite an existing .alc/ directory.",
    )
    init_parser.add_argument(
        "--setup",
        action="store_true",
        default=False,
        help="Also install/update the user-level editor skill after scaffolding.",
    )
    init_parser.add_argument(
        "--engine",
        default="claude-code",
        help="Engine whose editor skill to install with --setup (default: claude-code).",
    )
    init_parser.add_argument(
        "--stage",
        choices=["pre-pmf", "growth", "strong-pmf"],
        default=None,
        help=(
            "Also hire the Archetype Pack combo for this stage's mix "
            "(see `alc team list`). Omit to only print a discovery hint."
        ),
    )

    # alc setup [--engine NAME]
    setup_parser = subparsers.add_parser(
        "setup",
        help="Install or update the user-level editor skill for an engine.",
    )
    setup_parser.add_argument(
        "--engine",
        default="claude-code",
        help="Engine whose editor skill to install: claude-code or gemini (default: claude-code).",
    )

    # alc lint
    lint_parser = subparsers.add_parser(
        "lint", help="Check the Operator Layer for Policy Gate violations."
    )
    lint_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the violations as JSON (machine-readable).",
    )

    # alc run <blueprint> "<task>" [--engine NAME] [--isolate] [--primer NAME]
    #          [--bundle] [--from-bundle REF]
    run_parser = subparsers.add_parser("run", help="Run a Blueprint against a task.")
    run_parser.add_argument("blueprint", help="Blueprint name (e.g. 'chore').")
    run_parser.add_argument("task", help="Free-text task description.")
    run_parser.add_argument("--engine", default=None, help="Override the default engine.")
    run_parser.add_argument(
        "--isolate",
        action="store_true",
        default=False,
        help=(
            "Run inside an isolated git worktree on a temporary branch. "
            "Agent edits are committed there instead of mutating the working tree."
        ),
    )
    run_parser.add_argument(
        "--primer",
        default=None,
        metavar="NAME",
        help=(
            "Inject a named Primer (curated context block from .alc/primers/<NAME>.md) "
            "into the directive. Context Budget Trim move."
        ),
    )
    run_parser.add_argument(
        "--bundle",
        action="store_true",
        default=False,
        help="Write an append-only bundle file recording this run's result for later replay.",
    )
    run_parser.add_argument(
        "--from-bundle",
        default=None,
        metavar="REF",
        help=(
            "Replay a prior bundle into the directive. REF is a bundle file path or stem "
            "(looked up in bundles_dir). Context Budget Offload move."
        ),
    )
    run_parser.add_argument(
        "--tier",
        default=None,
        metavar="NAME",
        help="Override the Compute Tier for this invocation (flow: applies to every stage).",
    )

    # alc spike "<task>" [--engine NAME]
    spike_parser = subparsers.add_parser(
        "spike",
        help=(
            'Sugar for `alc run spike "<task>"` — the Prototyper pack\'s spike '
            "Blueprint, no blueprint name to remember."
        ),
    )
    spike_parser.add_argument("task", help="Free-text task description.")
    spike_parser.add_argument("--engine", default=None, help="Override the default engine.")

    # alc tick
    tick_parser = subparsers.add_parser(
        "tick",
        help=(
            "Drain the task queue (Unattended Mode Trigger). "
            "Processes all pending tasks once and exits — call via cron."
        ),
    )
    tick_parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Process up to N queue tasks in parallel; each isolated task gets "
            "its own git worktree."
        ),
    )

    # alc retry [stem] [--all]
    retry_parser = subparsers.add_parser(
        "retry",
        help=(
            "Re-enqueue a failed task (by its done/ filename stem) with the failure "
            "feedback appended, so the next drain fixes the specific reason. With no "
            "stem, lists the outstanding failures; with --all, re-enqueues all of them."
        ),
    )
    retry_parser.add_argument(
        "stem",
        nargs="?",
        default=None,
        help=(
            "Filename stem of the failed task under queue/done/ (e.g. "
            "plan-001-...-<uid>). Omit to list the outstanding failures."
        ),
    )
    retry_parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Re-enqueue every outstanding failure at once (ignored when a stem is given).",
    )
    retry_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="List the outstanding failures as JSON (machine-readable).",
    )

    # alc enqueue <name> "<task>" [--kind flow|specialist] [--engine NAME]
    #             [--isolate/--no-isolate] [--id ID] [--depends-on ID] [--touches PATH]
    #             [--from-file PATH] [--json]
    enqueue_parser = subparsers.add_parser(
        "enqueue",
        help="Write one or more queue task(s) directly, with no planner turn.",
    )
    enqueue_parser.add_argument("name", help="Flow or specialist name to dispatch.")
    enqueue_parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="Free-text task description. Omit when using --from-file.",
    )
    enqueue_parser.add_argument(
        "--kind",
        choices=["flow", "specialist"],
        default="flow",
        help="Unit kind to dispatch (default: flow).",
    )
    enqueue_parser.add_argument("--engine", default=None, help="Override the default engine.")
    enqueue_parser.add_argument(
        "--isolate",
        dest="isolate",
        action="store_true",
        default=True,
        help="Run the enqueued task(s) in an isolated git worktree (default).",
    )
    enqueue_parser.add_argument(
        "--no-isolate",
        dest="isolate",
        action="store_false",
        help="Do not isolate the enqueued task(s) in a worktree.",
    )
    enqueue_parser.add_argument(
        "--id",
        dest="id",
        default=None,
        metavar="ID",
        help="Short slug identifying this unit so another --depends-on can reference it.",
    )
    enqueue_parser.add_argument(
        "--depends-on",
        dest="depends_on",
        action="append",
        default=[],
        metavar="ID",
        help="Id of a unit this one depends on (repeatable).",
    )
    enqueue_parser.add_argument(
        "--touches",
        dest="touches",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "File path/glob this unit will edit; overlapping touches are "
            "serialized automatically (repeatable)."
        ),
    )
    enqueue_parser.add_argument(
        "--priority",
        dest="priority",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Tie-breaker among tasks ready in the same dependency wave, higher "
            "runs first (default 0)."
        ),
    )
    enqueue_parser.add_argument(
        "--from-file",
        dest="from_file",
        default=None,
        metavar="PATH",
        help=(
            "Batch-enqueue tasks from a file: a .jsonl file (one JSON object per "
            "line, 'task' required, other keys optional) or plain text (one task "
            "per line; blank lines and '#' comments are skipped)."
        ),
    )
    enqueue_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the written filenames as JSON (machine-readable).",
    )

    # alc land [branch...] [--all] [--json] [--push|--pr]
    land_parser = subparsers.add_parser(
        "land",
        help=(
            "Integrate alc/* demand branches into the current branch (linear "
            "cherry-pick). With no branch names, lists the unmerged ones."
        ),
    )
    land_parser.add_argument(
        "branch",
        nargs="*",
        help="Explicit alc/* branch name(s) to integrate. Omit to list the unmerged ones.",
    )
    land_parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Integrate every unmerged alc/* branch.",
    )
    land_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="List the unmerged branches as JSON (machine-readable); only with no branch/--all.",
    )
    land_parser.add_argument(
        "--push",
        action="store_true",
        default=False,
        help=(
            "After a successful local land, push the current branch to the "
            "delivery remote (manifest `delivery.remote`, default origin)."
        ),
    )
    land_parser.add_argument(
        "--pr",
        action="store_true",
        default=False,
        help=(
            "Push (see --push) and open a pull request via `gh` against the "
            "delivery base branch (manifest `delivery.base`, default main)."
        ),
    )

    # alc discard [branch...] [--all-unmerged] [--worktrees] [--bundles --older-than N] [--yes] [--json]
    discard_parser = subparsers.add_parser(
        "discard",
        help=(
            "Force-delete alc/* branches, prune stale worktrees, and/or remove "
            "old bundle files. With no arguments, lists the unmerged branches."
        ),
    )
    discard_parser.add_argument(
        "branch",
        nargs="*",
        help="Explicit alc/* branch name(s) to delete.",
    )
    discard_parser.add_argument(
        "--all-unmerged",
        action="store_true",
        default=False,
        help="Delete every unmerged alc/* branch (ignored when branch names are given).",
    )
    discard_parser.add_argument(
        "--worktrees",
        action="store_true",
        default=False,
        help="Prune stale worktree admin entries (git worktree prune).",
    )
    discard_parser.add_argument(
        "--bundles",
        action="store_true",
        default=False,
        help="Delete bundle files older than --older-than N days.",
    )
    discard_parser.add_argument(
        "--older-than",
        type=int,
        default=None,
        metavar="N",
        help="Age threshold in days for --bundles.",
    )
    discard_parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Confirm the deletion non-interactively (required when stdin is not a TTY).",
    )
    discard_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="List the unmerged branches as JSON (machine-readable); only with no other arguments.",
    )

    # alc explore <blueprint> "<task>" --variants N [--engine A --engine B] [--tier X --tier Y]
    explore_parser = subparsers.add_parser(
        "explore",
        help=(
            "Run N variants of the same Blueprint+task, each in its own isolated "
            "worktree — NEVER auto-merged. Compare them, then `alc adopt` one."
        ),
    )
    explore_parser.add_argument("blueprint", help="Blueprint name (e.g. 'chore').")
    explore_parser.add_argument("task", help="Free-text task description.")
    explore_parser.add_argument(
        "--variants",
        type=int,
        default=1,
        metavar="N",
        help="Number of copies of the unit to run (default: 1).",
    )
    explore_parser.add_argument(
        "--engine",
        action="append",
        default=None,
        metavar="NAME",
        help="Engine to explore (repeatable — crossed with --tier as a cartesian product).",
    )
    explore_parser.add_argument(
        "--tier",
        action="append",
        default=None,
        metavar="NAME",
        help="Compute tier to explore (repeatable — crossed with --engine as a cartesian product).",
    )
    explore_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the variant table as JSON (machine-readable).",
    )

    # alc compare <branch|stem>...
    compare_parser = subparsers.add_parser(
        "compare",
        help="Put explored variants side by side (branch, checks, scorecard, usage, diffstat).",
    )
    compare_parser.add_argument(
        "refs", nargs="+", help="Variant branch name(s) or bare stem(s) from `alc explore`."
    )
    compare_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the variant table as JSON (machine-readable).",
    )

    # alc adopt <branch> [--yes] [--json]
    adopt_parser = subparsers.add_parser(
        "adopt",
        help=(
            "Integrate the chosen variant branch and discard its unmerged "
            "sibling variants — closes the explore -> compare -> adopt loop."
        ),
    )
    adopt_parser.add_argument("branch", help="The winning alc/variant-* branch to integrate.")
    adopt_parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Confirm non-interactively (required when stdin is not a TTY).",
    )
    adopt_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print the outcome as JSON (machine-readable).",
    )

    # alc conduct "<goal>" [--engine NAME] [--enqueue]
    conduct_parser = subparsers.add_parser(
        "conduct",
        help=(
            "Conduct a goal: the Conductor agent plans the required Flows and "
            "either runs them now (default) or enqueues them for alc tick."
        ),
    )
    conduct_parser.add_argument("goal", help="High-level goal for the Conductor.")
    conduct_parser.add_argument("--engine", default=None, help="Override the default engine.")
    conduct_parser.add_argument(
        "--enqueue",
        action="store_true",
        default=False,
        help="Write queue task files instead of running Flows immediately.",
    )
    conduct_parser.add_argument(
        "--parallel",
        action="store_true",
        default=False,
        help=(
            "Dispatch independent plan units concurrently, each in an isolated "
            "git worktree (requires a git repo)."
        ),
    )
    conduct_parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Parallel fan-out width for --parallel (default: manifest.fanout_concurrency).",
    )
    conduct_parser.add_argument(
        "--tier",
        default=None,
        help="Compute tier for the planning turn (default: manifest.plan_tier).",
    )
    conduct_parser.add_argument(
        "--strict-stage",
        action="store_true",
        default=False,
        help=(
            "Refuse the plan instead of warning when a unit's archetype falls "
            "outside manifest.stage's target mix (no-op with no stage declared)."
        ),
    )

    # alc cycle <name> [--engine NAME] [--concurrency N] [--status] [--reset]
    cycle_parser = subparsers.add_parser(
        "cycle",
        help=(
            "Run ONE Autonomous Loop cycle (replenish -> drain -> check stop) and "
            "exit. State persists between fires — call via cron."
        ),
    )
    cycle_parser.add_argument("name", help="Loop name (e.g. 'deliver').")
    cycle_parser.add_argument("--engine", default=None, help="Override the default engine.")
    cycle_parser.add_argument(
        "--concurrency",
        type=int,
        default=0,
        help="Override the loop's drain concurrency for this cycle (0 = use the definition).",
    )
    cycle_parser.add_argument(
        "--status",
        action="store_true",
        default=False,
        help="Print the loop state without running a cycle.",
    )
    cycle_parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Reset the loop state, then run one cycle.",
    )
    cycle_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="With --status, print the loop state as JSON (machine-readable).",
    )

    # alc loop <name> [--engine NAME] [--interval S]
    loop_parser = subparsers.add_parser(
        "loop",
        help=(
            "Foreground wrapper that repeats `alc cycle` until the loop stops, "
            "sleeping between cycles. For interactive use without cron."
        ),
    )
    loop_parser.add_argument("name", help="Loop name (e.g. 'deliver').")
    loop_parser.add_argument("--engine", default=None, help="Override the default engine.")
    loop_parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Seconds to sleep between cycles (0 = no sleep). Default 300.",
    )
    loop_parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Reset the loop's stopped/exhausted state, then run — restart in one step.",
    )

    # alc specialist <name> "<task>" [--engine NAME]
    specialist_parser = subparsers.add_parser(
        "specialist",
        help=(
            "Run a Specialist (Recall -> Act -> Learn): read the Knowledge File, "
            "act on the task, then update the Knowledge File."
        ),
    )
    specialist_parser.add_argument("name", help="Specialist name (e.g. 'db').")
    specialist_parser.add_argument("task", help="Free-text task description.")
    specialist_parser.add_argument(
        "--engine", default=None, help="Override the default engine."
    )

    # alc primer <action> <name> [--force]
    primer_parser = subparsers.add_parser(
        "primer",
        help="Manage Primer files (curated context blocks) in the Operator Layer.",
    )
    primer_parser.add_argument(
        "action",
        choices=["new"],
        help="Action to perform. Currently only 'new' is supported.",
    )
    primer_parser.add_argument("name", help="Primer name (file stem, without .md extension).")
    primer_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite an existing Primer file.",
    )

    # alc new <kind> <name> [--force] [--from NAME]
    new_parser = subparsers.add_parser(
        "new",
        help="Author a new unit (blueprint/flow/specialist/loop/primer) from a core scaffold.",
    )
    new_parser.add_argument(
        "kind",
        choices=["blueprint", "flow", "specialist", "loop", "primer"],
        help="Kind of unit to create.",
    )
    new_parser.add_argument("name", help="Unit name (filename stem).")
    new_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite an existing unit of the same kind and name.",
    )
    new_parser.add_argument(
        "--from",
        dest="from_name",
        default=None,
        metavar="NAME",
        help="Clone an existing unit of the same kind, replacing its name: field.",
    )

    # alc team hire|list|retire|status
    team_parser = subparsers.add_parser(
        "team",
        help="Hire, list, retire, or check the status of Archetype Packs (team roster).",
    )
    team_subparsers = team_parser.add_subparsers(dest="team_action", required=True)

    team_hire_parser = team_subparsers.add_parser(
        "hire", help="Scaffold an Archetype Pack's files, then run `alc lint`."
    )
    team_hire_parser.add_argument("archetype", help="Pack name, e.g. 'builder'.")
    team_hire_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite the pack's files even if some already exist.",
    )

    team_list_parser = team_subparsers.add_parser(
        "list", help="List hired members and the state of any loops they brought."
    )
    team_list_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the roster as JSON (machine-readable).",
    )

    team_status_parser = team_subparsers.add_parser(
        "status",
        help=(
            "Like `alc team list`, plus Mix Health: archived reports' archetype "
            "spend against the declared stage's target mix."
        ),
    )
    team_status_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the roster as JSON (machine-readable).",
    )

    team_retire_parser = team_subparsers.add_parser(
        "retire",
        help="Archive a hired member's loop definition(s) into loops/retired/.",
    )
    team_retire_parser.add_argument("member", help="Archetype name to retire, e.g. 'builder'.")

    # alc prompts <action> [name] [--force]
    prompts_parser = subparsers.add_parser(
        "prompts",
        help="Manage keyed prompt overrides (.alc/prompts/) — list or eject.",
    )
    prompts_parser.add_argument(
        "action",
        choices=["list", "eject"],
        help="'list' the reserved/free prompts, or 'eject' a reserved default to a file.",
    )
    prompts_parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Reserved prompt name to eject (required for 'eject').",
    )
    prompts_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite an existing prompt override file when ejecting.",
    )
    prompts_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output 'prompts list' as JSON (machine-readable).",
    )

    # alc flow <flow_name> "<task>" [--engine NAME] [--isolate] [--primer NAME]
    #           [--bundle] [--from-bundle REF]
    flow_parser = subparsers.add_parser(
        "flow", help="Run a Flow (multi-stage pipeline) against a task."
    )
    flow_parser.add_argument("flow_name", help="Flow name (e.g. 'ship').")
    flow_parser.add_argument("task", help="Free-text task description.")
    flow_parser.add_argument("--engine", default=None, help="Override the default engine.")
    flow_parser.add_argument(
        "--isolate",
        action="store_true",
        default=False,
        help=(
            "Run all Flow stages inside one shared isolated git worktree. "
            "The plan→build file hand-off is preserved within the worktree."
        ),
    )
    flow_parser.add_argument(
        "--primer",
        default=None,
        metavar="NAME",
        help=(
            "Inject a named Primer (curated context block from .alc/primers/<NAME>.md) "
            "into every stage's directive. Context Budget Trim move."
        ),
    )
    flow_parser.add_argument(
        "--bundle",
        action="store_true",
        default=False,
        help="Write an append-only bundle file recording this flow's result for later replay.",
    )
    flow_parser.add_argument(
        "--from-bundle",
        default=None,
        metavar="REF",
        help=(
            "Replay a prior bundle into every stage's directive. REF is a bundle file path "
            "or stem (looked up in bundles_dir). Context Budget Offload move."
        ),
    )
    flow_parser.add_argument(
        "--tier",
        default=None,
        metavar="NAME",
        help="Override the Compute Tier for this invocation (flow: applies to every stage).",
    )

    # alc status [--json]
    status_parser = subparsers.add_parser(
        "status",
        help=(
            "Aggregate health signals (pending tasks, outstanding failures, loop "
            "states, unmerged branches) for external monitoring. Always exits 0."
        ),
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the status payload as JSON (machine-readable).",
    )

    # alc runs list|show|tail
    runs_parser = subparsers.add_parser(
        "runs", help="Inspect run logs (.alc/runs/*.jsonl): list, show, or tail one."
    )
    runs_subparsers = runs_parser.add_subparsers(dest="runs_action", required=True)

    runs_list_parser = runs_subparsers.add_parser(
        "list", help="List run logs, newest first."
    )
    runs_list_parser.add_argument(
        "--limit", type=int, default=50, help="Max runs to list (default: 50)."
    )
    runs_list_parser.add_argument(
        "--offset", type=int, default=0, help="Runs to skip from the newest (default: 0)."
    )
    runs_list_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the run list as JSON (machine-readable).",
    )

    runs_show_parser = runs_subparsers.add_parser(
        "show", help="Show every parsed event for one run."
    )
    runs_show_parser.add_argument(
        "stem", help="Run-log filename stem (e.g. from `alc runs list`)."
    )
    runs_show_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the run's events as JSON (machine-readable).",
    )

    runs_tail_parser = runs_subparsers.add_parser(
        "tail", help="Print the last N events of one run."
    )
    runs_tail_parser.add_argument(
        "stem", help="Run-log filename stem (e.g. from `alc runs list`)."
    )
    runs_tail_parser.add_argument(
        "-n",
        type=int,
        default=20,
        dest="lines",
        metavar="N",
        help="Number of trailing events to print (default: 20).",
    )

    # alc audit --since 7d|24h|30m [--json]
    audit_parser = subparsers.add_parser(
        "audit",
        help=(
            "Aggregate the archived queue reports (done/*.report.json) over a "
            "trailing time window: task counts, Scorecard totals/averages, "
            "changed files, and accumulated engine Usage."
        ),
    )
    audit_parser.add_argument(
        "--since",
        required=True,
        metavar="WINDOW",
        help="Trailing window to aggregate, e.g. '7d', '24h', '30m'.",
    )
    audit_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the aggregate as JSON (machine-readable).",
    )

    # alc checks audit [--json]
    checks_parser = subparsers.add_parser(
        "checks",
        help="Re-detect stacks and PROPOSE check_set upgrades against the Manifest.",
    )
    checks_subparsers = checks_parser.add_subparsers(dest="checks_action", required=True)

    checks_audit_parser = checks_subparsers.add_parser(
        "audit",
        help=(
            "Compare the Manifest's check_sets and each Blueprint's resolved checks "
            "against a fresh stack detection; never writes. Also flags checks "
            "commented out for a missing binary."
        ),
    )
    checks_audit_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the proposal as JSON (machine-readable).",
    )

    checks_history_parser = checks_subparsers.add_parser(
        "history",
        help=(
            "Aggregate the run logs' check_finished events into per-check "
            "pass-rate, mean duration, and a flake score; never writes."
        ),
    )
    checks_history_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the history as JSON (machine-readable).",
    )

    # alc metrics [--check NAME] [--json]
    metrics_parser = subparsers.add_parser(
        "metrics",
        help=(
            "Show the metric-check time series recorded in the project's "
            "ledger: values, delta, and trend per check."
        ),
    )
    metrics_parser.add_argument(
        "--check",
        default=None,
        metavar="NAME",
        help="Only show this check's series (default: every check in the ledger).",
    )
    metrics_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the series as JSON (machine-readable).",
    )

    # alc schedule install|list|remove <tick|cycle NAME> --every 15m
    schedule_parser = subparsers.add_parser(
        "schedule",
        help=(
            "Generate and manage the crontab entry that fires `alc tick` or "
            "`alc cycle NAME` on a cadence."
        ),
    )
    schedule_subparsers = schedule_parser.add_subparsers(
        dest="schedule_action", required=True
    )

    schedule_install_parser = schedule_subparsers.add_parser(
        "install",
        help=(
            "Write (or update) the crontab entry, idempotently — running it "
            "twice never produces two entries."
        ),
    )
    schedule_install_parser.add_argument(
        "target", choices=["tick", "cycle"], help="What to schedule."
    )
    schedule_install_parser.add_argument(
        "name", nargs="?", default=None, help="Loop name — required for 'cycle', omit for 'tick'."
    )
    schedule_install_parser.add_argument(
        "--every",
        required=True,
        metavar="CADENCE",
        help="How often to fire, e.g. '15m' or '1h'.",
    )

    schedule_list_parser = schedule_subparsers.add_parser(
        "list", help="List the crontab entries ALC itself installed."
    )
    schedule_list_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the entries as JSON (machine-readable).",
    )

    schedule_remove_parser = schedule_subparsers.add_parser(
        "remove",
        help="Remove ALC's crontab entry for a target — never touches an operator-written line.",
    )
    schedule_remove_parser.add_argument(
        "target", choices=["tick", "cycle"], help="What to unschedule."
    )
    schedule_remove_parser.add_argument(
        "name", nargs="?", default=None, help="Loop name — required for 'cycle', omit for 'tick'."
    )

    # alc ui [--host H] [--port P] [--ui-dist PATH]
    ui_parser = subparsers.add_parser(
        "ui",
        help=(
            "Serve the alc web IDE (API + WebSocket, plus the built frontend when "
            "--ui-dist points at it). Requires the optional 'ui' extra."
        ),
    )
    ui_parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)."
    )
    ui_parser.add_argument(
        "--port", type=int, default=8642, help="Port to bind (default: 8642)."
    )
    ui_parser.add_argument(
        "--ui-dist",
        default=None,
        metavar="PATH",
        help=(
            "Explicit directory of the built frontend to serve as an SPA. Must "
            "contain index.html (error + exit 1 otherwise). When unset, falls "
            "back to ALC_UI_DIST, then the bundled build, then API-only."
        ),
    )
    ui_parser.add_argument(
        "--no-ui",
        action="store_true",
        default=False,
        help="Serve only the API and WebSocket (do not serve any frontend).",
    )

    args = parser.parse_args()

    if args.command == "init":
        sys.exit(cmd_init(args))
    elif args.command == "setup":
        sys.exit(cmd_setup(args))
    elif args.command == "lint":
        sys.exit(cmd_lint(args))
    elif args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "spike":
        sys.exit(cmd_spike(args))
    elif args.command == "flow":
        sys.exit(cmd_flow(args))
    elif args.command == "tick":
        sys.exit(cmd_tick(args))
    elif args.command == "retry":
        sys.exit(cmd_retry(args))
    elif args.command == "enqueue":
        sys.exit(cmd_enqueue(args))
    elif args.command == "land":
        sys.exit(cmd_land(args))
    elif args.command == "discard":
        sys.exit(cmd_discard(args))
    elif args.command == "explore":
        sys.exit(cmd_explore(args))
    elif args.command == "compare":
        sys.exit(cmd_compare(args))
    elif args.command == "adopt":
        sys.exit(cmd_adopt(args))
    elif args.command == "conduct":
        sys.exit(cmd_conduct(args))
    elif args.command == "cycle":
        sys.exit(cmd_cycle(args))
    elif args.command == "loop":
        sys.exit(cmd_loop(args))
    elif args.command == "specialist":
        sys.exit(cmd_specialist(args))
    elif args.command == "primer":
        sys.exit(cmd_primer(args))
    elif args.command == "new":
        sys.exit(cmd_new(args))
    elif args.command == "team":
        sys.exit(cmd_team(args))
    elif args.command == "prompts":
        if args.action == "eject" and not args.name:
            parser.error("prompts eject requires a prompt NAME")
        sys.exit(cmd_prompts(args))
    elif args.command == "status":
        sys.exit(cmd_status(args))
    elif args.command == "runs":
        sys.exit(cmd_runs(args))
    elif args.command == "audit":
        sys.exit(cmd_audit(args))
    elif args.command == "checks":
        sys.exit(cmd_checks(args))
    elif args.command == "metrics":
        sys.exit(cmd_metrics(args))
    elif args.command == "schedule":
        sys.exit(cmd_schedule(args))
    elif args.command == "ui":
        sys.exit(cmd_ui(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
