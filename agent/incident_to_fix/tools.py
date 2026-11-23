"""MCP toolsets for ServiceNow (our stdio server) and GitHub (official remote server)."""
import os
import sys

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from mcp import StdioServerParameters
from mcp.client.stdio import get_default_environment

from .config import GITHUB_MCP_URL, REPO_ROOT

SNOW_ENV_VARS = ("SNOW_INSTANCE_URL", "SNOW_USER", "SNOW_PASSWORD")

# The only MCP tools any agent may be given. Merge, delete and close are not on the list.
SERVICENOW_TOOLS = ("get_incident", "add_work_note")
GITHUB_TOOLS = (
    "search_code",
    "get_file_contents",
    "list_commits",
    "create_branch",
    "push_files",
    "create_pull_request",
)


def _check_filter(tools: list[str], allowed: tuple[str, ...]) -> list[str]:
    unknown = set(tools) - set(allowed)
    if unknown:
        raise ValueError(f"tools not allowed: {sorted(unknown)}")
    return list(tools)


def servicenow_toolset(tools: list[str]) -> McpToolset:
    # The stdio client passes a minimal env by default, so forward the SNOW_* vars.
    env = {**get_default_environment(), **{k: os.environ[k] for k in SNOW_ENV_VARS if k in os.environ}}
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=["-m", "mcp_servers.servicenow.server"],
                cwd=str(REPO_ROOT),
                env=env,
            ),
            timeout=30,
        ),
        tool_filter=_check_filter(tools, SERVICENOW_TOOLS),
    )


def github_toolset(tools: list[str]) -> McpToolset:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=GITHUB_MCP_URL,
            headers={"Authorization": f"Bearer {token}"},
        ),
        tool_filter=_check_filter(tools, GITHUB_TOOLS),
    )
