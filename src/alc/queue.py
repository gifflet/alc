# queue.py — Unattended Mode: drains the task queue (the Source) for alc tick.
# process_queue moves task files into done/ (the Gate). When max_workers > 1
# and serial tasks are present, it prints a demotion notice to stderr.
from __future__ import annotations

import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from alc.flow import FlowRunner
from alc.intake import load_flow, load_specialist
from alc.models import FlowReport, Manifest, QueueTask, RunReport, Scorecard, TickResult
from alc.specialist import run_specialist
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


def _specialist_flow_report(name: str, engine: str, act: RunReport) -> FlowReport:
    """Wrap a Specialist's Act RunReport into a FlowReport for uniform Gate records."""
    return FlowReport(
        flow=name,
        engine=engine,
        success=act.success,
        stages=[act],
        scorecard=act.scorecard,
    )


def _run_specialist_task(
    manifest: Manifest,
    operator_layer: Path,
    qt: QueueTask,
    name: str,
    workdir: Path | None,
) -> FlowReport:
    """Run one specialist queue task, threading ``workdir`` when isolated."""
    specialists_dir = operator_layer.parent / manifest.specialists_dir
    specialist = load_specialist(specialists_dir, name)
    report = run_specialist(
        manifest=manifest,
        operator_layer=operator_layer,
        specialist=specialist,
        task=qt.task,
        engine_override=qt.engine,
        workdir=workdir,
    )
    engine_name = qt.engine or manifest.default_engine
    return _specialist_flow_report(name, engine_name, report.act)


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
        unit_name = qt.unit_name()
        flow_name = unit_name  # TickResult.flow carries the unit name (flow or specialist)
        engine_name = qt.engine or manifest.default_engine

        def _run(workdir: Path | None) -> FlowReport:
            """Run this task (flow or specialist) in the given workdir."""
            if qt.kind == "specialist":
                # A specialist run in a worktree resolves its Knowledge File against
                # the worktree so the Learn write lands on the isolated branch.
                ol = (workdir / operator_layer.name) if workdir is not None else operator_layer
                return _run_specialist_task(manifest, ol, qt, unit_name, workdir)
            flow = load_flow(flows_dir, unit_name)
            runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
            return runner.run(
                flow=flow,
                task=qt.task,
                engine_override=qt.engine,
                workdir=workdir,
            )

        branch: str | None = None

        if qt.isolate and is_git_repo(project_root):
            repo_root = git_toplevel(project_root)
            wt = IsolatedWorktree(repo_root, label="tick")
            wt_path = wt.__enter__()
            exc_info = (None, None, None)
            report: FlowReport | None = None
            try:
                report = _run(wt_path)
            except BaseException as exc:
                exc_info = (type(exc), exc, exc.__traceback__)
            finally:
                wt.__exit__(*exc_info)

            if exc_info[1] is not None:
                raise exc_info[1]

            branch = wt.branch if wt.committed else None
        else:
            report = _run(None)

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


def _partition_tasks(
    pending: list[Path],
    is_git: bool,
) -> tuple[list[Path], list[Path]]:
    """Split *pending* task files into parallel-eligible and serial lists.

    A task is eligible to run concurrently only when **both** conditions hold:
    - Its ``isolate`` flag is True (it will run in an isolated git worktree).
    - The project root is a git repository (``is_git`` is True).

    Tasks that fail either condition share the working directory and must run
    serially to avoid filesystem conflicts.  The relative order within each
    returned list matches the original *pending* order.

    Args:
        pending: Sorted list of queue task file paths.
        is_git: Whether the project root is a git repository.

    Returns:
        A ``(parallel_list, serial_list)`` tuple.
    """
    parallel: list[Path] = []
    serial: list[Path] = []
    for task_file in pending:
        try:
            raw = yaml.safe_load(task_file.read_text())
            qt = QueueTask.model_validate(raw)
            isolate_and_git = qt.isolate and is_git
        except Exception:
            # Unreadable / invalid tasks are treated as serial; _process_task
            # will capture and report the error when it runs.
            isolate_and_git = False
        if isolate_and_git:
            parallel.append(task_file)
        else:
            serial.append(task_file)
    return parallel, serial


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
    - Dispatch by ``qt.kind``: flow tasks run via FlowRunner; specialist tasks
      run via run_specialist. Legacy files (only ``flow:``) drain identically.
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

    # Parallel path — only isolated tasks (isolate:true + git repo) may run
    # concurrently; all others share the working directory and run serially.
    is_git = is_git_repo(project_root)
    parallel_tasks, serial_tasks = _partition_tasks(pending, is_git)

    if serial_tasks:
        n = len(serial_tasks)
        print(f"{n} non-isolated task(s) will run serially", file=sys.stderr)

    # Map original pending index -> TickResult so we can restore order.
    pending_index: dict[Path, int] = {p: i for i, p in enumerate(pending)}
    results: list[TickResult] = [None] * len(pending)  # type: ignore[list-item]

    # Run parallel-eligible tasks concurrently.
    if parallel_tasks:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_index = {
                pool.submit(
                    _process_task,
                    manifest,
                    operator_layer,
                    flows_dir,
                    queue_dir,
                    task_file,
                ): pending_index[task_file]
                for task_file in parallel_tasks
            }
            for future in future_to_index:
                results[future_to_index[future]] = future.result()

    # Run serial tasks one by one, preserving their original positions.
    for task_file in serial_tasks:
        result = _process_task(manifest, operator_layer, flows_dir, queue_dir, task_file)
        results[pending_index[task_file]] = result

    return results
