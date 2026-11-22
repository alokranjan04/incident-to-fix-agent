"""Create one branch per seeded bug (bug/02 ... bug/15) in your clone of the target repo.

Usage:
  python scripts/seed_bugs.py --target ../incident-to-fix-demo          # create branches locally
  python scripts/seed_bugs.py --target ../incident-to-fix-demo --push   # and push them to GitHub

Commit messages are deliberately ordinary ("Refactor pricing") so the agent cannot
read the answer from git history; it has to find the bug the way an engineer would.
"""
import argparse
import subprocess
from pathlib import Path

from _common import DEFAULT_TARGET, inject, load_bugs


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    ap.add_argument("--push", action="store_true")
    args = ap.parse_args()
    repo = args.target.resolve()

    if git(repo, "status", "--porcelain").strip():
        raise SystemExit("Target repo has uncommitted changes. Commit or stash them first.")
    git(repo, "checkout", "main")

    for bug in load_bugs():
        if not bug["inject"]:
            continue
        branch = bug["branch"]
        git(repo, "checkout", "-B", branch, "main")
        inject(repo, bug)
        git(repo, "commit", "-am", f"Refactor {Path(bug['file']).stem}")
        if args.push:
            git(repo, "push", "--force", "-u", "origin", branch)
        print(f"{branch}: ready")
    git(repo, "checkout", "main")


if __name__ == "__main__":
    main()
