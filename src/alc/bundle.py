# bundle.py — Context Budget Offload: append-only bundle record and replay summary.
# write_bundle records what a run produced to a JSONL file so the result can be
# replayed cheaply into a future run's directive via summarize_bundle.
# See docs/concepts.md — "Context Budget / Offload".
from __future__ import annotations

import json
import uuid
from pathlib import Path

from alc.models import FlowReport, RunReport

# Maximum characters of output_text included in the replay summary.
_MAX_OUTPUT_CHARS = 1500


def write_bundle(bundles_dir: Path, label: str, task: str, report: RunReport | FlowReport) -> Path:
    """Record the result of a run or flow to an append-only JSONL bundle file.

    Creates bundles_dir (with parents) if it does not exist. Each call writes a
    new file named <uuid4 hex8>.jsonl. The file is append-only JSONL:

    - Line 1: header event with label, task, and success.
    - For RunReport: one attempt event per AttemptRecord, then a result event.
    - For FlowReport: one stage event per stage RunReport, then a result event.

    Args:
        bundles_dir: Directory where bundle files are written.
        label: Human-readable label (blueprint name or flow name).
        task: The task string from the original run.
        report: A RunReport or FlowReport produced by a run.

    Returns:
        Path to the written bundle file.
    """
    bundles_dir.mkdir(parents=True, exist_ok=True)

    file_path = bundles_dir / f"{uuid.uuid4().hex[:8]}.jsonl"

    lines: list[str] = []

    # Header event — common to both report types.
    lines.append(json.dumps({
        "event": "header",
        "label": label,
        "task": task,
        "success": report.success,
    }))

    if isinstance(report, RunReport):
        # One attempt event per AttemptRecord.
        for attempt in report.attempts:
            lines.append(json.dumps({
                "event": "attempt",
                "index": attempt.index,
                "engine_ok": attempt.engine_ok,
                "failed_checks": attempt.failed_checks,
            }))
        # Result event with the final output.
        lines.append(json.dumps({
            "event": "result",
            "output_text": report.output_text,
        }))

    elif isinstance(report, FlowReport):
        # One stage event per stage RunReport.
        for stage in report.stages:
            lines.append(json.dumps({
                "event": "stage",
                "blueprint": stage.blueprint,
                "success": stage.success,
                "output_text": stage.output_text,
            }))
        # Result event: use last stage's output_text or empty string.
        last_output = report.stages[-1].output_text if report.stages else ""
        lines.append(json.dumps({
            "event": "result",
            "output_text": last_output,
        }))

    file_path.write_text("\n".join(lines) + "\n")
    return file_path


def summarize_bundle(path: Path, max_output_chars: int = _MAX_OUTPUT_CHARS) -> str:
    """Produce a compact plain-text replay summary from a bundle JSONL file.

    The summary is intended to be prepended to a new run's directive as a
    Context Budget Offload: prior context, not a full transcript.

    Args:
        path: Path to the bundle JSONL file produced by write_bundle.
        max_output_chars: Cap on the final output_text kept in the summary.
            Defaults to the former hardcoded value so an unset manifest is identical.

    Returns:
        A concise multi-line string describing the prior run's label, task,
        success state, attempt/stage count, and truncated final output.

    Raises:
        FileNotFoundError: If the bundle file does not exist.
        ValueError: If the file is not a valid bundle (malformed JSON).
    """
    if not path.exists():
        raise FileNotFoundError(f"Bundle file not found: {path}")

    events: list[dict] = []
    for raw_line in path.read_text().splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            events.append(json.loads(raw_line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Not a valid bundle (malformed JSON in {path}): {exc}") from exc

    header = next((e for e in events if e.get("event") == "header"), {})
    label = header.get("label", "unknown")
    task = header.get("task", "")
    success = header.get("success", False)

    attempts = [e for e in events if e.get("event") == "attempt"]
    stages = [e for e in events if e.get("event") == "stage"]
    result = next((e for e in events if e.get("event") == "result"), {})
    output_text = result.get("output_text", "")

    # Truncate output to keep the replay summary compact.
    truncated = output_text[:max_output_chars]
    if len(output_text) > max_output_chars:
        truncated += "… [truncated]"

    lines = [
        f"Label:   {label}",
        f"Task:    {task}",
        f"Success: {success}",
    ]
    if attempts:
        lines.append(f"Attempts: {len(attempts)}")
    if stages:
        lines.append(f"Stages: {len(stages)}")
    if truncated:
        lines.append(f"\nFinal output:\n{truncated}")

    return "\n".join(lines)
