"""Publisher: opens the PR, or adds one work note saying why the run stopped. Code, not an LLM,
so branch, base, title and note text cannot be steered by the incident text.

Idempotent and resilient: an existing fix/<INC> branch is reused; if create_pull_request
fails or its response cannot be read, list_pull_requests checks whether the PR exists; if
that cannot confirm it, the GitHub REST API creates it. Every call passes the guardrails."""
import asyncio
import json
import os
from typing import Any, AsyncGenerator, Awaitable, Callable, Iterator, MutableMapping

import requests
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.tools import ToolContext
from google.genai import types
from pydantic import Field

from .config import (
    ALLOWED_OWNER,
    ALLOWED_PR_URL_PREFIX,
    ALLOWED_REPO_NAME,
    FIX_BRANCH_PREFIX,
    GITHUB_API_PULLS_URL,
    MAX_FIX_ATTEMPTS,
    TOOL_CALL_BUDGET,
)
from .fixer import DROPPED_KEY, PATCH_KEY
from .guardrails import (
    STOP_BUDGET,
    STOP_ESCALATE,
    STOP_REASON_KEY,
    STOP_TESTS_FAILED,
    TOOL_CALLS_KEY,
    repo_violation,
    spend_tool_call,
)
from .locator import cap_suspect_files
from .reviewer import REVIEW_KEY
from .run_control import REQUESTED_NUMBER_KEY
from .verifier import TEST_RESULT_KEY

PR_URL_KEY = "pr_url"
OUTCOME_KEY = "outcome"
TITLE_MAX_CHARS = 120
REST_TIMEOUT_SECONDS = 30
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


def _payloads(result: Any) -> Iterator[Any]:
    """Structured or JSON-text payloads in an MCP/REST result; lists are flattened."""
    found: list[Any] = []
    if isinstance(result, dict):
        found.append(result.get("structuredContent"))
        for part in result.get("content") or []:
            try:
                found.append(json.loads(part.get("text", "")))
            except (AttributeError, TypeError, json.JSONDecodeError):
                continue
    for data in found:
        if isinstance(data, dict):
            yield data
            for value in data.values():
                if isinstance(value, list):
                    yield from (item for item in value if isinstance(item, dict))
        elif isinstance(data, list):
            yield from (item for item in data if isinstance(item, dict))


def _pr_url(data: dict) -> str | None:
    for key in ("html_url", "url"):
        url = data.get(key)
        if isinstance(url, str) and url.startswith(ALLOWED_PR_URL_PREFIX):
            return url
    return None


def extract_pr_url(result: Any, head: str | None = None) -> str | None:
    """The allow-listed repo's PR URL from a result; with `head`, only a PR from that branch."""
    for data in _payloads(result):
        ref = (data.get("head") or {}).get("ref") if isinstance(data.get("head"), dict) else None
        if head and ref and ref != head:
            continue
        url = _pr_url(data)
        if url:
            return url
    return None


def _progress(state: MutableMapping[str, Any]) -> str:
    files = ", ".join(f["path"] for f in cap_suspect_files(state.get("suspect_files"))) or "none"
    test = (state.get(TEST_RESULT_KEY) or {}).get("summary", "not run")
    return f"Suspect files: {files}. Last test result: {test}."


def stop_note(state: MutableMapping[str, Any]) -> str | None:
    """The work note for a run that must not open a PR, from stop_reason; None to publish."""
    stop = state.get(STOP_REASON_KEY)
    decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
    review = state.get(REVIEW_KEY) if isinstance(state.get(REVIEW_KEY), dict) else {}
    if stop == STOP_BUDGET:
        return f"Stopped: budget of {TOOL_CALL_BUDGET} tool calls reached, no PR opened. {_progress(state)}"
    if stop == STOP_ESCALATE or decision.get("decision") != "fix":
        return f"Escalated by triage, no PR opened: {decision.get('reason', 'no reason given')}"
    if stop == STOP_TESTS_FAILED or review.get("verdict") != "approve":
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


async def open_pull_request(args: dict, call_tool: CallTool, rest_call: CallTool) -> tuple[str | None, list[str]]:
    """Create the PR, confirming it via list_pull_requests and falling back to REST.
    Returns (url or None, what went wrong on the way)."""
    problems: list[str] = []
    result = await call_tool("create_pull_request", args)
    url = extract_pr_url(result)
    if url:
        return url, problems
    problems.append(f"create_pull_request: {tool_error(result) or 'no PR URL in the response'}")

    listed = await call_tool("list_pull_requests", {**REPO_ARGS, "head": f"{ALLOWED_OWNER}:{args['head']}", "state": "open"})
    url = extract_pr_url(listed, head=args["head"])
    if url:
        return url, problems
    problems.append(f"list_pull_requests: {tool_error(listed) or 'no open PR from ' + args['head']}")

    rest = await rest_call("create_pull_request", args)
    url = extract_pr_url(rest)
    if url:
        return url, problems
    problems.append(f"REST: {tool_error(rest) or 'no PR URL in the response'}")
    return None, problems


async def publish(state: MutableMapping[str, Any], call_tool: CallTool, rest_call: CallTool) -> dict[str, Any]:
    """Open the PR and note its URL, or add one work note explaining why not. Returns state delta."""
    incident = state.get("incident") or {}
    # A run stopped before get_incident still notes the number the user asked about.
    number = incident.get("number") or state.get(REQUESTED_NUMBER_KEY)
    if not number:
        return {OUTCOME_KEY: "No incident number was given; nothing to publish."}

    async def note(text: str) -> dict[str, Any]:
        text = _with_dropped(text, state)
        await call_tool("add_work_note", {"number": number, "text": text})
        return {OUTCOME_KEY: text}

    reason = stop_note(state)
    if reason:
        return await note(reason)

    head, base = fix_branch(number), state["branch"]
    created = await call_tool("create_branch", {**REPO_ARGS, "branch": head, "from_branch": base})
    error = tool_error(created)
    if error and "already exists" not in error.lower():  # an existing fix branch is reused
        return await note(f"No PR opened: create_branch failed: {error}")

    files = [{"path": f["path"], "content": f["new_content"]} for f in state[PATCH_KEY]]
    pushed = await call_tool("push_files", {**REPO_ARGS, "branch": head, "files": files, "message": pr_title(incident)})
    error = tool_error(pushed)
    if error:
        return await note(f"No PR opened: push_files failed: {error}")

    pr_args = {**REPO_ARGS, "title": pr_title(incident), "head": head, "base": base, "body": pr_body(state)}
    url, problems = await open_pull_request(pr_args, call_tool, rest_call)
    if not url:
        return await note(f"No PR opened: could not create or confirm a PR from {head}. " + "; ".join(problems))
    return {**await note(f"Pull request opened: {url}"), PR_URL_KEY: url}


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


async def rest_create_pull_request(name: str, args: dict) -> dict:
    """Fallback: POST /repos/{owner}/{repo}/pulls on the allow-listed repo. Called only through
    `guarded` as create_pull_request. Errors carry the status and GitHub's message, never headers."""
    if name != "create_pull_request":
        return {"error": f"REST fallback does not support {name}"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return {"error": "GITHUB_TOKEN is not set"}
    payload = {key: args[key] for key in ("title", "head", "base", "body") if key in args}

    def post() -> requests.Response:
        return requests.post(
            GITHUB_API_PULLS_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=REST_TIMEOUT_SECONDS,
        )

    try:
        response = await asyncio.to_thread(post)
    except requests.RequestException as exc:
        return {"error": f"GitHub REST request failed: {type(exc).__name__}"}
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code == 201:
        return {"structuredContent": body}
    message = body.get("message", "") if isinstance(body, dict) else ""
    return {"error": f"GitHub REST HTTP {response.status_code}: {message}".rstrip(": ")}


class Publisher(BaseAgent):
    """Last step. Calls GitHub and ServiceNow MCP tools directly, through `guarded`."""

    tools: list[Any] = Field(default_factory=list)
    rest_call: Any = Field(default=rest_create_pull_request)

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        delta: dict[str, Any] = {
            TOOL_CALLS_KEY: state.get(TOOL_CALLS_KEY) or 0,
            STOP_REASON_KEY: state.get(STOP_REASON_KEY),
        }
        try:
            delta.update(await publish(state, guarded(await self._raw_call(ctx), delta), guarded(self.rest_call, delta)))
        except Exception as exc:  # never let an exception reach the runner (adk web)
            delta[OUTCOME_KEY] = f"Publisher failed: {type(exc).__name__}: {exc}"
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=delta[OUTCOME_KEY])]),
            actions=EventActions(state_delta=delta),
        )

    async def _raw_call(self, ctx: InvocationContext) -> CallTool:
        readonly = ReadonlyContext(ctx)
        by_name = {tool.name: tool for toolset in self.tools for tool in await toolset.get_tools(readonly)}
        tool_context = ToolContext(ctx)

        async def raw_call(name: str, args: dict) -> Any:
            tool = by_name.get(name)
            if tool is None:
                return {"error": f"tool {name} is not available"}
            try:
                return await tool.run_async(args=args, tool_context=tool_context)
            except Exception as exc:  # e.g. a response the MCP client cannot parse
                return {"error": f"{type(exc).__name__}: {exc}"}

        return raw_call
