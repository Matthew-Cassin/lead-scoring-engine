"""Tests for lead_scoring_engine.claude_scorer.

The Anthropic client is mocked throughout -- real end-to-end scoring
behavior against the live API was verified by hand while building this
module (see the README's Quick Start for the captured real output).
"""

from unittest.mock import MagicMock, patch

import anthropic
import pytest

from lead_scoring_engine.claude_scorer import ClaudeScorer
from lead_scoring_engine.models import Lead, LeadScoringError
from tests._fakes import FakeMessage


def _scorer_with_mock_client(cache_dir=None):
    with patch("lead_scoring_engine.claude_scorer.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        scorer = ClaudeScorer(api_key="test-key", cache_dir=cache_dir)
    return scorer, mock_client


def _lead(**overrides):
    fields = {
        "id": "lead-1",
        "raw_text": "...",
        "name": "Jane",
        "company": "Acme",
        "industry": "SaaS",
    }
    fields.update(overrides)
    return Lead(**fields)


class TestConstruction:
    def test_client_construction_failure_becomes_lead_scoring_error(self):
        with patch("lead_scoring_engine.claude_scorer.anthropic.Anthropic") as mock_cls:
            mock_cls.side_effect = anthropic.AnthropicError("bad config")
            with pytest.raises(LeadScoringError):
                ClaudeScorer(api_key="whatever")


class TestScoreLead:
    def test_success_parses_all_fields(self):
        scorer, mock_client = _scorer_with_mock_client()
        mock_client.messages.create.return_value = FakeMessage(
            '{"score": 85, "reasoning": "strong signals", '
            '"high_value": true, "follow_up_tactic": "call today"}'
        )
        result = scorer.score_lead(_lead())
        assert result.success is True
        assert result.score == 85
        assert result.high_value is True
        assert result.follow_up_tactic == "call today"

    def test_skips_api_call_when_nothing_to_score(self):
        scorer, mock_client = _scorer_with_mock_client()
        empty_lead = Lead(id="lead-1", raw_text="...")
        result = scorer.score_lead(empty_lead)
        assert result.success is False
        assert "Insufficient data" in result.error
        mock_client.messages.create.assert_not_called()

    def test_score_as_float_string_is_coerced_to_int(self):
        scorer, mock_client = _scorer_with_mock_client()
        mock_client.messages.create.return_value = FakeMessage(
            '{"score": "72.0", "reasoning": "ok", "high_value": false, "follow_up_tactic": "email"}'
        )
        result = scorer.score_lead(_lead())
        assert result.success is True
        assert result.score == 72
        assert isinstance(result.score, int)

    def test_out_of_range_score_is_a_failure(self):
        scorer, mock_client = _scorer_with_mock_client()
        mock_client.messages.create.return_value = FakeMessage(
            '{"score": 150, "reasoning": "ok", "high_value": false, "follow_up_tactic": "x"}'
        )
        result = scorer.score_lead(_lead())
        assert result.success is False
        assert "0-100" in result.error

    def test_non_numeric_score_is_a_failure(self):
        scorer, mock_client = _scorer_with_mock_client()
        mock_client.messages.create.return_value = FakeMessage(
            '{"score": "high", "reasoning": "ok", "high_value": false, "follow_up_tactic": "x"}'
        )
        result = scorer.score_lead(_lead())
        assert result.success is False

    def test_unparseable_response_is_a_failure_not_an_exception(self):
        scorer, mock_client = _scorer_with_mock_client()
        mock_client.messages.create.return_value = FakeMessage("not json")
        result = scorer.score_lead(_lead())
        assert result.success is False
        assert result.usage is not None

    def test_api_error_is_a_failure_not_an_exception(self):
        scorer, mock_client = _scorer_with_mock_client()
        mock_client.messages.create.side_effect = anthropic.APIConnectionError(request=MagicMock())
        result = scorer.score_lead(_lead())
        assert result.success is False

    def test_cache_hit_skips_the_api_call(self, tmp_path):
        scorer, mock_client = _scorer_with_mock_client(cache_dir=str(tmp_path))
        mock_client.messages.create.return_value = FakeMessage(
            '{"score": 60, "reasoning": "ok", "high_value": false, "follow_up_tactic": "email"}'
        )
        lead = _lead()
        first = scorer.score_lead(lead)
        assert first.from_cache is False
        second = scorer.score_lead(lead)
        assert second.from_cache is True
        assert second.score == 60
        assert mock_client.messages.create.call_count == 1

    def test_cache_key_depends_on_scoring_inputs_not_lead_id(self, tmp_path):
        scorer, mock_client = _scorer_with_mock_client(cache_dir=str(tmp_path))
        mock_client.messages.create.return_value = FakeMessage(
            '{"score": 60, "reasoning": "ok", "high_value": false, "follow_up_tactic": "email"}'
        )
        scorer.score_lead(_lead(id="lead-1"))
        second = scorer.score_lead(_lead(id="lead-2"))  # same name/company/industry, different id
        assert second.from_cache is True
        assert mock_client.messages.create.call_count == 1
