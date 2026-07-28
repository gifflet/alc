# service.py — Read/write helpers that back the per-project API.
#
# Every parse/validation delegates to the alc control plane (intake loaders,
# policy lint, queue retry helpers, engine registry) — the UI never
# reimplements alc logic. Functions here take a project root and return
# JSON-safe dicts for the route handlers.
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict
from pathlib import Path

import yaml
from pydantic import ValidationError

from alc import artifacts as artifacts_core
from alc import metrics as metrics_core
from alc import onboard as onboard_core
from alc import runs as runs_core
from alc import signals as signals_core
from alc.audit import audit_window, parse_since
from alc.branches import branch_diff, delete_branches, list_alc_branches, prune_worktrees
from alc.checks import audit_checks, check_history
from alc.delivery import build_pr_body, changed_files, current_branch, open_pr, push_branch
from alc.engines.registry import resolve_engine
from alc.harvest import harvest
from alc.intake import load_all_blueprints, load_all_loops, load_manifest
from alc.loop import ledger_path, load_loop_state, loops_dir, state_path
from alc.manifestedit import validate_manifest_text
from alc.merge import MergeReport, auto_merge_branches
from alc.models import DeliverySpec, FlowReport, QueueTask, Signal
from alc.packs import PACKS, hired_archetypes, pack_files, split_pack_files
from alc.policy import lint as _lint
from alc.policy import lint_loops, validate_provisions, validate_prompts
from alc.prompts import (
    _DEFAULT_PROMPTS,
    list_prompts,
    override_format_error,
    resolve_prompt,
    validate_prompt_override,
)
from alc.queue import (
    build_retry_task,
    failure_feedback,
    outstanding_failures,
    write_retry_task,
)
from alc.scaffold import detect_stacks
from alc.schedule import has_crontab, list_entries, read_crontab
from alc.stagepolicy import MIX_HEALTH_WINDOW_S, lint_stage, mix_health
from alc.textutil import slugify
from alc.ui.errors import ApiError
from alc.ui.repostatus import repo_status
from alc.variants import list_all_variants, mark_live
from alc.worktree import git_toplevel, is_git_repo


def operator_layer(root: Path) -> Path:
    """Return the ``.alc/`` directory for a project root."""
    return root / ".alc"


# ---------------------------------------------------------------------------
# Project summary (registry listing)
# ---------------------------------------------------------------------------


def project_summary(id: str, name: str, path: str) -> dict:
    """Return a lightweight summary for a registered project.

    Best-effort: a project whose manifest no longer loads is reported as
    unavailable rather than raising, so one broken project never breaks the list.
    """
    root = Path(path)
    summary = {
        "id": id,
        "name": name,
        "path": path,
        "available": False,
        "default_engine": None,
        "queue_pending": 0,
    }
    try:
        manifest = load_manifest(operator_layer(root))
    except Exception:  # noqa: BLE001 — a broken project stays in the list, unavailable
        return summary
    summary["available"] = True
    summary["default_engine"] = manifest.default_engine
    queue_dir = root / manifest.queue_dir
    if queue_dir.is_dir():
        summary["queue_pending"] = len(list(queue_dir.glob("*.yaml")))
    return summary


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def read_manifest(root: Path) -> dict:
    """Return {raw, parsed} for the project's manifest."""
    path = operator_layer(root) / "manifest.yaml"
    raw = path.read_text()
    parsed = load_manifest(operator_layer(root)).model_dump(mode="json")
    return {"raw": raw, "parsed": parsed}


def write_manifest(root: Path, raw: str) -> dict:
    """Validate a manifest payload (parse + lint), then persist it.

    Raises ApiError(422) when the manifest does not parse or introduces a
    Policy Gate error, carrying the violations in the response detail. The file
    is written only after both checks pass.

    The parse+lint gate is the shared `manifestedit.validate_manifest_text` so
    the UI and the CLI (`alc onboard`) enforce one identical contract; this
    function only maps its blocking violations onto the HTTP error shape.
    """
    ol = operator_layer(root)
    errors = validate_manifest_text(raw, ol)
    if errors:
        # Preserve the two distinct 422s the endpoint has always returned: a
        # candidate that does not PARSE reports its loader error with no detail;
        # a candidate that parses but fails a Policy Gate rule carries the
        # violations back as `detail`.
        parse_error = next((v for v in errors if v.rule == "manifest-parse"), None)
        if parse_error is not None:
            raise ApiError(parse_error.message, status=422)
        raise ApiError(
            "manifest introduces Policy Gate errors",
            status=422,
            detail=[{"rule": v.rule, "severity": v.severity, "message": v.message} for v in errors],
        )

    (ol / "manifest.yaml").write_text(raw)
    return read_manifest(root)


# ---------------------------------------------------------------------------
# Lint / engines / scorecard
# ---------------------------------------------------------------------------


def lint_project(root: Path) -> dict:
    """Return {violations} for the project, matching `alc lint --json`."""
    ol = operator_layer(root)
    manifest = load_manifest(ol)
    blueprints = load_all_blueprints(manifest, ol)
    violations = _lint(manifest, blueprints)
    violations += validate_prompts(manifest, ol, blueprints)
    violations += validate_provisions(manifest, root)
    violations += lint_stage(manifest, blueprints)
    violations += lint_loops(manifest, load_all_loops(manifest, ol))
    return {
        "violations": [
            {"rule": v.rule, "severity": v.severity, "message": v.message}
            for v in violations
        ]
    }


def engines_info(root: Path) -> list[dict]:
    """Return one entry per engine: type, tier→model map, default flag, health."""
    manifest = load_manifest(operator_layer(root))

    tiers_by_engine: dict[str, dict[str, str]] = {}
    for tier, mapping in manifest.compute_tiers.items():
        for engine_name, model in mapping.items():
            tiers_by_engine.setdefault(engine_name, {})[tier] = model

    result = []
    for name, conf in manifest.engines.items():
        try:
            healthy = resolve_engine(name, manifest.engines).health_check()
        except Exception:  # noqa: BLE001 — unknown type / failed probe -> unhealthy
            healthy = False
        result.append(
            {
                "name": name,
                "type": conf.get("type"),
                "default": name == manifest.default_engine,
                "tiers": tiers_by_engine.get(name, {}),
                "healthy": healthy,
            }
        )
    return result


def scorecard(root: Path) -> dict:
    """Aggregate the scorecards of every archived queue report (done/).

    ``net_lines_total`` sums ``diffstat.adds - diffstat.dels`` over every stage
    (of every archived FlowReport) that carries a diffstat — mirroring
    ``stagepolicy.mix_health``'s ``ArchetypeSpend.net_lines`` accumulation.
    ``None`` when NO stage anywhere carried a diffstat (nothing computable),
    distinct from ``0`` (diffstats were computed and net out to zero) so the
    frontend can tell "no data" from "zero net change".

    ``runs_with_warnings`` counts archived reports where at least one stage
    carries a non-empty ``warnings`` list (a FlowReport has no ``warnings``
    field of its own — only its stages, each a RunReport, do).
    """
    done_dir = _queue_dir(root) / "done"
    totals = {
        "reports": 0,
        "successes": 0,
        "failures": 0,
        "span_total": 0,
        "passes_total": 0,
        "streak_total": 0,
        "touch_total": 0,
        "net_lines_total": None,
        "runs_with_warnings": 0,
    }
    # Both sources: the queue's done/ AND runs/ (where a direct `alc run` archives its
    # report) — so the Dashboard Scorecard counts interactive runs like audit/Mix Health.
    report_files = sorted(
        f
        for d in (done_dir, _runs_dir(root))
        if d.is_dir()
        for f in d.glob("*.report.json")
    )
    for report_file in report_files:
        try:
            report = FlowReport.model_validate_json(report_file.read_text())
        except (ValidationError, OSError):
            continue
        totals["reports"] += 1
        totals["successes" if report.success else "failures"] += 1
        totals["span_total"] += report.scorecard.span
        totals["passes_total"] += report.scorecard.passes
        totals["streak_total"] += report.scorecard.streak
        totals["touch_total"] += report.scorecard.touch
        for stage in report.stages:
            if stage.diffstat is not None:
                net = stage.diffstat.adds - stage.diffstat.dels
                totals["net_lines_total"] = (totals["net_lines_total"] or 0) + net
        if any(stage.warnings for stage in report.stages):
            totals["runs_with_warnings"] += 1
    return totals


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


def _queue_dir(root: Path) -> Path:
    manifest = load_manifest(operator_layer(root))
    return root / manifest.queue_dir


def _runs_dir(root: Path) -> Path:
    """The run-log dir where a direct `alc run` archives its `*.report.json` — the
    second source (besides queue `done/`) that audit + mix_health aggregate."""
    manifest = load_manifest(operator_layer(root))
    return root / manifest.runs_dir


def read_queue(root: Path) -> dict:
    """Return {pending, done}: pending tasks and archived tasks + their reports."""
    queue_dir = _queue_dir(root)
    pending: list[dict] = []
    done: list[dict] = []
    if not queue_dir.is_dir():
        return {"pending": pending, "done": done}

    for path in sorted(queue_dir.glob("*.yaml")):
        try:
            qt = QueueTask.model_validate(yaml.safe_load(path.read_text()))
        except (ValidationError, yaml.YAMLError):
            continue
        pending.append(
            {"stem": path.stem, "mtime": path.stat().st_mtime, "task": qt.model_dump(mode="json")}
        )
    # Mirror the drain's real dispatch order within a wave (queue.py's
    # `_topological_waves`): (-priority, filename), higher priority first.
    # Every task at the default priority 0 sorts by stem alone -> byte-identical
    # to the glob order above.
    pending.sort(key=lambda p: (-p["task"]["priority"], p["stem"]))

    done_dir = queue_dir / "done"
    if done_dir.is_dir():
        # A done task is RETRYABLE only when it is an OUTSTANDING failure: the latest
        # failed attempt of a lineage that no later retry has resolved. A failure
        # whose lineage was later fixed (success elsewhere) is NOT retryable — so the
        # UI must not offer a retry there, matching what `retry all` actually does.
        outstanding_stems = {f.stem for f in outstanding_failures(done_dir)}
        for report_file in sorted(done_dir.glob("*.report.json")):
            stem = report_file.name[: -len(".report.json")]
            task_file = done_dir / f"{stem}.yaml"
            task = None
            if task_file.exists():
                try:
                    task = QueueTask.model_validate(
                        yaml.safe_load(task_file.read_text())
                    ).model_dump(mode="json")
                except (ValidationError, yaml.YAMLError):
                    task = None
            try:
                report = json.loads(report_file.read_text())
            except (json.JSONDecodeError, OSError):
                report = None
            done.append(
                {
                    "stem": stem,
                    "mtime": report_file.stat().st_mtime,
                    "task": task,
                    "report": report,
                    "outstanding": stem in outstanding_stems,
                }
            )
    return {"pending": pending, "done": done}


def enqueue(root: Path, data: dict) -> str:
    """Validate a QueueTask payload and write it as a pending task; return its stem."""
    try:
        qt = QueueTask.model_validate(data)
    except ValidationError as exc:
        raise ApiError(f"invalid queue task: {exc}", status=422) from exc

    queue_dir = _queue_dir(root)
    queue_dir.mkdir(parents=True, exist_ok=True)
    first_line = qt.task.splitlines()[0] if qt.task else ""
    slug = slugify(first_line) or slugify(qt.unit_name()) or "task"
    stem = f"{slug}-{uuid.uuid4().hex[:8]}"
    (queue_dir / f"{stem}.yaml").write_text(yaml.safe_dump(qt.model_dump(), sort_keys=True))
    return stem


def enqueue_batch(root: Path, items: list[dict]) -> list[str]:
    """Validate every item as a QueueTask BEFORE writing any of them; return their stems.

    Mirrors `alc enqueue --from-file`'s own guarantee (cli.py's
    `_enqueue_entries_from_file`/`cmd_enqueue` comment): a typo in one entry
    never leaves a half-written batch behind. Each valid item is then written
    through `enqueue` itself — there is no second write path.
    """
    for data in items:
        try:
            QueueTask.model_validate(data)
        except ValidationError as exc:
            raise ApiError(f"invalid queue task: {exc}", status=422) from exc
    return [enqueue(root, data) for data in items]


def delete_pending(root: Path, stem: str) -> None:
    """Delete a pending task file by stem; raise ApiError(404) when absent."""
    path = _queue_dir(root) / f"{stem}.yaml"
    if not path.is_file():
        raise ApiError(f"no pending task '{stem}'", status=404)
    path.unlink()


def retry_queue(root: Path, stem: str | None = None, all_: bool = False) -> dict:
    """Re-enqueue failed task(s), reusing alc's retry helpers; return {enqueued}.

    ``stem`` retries one archived failure; ``all_`` retries every outstanding
    failure. Mirrors ``alc retry`` without its CLI printing.
    """
    manifest = load_manifest(operator_layer(root))
    queue_dir = root / manifest.queue_dir
    done_dir = queue_dir / "done"

    if stem:
        for suffix in (".report.json", ".yaml"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        targets = [stem]
    elif all_:
        targets = [f.stem for f in outstanding_failures(done_dir)]
    else:
        raise ApiError("provide 'stem' or set 'all'", status=400)

    enqueued: list[str] = []
    for target in targets:
        task_file = done_dir / f"{target}.yaml"
        report_file = done_dir / f"{target}.report.json"
        if not task_file.exists() or not report_file.exists():
            raise ApiError(f"no archived task + report for '{target}'", status=404)
        qt = QueueTask.model_validate(yaml.safe_load(task_file.read_text()))
        report = FlowReport.model_validate_json(report_file.read_text())
        if report.success:
            raise ApiError(f"task '{target}' succeeded; nothing to retry", status=409)
        retry_qt = build_retry_task(qt, failure_feedback(report))
        path = write_retry_task(retry_qt, queue_dir, target)
        enqueued.append(path.stem)
    return {"enqueued": enqueued}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def _runs_dir(root: Path) -> Path:
    manifest = load_manifest(operator_layer(root))
    return root / manifest.runs_dir


def _stale_after_seconds(root: Path) -> float:
    """Idle seconds after which an unfinished run is presumed dead (interrupted)."""
    try:
        return load_manifest(operator_layer(root)).default_timeout_s + runs_core.STALE_MARGIN_S
    except (OSError, ValidationError, ValueError):
        return 1800 + runs_core.STALE_MARGIN_S


def list_runs(root: Path, limit: int = 50, offset: int = 0) -> dict:
    """List run logs (newest first) with simple pagination."""
    return runs_core.list_runs(
        _runs_dir(root), _stale_after_seconds(root), limit=limit, offset=offset
    )


def read_run(root: Path, stem: str, offset: int = 0) -> dict:
    """Return parsed events for one run from line ``offset`` (for incremental tail).

    ``next_offset`` is the total line count, to be passed back as ``offset`` on
    the next poll so only new lines are returned.
    """
    try:
        return runs_core.read_run(
            _runs_dir(root), stem, _stale_after_seconds(root), offset=offset
        )
    except FileNotFoundError as exc:
        raise ApiError(f"no run '{stem}'", status=404) from exc


# ---------------------------------------------------------------------------
# Checks (`alc checks history` / `alc checks audit`) — two read-only Maintainer
# reads over checks.py; neither ever writes.
# ---------------------------------------------------------------------------


def checks_history(root: Path) -> list[dict]:
    """Return per-check pass-rate/mean-duration/flake-score (mirrors `alc checks history`).

    An absent or empty runs_dir yields an empty list, never an error — the
    same contract `check_history` itself already guarantees.
    """
    return [asdict(h) for h in check_history(_runs_dir(root))]


def checks_audit(root: Path) -> dict:
    """Return proposed check-set upgrades + smoke-only Blueprints (mirrors `alc checks audit`).

    Re-detects the project's stack(s) against *root* and diffs them against
    the Manifest's check_sets and each Blueprint's resolved checks — never
    writes (mirrors `cmd_checks`'s `_checks_audit`).
    """
    ol = operator_layer(root)
    manifest = load_manifest(ol)
    blueprints = load_all_blueprints(manifest, ol)
    return asdict(audit_checks(manifest, root, blueprints))


# ---------------------------------------------------------------------------
# Onboard (`alc onboard`) — HARVEST-ONLY: the deterministic proposal and its
# append-only, gate-first apply, reusing the pure onboard core
# (harvest -> build_proposal -> apply). The engine `--assist` path is DELIBERATELY
# not wired here — it spends an engine turn, so it stays a CLI-only choice; the
# UI empty-state points the operator at `alc onboard --assist` instead.
# ---------------------------------------------------------------------------


def _build_onboard_proposal(root: Path, stage: str | None) -> onboard_core.OnboardProposal:
    """Build the harvest-only OnboardProposal for *root* — the SERVER's single
    source of truth for what onboarding would do.

    Loads the manifest + blueprints, computes the hired roster
    (`packs.hired_archetypes`, the same membership test `alc team list` uses),
    runs the deterministic `harvest`, and builds the proposal through the pure
    core with NO ``engine_proposal``. Shared by the proposal read and the apply
    write so the two can never diverge (apply never trusts client-sent checks).
    """
    ol = operator_layer(root)
    manifest = load_manifest(ol)
    blueprints = load_all_blueprints(manifest, ol)
    hired = hired_archetypes(root)
    report = harvest(root)
    return onboard_core.build_proposal(
        manifest, root, blueprints, report, stage=stage, hired_archetypes=hired
    )


def onboard_proposal(root: Path, stage: str | None = None) -> dict:
    """Return the harvest-only `alc onboard` proposal as JSON (mirrors `--json`).

    ``dataclasses.asdict`` of the OnboardProposal — byte-identical to what
    `alc onboard --json` emits — so the UI and the CLI render the exact same
    shape and never drift. Writes nothing.
    """
    return asdict(_build_onboard_proposal(root, stage))


def onboard_apply(root: Path, stage: str | None = None) -> dict:
    """Apply the harvest-only `alc onboard` proposal; return what was written.

    The proposal is rebuilt SERVER-SIDE (never from client-sent check data — the
    server owns what gets written), then handed to `onboard.apply`, the only
    writer in the flow (append-only, validate-before-persist). A blocked apply
    (the shared gate rejected the candidate, so nothing was written) is surfaced
    as ApiError(422) with the violations in ``detail`` — the same Policy-Gate 422
    shape `write_manifest` returns.
    """
    proposal = _build_onboard_proposal(root, stage)
    result = onboard_core.apply(proposal, operator_layer(root))
    if result.violations:
        raise ApiError(
            "onboarding blocked — nothing was written",
            status=422,
            detail=[
                {"rule": v.rule, "severity": v.severity, "message": v.message}
                for v in result.violations
            ],
        )
    return asdict(result)


# ---------------------------------------------------------------------------
# Metrics (the metric-check ledger read back as a time series)
# ---------------------------------------------------------------------------


def metric_series(root: Path, check: str | None = None) -> dict:
    """Return the metric ledger's time series, keyed by check name.

    A missing/empty ledger yields an empty series (``metrics_core.metric_series``
    already treats an absent path that way), never an error.
    """
    manifest = load_manifest(operator_layer(root))
    path = metrics_core.ledger_path(root / manifest.metrics_dir)
    series = metrics_core.metric_series(path, check=check)
    return {name: [asdict(point) for point in points] for name, points in series.items()}


# ---------------------------------------------------------------------------
# Artifacts (e2e evidence a `capture:` command produced)
# ---------------------------------------------------------------------------


def _artifacts_dir(root: Path) -> Path:
    manifest = load_manifest(operator_layer(root))
    return root / manifest.artifacts_dir


def _artifacts_response(result: artifacts_core.RunArtifacts) -> dict:
    return {
        "stem": result.stem,
        "artifacts": [
            {"path": p, "type": artifacts_core.artifact_type(p)} for p in result.artifacts
        ],
    }


def run_artifacts(root: Path, stem: str) -> dict:
    """Return {stem, artifacts: [{path, type}]} for one run's captured evidence.

    Raises ApiError(404) when no such run log exists (mirrors ``read_run``).
    """
    try:
        result = artifacts_core.run_artifacts(_runs_dir(root), stem)
    except FileNotFoundError as exc:
        raise ApiError(f"no run '{stem}'", status=404) from exc
    return _artifacts_response(result)


def latest_artifacts(root: Path) -> dict:
    """Return the most recently modified run with captured evidence.

    ``{"stem": None, "artifacts": []}`` when no run has captured any yet — an
    explicit empty result, never a 404 (mirrors ``cmd_artifacts``' no-stem case).
    """
    result = artifacts_core.latest_run_with_artifacts(_runs_dir(root))
    if result is None:
        return {"stem": None, "artifacts": []}
    return _artifacts_response(result)


def artifact_file_path(root: Path, rel_path: str) -> Path:
    """Resolve *rel_path* to a real file confined inside the project's ``artifacts_dir``.

    *rel_path* is joined against the PROJECT ROOT, not ``artifacts_dir`` — the
    same base ``RunReport.artifacts`` paths are relative to, and so the same
    shape ``run_artifacts``/``latest_artifacts`` echo back (e.g.
    ``.alc/artifacts/<stem>/golden.html``). This keeps the list and bytes
    routes in agreement: the exact ``path`` one returns is what the other
    accepts.

    *rel_path* ultimately came from a model's report, so it is untrusted:
    resolved (symlinks included) and checked to still sit inside
    ``artifacts_dir`` — anything that escapes (a ``..`` component, an absolute
    path, a symlink pointing out, or a project-relative path that simply isn't
    under ``artifacts_dir``, e.g. ``.alc/manifest.yaml``) is ApiError(403). A
    path that resolves inside the directory but names no file is ApiError(404).
    """
    artifacts_root = _artifacts_dir(root).resolve()
    candidate = (root.resolve() / rel_path).resolve()
    if not candidate.is_relative_to(artifacts_root):
        raise ApiError(f"artifact path '{rel_path}' is outside artifacts_dir", status=403)
    if not candidate.is_file():
        raise ApiError(f"no artifact at '{rel_path}'", status=404)
    return candidate


# ---------------------------------------------------------------------------
# Audit (aggregate window over the archived queue reports)
# ---------------------------------------------------------------------------


def audit(root: Path, since: str) -> dict:
    """Return the aggregate window audit for the trailing *since* period.

    *since* is a relative window like "7d"/"24h"/"30m" (``audit.parse_since``);
    raises ApiError(422) with a clear message for anything else — never a
    traceback.
    """
    try:
        seconds = parse_since(since)
    except ValueError as exc:
        raise ApiError(str(exc), status=422) from exc
    done_dir = _queue_dir(root) / "done"
    return asdict(
        audit_window(done_dir, time.time() - seconds, extra_report_dir=_runs_dir(root))
    )


# ---------------------------------------------------------------------------
# Loops (state + ledger)
# ---------------------------------------------------------------------------


def read_loop_state(root: Path, name: str) -> dict:
    """Return the persisted (or fresh pending) state for a loop."""
    ol = operator_layer(root)
    manifest = load_manifest(ol)
    loops = loops_dir(manifest, ol)
    return load_loop_state(state_path(loops, name), name).model_dump(mode="json")


def read_loop_ledger(root: Path, name: str) -> dict:
    """Return the per-cycle ledger for a loop (empty when it has never run)."""
    ol = operator_layer(root)
    manifest = load_manifest(ol)
    loops = loops_dir(manifest, ol)
    path = ledger_path(loops, name)
    records: list[dict] = []
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {"records": records}


# ---------------------------------------------------------------------------
# Worktree status — backs the Loops view's reassuring dirty-tree notice.
# ---------------------------------------------------------------------------


def worktree_status(root: Path) -> dict:
    """Return the enriched RepoStatus (asdict) for the project's working tree.

    An autonomous run (``alc cycle``/``loop``/``tick``) is SAFE on a dirty tree: it
    commits only what IT produces, never the operator's own uncommitted work (the plan
    replenish is path-scoped and a serial committing demand aborts itself via the
    flow-level clean-tree guard). So the UI does not block a dirty tree — it WARNS and
    proceeds. Surfacing ``dirty`` lets the Loops view show a banner that sets
    expectations up front, without ever disabling the run controls.

    The shape is a backward-compatible SUPERSET of the old ``{"dirty": bool}``: the
    ``dirty`` key stays semantically IDENTICAL to ``commit.has_non_alc_changes`` — the
    SAME meaning the CLI preflight and the committing-Flow guard use, pinned by an
    agreement test (tests/ui/test_repostatus.py) so the UI and the CLI can never
    disagree on "dirty". Alongside it, ``repo_status`` adds branch / upstream /
    ahead / behind / untracked for the live StatusBar cluster.

    No-auto-fetch: ``ahead``/``behind`` come ONLY from the local remote-tracking ref
    (as of the operator's last fetch), read out of a single ``git status`` call. This
    endpoint NEVER runs ``git fetch``. An off-git project degrades to
    ``available: False`` (and ``dirty: False``) — no repo means no WIP to protect —
    and this never raises: ``repo_status`` degrades rather than throwing.
    """
    return asdict(repo_status(root))


# ---------------------------------------------------------------------------
# Prompts (reserved / free / ejected)
# ---------------------------------------------------------------------------


def _prompt_file(root: Path, name: str) -> Path:
    manifest = load_manifest(operator_layer(root))
    return root / manifest.prompts_dir / f"{name}.md"


def list_prompts_view(root: Path) -> list[dict]:
    """List reserved and free prompts, marking reserved/ejected status."""
    ol = operator_layer(root)
    manifest = load_manifest(ol)
    entries = list_prompts(ol, manifest)
    return [
        {
            "name": e.name,
            "kind": e.kind,
            "source": e.source,
            "reserved": e.kind == "reserved",
            "ejected": e.kind == "reserved" and e.source == "override",
        }
        for e in entries
    ]


def read_prompt(root: Path, name: str) -> dict:
    """Return {raw, reserved, ejected} for a prompt (reserved defaults resolve)."""
    ol = operator_layer(root)
    manifest = load_manifest(ol)
    try:
        raw = resolve_prompt(name, ol, manifest)
    except KeyError as exc:
        raise ApiError(f"no prompt named '{name}'", status=404) from exc
    reserved = name in _DEFAULT_PROMPTS
    file = _prompt_file(root, name)
    return {"raw": raw, "reserved": reserved, "ejected": reserved and file.exists()}


def write_prompt(root: Path, name: str, raw: str, create: bool) -> dict:
    """Persist a prompt override/free file; validate reserved overrides.

    ``create`` True (POST) refuses a reserved name (409) and refuses to
    overwrite an existing file (409). ``create`` False (PUT) creates or updates.
    """
    reserved = name in _DEFAULT_PROMPTS
    file = _prompt_file(root, name)

    if create:
        if reserved:
            raise ApiError(
                f"'{name}' is a reserved prompt; PUT it to override the default", status=409
            )
        if file.exists():
            raise ApiError(f"prompt '{name}' already exists", status=409)
        if not raw.strip():
            raw = f"# {name}\n\nReusable prompt fragment for this project.\n"

    if reserved:
        missing = validate_prompt_override(name, raw)
        if missing:
            raise ApiError(
                f"reserved prompt '{name}' is missing placeholders: {missing}", status=422
            )
        fmt_error = override_format_error(name, raw)
        if fmt_error:
            raise ApiError(f"reserved prompt '{name}' cannot render: {fmt_error}", status=422)

    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(raw)
    return read_prompt(root, name)


def delete_prompt(root: Path, name: str) -> None:
    """Delete a prompt file. A reserved, non-ejected prompt cannot be deleted (409)."""
    reserved = name in _DEFAULT_PROMPTS
    file = _prompt_file(root, name)
    if reserved and not file.exists():
        raise ApiError(
            f"'{name}' is a reserved prompt with no override to delete", status=409
        )
    if not file.exists():
        raise ApiError(f"no prompt named '{name}'", status=404)
    file.unlink()


# ---------------------------------------------------------------------------
# Team (Archetype Packs: roster, hire, Mix Health) — mirrors cli.py's
# `_team_roster` / `_team_hire`, which stay the reference behavior.
# ---------------------------------------------------------------------------


def team_roster(root: Path) -> dict:
    """Return {members, mix_health}: the hired roster and the stage's Mix Health.

    A member is an archetype whose pack files (`packs.pack_files`) are present
    on disk — the same test `_team_roster` uses, so the UI roster and
    `alc team list` never disagree. Each member carries its present files and
    the state of any loops its pack brought (`load_loop_state`).

    `mix_health` is `stagepolicy.mix_health`'s report, serialised as-is: with no
    `stage` declared its `core`/`secondary` stay empty (breakdown, never
    judged); `total_runs == 0` is the "no data yet" signal — never a misleading
    all-zero table.
    """
    ol = operator_layer(root)
    manifest = load_manifest(ol)
    stacks = detect_stacks(root)
    loops_directory = loops_dir(manifest, ol)
    loops_prefix = f"{manifest.loops_dir}/"

    members = []
    for archetype in sorted(PACKS):
        files = pack_files(archetype, stacks)
        present = sorted(rel for rel in files if (root / rel).exists())
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
        members.append({"archetype": archetype, "files": present, "loops": member_loops})

    done_dir = root / manifest.queue_dir / "done"
    # Same roster mapping the CLI passes (hired archetype -> its loop names), so
    # `/team` and `alc team status` derive the SAME idle-core hints from one
    # computation. asdict serialises the nested idle_core for free.
    member_roster = {
        m["archetype"]: [lp["name"] for lp in m["loops"]] for m in members
    }
    health = mix_health(
        done_dir,
        manifest,
        roster=member_roster,
        extra_report_dir=root / manifest.runs_dir,
        since_epoch=time.time() - MIX_HEALTH_WINDOW_S,
    )
    return {"members": members, "mix_health": asdict(health)}


def team_hire(root: Path, archetype: str, force: bool = False) -> dict:
    """Write *archetype*'s MISSING pack files (additive), then lint; return
    {written, kept, lint}.

    Mirrors `_team_hire`'s additive contract: writes only the pack files not yet
    on disk (`written`) and keeps the ones already present (`kept`), so a
    partially-present or drifted archetype receives the newer files ALC ships and
    a re-hire is a no-op — never a whole-pack refusal (the old 409 is gone;
    additive hire never conflicts). `force` overwrites ALL of a pack's files (the
    one destructive path), returning them all under `written` with an empty
    `kept`. An unknown archetype is ApiError(404), naming the valid ones
    (`PACKS`'s keys).
    """
    if archetype not in PACKS:
        available = ", ".join(sorted(PACKS)) or "none yet"
        raise ApiError(f"no pack named '{archetype}' yet (available: {available})", status=404)

    if force:
        files = pack_files(archetype, detect_stacks(root))
        written = sorted(files)
        kept: list[str] = []
        contents = files
    else:
        missing, present = split_pack_files(archetype, detect_stacks(root), root)
        written = sorted(missing)
        kept = sorted(present)
        contents = missing

    for rel_path in written:
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents[rel_path])

    return {"written": written, "kept": kept, "lint": lint_project(root)}


def team_retire(root: Path, member: str) -> dict:
    """Archive *member*'s loop file(s) into `retired/`, never delete; return {moved}.

    Mirrors `_team_retire`'s contract exactly: only the member's LOOP files
    (`pack_files`'s entries under `manifest.loops_dir/*.yaml`) move — its
    blueprints, flows, and specialists are left untouched. A member with no
    loop(s) on disk is a no-op (`{"moved": []}`), never an error, mirroring
    `_team_retire`'s "has no loop(s) on disk to retire" case. An unknown
    archetype is ApiError(404), naming the valid ones (`PACKS`'s keys).
    """
    if member not in PACKS:
        available = ", ".join(sorted(PACKS)) or "none yet"
        raise ApiError(f"no pack named '{member}' yet (available: {available})", status=404)

    ol = operator_layer(root)
    manifest = load_manifest(ol)
    loops_prefix = f"{manifest.loops_dir}/"

    files = pack_files(member, detect_stacks(root))
    loop_files = sorted(
        rel for rel in files if rel.startswith(loops_prefix) and rel.endswith(".yaml")
    )

    retired_dir = loops_dir(manifest, ol) / "retired"
    moved: list[str] = []
    for rel_path in loop_files:
        src = root / rel_path
        if not src.exists():
            continue
        retired_dir.mkdir(parents=True, exist_ok=True)
        dest = retired_dir / src.name
        src.rename(dest)
        moved.append(str(dest.relative_to(root)))

    return {"moved": moved}


# ---------------------------------------------------------------------------
# Branches (`alc land` / `alc discard` — thin over branches.py / merge.py)
# ---------------------------------------------------------------------------


def list_branches(root: Path) -> dict:
    """Return {available, branches}: the project's `alc/*` branches.

    Outside a git repository (or with no `git` binary) this is a clear
    ``{"available": False, "branches": []}`` — never a 500 — mirroring
    ``branches.list_alc_branches``'s own no-git degrade.
    """
    if not is_git_repo(root):
        return {"available": False, "branches": []}
    repo_root = git_toplevel(root)
    return {
        "available": True,
        "branches": [asdict(b) for b in list_alc_branches(repo_root)],
    }


def _resolve_land_delivery(
    root: Path, mode: str | None, remote: str | None, base: str | None
) -> DeliverySpec:
    """Resolve the effective DeliverySpec for a UI land request.

    Mirrors `cli._resolve_delivery`'s override relationship: the manifest's
    own `delivery` block is the default, and the request body's `mode` (else
    `remote`/`base`, when given) overrides it for this call only. An
    unreadable/missing manifest just falls back to `DeliverySpec()`'s own
    default (mode: local) — same never-raise contract as the CLI resolver.
    """
    try:
        delivery = load_manifest(operator_layer(root)).delivery or DeliverySpec()
    except Exception:  # noqa: BLE001 — mirrors cli._resolve_delivery
        delivery = DeliverySpec()

    updates = {
        k: v
        for k, v in {"mode": mode, "remote": remote, "base": base}.items()
        if v is not None
    }
    return delivery.model_copy(update=updates) if updates else delivery


def _land_delivery_warning(
    repo_root: Path, delivery: DeliverySpec, report: MergeReport
) -> str | None:
    """The remote last mile after a UI land (mirrors `cli._deliver`): push the
    current branch, and for `mode: "pr"` also open a PR via `gh`.

    Returns the failure reason as a warning string, or None once every
    attempted step succeeded. NEVER raises: a push failure or a missing `gh`
    is reported back, not thrown — the local merge this runs after already
    succeeded, exactly like `alc land --push`/`--pr`.
    """
    branch = current_branch(repo_root)
    if branch is None:
        return "could not resolve the current branch; skipping delivery."

    ok, message = push_branch(repo_root, delivery.remote, branch)
    if not ok:
        return message
    if delivery.mode != "pr":
        return None

    files = changed_files(repo_root, delivery.base, branch)
    body = build_pr_body(report, files)
    ok, message = open_pr(repo_root, delivery.base, branch, f"alc land: {branch}", body)
    return None if ok else message


def land_branches(
    root: Path,
    branches: list[str] | None,
    mode: str | None = None,
    remote: str | None = None,
    base: str | None = None,
) -> dict:
    """Integrate *branches* (every unmerged `alc/*` branch when omitted); return the MergeReport.

    Mirrors `alc land --all`'s branch selection when no explicit list is given.

    ``mode``/``remote``/``base`` are the UI's equivalent of `alc land`'s
    ``--push``/``--pr`` flags (roadmap-phase-4.md T8's DeliverySpec, wrapped
    for the UI, ui-phase-5.md T3): omitted, they fall back to the manifest's
    own `delivery` block, then to ``local`` — the response then stays byte-
    identical to before this existed (no ``warning`` key at all). For
    ``push``/``pr``, a delivery failure is carried back as ``warning`` in the
    response, NEVER a 500 — the local merge above already succeeded.
    """
    if not is_git_repo(root):
        raise ApiError("not inside a git repository", status=409)
    repo_root = git_toplevel(root)
    targets = (
        branches
        if branches is not None
        else [b.name for b in list_alc_branches(repo_root) if not b.merged]
    )
    report = auto_merge_branches(repo_root, targets)
    result: dict = {"merged": report.merged, "conflicted": report.conflicted}

    delivery = _resolve_land_delivery(root, mode, remote, base)
    if delivery.mode != "local":
        result["warning"] = _land_delivery_warning(repo_root, delivery, report)
    return result


def discard_branches(
    root: Path,
    branches: list[str],
    worktrees: bool = False,
    older_than_days: int | None = None,
) -> dict:
    """Delete *branches*, optionally prune stale worktrees and old bundle files.

    Mirrors `alc discard <branches> [--worktrees] [--bundles --older-than N]`
    minus its interactive confirmation — a frontend concern (Wave 2), never a
    backend gate. `delete_branches` already refuses a non-`alc/` ref and the
    current branch; relied on here, not reimplemented.
    """
    result: dict = {"deleted": [], "pruned_worktrees": 0, "deleted_bundles": []}

    if branches or worktrees:
        if not is_git_repo(root):
            raise ApiError("not inside a git repository", status=409)
        repo_root = git_toplevel(root)
        if branches:
            result["deleted"] = delete_branches(
                repo_root, branches, runs_dir=_runs_dir(root)
            )
        if worktrees:
            result["pruned_worktrees"] = prune_worktrees(repo_root)

    if older_than_days is not None:
        manifest = load_manifest(operator_layer(root))
        bundles_dir = root / manifest.bundles_dir
        if bundles_dir.is_dir():
            cutoff = time.time() - older_than_days * 86400
            targets = [p for p in bundles_dir.glob("*.jsonl") if p.stat().st_mtime < cutoff]
            for p in targets:
                p.unlink()
            result["deleted_bundles"] = [p.name for p in targets]

    return result


# ---------------------------------------------------------------------------
# Variants (`alc explore` / `alc compare` / `alc adopt`)
# ---------------------------------------------------------------------------

_VARIANT_BRANCH_RE = re.compile(r"^alc/variant-\d+-[0-9a-f]{8}$")


def list_variants(root: Path) -> list[dict]:
    """Return every archived explore variant as a comparable row (mirrors bare `alc compare`).

    Delegates to the ONE shared enumeration ``variants.list_all_variants`` so the
    UI Compare view and bare ``alc compare`` can never show a different set (or
    order). This function only resolves the manifest's ``variants_dir``; the seam
    (dir-missing → [], unreadable archives skipped, sorted by stem) lives there.

    Each row is then marked with ``live`` (``variants.mark_live``): the Compare view
    must not offer Diff/Adopt on a branch-gone (resolved) variant — both would 404.
    ONE git listing per GET, mirroring bare ``alc compare`` so the CLI and the UI can
    never drift (pinned by the parity test). Off git → every row resolved.
    """
    manifest = load_manifest(operator_layer(root))
    rows = list_all_variants(root / manifest.variants_dir)
    repo_root = git_toplevel(root) if is_git_repo(root) else None
    return mark_live(rows, repo_root)


def adopt_variant(root: Path, branch: str) -> dict:
    """Integrate *branch* and discard its unmerged `alc/variant-*` siblings (mirrors `alc adopt`).

    Destructive by design — the frontend owns confirmation (Wave 2), never a
    backend gate.
    """
    if not branch.startswith("alc/"):
        raise ApiError(f"not an alc/ branch: {branch}", status=422)
    if not is_git_repo(root):
        raise ApiError("not inside a git repository", status=409)
    repo_root = git_toplevel(root)

    losers = [
        b.name
        for b in list_alc_branches(repo_root)
        if not b.merged and b.name != branch and _VARIANT_BRANCH_RE.match(b.name)
    ]
    merge_report = auto_merge_branches(repo_root, [branch])
    discarded = (
        delete_branches(repo_root, losers, runs_dir=_runs_dir(root)) if losers else []
    )
    return {
        "merged": merge_report.merged,
        "conflicted": merge_report.conflicted,
        "discarded": discarded,
    }


def variant_diff(root: Path, branch: str) -> dict:
    """Return *branch*'s unified diff vs the current branch (mirrors `alc compare --diff`).

    The Compare view's summary metrics (checks, scorecard, cost, diffstat) can be
    identical across variants; this exposes the ONE thing that always differs —
    the actual change — so metric-tied variants can be told apart. Read-only: it
    only runs ``git diff`` (via ``branches.branch_diff``), never a mutation.
    """
    if not branch.startswith("alc/"):
        raise ApiError(f"not an alc/ branch: {branch}", status=422)
    if not is_git_repo(root):
        raise ApiError("not inside a git repository", status=409)
    repo_root = git_toplevel(root)

    bd = branch_diff(repo_root, branch)
    if bd is None:
        # None means the ref is gone (already adopted or discarded), not an empty
        # diff — so this is a 404 (nothing to show), distinct from a 409 non-repo.
        raise ApiError(
            f"no diff available for {branch} (unknown branch — already adopted or discarded?)",
            status=404,
        )
    # The base the three-dot diff was taken against (what the operator sees on
    # disk); `current_branch` is the same helper `delivery` uses, "HEAD" if unknown.
    base = current_branch(repo_root) or "HEAD"
    return {"branch": branch, "base": base, "diff": bd.text, "truncated": bd.truncated}


# ---------------------------------------------------------------------------
# Signals (`alc signal ingest` / `alc signal list`)
# ---------------------------------------------------------------------------


def _signals_dir(root: Path) -> Path:
    manifest = load_manifest(operator_layer(root))
    return root / manifest.signals_dir


def list_signals(root: Path) -> list[dict]:
    """Return every pending (not yet archived) signal (mirrors `alc signal list`)."""
    pending = signals_core.read_signals(_signals_dir(root))
    return [{"path": str(p.path), **p.signal.model_dump()} for p in pending]


def ingest_signal(root: Path, data: dict) -> dict:
    """Validate *data* as a Signal and ingest it; return {path}.

    ``Signal.ts`` defaults to now when *data* omits it — the model's own
    default, not duplicated here (mirrors `alc signal ingest`/the `/signal`
    webhook route, both of which validate straight through the same model).
    """
    try:
        signal = Signal.model_validate(data)
    except ValidationError as exc:
        raise ApiError(f"invalid signal: {exc}", status=422) from exc
    path = signals_core.ingest(_signals_dir(root), signal)
    return {"path": str(path)}


# ---------------------------------------------------------------------------
# Schedule (`alc schedule list`) — read-only; install/remove stay CLI-only
# ---------------------------------------------------------------------------


def schedule_status() -> dict:
    """Return the host crontab's ALC-scheduled entries (mirrors `alc schedule list`).

    Project-independent — the crontab lives on the host, not inside a project
    (ui-phase-5.md T12). Never writes: only `has_crontab`/`read_crontab` are
    called. No `crontab` binary on this host degrades to
    ``{"available": False, "entries": []}``, the same explicit-empty contract
    `_schedule_list` itself already prints as "No `crontab` on this platform.".
    """
    if not has_crontab():
        return {"available": False, "entries": []}
    return {"available": True, "entries": list_entries(read_crontab())}
