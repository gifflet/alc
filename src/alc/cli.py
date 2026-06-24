# cli.py — argparse entrypoint for ALC.
# Provides two subcommands: `alc lint` and `alc run <blueprint> "<task>" [--engine NAME]`.
from __future__ import annotations

import argparse
import json
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
    """Run `alc run <blueprint> "<task>" [--engine NAME]`."""
    from alc.intake import load_blueprint, load_manifest
    from alc.policy import has_errors, lint
    from alc.runner import MandateRunner, PolicyViolationError

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    blueprints_dir = operator_layer.parent / manifest.blueprints_dir
    blueprint = load_blueprint(blueprints_dir, args.blueprint)

    runner = MandateRunner(manifest=manifest, operator_layer=operator_layer)

    try:
        report = runner.run(
            blueprint=blueprint,
            task=args.task,
            engine_override=args.engine,
        )
    except PolicyViolationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Print concise human-readable summary.
    status = "SUCCESS" if report.success else "FAILED"
    print(f"Status:   {status}")
    print(f"Engine:   {report.engine}")
    print(f"Attempts: {report.scorecard.passes}")
    print(
        f"Scorecard: span={report.scorecard.span} passes={report.scorecard.passes} "
        f"streak={report.scorecard.streak} touch={report.scorecard.touch}"
    )
    print()
    # Print the full RunReport as JSON.
    print(report.model_dump_json(indent=2))

    return 0 if report.success else 1


def cmd_flow(args: argparse.Namespace) -> int:
    """Run `alc flow <flow_name> "<task>" [--engine NAME]`."""
    from alc.flow import FlowRunner
    from alc.intake import load_flow, load_manifest
    from alc.runner import PolicyViolationError

    operator_layer = _find_operator_layer()
    manifest = load_manifest(operator_layer)

    flows_dir = operator_layer.parent / manifest.flows_dir
    flow = load_flow(flows_dir, args.flow_name)

    runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)

    try:
        report = runner.run(
            flow=flow,
            task=args.task,
            engine_override=args.engine,
        )
    except PolicyViolationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Print concise human-readable summary.
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
    # Print the full FlowReport as JSON.
    print(report.model_dump_json(indent=2))

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

    # alc run <blueprint> "<task>" [--engine NAME]
    run_parser = subparsers.add_parser("run", help="Run a Blueprint against a task.")
    run_parser.add_argument("blueprint", help="Blueprint name (e.g. 'chore').")
    run_parser.add_argument("task", help="Free-text task description.")
    run_parser.add_argument("--engine", default=None, help="Override the default engine.")

    # alc flow <flow_name> "<task>" [--engine NAME]
    flow_parser = subparsers.add_parser(
        "flow", help="Run a Flow (multi-stage pipeline) against a task."
    )
    flow_parser.add_argument("flow_name", help="Flow name (e.g. 'ship').")
    flow_parser.add_argument("task", help="Free-text task description.")
    flow_parser.add_argument("--engine", default=None, help="Override the default engine.")

    args = parser.parse_args()

    if args.command == "lint":
        sys.exit(cmd_lint(args))
    elif args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "flow":
        sys.exit(cmd_flow(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
