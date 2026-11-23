"""Verifier: run_tests proves the patch's test fails before the fix and all tests pass after.

Runs locally in a temp clone for now; Cloud Build replaces this in the deploy milestone.
The verifier is code, not an LLM: it passes the patch from state straight to run_tests.
"""
import asyncio
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types
from mcp.client.stdio import get_default_environment

from .config import ALLOWED_REPO_URL
from .fixer import PATCH_KEY, is_test_change
from .guardrails import STOP_REASON_KEY, TOOL_CALLS_KEY, patch_violation, spend_tool_call

TEST_RESULT_KEY = "test_result"
TIMEOUT_SECONDS = 120
OUTPUT_TAIL_CHARS = 4000
_BRANCH_RE = re.compile(r"^(main|bug/\d{2})$")
# pytest exit codes: 1 = tests failed, 2 = collection error (e.g. imports code the fix adds).
_FAILED_BEFORE_FIX = {1, 2}


def _result(passed: bool, stage: str, summary: str, output: str = "") -> dict:
    return {"passed": passed, "stage": stage, "summary": summary, "output": output[-OUTPUT_TAIL_CHARS:]}


def _clean_env() -> dict[str, str]:
    """Minimal env: generated code under test never sees SNOW_* or GITHUB_TOKEN."""
    return {**get_default_environment(), "PYTHONDONTWRITEBYTECODE": "1", "GIT_TERMINAL_PROMPT": "0"}


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=cwd, env=_clean_env(), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS,
    )


def _clone(branch: str, dest: Path) -> None:
    done = _run(["git", "clone", "--quiet", "--depth", "1", "--branch", branch, ALLOWED_REPO_URL, str(dest)])
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"git clone exited {done.returncode}")


def _pytest(repo: Path, targets: list[str]) -> subprocess.CompletedProcess:
    return _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets], cwd=repo)


def _path_problem(path: str) -> str | None:
    p = PurePosixPath(path)
    if not p.parts or p.is_absolute() or ".." in p.parts or ":" in path or "\\" in path:
        return f"unsafe path {path!r}"
    return None


def _write(repo: Path, files: list[dict]) -> None:
    for change in files:
        target = repo / change["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change["new_content"], encoding="utf-8", newline="")


def _input_problem(branch: str, patch: list[dict]) -> str | None:
    if not _BRANCH_RE.match(branch or ""):
        return f"invalid branch {branch!r}"
    if not patch:
        return "patch is empty"
    paths = [str(f.get("path", "")) for f in patch]
    return next(filter(None, map(_path_problem, paths)), None) or patch_violation(paths)


def run_tests(branch: str, patch: list[dict]) -> dict:
    """Clone `branch`, run the patch's tests without the source changes (must fail), then the
    whole suite with the full patch (must pass). Returns passed, stage, summary, output."""
    problem = _input_problem(branch, patch)
    if problem:
        return _result(False, "input", problem)
    tests = [f for f in patch if is_test_change(f["path"])]
    if not tests:
        return _result(False, "no_test", "patch must add or change a test under tests/")

    with tempfile.TemporaryDirectory(prefix="incident-to-fix-", ignore_cleanup_errors=True) as tmp:
        repo = Path(tmp) / "repo"
        try:
            _clone(branch, repo)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            return _result(False, "clone", f"could not clone branch {branch}", str(exc))

        _write(repo, tests)
        try:
            before = _pytest(repo, [f["path"] for f in tests])
        except subprocess.TimeoutExpired:
            return _result(False, "before_fix", f"tests timed out after {TIMEOUT_SECONDS}s without the fix")
        if before.returncode not in _FAILED_BEFORE_FIX:
            return _result(
                False, "before_fix",
                f"the new test must fail without the fix (pytest exit {before.returncode})", before.stdout,
            )

        _write(repo, patch)
        try:
            after = _pytest(repo, [])
        except subprocess.TimeoutExpired:
            return _result(False, "after_fix", f"tests timed out after {TIMEOUT_SECONDS}s with the fix")
        if after.returncode != 0:
            return _result(False, "after_fix", f"tests fail with the fix (pytest exit {after.returncode})", after.stdout)
        return _result(True, "passed", "new test fails without the fix; all tests pass with it", after.stdout)


class Verifier(BaseAgent):
    """Runs run_tests on state['branch'] and state['patch']; writes state['test_result']."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        delta: dict[str, Any] = {}
        stopped = state.get(STOP_REASON_KEY)
        if stopped:
            text = f"Skipped: run stopped ({stopped})."
        else:
            delta[TOOL_CALLS_KEY] = state.get(TOOL_CALLS_KEY) or 0
            if spend_tool_call(delta):
                result = _result(False, "budget", "tool-call budget reached before tests could run")
            else:
                patch = state.get(PATCH_KEY)
                result = await self._run_tests(state.get("branch") or "", patch if isinstance(patch, list) else [])
            delta[TEST_RESULT_KEY] = result
            text = f"run_tests: {result['summary']}"
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=text)]),
            actions=EventActions(state_delta=delta),
        )

    @staticmethod
    async def _run_tests(branch: str, patch: list[dict]) -> dict:
        try:
            return await asyncio.to_thread(run_tests, branch, patch)
        except Exception as exc:  # report as a failed run, never crash the pipeline
            return _result(False, "error", f"run_tests raised {type(exc).__name__}", str(exc))
