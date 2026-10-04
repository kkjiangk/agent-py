---
name: log-analysis
description: Build a timeline and recurring patterns from actual logs, separating observed facts, inference, and unresolved checks.
---

# Log analysis

## Procedure

1. Determine current time when needed and define a bounded query window.
2. Use available real log tools and retain service, level, event, message, and request identifiers.
3. Group repeated logs while preserving representative evidence.
4. Separate observed log facts from inference and items needing verification.
5. When there are no results, say so and suggest the next bounded query.

## Constraints

Never fabricate logs or infer a confirmed root cause from missing evidence. Output the query scope, key evidence, timeline, findings, and next checks.
