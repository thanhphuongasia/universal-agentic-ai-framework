"""EmailSummaryTarget — EvalTarget for testing the email_summary prompt skill.

Injects a stub gmail_get_email tool so the agent goes through the full
tool-call flow (trigger → call gmail → read body → summarize) without
needing a live Gmail MCP server.

Usage in a suite:
    target = EmailSummaryTarget.build(skills_dir=Path("examples/ryuu_sensei/skills"))
    runner = EvalRunner(target=target, scorers=[coverage_scorer()])
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ryuu import Agent
from ryuu_eval_core.models import CaseResult, EvalCase
from ryuu_prompts.skills.registry import PromptSkillRegistry


@dataclass
class _StubGmailGetEmail:
    """Fake gmail_get_email tool — returns email body stored in case metadata."""

    tool_id: str = "gmail_get_email"
    _body: str = ""

    def load(self, body: str) -> None:
        self._body = body

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "gmail_get_email",
                "description": "Get full content of an email by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "email_id": {"type": "string", "description": "Email ID to fetch"},
                    },
                    "required": ["email_id"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        return {"ok": True, "body": self._body, "email_id": args.get("email_id")}


@dataclass
class EmailSummaryTarget:
    """EvalTarget that tests the email_summary prompt skill end-to-end.

    For each case:
    1. Loads the email body from case.metadata["email_body"]
    2. Seeds the stub gmail_get_email tool with that body
    3. Sends case.input["message"] to the Agent
    4. Returns the Agent's text output as CaseResult
    """

    _agent: Agent
    _stub_gmail: _StubGmailGetEmail

    @classmethod
    def build(
        cls,
        skills_dir: Path,
        model: str = "gpt-4o-mini",
    ) -> "EmailSummaryTarget":
        registry = PromptSkillRegistry.from_dirs([skills_dir])
        stub = _StubGmailGetEmail()
        instructions = registry.render_context()
        agent = Agent(
            model=model,
            instructions=instructions,
            tools=[stub],
            budget_usd=0.10,
            max_iterations=6,
            max_tokens=2048,
        )
        return cls(_agent=agent, _stub_gmail=stub)

    async def run(self, case: EvalCase) -> CaseResult:
        email_body = case.metadata.get("email_body", "")
        self._stub_gmail.load(email_body)

        message = case.input.get("message", "tóm tắt email này")
        email_id = case.input.get("email_id", "mock-001")
        prompt = f"{message}\n\nemail_id: {email_id}"

        result = await self._agent.run(prompt)
        return CaseResult(case=case, output=str(result.output) if result.output else "")
