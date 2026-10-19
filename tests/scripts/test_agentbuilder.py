# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline contracts for the narrowly backported AgentBuilder read client."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
import requests
import responses
import yaml
from responses import matchers

import agentbuilder


TENANT_ID = "00000000-0000-0000-0000-000000001111"
ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
BOT_ID = "00000000-0000-0000-0000-000000001111"
HOST = "https://0000000000004000800000000000111.1.environment.api.test.powerplatform.com"
COMPONENTS_URL = f"{HOST}/copilotstudio/minimalBots/api/{BOT_ID}/components"


def _client(session: requests.Session) -> agentbuilder.AgentBuilderClient:
    return agentbuilder.AgentBuilderClient(
        HOST, "offline-token", ring="test", tenant_id=TENANT_ID,
        api_version="2099-01-01", session=session,
    )


@responses.activate
def test_fetch_components_retains_the_existing_client_wire_contract() -> None:
    # The registration shape is captured at the Island Gateway, not evidence
    # that its version is interchangeable with the client's native ALM version.
    cassette = Path(__file__).parents[1] / "fixtures/cassettes/island_gateway_botcomponents.yaml"
    recorded = next(
        entry
        for entry in yaml.safe_load(cassette.read_text(encoding="utf-8"))["interactions"]
        if entry["request"]["uri"].endswith("/content/botcomponents")
    )
    payload = json.loads(recorded["response"]["body"]["string"])
    responses.post(
        COMPONENTS_URL,
        json=payload,
        match=[
            matchers.query_param_matcher(
                {"api-version": agentbuilder.NATIVE_ALM_API_VERSION}
            ),
            matchers.json_params_matcher({}),
        ],
    )

    with requests.Session() as session:
        client = _client(session)
        assert client.fetch_components(BOT_ID) == payload
        retry = session.get_adapter(HOST).max_retries
        assert retry.allowed_methods == frozenset({"GET", "HEAD", "OPTIONS"})
        assert "POST" not in retry.allowed_methods

    request = responses.calls[0].request
    assert agentbuilder.NATIVE_ALM_API_VERSION == "2022-03-01-preview"
    assert "2099-01-01" not in request.url
    assert request.headers["Authorization"] == "Bearer offline-token"
    assert request.headers["x-ms-client-name"] == "CopilotStudio"
    assert request.headers["Content-Type"] == "application/json"
    assert len(responses.calls) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
@responses.activate
def test_component_http_failures_are_not_empty_discovery_or_retried(status) -> None:
    responses.post(
        COMPONENTS_URL, status=status, json={"error": {"code": "Denied"}},
        headers={"x-ms-request-id": "offline-request"},
    )

    with requests.Session() as session:
        with pytest.raises(agentbuilder.AgentBuilderHTTPError) as caught:
            _client(session).fetch_components(BOT_ID)

    assert caught.value.status_code == status
    assert caught.value.error_code == "Denied"
    assert caught.value.request_id == "offline-request"
    assert len(responses.calls) == 1


@pytest.mark.parametrize("payload", [[], None, "not-an-object"])
@responses.activate
def test_components_reject_non_object_json(payload) -> None:
    responses.post(COMPONENTS_URL, body=json.dumps(payload), content_type="application/json")

    with requests.Session() as session:
        with pytest.raises(agentbuilder.AgentBuilderError, match="invalid shape"):
            _client(session).fetch_components(BOT_ID)


@responses.activate
def test_components_reject_non_json() -> None:
    responses.post(COMPONENTS_URL, body="<html>upstream failure</html>")

    with requests.Session() as session:
        with pytest.raises(agentbuilder.AgentBuilderError, match="non-JSON"):
            _client(session).fetch_components(BOT_ID)


@pytest.mark.parametrize(
    ("ring", "split", "suffix"),
    [
        ("prod", 30, "environment.api.powerplatform.com"),
        ("preprod", 31, "environment.api.preprod.powerplatform.com"),
        ("test", 31, "environment.api.test.powerplatform.com"),
    ],
)
def test_environment_host_derivation_preserves_ring_and_environment(ring, split, suffix):
    attempted = []

    def resolver(hostname, port):
        attempted.append((hostname, port))
        return [object()]

    compact = ENVIRONMENT_ID.replace("-", "")
    expected = f"https://{compact[:split]}.{compact[split:]}.{suffix}"
    host = agentbuilder.derive_environment_host(ENVIRONMENT_ID, ring, resolver=resolver)

    assert host == expected
    assert attempted == [(expected.removeprefix("https://"), 443)]
    assert agentbuilder.environment_id_from_host(host, ring) == ENVIRONMENT_ID
    assert agentbuilder.ring_from_environment_host(host) == ring
    assert agentbuilder.minimal_bot_read_scope(ring) == (
        f"{agentbuilder.RING_CONFIG[ring]['audience']}/CopilotStudio.MinimalBot.Read"
    )


def test_environment_host_derivation_tries_the_alternate_dns_split() -> None:
    attempted = []

    def resolver(hostname, port):
        attempted.append(hostname)
        if len(attempted) == 1:
            raise socket.gaierror
        return [object()]

    compact = ENVIRONMENT_ID.replace("-", "")
    assert agentbuilder.derive_environment_host(
        ENVIRONMENT_ID, "test", resolver=resolver
    ) == f"https://{compact[:30]}.{compact[30:]}.environment.api.test.powerplatform.com"
    assert len(attempted) == 2


@pytest.mark.parametrize(
    "host",
    [
        "http://example.environment.api.test.powerplatform.com",
        "https://example.environment.api.powerplatform.com",
        HOST + "/path",
        HOST + "?token=private",
        HOST + "#fragment",
        HOST.replace("https://", "https://user:password@"),
        HOST + ".attacker.example",
    ],
)
def test_unsafe_or_cross_ring_hosts_are_rejected(host) -> None:
    with pytest.raises(ValueError, match="environment host"):
        agentbuilder.validate_environment_host(host, "test")


@responses.activate
def test_environment_listing_uses_its_own_version_and_safe_pagination() -> None:
    url = "https://api.test.powerplatform.com/environmentmanagement/environments"
    next_url = f"{url}?api-version=2024-10-01&$skip=1"
    first = {"id": ENVIRONMENT_ID, "url": "https://orgmocktenant.crm.dynamics.com"}
    second = {"id": BOT_ID, "domainName": "orgsecond.crm.dynamics.com"}
    responses.get(
        url, json={"value": [first], "@odata.nextlink": next_url},
        match=[matchers.query_param_matcher({"api-version": "2024-10-01"})],
    )
    responses.get(next_url, json={"value": [second]})

    with requests.Session() as session:
        result = agentbuilder.list_environments("offline-token", "test", session=session)

    assert result == [first, second]
    assert len(responses.calls) == 2
    assert all(call.request.method == "GET" for call in responses.calls)


@responses.activate
def test_environment_listing_refuses_an_external_continuation() -> None:
    responses.get(
        "https://api.test.powerplatform.com/environmentmanagement/environments",
        json={"value": [], "@odata.nextLink": "https://private.example/next"},
    )

    with requests.Session() as session:
        with pytest.raises(agentbuilder.AgentBuilderError, match="unsafe continuation"):
            agentbuilder.list_environments("offline-token", "test", session=session)

    assert len(responses.calls) == 1
