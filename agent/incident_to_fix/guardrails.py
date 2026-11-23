"""Guardrails enforced in code (specs/03-guardrails.md). Milestone A: the repo allow-list."""
import logging
import re
from typing import Any

from google.adk.tools import BaseTool, ToolContext

from .config import ALLOWED_OWNER, ALLOWED_REPO, ALLOWED_REPO_NAME

log = logging.getLogger(__name__)

SERVICENOW_TOOLS = {"get_incident"}
GITHUB_REPO_TOOLS = {"get_file_contents", "list_commits"}
GITHUB_SEARCH_TOOLS = {"search_code"}

_QUALIFIER_RE = re.compile(r"\b(repo|org|user):(\"[^\"]*\"|\S+)", re.IGNORECASE)


def is_allowed_repo(repo: str) -> bool:
    """True for the allow-listed repo, as `owner/name` or bare `name` (ServiceNow u_repo)."""
    repo = repo.strip().lower()
    return repo in {ALLOWED_REPO.lower(), ALLOWED_REPO_NAME.lower()}


def _search_violation(query: str) -> str | None:
    qualifiers = [(kind.lower(), value.strip('"').lower()) for kind, value in _QUALIFIER_RE.findall(query)]
    if ("repo", ALLOWED_REPO.lower()) not in qualifiers:
        return f"search_code query must include repo:{ALLOWED_REPO}"
    if any(q != ("repo", ALLOWED_REPO.lower()) for q in qualifiers):
        return f"search_code query may only target repo:{ALLOWED_REPO}"
    return None


def repo_violation(tool_name: str, args: dict[str, Any]) -> str | None:
    """Return why a tool call breaks the allow-list, or None if it is allowed."""
    if tool_name in SERVICENOW_TOOLS:
        return None
    if tool_name in GITHUB_SEARCH_TOOLS:
        return _search_violation(str(args.get("query", "")))
    if tool_name in GITHUB_REPO_TOOLS:
        owner = str(args.get("owner", "")).strip().lower()
        repo = str(args.get("repo", "")).strip().lower()
        if (owner, repo) != (ALLOWED_OWNER.lower(), ALLOWED_REPO_NAME.lower()):
            return f"{tool_name} may only use {ALLOWED_REPO}, not {owner}/{repo}"
        return None
    return f"tool {tool_name} is not allowed"


def enforce_allow_list(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """before_tool_callback: block any call outside the allow-list. A dict skips the tool."""
    reason = repo_violation(tool.name, args)
    if reason is None:
        return None
    log.warning("Guardrail blocked %s: %s", tool.name, reason)
    return {"error": f"Blocked by guardrail: {reason}"}
