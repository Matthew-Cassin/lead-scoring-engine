"""Extract structured lead fields from raw text using the Claude API."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import anthropic

from . import config
from ._claude_common import ResponseCache, clean_field, parse_json_response, usage_from_response
from .logger import get_logger
from .models import ExtractionResult, LeadScoringError

logger = get_logger("claude_extractor")

__all__ = ["ClaudeExtractor"]

# Bumped whenever the prompt text changes, so cached responses from an
# older prompt version are never served under a new one.
_PROMPT_VERSION = "v1"

_EXTRACTION_PROMPT_TEMPLATE = """You are a data extraction expert. Extract the following \
fields from this lead data:

- Full Name
- Email Address
- Phone Number
- Company Name
- Industry/Vertical
- Any buying signals or intent indicators

Lead Data:
{raw_lead_text}

Return ONLY valid JSON with these exact keys (null if not found), and nothing else -- \
no commentary, no markdown code fence:
{{
  "name": "...",
  "email": "...",
  "phone": "...",
  "company": "...",
  "industry": "...",
  "intent_signals": "..."
}}"""


class ClaudeExtractor:
    """Extracts structured lead fields from raw, unstructured text via Claude.

    Args:
        api_key: Anthropic API key. Falls back to the ``ANTHROPIC_API_KEY``
            environment variable when omitted (the SDK's own default
            behavior).
        model: Claude model ID to call. Defaults to
            :data:`~lead_scoring_engine.config.CLAUDE_MODEL`.
        cache_dir: Directory for the on-disk response cache, or ``None``
            to disable caching. Defaults to
            :data:`~lead_scoring_engine.config.CACHE_DIR`.
        max_retries: Passed straight through to the underlying
            ``anthropic.Anthropic`` client, which retries rate limits,
            timeouts, and 5xx/overloaded responses automatically with
            backoff. Defaults to
            :data:`~lead_scoring_engine.config.MAX_RETRIES`.

    Raises:
        LeadScoringError: If the Anthropic client can't be constructed
            (e.g. no API key available anywhere).

    Example:
        >>> extractor = ClaudeExtractor(cache_dir=None)  # doctest: +SKIP
        >>> result = extractor.extract_lead_fields(  # doctest: +SKIP
        ...     "John Doe from Acme Corp, john@acme.com, looking for automation"
        ... )
        >>> result.success, result.company  # doctest: +SKIP
        (True, 'Acme Corp')
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
        self._cache = ResponseCache(Path(cache_dir) if cache_dir else None, kind="extract")

    def extract_lead_fields(self, raw_lead_text: str) -> ExtractionResult:
        """Extract name/email/phone/company/industry/intent from raw lead text.

        Args:
            raw_lead_text: Unstructured lead data -- an email, a form
                submission, scraped page text, anything with a person's
                or company's contact info embedded in prose.

        Returns:
            An :class:`~lead_scoring_engine.models.ExtractionResult`.
            ``success=False`` covers both an API call that ultimately
            failed (after the client's own retries) and a response that
            couldn't be parsed as the expected JSON shape -- never
            raised as an exception, so one bad lead never stops a batch.

        Raises:
            LeadScoringError: If ``raw_lead_text`` is not a string.
        """
        if not isinstance(raw_lead_text, str):
            raise LeadScoringError(
                f"raw_lead_text must be a string, got {type(raw_lead_text).__name__}"
            )

        cache_key = self._cache.key_for(self.model, _PROMPT_VERSION, raw_lead_text)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("Extraction cache hit")
            return ExtractionResult(**cached, from_cache=True)

        prompt = _EXTRACTION_PROMPT_TEMPLATE.format(raw_lead_text=raw_lead_text)
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=config.CLAUDE_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AnthropicError as exc:
            logger.warning("Extraction API call failed: %s", exc)
            return ExtractionResult(success=False, error=str(exc))

        usage = usage_from_response(response, self.model, config.PRICING_PER_MTOK_USD)
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        parsed = parse_json_response(text)
        if parsed is None:
            logger.warning("Extraction response was not valid JSON: %.200r", text)
            return ExtractionResult(success=False, error="Response was not valid JSON", usage=usage)

        fields = {
            "name": clean_field(parsed.get("name")),
            "email": clean_field(parsed.get("email")),
            "phone": clean_field(parsed.get("phone")),
            "company": clean_field(parsed.get("company")),
            "industry": clean_field(parsed.get("industry")),
            "intent_signals": clean_field(parsed.get("intent_signals")),
        }
        self._cache.set(cache_key, {"success": True, **fields})
        logger.info("Extraction succeeded")
        return ExtractionResult(success=True, usage=usage, **fields)
