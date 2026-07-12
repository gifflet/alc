# run_configs.py — Saved, named {command, args} presets per project.
#
# A Run Configuration captures a whitelisted command and its arguments so a user
# can re-run without re-filling a dialog. Configs persist to
# ``<root>/.alc/ui/run-configs.json`` and every save is validated through
# build_argv — the same validator the exec endpoint uses — so a stored config is
# always runnable via POST /exec.
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from alc.ui.command import build_argv
from alc.ui.errors import ApiError


class RunConfig(BaseModel):
    """A named preset: a whitelisted command and the arguments to run it with."""

    name: str
    command: str
    args: dict = {}


def _config_path(root: Path) -> Path:
    return root / ".alc" / "ui" / "run-configs.json"


def load_run_configs(root: Path) -> list[RunConfig]:
    """Read the saved run configs; return [] when absent, empty or malformed."""
    path = _config_path(root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
        return [RunConfig.model_validate(c) for c in data.get("configs", [])]
    except (json.JSONDecodeError, OSError, ValidationError, AttributeError):
        return []


def save_run_configs(root: Path, configs: list[RunConfig]) -> None:
    """Persist the run configs, creating ``.alc/ui/`` if needed."""
    path = _config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"configs": [c.model_dump() for c in configs]}
    path.write_text(json.dumps(payload, indent=2))


def validate_config(config: RunConfig) -> None:
    """Ensure a config is runnable; raises ApiError(422) on any invalid arg."""
    build_argv(config.command, config.args)


def add_run_config(root: Path, config: RunConfig) -> RunConfig:
    """Validate and append a config; reject a duplicate name (409)."""
    validate_config(config)
    configs = load_run_configs(root)
    if any(c.name == config.name for c in configs):
        raise ApiError(f"run config '{config.name}' already exists", status=409)
    configs.append(config)
    save_run_configs(root, configs)
    return config


def update_run_config(root: Path, name: str, config: RunConfig) -> RunConfig:
    """Validate and replace the config named ``name``; 404 when missing."""
    validate_config(config)
    configs = load_run_configs(root)
    for i, existing in enumerate(configs):
        if existing.name == name:
            configs[i] = config
            save_run_configs(root, configs)
            return config
    raise ApiError(f"no run config named '{name}'", status=404)


def delete_run_config(root: Path, name: str) -> None:
    """Remove the config named ``name``; 404 when missing."""
    configs = load_run_configs(root)
    remaining = [c for c in configs if c.name != name]
    if len(remaining) == len(configs):
        raise ApiError(f"no run config named '{name}'", status=404)
    save_run_configs(root, remaining)
