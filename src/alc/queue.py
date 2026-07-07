# queue.py — Unattended Mode: drains the task queue (the Source) for alc tick.
# process_queue is a pure function: no printing, no side-effects beyond the
# filesystem operations needed to move task files into done/ (the Gate).
from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from alc.flow import FlowRunner
from alc.intake import load_flow
from alc.models import FlowReport, Manifest, QueueTask, RunReport, Scorecard, TickResult
from alc.worktree import IsolatedWorktree, git_toplevel, is_git_repo


def _error_flow_report(flow_name: str, engine: str, message: str) -> FlowReport:
    """Build a minimal failed FlowReport to record when a task cannot run."""
    failed_run = RunReport(
        blueprint="(error)",
        engine=engine,
        success=False,
        attempts=[],
        scorecard=Scorecard(span=0, passes=0, streak=0, touch=0),
        output_text=message,
    )
    return FlowReport(
        flow=flow_name,
        engine=engine,
        success=False,
        stages=[failed_run],
        scorecard=Scorecard(span=0, passes=0, streak=0, touch=0),
    )


def _process_task(
    manifest: Manifest,
    operator_layer: Path,
    flows_dir: Path,
    queue_dir: Path,
    task_file: Path,
) -> TickResult:
    """Run one pending task file and archive it to done/, returning its Gate record.

    This is the per-task processing body shared by both the serial and the
    parallel drain paths. Per-task failures are captured into a failed
    TickResult so one bad task never aborts the tick.
    """
    project_root = operator_layer.parent
    flow_name = "(unknown)"
    engine_name = manifest.default_engine
    try:
        raw = yaml.safe_load(task_file.read_text())
        qt = QueueTask.model_validate(raw)
        flow_name = qt.flow
        engine_name = qt.engine or manifest.default_engine

        flow = load_flow(flows_dir, qt.flow)
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)

        branch: str | None = None

        if qt.isolate and is_git_repo(project_root):
            repo_root = git_toplevel(project_root)
            wt = IsolatedWorktree(repo_root, label="tick")
            wt_path = wt.__enter__()
            exc_info = (None, None, None)
            report: FlowReport | None = None
            try:
                report = runner.run(
                    flow=flow,
                    task=qt.task,
                    engine_override=qt.engine,
                    workdir=wt_path,
                )
            except BaseException as exc:
                exc_info = (type(exc), exc, exc.__traceback__)
            finally:
                wt.__exit__(*exc_info)

            if exc_info[1] is not None:
                raise exc_info[1]

            branch = wt.branch if wt.committed else None
        else:
            report = runner.run(
                flow=flow,
                task=qt.task,
                engine_override=qt.engine,
                workdir=None,
            )

        success = report.success

    except Exception:
        tb = traceback.format_exc()
        report = _error_flow_report(flow_name, engine_name, tb)
        success = False
        branch = None

    # Persist the Gate: write the report JSON and move the task file.
    done_dir = queue_dir / "done"
    done_dir.mkdir(parents=True, exist_ok=True)

    (done_dir / f"{task_file.stem}.report.json").write_text(
        report.model_dump_json(indent=2)
    )
    task_file.rename(done_dir / task_file.name)

    return TickResult(
        task_file=task_file.name,
        flow=flow_name,
        success=success,
        branch=branch,
        report=report,
    )


def process_queue(
    manifest: Manifest,
    operator_layer: Path,
    max_workers: int = 1,
) -> list[TickResult]:
    """Drain the task queue: run each pending Flow and archive the task file.

    The queue directory (Source) is ``<project_root>/<manifest.queue_dir>``.
    Pending tasks are ``*.yaml`` files directly inside that directory; the
    ``done/`` subdirectory is naturally excluded because its files are not at
    the top level of a glob(``*.yaml``).

    For each task:
    - Parse the YAML into a QueueTask.
    - Load the FlowDefinition and run it via FlowRunner.
    - If ``qt.isolate`` is True and the project root is a git repo, wrap the
      run in an IsolatedWorktree (Sandbox), record the branch on TickResult.
    - Write the Gate (FlowReport JSON) to ``done/<stem>.report.json``.
    - Move the task file to ``done/<filename>`` so it is never reprocessed.

    Per-task failures are recorded as failed TickResults and do not abort the
    tick — the remaining tasks continue to be processed.

    Args:
        manifest: The loaded Manifest (provides queue_dir, flows_dir, engines).
        operator_layer: Path to the ``.alc/`` directory.
        max_workers: Number of tasks to process in parallel (default 1, serial).
            When > 1 the per-task bodies run in a ThreadPoolExecutor; each task's
            worktree isolation and distinct done/ filenames keep this thread-safe.

    Returns:
        List of TickResult, one per pending task found, in the original pending
        order (empty if no queue dir).
    """
    project_root = operator_layer.parent
    queue_dir = project_root / manifest.queue_dir

    if not queue_dir.exists():
        return []

    pending = sorted(queue_dir.glob("*.yaml"))
    if not pending:
        return []

    flows_dir = project_root / manifest.flows_dir

    if max_workers == 1:
        # Serial path — behaviourally identical to the original drain loop.
        return [
            _process_task(manifest, operator_layer, flows_dir, queue_dir, task_file)
            for task_file in pending
        ]

    # Parallel path — preserve the original pending order in the results list.
    results: list[TickResult] = [None] * len(pending)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_index = {
            pool.submit(
                _process_task,
                manifest,
                operator_layer,
                flows_dir,
                queue_dir,
                task_file,
            ): index
            for index, task_file in enumerate(pending)
        }
        for future in future_to_index:
            results[future_to_index[future]] = future.result()

    return results
