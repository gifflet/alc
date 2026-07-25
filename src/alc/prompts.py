# prompts.py — Uniform keyed prompt-override store for the Operator Layer.
#
# ANY `<prompts_dir>/<name>.md` resolves by that name — the filename IS the key.
# Two classes of prompt:
#   - RESERVED names — ALC's built-in hooks. Each has an embedded default in the
#     `_DEFAULT_PROMPTS` registry; an operator override file transparently
#     replaces the built-in.
#   - FREE names — the operator's own library. Any other `<name>.md`, referenced
#     from a Blueprint/Flow workflow via a `{{prompt:<name>}}` include.
#
# resolve_prompt(name) is a GENERAL keyed store: reserved names always resolve to
# a default when no file exists; free names resolve only from a file.
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from alc.models import Manifest

# ---------------------------------------------------------------------------
# Reserved prompt registry
# ---------------------------------------------------------------------------
#
# Each reserved name maps to (template, required_placeholders). The templates are
# the single source of truth for ALC's built-in behavioral prompts — the internal
# call sites resolve through this registry so an operator override transparently
# replaces the built-in. Templates that embed literal `{`/`}` (JSON examples,
# ```-fences) keep the `{{ }}` escaping the call sites' `.format()` requires.

# The JSON-array output contract shared by the Conductor directive and the
# `plan-contract` prompt — the SINGLE source of truth for the plan output format.
# It embeds literal braces in the JSON example, so it keeps the `{{ }}` escaping
# every `.format()` call site needs (one `.format()` renders single braces).
_PLAN_OUTPUT_CONTRACT = """\
Output ONLY a JSON array — no prose, no
markdown fences, no explanation. Each element must be an object with exactly
three keys:
  "kind": either "flow" or "specialist"
  "name": one of the names listed in the Catalog (exact match, case-sensitive)
  "task": a concise free-text task description for that unit

Example output:
[{{"kind": "flow", "name": "ship", "task": "implement the feature"}}]"""

_CONDUCTOR_DIRECTIVE_TEMPLATE = (
    """\
# ALC Conductor — Single Mandate

You are the ALC Conductor. Your mandate is to decompose the operator's goal into
independent units of work, assigning each to the best-matching target drawn
exclusively from the Catalog below. Prefer a Specialist for area-scoped work; use
a Flow for multi-stage pipelines.

## Goal

{goal}

## Catalog

{catalog_text}

## Instructions

Break the goal into independent parts. """
    + _PLAN_OUTPUT_CONTRACT
    + "\n"
)

# The `plan-contract` prompt — injected into a planner Specialist's directive for a
# `kind: plan` replenish so the plan output format is embedded by ALC (not left to
# blueprint prose). It names the valid targets ({catalog}) and shares the same
# JSON-array contract as the Conductor. Phrased for a planner that emits demands.
_PLAN_CONTRACT_TEMPLATE = (
    """\
# ALC Plan Output Contract (required — overrides any conflicting instruction)

Return a JSON array; each element is an object of the form
{{"kind":"flow","name":"<a catalog name, e.g. demand>","task":"<title>\\n\\n<details>"}}.
The valid target names are exactly those in the Catalog below.

## File declarations (REQUIRED) & dependencies

Every element MUST include ``"touches"``: a JSON array of the file paths (or globs) this
demand will CREATE or EDIT, as precisely as you can predict them (e.g.
``"touches":["src/services/ingest.js","src/routes/audios.js"]``). ALC uses these to
GUARANTEE safety: it AUTOMATICALLY serializes any two demands whose ``touches`` overlap
(the second runs after the first has merged, branching off the updated main — no
conflict) and runs demands with DISJOINT touches in parallel. Declare touches accurately;
a demand that omits them is treated conservatively (serialized after the others), which
is slower. You do NOT decide the parallelism — the core derives it from ``touches``.

You MAY additionally add ``"id":"<short-slug>"`` + ``"depends_on":["<id>",...]`` for a
LOGICAL dependency (B builds on A even when their files are disjoint). Every id in a
depends_on MUST match some item's id in THIS plan. Example:
[{{"id":"ingest","kind":"flow","name":"demand","task":"...","touches":["src/services/ingest.js"]}}, {{"kind":"flow","name":"demand","task":"...","touches":["src/services/ingest.js","src/routes/audios.js"],"depends_on":["ingest"]}}]

## Impact (optional)

When you have real evidence behind a plan item — e.g. issue reports, error volume, a
Knowledge File accumulating what users keep hitting — you MAY add
``"impact":{{"score":<number>,"rationale":"<why>"}}`` to that item. ``score`` is any
numeric scale you choose (ALC does not interpret it); ``rationale`` is a short,
evidence-based justification (e.g. "6 issue reports this week reference this flow").
Omit ``impact`` entirely when you have no such evidence — it is never required, and ALC
does not yet act on it (no automated signal intake, metric checks, or prioritization
from this field — that lands in a later phase).

## Catalog

{catalog}

## Format rules

"""
    + _PLAN_OUTPUT_CONTRACT
    + """

Additional hard requirements:
- The top level MUST be a BARE JSON array (never wrapped in an object such as
  {{"plan": [...]}}).
- Emit VALID JSON only: use standard escapes (\\n, \\", \\\\); NEVER emit \\' — a
  single quote inside a string is written literally as '.
- No prose, headings, or ``` fences around the array.
- The FIRST line of each "task" is a short, BARE imperative title that becomes the
  commit subject directly — do NOT prefix it with "Implement:", "Add:", "Feature:"
  or any label; put any details after a blank line.
"""
)

_CORRECTIVE_SUFFIX = "\n\nYour previous output was invalid: {err}. Output ONLY the JSON array."

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

# The repair addendum's framing. ALC pre-renders the per-check ```-fenced blocks
# into `{failures}` (each block starts with a leading newline); this template
# controls the surrounding text. Written as an explicit string so the exact
# whitespace (`\n\n---\n## Repair Required\nThe following …\n` + `{failures}`)
# reproduces the pre-refactor addendum byte-for-byte.
_REPAIR_TEMPLATE = (
    "\n\n---\n## Repair Required\n"
    "The following checks FAILED. Fix all issues and try again.\n"
    "{failures}"
)

# The `runtime-conventions` prompt — ALC appends this to a run's directive whenever it
# has injected a network port into the run's env (a worktree port allocation), so the
# agent binds ALC's assigned port instead of hardcoding one. Core-owned default (no
# placeholders); an operator override in the prompt store transparently replaces it.
# This is the behavioral-defaults guarantee: the port-isolation core feature is enforced
# by the core, not re-implemented in each project's qa Blueprint.
_RUNTIME_CONVENTIONS_TEMPLATE = """\
## Runtime conventions (required by ALC — overrides any conflicting instruction above)

This run is isolated and ALC has already assigned it a free network port, exported as the
environment variables `PORT` and `ALC_PORT` (identical values). When you start the app or any
server to validate it:
- Bind THAT assigned port — do NOT choose or hardcode one. Most apps read `$PORT` automatically;
  otherwise pass it explicitly (e.g. `--port "$PORT"`) or set it (`PORT="$PORT" <cmd>`). Never
  invent a fixed port like 3000/3099 — parallel runs share the host and a hardcoded port WILL
  collide with a sibling run.
- Make every request against `http://localhost:$PORT`, and confirm the app's own startup output
  reports that port before hitting it.
"""


# The `service-conventions` prompt — ALC appends this when the CORE owns the app
# lifecycle for a run (a Blueprint opts in and the Manifest declares a service).
# ALC has already started the app and exported its address as `$ALC_BASE_URL`, so
# the agent must NOT start it or pick a port — it only makes requests. Core-owned
# default (no placeholders); an operator override in the prompt store replaces it.
_SERVICE_CONVENTIONS_TEMPLATE = """\
## Service conventions (required by ALC — overrides any conflicting instruction above)

ALC has ALREADY started the application for this run and is managing its full lifecycle.
Its address is exported as the environment variable `$ALC_BASE_URL` (e.g. `http://127.0.0.1:<port>`).
- Do NOT start the app, launch a server, or choose/bind a port — ALC owns all of that. The app
  is up for the whole run and ALC tears it down afterward.
- Make EVERY request against `$ALC_BASE_URL` (e.g. `curl "$ALC_BASE_URL/…"`). Never hardcode a
  host or port and never assume `localhost:3000` — use `$ALC_BASE_URL` verbatim.
"""

# The `commit-message` prompt — ALC uses this to ask the engine to generate a
# Conventional Commits subject from the staged diff. Core-owned default; an operator
# override in the prompt store transparently replaces it.
# NOTE: {diff} is injected via str.replace, NOT .format(), so the diff's own braces
# never crash the injection. The frozenset still declares {diff} so the lint
# (validate_prompt_override) can verify an override preserves the placeholder.
_COMMIT_MESSAGE_TEMPLATE = """\
Generate exactly ONE line: a Conventional Commits subject for the staged diff below.

Rules:
- Format: <type>(<scope>): <description>  (scope is optional but recommended)
- type must be one of: feat, fix, chore, refactor, docs, test, ci, perf, build, style, revert
- Choose the type that best matches the actual change shown in the diff
- Use the imperative mood (e.g. "add", "fix", "remove"), not past tense
- Maximum 72 characters total
- No trailing period
- No body, no footer, no Co-Authored-By line
- No backticks, no quotes around the output
- Output ONLY the subject line — no explanation, no preamble

Staged diff:
{diff}"""


# The `onboard` prompt — ALC uses this for the OPT-IN `alc onboard --assist` layer.
# Given the checks the deterministic harvest already found plus the project's file
# tree, the engine proposes the checks the harvest MISSED. Harvest-first: the engine
# only ADDS to the gaps, it never replaces a harvested check, and it never proposes a
# product stage (stage stays operator-only). Core-owned default; an operator override
# in the prompt store transparently replaces it.
# NOTE: {signals} and {tree} are injected via str.replace, NOT .format(), so their
# content (which may contain literal braces) never crashes the injection. The output
# is described in prose (no literal-brace JSON example) so the template keeps ONLY the
# two placeholders and stays cleanly `.format()`-able if it is ever ejected/linted.
# The frozenset still declares both so the lint (validate_prompt_override) can verify
# an override preserves them.
_ONBOARD_TEMPLATE = """\
You are helping ALC adopt an unfamiliar project. ALC has already run a deterministic
HARVEST of the checks this project declares (package.json scripts, Makefile/justfile/
Taskfile targets, pre-commit, tox/nox). Your job is to fill ONLY the gaps that harvest
missed — never to repeat or replace what harvest already found.

Harvested check signals (what ALC already has):
{signals}

Project file tree:
{tree}

Output ONLY a JSON object — no prose, no explanation, no markdown code fences. The
object has exactly these three keys:

- "checks": a JSON array of the build/test/lint checks the harvest MISSED. Include a
  check ONLY when the tree gives real evidence for it and it is not already in the
  signals above. Each element is a JSON object with:
    "name": a short slug for the check (e.g. "test", "lint", "typecheck", "build")
    "command": a JSON array of argv tokens (e.g. the tokens of "cargo test") — OR
    "shell": a single shell one-liner string — set EXACTLY ONE of "command"/"shell"
    "rationale": one sentence on why this check applies, citing tree evidence
    "confidence": one of "high", "medium", "low"

- "blueprint_opt_ins": a JSON object mapping a blueprint name to the check_set name it
  should use. Use an empty object when you have nothing to add.

- "unknowns": a JSON array of short strings naming what you could NOT determine.

Do NOT propose, infer, or include a product stage anywhere in the output — the product
stage is the operator's decision alone.
"""


_DEFAULT_PROMPTS: dict[str, tuple[str, frozenset[str]]] = {
    "plan-contract": (_PLAN_CONTRACT_TEMPLATE, frozenset({"catalog"})),
    "conductor": (_CONDUCTOR_DIRECTIVE_TEMPLATE, frozenset({"goal", "catalog_text"})),
    "corrective": (_CORRECTIVE_SUFFIX, frozenset({"err"})),
    "learn": (
        _LEARN_DIRECTIVE_TEMPLATE,
        frozenset({"area", "current_knowledge", "task", "act_output"}),
    ),
    "repair": (_REPAIR_TEMPLATE, frozenset({"failures"})),
    "runtime-conventions": (_RUNTIME_CONVENTIONS_TEMPLATE, frozenset()),
    "service-conventions": (_SERVICE_CONVENTIONS_TEMPLATE, frozenset()),
    # {diff} is declared so override validation can check the placeholder is present;
    # the actual injection uses str.replace (not .format) to avoid brace-collision.
    "commit-message": (_COMMIT_MESSAGE_TEMPLATE, frozenset({"diff"})),
    # {signals} and {tree} are declared for override validation; the actual injection
    # uses str.replace (not .format) — see the note on _ONBOARD_TEMPLATE.
    "onboard": (_ONBOARD_TEMPLATE, frozenset({"signals", "tree"})),
}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _prompt_path(name: str, operator_layer: Path, manifest: Manifest) -> Path:
    """Return the on-disk path a prompt override for *name* would occupy."""
    return operator_layer.parent / manifest.prompts_dir / f"{name}.md"


def resolve_prompt(name: str, operator_layer: Path, manifest: Manifest) -> str:
    """Return the effective text of the prompt named *name*.

    Resolution order:
      1. An override file `<prompts_dir>/<name>.md`, if it exists — its text wins.
      2. The embedded default template for a reserved name.
      3. Otherwise raise KeyError (an unknown free name with no file).

    Args:
        name: The prompt key (a reserved name or a free name).
        operator_layer: Path to the ``.alc/`` directory.
        manifest: The loaded Manifest (provides prompts_dir).

    Returns:
        The prompt template/text.

    Raises:
        KeyError: If *name* is not reserved and no override file exists.
    """
    override = _prompt_path(name, operator_layer, manifest)
    if override.exists():
        return override.read_text()
    if name in _DEFAULT_PROMPTS:
        return _DEFAULT_PROMPTS[name][0]
    raise KeyError(
        f"No prompt named '{name}': it is not a reserved prompt and no "
        f"{override} file exists."
    )


def render_plan_contract(
    catalog_text: str, operator_layer: Path, manifest: Manifest
) -> str:
    """Render the `plan-contract` prompt with the catalog of valid targets.

    Resolves the reserved (or overridden) ``plan-contract`` template and fills in
    ``{catalog}``. Used by the ``kind: plan`` replenish to inject ALC's plan-output
    contract into the planner Specialist's directive.

    Args:
        catalog_text: The catalog of available Flows/Specialists (from build_catalog).
        operator_layer: Path to the ``.alc/`` directory.
        manifest: The loaded Manifest (provides prompts_dir).

    Returns:
        The rendered plan contract, ready to append as an Act output-contract section.
    """
    return resolve_prompt("plan-contract", operator_layer, manifest).format(
        catalog=catalog_text
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def validate_prompt_override(name: str, text: str) -> list[str]:
    """Return the required placeholders MISSING from an override's *text*.

    For a reserved name every required placeholder must appear as a literal
    `{placeholder}` substring (a missing one would break the built-in call site).
    A non-reserved (free) name has no required placeholders, so this returns [].

    Args:
        name: The prompt key the override is for.
        text: The override file's text.

    Returns:
        Sorted list of missing required placeholder names (empty = valid).
    """
    spec = _DEFAULT_PROMPTS.get(name)
    if spec is None:
        return []
    required = spec[1]
    present = set(_PLACEHOLDER_RE.findall(text))
    return sorted(required - present)


def override_format_error(name: str, text: str) -> str | None:
    """Return an error message if a reserved override can't be safely ``.format()``-ed.

    A reserved prompt is applied via ``.format(**placeholders)`` at its call site, so an
    override with a stray unescaped ``{`` (not a doubled ``{{`` and not one of the prompt's
    placeholders) would crash at runtime. Trial-format with dummy values to catch that at
    lint time — safe by construction. Returns None for a valid override or a free name.

    Args:
        name: The prompt key the override is for.
        text: The override file's text.

    Returns:
        A human-readable error message, or None when the text renders cleanly.
    """
    spec = _DEFAULT_PROMPTS.get(name)
    if spec is None:
        return None
    required = spec[1]
    try:
        text.format(**{ph: "" for ph in required})
    except (KeyError, IndexError, ValueError) as exc:
        return (
            f"{type(exc).__name__}: {exc}. An override may only use the placeholders "
            f"{sorted(required)}; double any other literal brace ({{ -> {{{{, }} -> }}}})."
        )
    return None


# ---------------------------------------------------------------------------
# Include expansion
# ---------------------------------------------------------------------------

_INCLUDE_RE = re.compile(r"\{\{prompt:([^}]+)\}\}")

# Maximum include nesting depth before expansion aborts (defence in depth beyond
# the cycle guard, which already catches self-referential loops).
_MAX_INCLUDE_DEPTH = 10


def expand_includes(text: str, operator_layer: Path, manifest: Manifest) -> str:
    """Recursively expand every `{{prompt:<name>}}` token in *text*.

    A resolved prompt that itself contains `{{prompt:<name>}}` tokens is expanded
    too, up to ``_MAX_INCLUDE_DEPTH`` levels. A cycle on the current expansion path
    (e.g. A -> B -> A) raises ``ValueError`` naming the cycle. Text with no
    `{{prompt:}}` token is returned unchanged and touches no filesystem.

    Args:
        text: The composed workflow/directive text.
        operator_layer: Path to the ``.alc/`` directory.
        manifest: The loaded Manifest (provides prompts_dir).

    Returns:
        The text with every include (transitively) replaced by its resolved prompt.

    Raises:
        ValueError: If a referenced prompt name does not resolve, a cycle is
            detected, or the nesting depth is exceeded (so lint/compose fail
            loudly rather than silently dropping content or looping forever).
    """

    def _expand(current: str, seen: tuple[str, ...], depth: int) -> str:
        if depth > _MAX_INCLUDE_DEPTH:
            raise ValueError(
                f"Prompt include nesting exceeded {_MAX_INCLUDE_DEPTH} levels "
                f"(path: {' -> '.join(seen)})."
            )

        def _replace(match: re.Match[str]) -> str:
            ref = match.group(1).strip()
            if ref in seen:
                cycle = " -> ".join((*seen, ref))
                raise ValueError(f"Cyclic prompt include detected: {cycle}.")
            try:
                resolved = resolve_prompt(ref, operator_layer, manifest)
            except KeyError as exc:
                raise ValueError(
                    f"Unresolved prompt include '{{{{prompt:{ref}}}}}': {exc}"
                ) from exc
            # Recurse so a free prompt that itself references others expands fully.
            return _expand(resolved, (*seen, ref), depth + 1)

        return _INCLUDE_RE.sub(_replace, current)

    return _expand(text, (), 0)


def include_refs(text: str) -> list[str]:
    """Return every prompt name referenced by a `{{prompt:<name>}}` token in *text*."""
    return [m.strip() for m in _INCLUDE_RE.findall(text)]


# ---------------------------------------------------------------------------
# Listing (CLI)
# ---------------------------------------------------------------------------


@dataclass
class PromptEntry:
    """One row in `alc prompts list`.

    ``kind`` is "reserved" or "free"; ``source`` is "default" or "override".
    """

    name: str
    kind: str      # "reserved" or "free"
    source: str    # "default" or "override"


def list_prompts(operator_layer: Path, manifest: Manifest) -> list[PromptEntry]:
    """List every reserved prompt and every discovered free prompt file.

    Reserved prompts are reported as overridden (a file exists) or default.
    Free prompts are any `<prompts_dir>/<name>.md` whose stem is not reserved.

    Args:
        operator_layer: Path to the ``.alc/`` directory.
        manifest: The loaded Manifest (provides prompts_dir).

    Returns:
        List of PromptEntry, reserved names first (sorted), then free names (sorted).
    """
    prompts_dir = operator_layer.parent / manifest.prompts_dir
    on_disk = {p.stem for p in prompts_dir.glob("*.md")} if prompts_dir.exists() else set()

    entries: list[PromptEntry] = []
    for name in sorted(_DEFAULT_PROMPTS):
        source = "override" if name in on_disk else "default"
        entries.append(PromptEntry(name=name, kind="reserved", source=source))
    for name in sorted(on_disk - set(_DEFAULT_PROMPTS)):
        entries.append(PromptEntry(name=name, kind="free", source="override"))
    return entries


def eject_prompt(
    name: str, operator_layer: Path, manifest: Manifest, force: bool = False
) -> Path:
    """Write a reserved prompt's embedded default to `<prompts_dir>/<name>.md`.

    Args:
        name: A reserved prompt name.
        operator_layer: Path to the ``.alc/`` directory.
        manifest: The loaded Manifest (provides prompts_dir).
        force: Overwrite an existing file when True; refuse otherwise.

    Returns:
        Path to the written file.

    Raises:
        KeyError: If *name* is not a reserved prompt.
        FileExistsError: If the target file exists and force is False.
    """
    if name not in _DEFAULT_PROMPTS:
        raise KeyError(
            f"'{name}' is not a reserved prompt; eject only works for reserved "
            f"names (available: {sorted(_DEFAULT_PROMPTS)})."
        )
    target = _prompt_path(name, operator_layer, manifest)
    if target.exists() and not force:
        raise FileExistsError(
            f"Prompt '{name}' already exists: {target}; pass --force to overwrite."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_DEFAULT_PROMPTS[name][0])
    return target
