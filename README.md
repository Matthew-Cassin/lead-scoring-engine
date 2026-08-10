# lead-scoring-engine

[![CI](https://github.com/Matthew-Cassin/lead-scoring-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Matthew-Cassin/lead-scoring-engine/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Types](https://img.shields.io/badge/types-mypy%20strict-brightgreen)

AI-powered lead extraction, deduplication, and scoring. Feed it messy, unstructured lead text -- a form submission, a scraped page, a pasted email -- and it uses the Claude API to pull out structured fields, validates and deduplicates the results with the rest of this portfolio's tooling, then uses Claude again to score each lead 0-100 on likelihood to convert within 30 days.

This is the one tool in the set that spends real money per run (Claude API calls) -- see [Cost](#cost) before pointing it at a large batch.

## How this fits the rest of the toolset

Rather than reimplementing email/phone validation and fuzzy deduplication a third and fourth time, this project depends directly on two sibling libraries:

- [`email-phone-validator`](https://github.com/Matthew-Cassin/email-phone-validator) validates and normalizes every extracted email and phone number.
- [`contact-deduplicator`](https://github.com/Matthew-Cassin/contact-deduplicator) detects and merges duplicate leads (exact email, exact phone, fuzzy name).

Its own JSON output is generic enough for [`report-mailer`](https://github.com/Matthew-Cassin/report-mailer) to email as a digest, the same way it already does for `csv-data-cleaner` and `contact-scraper`'s reports.

## Installation

```bash
pip install git+https://github.com/Matthew-Cassin/lead-scoring-engine.git
```

Requires an Anthropic API key. Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`, or export it directly -- never commit a real key.

```bash
cp .env.example .env
# edit .env with your own key
```

## Features

- **AI extraction**: Claude pulls name, email, phone, company, industry, and buying-intent signals out of raw unstructured text.
- **Real validation, not regex**: delegates to `email-phone-validator` instead of a hand-rolled pattern -- a plain phone regex rejects any formatted number, which is exactly what extraction returns.
- **Real deduplication, not a second fuzzy-matcher**: delegates to `contact-deduplicator`'s exact-email/exact-phone/fuzzy-name matching.
- **AI scoring with reasoning**: every score comes with Claude's explanation, a high-value flag, and a suggested follow-up tactic -- never a bare number.
- **Cost-aware**: tracks real token usage and estimated USD cost per run, skips scoring entirely for leads with nothing extracted (no wasted call), and caches every Claude response on disk so a rerun over the same data never re-spends.
- **Never crashes on one bad lead.** A failed extraction, an unparseable score, an API error -- all come back as an ordinary inspectable result, the same design used throughout this toolset.

## Quick Start

### CLI

```bash
lead-scoring-engine --input sample_leads.csv --output results
```

```
Extracting fields...
  [##############################] 10/10

Scoring leads...
  [##############################] 8/8

✓ Loaded 10 lead(s) from sample_leads.csv
✓ Extracted fields (10/10 successful)
✓ Validated emails (7/10 valid)
✓ Deduplicated (2 duplicate(s) removed)
✓ Scored leads (avg: 52.5)

Results saved to:
  - results/leads_scored.csv
  - results/leads_scored.json
  - results/summary_report.txt
  - results/email_digest.html

Total API cost: $0.0448
```

That's a real run against `sample_leads.csv` (10 hand-written messy leads, `claude-sonnet-5`, 18 total API calls: 10 extractions + 8 scores, 2 leads merged away before scoring) -- not a mocked example. A rerun over the same file costs `$0.0000` and reports `18 cache hit(s)`.

`summary_report.txt` from that same run:

```
=== LEAD PROCESSING SUMMARY ===
Total Leads Processed: 10
Successful Extractions: 10 (100%)
Valid Email Addresses: 7 (70%)
Duplicates Found & Removed: 2
Average Lead Score: 52.5
High-Value Leads (flagged high_value): 4 (50%)
Cache Hits: 0
Total API Cost: $0.0448
Processing Time: 1m 30s

TOP LEADS (by score):
1. Amara Okafor (Northlight Cloud) - Score 88 -- Immediate outreach within 24 hours emphasizing quick implementation timeline and quarter-end deployment capability. Offer a fast-track onboarding call this week, provide case studies of similar cloud companies with rapid deployments, and propose a streamlined contract process to match their urgency.
2. Renata Silva (Brightwave Analytics) - Score 80 -- Immediately schedule the requested demo within 24-48 hours, and use the initial call to qualify company size, decision-making authority, and specific pain points to tailor a fast-tracked proposal.
3. Daniel Reyes (Meridian Logistics Inc) - Score 78 -- Send a tailored pricing breakdown with ROI calculator specific to logistics automation, and propose a short call within 48 hours to address any remaining objections before offering a limited-time incentive to close within 30 days.
4. Priya Patel (Summit Finance Group) - Score 68 -- Send a tailored ROI/compliance case study within 24 hours, request a discovery call to understand evaluation criteria and timeline, and differentiate from competitors by highlighting unique compliance features and implementation speed.
5. Carlos Mendoza (Palmetto Data Co) - Score 58 -- Send a personalized email referencing the trade show discussion, share a relevant CRM case study or demo offer, and ask qualifying questions about company size, current tools, and timeline to gauge urgency.
```

Two things worth calling out about that real run:

- **The two duplicate pairs in `sample_leads.csv` were deliberately built to test different matching signals** -- "Daniel Reyes" appears twice with the same email but no repeated phone, "Carlos Mendoza" appears twice with the same phone but no repeated email on the second mention. `contact-deduplicator` correctly merged both pairs, one via each signal, entirely through this project's integration layer.
- **Claude did not hallucinate a field it wasn't given.** The second "Carlos" lead only restates his phone number ("same number..."), not his email -- and the real extraction correctly returned `email: null` for that record rather than assuming it matched the first mention. (Deduplication still merged the two records via the phone number they *did* share.)

### Python

```python
from lead_scoring_engine import process_leads, export_csv, export_json

leads, stats = process_leads("sample_leads.csv")
print(f"{stats.successful_extractions}/{stats.total_input} extracted, avg score {stats.avg_score}")

export_csv(leads, "output/leads_scored.csv")
export_json(leads, "output/leads_scored.json")
```

## Cost

Each lead makes up to two Claude API calls (extraction, then scoring -- skipped if extraction found nothing at all). Pricing is pulled from `config.PRICING_PER_MTOK_USD`, sourced from [Anthropic's pricing page](https://platform.claude.com/docs/en/about-claude/pricing) as of 2026-08-08 -- check that page if your actual bill diverges from what this tool reports. `--model` lets you switch to Haiku 4.5 for cheaper, higher-volume runs, or Opus 5 for higher-quality scoring of a small, high-stakes batch.

The response cache (`--cache-dir`, on by default) means a rerun over unchanged input costs nothing further.

## CLI Reference

```
lead-scoring-engine --input FILE [OPTIONS]
```

| Option | Description |
|---|---|
| `--input FILE` | `.csv` (needs a `raw_lead` column) or `.json` (list of `{"raw_lead": ...}`) file. Required. |
| `--output DIR` | Output directory (default `output`). |
| `--formats LIST` | Comma-separated subset of `csv,json,summary,email` (default: all four). |
| `--api-key KEY` | Anthropic API key. Defaults to `ANTHROPIC_API_KEY`. |
| `--model ID` | Claude model ID (default `claude-sonnet-5`). |
| `--cache` / `--no-cache` | Cache Claude responses on disk (default: on). |
| `--cache-dir DIR` | Cache directory (default `.lead_cache`). |
| `--dedup-threshold FLOAT` | Fuzzy name-match threshold, 0.0-1.0 (default `0.85`). |
| `--rate-limit-delay SEC` | Delay between live API calls (default `1.5`). |
| `--max-retries N` | Retry budget for transient API errors (default `3`). |
| `--verbose` | Enable INFO-level console logging. |

## API Reference

### `process_leads(input_file, **options) -> (leads, stats)`

The main pipeline entry point. See the module docstring in `lead_processor.py` for the full option list (API key/model/cache overrides, dependency injection of a pre-built `ClaudeExtractor`/`ClaudeScorer` for testing, a `progress` callback).

### `Lead`

The record that flows through the whole pipeline -- see `models.py` for the full field list. Every field past `id`/`raw_text`/`source` starts `None` and is filled in by a later stage; `None` always means "not yet known," never "invalid."

### `ProcessingStats`

Summary of one run: `total_input`, `successful_extractions`, `valid_emails`, `duplicates_removed`, `avg_score`, `high_value_count`, `processing_time_sec`, `total_api_cost_usd`, `cache_hits`.

### Exporters

`export_csv(leads, filename)`, `export_json(leads, filename)`, `generate_summary_report(leads, stats) -> str`, `generate_email_digest(leads, top_n=20) -> str` (inline-CSS HTML).

## Limitations

- **Costs real money per run.** See [Cost](#cost).
- **Deviates from the "spec" this was built to** in a few deliberate ways: it depends on `email-phone-validator`/`contact-deduplicator` instead of reimplementing validation/dedup from scratch (see [How this fits](#how-this-fits-the-rest-of-the-toolset)); `validators.py`/`deduplicator.py` are thin wrappers around those libraries rather than standalone regex/fuzzywuzzy implementations; and there's no built-in `main.py` scheduler-style loop -- this is a single-run CLI, matching `report-mailer`'s "no scheduler, use cron" philosophy.
- **Extraction and scoring quality depend on Claude's read of messy text.** Ambiguous or contradictory raw lead text can produce a plausible-looking but wrong extraction; nothing here fact-checks Claude's output against ground truth.
- **Recipient/report emailing is intentionally out of scope.** Use `report-mailer` to send `summary_report.txt`/the JSON export as a digest.
- **Cost estimates, not invoices.** See [Cost](#cost).

## License

MIT -- see [LICENSE](LICENSE) for the full text.

## Contributing

Contributions are welcome. Please open an issue to discuss a change before submitting a pull request, and make sure `pytest` and `flake8` are clean.
