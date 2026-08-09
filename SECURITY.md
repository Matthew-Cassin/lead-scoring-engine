# Security Policy

## Supported Versions

Only the latest published release receives security fixes.

| Version | Supported |
| ------- | --------- |
| 1.x     | ✅        |
| < 1.0   | ❌        |

## Reporting a Vulnerability

Please report suspected vulnerabilities privately via [GitHub's private
vulnerability reporting](https://github.com/Matthew-Cassin/lead-scoring-engine/security/advisories/new)
rather than filing a public issue. Include reproduction steps and the
affected version. Expect an initial response within 5 business days.

## Credential Handling

The Claude API key is read from the `ANTHROPIC_API_KEY` environment
variable (via `.env`, which is gitignored -- see `.env.example` for the
template). It is never accepted as a CLI flag and never logged. Cached
API responses (`.lead_cache/`) and pipeline output (`output/`) may
contain real lead data and are also gitignored -- never commit them.
