"""Offline doubles for running the real agent pipeline: a scripted LLM and fake MCP toolsets."""
import json
from typing import Any, AsyncGenerator

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.tools import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.genai import types
from pydantic import Field

REPO = {"owner": "alokranjan04", "repo": "incident-to-fix-demo"}
PR_URL = "https://github.com/alokranjan04/incident-to-fix-demo/pull/7"
INCIDENT = {
    "number": "INC0010004",
    "short_description": "Order API returns 500 when quantity is 0",
    "description": "POST /orders with quantity 0 returns HTTP 500. Seen on branch bug/07.",
    "category": "software_defect",
    "u_repo": "incident-to-fix-demo",
    "state": "1",
    "state_label": "New",
}

# Which agent is asking, from a phrase in its instruction.
ROLES = {
    "You triage": "triage",
    "You find the files": "locator",
    "You fix the bug": "fixer",
    "You review a proposed fix": "reviewer",
}

DEFAULT_PLANS: dict[str, list[tuple[str, dict]]] = {
    "triage": [("get_incident", {"number": "INC0010004"})],
    "locator": [
        ("get_file_contents", {**REPO, "path": "app/routes/orders.py", "ref": "refs/heads/bug/07"}),
        ("get_file_contents", {**REPO, "path": "app/services/pricing.py", "ref": "refs/heads/bug/07"}),
    ],
    "fixer": [("get_file_contents", {**REPO, "path": "app/routes/orders.py", "ref": "refs/heads/bug/07"})],
}
DEFAULT_FINALS: dict[str, dict] = {
    "triage": {"decision": "fix", "reason": "Division by zero in create_order."},
    "locator": {"suspect_files": [{"path": "app/routes/orders.py", "reason": "Divides by quantity."}]},
    "fixer": {"files": [
        {"path": "app/routes/orders.py", "new_content": "fixed\n"},
        {"path": "tests/test_orders.py", "new_content": "test\n"},
    ]},
    "reviewer": {"verdict": "approve", "reasons": ["Scope ok", "Security ok", "Test added", "No protected paths"]},
}


class ScriptedLlm(BaseLlm):
    """Per agent: make the planned tool calls in order, then answer with the final JSON."""

    model: str = "scripted"
    plans: dict[str, list[tuple[str, dict]]] = Field(default_factory=lambda: dict(DEFAULT_PLANS))
    finals: dict[str, dict] = Field(default_factory=lambda: dict(DEFAULT_FINALS))
    progress: dict[str, int] = Field(default_factory=dict)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        role = self._role(llm_request)
        step = self.progress.get(role, 0)
        plan = self.plans.get(role, [])
        if step < len(plan):
            self.progress[role] = step + 1
            name, args = plan[step]
            part = types.Part(function_call=types.FunctionCall(name=name, args=args))
        else:
            self.progress[role] = 0  # the next run of this agent starts its plan again
            part = types.Part(text=json.dumps(self.finals[role]))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))

    @staticmethod
    def _role(llm_request: LlmRequest) -> str:
        instruction = str(llm_request.config.system_instruction or "")
        return next(role for phrase, role in ROLES.items() if phrase in instruction)


class FakeTool(BaseTool):
    def __init__(self, name: str, toolset: "FakeToolset") -> None:
        super().__init__(name=name, description=name)
        self._toolset = toolset

    def _get_declaration(self) -> types.FunctionDeclaration:
        # ADK only registers tools that declare themselves to the model.
        return types.FunctionDeclaration(
            name=self.name, description=self.name, parameters=types.Schema(type=types.Type.OBJECT)
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: Any) -> Any:
        self._toolset.calls.append((self.name, dict(args)))
        result = self._toolset.results.get(self.name, {"content": [{"type": "text", "text": "ok"}], "isError": False})
        if isinstance(result, Exception):
            raise result
        return result


class FakeToolset(BaseToolset):
    """Fake MCP server. `calls` is shared so one list shows the whole run in order."""

    def __init__(self, names: list[str], calls: list, results: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._names = names
        self.calls = calls
        self.results = {
            "get_incident": {"structuredContent": INCIDENT, "content": [], "isError": False},
            "create_pull_request": {"content": [{"type": "text", "text": json.dumps({"url": PR_URL})}], "isError": False},
            **(results or {}),
        }

    async def get_tools(self, readonly_context: Any = None) -> list[BaseTool]:
        return [FakeTool(name, self) for name in self._names]

    async def close(self) -> None:
        pass
