"""The code-driven agents (verifier, publisher) run inside a real ADK Runner: tools are loaded
from toolsets, results land in session state via events. Offline: fake toolset, fake clone."""
import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest
from google.adk.agents import SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.genai import types

from agent.incident_to_fix import verifier
from agent.incident_to_fix.publisher import Publisher
from agent.incident_to_fix.verifier import Verifier

PR_URL = "https://github.com/alokranjan04/incident-to-fix-demo/pull/3"


class FakeTool(BaseTool):
    def __init__(self, name: str, calls: list) -> None:
        super().__init__(name=name, description=name)
        self._calls = calls

    async def run_async(self, *, args: dict[str, Any], tool_context: Any) -> Any:
        self._calls.append((self.name, args))
        text = f'{{"url": "{PR_URL}"}}' if self.name == "create_pull_request" else "ok"
        return {"content": [{"type": "text", "text": text}], "isError": False}


class FakeToolset(BaseToolset):
    def __init__(self, calls: list) -> None:
        super().__init__()
        self._calls = calls

    async def get_tools(self, readonly_context: Any = None) -> list[BaseTool]:
        names = ["create_branch", "push_files", "create_pull_request", "add_work_note"]
        return [FakeTool(n, self._calls) for n in names]

    async def close(self) -> None:
        pass


def run_pipeline(state: dict, calls: list) -> dict:
    root = SequentialAgent(
        name="pipeline", sub_agents=[Verifier(name="verifier"), Publisher(name="publisher", tools=[FakeToolset(calls)])]
    )

    async def go() -> dict:
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name="t", user_id="u", state=state)
        runner = Runner(app_name="t", agent=root, session_service=sessions)
        message = types.Content(role="user", parts=[types.Part(text="INC0010004")])
        async for _ in runner.run_async(user_id="u", session_id=session.id, new_message=message):
            pass
        return (await sessions.get_session(app_name="t", user_id="u", session_id=session.id)).state

    return asyncio.run(go())


@pytest.fixture
def fake_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    origin = tmp_path / "origin"
    (origin / "app").mkdir(parents=True)
    (origin / "app" / "__init__.py").write_text("")
    (origin / "app" / "calc.py").write_text("def half(x):\n    return x // 3\n")
    monkeypatch.setattr(verifier, "_clone", lambda branch, dest: shutil.copytree(origin, dest))


def test_verified_and_approved_fix_is_published_through_adk(fake_clone: None) -> None:
    calls: list = []
    state = {
        "incident": {"number": "INC0010004", "short_description": "half() is wrong"},
        "branch": "main",
        "decision": {"decision": "fix", "reason": "defect"},
        "patch": [
            {"path": "app/calc.py", "new_content": "def half(x):\n    return x // 2\n"},
            {"path": "tests/test_calc.py", "new_content": "from app.calc import half\n\ndef test_half():\n    assert half(4) == 2\n"},
        ],
        "review": {"verdict": "approve", "reasons": ["ok"]},
    }

    final = run_pipeline(state, calls)

    assert final["test_result"]["passed"], final["test_result"]
    assert [name for name, _ in calls] == ["create_branch", "push_files", "create_pull_request", "add_work_note"]
    assert final["pr_url"] == PR_URL
    assert final["tool_calls"] == 5  # run_tests + 4 MCP calls


def test_escalated_incident_gets_only_a_work_note_through_adk(fake_clone: None) -> None:
    calls: list = []
    state = {
        "incident": {"number": "INC0010009", "short_description": "Printer jam"},
        "branch": "main",
        "decision": {"decision": "escalate", "reason": "Category is not software_defect."},
    }

    final = run_pipeline(state, calls)

    assert [name for name, _ in calls] == ["add_work_note"]
    assert "Category is not software_defect." in calls[0][1]["text"]
    assert "pr_url" not in final
