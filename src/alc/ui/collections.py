# collections.py — Generic CRUD over the Operator Layer's file collections.
#
# Blueprints, flows, specialists, loops and primers are all "a directory of files
# with one stem per unit". This module describes each as a CollectionSpec and
# implements list/read/write/delete once. Validation NEVER reimplements parsing:
# a raw payload is written to a temp dir and run through the real alc.intake
# loader, so a bad payload fails exactly as `alc` would (surfaced as 422).
from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from alc.intake import load_blueprint, load_flow, load_loop, load_specialist
from alc.models import Manifest
from alc.ui.errors import ApiError


@dataclass(frozen=True)
class CollectionSpec:
    """Describes one file collection: where it lives, its suffix and its loader."""

    name: str            # collection name (also the URL segment), e.g. "blueprints"
    dir_attr: str        # Manifest attribute holding the dir (relative to root)
    suffix: str          # file suffix, ".md" or ".yaml"
    loader: Callable[[Path, str], object] | None  # (dir, name) -> model; None = raw only


# The collections exposed by the API. Prompts are handled separately (reserved
# vs free semantics), so they are intentionally NOT listed here.
COLLECTIONS: dict[str, CollectionSpec] = {
    "blueprints": CollectionSpec("blueprints", "blueprints_dir", ".md", load_blueprint),
    "flows": CollectionSpec("flows", "flows_dir", ".yaml", load_flow),
    "specialists": CollectionSpec("specialists", "specialists_dir", ".yaml", load_specialist),
    "loops": CollectionSpec("loops", "loops_dir", ".yaml", load_loop),
    "primers": CollectionSpec("primers", "primers_dir", ".md", None),
}


def get_spec(collection: str) -> CollectionSpec:
    """Return the CollectionSpec for *collection* or raise ApiError(404)."""
    spec = COLLECTIONS.get(collection)
    if spec is None:
        raise ApiError(f"unknown collection '{collection}'", status=404)
    return spec


def collection_dir(spec: CollectionSpec, root: Path, manifest: Manifest) -> Path:
    """Resolve the on-disk directory for *spec* under the project root."""
    return root / getattr(manifest, spec.dir_attr)


def _parse_raw(spec: CollectionSpec, name: str, raw: str) -> object | None:
    """Validate *raw* through the collection's real loader; return the model.

    Returns None for a raw-only collection (no loader). Raises ApiError(422)
    when the loader rejects the payload (bad YAML / front-matter / schema).
    """
    if spec.loader is None:
        return None
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / f"{name}{spec.suffix}").write_text(raw)
        try:
            return spec.loader(Path(td), name)
        except Exception as exc:  # noqa: BLE001 — surface any parse/validation error
            raise ApiError(f"invalid {spec.name} '{name}': {exc}", status=422) from exc


def _dump(model: object | None) -> dict | None:
    """Serialise a parsed model to a JSON-safe dict (None passes through)."""
    if model is None:
        return None
    return model.model_dump(mode="json")  # type: ignore[attr-defined]


def list_items(spec: CollectionSpec, root: Path, manifest: Manifest) -> list[dict]:
    """List the units in a collection: [{name, mtime}], sorted by name."""
    directory = collection_dir(spec, root, manifest)
    if not directory.is_dir():
        return []
    items = []
    for path in sorted(directory.glob(f"*{spec.suffix}")):
        items.append({"name": path.stem, "mtime": path.stat().st_mtime})
    return items


def read_item(spec: CollectionSpec, root: Path, manifest: Manifest, name: str) -> dict:
    """Return {raw, parsed} for one unit; raise ApiError(404) when absent.

    ``parsed`` is best-effort: an on-disk file that no longer validates still
    returns its raw text with parsed=None rather than failing the read.
    """
    path = collection_dir(spec, root, manifest) / f"{name}{spec.suffix}"
    if not path.is_file():
        raise ApiError(f"no {spec.name} named '{name}'", status=404)
    raw = path.read_text()
    parsed = None
    if spec.loader is not None:
        try:
            parsed = _dump(spec.loader(path.parent, name))
        except Exception:  # noqa: BLE001 — tolerate an invalid file on read
            parsed = None
    return {"raw": raw, "parsed": parsed}


def write_item(
    spec: CollectionSpec,
    root: Path,
    manifest: Manifest,
    name: str,
    raw: str,
    create: bool,
) -> dict:
    """Validate then persist one unit; return {raw, parsed}.

    ``create`` True (POST) refuses to overwrite an existing unit (409); False
    (PUT) creates or updates. Validation runs BEFORE any write, so an invalid
    payload never touches disk.
    """
    directory = collection_dir(spec, root, manifest)
    path = directory / f"{name}{spec.suffix}"
    if create and path.exists():
        raise ApiError(f"{spec.name} '{name}' already exists", status=409)
    parsed = _dump(_parse_raw(spec, name, raw))
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(raw)
    return {"raw": raw, "parsed": parsed}


def delete_item(spec: CollectionSpec, root: Path, manifest: Manifest, name: str) -> None:
    """Delete one unit; raise ApiError(404) when it does not exist."""
    path = collection_dir(spec, root, manifest) / f"{name}{spec.suffix}"
    if not path.is_file():
        raise ApiError(f"no {spec.name} named '{name}'", status=404)
    path.unlink()
