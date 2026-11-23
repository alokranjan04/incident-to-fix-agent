"""Tests for the ServiceNow MCP server (specs/02-mcp-servers.md). HTTP is mocked."""
import asyncio
import logging
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_servers.servicenow import server

INCIDENT = {
    "sys_id": "abc123",
    "number": "INC0010004",
    "short_description": "Order total wrong",
    "description": "Discount applied twice",
    "category": "software_defect",
    "u_repo": "alokranjan04/incident-to-fix-demo",
    "state": "1",
}


class FakeResponse:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self.ok = status_code < 400
        self._body = body

    def json(self) -> dict:
        return self._body


class FakeServiceNow:
    """Stands in for requests.request; knows one incident and records every call."""

    def __init__(self, fail_patch: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_patch = fail_patch

    def __call__(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        if method == "GET":
            query = kwargs["params"]["sysparm_query"]
            rows = [INCIDENT] if query == f"number={INCIDENT['number']}" else []
            return FakeResponse(200, {"result": rows})
        if method == "PATCH":
            if self.fail_patch:
                return FakeResponse(403, {"error": {"message": "forbidden"}})
            return FakeResponse(200, {"result": {**INCIDENT, **kwargs["json"]}})
        raise AssertionError(f"unexpected method {method}")

    def patches(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == "PATCH"]


@pytest.fixture
def snow(monkeypatch: pytest.MonkeyPatch, test_password: str) -> FakeServiceNow:
    monkeypatch.setenv("SNOW_INSTANCE_URL", "https://example.service-now.com")
    monkeypatch.setenv("SNOW_USER", "mcp.integration")
    monkeypatch.setenv("SNOW_PASSWORD", test_password)
    fake = FakeServiceNow()
    monkeypatch.setattr(server.requests, "request", fake)
    return fake


def call_tool(name: str, args: dict) -> Any:
    async def go() -> Any:
        async with Client(server.mcp) as client:
            return await client.call_tool(name, args)

    return asyncio.run(go())


# --- Spec: tool table ---------------------------------------------------------------

def test_server_lists_the_three_tools() -> None:
    async def go() -> set[str]:
        async with Client(server.mcp) as client:
            return {t.name for t in await client.list_tools()}

    assert asyncio.run(go()) == {"get_incident", "add_work_note", "set_state"}


def test_get_incident_returns_the_spec_fields(snow: FakeServiceNow, test_password: str) -> None:
    result = server.get_incident("INC0010004")

    assert result == {**{k: INCIDENT[k] for k in server.INCIDENT_FIELDS}, "state_label": "New"}
    call = snow.calls[0]
    assert call["url"] == "https://example.service-now.com/api/now/table/incident"
    assert call["auth"] == ("mcp.integration", test_password)


def test_get_incident_is_read_only(snow: FakeServiceNow) -> None:
    server.get_incident("INC0010004")

    assert [c["method"] for c in snow.calls] == ["GET"]


# --- EARS: WHEN get_incident is called with an unknown number, the server SHALL return
#     a clear "not found" error, not an empty object. --------------------------------

def test_get_incident_unknown_number_returns_not_found_error(snow: FakeServiceNow) -> None:
    with pytest.raises(ToolError, match="Incident INC9999999 not found"):
        call_tool("get_incident", {"number": "INC9999999"})


# --- EARS: The server SHALL never log the password or full request headers. -----------

def test_server_never_logs_password_or_headers(
    snow: FakeServiceNow, caplog: pytest.LogCaptureFixture, test_password: str
) -> None:
    caplog.set_level(logging.DEBUG)
    snow.fail_patch = True

    server.get_incident("INC0010004")
    with pytest.raises(ToolError) as failed_call:
        server.add_work_note("INC0010004", "note")
    with pytest.raises(ToolError) as not_found:
        server.get_incident("INC9999999")

    assert caplog.records, "expected the server to log its requests"
    logged = caplog.text + str(failed_call.value) + str(not_found.value)
    for forbidden in (test_password, "Authorization", "Basic ", "Content-Type", "Accept"):
        assert forbidden not in logged


# --- EARS: WHEN add_work_note is called with text over 4,000 characters, the server
#     SHALL store at most 4,000 characters, ending with "… [truncated]". --------------

def test_add_work_note_truncates_text_over_4000_characters(snow: FakeServiceNow) -> None:
    assert server.add_work_note("INC0010004", "x" * 5000) == "ok"

    (patch,) = snow.patches()
    assert patch["url"].endswith("/api/now/table/incident/abc123")
    note = patch["json"]["work_notes"]
    assert len(note) == 4000
    assert note.endswith("… [truncated]")
    assert note.startswith("x" * (4000 - len("… [truncated]")))


def test_add_work_note_keeps_text_of_4000_characters_unchanged(snow: FakeServiceNow) -> None:
    server.add_work_note("INC0010004", "x" * 4000)

    (patch,) = snow.patches()
    assert patch["json"] == {"work_notes": "x" * 4000}


def test_add_work_note_unknown_number_returns_not_found_error(snow: FakeServiceNow) -> None:
    with pytest.raises(ToolError, match="not found"):
        server.add_work_note("INC9999999", "note")
    assert snow.patches() == []


# --- Spec: set_state only in_progress; never resolve or close -----------------------

def test_set_state_in_progress_sets_state_2(snow: FakeServiceNow) -> None:
    assert server.set_state("INC0010004", "in_progress") == "ok"

    (patch,) = snow.patches()
    assert patch["json"] == {"state": "2"}


@pytest.mark.parametrize("state", ["resolved", "closed", "canceled", "on_hold", "6", "7", "2", ""])
def test_set_state_rejects_anything_but_in_progress(snow: FakeServiceNow, state: str) -> None:
    with pytest.raises(ToolError, match="only 'in_progress'"):
        server.set_state("INC0010004", state)
    assert snow.calls == []


# --- EARS: WHEN any tool is called with an incident number that is not only letters and
#     digits, the server SHALL return an "invalid incident number" error and make no
#     ServiceNow request. ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("tool", "extra"),
    [("get_incident", {}), ("add_work_note", {"text": "note"}), ("set_state", {"state": "in_progress"})],
)
@pytest.mark.parametrize("number", ["INC0010004^ORactive=true", "INC 0010004", "", "INC-1"])
def test_invalid_incident_number_is_rejected_without_a_request(
    snow: FakeServiceNow, tool: str, extra: dict, number: str
) -> None:
    with pytest.raises(ToolError, match="(?i)invalid incident number"):
        call_tool(tool, {"number": number, **extra})
    assert snow.calls == []


# --- EARS: WHEN get_incident returns text fields containing \r\n, the server SHALL
#     replace each \r\n with \n. ---------------------------------------------------------

def test_get_incident_normalises_crlf_to_lf(
    snow: FakeServiceNow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(INCIDENT, "short_description", "Order API returns 500\r\nwhen quantity is 0")
    monkeypatch.setitem(
        INCIDENT,
        "description",
        "POST /orders returns HTTP 500.\r\nExpected: HTTP 400.\r\n\r\n"
        "Traceback (most recent call last):\r\n"
        '  File "app/routes/orders.py", line 42, in create_order\r\n'
        "ZeroDivisionError: division by zero",
    )

    result = call_tool("get_incident", {"number": "INC0010004"}).data

    assert result["short_description"] == "Order API returns 500\nwhen quantity is 0"
    assert result["description"] == (
        "POST /orders returns HTTP 500.\nExpected: HTTP 400.\n\n"
        "Traceback (most recent call last):\n"
        '  File "app/routes/orders.py", line 42, in create_order\n'
        "ZeroDivisionError: division by zero"
    )
    assert all("\r" not in value for value in result.values())


# --- EARS: WHEN get_incident returns an incident, the server SHALL include state_label,
#     the name of its state code. ------------------------------------------------------

@pytest.mark.parametrize(
    ("state", "label"),
    [("1", "New"), ("2", "In Progress"), ("3", "On Hold"), ("6", "Resolved"), ("7", "Closed"),
     ("8", "Canceled"), ("99", "Unknown")],
)
def test_get_incident_includes_state_label(
    snow: FakeServiceNow, monkeypatch: pytest.MonkeyPatch, state: str, label: str
) -> None:
    monkeypatch.setitem(INCIDENT, "state", state)

    result = call_tool("get_incident", {"number": "INC0010004"}).data

    assert result["state"] == state
    assert result["state_label"] == label
