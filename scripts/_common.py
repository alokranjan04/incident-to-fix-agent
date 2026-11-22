"""Shared helpers for the eval scripts."""
from pathlib import Path

import os

import yaml

AGENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = AGENT_ROOT.parent / "incident-to-fix-demo"


def load_bugs() -> list[dict]:
    return yaml.safe_load((AGENT_ROOT / "evals/bugs.yaml").read_text())["bugs"]


def inject(target_repo: Path, bug: dict) -> None:
    """Apply one bug's find/replace to a checkout of the target repo."""
    if not bug["inject"]:
        return
    path = target_repo / bug["file"]
    text = path.read_text()
    count = text.count(bug["inject"]["find"])
    if count != 1:
        raise ValueError(f"bug {bug['id']}: find text matched {count} times in {bug['file']} (must be 1)")
    path.write_text(text.replace(bug["inject"]["find"], bug["inject"]["replace"]))


def load_env() -> None:
    """Read KEY=value lines from .env into the environment (local runs only)."""
    env = AGENT_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
