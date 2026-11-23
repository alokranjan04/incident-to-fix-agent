"""Publisher (specs/01-agents.md, 03-guardrails.md):
- WHEN a PR is opened, the system SHALL put the incident number in the PR title and SHALL add
  the PR URL to the incident's work notes.
- WHEN triage decides the incident is not a code defect, the system SHALL add a work note
  explaining why and SHALL stop without opening a PR.
- IF tests fail after 2 fix attempts, THEN the system SHALL add a work note with the failing
  output and SHALL NOT open a PR.
- IF any budget limit is reached, THEN the system SHALL stop and add a work note with progress.
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
    """Records MCP calls that got past the guardrails and returns canned results."""

    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail

    async def __call__(self, name: str, args: dict) -> Any:
        self.calls.append((name, args))
        if name == self.fail:
            return {"content": [{"type": "text", "text": "reference already exists"}], "isError": True}
        if name == "create_pull_request":
            return {"content": [{"type": "text", "text": json.dumps({"id": "1", "url": PR_URL})}], "isError": False}
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def args(self, name: str) -> dict:
        return next(args for n, args in self.calls if n == name)


def run(state: dict, tools: FakeTools, budget: dict | None = None) -> dict:
    return asyncio.run(publish(state, guarded(tools, budget if budget is not None else {})))


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


def test_publish_failure_adds_a_work_note_and_stops() -> None:
    tools = FakeTools(fail="create_branch")

    delta = run(approved_state(), tools)

    assert tools.names() == ["create_branch", "add_work_note"]
    assert "create_branch failed: reference already exists" in tools.args("add_work_note")["text"]
    assert "pr_url" not in delta


# --- Escalate path: work note, no PR ----------------------------------------------------

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
    state = {"incident": INCIDENT, "branch": "main", "decision": decision}

    delta = run(state, tools)

    assert tools.names() == ["add_work_note"]
    text = tools.args("add_work_note")["text"]
    assert text.startswith("Escalated by triage, no PR opened") and expected in text
    assert "pr_url" not in delta


def test_still_failing_after_2_attempts_notes_the_failing_output_and_opens_no_pr() -> None:
    tools = FakeTools()
    state = approved_state(
        test_result={"passed": False, "stage": "after_fix", "summary": "tests fail with the fix (pytest exit 1)",
                     "output": "FAILED tests/test_orders.py::test_zero_quantity - ZeroDivisionError"},
        review={"verdict": "revise", "reasons": ["Tests did not pass."]},
    )

    run(state, tools)

    assert tools.names() == ["add_work_note"]
    text = tools.args("add_work_note")["text"]
    assert "not approved after 2 attempts" in text
    assert "FAILED tests/test_orders.py::test_zero_quantity - ZeroDivisionError" in text


def test_budget_reached_notes_progress_and_opens_no_pr() -> None:
    tools = FakeTools()

    run(approved_state(budget_exceeded=True), tools)

    assert tools.names() == ["add_work_note"]
    text = tools.args("add_work_note")["text"]
    assert "budget of 40 tool calls reached" in text
    assert "Suspect files: app/routes/orders.py" in text


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
        ({"content": [{"type": "text", "text": json.dumps({"html_url": PR_URL})}]}, PR_URL),
        ({"structuredContent": {"url": PR_URL}, "content": []}, PR_URL),
        ({"content": [{"type": "text", "text": json.dumps({"url": "https://evil.example/pr/1"})}]}, None),
        ({"content": [{"type": "text", "text": "not json"}]}, None),
    ],
)
def test_pr_url_is_taken_only_from_github(result: dict, url: str | None) -> None:
    assert extract_pr_url(result) == url
