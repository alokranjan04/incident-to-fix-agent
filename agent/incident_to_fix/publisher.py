"""Publisher: opens the PR, or adds a work note saying why not. Code, not an LLM, so branch,
base, title and note text cannot be steered by the incident text."""
import json
from typing import Any, AsyncGenerator, Awaitable, Callable, MutableMapping

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.tools import ToolContext
from google.genai import types
from pydantic import Field

from .config import ALLOWED_OWNER, ALLOWED_REPO_NAME, FIX_BRANCH_PREFIX, MAX_FIX_ATTEMPTS, TOOL_CALL_BUDGET
from .fixer import DROPPED_KEY, PATCH_KEY
from .guardrails import BUDGET_EXCEEDED_KEY, TOOL_CALLS_KEY, repo_violation, spend_tool_call
from .reviewer import REVIEW_KEY
from .verifier import TEST_RESULT_KEY

PR_URL_KEY = "pr_url"
OUTCOME_KEY = "outcome"
TITLE_MAX_CHARS = 120
REPO_ARGS = {"owner": ALLOWED_OWNER, "repo": ALLOWED_REPO_NAME}

CallTool = Callable[[str, dict], Awaitable[Any]]


def fix_branch(number: str) -> str:
    return f"{FIX_BRANCH_PREFIX}{number}"


def pr_title(incident: dict) -> str:
    """`<INC number>: <short description>` on one line."""
    summary = " ".join(str(incident.get("short_description", "")).split())
    return f"{incident['number']}: {summary}"[:TITLE_MAX_CHARS].rstrip()


def tool_error(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    if "error" in result:
        return str(result["error"])
    if result.get("isError"):
        texts = [p.get("text", "") for p in result.get("content") or [] if isinstance(p, dict)]
        return " ".join(texts).strip() or "tool reported an error"
    return None


def extract_pr_url(result: Any) -> str | None:
    """The PR's web URL from a create_pull_request result (structured or JSON text)."""
    candidates = []
    if isinstance(result, dict):
        candidates.append(result.get("structuredContent"))
        for part in result.get("content") or []:
            try:
                candidates.append(json.loads(part.get("text", "")))
            except (AttributeError, json.JSONDecodeError):
                continue
    for data in candidates:
        if isinstance(data, dict):
            for key in ("html_url", "url"):
                url = data.get(key)
                if isinstance(url, str) and url.startswith("https://github.com/"):
                    return url
    return None


def _progress(state: MutableMapping[str, Any]) -> str:
    files = ", ".join(f["path"] for f in state.get("suspect_files") or []) or "none"
    test = (state.get(TEST_RESULT_KEY) or {}).get("summary", "not run")
    return f"Suspect files: {files}. Last test result: {test}."


def no_pr_reason(state: MutableMapping[str, Any]) -> str | None:
    """Why no PR may be opened, as work-note text; None when the fix is approved."""
    decision = state.get("decision") or {}
    if not isinstance(decision, dict) or decision.get("decision") != "fix":
        reason = decision.get("reason", "no reason given") if isinstance(decision, dict) else "no decision"
        return f"Escalated by triage, no PR opened: {reason}"
    if state.get(BUDGET_EXCEEDED_KEY):
        return f"Stopped: budget of {TOOL_CALL_BUDGET} tool calls reached, no PR opened. {_progress(state)}"
    review = state.get(REVIEW_KEY) or {}
    if review.get("verdict") != "approve":
        test = state.get(TEST_RESULT_KEY) or {}
        reasons = "; ".join(review.get("reasons") or []) or "no review"
        return (
            f"No PR opened: the fix was not approved after {MAX_FIX_ATTEMPTS} attempts.\n"
            f"Review: {reasons}\nTests: {test.get('summary', 'not run')}\n{test.get('output', '')}".rstrip()
        )
    return None


def pr_body(state: MutableMapping[str, Any]) -> str:
    incident = state["incident"]
    files = "\n".join(f"- `{f['path']}`" for f in state.get(PATCH_KEY) or [])
    reasons = "\n".join(f"- {r}" for r in (state.get(REVIEW_KEY) or {}).get("reasons") or [])
    return (
        f"Fixes ServiceNow incident {incident['number']}.\n\n"
        f"Files changed:\n{files}\n\n"
        f"Tests: {(state.get(TEST_RESULT_KEY) or {}).get('summary', '')}\n\n"
        f"Review:\n{reasons}\n\n"
        "Opened by the incident-to-fix agent. An engineer must review and merge."
    )


def _with_dropped(text: str, state: MutableMapping[str, Any]) -> str:
    dropped = state.get(DROPPED_KEY) or []
    return text + ("\nDropped changes (guardrails): " + "; ".join(dropped) if dropped else "")


async def publish(state: MutableMapping[str, Any], call_tool: CallTool) -> dict[str, Any]:
    """Open the PR and note its URL, or add a work note explaining why not. Returns state delta."""
    incident = state.get("incident") or {}
    number = incident.get("number")
    if not number:
        return {OUTCOME_KEY: "No incident was read; nothing to publish."}

    async def note(text: str) -> dict[str, Any]:
        text = _with_dropped(text, state)
        await call_tool("add_work_note", {"number": number, "text": text})
        return {OUTCOME_KEY: text}

    reason = no_pr_reason(state)
    if reason:
        return await note(reason)

    head, base = fix_branch(number), state["branch"]
    files = [{"path": f["path"], "content": f["new_content"]} for f in state[PATCH_KEY]]
    steps = [
        ("create_branch", {**REPO_ARGS, "branch": head, "from_branch": base}),
        ("push_files", {**REPO_ARGS, "branch": head, "files": files, "message": pr_title(incident)}),
        ("create_pull_request", {**REPO_ARGS, "title": pr_title(incident), "head": head, "base": base,
                                 "body": pr_body(state)}),
    ]
    result: Any = None
    for name, args in steps:
        result = await call_tool(name, args)
        error = tool_error(result)
        if error:
            return await note(f"No PR opened: {name} failed: {error}")

    url = extract_pr_url(result)
    delta = await note(f"Pull request opened: {url}" if url else "Pull request opened, but its URL was not returned.")
    return {**delta, PR_URL_KEY: url}


def guarded(raw_call: CallTool, budget_state: MutableMapping[str, Any]) -> CallTool:
    """Apply the same guardrails as before_tool_callback. The closing work note is always
    allowed so a stopped run can still say why."""

    async def call(name: str, args: dict) -> Any:
        over_budget = spend_tool_call(budget_state)
        reason = repo_violation(name, args) or (over_budget if name != "add_work_note" else None)
        if reason:
            return {"error": f"Blocked by guardrail: {reason}"}
        return await raw_call(name, args)

    return call


class Publisher(BaseAgent):
    """Last step. Calls GitHub and ServiceNow MCP tools directly, through `guarded`."""

    tools: list[Any] = Field(default_factory=list)

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        readonly = ReadonlyContext(ctx)
        by_name = {tool.name: tool for toolset in self.tools for tool in await toolset.get_tools(readonly)}
        tool_context = ToolContext(ctx)

        async def raw_call(name: str, args: dict) -> Any:
            tool = by_name.get(name)
            if tool is None:
                return {"error": f"tool {name} is not available"}
            try:
                return await tool.run_async(args=args, tool_context=tool_context)
            except Exception as exc:  # report the failure in the work note, don't crash the run
                return {"error": f"{type(exc).__name__}: {exc}"}

        state = ctx.session.state
        delta: dict[str, Any] = {TOOL_CALLS_KEY: state.get(TOOL_CALLS_KEY) or 0}
        delta.update(await publish(state, guarded(raw_call, delta)))
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=delta[OUTCOME_KEY])]),
            actions=EventActions(state_delta=delta),
        )
