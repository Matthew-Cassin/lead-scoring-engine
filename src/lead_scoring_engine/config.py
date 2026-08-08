"""Configuration and settings for lead-scoring-engine.

Every value here is a default, not a hardcoded requirement -- the CLI
exposes overrides for the ones worth changing per run (``--model``,
``--dedup-threshold``, etc.).
"""

from __future__ import annotations

# Claude model used for both extraction and scoring. Sonnet 5 is a
# reasonable default balance of quality and cost for structured
# extraction plus short reasoning; pass a different model to
# ``ClaudeExtractor``/``ClaudeScorer`` (or ``--model`` on the CLI) for
# Haiku 4.5 (cheaper, better for high-volume/simple leads) or Opus 5
# (higher quality for ambiguous, high-stakes leads).
#
# NOTE ON THE ORIGINAL SPEC: it named "claude-opus-4-6", which is not a
# real model -- there has never been an Opus "4-6" release. Real current
# model IDs are ``claude-sonnet-5``, ``claude-opus-5``, and
# ``claude-haiku-4-5-20251001``.
CLAUDE_MODEL = "claude-sonnet-5"
CLAUDE_MAX_TOKENS = 1024

# Per-million-token USD pricing, base (non-cached, non-batch) rates only.
# Source: https://platform.claude.com/docs/en/about-claude/pricing,
# fetched 2026-08-08. Sonnet 5 is under introductory pricing through
# 2026-08-31 ($2/$10 per MTok in/out); it rises to standard pricing
# ($3/$15) after that. Costs this tool reports are an *estimate* from
# this table, not an invoice -- check the page above if your actual
# bill diverges, and update this table when it does.
PRICING_PER_MTOK_USD = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
}

# Fuzzy name-match threshold forwarded to contact-deduplicator's
# ContactDeduplicator(name_similarity_threshold=...).
DEDUP_THRESHOLD = 0.85

OUTPUT_DIR = "output"

# Extraction/scoring responses are cached here, keyed by a hash of their
# input, so re-running the pipeline on the same data doesn't re-spend on
# calls already made. Safe to delete at any time.
CACHE_DIR = ".lead_cache"

# Delay between consecutive Claude API calls, in seconds. A cheap,
# blunt guard against bursting into rate limits on large batches; the
# SDK's own retry-with-backoff (see claude_extractor.py/claude_scorer.py)
# handles the case where a limit gets hit anyway.
RATE_LIMIT_DELAY_SEC = 1.5

# Retry budget for transient Claude API errors (timeouts, rate limits,
# 5xx/overloaded responses). Non-transient errors (bad API key, bad
# request) are not retried -- see claude_extractor.py.
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 2.0
