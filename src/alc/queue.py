# queue.py — Unattended Mode: drains the task queue (the Source) for alc tick.
# process_queue moves task files into done/ (the Gate). When max_workers > 1
# and serial tasks are present, it prints a demotion notice to stderr.
from __future__ import annotations

import re
import sys
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import yaml

from alc.flow import FlowRunner
from alc.intake import load_flow, load_specialist
from alc.models import FlowReport, Manifest, QueueTask, RunReport, Scorecard, TickResult
from alc.specialist import run_specialist
from alc.textutil import slugify as _slugify
from alc.worktree import (
    IsolatedWorktree,
    allocate_free_ports,
    git_toplevel,
    is_git_repo,
    provision_worktree,
    release_ports,
)


# Feedback section appended to a re-enqueued task's body when the prior attempt
# failed. Kept as a module constant so tests can assert the exact wording.
_RETRY_FEEDBACK_HEADER = "## Previous attempt failed — fix the specific reason below"
_RETRY_FEEDBACK_INTRO = (
    "The prior attempt of this task failed validation. Address this exact issue "
    "so it passes this time; do not repeat it:"
)


def build_retry_task(
    qt: QueueTask, failure_output: str, max_feedback_chars: int = 2000
) -> QueueTask:
    """Return a new QueueTask that re-runs ``qt`` carrying the failure feedback.

    The returned task is a copy of ``qt`` with its ``task`` body extended by a
    clearly-delimited feedback section (the truncated failure output) and its
    ``retries`` counter incremented. Every other field (flow/kind/name/isolate/
    engine) is preserved — this is a forward-only, more-context version of the
    same unit, not an intra-flow loop.
    """
    feedback = failure_output.strip()[:max_feedback_chars]
    task = (
        f"{qt.task}\n\n"
        f"{_RETRY_FEEDBACK_HEADER}\n"
        f"{_RETRY_FEEDBACK_INTRO}\n\n"
        f"{feedback}"
    )
    return qt.model_copy(update={"task": task, "retries": qt.retries + 1})


def failure_feedback(report: FlowReport) -> str:
    """Return the feedback text for a retry: the failing stage's output.

    A Flow stops at its first failing stage, so ``stages[-1]`` is that stage; the
    ``_error_flow_report`` path also carries a single stage with the traceback.
    Shared by the automatic (drain) and manual (`alc retry`) retry paths.
    """
    if report.stages:
        return report.stages[-1].output_text
    return "The previous attempt failed without a captured stage output."


def write_retry_task(retry_qt: QueueTask, queue_dir: Path, original_stem: str) -> Path:
    """Write ``retry_qt`` as a new PENDING task YAML in ``queue_dir``; return its path.

    The file lands directly in ``queue_dir`` (not under done/) so the next drain
    pass picks it up. The filename is derived from ``original_stem`` (with any
    leading ``retry-…`` marker stripped so retries don't accrete prefixes) plus a
    short slug of the task's first line and a uuid, making it recognisable as a
    retry and unique across passes.

    Lineage: the whole retry chain shares ONE root stem. Retrying an original
    (retry_of=None) roots the lineage at its own ``original_stem``; retrying a
    retry (which already carries retry_of) propagates that same root forward.
    """
    root = retry_qt.retry_of or original_stem
    retry_qt = retry_qt.model_copy(update={"retry_of": root})
    base = re.sub(r"^retry-\d+-", "", original_stem)
    first_line = retry_qt.task.splitlines()[0] if retry_qt.task else ""
    slug = _slugify(first_line) or _slugify(base) or "task"
    uid = uuid.uuid4().hex[:8]
    path = queue_dir / f"retry-{retry_qt.retries:02d}-{slug}-{uid}.yaml"
    path.write_text(yaml.safe_dump(retry_qt.model_dump(), sort_keys=True))
    return path


@dataclass
class FailedTask:
    """One outstanding failure an operator could retry (see ``outstanding_failures``)."""

    stem: str      # filename stem of the latest failed attempt (what `alc retry <stem>` takes)
    title: str     # first line of the archived task body
    reason: str    # short single-line tail of the failing-stage output
    retries: int   # qt.retries of the latest failed attempt


def _failure_reason(report: FlowReport) -> str:
    """A short, RELIABLE failure reason from the report's structured record: the
    failing stage and the check(s) that failed — not free-text prose.

    ``stages[-1]`` is the stage that failed; its last attempt's ``failed_checks``
    are the gate(s) that never passed. Falls back to an engine-error note when no
    check was recorded (e.g. the engine itself failed), or a generic note when the
    report carries no stage.
    """
    if not report.stages:
        return "no captured failure"
    stage = report.stages[-1]
    checks = stage.attempts[-1].failed_checks if stage.attempts else []
    if checks:
        return f"failed at {stage.blueprint}: check(s) {', '.join(checks)}"
    return f"failed at {stage.blueprint}: engine error"


def outstanding_failures(done_dir: Path) -> list[FailedTask]:
    """Return the failed tasks an operator could retry — one per UNRESOLVED lineage.

    Scans every ``done/<stem>.report.json`` archive, groups archived tasks by
    their lineage root (``qt.retry_of or <stem>``), and drops any root whose
    lineage already contains a successful attempt (resolved by a later retry).
    For each remaining root the LATEST failed attempt (highest ``qt.retries``) is
    returned, since that is what a fresh retry would descend from. Sorted by
    recency (most recently failed first).

    An absent or empty ``done_dir`` yields an empty list.
    """
    if not done_dir.exists():
        return []

    # Per-root state: whether any attempt succeeded, and the latest failed attempt
    # (with its report file mtime, used to sort the list by recency).
    resolved: dict[str, bool] = {}
    latest_failed: dict[str, tuple[str, QueueTask, FlowReport, float]] = {}

    for report_file in sorted(done_dir.glob("*.report.json")):
        stem = report_file.name[: -len(".report.json")]
        task_file = done_dir / f"{stem}.yaml"
        if not task_file.exists():
            continue  # orphan report with no archived task -> skip

        try:
            qt = QueueTask.model_validate(yaml.safe_load(task_file.read_text()))
            report = FlowReport.model_validate_json(report_file.read_text())
        except Exception:
            continue  # unreadable / invalid archive -> skip

        root = qt.retry_of or stem
        if report.success:
            resolved[root] = True
            continue
        resolved.setdefault(root, False)

        # Keep the highest-retries failed attempt for this root (ties -> any).
        current = latest_failed.get(root)
        if current is None or qt.retries > current[1].retries:
            latest_failed[root] = (stem, qt, report, report_file.stat().st_mtime)

    ranked: list[tuple[float, FailedTask]] = []
    for root, (stem, qt, report, mtime) in latest_failed.items():
        if resolved.get(root):
            continue  # a later attempt in this lineage succeeded -> not outstanding
        title = qt.task.splitlines()[0] if qt.task else ""
        ranked.append((
            mtime,
            FailedTask(
                stem=stem,
                title=title,
                reason=_failure_reason(report),
                retries=qt.retries,
            ),
        ))

    ranked.sort(key=lambda r: r[0], reverse=True)  # most recently failed first
    return [ft for _, ft in ranked]


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
    env: dict[str, str] | None = None,
) -> FlowReport:
    """Run one specialist queue task, threading ``workdir``/``env`` when isolated."""
    specialists_dir = operator_layer.parent / manifest.specialists_dir
    specialist = load_specialist(specialists_dir, name)
    report = run_specialist(
        manifest=manifest,
        operator_layer=operator_layer,
        specialist=specialist,
        task=qt.task,
        engine_override=qt.engine,
        workdir=workdir,
        env=env,
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
    # Captured outside the try so the auto-retry below can read it even if an
    # early exception happened. It stays None when parsing failed -> no retry.
    qt: QueueTask | None = None
    try:
        raw = yaml.safe_load(task_file.read_text())
        qt = QueueTask.model_validate(raw)
        unit_name = qt.unit_name()
        flow_name = unit_name  # TickResult.flow carries the unit name (flow or specialist)
        engine_name = qt.engine or manifest.default_engine

        # Announce the active unit so operator output is grouped under a header.
        print(f"▶ {task_file.name} — {qt.kind}:{unit_name}", file=sys.stderr, flush=True)

        def _run(
            workdir: Path | None, env: dict[str, str] | None = None
        ) -> FlowReport:
            """Run this task (flow or specialist) in the given workdir.

            ``env`` carries per-run environment (e.g. the worktree's ALC_PORT range)
            into the engine turn(s). None -> unchanged (byte-identical).
            """
            if qt.kind == "specialist":
                # A specialist run in a worktree resolves its Knowledge File against
                # the worktree so the Learn write lands on the isolated branch.
                ol = (workdir / operator_layer.name) if workdir is not None else operator_layer
                return _run_specialist_task(manifest, ol, qt, unit_name, workdir, env)
            flow = load_flow(flows_dir, unit_name)
            runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
            return runner.run(
                flow=flow,
                task=qt.task,
                engine_override=qt.engine,
                workdir=workdir,
                env=env,
            )

        branch: str | None = None

        # Safety guard: a committing flow inside an isolated worktree would fire
        # BOTH the IsolatedWorktree exit-commit AND the flow's terminal commit,
        # producing a double-commit. Refuse loudly instead of silently corrupting.
        if qt.kind == "flow" and qt.isolate and is_git_repo(project_root):
            try:
                _check_flow = load_flow(flows_dir, unit_name)
                if _check_flow.commit is not None and _check_flow.commit.enabled:
                    _msg = (
                        "committing flows are not yet supported with worktree isolation "
                        "(isolate:true); see ROADMAP: worktree with linked dependencies"
                    )
                    print(f"[ERROR] {_msg}", file=sys.stderr)
                    return TickResult(
                        task_file=task_file.name,
                        flow=flow_name,
                        success=False,
                        branch=None,
                        report=_error_flow_report(unit_name, engine_name, _msg),
                    )
            except Exception:
                pass  # load failure will be caught by the outer try/except below

        if qt.isolate and is_git_repo(project_root):
            repo_root = git_toplevel(project_root)
            wt = IsolatedWorktree(
                repo_root, label="tick", commit_message=manifest.worktree_commit_message
            )
            wt_path = wt.__enter__()
            exc_info = (None, None, None)
            report: FlowReport | None = None
            # Free port RANGE for this worktree run. Declared before the try so the
            # `finally` can ALWAYS release, even if allocation itself raises.
            ports: list[int] = []
            port_env: dict[str, str] | None = None
            try:
                # Allocate a free port RANGE so N parallel dev servers don't collide;
                # injected as ALC_PORT / ALC_PORT_2.. / ALC_PORTS. With worktree_ports
                # == 0 (default) nothing is allocated and no env is passed ->
                # byte-identical to today. Inside the try so a (pathological)
                # allocation failure still cleans up the worktree via finally.
                if manifest.worktree_ports > 0:
                    ports = allocate_free_ports(manifest.worktree_ports)
                    port_env = {"ALC_PORT": str(ports[0])}
                    for i, port in enumerate(ports[1:], start=2):
                        port_env[f"ALC_PORT_{i}"] = str(port)
                    port_env["ALC_PORTS"] = ",".join(str(p) for p in ports)
                # Provision gitignored runtime deps (node_modules/.env/data) into
                # the worktree so the demand's dev/qa can run the real app there.
                # With an empty worktree_provision this is a no-op -> byte-identical.
                provision_worktree(
                    wt_path, project_root, manifest.worktree_provision
                )
                report = _run(wt_path, port_env)
            except BaseException as exc:
                exc_info = (type(exc), exc, exc.__traceback__)
            finally:
                # Release the ports even on failure so a later run can reuse them.
                release_ports(ports)
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

    # Auto-retry with feedback: a failed task whose lineage has retries left is
    # re-enqueued (forward-only) carrying the failure output so the next drain
    # pass can fix the specific reason. With max_task_retries == 0 (default) this
    # whole block is skipped -> byte-identical to the pre-feature behavior.
    if not success and qt is not None and qt.retries < manifest.max_task_retries:
        retry_qt = build_retry_task(qt, failure_feedback(report))
        write_retry_task(retry_qt, queue_dir, task_file.stem)
        print(
            f"▶ retry queued (attempt {retry_qt.retries}/{manifest.max_task_retries})"
            " — carrying the failure feedback",
            file=sys.stderr,
            flush=True,
        )

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
