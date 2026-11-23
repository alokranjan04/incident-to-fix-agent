"""Guardrails (specs/03-guardrails.md): protected paths, at most 3 files per PR, the 40
tool-call budget. IF a planned change touches a protected path, THEN the system SHALL drop
that change (and the publisher adds a work note saying why, see test_publisher.py)."""
from types import SimpleNamespace

import pytest

from agent.incident_to_fix.fixer import sanitise_patch, store_patch
from agent.incident_to_fix.guardrails import (
    enforce_allow_list,
    enforce_budget,
    is_protected_path,
    patch_violation,
)

REPO = {"owner": "alokranjan04", "repo": "incident-to-fix-demo"}


def change(path: str) -> dict:
    return {"path": path, "new_content": "x = 1\n"}


# --- Protected paths -------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "/.github/CODEOWNERS",
        "app/.github/x.yml",
        "requirements.txt",
        "app/requirements.txt",
        ".env",
        "config/.env.production",
        "app/secrets.py",
        "app/client_secret.json",
        "app/token_store.py",
        "app/GitHubToken.py",
        ".github\\workflows\\ci.yml",
    ],
)
def test_protected_paths_are_recognised(path: str) -> None:
    assert is_protected_path(path)


@pytest.mark.parametrize(
    "path", ["app/routes/orders.py", "tests/test_orders.py", "README.md", "requirements-dev.in", "app/github.py"]
)
def test_ordinary_paths_are_not_protected(path: str) -> None:
    assert not is_protected_path(path)


def test_fixer_patch_drops_protected_changes_and_records_why() -> None:
    state = {"patch": {"files": [change("app/routes/orders.py"), change(".github/workflows/ci.yml"),
                                 change("requirements.txt"), change("tests/test_orders.py")]}}

    store_patch(SimpleNamespace(state=state))

    assert [f["path"] for f in state["patch"]] == ["app/routes/orders.py", "tests/test_orders.py"]
    assert state["dropped_changes"] == [
        ".github/workflows/ci.yml: protected path",
        "requirements.txt: protected path",
    ]


def test_push_files_with_a_protected_path_is_blocked() -> None:
    args = {**REPO, "branch": "fix/INC1", "files": [{"path": ".env", "content": "x"}], "message": "m"}

    result = enforce_allow_list(SimpleNamespace(name="push_files"), args, SimpleNamespace(state={}))

    assert result is not None and "protected paths: .env" in result["error"]


# --- At most 3 files per PR ------------------------------------------------------------

def test_fixer_patch_keeps_at_most_3_files() -> None:
    kept, dropped = sanitise_patch([change(f"app/m{i}.py") for i in range(5)])

    assert [f["path"] for f in kept] == ["app/m0.py", "app/m1.py", "app/m2.py"]
    assert dropped == ["app/m3.py: over the 3-file limit", "app/m4.py: over the 3-file limit"]


def test_duplicate_paths_count_once() -> None:
    kept, _ = sanitise_patch([change("app/a.py"), change("/app/a.py"), change("app/b.py")])

    assert [f["path"] for f in kept] == ["app/a.py", "app/b.py"]


def test_patch_violation_limits() -> None:
    assert patch_violation(["a.py", "b.py", "c.py"]) is None
    assert patch_violation(["a.py", "b.py", "c.py", "d.py"]) == "4 files changed; at most 3 allowed"


def test_push_files_with_4_files_is_blocked() -> None:
    files = [{"path": f"app/m{i}.py", "content": "x"} for i in range(4)]
    args = {**REPO, "branch": "fix/INC1", "files": files, "message": "m"}

    result = enforce_allow_list(SimpleNamespace(name="push_files"), args, SimpleNamespace(state={}))

    assert result is not None and "at most 3" in result["error"]


# --- Budget: at most 40 tool calls per incident ----------------------------------------

def test_budget_allows_40_calls_then_blocks() -> None:
    tool, tool_context = SimpleNamespace(name="get_file_contents"), SimpleNamespace(state={})

    results = [enforce_budget(tool, {}, tool_context) for _ in range(41)]

    assert results[:40] == [None] * 40
    assert "budget of 40 tool calls reached" in results[40]["error"]
    assert tool_context.state == {"tool_calls": 41, "budget_exceeded": True}
