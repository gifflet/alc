# specialist.py — Specialist orchestrator: Recall -> Act -> Learn.
#
# A Specialist is an agent tied to one area of the codebase. It reads its
# Knowledge File before acting (Recall), performs work via execute_mandate (Act),
# then asks the engine to update the Knowledge File from what it just did (Learn).
#
# DIP seam: the Engine is injected by the caller in `learn`; no concrete adapter
# is imported here. `resolve_engine` is imported locally in `run_specialist`
# (same pattern as conduct.py).
from __future__ import annotations

from pathlib import Path

from alc.engine import Engine, EngineRequest
from alc.intake import load_blueprint
from alc.models import Blueprint, Manifest, Specialist, SpecialistReport
from alc.runner import execute_mandate

# ---------------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------------


def recall(knowledge_path: Path) -> str:
    """Return the Knowledge File's text, or empty string if it does not exist.

    Args:
        knowledge_path: Absolute path to the Knowledge File.

    Returns:
        File contents as a string, or "" when the file is absent.
    """
    if not knowledge_path.exists():
        return ""
    return knowledge_path.read_text()


# ---------------------------------------------------------------------------
# Act directive composition (pure / testable)
# ---------------------------------------------------------------------------

_ACT_HEADER_TEMPLATE = """\
# ALC Specialist — {blueprint_name}
Task: {task}

---
"""

_KNOWLEDGE_SECTION_HEADER = (
    "## Specialist knowledge (working model — not authoritative; the code is)\n\n"
)


def compose_act_directive(blueprint: Blueprint, task: str, knowledge: str) -> str:
    """Compose the Act directive for a Specialist invocation.

    Produces a header naming the Specialist's blueprint and task, an optional
    knowledge section (only when ``knowledge`` is non-empty), then the
    blueprint's workflow body.

    Args:
        blueprint: The Blueprint providing the workflow.
        task: The free-text task the Specialist must perform.
        knowledge: Current Knowledge File contents; omitted from the directive
            when empty.

    Returns:
        The fully composed directive string.
    """
    header = _ACT_HEADER_TEMPLATE.format(
        blueprint_name=blueprint.name,
        task=task,
    )

    knowledge_section = ""
    if knowledge:
        knowledge_section = _KNOWLEDGE_SECTION_HEADER + knowledge + "\n\n---\n"

    return header + knowledge_section + blueprint.workflow


# ---------------------------------------------------------------------------
# Learn
# ---------------------------------------------------------------------------

_LEARN_DIRECTIVE_TEMPLATE = """\
You maintain a Knowledge File: a concise, durable working model of one area of a
codebase (key files, patterns, gotchas). It is not a transcript or a changelog.

Area: {area}

Current Knowledge File (between the <<<BEGIN>>> and <<<END>>> markers):
<<<BEGIN>>>
{current_knowledge}
<<<END>>>

A task was just completed in this area. Use it only to decide what, if anything,
is worth recording durably:
- Task: {task}
- What the agent did: {act_output}

Produce the updated Knowledge File. If nothing durable changed, reproduce the
current one unchanged. Keep it concise.

Respond with ONLY the Knowledge File content itself — no preamble, no commentary,
no code fences, and do NOT copy any of the headings or markers from this prompt.
"""


def learn(
    engine: Engine,
    model: str | None,
    knowledge: str,
    area: str,
    task: str,
    act_output: str,
) -> str:
    """Ask the engine to update the Knowledge File and return the new text.

    Builds a Learn directive, calls the engine, and returns the result. If the
    engine returns blank/whitespace, the original ``knowledge`` is returned
    unchanged (safety: never overwrite with nothing).

    Args:
        engine: Injected Engine instance (DIP — no concrete adapter imported here).
        model: Concrete model id resolved from the Compute Tier (may be None).
        knowledge: Current Knowledge File contents.
        area: Human description of the area this Specialist covers.
        task: The task the Specialist just completed.
        act_output: The full output_text from the Act step's RunReport.

    Returns:
        Updated Knowledge File text, or the original ``knowledge`` if the engine
        returns blank output.
    """
    directive = _LEARN_DIRECTIVE_TEMPLATE.format(
        area=area,
        current_knowledge=knowledge if knowledge else "(empty — first run)",
        task=task,
        act_output=act_output,
    )

    request = EngineRequest(
        directive=directive,
        workdir=Path.cwd(),
        model=model,
    )
    result = engine.run(request)

    new_knowledge = result.output_text
    if not new_knowledge or not new_knowledge.strip():
        # Safety: never overwrite the Knowledge File with nothing.
        return knowledge

    return new_knowledge


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_specialist(
    manifest: Manifest,
    operator_layer: Path,
    specialist: Specialist,
    task: str,
    engine_override: str | None = None,
    workdir: Path | None = None,
) -> SpecialistReport:
    """Orchestrate one Recall -> Act -> Learn cycle for a Specialist.

    1. **Recall** — read the Knowledge File (empty string if absent).
    2. **Act** — load the Blueprint, compose the directive, run execute_mandate.
    3. **Learn** — if Act succeeded, ask the engine to update the Knowledge File;
       write the result to disk when the text has changed.

    Args:
        manifest: Loaded Manifest (engine config, compute tiers, blueprints_dir).
        operator_layer: Path to the ``.alc/`` directory.
        specialist: The Specialist to run.
        task: Free-text task description provided by the operator.
        engine_override: Use this engine name instead of manifest.default_engine.
        workdir: Directory the Act step runs checks in. Defaults to Path.cwd()
            (None = unchanged). Pass an IsolatedWorktree path to confine edits.

    Returns:
        SpecialistReport with the Specialist name, Act RunReport, and whether
        the Knowledge File was updated.

    NOTE: Running the SAME Specialist concurrently races on its Knowledge File
    (Recall reads and Learn writes the one file). Distinct Specialists are safe
    to fan out in parallel — each owns a separate Knowledge File.
    """
    from alc.engines.registry import resolve_engine

    # Recall: read the Knowledge File.
    knowledge_path = operator_layer.parent / specialist.knowledge_path
    knowledge = recall(knowledge_path)

    # Load the Blueprint for the Act step.
    blueprints_dir = operator_layer.parent / manifest.blueprints_dir
    blueprint = load_blueprint(blueprints_dir, specialist.blueprint)

    # Act: compose the directive and run the Single Mandate.
    directive = compose_act_directive(blueprint, task, knowledge)
    act = execute_mandate(manifest, blueprint, directive, engine_override, workdir)

    # Learn: only when Act succeeded.
    knowledge_updated = False
    if act.success:
        engine_name = engine_override or manifest.default_engine
        engine = resolve_engine(engine_name, manifest.engines)
        model: str | None = manifest.compute_tiers.get("standard", {}).get(engine_name)

        new_knowledge = learn(
            engine=engine,
            model=model,
            knowledge=knowledge,
            area=specialist.area,
            task=task,
            act_output=act.output_text,
        )

        if new_knowledge != knowledge:
            knowledge_path.parent.mkdir(parents=True, exist_ok=True)
            knowledge_path.write_text(new_knowledge)
            knowledge_updated = True

    return SpecialistReport(
        specialist=specialist.name,
        act=act,
        knowledge_updated=knowledge_updated,
    )
