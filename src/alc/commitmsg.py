# commitmsg.py — Engine-generated Conventional Commits subject for control-plane commits.
# Every commit the ALC control plane makes (worktree exit, FlowRunner terminal commit)
# can optionally route through here to produce a concise, typed subject from the staged
# diff rather than relying on a static template.
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from alc.engine import EngineRequest, EngineResult
from alc.engines.registry import resolve_engine
from alc.models import Manifest
from alc.prompts import resolve_prompt

# Matches a valid Conventional Commits subject line.
_CC_RE = re.compile(
    r"^(feat|fix|chore|refactor|docs|test|ci|perf|build|style|revert)"
    r"(\([^)]+\))?!?: .+"
)

# Characters to strip from the start/end of engine output when sanitizing.
_STRIP_CHARS = "`\"'"

# Maximum diff length forwarded to the engine (keeps the prompt within budget).
_DIFF_CAP = 8000

# Maximum length of the returned subject line (guards against runaway output).
_SUBJECT_CAP = 100


def _sanitize(text: str) -> str:
    """Return the first non-empty line of *text*, stripped of backticks/quotes."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("co-authored-by"):
            continue
        return line.strip(_STRIP_CHARS)
    return ""


def generate_commit_message(
    diff: str,
    engine: object,
    model: str | None,
    workdir: Path,
    operator_layer: Path,
    manifest: Manifest,
    fallback: str,
) -> str:
    """Generate a Conventional Commits subject from *diff* via *engine*.

    Returns *fallback* when the diff is empty, the engine fails, or the output
    does not match the Conventional Commits pattern.  Never raises.

    Args:
        diff: The output of ``git diff --cached`` (staged changes).
        engine: An Engine instance whose ``run`` method is called once.
        model: Model id to forward in the EngineRequest (may be None).
        workdir: Working directory for the engine turn.
        operator_layer: Path to the ``.alc/`` directory (for prompt resolution).
        manifest: The loaded Manifest.
        fallback: Message to return when generation fails or is skipped.

    Returns:
        A validated Conventional Commits subject line, or *fallback*.
    """
    if not diff or not diff.strip():
        return fallback

    try:
        template = resolve_prompt("commit-message", operator_layer, manifest)
        # Inject the diff with str.replace, not .format(), because the diff may
        # contain literal braces that would crash a .format() call.
        directive = template.replace("{diff}", diff[:_DIFF_CAP])

        request = EngineRequest(directive=directive, workdir=workdir, model=model)
        result: EngineResult = engine.run(request)  # type: ignore[attr-defined]

        subject = _sanitize(result.output_text)
        if _CC_RE.match(subject):
            return subject[:_SUBJECT_CAP]
    except Exception:
        pass  # any failure degrades to the fallback

    return fallback


def make_commit_message_provider(
    manifest: Manifest,
    operator_layer: Path,
    workdir: Path,
    fallback: str,
    engine_override: str | None = None,
) -> Callable[[str], str] | None:
    """Return a ``diff -> message`` callable, or None when generation is disabled.

    When ``manifest.generate_commit_messages`` is False the function returns None
    and callers use the static fallback message verbatim (byte-identical to the
    pre-feature behavior).

    When enabled, resolves the engine and the standard-tier model, then returns a
    closure that calls :func:`generate_commit_message` for each diff it receives.

    Args:
        manifest: The loaded Manifest (provides engine config and generate flag).
        operator_layer: Path to the ``.alc/`` directory.
        workdir: Working directory passed to the engine turn.
        fallback: Static message used when generation fails or is skipped.
        engine_override: If set, use this engine name instead of the default.

    Returns:
        A callable ``(diff: str) -> str``, or None when disabled.
    """
    if not manifest.generate_commit_messages:
        return None

    engine_name = engine_override or manifest.default_engine
    try:
        engine = resolve_engine(engine_name, manifest.engines)
    except Exception:
        return None  # unresolvable engine -> degrade to fallback path

    # Prefer the standard-tier model for the commit engine; fall back to None
    # (the engine chooses its own default).
    model: str | None = manifest.compute_tiers.get("standard", {}).get(engine_name)

    def _provider(diff: str) -> str:
        return generate_commit_message(
            diff=diff,
            engine=engine,
            model=model,
            workdir=workdir,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback=fallback,
        )

    return _provider
