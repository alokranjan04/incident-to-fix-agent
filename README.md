# incident-to-fix-agent

An ADK multi-agent system that turns a ServiceNow incident into a tested, reviewed GitHub
pull request, using MCP servers for ServiceNow and GitHub. An engineer always merges.

Target repo: `incident-to-fix-demo` (keep both folders side by side).

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # fill in SNOW_PASSWORD and GITHUB_TOKEN for local runs

python scripts/verify_bugs.py                     # 15/15 bugs verified
python scripts/seed_bugs.py --push                # bug/02 .. bug/15 on GitHub
python scripts/create_incidents.py --dry-run      # preview, then run without --dry-run
```

## Specs (build in this order)
1. `specs/02-mcp-servers.md`
2. `specs/01-agents.md`
3. `specs/03-guardrails.md`
4. `specs/04-evals.md`
5. `specs/05-deploy.md`

Start with `specs/00-overview.md`.
