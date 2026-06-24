# cli.py — argparse entrypoint for ALC.
# Provides subcommands: `alc lint`, `alc run`, and `alc flow`.
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


def cmd_lint(args: argparse.Namespace) -> int:
    """Run `alc lint`: check the Operator Layer for Policy Gate violations."""
    from alc.intake import load_all_blueprints, load_manifest
    from alc.policy import has_errors, lint

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)
    blueprints = load_all_blueprints(manifest, operator_layer)
    violations = lint(manifest, blueprints)

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
    from alc.intake import load_blueprint, load_manifest
    from alc.runner import MandateRunner, PolicyViolationError
    from alc.worktree import IsolatedWorktree, git_toplevel, is_git_repo

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    blueprints_dir = operator_layer.parent / manifest.blueprints_dir
    blueprint = load_blueprint(blueprints_dir, args.blueprint)

    runner = MandateRunner(manifest=manifest, operator_layer=operator_layer)

    use_isolate = args.isolate
    if use_isolate and not is_git_repo(Path.cwd()):
        print("--isolate ignored: not inside a git repository", file=sys.stderr)
        use_isolate = False

    if use_isolate:
        repo_root = git_toplevel(Path.cwd())
        wt = IsolatedWorktree(repo_root, label="run")
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
        return 0 if report.success else 1

    # Non-isolated path (default).
    try:
        report = runner.run(
            blueprint=blueprint,
            task=args.task,
            engine_override=args.engine,
        )
    except PolicyViolationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    _print_run_report(report)
    return 0 if report.success else 1


def cmd_tick(args: argparse.Namespace) -> int:
    """Run `alc tick`: drain the task queue (Unattended Mode Trigger).

    Processes every pending *.yaml file in queue_dir once and exits. Designed
    to be called by cron or launchd — cron provides the cadence; this command
    provides one drain pass. Exit code is always 0 (cron-friendly); per-task
    outcomes live in the Gate reports under done/.
    """
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
        results = process_queue(manifest, operator_layer)

    if not results:
        print("No pending tasks.")
        return 0

    for result in results:
        status = "SUCCESS" if result.success else "FAILED"
        line = f"{result.task_file}: {result.flow} -> {status}"
        if result.branch:
            line += f" (branch {result.branch})"
        print(line)

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
        )
    except ValueError as exc:
        print(f"[ERROR] Conductor could not produce a valid plan: {exc}", file=sys.stderr)
        return 1

    # Summary header.
    print(f"Goal: {report.goal}")
    print()
    print("Plan:")
    for item in report.plan.items:
        print(f"  -> {item.flow}: {item.task}")
    print()

    if report.mode == "run":
        all_ok = True
        for flow_report in report.flow_reports:
            status = "SUCCESS" if flow_report.success else "FAILED"
            print(f"  {flow_report.flow} -> {status}")
            if not flow_report.success:
                all_ok = False
        print()
        print(report.model_dump_json(indent=2))
        return 0 if all_ok else 1

    # Enqueue mode.
    n = len(report.enqueued_files)
    files_str = ", ".join(report.enqueued_files)
    print(f"Enqueued {n} task(s): {files_str}")
    print()
    print(report.model_dump_json(indent=2))
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
    from alc.flow import FlowRunner
    from alc.intake import load_flow, load_manifest
    from alc.runner import PolicyViolationError
    from alc.worktree import IsolatedWorktree, git_toplevel, is_git_repo

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    flows_dir = operator_layer.parent / manifest.flows_dir
    flow = load_flow(flows_dir, args.flow_name)

    runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)

    use_isolate = args.isolate
    if use_isolate and not is_git_repo(Path.cwd()):
        print("--isolate ignored: not inside a git repository", file=sys.stderr)
        use_isolate = False

    if use_isolate:
        repo_root = git_toplevel(Path.cwd())
        wt = IsolatedWorktree(repo_root, label="flow")
        wt_path = wt.__enter__()
        exc_info = (None, None, None)
        report = None
        try:
            report = runner.run(
                flow=flow,
                task=args.task,
                engine_override=args.engine,
                workdir=wt_path,
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
        return 0 if report.success else 1

    # Non-isolated path (default).
    try:
        report = runner.run(
            flow=flow,
            task=args.task,
            engine_override=args.engine,
        )
    except PolicyViolationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    _print_flow_report(report)
    return 0 if report.success else 1


def main() -> None:
    """Console-script entrypoint."""
    parser = argparse.ArgumentParser(
        prog="alc",
        description="ALC — Agentic Layer Compiler & Runtime",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # alc lint
    subparsers.add_parser("lint", help="Check the Operator Layer for Policy Gate violations.")

    # alc run <blueprint> "<task>" [--engine NAME] [--isolate]
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

    # alc tick
    subparsers.add_parser(
        "tick",
        help=(
            "Drain the task queue (Unattended Mode Trigger). "
            "Processes all pending tasks once and exits — call via cron."
        ),
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

    # alc flow <flow_name> "<task>" [--engine NAME] [--isolate]
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

    args = parser.parse_args()

    if args.command == "lint":
        sys.exit(cmd_lint(args))
    elif args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "flow":
        sys.exit(cmd_flow(args))
    elif args.command == "tick":
        sys.exit(cmd_tick(args))
    elif args.command == "conduct":
        sys.exit(cmd_conduct(args))
    elif args.command == "specialist":
        sys.exit(cmd_specialist(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
