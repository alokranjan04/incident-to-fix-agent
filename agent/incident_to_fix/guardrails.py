"""Guardrails enforced in code (specs/03-guardrails.md): repo allow-list, protected paths,
files per PR, write-branch rules, never merge, and the tool-call budget."""
import logging
import re
from pathlib import PurePosixPath
from typing import Any, MutableMapping

from google.adk.tools import BaseTool, ToolContext

from .config import (
    ALLOWED_OWNER,
    ALLOWED_REPO,
    ALLOWED_REPO_NAME,
    FIX_BRANCH_PREFIX,
    MAX_FILES_PER_PR,
    TOOL_CALL_BUDGET,
)

log = logging.getLogger(__name__)

SERVICENOW_TOOLS = {"get_incident", "add_work_note"}
GITHUB_READ_TOOLS = {"get_file_contents", "list_commits", "list_pull_requests"}
GITHUB_SEARCH_TOOLS = {"search_code"}
GITHUB_WRITE_TOOLS = {"create_branch", "push_files", "create_pull_request"}
GITHUB_REPO_TOOLS = GITHUB_READ_TOOLS | GITHUB_WRITE_TOOLS

TOOL_CALLS_KEY = "tool_calls"
# Why the run stopped early. The first reason recorded wins; the publisher reports it.
STOP_REASON_KEY = "stop_reason"
STOP_BUDGET = "budget"
STOP_ESCALATE = "escalate"
STOP_TESTS_FAILED = "tests_failed"

_QUALIFIER_RE = re.compile(r"\b(repo|org|user):(\"[^\"]*\"|\S+)", re.IGNORECASE)
_PROTECTED_NAME_PARTS = ("secret", "token", ".env")


def is_allowed_repo(repo: str) -> bool:
    """True for the allow-listed repo, as `owner/name` or bare `name` (ServiceNow u_repo)."""
    repo = repo.strip().lower()
    return repo in {ALLOWED_REPO.lower(), ALLOWED_REPO_NAME.lower()}


def is_protected_path(path: str) -> bool:
    """`.github/`, `requirements.txt`, or a file name containing secret, token or .env."""
    parts = PurePosixPath(path.strip().replace("\\", "/").lstrip("/")).parts
    if not parts:
        return False
    name = parts[-1].lower()
    return (
        ".github" in (p.lower() for p in parts[:-1])
        or name == "requirements.txt"
        or any(part in name for part in _PROTECTED_NAME_PARTS)
    )


def patch_violation(paths: list[str]) -> str | None:
    """Why a set of changed files breaks the per-PR rules, or None."""
    if len(paths) > MAX_FILES_PER_PR:
        return f"{len(paths)} files changed; at most {MAX_FILES_PER_PR} allowed"
    protected = [p for p in paths if is_protected_path(p)]
    if protected:
        return f"protected paths: {', '.join(protected)}"
    return None


def _search_violation(query: str) -> str | None:
    qualifiers = [(kind.lower(), value.strip('"').lower()) for kind, value in _QUALIFIER_RE.findall(query)]
    if ("repo", ALLOWED_REPO.lower()) not in qualifiers:
        return f"search_code query must include repo:{ALLOWED_REPO}"
    if any(q != ("repo", ALLOWED_REPO.lower()) for q in qualifiers):
        return f"search_code query may only target repo:{ALLOWED_REPO}"
    return None


def _is_fix_branch(branch: Any) -> bool:
    return isinstance(branch, str) and branch.startswith(FIX_BRANCH_PREFIX) and len(branch) > len(FIX_BRANCH_PREFIX)


def _write_violation(tool_name: str, args: dict[str, Any]) -> str | None:
    if tool_name == "create_branch" and not _is_fix_branch(args.get("branch")):
        return f"create_branch may only create {FIX_BRANCH_PREFIX}* branches"
    if tool_name == "push_files":
        if not _is_fix_branch(args.get("branch")):
            return f"push_files may only push to {FIX_BRANCH_PREFIX}* branches"
        files = args.get("files") or []
        return patch_violation([str(f.get("path", "")) for f in files if isinstance(f, dict)])
    if tool_name == "create_pull_request" and not _is_fix_branch(args.get("head")):
        return f"create_pull_request head must be a {FIX_BRANCH_PREFIX}* branch"
    return None


def repo_violation(tool_name: str, args: dict[str, Any]) -> str | None:
    """Return why a tool call breaks the guardrails, or None if it is allowed."""
    if tool_name in SERVICENOW_TOOLS:
        return None
    if tool_name in GITHUB_SEARCH_TOOLS:
        return _search_violation(str(args.get("query", "")))
    if tool_name in GITHUB_REPO_TOOLS:
        owner = str(args.get("owner", "")).strip().lower()
        repo = str(args.get("repo", "")).strip().lower()
        if (owner, repo) != (ALLOWED_OWNER.lower(), ALLOWED_REPO_NAME.lower()):
            return f"{tool_name} may only use {ALLOWED_REPO}, not {owner}/{repo}"
        return _write_violation(tool_name, args)
    # Deny by default: merge, delete_branch, update_issue and anything else unlisted.
    return f"tool {tool_name} is not allowed"


def record_stop(state: MutableMapping[str, Any], reason: str) -> None:
    """Record why the run stops, unless an earlier reason is already recorded."""
    if not state.get(STOP_REASON_KEY):
        state[STOP_REASON_KEY] = reason


def spend_tool_call(state: MutableMapping[str, Any]) -> str | None:
    """Count one tool call against the budget. Returns why it is refused, or None."""
    used = int(state.get(TOOL_CALLS_KEY) or 0) + 1
    state[TOOL_CALLS_KEY] = used
    if used > TOOL_CALL_BUDGET:
        record_stop(state, STOP_BUDGET)
        return f"budget of {TOOL_CALL_BUDGET} tool calls reached"
    return None


def _blocked(tool_name: str, reason: str) -> dict:
    log.warning("Guardrail blocked %s: %s", tool_name, reason)
    return {"error": f"Blocked by guardrail: {reason}"}


def enforce_budget(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """before_tool_callback: every attempted call counts, blocked or not."""
    reason = spend_tool_call(tool_context.state)
    return _blocked(tool.name, reason) if reason else None


def enforce_allow_list(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """before_tool_callback: block any call outside the guardrails. A dict skips the tool."""
    reason = repo_violation(tool.name, args)
    return _blocked(tool.name, reason) if reason else None
