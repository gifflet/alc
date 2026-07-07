# fanout.py — Concurrent fan-out: run isolated units (Flows/Blueprints) in parallel.
# Each unit runs in its own IsolatedWorktree, so file edits land only on that
# unit's branch. The work is subprocess-bound (engine + check subprocesses), so a
# ThreadPoolExecutor is the right primitive — nothing has to become async, and the
# control-plane / execution-plane split is untouched.
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alc.flow import FlowRunner
from alc.intake import load_blueprint, load_flow
from alc.models import FanoutReport, Manifest, UnitResult
from alc.runner import MandateRunner
from alc.worktree import IsolatedWorktree, git_toplevel, is_git_repo


def run_unit(
    manifest: Manifest,
    operator_layer: Path,
    kind: str,
    name: str,
    task: str,
    engine_override: str | None = None,
) -> UnitResult:
    """Run one Flow or Blueprint in a fresh IsolatedWorktree and return its outcome.

    Args:
        manifest: The loaded Manifest (provides engines, dirs, compute tiers).
        operator_layer: Path to the ``.alc/`` directory.
        kind: "flow" or "blueprint" — selects FlowRunner or MandateRunner.
        name: The Flow or Blueprint name (also used as the worktree label).
        task: The free-text task description for this unit.
        engine_override: If set, use this engine instead of manifest.default_engine.

    Returns:
        UnitResult carrying the report and the committed branch (or an error).

    Raises:
        RuntimeError: If the project root is not inside a git repository — fan-out
            requires per-unit worktree isolation.
    """
    project_root = operator_layer.parent
    if not is_git_repo(project_root):
        raise RuntimeError(
            "Concurrent fan-out requires a git repository: "
            f"{project_root} is not inside a git work tree."
        )

    try:
        repo_root = git_toplevel(project_root)
        wt = IsolatedWorktree(repo_root, label=f"fanout-{name}")
        # Use the context manager manually so we can inspect wt after __exit__
        # (mirrors cli.py: enter -> run -> __exit__ under try/finally).
        wt_path = wt.__enter__()
        exc_info = (None, None, None)
        run_report = None
        flow_report = None
        try:
            if kind == "flow":
                flow = load_flow(project_root / manifest.flows_dir, name)
                runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
                flow_report = runner.run(
                    flow=flow,
                    task=task,
                    engine_override=engine_override,
                    workdir=wt_path,
                )
            else:
                blueprint = load_blueprint(project_root / manifest.blueprints_dir, name)
                runner = MandateRunner(manifest=manifest, operator_layer=operator_layer)
                run_report = runner.run(
                    blueprint=blueprint,
                    task=task,
                    engine_override=engine_override,
                    workdir=wt_path,
                )
        except BaseException as exc:
            exc_info = (type(exc), exc, exc.__traceback__)
        finally:
            wt.__exit__(*exc_info)

        if exc_info[1] is not None:
            raise exc_info[1]

        report = flow_report if kind == "flow" else run_report
        return UnitResult(
            kind=kind,
            name=name,
            task=task,
            success=report.success,
            branch=wt.branch if wt.committed else None,
            run_report=run_report,
            flow_report=flow_report,
        )
    except Exception as exc:
        # A single unit failure must never kill the pool — record it and move on.
        return UnitResult(
            kind=kind,
            name=name,
            task=task,
            success=False,
            error=str(exc),
        )


def run_fanout(
    manifest: Manifest,
    operator_layer: Path,
    units: list[dict],
    max_workers: int = 4,
) -> FanoutReport:
    """Run every unit concurrently, each isolated in its own git worktree.

    Args:
        manifest: The loaded Manifest.
        operator_layer: Path to the ``.alc/`` directory.
        units: Ordered list of ``{"kind", "name", "task"}`` dicts. ``kind`` is
            "flow" or "blueprint".
        max_workers: Bounded concurrency (default 4). The work is subprocess-bound,
            so threads are correct.

    Returns:
        FanoutReport whose ``units`` preserve the input order and whose ``success``
        is True only if every unit succeeded.
    """
    results: list[UnitResult] = [None] * len(units)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_index = {
            pool.submit(
                run_unit,
                manifest,
                operator_layer,
                unit["kind"],
                unit["name"],
                unit["task"],
            ): index
            for index, unit in enumerate(units)
        }
        for future in future_to_index:
            index = future_to_index[future]
            results[index] = future.result()

    success = all(r.success for r in results)
    return FanoutReport(units=results, success=success)
