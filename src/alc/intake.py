# intake.py — Loads and parses the Operator Layer (manifest + blueprints + flows + specialists).
# Single responsibility: read YAML/Markdown from disk and return typed models.
from __future__ import annotations

from pathlib import Path

import yaml

from alc.models import Blueprint, Check, FlowDefinition, Manifest, ReportSpec, Specialist


def load_manifest(operator_layer: Path) -> Manifest:
    """Load and parse .alc/manifest.yaml into a Manifest model.

    Args:
        operator_layer: Path to the .alc/ directory.

    Returns:
        Parsed Manifest.

    Raises:
        FileNotFoundError: If manifest.yaml is missing.
    """
    manifest_path = operator_layer / "manifest.yaml"
    with manifest_path.open() as fh:
        data = yaml.safe_load(fh)
    return Manifest.model_validate(data)


def _parse_front_matter(content: str) -> tuple[dict, str]:
    """Split a Markdown file with YAML front-matter (between --- fences).

    Returns:
        (front_matter_dict, body_text)
    """
    content = content.strip()
    if not content.startswith("---"):
        return {}, content

    # Drop the opening '---' line.
    rest = content[3:]
    # Find the closing '---'.
    end_idx = rest.find("\n---")
    if end_idx == -1:
        return {}, content

    fm_text = rest[:end_idx].strip()
    body = rest[end_idx + 4:].strip()  # skip '\n---'
    fm_dict = yaml.safe_load(fm_text) or {}
    return fm_dict, body


def load_blueprint(blueprints_dir: Path, name: str) -> Blueprint:
    """Load a Blueprint by name from the blueprints directory.

    The Blueprint file is a Markdown file with YAML front-matter. The front-matter
    provides all Blueprint fields; the remaining body becomes `workflow`.

    Args:
        blueprints_dir: Directory containing blueprint Markdown files.
        name: Blueprint name (used as the filename stem).

    Returns:
        Parsed Blueprint.

    Raises:
        FileNotFoundError: If the blueprint file does not exist.
    """
    blueprint_path = blueprints_dir / f"{name}.md"
    content = blueprint_path.read_text()
    fm, body = _parse_front_matter(content)

    # Build Check objects from front-matter.
    raw_checks = fm.get("checks", [])
    checks = [
        Check(name=c["name"], command=c["command"]) if isinstance(c, dict) else c
        for c in raw_checks
    ]

    # Build ReportSpec if present.
    report: ReportSpec | None = None
    if "report" in fm:
        r = fm["report"]
        report = ReportSpec.model_validate(r)

    return Blueprint(
        name=fm.get("name", name),
        purpose=fm.get("purpose", ""),
        compute_tier=fm.get("compute_tier", "standard"),
        checks=checks,
        report=report,
        workflow=body,
    )


def load_all_blueprints(manifest: Manifest, operator_layer: Path) -> list[Blueprint]:
    """Load every .md file from the blueprints directory.

    `manifest.blueprints_dir` is relative to the project root (the parent of the
    Operator Layer), e.g. ".alc/blueprints".
    """
    blueprints_dir = operator_layer.parent / manifest.blueprints_dir

    blueprints = []
    for md_file in sorted(blueprints_dir.glob("*.md")):
        blueprints.append(load_blueprint(blueprints_dir, md_file.stem))
    return blueprints


def load_flow(flows_dir: Path, name: str) -> FlowDefinition:
    """Load a FlowDefinition by name from the flows directory.

    Flows are plain YAML files (not Markdown with front-matter) because they are
    configuration, not prompts.

    Args:
        flows_dir: Directory containing flow YAML files.
        name: Flow name (used as the filename stem).

    Returns:
        Parsed FlowDefinition.

    Raises:
        FileNotFoundError: If the flow file does not exist.
    """
    flow_path = flows_dir / f"{name}.yaml"
    with flow_path.open() as fh:
        data = yaml.safe_load(fh)
    return FlowDefinition.model_validate(data)


def load_all_flows(manifest: Manifest, operator_layer: Path) -> list[FlowDefinition]:
    """Load every .yaml file from the flows directory.

    `manifest.flows_dir` is relative to the project root (the parent of the
    Operator Layer), e.g. ".alc/flows".
    """
    flows_dir = operator_layer.parent / manifest.flows_dir
    if not flows_dir.exists():
        return []

    flows = []
    for yaml_file in sorted(flows_dir.glob("*.yaml")):
        flows.append(load_flow(flows_dir, yaml_file.stem))
    return flows


def load_specialist(specialists_dir: Path, name: str) -> Specialist:
    """Load a Specialist definition by name from the specialists directory.

    Specialists are plain YAML files (not Markdown with front-matter) because
    they are configuration, not prompts.

    Args:
        specialists_dir: Directory containing specialist YAML files.
        name: Specialist name (used as the filename stem).

    Returns:
        Parsed Specialist.

    Raises:
        FileNotFoundError: If the specialist file does not exist.
    """
    specialist_path = specialists_dir / f"{name}.yaml"
    with specialist_path.open() as fh:
        data = yaml.safe_load(fh)
    return Specialist.model_validate(data)
