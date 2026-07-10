# textutil.py — small, dependency-free text helpers shared across the control plane.
# A leaf module (stdlib only) so any module can import it without an import cycle.
from __future__ import annotations

import re
import unicodedata


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
