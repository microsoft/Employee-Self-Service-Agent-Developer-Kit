# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ``flightcheck.graph_client.GraphClient.search_users``.

``search_users`` is the one live directory hop the ``/roles`` attestation skill
needs: it turns a person's name (or email / UPN) into the Entra object id used as
the attestation ``subjectId``. These tests exercise it against the schema-backed
(validatable) Graph ``/users`` mock, pinning:

* the outgoing ``$search`` / ``$select`` and the ``ConsistencyLevel: eventual``
  header ``$search`` requires,
* the degrade-quietly contract (blank query -> no call; 401/403 -> ``[]``;
  empty result -> ``[]``).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import responses

from flightcheck.graph_client import GraphClient
from tests.conftest import require_validated_mock
from tests.mocks import graph

require_validated_mock(graph)


def _client(token: str = "fake-token") -> GraphClient:
    client = GraphClient("tenant-Z")
    client._token = token  # skip MSAL; headers only need a bearer value
    return client


@responses.activate
def test_search_users_returns_candidates_and_sends_search_query():
    responses.add(
        **graph.search_users(
            users=[
                graph.user(
                    user_id="oid-1",
                    display_name="Priya Sharma",
                    user_principal_name="priya@contoso.com",
                    job_title="HR Analyst",
                )
            ]
        )
    )

    users = _client().search_users("Priya Sharma")

    assert [u["id"] for u in users] == ["oid-1"]
    request = responses.calls[0].request
    query = parse_qs(urlparse(request.url).query)
    assert query["$search"][0].startswith('"displayName:Priya Sharma"')
    assert query["$select"][0] == "id,displayName,userPrincipalName,mail,jobTitle"
    # $search on directory objects is rejected without eventual consistency.
    assert request.headers.get("ConsistencyLevel") == "eventual"


@responses.activate
def test_search_users_blank_query_makes_no_call():
    users = _client().search_users("   ")
    assert users == []
    assert len(responses.calls) == 0


@responses.activate
def test_search_users_no_match_returns_empty_list():
    responses.add(**graph.search_users(users=[]))
    assert _client().search_users("Nobody Here") == []


@responses.activate
def test_search_users_permission_denied_returns_empty_list():
    # Missing a directory user-read scope -> Graph 403 -> quiet [] (the caller
    # prompts the maker to sign in / consent, or escalates to the fallback).
    responses.add(method="GET", url=f"{graph.GRAPH_BASE}/users", status=403, json={})
    assert _client().search_users("Priya") == []
