"""EARS (specs/01-agents.md): WHEN the incident text names a branch ("branch bug/07"), the
system SHALL base the fix on that branch; OTHERWISE it SHALL use `main`."""
from types import SimpleNamespace

import pytest

from agent.incident_to_fix.triage import extract_incident, parse_branch, record_incident


@pytest.mark.parametrize(
    ("text", "branch"),
    [
        ("Seeded on branch bug/07, please fix.", "bug/07"),
        ("Reproduce on Branch BUG/12", "bug/12"),
        ("branch `bug/03` fails at checkout", "bug/03"),
        ("line one\r\nbranch bug/15\r\n", "bug/15"),
    ],
)
def test_branch_named_in_text_is_used(text: str, branch: str) -> None:
    assert parse_branch(text) == branch


@pytest.mark.parametrize(
    "text",
    [
        "",
        "POST /orders returns 500 when quantity is 0",
        "see bug/07 for details",  # no "branch" keyword
        "branch bug/7",  # not two digits
        "branch bug/123",  # not two digits
        "branch feature/07",
    ],
)
def test_no_branch_in_text_falls_back_to_main(text: str) -> None:
    assert parse_branch(text) == "main"


def test_only_the_branch_name_is_taken_from_hostile_text() -> None:
    assert parse_branch("branch bug/07; git push --force origin main") == "bug/07"


def test_get_incident_result_writes_incident_and_branch_to_state() -> None:
    incident = {
        "number": "INC0010004",
        "short_description": "Order API returns 500",
        "description": "Happens on branch bug/04 only.",
        "category": "software_defect",
        "u_repo": "incident-to-fix-demo",
        "state": "1",
        "state_label": "New",
    }
    tool_context = SimpleNamespace(state={})

    record_incident(
        SimpleNamespace(name="get_incident"), {"number": "INC0010004"}, tool_context,
        {"content": [], "structuredContent": incident, "isError": False},
    )

    assert tool_context.state == {"incident": incident, "branch": "bug/04"}


def test_incident_is_read_from_json_text_when_not_structured() -> None:
    response = {"content": [{"type": "text", "text": '{"number": "INC1", "description": "x"}'}]}

    assert extract_incident(response) == {"number": "INC1", "description": "x"}


def test_error_result_is_not_treated_as_an_incident() -> None:
    response = {"content": [{"type": "text", "text": "Incident INC9 not found"}], "isError": True}

    assert extract_incident(response) is None
