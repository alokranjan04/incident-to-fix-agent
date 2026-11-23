"""Reviewer: checklist review of the patch. Code can veto an approval; approval exits the loop."""
from typing import Any, Literal

from google.adk.agents.callback_context import CallbackContext
from pydantic import BaseModel, Field

from .fixer import PATCH_KEY, is_test_change
from .guardrails import patch_violation
from .verifier import TEST_RESULT_KEY

REVIEW_KEY = "review"


class Review(BaseModel):
    verdict: Literal["approve", "revise"]
    reasons: list[str] = Field(description="One line per checklist item: scope, security, test added, protected paths.")


def code_review_problems(patch: Any, test_result: Any) -> list[str]:
    """Checklist items code can decide on its own. Any problem forces 'revise'."""
    problems = []
    if not isinstance(test_result, dict) or not test_result.get("passed"):
        problems.append("Tests did not pass: the new test must fail before the fix and all tests pass after.")
    files = patch if isinstance(patch, list) else []
    if not files:
        problems.append("Patch is empty.")
    elif not any(is_test_change(str(f.get("path", ""))) for f in files):
        problems.append("No test added or changed under tests/.")
    violation = patch_violation([str(f.get("path", "")) for f in files])
    if violation:
        problems.append(f"Guardrail: {violation}.")
    return problems


def gate_review(callback_context: CallbackContext) -> None:
    """after_agent_callback: veto approvals that fail code checks; exit the loop on approve."""
    state = callback_context.state
    review = state.get(REVIEW_KEY)
    if not isinstance(review, dict) or review.get("verdict") not in ("approve", "revise"):
        review = {"verdict": "revise", "reasons": ["Reviewer returned no structured verdict."]}
    problems = code_review_problems(state.get(PATCH_KEY), state.get(TEST_RESULT_KEY))
    if problems:
        review = {"verdict": "revise", "reasons": list(review.get("reasons") or []) + problems}
    state[REVIEW_KEY] = review
    if review["verdict"] == "approve":
        callback_context.actions.escalate = True
    return None
