"""EARS (specs/01-agents.md): WHEN get_file_contents is called again with the same path and
ref in a session, the system SHALL return the cached result without calling GitHub."""
from types import SimpleNamespace
from typing import Any

import pytest

from agent.incident_to_fix.agent import fixer, locator
from agent.incident_to_fix.file_cache import serve_cached_file, store_file
from agent.incident_to_fix.guardrails import enforce_allow_list, enforce_budget

GET_FILE = SimpleNamespace(name="get_file_contents")
REPO = {"owner": "alokranjan04", "repo": "incident-to-fix-demo"}
ORDERS = {**REPO, "path": "app/routes/orders.py", "ref": "refs/heads/bug/07"}
FILE_RESULT = {"content": [{"type": "text", "text": "def create_order(): ..."}], "isError": False}


class FakeGitHub:
    """Runs ADK's callback order for one tool call: before callbacks, tool, after callback."""

    def __init__(self) -> None:
        self.calls = 0
        self.tool_context = SimpleNamespace(state={})

    def get_file_contents(self, args: dict[str, Any], response: dict = FILE_RESULT) -> dict:
        for before in (enforce_allow_list, serve_cached_file):
            result = before(GET_FILE, args, self.tool_context)
            if result is not None:
                return result
        self.calls += 1
        store_file(GET_FILE, args, self.tool_context, response)
        return response


def test_same_path_and_ref_is_read_from_github_once() -> None:
    github = FakeGitHub()

    first = github.get_file_contents(ORDERS)
    second = github.get_file_contents(ORDERS)

    assert first == second == FILE_RESULT
    assert github.calls == 1


def test_equivalent_ref_and_path_spellings_share_a_cache_entry() -> None:
    github = FakeGitHub()

    github.get_file_contents(ORDERS)
    github.get_file_contents({**ORDERS, "path": "/app/routes/orders.py", "ref": "bug/07"})

    assert github.calls == 1


def test_different_ref_or_path_is_fetched_again() -> None:
    github = FakeGitHub()

    github.get_file_contents(ORDERS)
    github.get_file_contents({**ORDERS, "ref": "refs/heads/main"})
    github.get_file_contents({**ORDERS, "path": "app/services/pricing.py"})

    assert github.calls == 3


def test_errors_are_not_cached() -> None:
    github = FakeGitHub()
    error = {"content": [{"type": "text", "text": "rate limited"}], "isError": True}

    github.get_file_contents(ORDERS, response=error)
    github.get_file_contents(ORDERS)

    assert github.calls == 2


def test_cache_is_per_session() -> None:
    first_session, second_session = FakeGitHub(), FakeGitHub()

    first_session.get_file_contents(ORDERS)
    second_session.get_file_contents(ORDERS)

    assert first_session.calls == second_session.calls == 1


def test_other_tools_are_not_cached() -> None:
    tool_context = SimpleNamespace(state={})
    list_commits = SimpleNamespace(name="list_commits")

    store_file(list_commits, {**REPO, "sha": "main"}, tool_context, FILE_RESULT)

    assert serve_cached_file(list_commits, {**REPO, "sha": "main"}, tool_context) is None
    assert tool_context.state == {}


@pytest.mark.parametrize("agent", [locator, fixer], ids=lambda a: a.name)
def test_allow_list_runs_before_the_cache(agent: Any) -> None:
    assert agent.before_tool_callback == [enforce_budget, enforce_allow_list, serve_cached_file]
    assert agent.after_tool_callback is store_file
