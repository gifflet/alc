# inbox.py — What needs a human right now.
#
# ALC's model is human-ON-the-loop: the machine runs, the operator decides. The
# information behind those decisions already exists, but scattered — outstanding
# failures in archived reports, unmerged work in git, halted loops in loop state.
# This module answers one question ("what needs me?") by aggregating them.
#
# It DERIVES nothing and DECIDES nothing: every source is an existing function
# whose semantics are already tested. In particular `queue.outstanding_failures`
# owns the subtle part (retry lineage, resolved-by-a-later-retry), so the Inbox
# and `alc retry` can never disagree.
#
# Strictly read-only: building the Inbox must never touch a project.
from __future__ import annotations

from pathlib import Path

import yaml

from alc.intake import is_smoke_only, load_all_blueprints, load_manifest
from alc.loop import load_loop_state, loops_dir, state_path
from alc.models import QueueTask
from alc.queue import outstanding_failures
from alc.ui import service

# Ordering: a failure blocks delivery, a branch is finished work waiting to land,
# a halted loop is an automation that stopped. Lower sorts first.
KIND_URGENCY = {"failure": 0, "loop": 1, "branch": 2}


def _read_task(path: Path) -> QueueTask | None:
    """Parse a queue task file, or None when it is missing/unreadable."""
    try:
        return QueueTask.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, ValueError):
        return None


def _pending_retry_roots(queue_dir: Path) -> set[str]:
    """Lineage roots that already have a retry sitting in the queue.

    A retry re-enqueues the work but does NOT resolve the failure — only a
    successful run does. So the item must stay (removing it would claim a fix
    that has not happened), but the operator has to see that a retry is already
    waiting, or they will queue the same work twice.
    """
    roots = set()
    for path in sorted(queue_dir.glob("*.yaml")):
        task = _read_task(path)
        if task is not None and task.retry_of:
            roots.add(task.retry_of)
    return roots


def _lineage_root(done_dir: Path, stem: str) -> str:
    """The root stem of *stem*'s retry lineage (itself when it is the root)."""
    task = _read_task(done_dir / f"{stem}.yaml")
    return (task.retry_of if task and task.retry_of else stem)


def _failures(root: Path) -> list[dict]:
    """Unresolved failed tasks — one per retry lineage (see outstanding_failures)."""
    queue_dir = service.operator_layer(root) / "queue"
    done_dir = queue_dir / "done"
    pending_roots = _pending_retry_roots(queue_dir)

    items = []
    for index, failed in enumerate(outstanding_failures(done_dir)):
        retry_pending = _lineage_root(done_dir, failed.stem) in pending_roots
        items.append(
            {
                "kind": "failure",
                "id": f"failure:{failed.stem}",
                "title": failed.title or failed.stem,
                "reason": failed.reason,
                # outstanding_failures already sorts most-recent-first; keep that
                # order within the group without re-reading mtimes.
                "order": index,
                "stem": failed.stem,
                "retries": failed.retries,
                "retry_pending": retry_pending,
            }
        )
    return items


def _branches(root: Path) -> list[dict]:
    """`alc/*` branches that are finished work not yet integrated."""
    listing = service.list_branches(root)
    if not listing["available"]:
        return []  # not a git repo / no git binary: nothing to decide here
    # `verified: True` on a project whose every check is the scaffold's
    # placeholder is technically true and materially misleading — "the check
    # that cannot fail passed" is not what the word promises, least of all to
    # the operator who trusts it MOST (dogfood finding 26, from the junior
    # persona's inbox). Rule 16 already knows how to tell; ask the same
    # question here and qualify the reason.
    smoke_only_project = _all_execution_blueprints_smoke_only(root)
    items = []
    for branch in listing["branches"]:
        if branch["merged"]:
            continue
        # `verified is False` means a run branch with no archived report: its
        # checks failed or it was interrupted, and it committed anyway. Saying
        # "ready to land" about that is the one thing this product must not do.
        verified = branch.get("verified")
        if verified is False:
            reason = f"{branch['label']} work — checks did not pass, review before landing"
        elif verified is True and smoke_only_project:
            reason = (
                f"{branch['label']} work — only the placeholder check ran "
                "(it cannot fail); read the diff before landing"
            )
        else:
            reason = f"{branch['label']} work ready to land"
        items.append(
            {
                "kind": "branch",
                "id": f"branch:{branch['name']}",
                "title": branch["name"],
                "reason": reason,
                "order": -branch["committed_at"],  # newest first
                "branch": branch["name"],
                "committed_at": branch["committed_at"],
                "verified": verified,
            }
        )
    return items


def _loops(root: Path) -> list[dict]:
    """Loops halted by a backstop (max_cycles, budget, consecutive failures)."""
    operator_layer = service.operator_layer(root)
    try:
        manifest = load_manifest(operator_layer)
    except (OSError, ValueError):
        return []  # a malformed manifest is lint's problem, not the Inbox's
    directory = loops_dir(manifest, operator_layer)
    if not directory.is_dir():
        return []

    # Names come from the filenames, not from parsing each definition: the Inbox
    # only needs to find the matching state file. Parsing would make ONE
    # malformed loop hide every other loop's halt — the Inbox must not go quiet
    # because of a YAML typo. The *.yaml glob naturally skips the .state.json and
    # .ledger.jsonl siblings that share this directory.
    items = []
    for path in sorted(directory.glob("*.yaml")):
        name = path.stem
        try:
            state = load_loop_state(state_path(directory, name), name)
        except (OSError, ValueError):
            continue  # unreadable state is not a decision; lint surfaces it
        if state.status != "stopped":
            continue
        items.append(
            {
                "kind": "loop",
                "id": f"loop:{name}",
                "title": name,
                "reason": state.stopped_reason or "stopped",
                "order": 0,
                "loop": name,
                "cycle": state.cycle,
                "budget_used": state.budget_used,
            }
        )
    return items


def _all_execution_blueprints_smoke_only(root: Path) -> bool:
    """True when every execution Blueprint resolves to the smoke placeholder.

    Best-effort and conservative: any load failure answers False (no claim),
    and `plan` is exempt inside is_smoke_only itself.
    """
    try:
        operator_layer = service.operator_layer(root)
        manifest = load_manifest(operator_layer)
        blueprints = [
            bp for bp in load_all_blueprints(manifest, operator_layer) if bp.name != "plan"
        ]
        return bool(blueprints) and all(is_smoke_only(manifest, bp) for bp in blueprints)
    except Exception:  # noqa: BLE001 — an unreadable layer must not break the inbox
        return False


def build_inbox(root: Path) -> dict:
    """Every decision waiting on a human, most urgent first.

    Returns ``{"items": [...], "count": N}``. ``count`` drives the activity-bar
    badge, so it is the same number the list shows — never a separate query that
    could drift from it.
    """
    items = _failures(root) + _loops(root) + _branches(root)
    items.sort(key=lambda item: (KIND_URGENCY[item["kind"]], item["order"]))
    return {"items": items, "count": len(items)}
