# 00 · Overview

## Goal
An agent that turns a ServiceNow "Software defect" incident into a tested, reviewed pull
request on GitHub, and writes the PR link back to the incident. An engineer always merges.

## In scope
- Target repo: `alokranjan04/incident-to-fix-demo` (FastAPI order service).
- Incidents: ServiceNow PDI `dev492519`, category `software_defect`, field `u_repo`.
- Google Cloud project: `incident-to-fix`. Secrets: `snow-instance-url`, `snow-user`,
  `snow-password`, `github-token`.

## Out of scope
- Merging, deploying, or editing CI, secrets or infrastructure files.
- Any repo other than the allow-listed one.

## Success measures (see 04-evals.md)
- Right file found in at least 12 of 15 seeded incidents.
- Hidden test passes after the fix in at least 10 of 15.
- Zero unsafe actions across the eval set and the 3 injection cases.
- Median time from incident to PR under 5 minutes; cost per incident logged.

## Build order
1. 02-mcp-servers.md  2. 01-agents.md  3. 03-guardrails.md  4. 04-evals.md  5. 05-deploy.md
