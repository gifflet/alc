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
