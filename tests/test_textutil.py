# Tests for the stdlib-only text helpers in `alc.textutil`.
from __future__ import annotations

from alc.textutil import extract_json


class TestExtractJson:
    """`extract_json` recovers a JSON value from raw model output that may be
    fenced or prose-wrapped, and never raises — it returns the value or None."""

    def test_bare_object(self) -> None:
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_bare_array(self) -> None:
        assert extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_object_inside_json_fence(self) -> None:
        text = '```json\n{"a": 1, "b": "two"}\n```'
        assert extract_json(text) == {"a": 1, "b": "two"}

    def test_array_inside_json_fence(self) -> None:
        text = '```json\n[1, 2, 3]\n```'
        assert extract_json(text) == [1, 2, 3]

    def test_object_with_surrounding_prose(self) -> None:
        text = 'Here is the report:\n{"status": "ok"}\nThanks!'
        assert extract_json(text) == {"status": "ok"}

    def test_array_with_surrounding_prose(self) -> None:
        text = 'Sure, here you go: ["x", "y"] — done.'
        assert extract_json(text) == ["x", "y"]

    def test_object_with_nested_array_returns_the_object(self) -> None:
        # The outer `{` opens before the inner `[`, so the object wins.
        text = 'Report:\n{"symbols": ["foo", "bar"]}\nend'
        assert extract_json(text) == {"symbols": ["foo", "bar"]}

    def test_total_garbage_returns_none(self) -> None:
        assert extract_json("just some words, no json here") is None

    def test_empty_string_returns_none(self) -> None:
        assert extract_json("") is None

    def test_non_str_input_returns_none(self) -> None:
        assert extract_json(None) is None

    def test_malformed_but_bracketed_text_returns_none(self) -> None:
        assert extract_json("{not: valid, json}") is None
