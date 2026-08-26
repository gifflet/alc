# review.py — Turn diff-line comments into a queued unit of work.
#
# Reviewing what an agent produced is the human moment ALC is built around: it
# sits right before `alc land`. Until now the UI could show a variant's diff but
# offered no way to react to it except discarding the branch.
#
# Comments never reach a running engine turn — the turn is the Engine's and
# opaque by contract, and there is no join point that accepts free text
# mid-turn. Instead they compose the TASK BODY of a new queue task, which the
# Assurance Loop then verifies like any other unit: recorded, replayable and
# visible on the Scorecard. That is the honest mechanism, and it is the same one
# `alc retry` already uses for failure feedback.
from __future__ import annotations

from pathlib import Path

from alc.ui import service
from alc.ui.errors import ApiError


def compose_feedback(branch: str, comments: list[dict]) -> str:
    """Render line comments as a task body.

    The shape mirrors what ``queue.failure_feedback`` produces, so the directive
    an engine receives looks familiar rather than novel. Pure, so the format is
    unit-tested without touching a repository.
    """
    lines = [f"Review feedback on branch {branch}:", ""]
    for comment in comments:
        path = str(comment.get("path", "")).strip()
        line_no = comment.get("line")
        text = str(comment.get("text", "")).strip()
        where = f"{path}:{line_no}" if path and line_no is not None else path or "(general)"
        lines.append(f"{where} — {text}")
    return "\n".join(lines)


def submit_review(
    root: Path,
    branch: str,
    comments: list[dict],
    *,
    kind: str = "flow",
    name: str | None = None,
    engine: str | None = None,
) -> dict:
    """Compose *comments* into one queue task for *branch*; return its stem.

    One task, not one per comment: the reviewer's notes are a single unit of
    work, and splitting them would let an agent fix line 12 while contradicting
    the note on line 40.
    """
    if not branch.startswith("alc/"):
        raise ApiError(f"not an alc/ branch: {branch}", status=422)
    cleaned = [c for c in comments if str(c.get("text", "")).strip()]
    if not cleaned:
        # An empty review is a no-op, not a task: queuing it would dispatch an
        # engine turn with nothing to act on.
        raise ApiError("no review comments to submit", status=422)
    if not name or not name.strip():
        # QueueTask.unit_name() falls back to `flow`, which is "" here — the task
        # would sit in the queue and fail the moment the drain tried to dispatch
        # it. Refuse up front rather than writing work that cannot run.
        raise ApiError(
            f"review needs a unit to run as: pass the {kind} name to dispatch",
            status=422,
        )

    payload = {
        "kind": kind,
        "name": name,
        "task": compose_feedback(branch, cleaned),
        "engine": engine,
    }
    if kind == "flow" and name:
        # Legacy-compatible: a flow task also carries `flow` so an older reader
        # resolves the unit name the same way.
        payload["flow"] = name
    stem = service.enqueue(root, payload)
    return {"stem": stem, "comments": len(cleaned), "branch": branch}
