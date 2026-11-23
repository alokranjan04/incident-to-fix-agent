"""Per-session cache for get_file_contents, keyed by (path, ref), so a file is read once."""
from typing import Any

from google.adk.tools import BaseTool, ToolContext

CACHE_STATE_KEY = "file_cache"
CACHED_TOOL = "get_file_contents"


def cache_key(args: dict[str, Any]) -> str:
    path = str(args.get("path", "")).strip().lstrip("/")
    ref = str(args.get("ref", "")).strip().removeprefix("refs/heads/")
    return f"{ref}:{path}"


def _is_cacheable(tool_response: Any) -> bool:
    return (
        isinstance(tool_response, dict)
        and not tool_response.get("isError")
        and "error" not in tool_response
    )


def serve_cached_file(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """before_tool_callback: return the cached result instead of calling GitHub again."""
    if tool.name != CACHED_TOOL:
        return None
    return (tool_context.state.get(CACHE_STATE_KEY) or {}).get(cache_key(args))


def store_file(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: Any
) -> None:
    """after_tool_callback: remember successful get_file_contents results for this session."""
    if tool.name != CACHED_TOOL or not _is_cacheable(tool_response):
        return None
    cache = dict(tool_context.state.get(CACHE_STATE_KEY) or {})
    cache[cache_key(args)] = tool_response
    tool_context.state[CACHE_STATE_KEY] = cache
    return None
