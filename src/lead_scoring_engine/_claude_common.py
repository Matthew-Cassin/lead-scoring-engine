"""Private helpers shared by claude_extractor.py and claude_scorer.py.

Not part of the public API (note the leading underscore) -- both of
those modules need the same on-disk response cache, JSON-from-response
parsing, and cost accounting, and keeping one implementation avoids
fixing the same real-world Claude-response quirk (see
``parse_json_response``) in two places.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

from .logger import get_logger
from .models import ApiUsage

logger = get_logger("_claude_common")

# Values Claude sometimes returns *as the string content* of a "not
# found" field despite being told to use JSON null -- found by testing
# real extractions, not guessed. Normalized to Python None so callers
# never have to special-case them.
_NULL_LIKE = {"null", "n/a", "na", "none", "unknown", "not found", "not provided", ""}


def clean_field(value: Any) -> Optional[str]:
    """Normalize one extracted field value to ``None`` or a clean string.

    Args:
        value: The raw value from a parsed Claude JSON response --
            expected to be a string or ``None``, but coerced to a string
            first in case Claude returns a non-string type (e.g. a bare
            number for a name that looks numeric).

    Returns:
        ``None`` if the value is missing or one of the "not found"
        strings Claude sometimes uses instead of JSON ``null``;
        otherwise the stripped string.
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    stripped = text.strip()
    return None if stripped.lower() in _NULL_LIKE else stripped


def parse_json_response(text: str) -> Optional[Dict[str, Any]]:
    """Parse a JSON object out of a Claude text response.

    Handles two real deviations from "return only valid JSON" seen in
    practice: the response wrapped in a ```` ```json ... ``` ```` fence,
    and JSON preceded/followed by stray commentary. Falls back to a
    brace-counting scan for the first balanced ``{...}`` block rather
    than a greedy regex, so it doesn't misfire on nested objects.

    Args:
        text: The concatenated text content of a Claude response.

    Returns:
        The parsed object, or ``None`` if no valid JSON object could be
        found anywhere in ``text``.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()

    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    if start == -1:
        return None
    depth = 0
    for i, char in enumerate(stripped[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(stripped[start : i + 1])  # noqa: E203
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def usage_from_response(
    response: Any, model: str, pricing: Dict[str, Dict[str, float]]
) -> ApiUsage:
    """Build an :class:`~lead_scoring_engine.models.ApiUsage` from a Claude response.

    Args:
        response: The ``anthropic.types.Message`` returned by
            ``client.messages.create()``.
        model: The model ID the call was made with.
        pricing: A ``{model: {"input": usd_per_mtok, "output": usd_per_mtok}}``
            table, typically ``config.PRICING_PER_MTOK_USD``.

    Returns:
        Token counts plus an estimated cost -- ``0.0`` (with a logged
        warning) if ``model`` isn't in ``pricing``, so an unrecognized
        model degrades cost *reporting*, not the extraction/scoring
        result itself.
    """
    rates = pricing.get(model)
    if rates is None:
        logger.warning("No pricing data for model %r; cost will be reported as $0.00", model)
        cost = 0.0
    else:
        cost = (response.usage.input_tokens / 1_000_000) * rates["input"] + (
            response.usage.output_tokens / 1_000_000
        ) * rates["output"]
    return ApiUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cost_usd=round(cost, 6),
    )


class ResponseCache:
    """A small on-disk cache for Claude API responses.

    Keyed by a hash of everything that determines the response (model,
    prompt version, and input text), so the same input never re-spends
    on an API call. Never stores a failed call -- callers only call
    :meth:`set` after a success. Silently disabled (every call a no-op)
    when constructed with ``cache_dir=None``.
    """

    def __init__(self, cache_dir: Optional[Path], kind: str) -> None:
        self.cache_dir = cache_dir
        self.kind = kind

    def key_for(self, model: str, prompt_version: str, input_text: str) -> str:
        """Compute the cache key for one (model, prompt version, input) triple."""
        digest_input = f"{model}:{prompt_version}:{input_text}".encode("utf-8")
        return hashlib.sha256(digest_input).hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{self.kind}_{key}.json"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Return the cached dict for ``key``, or ``None`` on a cache miss."""
        if self.cache_dir is None:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Ignoring unreadable cache entry: %s", path)
            return None

    def set(self, key: str, data: Dict[str, Any]) -> None:
        """Write ``data`` to the cache under ``key``. A no-op if caching is disabled."""
        if self.cache_dir is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(json.dumps(data), encoding="utf-8")
