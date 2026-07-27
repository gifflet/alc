# variants.py — Persisted archive for `alc explore` variants, read back by
# `alc compare` (and matched against by `alc adopt`'s sibling discovery). A
# variant's branch name (minted by IsolatedWorktree) is only known AFTER the
# fan-out finishes, and `explore`'s in-memory FanoutReport is gone once the
# process exits — so `compare`, run later in a separate invocation, must read
# each variant back from one JSON file per branch under `manifest.variants_dir`.
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from alc.branches import live_variant_branches
from alc.models import UnitResult


def _stem(ref: str) -> str:
    """Return the archive stem for a branch name or a bare stem: strip 'alc/'."""
    return ref.removeprefix("alc/")


def write_variant(
    variants_dir: Path,
    branch: str,
    engine: str | None,
    tier: str | None,
    unit: UnitResult,
) -> Path:
    """Archive one explore variant's outcome to ``<variants_dir>/<stem>.json``.

    Keyed by *branch* (the committed worktree branch, e.g.
    ``alc/variant-1-a1b2c3d4``) so a later, separate ``alc compare``/``alc
    adopt`` invocation can read it back by the branch name or its bare stem.
    Only meaningful for a variant that actually committed — a caller with no
    branch has nothing worth archiving.
    """
    variants_dir.mkdir(parents=True, exist_ok=True)
    record = {"branch": branch, "engine": engine, "tier": tier, "unit": unit.model_dump(mode="json")}
    path = variants_dir / f"{_stem(branch)}.json"
    path.write_text(json.dumps(record, indent=2))
    return path


def read_variant(
    variants_dir: Path, ref: str
) -> tuple[UnitResult, str | None, str | None] | None:
    """Read back one archived variant by branch name or its bare stem.

    Returns ``(unit, engine, tier)``, or None when no archive exists for *ref*
    (never explored, or the archive is unreadable/malformed).
    """
    path = variants_dir / f"{_stem(ref)}.json"
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text())
        unit = UnitResult.model_validate(record["unit"])
    except Exception:
        return None
    return unit, record.get("engine"), record.get("tier")


def variant_row(unit: UnitResult, engine: str | None = None, tier: str | None = None) -> dict:
    """Build one explore/compare table row from a UnitResult (plus its engine/tier).

    ``engine``/``tier`` are the variant's REQUESTED values (known to the caller
    — ``cmd_explore`` built the unit, ``read_variant`` returns them from the
    archive); ``engine`` falls back to the report's resolved engine name when
    not given. Every field printed comes straight off ``RunReport`` — nothing
    computed here beyond picking it apart into a flat, printable shape.
    """
    rr = unit.run_report
    if rr is None:
        return {
            "branch": unit.branch,
            "engine": engine,
            "tier": tier,
            "success": unit.success,
            "checks": unit.error or "no report",
            "scorecard": None,
            "usage": None,
            "diffstat": None,
        }
    failed = rr.attempts[-1].failed_checks if rr.attempts else []
    checks = "all passed" if not failed else f"failed: {', '.join(failed)}"
    return {
        "branch": unit.branch,
        "engine": engine or rr.engine,
        "tier": tier,
        "success": unit.success,
        "checks": checks,
        "scorecard": rr.scorecard.model_dump(),
        "usage": asdict(rr.usage) if rr.usage is not None else None,
        "diffstat": rr.diffstat.model_dump() if rr.diffstat is not None else None,
    }


def mark_live(rows: list[dict], repo_root: Path | None) -> list[dict]:
    """Annotate each variant row with ``live``: does its branch still exist in git?

    THE one enricher shared by both Compare surfaces (bare `alc compare` and the UI
    ``ui.service.list_variants``) so neither offers Diff/Adopt on a branch-gone
    (resolved) variant — both would 404. A resolved variant stays in the listing as
    history; ``live`` only tells the surface which actions are still valid.

    ``repo_root=None`` (off git — no repository, no branches) marks EVERY row
    ``live: False`` — the safe default: no branch means nothing actionable, hence no
    broken button. A never-committed row (``branch`` is None) is likewise
    ``live: False``. One `for-each-ref` (``live_variant_branches``) answers the whole
    table. Mutates *rows* in place and returns them. This is a compare-surface
    concept only — explore-time rows are deliberately NOT marked.
    """
    live = live_variant_branches(repo_root) if repo_root is not None else set()
    for row in rows:
        branch = row.get("branch")
        row["live"] = branch in live if branch else False
    return rows


def list_all_variants(variants_dir: Path) -> list[dict]:
    """Enumerate EVERY archived variant under *variants_dir* as a comparable row.

    THE one enumeration shared by the UI Compare view (``ui.service.list_variants``)
    and bare ``alc compare`` — so the CLI read and the UI Compare view can never
    show a different set. An unreadable/malformed archive is silently SKIPPED: a
    bulk listing degrades gracefully rather than failing on one bad file (an
    explicitly-NAMED ref, by contrast, stays an error in ``read_variant``'s
    caller). Rows come out sorted by archive stem — the UI's order, preserved here
    for parity. A missing ``variants_dir`` (nothing explored yet) is an empty list.

    Takes ``variants_dir`` (this module's existing seam — ``write_variant`` /
    ``read_variant`` are already ``variants_dir``-keyed) so this stays ignorant of
    manifest loading; the caller resolves ``manifest.variants_dir`` and passes it in.
    """
    if not variants_dir.is_dir():
        return []
    rows = []
    for path in sorted(variants_dir.glob("*.json")):
        found = read_variant(variants_dir, path.stem)
        if found is None:
            continue
        unit, engine, tier = found
        rows.append(variant_row(unit, engine, tier))
    return rows
