# service.py — Read/write helpers that back the per-project API.
#
# Every parse/validation delegates to the alc control plane (intake loaders,
# policy lint, queue retry helpers, engine registry) — the UI never
# reimplements alc logic. Functions here take a project root and return
# JSON-safe dicts for the route handlers.
from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import yaml
from pydantic import ValidationError

from alc.engines.registry import resolve_engine
from alc.intake import load_all_blueprints, load_manifest
from alc.loop import ledger_path, load_loop_state, loops_dir, state_path
from alc.models import FlowReport, QueueTask
from alc.policy import lint as _lint
from alc.policy import validate_provisions, validate_prompts
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
from alc.textutil import slugify
from alc.ui.errors import ApiError

# A run finishes at the terminal event for its KIND (mirrors the detail view's
# buildTimeline): a flow at ``flow_finished``, a task at ``task_finished``. A
# flow/task run's inner ``mandate_finished`` lines are NOT terminal — the run
# is still live until its wrapper closes; only a bare mandate run (no flow/task
# wrapper) finishes at its own ``mandate_finished``.
_WRAPPER_STARTS = {"flow_started", "task_started"}
_WRAPPER_TERMINALS = {"flow_finished", "task_finished"}


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
    """
    ol = operator_layer(root)
    # 1. Parse the candidate manifest in isolation.
    with tempfile.TemporaryDirectory() as td:
        tmp_ol = Path(td) / ".alc"
        tmp_ol.mkdir()
        (tmp_ol / "manifest.yaml").write_text(raw)
        try:
            manifest = load_manifest(tmp_ol)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(f"invalid manifest: {exc}", status=422) from exc

    # 2. Lint the candidate manifest against the project's real blueprints.
    try:
        blueprints = load_all_blueprints(manifest, ol)
    except Exception:  # noqa: BLE001 — a broken blueprint must not mask manifest lint
        blueprints = []
    violations = _lint(manifest, blueprints)
    errors = [v for v in violations if v.severity == "error"]
    if errors:
        raise ApiError(
            "manifest introduces Policy Gate errors",
            status=422,
            detail=[{"rule": v.rule, "severity": v.severity, "message": v.message} for v in errors],
        )

    # 3. Persist.
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
    """Aggregate the scorecards of every archived queue report (done/)."""
    done_dir = _queue_dir(root) / "done"
    totals = {
        "reports": 0,
        "successes": 0,
        "failures": 0,
        "span_total": 0,
        "passes_total": 0,
        "streak_total": 0,
        "touch_total": 0,
    }
    if not done_dir.is_dir():
        return totals

    for report_file in sorted(done_dir.glob("*.report.json")):
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
    return totals


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


def _queue_dir(root: Path) -> Path:
    manifest = load_manifest(operator_layer(root))
    return root / manifest.queue_dir


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

    done_dir = queue_dir / "done"
    if done_dir.is_dir():
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


def _run_kind(stem: str) -> str:
    """Extract the run kind from a run-log stem (``<ts>-<kind>-<slug>-<hex>``)."""
    parts = stem.split("-")
    return parts[1] if len(parts) > 1 else ""


def _run_finished(path: Path) -> bool:
    """Return True when the run reached the terminal event for its kind.

    Mirrors the detail view (buildTimeline) so the runs list and the run detail
    never disagree: a flow/task run's inner ``mandate_finished`` is not terminal
    — only ``flow_finished`` / ``task_finished`` closes it; a bare mandate run
    (no flow/task wrapper) closes at its ``mandate_finished``.
    """
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    except OSError:
        return False
    events: set[str] = set()
    for ln in lines:
        try:
            event = json.loads(ln).get("event")
        except json.JSONDecodeError:
            continue
        if isinstance(event, str):
            events.add(event)
    if events & _WRAPPER_TERMINALS:
        return True
    return not (events & _WRAPPER_STARTS) and "mandate_finished" in events


def list_runs(root: Path, limit: int = 50, offset: int = 0) -> dict:
    """List run logs (newest first) with simple pagination."""
    runs_dir = _runs_dir(root)
    if not runs_dir.is_dir():
        return {"runs": [], "total": 0}

    files = sorted(
        runs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    total = len(files)
    page = files[offset : offset + limit]
    runs = []
    for path in page:
        st = path.stat()
        runs.append(
            {
                "stem": path.stem,
                "kind": _run_kind(path.stem),
                "mtime": st.st_mtime,
                "size": st.st_size,
                "finished": _run_finished(path),
            }
        )
    return {"runs": runs, "total": total}


def read_run(root: Path, stem: str, offset: int = 0) -> dict:
    """Return parsed events for one run from line ``offset`` (for incremental tail).

    ``next_offset`` is the total line count, to be passed back as ``offset`` on
    the next poll so only new lines are returned.
    """
    path = _runs_dir(root) / f"{stem}.jsonl"
    if not path.is_file():
        raise ApiError(f"no run '{stem}'", status=404)
    lines = path.read_text().splitlines()
    events = []
    for line in lines[offset:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"events": events, "next_offset": len(lines)}


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
