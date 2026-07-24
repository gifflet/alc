# textutil.py — small, dependency-free text helpers shared across the control plane.
# A leaf module (stdlib only) so any module can import it without an import cycle.
from __future__ import annotations

import json
import re
import unicodedata


def extract_json(text: str) -> object | None:
    """Recover a JSON value from raw model output that may be fenced or prose-wrapped.

    Tries strict ``json.loads`` first; on failure, extracts the outermost
    bracketed region — the object ``{`` or array ``[`` that opens FIRST in the
    text wins — and parses that slice. Never raises: returns the parsed value,
    or ``None`` when the text is not a string, has no bracketed region, or the
    recovered slice is still not valid JSON.
    """
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    candidates = []
    obj_start = text.find("{")
    if obj_start != -1:
        candidates.append((obj_start, "}"))
    arr_start = text.find("[")
    if arr_start != -1:
        candidates.append((arr_start, "]"))
    if not candidates:
        return None
    start, closer = min(candidates)
    end = text.rfind(closer)
    if end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def slugify(text: str, max_len: int = 40) -> str:
    """Turn a title into a filesystem-safe slug.

    Transliterates accented characters to their ASCII base (so Portuguese words
    keep their letters instead of losing them), lowercases, collapses any run of
    non-alphanumeric characters to a single hyphen, trims leading/trailing
    hyphens, and caps the length. Returns ``""`` when the text has no usable
    characters (callers fall back to a uid).
    """
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug
