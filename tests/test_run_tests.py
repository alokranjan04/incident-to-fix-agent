"""EARS (specs/01-agents.md): the fixer SHALL add or change a test that fails before the fix
and passes after it. run_tests checks this with real pytest runs on a local fixture repo
(the git clone is replaced by a copy, so no network)."""
import shutil
from pathlib import Path

import pytest

from agent.incident_to_fix import verifier
from agent.incident_to_fix.verifier import run_tests

BUGGY_SOURCE = "def unit_price(total, quantity):\n    return total / quantity\n"
FIXED_SOURCE = (
    "def unit_price(total, quantity):\n"
    "    if quantity < 1:\n"
    "        raise ValueError('quantity must be at least 1')\n"
    "    return total / quantity\n"
)
EXISTING_TEST = "from app.calc import unit_price\n\ndef test_unit_price():\n    assert unit_price(10, 2) == 5\n"
NEW_TEST = (
    "import os\n\nimport pytest\n\nfrom app.calc import unit_price\n\n"
    "def test_unit_price():\n    assert unit_price(10, 2) == 5\n\n"
    "def test_zero_quantity_is_rejected():\n"
    "    with pytest.raises(ValueError):\n        unit_price(10, 0)\n\n"
    "def test_secrets_are_not_visible():\n"
    "    assert 'GITHUB_TOKEN' not in os.environ and 'SNOW_PASSWORD' not in os.environ\n"
)
FIX = {"path": "app/calc.py", "new_content": FIXED_SOURCE}
TEST = {"path": "tests/test_calc.py", "new_content": NEW_TEST}


@pytest.fixture
def clones(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace git clone with a copy of a tiny buggy repo. Records the branches cloned."""
    origin = tmp_path / "origin"
    (origin / "app").mkdir(parents=True)
    (origin / "tests").mkdir()
    (origin / "app" / "__init__.py").write_text("")
    (origin / "app" / "calc.py").write_text(BUGGY_SOURCE)
    (origin / "tests" / "__init__.py").write_text("")
    (origin / "tests" / "test_calc.py").write_text(EXISTING_TEST)
    branches: list[str] = []

    def fake_clone(branch: str, dest: Path) -> None:
        branches.append(branch)
        shutil.copytree(origin, dest)

    monkeypatch.setattr(verifier, "_clone", fake_clone)
    monkeypatch.setenv("SNOW_PASSWORD", "not-for-tests")
    return branches


def test_test_that_fails_before_and_passes_after_the_fix_passes(clones: list[str]) -> None:
    result = run_tests("bug/07", [FIX, TEST])

    assert result["passed"], result
    assert result["stage"] == "passed"
    assert clones == ["bug/07"]


def test_test_that_already_passes_without_the_fix_is_rejected(clones: list[str]) -> None:
    result = run_tests("main", [FIX, {"path": "tests/test_calc.py", "new_content": EXISTING_TEST}])

    assert not result["passed"]
    assert result["stage"] == "before_fix"
    assert "must fail without the fix" in result["summary"]


def test_fix_that_does_not_make_the_test_pass_is_rejected(clones: list[str]) -> None:
    result = run_tests("main", [{"path": "app/calc.py", "new_content": BUGGY_SOURCE}, TEST])

    assert not result["passed"]
    assert result["stage"] == "after_fix"
    assert "test_zero_quantity_is_rejected" in result["output"]


def test_patch_without_a_test_is_rejected(clones: list[str]) -> None:
    result = run_tests("main", [FIX])

    assert (result["passed"], result["stage"]) == (False, "no_test")
    assert clones == []


@pytest.mark.parametrize(
    ("branch", "patch", "problem"),
    [
        ("main; rm -rf /", [FIX, TEST], "invalid branch"),
        ("--upload-pack=evil", [FIX, TEST], "invalid branch"),
        ("main", [], "patch is empty"),
        ("main", [{"path": "../outside.py", "new_content": ""}, TEST], "unsafe path"),
        ("main", [{"path": "/etc/passwd", "new_content": ""}, TEST], "unsafe path"),
        ("main", [{"path": "C:/x.py", "new_content": ""}, TEST], "unsafe path"),
        ("main", [{"path": "requirements.txt", "new_content": ""}, TEST], "protected paths"),
        ("main", [FIX, TEST, {"path": "a.py", "new_content": ""}, {"path": "b.py", "new_content": ""}], "at most 3"),
    ],
)
def test_unsafe_input_is_rejected_before_cloning(
    clones: list[str], branch: str, patch: list[dict], problem: str
) -> None:
    result = run_tests(branch, patch)

    assert (result["passed"], result["stage"]) == (False, "input")
    assert problem in result["summary"]
    assert clones == []


def test_tests_that_hang_time_out(clones: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier, "TIMEOUT_SECONDS", 2)
    hanging = "import time\n\ndef test_hangs():\n    time.sleep(30)\n"

    result = run_tests("main", [FIX, {"path": "tests/test_calc.py", "new_content": hanging}])

    assert (result["passed"], result["stage"]) == (False, "before_fix")
    assert "timed out" in result["summary"]
