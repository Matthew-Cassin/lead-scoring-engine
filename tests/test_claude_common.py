"""Tests for lead_scoring_engine._claude_common.

parse_json_response's fenced/commentary-tolerant parsing was written to
handle deviations from "return only JSON" actually seen from Claude
while empirically verifying claude_extractor.py/claude_scorer.py
against the real API (see those modules' docstrings) -- these cases
lock that behavior in.
"""

from lead_scoring_engine._claude_common import (
    ResponseCache,
    clean_field,
    parse_json_response,
    usage_from_response,
)
from tests._fakes import FakeMessage


class TestParseJsonResponse:
    def test_bare_json(self):
        assert parse_json_response('{"a": 1}') == {"a": 1}

    def test_fenced_with_json_tag(self):
        assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}

    def test_fenced_without_tag(self):
        assert parse_json_response('```\n{"a": 1}\n```') == {"a": 1}

    def test_leading_and_trailing_commentary(self):
        text = 'Sure, here is the JSON:\n{"a": 1}\nLet me know if you need more.'
        assert parse_json_response(text) == {"a": 1}

    def test_nested_braces_not_truncated(self):
        text = '{"a": {"b": 1, "c": [1, 2]}, "d": "text with a } brace"}'
        assert parse_json_response(text) == {"a": {"b": 1, "c": [1, 2]}, "d": "text with a } brace"}

    def test_no_json_object_returns_none(self):
        assert parse_json_response("no json here at all") is None

    def test_malformed_json_returns_none(self):
        assert parse_json_response('{"a": 1,}') is None

    def test_top_level_array_returns_none(self):
        # A well-formed JSON array is valid JSON but not the dict shape callers need.
        assert parse_json_response("[1, 2, 3]") is None


class TestCleanField:
    def test_none_stays_none(self):
        assert clean_field(None) is None

    def test_normal_string_passes_through_stripped(self):
        assert clean_field("  Acme Corp  ") == "Acme Corp"

    def test_null_like_strings_become_none(self):
        for value in ["null", "NULL", "n/a", "N/A", "none", "unknown", "not found", "", "   "]:
            assert clean_field(value) is None, f"{value!r} should normalize to None"

    def test_non_string_is_coerced(self):
        assert clean_field(42) == "42"


class TestUsageFromResponse:
    def test_known_model_computes_cost(self):
        response = FakeMessage("x", input_tokens=1_000_000, output_tokens=1_000_000)
        pricing = {"claude-sonnet-5": {"input": 2.0, "output": 10.0}}
        usage = usage_from_response(response, "claude-sonnet-5", pricing)
        assert usage.input_tokens == 1_000_000
        assert usage.output_tokens == 1_000_000
        assert usage.cost_usd == 12.0

    def test_unknown_model_reports_zero_cost(self):
        response = FakeMessage("x", input_tokens=1000, output_tokens=1000)
        usage = usage_from_response(response, "some-future-model", {})
        assert usage.cost_usd == 0.0
        assert usage.input_tokens == 1000


class TestResponseCache:
    def test_disabled_cache_always_misses_and_ignores_writes(self):
        cache = ResponseCache(None, kind="extract")
        key = cache.key_for("model", "v1", "input")
        cache.set(key, {"success": True})
        assert cache.get(key) is None

    def test_set_then_get_roundtrips(self, tmp_path):
        cache = ResponseCache(tmp_path, kind="extract")
        key = cache.key_for("model", "v1", "input text")
        cache.set(key, {"success": True, "name": "Jane"})
        assert cache.get(key) == {"success": True, "name": "Jane"}

    def test_miss_returns_none(self, tmp_path):
        cache = ResponseCache(tmp_path, kind="extract")
        assert cache.get("nonexistent-key") is None

    def test_different_kinds_do_not_collide(self, tmp_path):
        extract_cache = ResponseCache(tmp_path, kind="extract")
        score_cache = ResponseCache(tmp_path, kind="score")
        key = extract_cache.key_for("model", "v1", "same input")
        extract_cache.set(key, {"success": True, "which": "extract"})
        assert score_cache.get(key) is None

    def test_corrupted_cache_file_is_ignored_not_raised(self, tmp_path):
        cache = ResponseCache(tmp_path, kind="extract")
        key = cache.key_for("model", "v1", "input")
        (tmp_path / f"extract_{key}.json").write_text("{not valid json", encoding="utf-8")
        assert cache.get(key) is None

    def test_key_differs_by_model_prompt_version_and_input(self, tmp_path):
        cache = ResponseCache(tmp_path, kind="extract")
        base = cache.key_for("model-a", "v1", "text")
        assert base != cache.key_for("model-b", "v1", "text")
        assert base != cache.key_for("model-a", "v2", "text")
        assert base != cache.key_for("model-a", "v1", "different text")
