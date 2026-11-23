"""Guardrail (specs/03-guardrails.md): repo allow-list is `alokranjan04/incident-to-fix-demo`
only, enforced in before_tool_callback. Also the triage gate (specs/01-agents.md): only a
`software_defect` with `u_repo` on the allow-list can go ahead."""
from types import SimpleNamespace
from typing import Any

import pytest

from agent.incident_to_fix.guardrails import enforce_allow_list, is_allowed_repo
from agent.incident_to_fix.triage import gate_decision

REPO = {"owner": "alokranjan04", "repo": "incident-to-fix-demo"}


def call(tool_name: str, args: dict[str, Any]) -> dict | None:
    return enforce_allow_list(SimpleNamespace(name=tool_name), args, SimpleNamespace(state={}))


# --- Allowed calls run (callback returns None) ----------------------------------------

@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("get_incident", {"number": "INC0010004"}),
        ("get_file_contents", {**REPO, "path": "app/routes/orders.py", "ref": "refs/heads/bug/07"}),
        ("get_file_contents", {"owner": "AlokRanjan04", "repo": "Incident-To-Fix-Demo", "path": "x"}),
        ("list_commits", {**REPO, "sha": "bug/07"}),
        ("search_code", {"query": "quantity repo:alokranjan04/incident-to-fix-demo"}),
        ("search_code", {"query": 'repo:"alokranjan04/incident-to-fix-demo" language:python total'}),
        ("add_work_note", {"number": "INC0010004", "text": "x"}),
        ("create_branch", {**REPO, "branch": "fix/INC0010004", "from_branch": "bug/07"}),
        ("create_pull_request", {**REPO, "title": "x", "head": "fix/INC0010004", "base": "bug/07"}),
    ],
)
def test_calls_on_the_allowed_repo_run(tool: str, args: dict) -> None:
    assert call(tool, args) is None


# --- Blocked calls are skipped (callback returns an error dict) -----------------------

@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("get_file_contents", {"owner": "someone-else", "repo": "incident-to-fix-demo", "path": "x"}),
        ("get_file_contents", {"owner": "alokranjan04", "repo": "other-repo", "path": "x"}),
        ("get_file_contents", {"path": "x"}),
        ("list_commits", {"owner": "alokranjan04", "repo": "incident-to-fix-agent"}),
        ("search_code", {"query": "password"}),
        ("search_code", {"query": "token repo:alokranjan04/incident-to-fix-agent"}),
        ("search_code", {"query": "x repo:alokranjan04/incident-to-fix-demo repo:evil/repo"}),
        ("search_code", {"query": "x repo:alokranjan04/incident-to-fix-demo org:github"}),
        ("search_code", {"query": "x repo:alokranjan04/incident-to-fix-demo user:alokranjan04"}),
        ("search_code", {"query": "x repo:alokranjan04/incident-to-fix-demo-fork"}),
        ("create_pull_request", {**REPO, "title": "x"}),
        ("push_files", {**REPO, "branch": "main"}),
        ("create_branch", {**REPO, "branch": "main", "from_branch": "bug/07"}),
        ("create_pull_request", {**REPO, "title": "x", "head": "main", "base": "bug/07"}),
        ("merge_pull_request", {**REPO, "pullNumber": 1}),
        ("delete_branch", {**REPO, "branch": "fix/INC0010004"}),
        ("set_state", {"number": "INC0010004", "state": "resolved"}),
    ],
)
def test_calls_outside_the_allow_list_are_blocked(tool: str, args: dict) -> None:
    result = call(tool, args)

    assert isinstance(result, dict)
    assert result["error"].startswith("Blocked by guardrail")


@pytest.mark.parametrize(
    ("repo", "allowed"),
    [
        ("incident-to-fix-demo", True),
        ("alokranjan04/incident-to-fix-demo", True),
        (" Incident-To-Fix-Demo ", True),
        ("incident-to-fix-agent", False),
        ("someone-else/incident-to-fix-demo", False),
        ("", False),
    ],
)
def test_u_repo_allow_list(repo: str, allowed: bool) -> None:
    assert is_allowed_repo(repo) is allowed


# --- Triage gate: decision is forced to escalate in code ------------------------------

def _gate(incident: dict | None, decision: Any) -> dict:
    state = {"incident": incident, "decision": decision}
    gate_decision(SimpleNamespace(state=state))
    return state["decision"]


FIX = {"decision": "fix", "reason": "Division by zero in create_order."}
DEFECT = {"number": "INC1", "category": "software_defect", "u_repo": "incident-to-fix-demo"}


def test_defect_in_allowed_repo_keeps_the_fix_decision() -> None:
    assert _gate(DEFECT, FIX) == FIX


@pytest.mark.parametrize(
    "incident",
    [
        {**DEFECT, "u_repo": "incident-to-fix-agent"},
        {**DEFECT, "u_repo": "someone-else/incident-to-fix-demo"},
        {**DEFECT, "category": "hardware"},
        None,
    ],
)
def test_fix_is_overridden_to_escalate_outside_the_allow_list(incident: dict | None) -> None:
    assert _gate(incident, FIX)["decision"] == "escalate"


def test_unstructured_decision_escalates() -> None:
    assert _gate(DEFECT, "fix it!")["decision"] == "escalate"
