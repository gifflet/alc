# cli.py — argparse entrypoint for ALC.
# Provides subcommands: `alc init` (supports --setup), `alc lint`, `alc run`,
# `alc flow`, `alc tick`, `alc conduct`, `alc cycle`, `alc loop`, `alc specialist`,
# `alc setup`.
from __future__ import annotations

import argparse
import sys
from pathlib import Path


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


def cmd_init(args: argparse.Namespace) -> int:
    """Run `alc init [--force] [--setup]`: scaffold a default Operator Layer into cwd."""
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

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    blueprints = load_all_blueprints(manifest, operator_layer)
    violations = lint(manifest, blueprints)
    violations += validate_prompts(manifest, operator_layer, blueprints)
    violations += validate_provisions(manifest, operator_layer.parent)

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

    if use_isolate:
        repo_root = git_toplevel(Path.cwd())
        wt = IsolatedWorktree(
            repo_root, label="run", commit_message=manifest.worktree_commit_message
        )
        # Use the context manager manually so we can inspect wt after __exit__.
        wt_path = wt.__enter__()
        exc_info = (None, None, None)
        report = None
        try:
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
    """Run `alc conduct "<goal>" [--engine NAME] [--enqueue]`."""
    import sys

    from alc.conduct import conduct
    from alc.intake import load_manifest

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
        )
    except ValueError as exc:
        print(f"[ERROR] Conductor could not produce a valid plan: {exc}", file=sys.stderr)
        return 1

    # Summary header.
    print(f"Goal: {report.goal}")
    print()
    print("Plan:")
    for item in report.plan.items:
        print(f"  -> {item.name} ({item.kind}): {item.task}")
    print()

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
    from alc.intake import load_manifest, load_specialist
    from alc.specialist import run_specialist

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    specialists_dir = operator_layer.parent / manifest.specialists_dir
    specialist = load_specialist(specialists_dir, args.name)

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

    # Safety guard: a committing flow + worktree isolation would double-commit.
    # Refuse early with a clear error so the operator can choose one or the other.
    if use_isolate and flow.commit is not None and flow.commit.enabled:
        print(
            "[ERROR] committing flows are not yet supported with worktree isolation "
            "(isolate:true); see ROADMAP: worktree with linked dependencies",
            file=sys.stderr,
        )
        return 1

    if use_isolate:
        repo_root = git_toplevel(Path.cwd())
        wt = IsolatedWorktree(
            repo_root, label="flow", commit_message=manifest.worktree_commit_message
        )
        wt_path = wt.__enter__()
        exc_info = (None, None, None)
        report = None
        try:
            report = runner.run(
                flow=flow,
                task=args.task,
                engine_override=args.engine,
                workdir=wt_path,
                extra_context=extra_context,
                tier_override=args.tier,
            )
        except PolicyViolationError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            exc_info = (type(exc), exc, exc.__traceback__)
        except BaseException as exc:
            exc_info = (type(exc), exc, exc.__traceback__)
        finally:
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


def main() -> None:
    """Console-script entrypoint."""
    parser = argparse.ArgumentParser(
        prog="alc",
        description="ALC — Agentic Layer Compiler & Runtime",
    )
    from alc.setup_skill import _resolve_version

    parser.add_argument(
        "--version", action="version", version=f"alc {_resolve_version()}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # alc init [--force] [--setup]
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

    args = parser.parse_args()

    if args.command == "init":
        sys.exit(cmd_init(args))
    elif args.command == "setup":
        sys.exit(cmd_setup(args))
    elif args.command == "lint":
        sys.exit(cmd_lint(args))
    elif args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "flow":
        sys.exit(cmd_flow(args))
    elif args.command == "tick":
        sys.exit(cmd_tick(args))
    elif args.command == "retry":
        sys.exit(cmd_retry(args))
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
    elif args.command == "prompts":
        if args.action == "eject" and not args.name:
            parser.error("prompts eject requires a prompt NAME")
        sys.exit(cmd_prompts(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
