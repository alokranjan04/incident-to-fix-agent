"""Run lifecycle: per-run state reset, clean stops for agents with an output_schema, and
turning tool exceptions into results so nothing escapes to the runner (adk web)."""
import json
import logging
import re
from typing import Any, Callable

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

from .guardrails import STOP_REASON_KEY, STOP_TESTS_FAILED, TOOL_CALLS_KEY, record_stop

log = logging.getLogger(__name__)

# Everything one run writes. Reset at the start of each run so a second incident in the same
# session starts clean (fresh budget). file_cache is deliberately session-scoped.
RUN_STATE_KEYS = (
    "incident", "branch", "decision", "suspect_files", "patch", "dropped_changes",
    "test_result", "review", "pr_url", "outcome", STOP_REASON_KEY,
)
REQUESTED_NUMBER_KEY = "requested_number"
ERROR_TEXT_MAX_CHARS = 500
_NUMBER_RE = re.compile(r"\bINC\d{7}\b", re.IGNORECASE)

StopOutput = Callable[[str], dict]


def requested_number(content: types.Content | None) -> str | None:
    """The incident number in the user's message, e.g. INC0010004."""
    text = " ".join(p.text for p in (content.parts or []) if p.text) if content else ""
    match = _NUMBER_RE.search(text)
    return match.group(0).upper() if match else None


def start_run(callback_context: CallbackContext) -> None:
    """Root before_agent_callback: the budget and run state are per invocation. Also keeps
    the requested incident number, so a run stopped before get_incident can still add a note."""
    state = callback_context.state
    state[TOOL_CALLS_KEY] = 0
    for key in RUN_STATE_KEYS:
        state[key] = None
    state[REQUESTED_NUMBER_KEY] = requested_number(callback_context.user_content)
    return None


def _stop_content(reason: str, output: StopOutput) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=json.dumps(output(reason)))])


def skip_when_stopped(output: StopOutput) -> Callable[[CallbackContext], types.Content | None]:
    """before_agent_callback: once the run has stopped, answer with schema-valid output."""

    def callback(callback_context: CallbackContext) -> types.Content | None:
        reason = callback_context.state.get(STOP_REASON_KEY)
        return _stop_content(reason, output) if reason else None

    return callback


def stop_model_when_stopped(output: StopOutput) -> Callable[..., LlmResponse | None]:
    """before_model_callback: a stop mid-agent (budget) ends the agent's turn at once,
    with schema-valid output, instead of letting the model keep calling blocked tools."""

    def callback(callback_context: CallbackContext, llm_request: LlmRequest) -> LlmResponse | None:
        reason = callback_context.state.get(STOP_REASON_KEY)
        return LlmResponse(content=_stop_content(reason, output)) if reason else None

    return callback


def finish_fix_loop(callback_context: CallbackContext) -> None:
    """fix_loop after_agent_callback: no approval after the last attempt means tests_failed."""
    state = callback_context.state
    if (state.get("review") or {}).get("verdict") != "approve":
        record_stop(state, STOP_TESTS_FAILED)
    return None


def tool_error_result(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, error: Exception
) -> dict:
    """on_tool_error_callback: report a tool exception to the model as an error result."""
    log.warning("Tool %s raised %s", tool.name, type(error).__name__)
    return {"error": f"{tool.name} failed: {type(error).__name__}: {str(error)[:ERROR_TEXT_MAX_CHARS]}"}
