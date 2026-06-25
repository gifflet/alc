# primer.py — Context Budget Trim: load a named Primer from the Operator Layer.
# A Primer is a curated context block injected into a run's directive instead of
# an always-on memory dump. See docs/concepts.md — "Context Budget / Trim".
from __future__ import annotations

from pathlib import Path


def load_primer(primers_dir: Path, name: str) -> str:
    """Return the text of the named Primer file.

    Args:
        primers_dir: Directory containing Primer Markdown files (e.g. .alc/primers/).
        name: Primer name (used as the filename stem, without the .md extension).

    Returns:
        Raw text content of the Primer file.

    Raises:
        FileNotFoundError: If the Primer file does not exist in primers_dir.
    """
    primer_path = primers_dir / f"{name}.md"
    if not primer_path.exists():
        raise FileNotFoundError(
            f"Primer '{name}' not found: expected {primer_path}"
        )
    return primer_path.read_text()
