# Working on this project (instructions for coding agents)

This project is built spec-first. Before writing code:
1. Read `specs/00-overview.md`, then the spec for the part you are building.
2. Implement only what the spec says. If the spec is unclear, stop and ask.
3. Each EARS line ("WHEN ... SHALL ...") needs a test that proves it.

Rules
- Never read, copy or summarise anything under `evals/` into the agent's prompts or tools.
  The evals are the answer key.
- Never hard-code secrets. Read them from Secret Manager (or `.env` for local runs only).
- Python 3.12, Google ADK, FastMCP. Keep functions small and typed.
- Run `pytest -q` before every commit.
