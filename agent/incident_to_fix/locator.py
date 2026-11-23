"""Locator: ranks at most 3 suspect source files (not tests), each with a one-line reason."""
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from pydantic import BaseModel, Field

MAX_SUSPECT_FILES = 3
_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$", re.IGNORECASE
)


class SuspectFile(BaseModel):
    path: str = Field(description="Repo-relative path of a non-test source file.")
    reason: str = Field(description="One line on why this file is suspect; name related tests.")


class LocatorResult(BaseModel):
    suspect_files: list[SuspectFile] = Field(max_length=MAX_SUSPECT_FILES)


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH_RE.search(path.strip().lstrip("/")))


def cap_suspect_files(value: Any) -> list[dict]:
    """At most 3 non-test files, each with a single-line reason, whatever the model returned."""
    files = value.get("suspect_files", []) if isinstance(value, dict) else value
    if not isinstance(files, list):
        return []
    capped = []
    for item in files:
        if not isinstance(item, dict) or not item.get("path") or is_test_path(str(item["path"])):
            continue
        lines = str(item.get("reason", "")).strip().splitlines()
        capped.append({"path": item["path"], "reason": lines[0] if lines else ""})
    return capped[:MAX_SUSPECT_FILES]


def store_suspect_files(callback_context: CallbackContext) -> None:
    """after_agent_callback: normalise suspect_files in state."""
    state = callback_context.state
    state["suspect_files"] = cap_suspect_files(state.get("suspect_files"))
    return None
