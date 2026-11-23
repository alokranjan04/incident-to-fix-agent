"""EARS (specs/01-agents.md): the locator SHALL return at most 3 suspect files, each with a
one-line reason, and SHALL rank only non-test source files."""
import pytest

from agent.incident_to_fix.locator import cap_suspect_files, is_test_path


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_orders.py",
        "test/orders.py",
        "app/tests/helpers.py",
        "/tests/test_orders.py",
        "app/test_orders.py",
        "app/orders_test.py",
        "conftest.py",
        "tests/conftest.py",
        "Tests/Test_Orders.py",
    ],
)
def test_test_files_are_recognised(path: str) -> None:
    assert is_test_path(path)


@pytest.mark.parametrize(
    "path",
    ["app/routes/orders.py", "app/services/pricing.py", "app/contest.py", "app/latest_rates.py", "app/testing.py"],
)
def test_source_files_are_not_mistaken_for_tests(path: str) -> None:
    assert not is_test_path(path)


def test_test_files_are_dropped_and_sources_keep_their_rank() -> None:
    result = cap_suspect_files(
        {
            "suspect_files": [
                {"path": "tests/test_orders.py", "reason": "Test fails on quantity 0."},
                {"path": "app/routes/orders.py", "reason": "Divides by quantity; covered by tests/test_orders.py"},
                {"path": "app/conftest.py", "reason": "Fixtures."},
                {"path": "app/services/pricing.py", "reason": "Computes unit price."},
            ]
        }
    )

    assert [f["path"] for f in result] == ["app/routes/orders.py", "app/services/pricing.py"]
    assert "tests/test_orders.py" in result[0]["reason"]


def test_at_most_3_source_files_after_tests_are_dropped() -> None:
    files = [{"path": "tests/test_a.py", "reason": "x"}] + [
        {"path": f"app/mod_{i}.py", "reason": f"reason {i}"} for i in range(5)
    ]

    result = cap_suspect_files(files)

    assert [f["path"] for f in result] == ["app/mod_0.py", "app/mod_1.py", "app/mod_2.py"]


def test_reason_is_cut_to_one_line() -> None:
    result = cap_suspect_files([{"path": "app/routes/orders.py", "reason": "Divides by zero.\nMore detail."}])

    assert result == [{"path": "app/routes/orders.py", "reason": "Divides by zero."}]
