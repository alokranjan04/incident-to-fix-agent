# 02 · MCP servers

## ServiceNow MCP server (build it: Python + FastMCP)
Credentials come from Secret Manager; the account is `mcp.integration` (role `itil` only).

| Tool | Input | Output | Notes |
| --- | --- | --- | --- |
| get_incident | number | number, short_description, description, category, u_repo, state | read-only |
| add_work_note | number, text | ok | text capped at 4,000 characters |
| set_state | number, state | ok | only `in_progress`; never resolve or close |

Acceptance criteria
- WHEN `get_incident` is called with an unknown number, the server SHALL return a clear
  "not found" error, not an empty object.
- The server SHALL never log the password or full request headers.

## GitHub MCP server (use GitHub's official server)
Token: fine-grained PAT, repo `incident-to-fix-demo` only, Contents and Pull requests
read/write. Tools used: search_code, get_file_contents, list_commits, create_branch,
push_files, create_pull_request.

## Check before the agent uses them
- [ ] MCP Inspector lists every tool for both servers.
- [ ] `get_incident INC0010004` returns the incident as JSON.
- [ ] `get_file_contents app/routes/orders.py` returns the file from `main`.
