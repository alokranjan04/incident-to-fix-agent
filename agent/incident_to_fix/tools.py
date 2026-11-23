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


def servicenow_toolset() -> McpToolset:
    """Read-only in milestone A: get_incident only."""
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
        tool_filter=["get_incident"],
    )


def github_toolset() -> McpToolset:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=GITHUB_MCP_URL,
            headers={"Authorization": f"Bearer {token}"},
        ),
        tool_filter=["search_code", "get_file_contents", "list_commits"],
    )
