# command.py — Build a safe argv for an `alc` subprocess from an API request.
#
# The exec endpoint accepts {command, args}. This module maps that to a strict
# argv list ``[python, "-m", "alc", <command>, ...flags]`` — NEVER a shell
# string — with a per-command whitelist of positionals and flags. Anything
# outside the whitelist is rejected (ApiError 422) so the UI cannot smuggle
# arbitrary flags or commands into the CLI.
from __future__ import annotations

import sys
from dataclasses import dataclass

from alc.ui.errors import ApiError


@dataclass(frozen=True)
class _Spec:
    """Whitelist for one command: required/optional positionals and flags."""

    positionals: tuple[str, ...] = ()
    opt_positionals: tuple[str, ...] = ()
    value_flags: tuple[str, ...] = ()
    bool_flags: tuple[str, ...] = ()

    def allowed(self) -> set[str]:
        return {
            *self.positionals,
            *self.opt_positionals,
            *self.value_flags,
            *self.bool_flags,
        }


# The commands the UI may dispatch, each with its exact accepted arguments.
_COMMANDS: dict[str, _Spec] = {
    "run": _Spec(
        positionals=("blueprint", "task"),
        value_flags=("engine", "tier", "primer"),
        bool_flags=("isolate", "bundle"),
    ),
    "flow": _Spec(
        positionals=("flow", "task"),
        value_flags=("engine", "tier", "primer"),
        bool_flags=("isolate", "bundle"),
    ),
    "specialist": _Spec(
        positionals=("name", "task"),
        value_flags=("engine",),
    ),
    "tick": _Spec(value_flags=("concurrency",)),
    "conduct": _Spec(
        positionals=("goal",),
        value_flags=("engine", "tier", "concurrency"),
        bool_flags=("enqueue", "parallel"),
    ),
    "cycle": _Spec(
        positionals=("name",),
        value_flags=("engine", "concurrency"),
        bool_flags=("reset", "status"),
    ),
    "loop": _Spec(
        positionals=("name",),
        value_flags=("engine", "interval"),
        bool_flags=("reset",),
    ),
    "retry": _Spec(opt_positionals=("stem",), bool_flags=("all",)),
    "lint": _Spec(bool_flags=("json",)),
}


def command_schema() -> dict[str, dict[str, list[str]]]:
    """Serialize the command whitelist to a JSON-friendly schema.

    The single source of truth the frontend reads to render a config form and
    the backend reuses (via build_argv) to validate — one entry per command with
    its accepted positionals, optional positionals and value/bool flags.
    """
    return {
        command: {
            "positionals": list(spec.positionals),
            "opt_positionals": list(spec.opt_positionals),
            "value_flags": list(spec.value_flags),
            "bool_flags": list(spec.bool_flags),
        }
        for command, spec in _COMMANDS.items()
    }


def build_argv(command: str, args: dict | None) -> list[str]:
    """Return the argv for ``alc <command>`` from a validated args dict.

    Raises ApiError(422) for an unknown command, an unknown argument, or a
    missing required positional.
    """
    spec = _COMMANDS.get(command)
    if spec is None:
        raise ApiError(
            f"unknown command '{command}' (allowed: {sorted(_COMMANDS)})", status=422
        )

    args = args or {}
    unknown = set(args) - spec.allowed()
    if unknown:
        raise ApiError(
            f"unknown arg(s) for '{command}': {sorted(unknown)}", status=422
        )

    argv = [sys.executable, "-m", "alc", command]

    for name in spec.positionals:
        value = args.get(name)
        if value in (None, ""):
            raise ApiError(f"'{command}' requires '{name}'", status=422)
        argv.append(str(value))

    for name in spec.opt_positionals:
        value = args.get(name)
        if value not in (None, ""):
            argv.append(str(value))

    for name in spec.value_flags:
        value = args.get(name)
        if value not in (None, ""):
            argv.extend([f"--{name}", str(value)])

    for name in spec.bool_flags:
        if args.get(name):
            argv.append(f"--{name}")

    return argv
