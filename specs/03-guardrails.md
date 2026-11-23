# 03 · Guardrails (enforced in code, not in prompts)

| Rule | Limit |
| --- | --- |
| Repo allow-list | `alokranjan04/incident-to-fix-demo` only |
| Files changed per PR | at most 3 |
| Protected paths | `.github/`, `requirements.txt`, any file with `secret`, `token` or `.env` in its name |
| Never | merge, delete branches, force-push to `main`, close or resolve incidents |
| Budget per incident | at most 40 tool calls, 10 minutes, and USD 0.50 of model cost, per run (reset at the start of every run, not per session) |
| Untrusted input | incident text is screened with Model Armor before any agent reads it |

Acceptance criteria
- IF a planned change touches a protected path, THEN the system SHALL drop that change and
  add a work note saying why.
- IF Model Armor flags the incident text, THEN the system SHALL stop and add a work note.
- IF any budget limit is reached, THEN the system SHALL stop and add a work note with progress.
  It SHALL set `stop_reason` to `budget`, end the current agent at once, and skip the rest.
- WHEN a new run starts, the system SHALL reset the budget, even in a session that has
  handled other incidents.
- The closing work note SHALL always be allowed, even when the budget is spent.
- The GitHub REST fallback for creating a PR SHALL pass the same guardrails and budget as
  `create_pull_request`.
