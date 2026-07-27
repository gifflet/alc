# test_authoring.py — Hermetic tests for the core unit scaffolds.
from __future__ import annotations

import yaml

from alc.authoring import scaffold_text


class TestScaffoldTextKnownKinds:
    def test_blueprint_fills_name_and_parses_as_front_matter(self) -> None:
        text = scaffold_text("blueprints", "review")
        assert text.startswith("---\n")
        assert "name: review" in text
        assert "## review workflow" in text

    def test_flow_fills_name(self) -> None:
        text = scaffold_text("flows", "ship")
        assert "name: ship" in text
        assert "blueprint: chore" in text

    def test_specialist_fills_name_in_all_placeholders(self) -> None:
        text = scaffold_text("specialists", "frontend")
        assert "name: frontend" in text
        assert "knowledge_path: .alc/knowledge/frontend.md" in text

    def test_loop_fills_name(self) -> None:
        text = scaffold_text("loops", "nightly")
        assert "name: nightly" in text
        assert "max_cycles: 10" in text

    def test_loop_scaffold_carries_a_usd_budget_cost_ceiling(self) -> None:
        # GAP 2: an authored loop must be safe-by-default too — max_cycles alone is
        # no cost ceiling for a real-engine loop, so the scaffold ships a $10 usd
        # cap alongside it. Parse the YAML so the block layout stays free.
        text = scaffold_text("loops", "nightly")
        stop = yaml.safe_load(text)["stop"]
        assert stop["budget"] == {"unit": "usd", "max": 10}

    def test_primer_fills_name_as_title(self) -> None:
        text = scaffold_text("primers", "house-style")
        assert text.startswith("# house-style\n")


class TestScaffoldTextUnknownKind:
    def test_returns_empty_string(self) -> None:
        assert scaffold_text("bogus", "anything") == ""
