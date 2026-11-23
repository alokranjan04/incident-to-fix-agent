"""Reviewer gate: code vetoes an approval that fails the checklist items it can check, and an
approval exits the fix loop (LoopAgent max_iterations=2, exit on approve)."""
from types import SimpleNamespace

import pytest

from agent.incident_to_fix.agent import fix_loop
from agent.incident_to_fix.reviewer import gate_review

PATCH = [
    {"path": "app/routes/orders.py", "new_content": "fixed\n"},
    {"path": "tests/test_orders.py", "new_content": "test\n"},
]
PASSED = {"passed": True, "stage": "passed", "summary": "ok", "output": ""}
APPROVE = {"verdict": "approve", "reasons": ["All checklist items pass."]}


def gate(**state: object) -> SimpleNamespace:
    ctx = SimpleNamespace(state=dict(state), actions=SimpleNamespace(escalate=None))
    gate_review(ctx)
    return ctx


def test_approval_with_passing_tests_exits_the_loop() -> None:
    ctx = gate(patch=PATCH, test_result=PASSED, review=APPROVE)

    assert ctx.state["review"] == APPROVE
    assert ctx.actions.escalate is True


@pytest.mark.parametrize(
    ("patch", "test_result", "problem"),
    [
        (PATCH, {**PASSED, "passed": False}, "Tests did not pass"),
        (PATCH, None, "Tests did not pass"),
        ([PATCH[0]], PASSED, "No test added"),
        ([], PASSED, "Patch is empty"),
        (PATCH + [{"path": "requirements.txt", "new_content": ""}], PASSED, "protected paths"),
    ],
)
def test_approval_is_vetoed_by_code_checks(patch: list, test_result: dict | None, problem: str) -> None:
    ctx = gate(patch=patch, test_result=test_result, review=APPROVE)

    assert ctx.state["review"]["verdict"] == "revise"
    assert any(problem in r for r in ctx.state["review"]["reasons"])
    assert ctx.actions.escalate is None


def test_revise_does_not_exit_the_loop() -> None:
    ctx = gate(patch=PATCH, test_result=PASSED, review={"verdict": "revise", "reasons": ["Scope too wide."]})

    assert ctx.state["review"]["verdict"] == "revise"
    assert ctx.actions.escalate is None


def test_missing_verdict_is_treated_as_revise() -> None:
    ctx = gate(patch=PATCH, test_result=PASSED, review="looks good")

    assert ctx.state["review"]["verdict"] == "revise"


def test_fix_loop_runs_fixer_verifier_reviewer_at_most_twice() -> None:
    assert [a.name for a in fix_loop.sub_agents] == ["fixer", "verifier", "reviewer"]
    assert fix_loop.max_iterations == 2
