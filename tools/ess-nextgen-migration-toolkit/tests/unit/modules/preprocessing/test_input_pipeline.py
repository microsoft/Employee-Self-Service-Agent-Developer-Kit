"""Unit tests for the input pipeline vertical slice."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from modules.migration.models import MigrationContext
from modules.preprocessing.input_pipeline import build_input_pipeline
from modules.preprocessing.steps.agent_selection_step import AgentSelectionStep
from modules.preprocessing.steps.gather_input_with_auth_step import (
    GatherInputWithAuthStep,
    _discover_tenant,
)
from modules.preprocessing.steps.gather_preferred_solution_step import (
    GatherPreferredSolutionStep,
)


def _make_token(claims: dict[str, str]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode("ascii")
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8"))
        .rstrip(b"=")
        .decode(
            "ascii",
        )
    )
    return f"{header}.{payload}.signature"


class FakeLogger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def LogInfo(self, message: str, **_: object) -> None:
        self.messages.append(("INFO", message))

    def LogDebug(self, message: str, **_: object) -> None:
        self.messages.append(("DEBUG", message))


class StubMsalTokenProvider:
    token = _make_token({"tid": "tenant-123", "oid": "user-456", "upn": "maker@contoso.com"})
    instances: list[StubMsalTokenProvider] = []

    def __init__(self, config: object) -> None:
        self.config = config
        self.instances.append(self)

    def get_token(self) -> str:
        return self.token


class FakeDataverseClient:
    def __init__(self, agents: list[dict[str, Any]]) -> None:
        self._agents = agents
        self.calls: list[tuple[str, str]] = []

    def query_all(self, entity_set: str, *, select: str) -> list[dict[str, Any]]:
        self.calls.append((entity_set, select))
        return list(self._agents)


def test_gather_input_with_auth_step_populates_identity_and_bootstraps_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = FakeLogger()
    step = GatherInputWithAuthStep(logger, ("READONLY", "WRITEBACK"))  # type: ignore[arg-type]
    StubMsalTokenProvider.instances.clear()
    discovered_authority = "https://login.microsoftonline.com/tenant-123"
    monkeypatch.setattr(
        "modules.preprocessing.steps.gather_input_with_auth_step._discover_tenant",
        lambda env_url: "tenant-123",
    )
    monkeypatch.setattr(
        "modules.preprocessing.steps.gather_input_with_auth_step.MsalTokenProvider",
        StubMsalTokenProvider,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _: "https://fabrikam.crm.dynamics.com/",
    )

    context = step.execute(MigrationContext())

    assert context.tid == "tenant-123"
    assert context.oid == "user-456"
    assert context.upn == "maker@contoso.com"
    assert context.environment_url == "https://fabrikam.crm.dynamics.com"
    assert context.dataverse_client is not None
    assert context.dataverse_client.environment_url == "https://fabrikam.crm.dynamics.com"
    assert len(StubMsalTokenProvider.instances) == 1
    provider = StubMsalTokenProvider.instances[0]
    assert provider.config.client_id == "51f81489-12ee-4a9e-aaae-a2591f45987d"
    assert provider.config.authority == discovered_authority
    assert provider.config.scopes == ("https://fabrikam.crm.dynamics.com/user_impersonation",)


def test_discover_tenant_reads_tenant_from_www_authenticate_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "modules.preprocessing.steps.gather_input_with_auth_step.httpx.get",
        lambda *args, **kwargs: httpx.Response(
            401,
            headers={
                "WWW-Authenticate": (
                    'Bearer authorization_uri="https://login.microsoftonline.com/'
                    'tenant-789/oauth2/authorize"'
                ),
            },
        ),
    )

    assert _discover_tenant("https://fabrikam.crm.dynamics.com") == "tenant-789"


def test_discover_tenant_defaults_to_organizations_when_header_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "modules.preprocessing.steps.gather_input_with_auth_step.httpx.get",
        lambda *args, **kwargs: httpx.Response(401),
    )

    assert _discover_tenant("https://fabrikam.crm.dynamics.com") == "organizations"


def test_gather_preferred_solution_step_stores_solution_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = FakeLogger()
    step = GatherPreferredSolutionStep(logger, ("READONLY", "WRITEBACK"))  # type: ignore[arg-type]
    monkeypatch.setattr("builtins.input", lambda _: "ess_customizations")

    result = step.execute(MigrationContext())

    assert result.preferred_solution == "ess_customizations"


def test_gather_preferred_solution_step_leaves_solution_empty_when_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = FakeLogger()
    step = GatherPreferredSolutionStep(logger, ("READONLY", "WRITEBACK"))  # type: ignore[arg-type]
    monkeypatch.setattr("builtins.input", lambda _: "   ")

    result = step.execute(MigrationContext())

    assert result.preferred_solution is None


def test_agent_selection_step_queries_agents_and_stores_selected_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = FakeLogger()
    step = AgentSelectionStep(logger, ("READONLY", "WRITEBACK"))  # type: ignore[arg-type]
    fake_client = FakeDataverseClient(
        [
            {"name": "Zebra Agent", "botid": "bot-z", "statecode": 1},
            {"name": "Alpha Agent", "botid": "bot-a", "statecode": 0},
        ],
    )
    context = MigrationContext(dataverse_client=fake_client)
    monkeypatch.setattr("builtins.input", lambda _: "1")

    result = step.execute(context)

    assert fake_client.calls == [("bots", "name,botid,statecode")]
    assert result.selected_agent_id == "bot-a"
    assert result.selected_agent_name == "Alpha Agent"
    assert ("INFO", "1. Alpha Agent [bot-a] state=0") in logger.messages
    assert ("INFO", "2. Zebra Agent [bot-z] state=1") in logger.messages


def test_build_input_pipeline_wires_steps_in_order() -> None:
    pipeline = build_input_pipeline(FakeLogger(), ("READONLY", "WRITEBACK"))  # type: ignore[arg-type]

    assert [step.name() for step in pipeline.steps] == [
        "GatherInputWithAuthStep",
        "AgentSelectionStep",
        "GatherPreferredSolutionStep",
    ]
