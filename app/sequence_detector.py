from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Deque

from app.database import get_connection


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
    database_path: Path | str | None = None
    _events_by_session: dict[str, Deque[ToolCallEvent]] = field(
        default_factory=lambda: defaultdict(deque)
    )

    def add_call(self, event: ToolCallEvent) -> None:
        if self.database_path is not None:
            self._add_persistent_call(event)
            return

        events = self._events_by_session[event.session_id]
        events.append(event)
        while len(events) > self.max_events_per_session:
            events.popleft()

    def recent_calls(self, session_id: str) -> list[ToolCallEvent]:
        if self.database_path is not None:
            return self._persistent_recent_calls(session_id)
        return list(self._events_by_session.get(session_id, ()))

    def clear(self) -> None:
        if self.database_path is not None:
            with get_connection(self.database_path) as connection:
                connection.execute("DELETE FROM sequence_events")
                connection.commit()
            return
        self._events_by_session.clear()

    def _add_persistent_call(self, event: ToolCallEvent) -> None:
        with get_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO sequence_events (
                    agent_id,
                    session_id,
                    tool_name,
                    action,
                    resource,
                    parameters_json,
                    timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.agent_id,
                    event.session_id,
                    event.tool_name,
                    event.action,
                    event.resource,
                    json.dumps(event.parameters),
                    event.timestamp.isoformat(),
                ),
            )
            connection.execute(
                """
                DELETE FROM sequence_events
                WHERE session_id = ?
                  AND id NOT IN (
                      SELECT id
                      FROM sequence_events
                      WHERE session_id = ?
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (
                    event.session_id,
                    event.session_id,
                    self.max_events_per_session,
                ),
            )
            connection.commit()

    def _persistent_recent_calls(self, session_id: str) -> list[ToolCallEvent]:
        with get_connection(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT agent_id, session_id, tool_name, action, resource,
                       parameters_json, timestamp
                FROM sequence_events
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, self.max_events_per_session),
            ).fetchall()

        return [
            ToolCallEvent(
                agent_id=row["agent_id"],
                session_id=row["session_id"],
                tool_name=row["tool_name"],
                action=row["action"],
                resource=row["resource"],
                parameters=json.loads(row["parameters_json"]),
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
            for row in reversed(rows)
        ]
