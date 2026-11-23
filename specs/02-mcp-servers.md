# 02 · MCP servers

## ServiceNow MCP server (build it: Python + FastMCP)
Credentials come from env vars `SNOW_INSTANCE_URL`, `SNOW_USER`, `SNOW_PASSWORD`. On Cloud Run,
Secret Manager injects them; for local runs they are loaded from `.env`. The account is
`mcp.integration` (role `itil` only).

| Tool | Input | Output | Notes |
| --- | --- | --- | --- |
| get_incident | number | number, short_description, description, category, u_repo, state, state_label | read-only; state_label: 1 New, 2 In Progress, 3 On Hold, 6 Resolved, 7 Closed, 8 Canceled |
| add_work_note | number, text | ok | text capped at 4,000 characters; longer text is truncated and ends with `… [truncated]` |
| set_state | number, state | ok | only `in_progress`; never resolve or close |

Acceptance criteria
- WHEN `get_incident` is called with an unknown number, the server SHALL return a clear
  "not found" error, not an empty object.
- The server SHALL never log the password or full request headers.
- WHEN any tool is called with an incident number that is not only letters and digits, the
  server SHALL return an "invalid incident number" error and make no ServiceNow request.
- WHEN `add_work_note` is called with text over 4,000 characters, the server SHALL store
  at most 4,000 characters, ending with `… [truncated]`.
- WHEN `get_incident` returns an incident, the server SHALL include `state_label`, the name
  of its state code.
- WHEN `get_incident` returns text fields containing `\r\n`, the server SHALL replace each
  `\r\n` with `\n`.

## GitHub MCP server (use GitHub's official server)
Token: fine-grained PAT, repo `incident-to-fix-demo` only, Contents and Pull requests
read/write. Tools used: search_code, get_file_contents, list_commits, create_branch,
push_files, create_pull_request.

## Check before the agent uses them
- [ ] MCP Inspector lists every tool for both servers.
- [ ] `get_incident INC0010004` returns the incident as JSON.
- [ ] `get_file_contents app/routes/orders.py` returns the file from `main`.
