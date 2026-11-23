"""Locator: ranks at most 3 suspect files in the target repo, each with a one-line reason."""
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.genai import types
from pydantic import BaseModel, Field

MAX_SUSPECT_FILES = 3


class SuspectFile(BaseModel):
    path: str = Field(description="Repo-relative file path.")
    reason: str = Field(description="One line on why this file is suspect.")


class LocatorResult(BaseModel):
    suspect_files: list[SuspectFile] = Field(max_length=MAX_SUSPECT_FILES)


def cap_suspect_files(value: Any) -> list[dict]:
    """At most 3 files, each with a single-line reason, whatever the model returned."""
    files = value.get("suspect_files", []) if isinstance(value, dict) else value or []
    capped = []
    for item in files[:MAX_SUSPECT_FILES]:
        if isinstance(item, dict) and item.get("path"):
            lines = str(item.get("reason", "")).strip().splitlines()
            capped.append({"path": item["path"], "reason": lines[0] if lines else ""})
    return capped


def skip_unless_fix(callback_context: CallbackContext) -> types.Content | None:
    """before_agent_callback: the locator only runs when triage decided to fix."""
    decision = callback_context.state.get("decision") or {}
    if isinstance(decision, dict) and decision.get("decision") == "fix":
        return None
    return types.Content(role="model", parts=[types.Part(text="Skipped: triage did not decide to fix.")])


def store_suspect_files(callback_context: CallbackContext) -> None:
    """after_agent_callback: normalise suspect_files in state."""
    state = callback_context.state
    state["suspect_files"] = cap_suspect_files(state.get("suspect_files"))
    return None
