"""Model settings: no hard-coded model names; GEMINI_FIX_MODEL falls back to GEMINI_MODEL."""
import pytest

from agent.incident_to_fix.config import resolve_models


def test_fix_model_falls_back_to_gemini_model() -> None:
    assert resolve_models({"GEMINI_MODEL": "gemini-3.8-flash"}) == ("gemini-3.8-flash", "gemini-3.8-flash")


def test_empty_fix_model_falls_back_to_gemini_model() -> None:
    assert resolve_models({"GEMINI_MODEL": "gemini-3.8-flash", "GEMINI_FIX_MODEL": "  "}) == (
        "gemini-3.8-flash",
        "gemini-3.8-flash",
    )


def test_fix_model_can_be_set_separately() -> None:
    env = {"GEMINI_MODEL": "gemini-3.8-flash", "GEMINI_FIX_MODEL": "gemini-3.8-pro"}

    assert resolve_models(env) == ("gemini-3.8-flash", "gemini-3.8-pro")


@pytest.mark.parametrize("env", [{}, {"GEMINI_MODEL": ""}, {"GEMINI_FIX_MODEL": "gemini-3.8-pro"}])
def test_missing_gemini_model_is_a_clear_error(env: dict) -> None:
    with pytest.raises(RuntimeError, match="GEMINI_MODEL is not set"):
        resolve_models(env)


def test_agent_code_has_no_hard_coded_model_names() -> None:
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "agent" / "incident_to_fix"
    for source in package.glob("*.py"):
        assert "gemini-" not in source.read_text(encoding="utf-8"), source.name
