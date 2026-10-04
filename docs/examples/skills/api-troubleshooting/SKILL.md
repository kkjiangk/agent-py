---
name: api-troubleshooting
description: Investigate API timeouts, elevated errors, HTTP status changes, and dependency failures using correlated evidence.
---

# API troubleshooting

## Procedure

1. Identify the endpoint, environment, time window, and impact.
2. Check status codes, latency percentiles, and request-volume changes.
3. Correlate application logs through request or trace identifiers.
4. Check dependency timeout, retry, and availability evidence.
5. Compare recent changes and relevant runbooks to form testable hypotheses.

## Constraints

Distinguish correlation from causation. Preserve tool failures and propose alternative checks. Do not execute destructive actions without an authorized target.
