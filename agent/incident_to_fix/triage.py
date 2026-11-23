"""Triage: reads the incident, picks the branch and decides fix or escalate."""
import json
import re
from typing import Any, Literal

from google.adk.agents.callback_context import CallbackContext
from google.adk.tools import BaseTool, ToolContext
from pydantic import BaseModel, Field

from .config import DEFECT_CATEGORY
from .guardrails import is_allowed_repo

DEFAULT_BRANCH = "main"
_BRANCH_RE = re.compile(r"\bbranch\s+[`'\"]?(bug/\d{2})\b", re.IGNORECASE)


class TriageDecision(BaseModel):
    decision: Literal["fix", "escalate"]
    reason: str = Field(description="One sentence explaining the decision.")


def parse_branch(text: str) -> str:
    """Return `bug/NN` when the text says "branch bug/NN", else `main`."""
    match = _BRANCH_RE.search(text or "")
    return match.group(1).lower() if match else DEFAULT_BRANCH


def extract_incident(tool_response: Any) -> dict | None:
    """Pull the incident dict out of an MCP tool result (structured or JSON text)."""
    if not isinstance(tool_response, dict) or tool_response.get("isError"):
        return None
    structured = tool_response.get("structuredContent") or tool_response.get("structured_content")
    if isinstance(structured, dict) and "number" in structured:
        return structured
    for part in tool_response.get("content") or []:
        try:
            data = json.loads(part.get("text", ""))
        except (AttributeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "number" in data:
            return data
    return None


def record_incident(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: Any
) -> None:
    """after_tool_callback: write incident and branch to state in code, not by the model."""
    if tool.name != "get_incident":
        return None
    incident = extract_incident(tool_response)
    if incident is None:
        return None
    tool_context.state["incident"] = incident
    text = f"{incident.get('short_description', '')}\n{incident.get('description', '')}"
    tool_context.state["branch"] = parse_branch(text)
    return None


def gate_decision(callback_context: CallbackContext) -> None:
    """after_agent_callback: only a software defect in the allow-listed repo can be fixed."""
    state = callback_context.state
    incident = state.get("incident") or {}
    decision = state.get("decision") or {}
    if not isinstance(decision, dict):
        decision = {"decision": "escalate", "reason": "Triage returned no structured decision."}
    if not incident:
        decision = {"decision": "escalate", "reason": "Incident could not be read."}
    elif incident.get("category") != DEFECT_CATEGORY:
        decision = {"decision": "escalate", "reason": f"Category is not {DEFECT_CATEGORY}."}
    elif not is_allowed_repo(str(incident.get("u_repo", ""))):
        decision = {"decision": "escalate", "reason": "u_repo is not on the allow-list."}
    state["decision"] = decision
    return None
