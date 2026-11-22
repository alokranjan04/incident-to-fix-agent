"""ServiceNow MCP server (spec: specs/02-mcp-servers.md).

Tools: get_incident, add_work_note, set_state. Uses the Table API on `incident`.
Credentials come from SNOW_INSTANCE_URL, SNOW_USER, SNOW_PASSWORD: injected by Secret Manager
on Cloud Run, loaded from `.env` for local runs.
"""
import logging
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

load_dotenv(override=False)

log = logging.getLogger(__name__)

mcp = FastMCP("servicenow")

INCIDENT_PATH = "/api/now/table/incident"
INCIDENT_FIELDS = ("number", "short_description", "description", "category", "u_repo", "state")
WORK_NOTE_MAX_CHARS = 4000
TRUNCATION_MARKER = "… [truncated]"
STATE_LABELS = {
    "1": "New",
    "2": "In Progress",
    "3": "On Hold",
    "6": "Resolved",
    "7": "Closed",
    "8": "Canceled",
}
ALLOWED_STATES = {"in_progress": "2"}
TIMEOUT_SECONDS = 30
_NUMBER_RE = re.compile(r"^[A-Za-z0-9]+$")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ToolError(f"{name} is not set")
    return value


def _request(method: str, path: str, **kwargs: Any) -> dict:
    """Call the Table API. Logs method, path and status only: never auth or headers."""
    url = _env("SNOW_INSTANCE_URL").rstrip("/") + path
    response = requests.request(
        method,
        url,
        auth=(_env("SNOW_USER"), _env("SNOW_PASSWORD")),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=TIMEOUT_SECONDS,
        **kwargs,
    )
    log.info("ServiceNow %s %s -> %s", method, path, response.status_code)
    if not response.ok:
        raise ToolError(f"ServiceNow {method} {path} failed with HTTP {response.status_code}")
    return response.json()


def _check_number(number: str) -> str:
    number = number.strip()
    if not _NUMBER_RE.match(number):
        raise ToolError(f"Invalid incident number: {number!r}")
    return number


def _find_incident(number: str, fields: tuple[str, ...]) -> dict:
    number = _check_number(number)
    body = _request(
        "GET",
        INCIDENT_PATH,
        params={
            "sysparm_query": f"number={number}",
            "sysparm_fields": ",".join(fields),
            "sysparm_limit": "1",
        },
    )
    rows = body.get("result") or []
    if not rows:
        raise ToolError(f"Incident {number} not found")
    return rows[0]


def _truncate(text: str) -> str:
    if len(text) <= WORK_NOTE_MAX_CHARS:
        return text
    return text[: WORK_NOTE_MAX_CHARS - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


def _update_incident(number: str, changes: dict[str, str]) -> None:
    sys_id = _find_incident(number, ("sys_id",))["sys_id"]
    _request("PATCH", f"{INCIDENT_PATH}/{sys_id}", json=changes)


@mcp.tool
def get_incident(number: str) -> dict:
    """Read an incident by number (e.g. INC0010004). Read-only."""
    row = _find_incident(number, INCIDENT_FIELDS)
    incident = {field: row.get(field, "") for field in INCIDENT_FIELDS}
    incident["state_label"] = STATE_LABELS.get(incident["state"], "Unknown")
    return incident


@mcp.tool
def add_work_note(number: str, text: str) -> str:
    """Add a work note to an incident. Text over 4,000 characters is truncated."""
    _update_incident(number, {"work_notes": _truncate(text)})
    return "ok"


@mcp.tool
def set_state(number: str, state: str) -> str:
    """Set an incident's state. Only "in_progress" is allowed; never resolves or closes."""
    if state not in ALLOWED_STATES:
        raise ToolError(f"State {state!r} is not allowed; only 'in_progress' is permitted")
    _update_incident(number, {"state": ALLOWED_STATES[state]})
    return "ok"


if __name__ == "__main__":
    mcp.run()
