from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
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


class PolicyValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Policy validation failed.")


class PolicyEngine:
    SUPPORTED_OPERATORS = {
        "equals",
        "greater_than",
        "less_than",
        "contains",
        "regex",
        "in",
    }

    def __init__(self, policies: list[Policy]) -> None:
        self.policies = sorted(policies, key=lambda policy: policy.priority, reverse=True)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "PolicyEngine":
        with Path(path).open("r", encoding="utf-8") as policy_file:
            raw_config = yaml.safe_load(policy_file) or {}

        cls.validate_config(raw_config)
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

    @classmethod
    def validate_config(cls, raw_config: Any) -> None:
        errors: list[str] = []
        if not isinstance(raw_config, dict):
            raise PolicyValidationError(["Policy file must contain a YAML object."])

        raw_policies = raw_config.get("policies")
        if not isinstance(raw_policies, list):
            raise PolicyValidationError(["`policies` must be a list."])

        seen_policy_ids: set[str] = set()
        for index, raw_policy in enumerate(raw_policies):
            path = f"policies[{index}]"
            if not isinstance(raw_policy, dict):
                errors.append(f"{path} must be an object.")
                continue

            policy_id = raw_policy.get("id")
            if not isinstance(policy_id, str) or not policy_id:
                errors.append(f"{path}.id must be a non-empty string.")
            elif policy_id in seen_policy_ids:
                errors.append(f"{path}.id duplicates policy id `{policy_id}`.")
            else:
                seen_policy_ids.add(policy_id)

            try:
                Decision(raw_policy.get("effect"))
            except ValueError:
                errors.append(
                    f"{path}.effect must be one of: allow, block, require_approval."
                )

            cls._validate_int_field(
                raw_policy,
                "priority",
                path,
                errors,
                required=False,
            )
            cls._validate_int_field(
                raw_policy,
                "risk_score",
                path,
                errors,
                required=False,
                minimum=0,
                maximum=100,
            )

            conditions = raw_policy.get("conditions", {})
            if not isinstance(conditions, dict):
                errors.append(f"{path}.conditions must be an object.")
                continue
            cls._validate_condition_block(conditions, f"{path}.conditions", errors)

        if errors:
            raise PolicyValidationError(errors)

    @classmethod
    def _validate_condition_block(
        cls, conditions: dict[str, Any], path: str, errors: list[str]
    ) -> None:
        for scalar_field in ("tool_name", "action", "resource"):
            if scalar_field in conditions:
                cls._validate_operator_condition(
                    conditions[scalar_field],
                    f"{path}.{scalar_field}",
                    errors,
                    allow_plain_value=True,
                )

        parameter_conditions = conditions.get("parameters", [])
        cls._validate_parameter_conditions(
            parameter_conditions,
            f"{path}.parameters",
            errors,
        )

        sequence = conditions.get("sequence")
        if sequence is not None:
            if not isinstance(sequence, list) or not sequence:
                errors.append(f"{path}.sequence must be a non-empty list when present.")
            else:
                for index, step in enumerate(sequence):
                    step_path = f"{path}.sequence[{index}]"
                    if not isinstance(step, dict):
                        errors.append(f"{step_path} must be an object.")
                        continue
                    cls._validate_condition_block(step, step_path, errors)

    @classmethod
    def _validate_parameter_conditions(
        cls,
        parameter_conditions: Any,
        path: str,
        errors: list[str],
    ) -> None:
        if not isinstance(parameter_conditions, list):
            errors.append(f"{path} must be a list.")
            return

        for index, condition in enumerate(parameter_conditions):
            condition_path = f"{path}[{index}]"
            if not isinstance(condition, dict):
                errors.append(f"{condition_path} must be an object.")
                continue
            if not isinstance(condition.get("path"), str) or not condition["path"]:
                errors.append(f"{condition_path}.path must be a non-empty string.")
            cls._validate_operator_condition(
                {key: value for key, value in condition.items() if key != "path"},
                condition_path,
                errors,
                allow_plain_value=False,
            )

    @classmethod
    def _validate_operator_condition(
        cls,
        condition: Any,
        path: str,
        errors: list[str],
        *,
        allow_plain_value: bool,
    ) -> None:
        if allow_plain_value and not isinstance(condition, dict):
            return
        if not isinstance(condition, dict):
            errors.append(f"{path} must be an operator object.")
            return

        operators = set(condition)
        unsupported_operators = operators - cls.SUPPORTED_OPERATORS
        if unsupported_operators:
            unsupported = ", ".join(sorted(unsupported_operators))
            errors.append(f"{path} has unsupported operator(s): {unsupported}.")
        if not operators:
            errors.append(f"{path} must contain at least one operator.")
        if "in" in condition and not isinstance(condition["in"], list):
            errors.append(f"{path}.in must be a list.")
        if "regex" in condition:
            try:
                re.compile(str(condition["regex"]))
            except re.error as exc:
                errors.append(f"{path}.regex is invalid: {exc}.")

    @classmethod
    def _validate_int_field(
        cls,
        raw_policy: dict[str, Any],
        field_name: str,
        path: str,
        errors: list[str],
        *,
        required: bool,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> None:
        if field_name not in raw_policy:
            if required:
                errors.append(f"{path}.{field_name} is required.")
            return
        value = raw_policy[field_name]
        if not isinstance(value, int):
            errors.append(f"{path}.{field_name} must be an integer.")
            return
        if minimum is not None and value < minimum:
            errors.append(f"{path}.{field_name} must be at least {minimum}.")
        if maximum is not None and value > maximum:
            errors.append(f"{path}.{field_name} must be at most {maximum}.")

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
        return self._matches_operator_condition(value, condition)

    def _matches_parameter_conditions(
        self, parameters: dict[str, Any], parameter_conditions: list[dict[str, Any]]
    ) -> bool:
        for condition in parameter_conditions:
            path = str(condition["path"])
            value = self._get_parameter_value(parameters, path)
            operator_condition = {
                key: expected
                for key, expected in condition.items()
                if key != "path"
            }
            if not self._matches_operator_condition(value, operator_condition):
                return False
        return True

    def _matches_operator_condition(
        self, value: Any, operator_condition: dict[str, Any]
    ) -> bool:
        if "equals" in operator_condition and value != operator_condition["equals"]:
            return False
        if "in" in operator_condition and value not in operator_condition["in"]:
            return False
        if "greater_than" in operator_condition and not self._matches_numeric_compare(
            value, operator_condition["greater_than"], "greater_than"
        ):
            return False
        if "less_than" in operator_condition and not self._matches_numeric_compare(
            value, operator_condition["less_than"], "less_than"
        ):
            return False
        if "contains" in operator_condition and not self._matches_contains(
            value, operator_condition["contains"]
        ):
            return False
        if "regex" in operator_condition and not re.search(
            str(operator_condition["regex"]), str(value)
        ):
            return False
        return True

    def _matches_numeric_compare(
        self, value: Any, expected: Any, operator: str
    ) -> bool:
        try:
            value_number = float(value)
            expected_number = float(expected)
        except (TypeError, ValueError):
            return False

        if operator == "greater_than":
            return value_number > expected_number
        if operator == "less_than":
            return value_number < expected_number
        return False

    def _matches_contains(self, value: Any, expected: Any) -> bool:
        if isinstance(value, str):
            return str(expected) in value
        if isinstance(value, list | tuple | set):
            return expected in value
        if isinstance(value, dict):
            return expected in value or expected in value.values()
        return False

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
