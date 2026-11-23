"""Publisher (specs/01-agents.md, 03-guardrails.md):
- WHEN a PR is opened, the system SHALL put the incident number in the PR title and SHALL add
  the PR URL to the incident's work notes.
- WHEN triage decides the incident is not a code defect, the system SHALL add a work note
  explaining why and SHALL stop without opening a PR.
- IF tests fail after 2 fix attempts, THEN the system SHALL add a work note with the failing
  output and SHALL NOT open a PR.
- IF any budget limit is reached, THEN the system SHALL stop and add a work note with progress.
- Idempotency: an existing fix/<INC> branch is reused; a PR whose creation response is
  unreadable is confirmed with list_pull_requests, else created via the REST API.
All calls go through `guarded`, the same guardrails the LLM agents' callbacks apply."""
import asyncio
import json
from typing import Any

import pytest

from agent.incident_to_fix.publisher import extract_pr_url, fix_branch, guarded, pr_title, publish

PR_URL = "https://github.com/alokranjan04/incident-to-fix-demo/pull/12"
INCIDENT = {"number": "INC0010004", "short_description": "Order API returns 500 when quantity is 0"}
PATCH = [
    {"path": "app/routes/orders.py", "new_content": "fixed\n"},
    {"path": "tests/test_orders.py", "new_content": "test\n"},
]
OK = {"content": [{"type": "text", "text": "ok"}], "isError": False}


def text_result(payload: Any) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


def error_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


CREATED_PR = text_result({"id": "1", "url": PR_URL})
UNPARSEABLE = {"error": "ValidationError: 1 validation error for UiWidget id: Input should be a valid string"}


def approved_state(**overrides: Any) -> dict:
    return {
        "incident": INCIDENT,
        "branch": "bug/07",
        "decision": {"decision": "fix", "reason": "Code defect."},
        "suspect_files": [{"path": "app/routes/orders.py", "reason": "divides by quantity"}],
        "patch": PATCH,
        "test_result": {"passed": True, "stage": "passed", "summary": "all tests pass", "output": ""},
        "review": {"verdict": "approve", "reasons": ["Scope ok", "Security ok", "Test added", "No protected paths"]},
        **overrides,
    }


class FakeTools:
    """Records calls that got past the guardrails and returns canned results by tool name."""

    def __init__(self, **results: Any) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.results = {"create_pull_request": CREATED_PR, "list_pull_requests": text_result([]), **results}

    async def __call__(self, name: str, args: dict) -> Any:
        self.calls.append((name, args))
        return self.results.get(name, OK)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def args(self, name: str) -> dict:
        return next(args for n, args in self.calls if n == name)


def run(state: dict, tools: FakeTools, rest: FakeTools | None = None, budget: dict | None = None) -> dict:
    budget = budget if budget is not None else {}
    rest = rest or FakeTools(create_pull_request={"error": "REST should not be called"})
    return asyncio.run(publish(state, guarded(tools, budget), guarded(rest, budget)))


# --- PR title format -------------------------------------------------------------------

def test_pr_title_starts_with_the_incident_number() -> None:
    assert pr_title(INCIDENT) == "INC0010004: Order API returns 500 when quantity is 0"


def test_pr_title_is_one_line_and_capped() -> None:
    title = pr_title({"number": "INC0010004", "short_description": "Line one\r\nline two " + "x" * 300})

    assert title.startswith("INC0010004: Line one line two ")
    assert "\n" not in title and len(title) <= 120


def test_fix_branch_is_named_after_the_incident() -> None:
    assert fix_branch("INC0010004") == "fix/INC0010004"


# --- Happy path: branch, push, PR, work note with URL -----------------------------------

def test_approved_fix_opens_a_pr_from_the_incident_branch_and_notes_the_url() -> None:
    tools = FakeTools()

    delta = run(approved_state(), tools)

    assert tools.names() == ["create_branch", "push_files", "create_pull_request", "add_work_note"]
    assert tools.args("create_branch")["branch"] == "fix/INC0010004"
    assert tools.args("create_branch")["from_branch"] == "bug/07"
    assert tools.args("push_files")["files"] == [
        {"path": "app/routes/orders.py", "content": "fixed\n"},
        {"path": "tests/test_orders.py", "content": "test\n"},
    ]
    pr = tools.args("create_pull_request")
    assert (pr["head"], pr["base"]) == ("fix/INC0010004", "bug/07")
    assert pr["title"].startswith("INC0010004: ")
    assert tools.args("add_work_note") == {"number": "INC0010004", "text": f"Pull request opened: {PR_URL}"}
    assert delta["pr_url"] == PR_URL


# --- Idempotency and resilience ---------------------------------------------------------

def test_existing_fix_branch_is_reused() -> None:
    tools = FakeTools(create_branch=error_result("Reference already exists"))

    delta = run(approved_state(), tools)

    assert tools.names() == ["create_branch", "push_files", "create_pull_request", "add_work_note"]
    assert tools.args("push_files")["branch"] == "fix/INC0010004"
    assert delta["pr_url"] == PR_URL


def test_other_create_branch_errors_stop_with_one_work_note() -> None:
    tools = FakeTools(create_branch=error_result("Not Found"))

    delta = run(approved_state(), tools)

    assert tools.names() == ["create_branch", "add_work_note"]
    assert "create_branch failed: Not Found" in tools.args("add_work_note")["text"]
    assert "pr_url" not in delta


def test_unreadable_pr_response_is_confirmed_with_list_pull_requests() -> None:
    listed = text_result([{"number": 12, "html_url": PR_URL, "head": {"ref": "fix/INC0010004"}}])
    tools = FakeTools(create_pull_request=UNPARSEABLE, list_pull_requests=listed)

    delta = run(approved_state(), tools)

    assert tools.names() == ["create_branch", "push_files", "create_pull_request", "list_pull_requests", "add_work_note"]
    assert tools.args("list_pull_requests") == {
        "owner": "alokranjan04", "repo": "incident-to-fix-demo", "head": "alokranjan04:fix/INC0010004", "state": "open",
    }
    assert tools.args("add_work_note")["text"] == f"Pull request opened: {PR_URL}"
    assert delta["pr_url"] == PR_URL


def test_pr_from_another_branch_does_not_count_as_confirmation() -> None:
    other = text_result([{"html_url": PR_URL.replace("12", "99"), "head": {"ref": "fix/INC0000001"}}])
    rest = FakeTools(create_pull_request={"structuredContent": {"html_url": PR_URL}})
    tools = FakeTools(create_pull_request=UNPARSEABLE, list_pull_requests=other)

    delta = run(approved_state(), tools, rest=rest)

    assert rest.names() == ["create_pull_request"]
    assert delta["pr_url"] == PR_URL


def test_rest_fallback_creates_the_pr_when_mcp_cannot_confirm_it() -> None:
    rest = FakeTools(create_pull_request={"structuredContent": {"number": 12, "html_url": PR_URL}})
    tools = FakeTools(create_pull_request=UNPARSEABLE, list_pull_requests=text_result([]))

    delta = run(approved_state(), tools, rest=rest)

    assert rest.names() == ["create_pull_request"]
    rest_args = rest.args("create_pull_request")
    assert (rest_args["head"], rest_args["base"]) == ("fix/INC0010004", "bug/07")
    assert rest_args["title"].startswith("INC0010004: ")
    assert tools.args("add_work_note")["text"] == f"Pull request opened: {PR_URL}"
    assert delta["pr_url"] == PR_URL


def test_rest_fallback_failure_ends_with_one_work_note_listing_each_attempt() -> None:
    rest = FakeTools(create_pull_request={"error": "GitHub REST HTTP 422: Validation Failed"})
    tools = FakeTools(create_pull_request=UNPARSEABLE, list_pull_requests=text_result([]))

    delta = run(approved_state(), tools, rest=rest)

    assert tools.names().count("add_work_note") == 1
    text = tools.args("add_work_note")["text"]
    assert text.startswith("No PR opened: could not create or confirm a PR from fix/INC0010004.")
    assert "UiWidget" in text and "no open PR" in text and "HTTP 422" in text
    assert "pr_url" not in delta


def test_rest_fallback_obeys_the_same_guardrails() -> None:
    rest = FakeTools(create_pull_request={"structuredContent": {"html_url": PR_URL}})
    tools = FakeTools(create_pull_request=UNPARSEABLE)
    budget = {"tool_calls": 0}

    # create_branch, push_files, create_pull_request, list_pull_requests use 4; REST is the 5th.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("agent.incident_to_fix.guardrails.TOOL_CALL_BUDGET", 4)
        run(approved_state(), tools, rest=rest, budget=budget)

    assert rest.calls == []
    assert "budget of 4 tool calls reached" in tools.args("add_work_note")["text"]
    assert budget["stop_reason"] == "budget"


# --- One work note explaining why the run stopped --------------------------------------

@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        ({"decision": "escalate", "reason": "Category is not software_defect."}, "Category is not software_defect."),
        ({"decision": "escalate", "reason": "u_repo is not on the allow-list."}, "u_repo is not on the allow-list."),
        (None, "no reason given"),
    ],
)
def test_escalate_adds_a_work_note_and_opens_no_pr(decision: dict | None, expected: str) -> None:
    tools = FakeTools()
    state = {"incident": INCIDENT, "branch": "main", "decision": decision, "stop_reason": "escalate"}

    delta = run(state, tools)

    assert tools.names() == ["add_work_note"]
    text = tools.args("add_work_note")["text"]
    assert text.startswith("Escalated by triage, no PR opened") and expected in text
    assert "pr_url" not in delta


def test_tests_failed_notes_the_failing_output_and_opens_no_pr() -> None:
    tools = FakeTools()
    state = approved_state(
        stop_reason="tests_failed",
        test_result={"passed": False, "stage": "after_fix", "summary": "tests fail with the fix (pytest exit 1)",
                     "output": "FAILED tests/test_orders.py::test_zero_quantity - ZeroDivisionError"},
        review={"verdict": "revise", "reasons": ["Tests did not pass."]},
    )

    run(state, tools)

    assert tools.names() == ["add_work_note"]
    text = tools.args("add_work_note")["text"]
    assert "not approved after 2 attempts" in text
    assert "FAILED tests/test_orders.py::test_zero_quantity - ZeroDivisionError" in text


def test_budget_stop_notes_progress_and_opens_no_pr() -> None:
    tools = FakeTools()

    run(approved_state(stop_reason="budget", suspect_files={"suspect_files": []}), tools)

    assert tools.names() == ["add_work_note"]
    text = tools.args("add_work_note")["text"]
    assert "budget of 40 tool calls reached" in text
    assert "Suspect files: none" in text


def test_dropped_protected_changes_are_explained_in_the_work_note() -> None:
    tools = FakeTools()

    run(approved_state(dropped_changes=["requirements.txt: protected path"]), tools)

    assert "Dropped changes (guardrails): requirements.txt: protected path" in tools.args("add_work_note")["text"]


def test_no_incident_means_no_calls() -> None:
    tools = FakeTools()

    run({}, tools)

    assert tools.calls == []


# --- The publisher's own calls are guarded ---------------------------------------------

def test_budget_blocks_publishing_but_still_allows_the_closing_work_note() -> None:
    tools = FakeTools()

    run(approved_state(), tools, budget={"tool_calls": 40})

    assert tools.names() == ["add_work_note"]
    assert "budget of 40 tool calls reached" in tools.args("add_work_note")["text"]


def test_guard_blocks_push_to_main_even_if_asked() -> None:
    tools = FakeTools()
    call = guarded(tools, {})

    result = asyncio.run(call("push_files", {"owner": "alokranjan04", "repo": "incident-to-fix-demo",
                                             "branch": "main", "files": [], "message": "m"}))

    assert "Blocked by guardrail" in result["error"]
    assert tools.calls == []


@pytest.mark.parametrize(
    ("result", "url"),
    [
        (text_result({"html_url": PR_URL}), PR_URL),
        ({"structuredContent": {"url": PR_URL}, "content": []}, PR_URL),
        (text_result({"url": "https://evil.example/pr/1"}), None),
        (text_result({"html_url": "https://github.com/someone/else/pull/1"}), None),
        ({"content": [{"type": "text", "text": "not json"}]}, None),
        (UNPARSEABLE, None),
    ],
)
def test_pr_url_is_taken_only_from_the_allowed_repo(result: dict, url: str | None) -> None:
    assert extract_pr_url(result) == url
