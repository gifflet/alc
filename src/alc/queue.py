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
from alc.merge import auto_merge_branches
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
            workdir: Path | None,
            env: dict[str, str] | None = None,
            skip_commit: bool = False,
        ) -> FlowReport:
            """Run this task (flow or specialist) in the given workdir.

            ``env`` carries per-run environment (e.g. the worktree's ALC_PORT range)
            into the engine turn(s). None -> unchanged (byte-identical).

            ``skip_commit`` is threaded to the FlowRunner so a committing demand run
            inside a worktree does NOT double-commit/revert (the worktree owns it);
            the specialist path has no terminal commit and ignores it.
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
                skip_commit=skip_commit,
            )

        branch: str | None = None
        # True only for a SUCCESSFUL committing demand run in a worktree — its
        # branch is eligible for the post-batch auto-merge (Part E). The
        # non-isolate/serial path and the outer-except path default it False.
        demand_committed = False

        if qt.isolate and is_git_repo(project_root):
            repo_root = git_toplevel(project_root)

            # Detect a committing demand: a flow whose commit is enabled. Such a
            # demand is committed ONCE by the worktree exit-commit (using the
            # demand's rendered message, excluding `.alc/`), not by the FlowRunner
            # — the two commits are reconciled into one.
            is_committing_demand = False
            demand_message = manifest.worktree_commit_message
            if qt.kind == "flow":
                try:
                    _flow = load_flow(flows_dir, unit_name)
                    if _flow.commit is not None and _flow.commit.enabled:
                        is_committing_demand = True
                        try:
                            demand_message = _flow.commit.message.format(
                                name=_flow.name,
                                task=(qt.task.splitlines()[0] if qt.task else ""),
                            )
                        except (KeyError, IndexError, ValueError):
                            demand_message = f"chore(cycle): {_flow.name}"
                except Exception:
                    pass  # a load failure surfaces via the outer try/except

            wt = IsolatedWorktree(
                repo_root,
                label="tick",
                commit_message=demand_message,
                exclude_paths=((".alc/",) if is_committing_demand else ()),
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
                    # Expose the primary port under the conventional `PORT` too (not just
                    # `ALC_PORT`) so a standard app binds it with zero ALC awareness.
                    port_env = {"ALC_PORT": str(ports[0]), "PORT": str(ports[0])}
                    for i, port in enumerate(ports[1:], start=2):
                        port_env[f"ALC_PORT_{i}"] = str(port)
                    port_env["ALC_PORTS"] = ",".join(str(p) for p in ports)
                # Provision gitignored runtime deps (node_modules/.env/data) into
                # the worktree so the demand's dev/qa can run the real app there.
                # With an empty worktree_provision this is a no-op -> byte-identical.
                provision_worktree(
                    wt_path, project_root, manifest.worktree_provision
                )
                report = _run(wt_path, port_env, skip_commit=is_committing_demand)
            except BaseException as exc:
                exc_info = (type(exc), exc, exc.__traceback__)
            finally:
                # Release the ports even on failure so a later run can reuse them.
                release_ports(ports)
                # For a committing demand the worktree owns the single commit:
                # keep it only on flow SUCCESS, otherwise discard the branch
                # (on exception report is None -> discarded, like the serial
                # revert). A non-committing isolate flow leaves commit_on_exit
                # True -> today's behavior (commit iff changes).
                if is_committing_demand:
                    wt.commit_on_exit = report is not None and report.success
                wt.__exit__(*exc_info)

            if exc_info[1] is not None:
                raise exc_info[1]

            branch = wt.branch if wt.committed else None
            # A committing demand that committed to its branch is auto-mergeable
            # post-batch. A failed demand has wt.committed False -> branch None ->
            # demand_committed False -> nothing to merge (Part C's discard).
            demand_committed = is_committing_demand and wt.committed
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
        auto_merge=demand_committed,
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


def _run_wave(
    wave_files: list[Path],
    manifest: Manifest,
    operator_layer: Path,
    flows_dir: Path,
    queue_dir: Path,
    max_workers: int,
) -> dict[Path, TickResult]:
    """Run exactly ``wave_files`` and return a ``{file: TickResult}`` map.

    This is the scheduling body extracted verbatim from the former
    ``process_queue``: with ``max_workers == 1`` every task runs serially; with
    ``> 1`` only isolated tasks (isolate:true + git repo) run concurrently in a
    ThreadPoolExecutor while all others share the workdir and run serially. The
    map is order-independent — the caller restores the original pending order.
    """
    project_root = operator_layer.parent

    if max_workers == 1:
        # Serial path — behaviourally identical to the original drain loop.
        return {
            task_file: _process_task(
                manifest, operator_layer, flows_dir, queue_dir, task_file
            )
            for task_file in wave_files
        }

    # Parallel path — only isolated tasks (isolate:true + git repo) may run
    # concurrently; all others share the working directory and run serially.
    is_git = is_git_repo(project_root)
    parallel_tasks, serial_tasks = _partition_tasks(wave_files, is_git)

    if serial_tasks:
        n = len(serial_tasks)
        print(f"{n} non-isolated task(s) will run serially", file=sys.stderr)

    results: dict[Path, TickResult] = {}

    # Run parallel-eligible tasks concurrently.
    if parallel_tasks:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_file = {
                pool.submit(
                    _process_task,
                    manifest,
                    operator_layer,
                    flows_dir,
                    queue_dir,
                    task_file,
                ): task_file
                for task_file in parallel_tasks
            }
            for future in future_to_file:
                results[future_to_file[future]] = future.result()

    # Run serial tasks one by one.
    for task_file in serial_tasks:
        results[task_file] = _process_task(
            manifest, operator_layer, flows_dir, queue_dir, task_file
        )

    return results


def _topological_waves(pending: list[Path]) -> list[list[Path]]:
    """Order ``pending`` task files into dependency WAVES (Kahn's algorithm).

    Each file's QueueTask declares an optional ``id`` and ``depends_on``; a file
    that is unreadable is treated as having no id and no deps. A task's BLOCKING
    deps are only those ids present among the pending tasks (a dep on something
    not in this drain can't block it). Wave 0 is the files with no blocking dep;
    each next wave is the files whose blocking deps all landed in earlier waves.
    Each wave is sorted by filename for determinism.

    With NO ``depends_on`` anywhere, wave 0 already holds every file, so the
    result is exactly ``[sorted(pending)]`` — one wave, byte-identical to the
    pre-change single drain.

    A dependency cycle (files remain but none is ready) never deadlocks: the
    remaining files collapse into one final wave and a WARNING is printed.
    """
    # Read each file's id + deps once (unreadable -> no id, no deps).
    deps_by_file: dict[Path, list[str]] = {}
    id_by_file: dict[Path, str | None] = {}
    for task_file in pending:
        try:
            qt = QueueTask.model_validate(yaml.safe_load(task_file.read_text()))
            id_by_file[task_file] = qt.id
            deps_by_file[task_file] = list(qt.depends_on)
        except Exception:
            id_by_file[task_file] = None
            deps_by_file[task_file] = []

    pending_ids = {id_by_file[f] for f in pending if id_by_file[f] is not None}
    # Blocking deps = declared deps that name an id present in THIS drain.
    blocking: dict[Path, set[str]] = {
        f: {d for d in deps_by_file[f] if d in pending_ids} for f in pending
    }

    waves: list[list[Path]] = []
    remaining = set(pending)
    resolved_ids: set[str] = set()

    while remaining:
        ready = sorted(f for f in remaining if blocking[f] <= resolved_ids)
        if not ready:
            # A cycle among the remaining files — never deadlock: emit one final
            # wave with everything left and warn (deterministic filename order).
            print(
                "[drain] WARNING: dependency cycle detected; running remaining "
                f"{len(remaining)} task(s) in one wave.",
                file=sys.stderr,
                flush=True,
            )
            waves.append(sorted(remaining))
            break
        waves.append(ready)
        for f in ready:
            remaining.discard(f)
            if id_by_file[f] is not None:
                resolved_ids.add(id_by_file[f])  # type: ignore[arg-type]

    return waves


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

    Tasks are scheduled in dependency WAVES (``_topological_waves``): a task that
    declares ``depends_on`` runs only AFTER its precedents have MERGED, so its
    worktree branches off the updated main. Each wave's passed committing-demand
    branches are auto-merged BEFORE the next wave runs. With NO ``depends_on``
    anywhere this is a single wave of all pending tasks with ONE trailing
    auto-merge — byte-identical to the pre-change drain.

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

    results_by_file: dict[Path, TickResult] = {}
    for wave in _topological_waves(pending):
        wave_results = _run_wave(
            wave, manifest, operator_layer, flows_dir, queue_dir, max_workers
        )
        results_by_file.update(wave_results)

        # Auto-merge THIS wave's passed committing-demand branches into the
        # current branch (Part D/E) so the NEXT wave's worktrees branch off the
        # updated main. Branches from non-committing isolate tasks (auto_merge
        # False) are left for manual review. When no committing demand ran in a
        # worktree this list is empty -> no-op. With one wave (no deps) this is
        # the single trailing auto-merge of the pre-change drain.
        merge_branches = [
            r.branch
            for f in wave
            if (r := wave_results.get(f)) is not None and r.branch and r.auto_merge
        ]
        if merge_branches:
            report = auto_merge_branches(git_toplevel(project_root), merge_branches)
            for r in wave_results.values():
                if r.branch and r.auto_merge:
                    r.merged = r.branch in report.merged  # True merged / False left
            print(report.summary(), file=sys.stderr, flush=True)

    return [results_by_file[f] for f in pending]
