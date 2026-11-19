# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
import socket
from collections.abc import Mapping
from typing import Any

import pytest
import requests

import agentbuilder
import alm_enrollment


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
SCHEMA = "gptagent_freshstarter"
_MISSING = object()


class FakeHTTPResponse:
    def __init__(
        self,
        status_code: int,
        *,
        json_body: Any = _MISSING,
        text: str = "",
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_body = json_body
        self.text = text if json_body is _MISSING else json.dumps(json_body)
        self.headers = headers or {}

    def json(self) -> Any:
        if self._json_body is _MISSING:
            raise ValueError("Response body is not JSON.")
        return self._json_body


class FakeAlmClient:
    def __init__(
        self,
        *,
        fetch_responses: list[Any],
        update_response: FakeHTTPResponse | None = None,
        update_exception: BaseException | None = None,
    ) -> None:
        self._fetch_responses = fetch_responses
        self._update_response = update_response
        self._update_exception = update_exception
        self.fetch_calls: list[str] = []
        self.update_calls: list[tuple[str, dict[str, Any]]] = []

    def fetch_components(self, agent_id: str) -> dict[str, Any]:
        self.fetch_calls.append(agent_id)
        result = self._fetch_responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def update_bot_entity(
        self,
        agent_id: str,
        bot: dict[str, Any],
    ) -> FakeHTTPResponse:
        self.update_calls.append((agent_id, bot))
        if self._update_exception is not None:
            raise self._update_exception
        assert self._update_response is not None
        return self._update_response


def _bot_changeset(
    *,
    version: int,
    alm_enabled: Any = _MISSING,
) -> dict[str, Any]:
    settings = {"existing": "preserved"}
    if alm_enabled is not _MISSING:
        settings["alm.isAlmEnabled"] = alm_enabled
    return {
        "bot": {
            "$kind": "BotEntity",
            "version": version,
            "cdsBotId": AGENT_ID,
            "schemaName": SCHEMA,
            "configuration": {
                "$kind": "BotConfiguration",
                "gPTSettings": {"defaultSchemaName": "gptagent_ess"},
                "settings": settings,
            },
            "unknownFutureField": {"preserve": True},
        },
        "botComponentChanges": [
            {"existingComponent": "must-not-be-resubmitted"}
        ],
        "changeToken": "read-only-evidence",
    }


def test_ensure_alm_preserves_full_bot_and_verifies_read_back(
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = _bot_changeset(version=1)
    client = FakeAlmClient(
        fetch_responses=[
            before,
            _bot_changeset(version=2, alm_enabled=True),
        ],
        update_response=FakeHTTPResponse(
            200,
            json_body={
                "botComponentChanges": [],
                "unknownServiceField": "preserved in evidence",
                "authorization": "leak-me-not",
            },
            headers={"x-ms-request-id": "req-alm-42"},
        ),
    )

    result = alm_enrollment.ensure_alm(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
    )

    assert client.fetch_calls == [AGENT_ID, AGENT_ID]
    assert len(client.update_calls) == 1
    update_agent_id, update_bot = client.update_calls[0]
    assert update_agent_id == AGENT_ID
    assert update_bot["configuration"]["settings"] == {
        "existing": "preserved",
        "alm.isAlmEnabled": True,
    }
    assert update_bot["configuration"]["gPTSettings"] == {
        "defaultSchemaName": "gptagent_ess"
    }
    assert update_bot["unknownFutureField"] == {"preserve": True}
    assert before["bot"]["configuration"]["settings"] == {
        "existing": "preserved"
    }
    assert result == {
        "environmentId": ENVIRONMENT_ID,
        "agentId": AGENT_ID,
        "outcome": "enabled",
        "beforeBotVersion": 1,
        "afterBotVersion": 2,
        "previousValue": None,
        "persistedValue": True,
    }

    output = capsys.readouterr().out
    annotations = json.loads(
        output.split("DA_ALM_ENROLLMENT_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    response = json.loads(
        output.split("DA_ALM_ENROLLMENT_RESPONSE_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["outcome"] == "update-accepted"
    assert annotations["requestId"] == "req-alm-42"
    assert response["unknownServiceField"] == "preserved in evidence"
    assert response["authorization"] == "[REDACTED]"


def test_ensure_alm_reads_request_id_from_response_header_mapping(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeAlmClient(
        fetch_responses=[
            _bot_changeset(version=1),
            _bot_changeset(version=2, alm_enabled=True),
        ],
        update_response=FakeHTTPResponse(
            200,
            json_body={"accepted": True},
            headers=requests.structures.CaseInsensitiveDict(
                {"X-MS-Request-ID": "req-mapped"}
            ),
        ),
    )

    alm_enrollment.ensure_alm(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
    )

    annotations = json.loads(
        capsys.readouterr()
        .out.split("DA_ALM_ENROLLMENT_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["requestId"] == "req-mapped"


def test_ensure_alm_is_repeatable_without_a_second_write() -> None:
    client = FakeAlmClient(
        fetch_responses=[_bot_changeset(version=2, alm_enabled=True)],
    )

    result = alm_enrollment.ensure_alm(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
    )

    assert result["outcome"] == "already-enabled"
    assert result["persistedValue"] is True
    assert client.fetch_calls == [AGENT_ID]
    assert client.update_calls == []


def test_ensure_alm_rejects_mismatched_fetched_agent_before_write() -> None:
    before = _bot_changeset(version=1)
    before["bot"]["cdsBotId"] = (
        "00000000-0000-4000-8000-000000006666"
    )
    client = FakeAlmClient(fetch_responses=[before])

    with pytest.raises(
        alm_enrollment.AlmEnrollmentError,
        match="does not match",
    ):
        alm_enrollment.ensure_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    assert client.update_calls == []


def test_ensure_alm_fails_when_read_back_does_not_persist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeAlmClient(
        fetch_responses=[
            _bot_changeset(version=1),
            _bot_changeset(version=2, alm_enabled=False),
        ],
        update_response=FakeHTTPResponse(
            200,
            json_body={"accepted": True},
        ),
    )

    with pytest.raises(
        alm_enrollment.AlmEnrollmentError,
        match="read-back",
    ):
        alm_enrollment.ensure_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    assert len(client.update_calls) == 1
    verification = json.loads(
        capsys.readouterr()
        .out.split("DA_ALM_ENROLLMENT_VERIFY_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert verification["outcome"] == "verification-failed"
    assert verification["persistedValue"] is False


def test_ensure_alm_preserves_rejection_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeAlmClient(
        fetch_responses=[_bot_changeset(version=1)],
        update_response=FakeHTTPResponse(
            409,
            json_body={
                "error": {
                    "code": "VersionConflict",
                    "message": "service-owned detail",
                }
            },
            headers={"x-ms-request-id": "req-conflict"},
        ),
    )

    with pytest.raises(
        alm_enrollment.AlmEnrollmentError,
        match="rejected",
    ):
        alm_enrollment.ensure_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    output = capsys.readouterr().out
    annotations = json.loads(
        output.split("DA_ALM_ENROLLMENT_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["httpStatus"] == 409
    assert annotations["errorCode"] == "VersionConflict"
    assert annotations["requestId"] == "req-conflict"


def test_ensure_alm_redacts_credential_shaped_text_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeAlmClient(
        fetch_responses=[_bot_changeset(version=1)],
        update_response=FakeHTTPResponse(
            500,
            text=(
                "Authorization: Bearer secret-token "
                "client_secret=do-not-print diagnostic=kept"
            ),
        ),
    )

    with pytest.raises(alm_enrollment.AlmEnrollmentError, match="rejected"):
        alm_enrollment.ensure_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    response = (
        capsys.readouterr()
        .out.split("DA_ALM_ENROLLMENT_RESPONSE_TEXT:", 1)[1]
        .splitlines()[0]
    )
    assert "secret-token" not in response
    assert "do-not-print" not in response
    assert "diagnostic=kept" in response
    assert response.count("[REDACTED]") == 2


def test_ensure_alm_uncertain_transport_preserves_causal_chain(
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        try:
            raise socket.timeout("socket timed out")
        except socket.timeout as socket_error:
            raise requests.exceptions.ReadTimeout("read timed out") from (
                socket_error
            )
    except requests.exceptions.ReadTimeout as transport_error:
        error = transport_error
    client = FakeAlmClient(
        fetch_responses=[
            _bot_changeset(version=1),
            _bot_changeset(version=1, alm_enabled=False),
        ],
        update_exception=error,
    )

    with pytest.raises(
        alm_enrollment.AlmEnrollmentError,
        match="outcome remains uncertain",
    ):
        alm_enrollment.ensure_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    output = capsys.readouterr().out
    annotations = json.loads(
        output.split("DA_ALM_ENROLLMENT_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["outcome"] == "uncertain-transport"
    assert annotations["transportErrorType"] == "ReadTimeout"
    assert annotations["transportErrorChain"] == [
        {"type": "ReadTimeout", "message": "read timed out"},
        {"type": "TimeoutError", "message": "socket timed out"},
    ]
    verification = json.loads(
        output.split("DA_ALM_ENROLLMENT_VERIFY_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert verification["outcome"] == "uncertain"
    assert verification["persistedValue"] is False


def test_ensure_alm_reconciles_uncertain_transport_with_read_back(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeAlmClient(
        fetch_responses=[
            _bot_changeset(version=1),
            _bot_changeset(version=2, alm_enabled=True),
        ],
        update_exception=requests.exceptions.ReadTimeout("read timed out"),
    )

    result = alm_enrollment.ensure_alm(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
    )

    assert result["outcome"] == "enabled"
    assert result["updateOutcome"] == "uncertain-transport"
    assert result["persistedValue"] is True
    verification = json.loads(
        capsys.readouterr()
        .out.split("DA_ALM_ENROLLMENT_VERIFY_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert verification == result


def test_ensure_alm_preserves_verification_rejection_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    verification_response = FakeHTTPResponse(
        503,
        json_body={
            "error": {
                "code": "Unavailable",
                "message": "verification detail",
            }
        },
        headers={"x-ms-request-id": "req-verify"},
    )
    client = FakeAlmClient(
        fetch_responses=[
            _bot_changeset(version=1),
            agentbuilder.AgentBuilderHTTPError(
                "Component fetch",
                503,
                error_code="Unavailable",
                request_id="req-verify",
                response=verification_response,
            ),
        ],
        update_response=FakeHTTPResponse(
            200,
            json_body={"accepted": True},
        ),
    )

    with pytest.raises(
        alm_enrollment.AlmEnrollmentError,
        match="Verification did not complete",
    ):
        alm_enrollment.ensure_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    output = capsys.readouterr().out
    annotations = json.loads(
        output.split(
            "DA_ALM_ENROLLMENT_VERIFY_ANNOTATIONS_JSON:",
            1,
        )[1].splitlines()[0]
    )
    assert annotations["outcome"] == "verification-rejected"
    assert annotations["errorCode"] == "Unavailable"
    assert annotations["requestId"] == "req-verify"
