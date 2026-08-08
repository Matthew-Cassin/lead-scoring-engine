"""Score a lead's likelihood to convert using the Claude API."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import anthropic

from . import config
from ._claude_common import ResponseCache, clean_field, parse_json_response, usage_from_response
from .logger import get_logger
from .models import Lead, LeadScoringError, ScoreResult

logger = get_logger("claude_scorer")

__all__ = ["ClaudeScorer"]

_PROMPT_VERSION = "v1"

_SCORING_PROMPT_TEMPLATE = """You are a B2B sales expert. Score this lead 0-100 on \
likelihood to convert within 30 days.

Lead Profile:
- Name: {name}
- Company: {company}
- Industry: {industry}
- Intent Signals: {intent_signals}

Consider:
- Industry demand (SaaS/Tech higher than others)
- Specificity of intent signals
- Company size indicators
- Urgency language

Return ONLY valid JSON, and nothing else -- no commentary, no markdown code fence:
{{
  "score": <0-100>,
  "reasoning": "Brief explanation of score",
  "high_value": <true/false>,
  "follow_up_tactic": "Suggested approach"
}}"""

_MISSING = "(not provided)"


class ClaudeScorer:
    """Scores a lead's conversion likelihood via Claude.

    Args:
        api_key: Anthropic API key. Falls back to the ``ANTHROPIC_API_KEY``
            environment variable when omitted.
        model: Claude model ID to call. Defaults to
            :data:`~lead_scoring_engine.config.CLAUDE_MODEL`.
        cache_dir: Directory for the on-disk response cache, or ``None``
            to disable caching. Defaults to
            :data:`~lead_scoring_engine.config.CACHE_DIR`.
        max_retries: Passed straight through to the underlying
            ``anthropic.Anthropic`` client. Defaults to
            :data:`~lead_scoring_engine.config.MAX_RETRIES`.

    Raises:
        LeadScoringError: If the Anthropic client can't be constructed.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        cache_dir: Optional[str] = config.CACHE_DIR,
        max_retries: Optional[int] = None,
    ) -> None:
        try:
            self._client = anthropic.Anthropic(
                api_key=api_key, max_retries=max_retries or config.MAX_RETRIES
            )
        except anthropic.AnthropicError as exc:
            raise LeadScoringError(f"Could not initialize the Claude API client: {exc}") from exc

        self.model = model or config.CLAUDE_MODEL
        self._cache = ResponseCache(Path(cache_dir) if cache_dir else None, kind="score")

    def score_lead(self, lead: Lead) -> ScoreResult:
        """Score one lead's likelihood to convert within 30 days.

        Args:
            lead: A :class:`~lead_scoring_engine.models.Lead`, typically
                one that has already gone through extraction. Only
                ``name``, ``company``, ``industry``, and
                ``intent_signals`` are used -- contact fields play no
                part in the score itself.

        Returns:
            A :class:`~lead_scoring_engine.models.ScoreResult`.
            ``success=False`` when there's nothing worth scoring (every
            input field is missing -- no API call is made in that case,
            since there's nothing for Claude to reason about), when the
            API call ultimately fails, or when the response can't be
            parsed. Never raised as an exception.
        """
        if not any([lead.name, lead.company, lead.industry, lead.intent_signals]):
            logger.info("Skipping score: no name, company, industry, or intent signals")
            return ScoreResult(
                success=False,
                error="Insufficient data to score: no name, company, industry, "
                "or intent signals were extracted for this lead",
            )

        prompt_key_text = "|".join(
            [lead.name or "", lead.company or "", lead.industry or "", lead.intent_signals or ""]
        )
        cache_key = self._cache.key_for(self.model, _PROMPT_VERSION, prompt_key_text)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("Scoring cache hit")
            return ScoreResult(**cached, from_cache=True)

        prompt = _SCORING_PROMPT_TEMPLATE.format(
            name=lead.name or _MISSING,
            company=lead.company or _MISSING,
            industry=lead.industry or _MISSING,
            intent_signals=lead.intent_signals or _MISSING,
        )
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=config.CLAUDE_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AnthropicError as exc:
            logger.warning("Scoring API call failed: %s", exc)
            return ScoreResult(success=False, error=str(exc))

        usage = usage_from_response(response, self.model, config.PRICING_PER_MTOK_USD)
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        parsed = parse_json_response(text)
        if parsed is None:
            logger.warning("Scoring response was not valid JSON: %.200r", text)
            return ScoreResult(success=False, error="Response was not valid JSON", usage=usage)

        score = self._coerce_score(parsed.get("score"))
        if score is None:
            logger.warning("Scoring response had an unusable score value: %r", parsed.get("score"))
            return ScoreResult(
                success=False, error="Response did not contain a usable 0-100 score", usage=usage
            )

        fields = {
            "score": score,
            "reasoning": clean_field(parsed.get("reasoning")),
            "high_value": bool(parsed.get("high_value")) if "high_value" in parsed else None,
            "follow_up_tactic": clean_field(parsed.get("follow_up_tactic")),
        }
        self._cache.set(cache_key, {"success": True, **fields})
        logger.info("Scoring succeeded: %d", score)
        return ScoreResult(success=True, usage=usage, **fields)

    @staticmethod
    def _coerce_score(raw_score: object) -> Optional[int]:
        """Clamp/validate Claude's reported score into a usable 0-100 int.

        Handles Claude returning the score as a float or a numeric
        string, both seen in practice, and rejects anything outside
        0-100 or not numeric at all rather than silently clamping bad
        output into a misleadingly plausible-looking number.
        """
        try:
            value = int(round(float(raw_score)))
        except (TypeError, ValueError):
            return None
        return value if 0 <= value <= 100 else None
