# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only component evidence, not topic-set membership or write authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid

import requests

from agentbuilder import AgentBuilderClient, AgentBuilderError, AgentBuilderHTTPError


class ComponentReadError(RuntimeError):
    """A bounded failure without service bodies, tokens or component content."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ComponentState:
    component_id: str
    state: str
    reason: str


@dataclass(frozen=True)
class ComponentSnapshot:
    agent_id: str
    components: tuple[ComponentState, ...]
    _change_token: str | None = field(repr=False)

    def public_result(self) -> dict[str, Any]:
        """Return state evidence without the private in-memory change token."""
        return {
            "agentId": self.agent_id,
            "changeTokenAvailable": self._change_token is not None,
            "components": [
                {"componentId": item.component_id, "state": item.state, "reason": item.reason}
                for item in self.components
            ],
        }


def normalize_state(state: Any, status: Any) -> tuple[str, str]:
    """Only matching, known state/status pairs establish On or Off."""
    if state is None and status is None:
        return "Unknown", "missing_state_and_status"
    if state is None:
        return "Unknown", "missing_state"
    if status is None:
        return "Unknown", "missing_status"
    if not isinstance(state, str) or state not in ("Active", "Inactive"):
        return "Unknown", "unknown_state"
    if not isinstance(status, str) or status not in ("Active", "Inactive"):
        return "Unknown", "unknown_status"
    if state != status:
        return "Unknown", "contradictory_state"
    return ("On" if state == "Active" else "Off"), "verified_pair"


def _identity(value: Any) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Invalid identity.")
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return value


def _require_agent(value: Any, agent_id: str) -> None:
    try:
        matches = isinstance(value, str) and str(uuid.UUID(value)) == agent_id
    except ValueError:
        matches = False
    if not matches:
        raise ComponentReadError(
            "target_mismatch", "Component evidence does not match the selected agent."
        )


def _snapshot(
    body: Any, agent_id: str, component_ids: tuple[str, ...],
) -> ComponentSnapshot:
    if not isinstance(body, dict) or not isinstance(body.get("botComponentChanges"), list):
        raise ComponentReadError(
            "invalid_response", "The component read did not return a valid collection."
        )
    if "bot" in body:
        if not isinstance(body["bot"], dict):
            raise ComponentReadError("invalid_response", "The component read is malformed.")
        if "cdsBotId" in body["bot"]:
            _require_agent(body["bot"]["cdsBotId"], agent_id)
    token = body.get("changeToken")
    if token is not None and (not isinstance(token, str) or not token.strip()):
        raise ComponentReadError("invalid_response", "The component read is malformed.")
    requested = set(component_ids)
    found: dict[str, list[tuple[str, str]]] = {}
    for change in body["botComponentChanges"]:
        if (
            not isinstance(change, dict)
            or change.get("$kind") != "BotComponentInsert"
            or not isinstance(change.get("component"), dict)
        ):
            raise ComponentReadError(
                "invalid_response", "The component read contains an unsupported record."
            )
        component = change["component"]
        try:
            identity = _identity(component.get("id"))
        except ValueError:
            raise ComponentReadError(
                "invalid_response", "The component read contains an unidentified record."
            ) from None
        if "parentBotId" in component:
            _require_agent(component["parentBotId"], agent_id)
        if identity in requested:
            found.setdefault(identity, []).append(
                normalize_state(component.get("state"), component.get("status"))
            )
    evidence = []
    for identity in component_ids:
        matches = found.get(identity, [])
        if not matches:
            state, reason = "Unknown", "missing_component"
        elif len(matches) != 1:
            state, reason = "Unknown", "ambiguous_identity"
        else:
            state, reason = matches[0]
        evidence.append(ComponentState(identity, state, reason))
    return ComponentSnapshot(agent_id, tuple(evidence), token)


def read_component_states(
    client: AgentBuilderClient, agent_id: str, component_ids: list[str] | tuple[str, ...],
) -> ComponentSnapshot:
    """Fetch once for an already verified target using the caller-owned client.

    IDs must come from the caller's exact selection, never inferred set names.
    No client/session defaults are changed; no token, content or evidence is saved.
    A fresh snapshot is fetched on every invocation, including after a failure.
    """
    try:
        if not isinstance(agent_id, str):
            raise ValueError("Invalid agent.")
        target = str(uuid.UUID(agent_id))
        if not isinstance(component_ids, (list, tuple)) or not component_ids:
            raise ValueError("Missing component identities.")
        identities = tuple(_identity(value) for value in component_ids)
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate component identities.")
    except ValueError:
        raise ComponentReadError(
            "invalid_request", "Provide one agent ID and distinct exact component IDs."
        ) from None
    try:
        body = client.fetch_components(target)
    except AgentBuilderHTTPError as exc:
        reason = {
            401: "authentication_failed", 403: "access_denied",
            404: "target_not_found", 429: "read_throttled",
        }.get(exc.status_code, "read_failed")
        raise ComponentReadError(
            reason, "Components could not be read. No topic changes were attempted."
        ) from None
    except requests.Timeout:
        raise ComponentReadError(
            "read_timeout", "The component read timed out. No topic changes were attempted."
        ) from None
    except (AgentBuilderError, requests.RequestException):
        raise ComponentReadError(
            "read_failed", "Components could not be read. No topic changes were attempted."
        ) from None
    return _snapshot(body, target, identities)
