# primer.py — Context Budget Trim: load and scaffold named Primers.
# A Primer is a curated context block injected into a run's directive instead of
# an always-on memory dump. See docs/concepts.md — "Context Budget / Trim".
from __future__ import annotations

from pathlib import Path

# Starter template written when new_primer() creates a fresh file.
_PRIMER_TEMPLATE = """\
# {name}

## Where things live
<!-- Describe the key directories and files the agent should know about. -->

## Conventions
<!-- List naming rules, style guides, or patterns followed in this codebase. -->
"""


def new_primer(primers_dir: Path, name: str, force: bool = False) -> Path:
    """Create a new Primer file at primers_dir/<name>.md from a starter template.

    Args:
        primers_dir: Directory where Primer Markdown files live (e.g. .alc/primers/).
        name: Primer name (used as the filename stem, without the .md extension).
        force: If True, overwrite an existing file. If False and the file exists,
            raise FileExistsError.

    Returns:
        Path to the newly created Primer file.

    Raises:
        FileExistsError: If the Primer file already exists and force is False.
    """
    primers_dir.mkdir(parents=True, exist_ok=True)
    primer_path = primers_dir / f"{name}.md"
    if primer_path.exists() and not force:
        raise FileExistsError(
            f"Primer '{name}' already exists: {primer_path}; pass --force to overwrite"
        )
    primer_path.write_text(_PRIMER_TEMPLATE.format(name=name))
    return primer_path


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
