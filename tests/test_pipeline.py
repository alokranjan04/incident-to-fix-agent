"""The real agent pipeline, run offline in an ADK Runner with a scripted LLM and fake MCP
servers. Covers (specs/01-agents.md, 03-guardrails.md):
- the budget is per invocation: a second run in the same session gets a fresh budget;
- IF any budget limit is reached, THEN the system SHALL stop and add a work note: a budget
  stop in each agent ends cleanly with stop_reason set and one work note, no exception;
- schema-valid output from stopped agents, and tool exceptions reported, not raised."""
import asyncio
from typing import Any

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent.incident_to_fix import guardrails, verifier
from agent.incident_to_fix.agent import Toolsets, build_root_agent
from tests.pipeline_fakes import INCIDENT, PR_URL, FakeToolset, ScriptedLlm

PUBLISH_TOOLS = ["create_branch", "push_files", "create_pull_request", "list_pull_requests"]
PASSED = {"passed": True, "stage": "passed", "summary": "new test fails without the fix; all tests pass", "output": ""}


class Pipeline:
    """One ADK app with the real agents, a scripted model and fake MCP servers."""

    def __init__(self, llm: ScriptedLlm | None = None, results: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.rest_calls: list[tuple[str, dict]] = []
        llm = llm or ScriptedLlm()
        toolsets = Toolsets(
            triage=[FakeToolset(["get_incident"], self.calls, results)],
            locator=[FakeToolset(["search_code", "get_file_contents", "list_commits"], self.calls, results)],
            fixer=[FakeToolset(["get_file_contents"], self.calls, results)],
            publisher=[FakeToolset(PUBLISH_TOOLS + ["add_work_note"], self.calls, results)],
        )
        self.root = build_root_agent(llm, llm, toolsets, rest_call=self._rest)
        self.sessions = InMemorySessionService()
        self.runner = Runner(app_name="t", agent=self.root, session_service=self.sessions)
        self.session_id: str | None = None

    async def _rest(self, name: str, args: dict) -> dict:
        self.rest_calls.append((name, args))
        return {"error": "REST not expected in this test"}

    def run(self, message: str = "Please fix INC0010004") -> dict:
        async def go() -> dict:
            if self.session_id is None:
                self.session_id = (await self.sessions.create_session(app_name="t", user_id="u")).id
            content = types.Content(role="user", parts=[types.Part(text=message)])
            async for _ in self.runner.run_async(user_id="u", session_id=self.session_id, new_message=content):
                pass
            session = await self.sessions.get_session(app_name="t", user_id="u", session_id=self.session_id)
            return dict(session.state)

        self.calls.clear()
        return asyncio.run(go())

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def notes(self) -> list[str]:
        return [args["text"] for name, args in self.calls if name == "add_work_note"]


@pytest.fixture(autouse=True)
def passing_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """The verifier's run_tests is covered in test_run_tests.py; here it always passes."""
    monkeypatch.setattr(verifier, "run_tests", lambda branch, patch: dict(PASSED))


def test_happy_path_opens_a_pr_and_notes_it() -> None:
    pipeline = Pipeline()

    state = pipeline.run()

    assert pipeline.names() == [
        "get_incident", "get_file_contents", "get_file_contents",  # triage, locator
        # fixer re-reads orders.py: served from the cache, so no call reaches GitHub
        "create_branch", "push_files", "create_pull_request", "add_work_note",
    ]
    assert state["pr_url"] == PR_URL
    assert state["stop_reason"] is None
    assert state["branch"] == "bug/07"
    assert pipeline.notes() == [f"Pull request opened: {PR_URL}"]
    assert state["tool_calls"] == 9  # 1 + 2 + 1 (cached, still counted) + run_tests + 4


def test_second_run_in_the_same_session_gets_a_fresh_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guardrails, "TOOL_CALL_BUDGET", 12)  # one run uses 9; two would use 18
    pipeline = Pipeline()

    first = pipeline.run()
    second = pipeline.run()

    assert first["pr_url"] == second["pr_url"] == PR_URL
    assert second["tool_calls"] == 9
    assert second["stop_reason"] is None
    assert pipeline.notes() == [f"Pull request opened: {PR_URL}"]


@pytest.mark.parametrize(
    ("budget", "stopped_in", "calls_made"),
    [
        (0, "triage", []),
        (1, "locator", ["get_incident"]),
        (3, "fixer", ["get_incident", "get_file_contents", "get_file_contents"]),
        (4, "verifier", ["get_incident", "get_file_contents", "get_file_contents"]),
        (5, "publisher", ["get_incident", "get_file_contents", "get_file_contents"]),
    ],
)
def test_budget_stop_in_each_agent_ends_cleanly_with_one_work_note(
    monkeypatch: pytest.MonkeyPatch, budget: int, stopped_in: str, calls_made: list[str]
) -> None:
    monkeypatch.setattr(guardrails, "TOOL_CALL_BUDGET", budget)
    pipeline = Pipeline()

    state = pipeline.run()  # must not raise

    assert state["stop_reason"] == "budget", stopped_in
    assert pipeline.names() == calls_made + ["add_work_note"]
    (note,) = pipeline.notes()
    assert "tool calls reached" in note
    assert state.get("pr_url") is None
    assert pipeline.rest_calls == []


def test_budget_stop_leaves_schema_valid_output_in_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guardrails, "TOOL_CALL_BUDGET", 1)  # stops in the locator
    pipeline = Pipeline()

    state = pipeline.run()

    assert state["decision"]["decision"] == "fix"
    assert state["suspect_files"] == []
    assert "patch" not in state or state["patch"] is None  # fix_loop never ran


def test_escalated_incident_stops_with_one_work_note() -> None:
    pipeline = Pipeline(results={"get_incident": {"structuredContent": {**INCIDENT, "category": "hardware"},
                                                  "content": [], "isError": False}})

    state = pipeline.run()

    assert state["stop_reason"] == "escalate"
    assert pipeline.names() == ["get_incident", "add_work_note"]
    assert pipeline.notes()[0].startswith("Escalated by triage, no PR opened: Category is not software_defect.")


def test_tests_failing_twice_stops_with_one_work_note(monkeypatch: pytest.MonkeyPatch) -> None:
    failed = {"passed": False, "stage": "after_fix", "summary": "tests fail with the fix (pytest exit 1)",
              "output": "FAILED tests/test_orders.py::test_zero_quantity"}
    monkeypatch.setattr(verifier, "run_tests", lambda branch, patch: dict(failed))
    pipeline = Pipeline()

    state = pipeline.run()

    assert state["stop_reason"] == "tests_failed"
    assert "create_pull_request" not in pipeline.names()
    (note,) = pipeline.notes()
    assert "not approved after 2 attempts" in note and "FAILED tests/test_orders.py::test_zero_quantity" in note


def test_tool_exception_in_an_llm_agent_is_reported_not_raised() -> None:
    pipeline = Pipeline(results={"get_file_contents": RuntimeError("GitHub MCP exploded")})

    state = pipeline.run()  # must not raise

    assert state["pr_url"] == PR_URL  # the scripted model carries on after the error result


def test_create_pull_request_exception_is_confirmed_via_list_pull_requests() -> None:
    listed = {"content": [{"type": "text", "text": f'[{{"html_url": "{PR_URL}", "head": {{"ref": "fix/INC0010004"}}}}]'}],
              "isError": False}
    pipeline = Pipeline(results={
        "create_pull_request": ValueError("1 validation error for UiWidget id: Input should be a valid string"),
        "list_pull_requests": listed,
    })

    state = pipeline.run()

    assert state["pr_url"] == PR_URL
    assert pipeline.names()[-3:] == ["create_pull_request", "list_pull_requests", "add_work_note"]
    assert pipeline.rest_calls == []
