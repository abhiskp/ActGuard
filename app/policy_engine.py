from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.models import Decision, ToolCallRequest
from app.sequence_detector import ToolCallEvent


@dataclass(frozen=True)
class PolicyMatch:
    decision: Decision
    reason: str
    matched_policy_id: str | None
    risk_score: int


@dataclass(frozen=True)
class Policy:
    policy_id: str
    description: str
    effect: Decision
    risk_score: int
    reason: str
    conditions: dict[str, Any]
    priority: int = 0


class PolicyEngine:
    def __init__(self, policies: list[Policy]) -> None:
        self.policies = sorted(policies, key=lambda policy: policy.priority, reverse=True)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "PolicyEngine":
        with Path(path).open("r", encoding="utf-8") as policy_file:
            raw_config = yaml.safe_load(policy_file) or {}

        policies = [
            Policy(
                policy_id=str(raw_policy["id"]),
                description=str(raw_policy.get("description", "")),
                effect=Decision(raw_policy["effect"]),
                risk_score=int(raw_policy.get("risk_score", 0)),
                reason=str(raw_policy.get("reason", raw_policy.get("description", ""))),
                conditions=dict(raw_policy.get("conditions", {})),
                priority=int(raw_policy.get("priority", 0)),
            )
            for raw_policy in raw_config.get("policies", [])
        ]
        return cls(policies)

    def evaluate(
        self, request: ToolCallRequest, previous_calls: list[ToolCallEvent] | None = None
    ) -> PolicyMatch:
        previous_calls = previous_calls or []
        for policy in self.policies:
            if self._matches_policy(policy, request, previous_calls):
                return PolicyMatch(
                    decision=policy.effect,
                    reason=policy.reason,
                    matched_policy_id=policy.policy_id,
                    risk_score=policy.risk_score,
                )
        return PolicyMatch(
            decision=Decision.ALLOW,
            reason="No blocking or approval policy matched.",
            matched_policy_id=None,
            risk_score=0,
        )

    def _matches_policy(
        self,
        policy: Policy,
        request: ToolCallRequest,
        previous_calls: list[ToolCallEvent],
    ) -> bool:
        conditions = policy.conditions
        if not self._matches_scalar_condition(request.tool_name, conditions.get("tool_name")):
            return False
        if not self._matches_scalar_condition(request.action, conditions.get("action")):
            return False
        if not self._matches_scalar_condition(request.resource, conditions.get("resource")):
            return False
        if not self._matches_parameter_conditions(
            request.parameters, conditions.get("parameters", [])
        ):
            return False
        if not self._matches_sequence(conditions.get("sequence"), previous_calls, request):
            return False
        return True

    def _matches_scalar_condition(self, value: str, condition: Any) -> bool:
        if condition is None:
            return True
        if not isinstance(condition, dict):
            return value == condition
        if "equals" in condition and value != condition["equals"]:
            return False
        if "in" in condition and value not in condition["in"]:
            return False
        return True

    def _matches_parameter_conditions(
        self, parameters: dict[str, Any], parameter_conditions: list[dict[str, Any]]
    ) -> bool:
        for condition in parameter_conditions:
            path = str(condition["path"])
            value = self._get_parameter_value(parameters, path)
            if "equals" in condition and value != condition["equals"]:
                return False
            if "greater_than" in condition:
                try:
                    if float(value) <= float(condition["greater_than"]):
                        return False
                except (TypeError, ValueError):
                    return False
        return True

    def _matches_sequence(
        self,
        sequence: list[dict[str, Any]] | None,
        previous_calls: list[ToolCallEvent],
        request: ToolCallRequest,
    ) -> bool:
        if not sequence:
            return True

        observed_calls = [
            *previous_calls,
            ToolCallEvent(
                agent_id=request.agent_id,
                session_id=request.session_id,
                tool_name=request.tool_name,
                action=request.action,
                resource=request.resource,
                parameters=request.parameters,
                timestamp=request.timestamp,
            ),
        ]
        if len(observed_calls) < len(sequence):
            return False

        candidate_calls = observed_calls[-len(sequence) :]
        return all(
            self._event_matches_sequence_step(event, step)
            for event, step in zip(candidate_calls, sequence)
        )

    def _event_matches_sequence_step(
        self, event: ToolCallEvent, step: dict[str, Any]
    ) -> bool:
        if not self._matches_scalar_condition(event.tool_name, step.get("tool_name")):
            return False
        if not self._matches_scalar_condition(event.action, step.get("action")):
            return False
        if not self._matches_scalar_condition(event.resource, step.get("resource")):
            return False
        return self._matches_parameter_conditions(event.parameters, step.get("parameters", []))

    def _get_parameter_value(self, parameters: dict[str, Any], path: str) -> Any:
        current_value: Any = parameters
        for part in path.split("."):
            if not isinstance(current_value, dict) or part not in current_value:
                return None
            current_value = current_value[part]
        return current_value
