# test_prompts.py — Hermetic tests for the keyed prompt-override store.
# Covers resolve_prompt, validate_prompt_override, expand_includes, list/eject,
# the byte-identical defaults, and lint's prompt rules. No real engine is called.
from __future__ import annotations

from pathlib import Path

import pytest

from alc.engine import Capabilities, EngineResult
from alc.intake import load_manifest
from alc.prompts import (
    _DEFAULT_PROMPTS,
    eject_prompt,
    expand_includes,
    list_prompts,
    override_format_error,
    render_plan_contract,
    resolve_prompt,
    validate_prompt_override,
)


class _RecordingEngine:
    """Engine that records the last directive it received (byte-identity checks)."""

    name = "mock"

    def __init__(self, output: str = "[mock] applied") -> None:
        self.seen_directive: str | None = None
        self._output = output

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request):
        self.seen_directive = request.directive
        return EngineResult(ok=True, output_text=self._output)


def _write_prompt(operator_layer: Path, name: str, text: str) -> None:
    """Write a prompt override file into the Operator Layer's prompts_dir."""
    prompts_dir = operator_layer / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    (prompts_dir / f"{name}.md").write_text(text)


# ---------------------------------------------------------------------------
# resolve_prompt
# ---------------------------------------------------------------------------


class TestResolvePrompt:
    def test_reserved_default_when_no_file(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        text = resolve_prompt("conductor", operator_layer, manifest)
        assert text == _DEFAULT_PROMPTS["conductor"][0]

    def test_override_file_wins(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_prompt(operator_layer, "conductor", "MY OVERRIDE {goal} {catalog_text}")
        text = resolve_prompt("conductor", operator_layer, manifest)
        assert text == "MY OVERRIDE {goal} {catalog_text}"

    def test_free_name_from_file(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_prompt(operator_layer, "my-free", "custom prompt body")
        assert resolve_prompt("my-free", operator_layer, manifest) == "custom prompt body"

    def test_unknown_free_name_raises_keyerror(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        with pytest.raises(KeyError):
            resolve_prompt("does-not-exist", operator_layer, manifest)


# ---------------------------------------------------------------------------
# Reserved defaults render with their required placeholders
# ---------------------------------------------------------------------------


class TestReservedDefaultsRender:
    def test_every_default_formats_with_its_placeholders(self) -> None:
        # Every reserved default must .format(**placeholders) without KeyError or
        # IndexError — this guards the {{ }} escaping of embedded JSON/fences.
        for name, (template, required) in _DEFAULT_PROMPTS.items():
            kwargs = {ph: f"<{ph}>" for ph in required}
            rendered = template.format(**kwargs)
            assert isinstance(rendered, str)
            for ph in required:
                assert f"<{ph}>" in rendered


# ---------------------------------------------------------------------------
# plan-contract (Part A)
# ---------------------------------------------------------------------------


class TestPlanContract:
    def test_is_reserved(self) -> None:
        assert "plan-contract" in _DEFAULT_PROMPTS
        assert _DEFAULT_PROMPTS["plan-contract"][1] == frozenset({"catalog"})

    def test_resolves_and_renders_with_catalog(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        rendered = render_plan_contract("- demand (flow): work", operator_layer, manifest)
        # The catalog substitution landed and the placeholder is gone.
        assert "- demand (flow): work" in rendered
        assert "{catalog}" not in rendered

    def test_states_key_format_rules(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        rendered = render_plan_contract("(catalog)", operator_layer, manifest)
        # It names the JSON-array contract, forbids \' and object-wrapping.
        assert "JSON array" in rendered
        assert "NEVER emit \\'" in rendered
        assert "BARE JSON array" in rendered
        assert "never wrapped in an object" in rendered
        # The title must be a bare imperative — no "Implement:"-style prefix.
        assert "BARE imperative title" in rendered
        assert 'do NOT prefix it with "Implement:"' in rendered
        # The three-key example survived one .format() as single braces.
        assert '{"kind": "flow", "name": "ship", "task": "implement the feature"}' in rendered

    def test_override_wins(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_prompt(operator_layer, "plan-contract", "MY CONTRACT {catalog}")
        assert render_plan_contract("CAT", operator_layer, manifest) == "MY CONTRACT CAT"


# ---------------------------------------------------------------------------
# validate_prompt_override
# ---------------------------------------------------------------------------


class TestValidatePromptOverride:
    def test_missing_required_placeholder_reported(self) -> None:
        # A conductor override without {catalog_text} is invalid.
        missing = validate_prompt_override("conductor", "only has {goal}")
        assert missing == ["catalog_text"]

    def test_complete_override_returns_empty(self) -> None:
        text = "{goal} then {catalog_text}"
        assert validate_prompt_override("conductor", text) == []

    def test_free_name_has_no_requirements(self) -> None:
        assert validate_prompt_override("my-free", "no placeholders at all") == []


class TestOverrideFormatError:
    def test_valid_override_renders(self) -> None:
        assert override_format_error("conductor", "{goal} {catalog_text}") is None

    def test_default_renders(self) -> None:
        # Every reserved default must be safely formattable (guards the {{ }} escaping).
        for name, (template, _req) in _DEFAULT_PROMPTS.items():
            assert override_format_error(name, template) is None, name

    def test_stray_unescaped_brace_reported(self) -> None:
        # A stray {oops} not in the required set would crash the call site's .format().
        err = override_format_error("conductor", "{goal} {catalog_text} {oops}")
        assert err is not None

    def test_free_name_never_errors(self) -> None:
        assert override_format_error("my-free", "anything {with} braces") is None


# ---------------------------------------------------------------------------
# expand_includes
# ---------------------------------------------------------------------------


class TestExpandIncludes:
    def test_free_include_expands_to_file_text(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_prompt(operator_layer, "my-free", "FREE BODY")
        result = expand_includes("before {{prompt:my-free}} after", operator_layer, manifest)
        assert result == "before FREE BODY after"

    def test_unknown_include_raises_value_error(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        with pytest.raises(ValueError, match="nope"):
            expand_includes("{{prompt:nope}}", operator_layer, manifest)

    def test_text_without_tokens_unchanged(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        text = "plain workflow with no includes"
        assert expand_includes(text, operator_layer, manifest) == text

    def test_recursive_include_expands_nested(self, operator_layer: Path) -> None:
        # An include token inside included text is expanded too (recursive).
        manifest = load_manifest(operator_layer)
        _write_prompt(operator_layer, "outer", "OUTER {{prompt:inner}}")
        _write_prompt(operator_layer, "inner", "INNER")
        result = expand_includes("{{prompt:outer}}", operator_layer, manifest)
        assert result == "OUTER INNER"

    def test_cycle_raises_value_error(self, operator_layer: Path) -> None:
        # A -> B -> A must be detected and named, not loop forever.
        manifest = load_manifest(operator_layer)
        _write_prompt(operator_layer, "a", "A {{prompt:b}}")
        _write_prompt(operator_layer, "b", "B {{prompt:a}}")
        with pytest.raises(ValueError, match="Cyclic prompt include"):
            expand_includes("{{prompt:a}}", operator_layer, manifest)


# ---------------------------------------------------------------------------
# list_prompts / eject_prompt
# ---------------------------------------------------------------------------


class TestListPrompts:
    def test_reflects_default_and_override(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_prompt(operator_layer, "conductor", "{goal} {catalog_text}")
        _write_prompt(operator_layer, "my-free", "free body")

        entries = {e.name: e for e in list_prompts(operator_layer, manifest)}
        assert entries["conductor"].kind == "reserved"
        assert entries["conductor"].source == "override"
        # A reserved prompt with no file is a default.
        assert entries["learn"].source == "default"
        # The free file is discovered.
        assert entries["my-free"].kind == "free"

    def test_no_prompts_dir_lists_reserved_defaults(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        entries = list_prompts(operator_layer, manifest)
        names = {e.name for e in entries}
        assert names == set(_DEFAULT_PROMPTS)
        assert all(e.source == "default" for e in entries)


class TestEjectPrompt:
    def test_writes_default(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        path = eject_prompt("conductor", operator_layer, manifest)
        assert path.exists()
        assert path.read_text() == _DEFAULT_PROMPTS["conductor"][0]

    def test_refuses_to_clobber_without_force(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        eject_prompt("conductor", operator_layer, manifest)
        with pytest.raises(FileExistsError):
            eject_prompt("conductor", operator_layer, manifest)

    def test_force_overwrites(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_prompt(operator_layer, "conductor", "stale")
        path = eject_prompt("conductor", operator_layer, manifest, force=True)
        assert path.read_text() == _DEFAULT_PROMPTS["conductor"][0]

    def test_unknown_name_raises_keyerror(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        with pytest.raises(KeyError):
            eject_prompt("not-reserved", operator_layer, manifest)


# ---------------------------------------------------------------------------
# Byte-identity: reserved paths are unchanged with no override present
# ---------------------------------------------------------------------------


class TestConductorByteIdentity:
    def test_directive_matches_default_template(self, operator_layer: Path) -> None:
        from alc.conduct import conduct

        manifest = load_manifest(operator_layer)
        engine = _RecordingEngine(output='[{"kind":"flow","name":"ship","task":"x"}]')

        import alc.engines.registry as registry

        orig = registry.resolve_engine
        registry.resolve_engine = lambda name, engines: engine
        try:
            conduct(
                manifest=manifest,
                operator_layer=operator_layer,
                goal="do the thing",
                engine_override="mock",
            )
        finally:
            registry.resolve_engine = orig

        expected = _DEFAULT_PROMPTS["conductor"][0].format(
            goal="do the thing",
            catalog_text=(
                "- ship (flow): Plan a change, then implement it — each stage its "
                "own mandate. (stages: plan, chore)"
            ),
        )
        assert engine.seen_directive == expected

    def test_directive_anchored_to_literal_bytes(self, operator_layer: Path) -> None:
        # Anchor the recomposed `<prefix> + _PLAN_OUTPUT_CONTRACT + "\n"` seam and tail
        # to LITERAL bytes, so a future edit cannot silently drift a newline at the
        # concatenation (the equality test above uses the live constant — self-referential).
        manifest = load_manifest(operator_layer)
        rendered = _DEFAULT_PROMPTS["conductor"][0].format(goal="G", catalog_text="C")
        # The seam between the prefix and the shared contract, byte-for-byte.
        assert (
            "## Instructions\n\nBreak the goal into independent parts. "
            "Output ONLY a JSON array — no prose, no\nmarkdown fences" in rendered
        )
        # The tail: the JSON example (single braces after one .format()) + trailing "\n".
        assert rendered.endswith(
            '[{"kind": "flow", "name": "ship", "task": "implement the feature"}]\n'
        )

    def test_override_directive_uses_override(self, operator_layer: Path) -> None:
        from alc.conduct import conduct

        _write_prompt(operator_layer, "conductor", "OVERRIDE goal={goal} cat={catalog_text}")
        manifest = load_manifest(operator_layer)
        engine = _RecordingEngine(output='[{"kind":"flow","name":"ship","task":"x"}]')

        import alc.engines.registry as registry

        orig = registry.resolve_engine
        registry.resolve_engine = lambda name, engines: engine
        try:
            conduct(
                manifest=manifest,
                operator_layer=operator_layer,
                goal="do the thing",
                engine_override="mock",
            )
        finally:
            registry.resolve_engine = orig

        assert engine.seen_directive.startswith("OVERRIDE goal=do the thing cat=")


class TestLearnByteIdentity:
    def test_learn_directive_matches_default_template(self) -> None:
        from alc.specialist import learn

        engine = _RecordingEngine(output="NEW")
        learn(engine, None, "OLD", "the db layer", "document it", "did stuff")

        expected = _DEFAULT_PROMPTS["learn"][0].format(
            area="the db layer",
            current_knowledge="OLD",
            task="document it",
            act_output="did stuff",
        )
        assert engine.seen_directive == expected

    def test_learn_directive_uses_override(self, operator_layer: Path) -> None:
        from alc.models import Specialist
        from alc.specialist import run_specialist

        _write_prompt(operator_layer, "learn", "LEARN-OVERRIDE {area} {current_knowledge} {task} {act_output}")
        specialists_dir = operator_layer / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        import yaml

        data = {
            "name": "db",
            "area": "the db layer",
            "blueprint": "chore",
            "knowledge_path": ".alc/specialists/db.knowledge.md",
        }
        (specialists_dir / "db.yaml").write_text(yaml.safe_dump(data))
        manifest = load_manifest(operator_layer)

        # Record the Learn directive by monkeypatching the engine the specialist uses.
        engine = _RecordingEngine(output="UPDATED")
        import alc.engines.registry as registry

        orig = registry.resolve_engine
        registry.resolve_engine = lambda name, engines: engine
        try:
            run_specialist(
                manifest=manifest,
                operator_layer=operator_layer,
                specialist=Specialist.model_validate(data),
                task="document",
                engine_override="mock",
            )
        finally:
            registry.resolve_engine = orig

        # The last directive the engine saw is the Learn turn (Act ran first).
        assert engine.seen_directive.startswith("LEARN-OVERRIDE the db layer")


class TestRepairByteIdentity:
    def test_build_failure_section_matches_pre_refactor(self) -> None:
        from alc.assurance import AssuranceLoop
        from alc.engines.mock import MockEngine
        from alc.verifier import Verifier

        class _CR:
            def __init__(self, name: str, output: str) -> None:
                self.name = name
                self.output = output

        failed = [_CR("pytest", "E assert 1 == 2\n"), _CR("ruff", "x.py F401\n")]
        loop = AssuranceLoop(engine=MockEngine(), verifier=Verifier())

        def _pre_refactor(failed_checks) -> str:
            lines = [
                "\n\n---\n## Repair Required\n",
                "The following checks FAILED. Fix all issues and try again.\n",
            ]
            for cr in failed_checks:
                lines.append(f"\n### Check: {cr.name}\n```\n{cr.output.strip()}\n```\n")
            return "".join(lines)

        assert loop._build_failure_section(failed) == _pre_refactor(failed)

    def test_repair_override_is_used(self) -> None:
        from alc.assurance import AssuranceLoop
        from alc.engines.mock import MockEngine
        from alc.verifier import Verifier

        class _CR:
            def __init__(self, name: str, output: str) -> None:
                self.name = name
                self.output = output

        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=Verifier(),
            repair_template="REPAIR-OVERRIDE\n{failures}",
        )
        section = loop._build_failure_section([_CR("c", "boom")])
        assert section.startswith("REPAIR-OVERRIDE\n")
        assert "### Check: c" in section


def test_prompts_list_json_output(operator_layer, monkeypatch, capsys) -> None:
    """`alc prompts list --json` emits the entries via the shared emit_json helper."""
    import argparse
    import json as _json

    from alc.cli import cmd_prompts

    monkeypatch.chdir(operator_layer.parent)
    rc = cmd_prompts(
        argparse.Namespace(action="list", name=None, force=False, json=True)
    )
    assert rc == 0
    data = _json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    names = {e["name"] for e in data}
    assert "conductor" in names  # a reserved prompt is present
    assert all({"name", "kind", "source"} <= set(e) for e in data)
