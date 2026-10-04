---
name: change-risk-review
description: Review a proposed release, configuration update, schema migration, or infrastructure change and identify risks, mitigations, stop conditions, and rollback checks.
---

# Change risk review

## Procedure

1. Identify affected components, dependencies, and the intended change.
2. Assess migration compatibility, capacity, performance, timeouts, and permission effects.
3. Assign high, medium, or low risk with supporting evidence.
4. For each high risk, specify mitigation and a measurable stop condition.
5. Define rollback steps, observed metrics, and a verification window.

## Constraints

Ask for material missing change details. A risk review does not authorize performing the change.
