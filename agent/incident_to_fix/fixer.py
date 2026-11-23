"""Fixer: writes the patch (full new file contents) including a test under tests/."""
from pathlib import PurePosixPath
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from pydantic import BaseModel, Field

from .config import MAX_FILES_PER_PR
from .guardrails import is_protected_path

PATCH_KEY = "patch"
DROPPED_KEY = "dropped_changes"


class FileChange(BaseModel):
    path: str = Field(description="Repo-relative path, e.g. app/routes/orders.py or tests/test_orders.py.")
    new_content: str = Field(description="The complete new content of the file.")


class Patch(BaseModel):
    files: list[FileChange] = Field(max_length=MAX_FILES_PER_PR)


def normalise_path(path: str) -> str:
    return str(PurePosixPath(path.strip().replace("\\", "/").lstrip("/")))


def is_test_change(path: str) -> bool:
    return normalise_path(path).startswith("tests/")


def sanitise_patch(value: Any) -> tuple[list[dict], list[str]]:
    """Drop protected paths and anything past the file limit. Returns (kept, dropped reasons)."""
    files = value.get("files", []) if isinstance(value, dict) else value or []
    kept: list[dict] = []
    dropped: list[str] = []
    for item in files:
        if not isinstance(item, dict) or not item.get("path") or not isinstance(item.get("new_content"), str):
            continue
        path = normalise_path(str(item["path"]))
        if is_protected_path(path):
            dropped.append(f"{path}: protected path")
        elif any(f["path"] == path for f in kept):
            continue
        elif len(kept) >= MAX_FILES_PER_PR:
            dropped.append(f"{path}: over the {MAX_FILES_PER_PR}-file limit")
        else:
            kept.append({"path": path, "new_content": item["new_content"]})
    return kept, dropped


def store_patch(callback_context: CallbackContext) -> None:
    """after_agent_callback: enforce the patch guardrails in code before anything runs it."""
    state = callback_context.state
    kept, dropped = sanitise_patch(state.get(PATCH_KEY))
    state[PATCH_KEY] = kept
    earlier = list(state.get(DROPPED_KEY) or [])
    state[DROPPED_KEY] = earlier + [d for d in dropped if d not in earlier]
    return None
