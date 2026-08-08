"""Export processed leads to CSV, JSON, a text summary, and an HTML digest."""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path
from typing import List

import pandas as pd

from .models import Lead, ProcessingStats

__all__ = ["export_csv", "export_json", "generate_summary_report", "generate_email_digest"]

_CSV_COLUMNS = [
    "id",
    "name",
    "email",
    "email_valid",
    "phone",
    "phone_valid",
    "company",
    "industry",
    "intent_signals",
    "score",
    "score_reasoning",
    "high_value",
    "follow_up_tactic",
]


def export_csv(leads: List[Lead], filename: str) -> None:
    """Write ``leads`` to a CSV file, creating parent directories as needed.

    Columns: ``id, name, email, email_valid, phone, phone_valid,
    company, industry, intent_signals, score, score_reasoning,
    high_value, follow_up_tactic``. Broader than the original spec's
    column list -- the validity flags are genuinely useful output, not
    just intermediate state.
    """
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{column: getattr(lead, column) for column in _CSV_COLUMNS} for lead in leads]
    pd.DataFrame(rows, columns=_CSV_COLUMNS).to_csv(path, index=False)


def export_json(leads: List[Lead], filename: str) -> None:
    """Write ``leads`` to a JSON file (a list of full lead objects)."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump([asdict(lead) for lead in leads], handle, indent=2)


def generate_summary_report(leads: List[Lead], stats: ProcessingStats) -> str:
    """Build a plain-text run summary, in the same shape a CLI would print.

    Args:
        leads: The final (deduplicated, scored) leads.
        stats: The run's :class:`~lead_scoring_engine.models.ProcessingStats`.

    Returns:
        A multi-line text report: headline stats, then a "TOP LEADS"
        section listing up to 5 leads by score, highest first.
    """

    def pct(count: int, total: int) -> str:
        return f"{count} ({round(100 * count / total)}%)" if total else f"{count} (0%)"

    lines = [
        "=== LEAD PROCESSING SUMMARY ===",
        f"Total Leads Processed: {stats.total_input}",
        f"Successful Extractions: {pct(stats.successful_extractions, stats.total_input)}",
        f"Valid Email Addresses: {pct(stats.valid_emails, stats.total_input)}",
        f"Duplicates Found & Removed: {stats.duplicates_removed}",
        f"Average Lead Score: {stats.avg_score}",
        f"High-Value Leads (flagged high_value): {pct(stats.high_value_count, len(leads))}",
        f"Cache Hits: {stats.cache_hits}",
        f"Total API Cost: ${stats.total_api_cost_usd:.4f}",
        f"Processing Time: {_format_duration(stats.processing_time_sec)}",
        "",
        "TOP LEADS (by score):",
    ]

    scored = sorted(
        (lead for lead in leads if lead.score is not None),
        key=lambda lead: lead.score,
        reverse=True,
    )
    if not scored:
        lines.append("(none scored)")
    for rank, lead in enumerate(scored[:5], start=1):
        company = f" ({lead.company})" if lead.company else ""
        tactic = f" -- {lead.follow_up_tactic}" if lead.follow_up_tactic else ""
        name = lead.name or lead.id
        lines.append(f"{rank}. {name}{company} - Score {lead.score}{tactic}")

    return "\n".join(lines)


def generate_email_digest(leads: List[Lead], top_n: int = 20) -> str:
    """Build an HTML email digest of the highest-scoring leads.

    Inline styles only (no ``<style>`` block), matching the convention
    used across this portfolio's other HTML output (see report-mailer's
    ``formatter.py``) since mail clients like Gmail and Outlook strip
    ``<style>`` blocks.

    Args:
        leads: The final (deduplicated, scored) leads.
        top_n: Maximum number of leads to include, highest score first.

    Returns:
        A complete HTML document as a string.
    """
    scored = sorted(
        (lead for lead in leads if lead.score is not None),
        key=lambda lead: lead.score,
        reverse=True,
    )[:top_n]

    rows = "\n".join(_digest_row_html(lead) for lead in scored) or (
        '<tr><td style="padding:12px;color:#666;" colspan="5">No scored leads.</td></tr>'
    )

    return f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:720px;margin:0 auto;">
  <h1 style="font-size:20px;color:#1a1a1a;border-bottom:2px solid #2d6cdf;padding-bottom:8px;">
    Lead Scoring Digest
  </h1>
  <p style="color:#444;font-size:14px;">
    Top {len(scored)} lead(s) out of {len(leads)} processed, ranked by conversion likelihood.
  </p>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    <thead>
      <tr style="background:#f2f4f8;text-align:left;">
        <th style="padding:8px;border-bottom:2px solid #ddd;">Score</th>
        <th style="padding:8px;border-bottom:2px solid #ddd;">Name</th>
        <th style="padding:8px;border-bottom:2px solid #ddd;">Company</th>
        <th style="padding:8px;border-bottom:2px solid #ddd;">Email</th>
        <th style="padding:8px;border-bottom:2px solid #ddd;">Follow-up</th>
      </tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>
</div>"""


def _digest_row_html(lead: Lead) -> str:
    badge_color = "#1a7f37" if lead.high_value else "#444"
    name = html.escape(lead.name or lead.id)
    company = html.escape(lead.company or "")
    email = html.escape(lead.email or "")
    tactic = html.escape(lead.follow_up_tactic or "")
    return f"""      <tr style="border-bottom:1px solid #eee;">
        <td style="padding:8px;font-weight:bold;color:{badge_color};">{lead.score}</td>
        <td style="padding:8px;">{name}</td>
        <td style="padding:8px;">{company}</td>
        <td style="padding:8px;">{email}</td>
        <td style="padding:8px;color:#555;">{tactic}</td>
      </tr>"""


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds as e.g. ``"2m 15s"`` or ``"3.4s"``."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(round(seconds)), 60)
    return f"{minutes}m {remainder}s"
