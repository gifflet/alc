# authoring.py — Minimal unit scaffolds shared by the CLI and the UI.
#
# Each scaffold is a minimal, valid payload for a new unit — it parses cleanly
# through the collection's real loader, and the operator fills in the details
# from there. Lives in the core (not `alc.ui`) so the CLI can author units
# without importing the optional UI layer.
from __future__ import annotations

_SCAFFOLDS: dict[str, str] = {
    "blueprints": (
        "---\n"
        "name: {name}\n"
        "purpose: Describe what this blueprint does.\n"
        "compute_tier: standard\n"
        "checks:\n"
        "  - name: smoke\n"
        '    command: ["true"]\n'
        "---\n\n"
        "## {name} workflow\n\n"
        "1. Read the task and locate the relevant files.\n"
        "2. Make the smallest change that satisfies it.\n"
        "3. Run the checks to verify.\n"
    ),
    "flows": (
        "name: {name}\n"
        'description: ""\n'
        "stages:\n"
        "  - name: build\n"
        "    blueprint: chore\n"
    ),
    "specialists": (
        "name: {name}\n"
        'area: ""\n'
        "blueprint: chore\n"
        "knowledge_path: .alc/knowledge/{name}.md\n"
    ),
    "loops": ("name: {name}\nstop:\n  max_cycles: 10\n"),
    "primers": ("# {name}\n\nReusable context for this project.\n"),
}


def scaffold_text(kind: str, name: str) -> str:
    """Return a minimal valid payload for a new *name* unit of *kind* (empty if none)."""
    template = _SCAFFOLDS.get(kind)
    return template.format(name=name) if template else ""
