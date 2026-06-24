# registry.py — Maps engine type strings to constructed Engine instances.
# The control plane uses this to resolve a name from the manifest into a concrete adapter.
# This is the only place that imports concrete engine classes (DIP boundary).
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alc.engine import Engine

# Registry of known engine type strings -> factory callables.
# Add new adapters here without touching the control plane.
_FACTORIES: dict[str, type] = {}


def _register_defaults() -> None:
    """Lazy import so control-plane modules never import adapters directly."""
    from alc.engines.claude_code import ClaudeCodeEngine
    from alc.engines.gemini import GeminiEngine
    from alc.engines.mock import MockEngine

    _FACTORIES["mock"] = MockEngine
    _FACTORIES["claude-code"] = ClaudeCodeEngine
    _FACTORIES["gemini"] = GeminiEngine


def resolve_engine(engine_name: str, engines_config: dict[str, dict]) -> "Engine":
    """Resolve an engine name from the manifest to a constructed Engine instance.

    Args:
        engine_name: The key used in manifest.engines (e.g. "mock", "claude-code").
        engines_config: The full manifest.engines dict.

    Returns:
        A constructed Engine instance.

    Raises:
        KeyError: If the engine name or type is not found.
    """
    if not _FACTORIES:
        _register_defaults()

    if engine_name not in engines_config:
        raise KeyError(
            f"Engine '{engine_name}' not declared in manifest.engines. "
            f"Available: {list(engines_config)}"
        )

    engine_conf = engines_config[engine_name]
    engine_type = engine_conf.get("type")

    if engine_type not in _FACTORIES:
        raise KeyError(
            f"Unknown engine type '{engine_type}' for engine '{engine_name}'. "
            f"Registered types: {list(_FACTORIES)}"
        )

    return _FACTORIES[engine_type]()
