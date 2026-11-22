"""Check that every seeded bug is real: its hidden test fails with the bug in place.

Usage: python scripts/verify_bugs.py [--target ../incident-to-fix-demo]
Works on a temporary copy, so the target repo is never changed.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _common import AGENT_ROOT, DEFAULT_TARGET, inject, load_bugs


def hidden_test_passes(repo: Path, bug: dict) -> bool:
    tests = repo / "_hidden"
    tests.mkdir(exist_ok=True)
    shutil.copy(AGENT_ROOT / "evals/hidden_tests/conftest.py", tests / "conftest.py")
    shutil.copy(AGENT_ROOT / bug["hidden_test"], tests)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "_hidden"],
                       cwd=repo, capture_output=True, text=True)
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = ap.parse_args()

    bugs = load_bugs()
    problems = 0
    for bug in bugs:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(args.target, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
            try:
                inject(repo, bug)
            except ValueError as exc:
                print(exc)
                problems += 1
                continue
            caught = not hidden_test_passes(repo, bug)
            problems += not caught
            print(f"bug {bug['id']}: {'OK' if caught else 'PROBLEM: hidden test passes with the bug'}")
    print(f"\n{len(bugs) - problems}/{len(bugs)} bugs verified")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
