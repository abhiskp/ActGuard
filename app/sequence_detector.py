from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque


@dataclass(frozen=True)
class ToolCallEvent:
    agent_id: str
    session_id: str
    tool_name: str
    action: str
    resource: str
    parameters: dict[str, Any]
    timestamp: datetime


@dataclass
class SequenceDetector:
    max_events_per_session: int = 50
    _events_by_session: dict[str, Deque[ToolCallEvent]] = field(
        default_factory=lambda: defaultdict(deque)
    )

    def add_call(self, event: ToolCallEvent) -> None:
        events = self._events_by_session[event.session_id]
        events.append(event)
        while len(events) > self.max_events_per_session:
            events.popleft()

    def recent_calls(self, session_id: str) -> list[ToolCallEvent]:
        return list(self._events_by_session.get(session_id, ()))

    def clear(self) -> None:
        self._events_by_session.clear()
