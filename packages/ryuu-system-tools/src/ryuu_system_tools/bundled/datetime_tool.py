"""Current date/time anchor for the LLM.

LLMs hallucinate dates without an authoritative reference — especially for
relative queries like "30 days ago" or "tasks due today". This tool returns
the real wall-clock, optionally in any IANA timezone.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass
class GetCurrentDatetimeTool:
    tool_id: str = "get_current_datetime"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "get_current_datetime",
                "description": (
                    "Return the current date and time. Pass `timezone` (IANA name like "
                    "'Asia/Ho_Chi_Minh', 'America/New_York') to get the user's local time; "
                    "omit for the bot host's clock. Call this whenever you need today's "
                    "date for relative math ('last 30 days', 'tasks due today', 'next "
                    "Monday') — never guess. Returns ISO date, ISO datetime, weekday, "
                    "and timezone."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timezone": {
                            "type": "string",
                            "description": "IANA timezone name (optional). E.g. 'Asia/Ho_Chi_Minh'.",
                        },
                    },
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        tz_name = (args or {}).get("timezone")
        if tz_name:
            try:
                now = datetime.now(ZoneInfo(tz_name))
            except ZoneInfoNotFoundError:
                return {"error": f"Unknown IANA timezone: {tz_name!r}"}
        else:
            now = datetime.now().astimezone()
        return {
            "date": now.date().isoformat(),
            "datetime": now.isoformat(timespec="seconds"),
            "weekday": now.strftime("%A"),
            "timezone": now.strftime("%Z") or "local",
        }


TOOLS = [GetCurrentDatetimeTool()]
