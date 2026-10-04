# Chat skill examples

These five UTF-8 `SKILL.md` files are optional application uploads, not automatically enabled developer tooling:

- [Log analysis](log-analysis/SKILL.md)
- [Knowledge search](knowledge-search/SKILL.md)
- [API troubleshooting](api-troubleshooting/SKILL.md)
- [Incident report](incident-report/SKILL.md)
- [Change risk review](change-risk-review/SKILL.md)

Open skill settings in the chat workspace, upload a file, select the desired skills, and save. Each YAML frontmatter name matches its parent directory and its description identifies the capability. Files stay below the 64 KiB upload limit.

The initial agent prompt includes only selected skill names and descriptions. When relevant, the agent calls `load_skill(name)` and receives the complete body as a tool result. These examples define evidence-handling procedures and do not grant permission for external changes.
