"""Tests for lead_scoring_engine.claude_extractor.

The Anthropic client is mocked throughout -- real end-to-end extraction
behavior against the live API was verified by hand while building this
module (see the README's Quick Start for the captured real output),
including the exact response shape ``tests/_fakes.py`` mirrors.
"""

from unittest.mock import MagicMock, patch

import anthropic
import pytest

from lead_scoring_engine.claude_extractor import ClaudeExtractor
from lead_scoring_engine.models import LeadScoringError
from tests._fakes import FakeMessage


def _extractor_with_mock_client(cache_dir=None):
    """Build a ClaudeExtractor whose ``anthropic.Anthropic`` client is a MagicMock."""
    with patch("lead_scoring_engine.claude_extractor.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        extractor = ClaudeExtractor(api_key="test-key", cache_dir=cache_dir)
    return extractor, mock_client


class TestConstruction:
    def test_client_construction_failure_becomes_lead_scoring_error(self):
        with patch("lead_scoring_engine.claude_extractor.anthropic.Anthropic") as mock_cls:
            mock_cls.side_effect = anthropic.AnthropicError("bad config")
            with pytest.raises(LeadScoringError):
                ClaudeExtractor(api_key="whatever")


class TestExtractLeadFields:
    def test_success_parses_all_fields(self):
        extractor, mock_client = _extractor_with_mock_client()
        mock_client.messages.create.return_value = FakeMessage(
            '{"name": "Jane Doe", "email": "jane@x.com", "phone": "555-0100", '
            '"company": "Acme", "industry": "SaaS", "intent_signals": "wants a demo"}'
        )
        result = extractor.extract_lead_fields("Jane Doe, jane@x.com, wants a demo")
        assert result.success is True
        assert result.name == "Jane Doe"
        assert result.email == "jane@x.com"
        assert result.company == "Acme"
        assert result.usage.input_tokens == 100
        assert result.from_cache is False

    def test_null_like_fields_are_normalized_to_none(self):
        extractor, mock_client = _extractor_with_mock_client()
        mock_client.messages.create.return_value = FakeMessage(
            '{"name": "Bob", "email": null, "phone": "N/A", '
            '"company": "unknown", "industry": null, "intent_signals": null}'
        )
        result = extractor.extract_lead_fields("just a name: Bob")
        assert result.success is True
        assert result.email is None
        assert result.phone is None
        assert result.company is None

    def test_response_wrapped_in_markdown_fence_still_parses(self):
        extractor, mock_client = _extractor_with_mock_client()
        mock_client.messages.create.return_value = FakeMessage(
            '```json\n{"name": "Bob", "email": null, "phone": null, '
            '"company": null, "industry": null, "intent_signals": null}\n```'
        )
        result = extractor.extract_lead_fields("Bob")
        assert result.success is True
        assert result.name == "Bob"

    def test_unparseable_response_is_a_failure_not_an_exception(self):
        extractor, mock_client = _extractor_with_mock_client()
        mock_client.messages.create.return_value = FakeMessage("not json at all")
        result = extractor.extract_lead_fields("some lead")
        assert result.success is False
        assert result.error is not None
        assert result.usage is not None  # the call still happened and cost tokens

    def test_api_error_is_a_failure_not_an_exception(self):
        extractor, mock_client = _extractor_with_mock_client()
        mock_client.messages.create.side_effect = anthropic.APIConnectionError(
            request=MagicMock()
        )
        result = extractor.extract_lead_fields("some lead")
        assert result.success is False
        assert result.usage is None

    def test_wrong_type_raises_lead_scoring_error(self):
        extractor, _ = _extractor_with_mock_client()
        with pytest.raises(LeadScoringError):
            extractor.extract_lead_fields(12345)

    def test_cache_hit_skips_the_api_call(self, tmp_path):
        extractor, mock_client = _extractor_with_mock_client(cache_dir=str(tmp_path))
        mock_client.messages.create.return_value = FakeMessage(
            '{"name": "Bob", "email": null, "phone": null, '
            '"company": null, "industry": null, "intent_signals": null}'
        )
        first = extractor.extract_lead_fields("Bob's lead text")
        assert first.from_cache is False
        assert mock_client.messages.create.call_count == 1

        second = extractor.extract_lead_fields("Bob's lead text")
        assert second.from_cache is True
        assert second.name == "Bob"
        assert mock_client.messages.create.call_count == 1  # unchanged -- no second call

    def test_failed_call_is_never_cached(self, tmp_path):
        extractor, mock_client = _extractor_with_mock_client(cache_dir=str(tmp_path))
        mock_client.messages.create.return_value = FakeMessage("not json")
        extractor.extract_lead_fields("some lead")
        extractor.extract_lead_fields("some lead")
        assert mock_client.messages.create.call_count == 2  # retried the API, not served from cache
