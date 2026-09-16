# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any

import pytest
import requests

import agentbuilder
import setup_mos_starter as mos


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
TENANT_ID = "00000000-0000-4000-8000-000000009999"
HOST = (
    "https://0000000000004000800000000000111."
    "1.environment.api.test.powerplatform.com"
)
SCHEMA = "gptagent_freshstarter"
FUSE_RELATIVE = ".local/setup/mos-starter/create-attempted"
_MISSING = object()


class FakeHTTPResponse:
    """Minimal stand-in for the ``requests.Response`` surface this module uses."""

    def __init__(
        self,
        status_code: int,
        *,
        json_body: Any = _MISSING,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_body = json_body
        self.text = text if json_body is _MISSING else json.dumps(json_body)
        self.headers = headers or {}

    def json(self) -> Any:
        if self._json_body is _MISSING:
            raise ValueError("Response body is not JSON.")
        return self._json_body


class FakeMosClient:
    """Fakes the single create POST."""

    host = HOST
    ring = "test"
    tenant_id = TENANT_ID
    api_version = "2024-10-01"

    def __init__(
        self,
        *,
        create_response: FakeHTTPResponse | None = None,
        create_exception: BaseException | None = None,
        kit_root: Path | None = None,
    ) -> None:
        self.create_calls = 0
        self.fuse_existed_at_dispatch: bool | None = None
        self._create_response = create_response
        self._create_exception = create_exception
        self._kit_root = kit_root

    def create_agent_from_starter_package(self, package_id: str) -> FakeHTTPResponse:
        self.create_calls += 1
        if self._kit_root is not None:
            self.fuse_existed_at_dispatch = (
                self._kit_root / FUSE_RELATIVE
            ).exists()
        if self._create_exception is not None:
            raise self._create_exception
        assert self._create_response is not None
        return self._create_response


class FakeCatalogClient:
    """Fakes only the read-only ``list_starter_packages`` GET."""

    def __init__(
        self,
        *,
        packages: list[Any] | None = None,
        exception: BaseException | None = None,
    ) -> None:
        self._packages = packages
        self._exception = exception

    def list_starter_packages(self) -> list[Any]:
        if self._exception is not None:
            raise self._exception
        assert self._packages is not None
        return self._packages


class FakeAlmClient:
    """Fakes the bounded fetch, BotEntity update, and verification fetch."""

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
        "botComponentChanges": [{"existingComponent": "must-not-be-resubmitted"}],
        "changeToken": "read-only-evidence",
    }


def _dns_failure() -> requests.exceptions.ConnectionError:
    try:
        try:
            raise socket.gaierror(-2, "Name or service not known")
        except socket.gaierror as dns_exc:
            raise requests.exceptions.ConnectionError("dns lookup failed") from (
                dns_exc
            )
    except requests.exceptions.ConnectionError as chained:
        return chained


def _connection_refused() -> requests.exceptions.ConnectionError:
    try:
        try:
            raise ConnectionRefusedError("actively refused")
        except ConnectionRefusedError as refused_exc:
            raise requests.exceptions.ConnectionError("refused") from refused_exc
    except requests.exceptions.ConnectionError as chained:
        return chained


# --- catalog (list) -----------------------------------------------------


def test_summarize_starter_packages_drops_blank_or_missing_package_ids() -> None:
    packages = [
        {"packageId": "pkg-1", "name": "Beta"},
        {"packageId": "", "name": "Blank id excluded"},
        {"name": "Missing id excluded"},
        {"packageId": "   ", "name": "Whitespace id excluded"},
        {"packageId": "pkg-2", "name": "Alpha"},
        "not-a-dict",
    ]

    result = mos.summarize_starter_packages(packages)

    assert [item["packageId"] for item in result] == ["pkg-2", "pkg-1"]
    assert all("shortDescription" in item for item in result)


def test_summarize_starter_packages_never_mutates_input() -> None:
    packages = [{"packageId": "pkg-1", "name": "Beta", "secretField": "keep"}]

    result = mos.summarize_starter_packages(packages)

    assert packages[0]["secretField"] == "keep"
    assert "secretField" not in result[0]


def test_catalog_warnings_reports_malformed_rows_with_safe_projection_only() -> None:
    packages = [
        {"packageId": "pkg-1", "name": "Beta"},
        "not-a-dict",
        {"name": "Missing id", "secretField": "must-not-copy"},
        {"packageId": "  ", "name": "Blank id"},
    ]

    warnings = mos.catalog_warnings(packages)

    assert warnings[0] == {"index": 1, "reason": "not-an-object"}
    assert warnings[1]["index"] == 2
    assert warnings[1]["reason"] == "missing-package-id"
    assert warnings[1]["package"]["name"] == "Missing id"
    assert "secretField" not in warnings[1]["package"]
    assert warnings[2]["index"] == 3
    assert warnings[2]["reason"] == "missing-package-id"
    assert len(warnings) == 3


def test_catalog_warnings_is_empty_when_every_row_is_valid() -> None:
    packages = [{"packageId": "pkg-1", "name": "Beta"}]

    assert mos.catalog_warnings(packages) == []


# --- redaction ---------------------------------------------------------


def test_redact_json_masks_nested_case_varied_secret_fields() -> None:
    body = {
        "AUTHORIZATION": "should-be-hidden",
        "nested": {
            "Cookie": "session=abc",
            "Client_Secret": "topsecret",
            "deeper": [{"Access_Token": "tok"}, {"refreshToken": "rtok"}],
        },
        "packageId": "pkg-1",
        "message": "Unfamiliar detail the platform sent back",
        "unknownField": "keep me exactly",
    }

    redacted = mos.redact_json(body)

    assert redacted["AUTHORIZATION"] == mos.REDACTED
    assert redacted["nested"]["Cookie"] == mos.REDACTED
    assert redacted["nested"]["Client_Secret"] == mos.REDACTED
    assert redacted["nested"]["deeper"][0]["Access_Token"] == mos.REDACTED
    assert redacted["nested"]["deeper"][1]["refreshToken"] == mos.REDACTED
    assert redacted["packageId"] == "pkg-1"
    assert redacted["message"] == "Unfamiliar detail the platform sent back"
    assert redacted["unknownField"] == "keep me exactly"


def test_redact_text_masks_bounded_credential_patterns_preserves_rest() -> None:
    text = (
        "HTTP/1.1 401 Unauthorized\n"
        "Authorization: " + "Bear" + "er abc.def.ghi\n"
        "Set-Cookie: session=xyz; Path=/\n"
        'body: {"password": "hunter2", "message": "unexpected input"}'
    )

    redacted = mos.redact_text(text)

    assert "abc.def.ghi" not in redacted
    assert "hunter2" not in redacted
    assert "session=xyz" not in redacted
    assert "unexpected input" in redacted
    assert "401 Unauthorized" in redacted


def test_redact_text_preserves_json_key_quoting_around_secret_value() -> None:
    text = 'prefix {"password": "hunter2"} suffix'

    redacted = mos.redact_text(text)

    assert redacted == 'prefix {"password": "' + mos.REDACTED + '"} suffix'


def test_redact_json_preserves_benign_lookalike_field_names() -> None:
    body = {
        "secretaryName": "Jordan Pat",
        "cookiePolicy": "https://example.com/cookies",
        "authorizationStatus": "approved",
        "developerName": "Contoso",
    }

    redacted = mos.redact_json(body)

    assert redacted == body


def test_redact_json_recursively_redacts_credential_shapes_in_benign_keyed_strings() -> (
    None
):
    scheme = "Bear" + "er"
    body = {
        "message": f"Retry with {scheme} abc.def.ghi and password=hunter2",
        "unrelatedNote": "Nothing sensitive to see here",
    }

    redacted = mos.redact_json(body)

    assert "abc.def.ghi" not in redacted["message"]
    assert "hunter2" not in redacted["message"]
    assert mos.REDACTED in redacted["message"]
    assert "Retry with" in redacted["message"]
    assert redacted["unrelatedNote"] == "Nothing sensitive to see here"


def test_redact_text_bearer_substitution_uses_the_redacted_marker() -> None:
    scheme = "Bear" + "er"
    redacted = mos.redact_text(f"{scheme} abc.def.ghi")

    assert redacted == mos.REDACTED


# --- fuse lifecycle ------------------------------------------------------


def test_create_fuse_exists_before_dispatch_and_is_retained_after_create(
    tmp_path: Path,
) -> None:
    client = FakeMosClient(
        create_response=FakeHTTPResponse(
            201,
            json_body={
                "botId": AGENT_ID,
                "sourcePackage": {
                    "packageId": "pkg-1",
                    "schemaName": SCHEMA,
                    "version": "1.0.0",
                },
            },
        ),
        kit_root=tmp_path,
    )

    result = mos.create_from_starter_package(
        client,
        environment_id=ENVIRONMENT_ID,
        package_id="pkg-1",
        kit_root=tmp_path,
        package_name="First Package",
        package_version="1.0.0",
    )

    assert client.fuse_existed_at_dispatch is True
    assert (tmp_path / FUSE_RELATIVE).is_file()
    assert "catalogPackageVersion: 1.0.0" in (
        tmp_path / FUSE_RELATIVE
    ).read_text(encoding="utf-8")
    assert result["environmentId"] == ENVIRONMENT_ID
    assert result["agentId"] == AGENT_ID
    assert result["schemaName"] == SCHEMA
    assert result["starterPackageId"] == "pkg-1"
    assert result["starterPackageName"] == "First Package"
    assert result["catalogPackageVersion"] == "1.0.0"
    assert result["templateVersion"] == "1.0.0"
    assert not (tmp_path / ".local" / "setup" / "config.json").exists()
    assert not (tmp_path / "workspace").exists()


def test_existing_fuse_blocks_a_second_create_without_dispatching(
    tmp_path: Path,
) -> None:
    fuse_path = tmp_path / FUSE_RELATIVE
    fuse_path.parent.mkdir(parents=True)
    fuse_path.write_text("startedAt: earlier attempt\n", encoding="utf-8")
    client = FakeMosClient(kit_root=tmp_path)

    with pytest.raises(
        mos.MosStarterSetupError,
        match="already been attempted|already attempted",
    ):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    assert client.create_calls == 0
    assert fuse_path.read_text(encoding="utf-8") == "startedAt: earlier attempt\n"


def test_create_rejects_blank_package_id(tmp_path: Path) -> None:
    client = FakeMosClient(kit_root=tmp_path)

    with pytest.raises(mos.MosStarterSetupError, match="package ID is required"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="   ",
            kit_root=tmp_path,
        )

    assert client.create_calls == 0
    assert not (tmp_path / FUSE_RELATIVE).exists()


def test_create_enforces_empty_workspace_guard(tmp_path: Path) -> None:
    (tmp_path / ".local").mkdir()
    (tmp_path / ".local" / "config.json").write_text("{}", encoding="utf-8")
    client = FakeMosClient(kit_root=tmp_path)

    with pytest.raises(mos.MosStarterSetupError, match="already contains"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    assert client.create_calls == 0
    assert not (tmp_path / FUSE_RELATIVE).exists()


@pytest.mark.parametrize(
    "build_exception",
    [
        lambda: requests.exceptions.ConnectTimeout("connect timed out"),
        _dns_failure,
        _connection_refused,
    ],
)
def test_create_removes_fuse_on_pre_dispatch_failure(
    tmp_path: Path,
    build_exception: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeMosClient(create_exception=build_exception(), kit_root=tmp_path)

    with pytest.raises(mos.MosStarterSetupError, match="did not reach the service"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    assert not (tmp_path / FUSE_RELATIVE).exists()
    annotations = json.loads(
        capsys.readouterr()
        .out.split("DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["outcome"] == "pre-dispatch-failure"
    assert annotations["fuseDisposition"] == "removed"


@pytest.mark.parametrize(
    "build_exception",
    [
        lambda: requests.exceptions.ReadTimeout("read timed out"),
        lambda: requests.exceptions.ConnectionError("connection reset"),
        lambda: requests.exceptions.Timeout("ambiguous timeout"),
    ],
)
def test_create_keeps_fuse_on_uncertain_transport_failure(
    tmp_path: Path,
    build_exception: Any,
) -> None:
    client = FakeMosClient(create_exception=build_exception(), kit_root=tmp_path)

    with pytest.raises(mos.MosStarterSetupError, match="outcome is uncertain"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    assert (tmp_path / FUSE_RELATIVE).is_file()


def test_uncertain_transport_preserves_redacted_runtime_context(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport_error = requests.exceptions.ConnectionError(
        "connection reset after Authorization: Bearer abc.def.ghi"
    )
    client = FakeMosClient(
        create_exception=transport_error,
        kit_root=tmp_path,
    )

    with pytest.raises(mos.MosStarterSetupError) as raised:
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    annotations = json.loads(
        capsys.readouterr()
        .out.split("DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert raised.value.__cause__ is transport_error
    assert annotations["transportErrorType"] == "ConnectionError"
    assert annotations["transportError"] == (
        "connection reset after Authorization: <redacted>"
    )
    assert annotations["outcome"] == "uncertain-transport"
    assert annotations["fuseDisposition"] == "retained"


def test_create_keeps_fuse_on_malformed_2xx_missing_identity(
    tmp_path: Path,
) -> None:
    client = FakeMosClient(
        create_response=FakeHTTPResponse(200, json_body={"unexpected": "shape"}),
        kit_root=tmp_path,
    )

    with pytest.raises(mos.MosStarterSetupError, match="usable agent identity"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    assert (tmp_path / FUSE_RELATIVE).is_file()


def test_create_keeps_fuse_on_non_json_2xx_body(tmp_path: Path) -> None:
    client = FakeMosClient(
        create_response=FakeHTTPResponse(200, text="<html>not json</html>"),
        kit_root=tmp_path,
    )

    with pytest.raises(mos.MosStarterSetupError, match="usable agent identity"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    assert (tmp_path / FUSE_RELATIVE).is_file()


def test_create_keeps_fuse_when_service_returns_a_different_package(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeMosClient(
        create_response=FakeHTTPResponse(
            201,
            json_body={
                "botId": AGENT_ID,
                "sourcePackage": {
                    "packageId": "different-package",
                    "schemaName": SCHEMA,
                    "version": "1.0.0",
                },
            },
        ),
        kit_root=tmp_path,
    )

    with pytest.raises(mos.MosStarterSetupError, match="different source package"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    annotations = json.loads(
        capsys.readouterr()
        .out.split("DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["outcome"] == "source-package-mismatch"
    assert annotations["returnedPackageId"] == "different-package"
    assert annotations["fuseDisposition"] == "retained"
    assert (tmp_path / FUSE_RELATIVE).is_file()


@pytest.mark.parametrize("status", [300, 302, 405, 408, 425, 429, 500, 502, 503])
def test_create_keeps_fuse_on_uncertain_status_codes(
    tmp_path: Path,
    status: int,
) -> None:
    client = FakeMosClient(
        create_response=FakeHTTPResponse(status, json_body={"message": "wait"}),
        kit_root=tmp_path,
    )

    with pytest.raises(mos.MosStarterSetupError, match="not a definitive outcome"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    assert (tmp_path / FUSE_RELATIVE).is_file()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 412, 422])
def test_create_removes_fuse_on_definitive_rejection(
    tmp_path: Path,
    status: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeMosClient(
        create_response=FakeHTTPResponse(
            status,
            json_body={"error": {"code": "Rejected"}},
        ),
        kit_root=tmp_path,
    )

    with pytest.raises(mos.MosStarterSetupError, match="rejected"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    assert not (tmp_path / FUSE_RELATIVE).exists()
    annotations = json.loads(
        capsys.readouterr()
        .out.split("DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["outcome"] == "rejected"
    assert annotations["fuseDisposition"] == "removed"


def test_create_removes_fuse_and_reports_collision_on_409(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeMosClient(
        create_response=FakeHTTPResponse(
            409,
            json_body={"error": {"code": "Conflict"}},
        ),
        kit_root=tmp_path,
    )

    with pytest.raises(mos.MosStarterSetupError, match="collision"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    assert not (tmp_path / FUSE_RELATIVE).exists()
    annotations = json.loads(
        capsys.readouterr()
        .out.split("DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["outcome"] == "collision"
    assert annotations["fuseDisposition"] == "removed"


def test_emit_annotations_recursively_redacts_before_printing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    scheme = "Bear" + "er"
    annotations = {
        "targetEnvironmentId": ENVIRONMENT_ID,
        "outcome": "uncertain-transport",
        "transportError": (
            f"Upstream rejected with {scheme} abc.def.ghi and "
            "client_secret=topsecret999"
        ),
    }

    mos._emit_annotations(annotations)

    out = capsys.readouterr().out
    printed = json.loads(
        out.split("DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:", 1)[1].splitlines()[0]
    )
    assert printed["targetEnvironmentId"] == ENVIRONMENT_ID
    assert printed["outcome"] == "uncertain-transport"
    assert "abc.def.ghi" not in printed["transportError"]
    assert "topsecret999" not in printed["transportError"]
    assert printed["transportError"].count(mos.REDACTED) == 2
    assert "Upstream rejected with" in printed["transportError"]


def test_create_fuse_write_failure_closes_removes_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_fsync(_fd: int) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(mos.os, "fsync", failing_fsync)
    client = FakeMosClient(kit_root=tmp_path)

    with pytest.raises(OSError, match="simulated disk failure"):
        mos.create_from_starter_package(
            client,
            environment_id=ENVIRONMENT_ID,
            package_id="pkg-1",
            kit_root=tmp_path,
        )

    assert client.create_calls == 0
    assert not (tmp_path / FUSE_RELATIVE).exists()


def test_create_fuse_cleanup_failure_is_attached_to_original_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_error = OSError("simulated write failure")

    def failing_fsync(_fd: int) -> None:
        raise write_error

    def failing_unlink(_self: Path, *, missing_ok: bool = False) -> None:
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(mos.os, "fsync", failing_fsync)
    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(OSError) as raised:
        mos._create_fuse(tmp_path / FUSE_RELATIVE, "attempt")

    assert raised.value is write_error
    assert raised.value.__notes__ == [
        "The partial attempt fuse could not be removed: simulated cleanup failure"
    ]


def test_evidence_annotations_and_response_are_printed_and_redacted(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeMosClient(
        create_response=FakeHTTPResponse(
            201,
            json_body={
                "botId": AGENT_ID,
                "sourcePackage": {
                    "packageId": "pkg-1",
                    "schemaName": SCHEMA,
                    "version": "1.0.0",
                },
                "diagnostics": {"Authorization": "leak-me-not"},
            },
            headers={"x-ms-request-id": "req-42"},
        ),
        kit_root=tmp_path,
    )

    mos.create_from_starter_package(
        client,
        environment_id=ENVIRONMENT_ID,
        package_id="pkg-1",
        kit_root=tmp_path,
        package_name="First Package",
        package_version="1.0.0",
    )

    out = capsys.readouterr().out
    annotations = json.loads(
        out.split("DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:", 1)[1].splitlines()[0]
    )
    response = json.loads(
        out.split("DA_MOS_STARTER_CREATE_RESPONSE_JSON:", 1)[1].splitlines()[0]
    )
    assert annotations["httpStatus"] == 201
    assert annotations["requestId"] == "req-42"
    assert annotations["packageId"] == "pkg-1"
    assert annotations["fuseDisposition"] == "retained"
    assert annotations["outcome"] == "created"
    assert annotations["agentId"] == AGENT_ID
    assert annotations["schemaName"] == SCHEMA
    assert annotations["templateVersion"] == "1.0.0"
    assert response["diagnostics"]["Authorization"] == mos.REDACTED
    assert response["botId"] == AGENT_ID
    assert response["sourcePackage"]["version"] == "1.0.0"
    assert "leak-me-not" not in out


# --- list_starter_packages wrapper ---------------------------------------


def test_list_starter_packages_returns_valid_and_reports_warnings() -> None:
    client = FakeCatalogClient(
        packages=[
            {"packageId": "pkg-1", "name": "Beta"},
            "not-a-dict",
            {"name": "Missing id"},
        ]
    )

    result = mos.list_starter_packages(client, environment_id=ENVIRONMENT_ID)

    assert result["environmentId"] == ENVIRONMENT_ID
    assert [item["packageId"] for item in result["packages"]] == ["pkg-1"]
    assert len(result["catalogWarnings"]) == 2
    assert result["catalogWarnings"][0]["reason"] == "not-an-object"
    assert result["catalogWarnings"][1]["reason"] == "missing-package-id"


def test_list_starter_packages_prints_evidence_and_reraises_on_http_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_response = FakeHTTPResponse(
        500,
        json_body={
            "error": {
                "code": "InternalError",
                "message": "Unfamiliar upstream detail",
                "authorization": "leak-me-not",
            }
        },
        headers={"x-ms-request-id": "req-99"},
    )
    client = FakeCatalogClient(
        exception=agentbuilder.AgentBuilderHTTPError(
            "Starter package listing",
            500,
            request_id="req-99",
            response=raw_response,
        )
    )

    with pytest.raises(agentbuilder.AgentBuilderHTTPError):
        mos.list_starter_packages(client, environment_id=ENVIRONMENT_ID)

    out = capsys.readouterr().out
    annotations = json.loads(
        out.split("DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:", 1)[1].splitlines()[0]
    )
    response = json.loads(
        out.split("DA_MOS_STARTER_LIST_RESPONSE_JSON:", 1)[1].splitlines()[0]
    )
    assert annotations["httpStatus"] == 500
    assert annotations["requestId"] == "req-99"
    assert response["error"]["authorization"] == mos.REDACTED
    assert response["error"]["message"] == "Unfamiliar upstream detail"
    assert "leak-me-not" not in out


def test_list_starter_packages_reraises_without_evidence_when_no_response() -> None:
    client = FakeCatalogClient(
        exception=agentbuilder.AgentBuilderHTTPError("Starter package listing", 500)
    )

    with pytest.raises(agentbuilder.AgentBuilderHTTPError):
        mos.list_starter_packages(client, environment_id=ENVIRONMENT_ID)


def test_list_starter_packages_reports_invalid_response_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeCatalogClient(
        exception=agentbuilder.AgentBuilderError(
            "Starter package listing returned an invalid shape."
        )
    )

    with pytest.raises(agentbuilder.AgentBuilderError):
        mos.list_starter_packages(client, environment_id=ENVIRONMENT_ID)

    annotations = json.loads(
        capsys.readouterr()
        .out.split("DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["outcome"] == "invalid-response"
    assert "invalid shape" in annotations["error"]


def test_list_starter_packages_reports_transport_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeCatalogClient(
        exception=requests.exceptions.ReadTimeout("catalog read timed out")
    )

    with pytest.raises(requests.exceptions.ReadTimeout):
        mos.list_starter_packages(client, environment_id=ENVIRONMENT_ID)

    annotations = json.loads(
        capsys.readouterr()
        .out.split("DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["outcome"] == "transport-failure"
    assert annotations["transportErrorType"] == "ReadTimeout"


# --- ALM opt-in -----------------------------------------------------------


def test_enable_alm_preserves_full_bot_and_verifies_read_back(
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = _bot_changeset(version=1)
    after = _bot_changeset(version=2, alm_enabled=True)
    client = FakeAlmClient(
        fetch_responses=[before, after],
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

    result = mos.enable_alm(
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
    assert before["bot"]["configuration"]["settings"] == {"existing": "preserved"}
    assert result == {
        "environmentId": ENVIRONMENT_ID,
        "agentId": AGENT_ID,
        "outcome": "enabled",
        "beforeBotVersion": 1,
        "afterBotVersion": 2,
        "previousValue": None,
        "persistedValue": True,
    }

    out = capsys.readouterr().out
    annotations = json.loads(
        out.split("DA_MOS_STARTER_ALM_ANNOTATIONS_JSON:", 1)[1].splitlines()[0]
    )
    response = json.loads(
        out.split("DA_MOS_STARTER_ALM_RESPONSE_JSON:", 1)[1].splitlines()[0]
    )
    assert annotations["outcome"] == "update-accepted"
    assert annotations["requestId"] == "req-alm-42"
    assert response["unknownServiceField"] == "preserved in evidence"
    assert response["authorization"] == mos.REDACTED
    assert "leak-me-not" not in out


def test_enable_alm_is_repeatable_without_a_second_write() -> None:
    client = FakeAlmClient(
        fetch_responses=[_bot_changeset(version=2, alm_enabled=True)],
    )

    result = mos.enable_alm(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
    )

    assert result["outcome"] == "already-enabled"
    assert result["persistedValue"] is True
    assert client.fetch_calls == [AGENT_ID]
    assert client.update_calls == []


def test_enable_alm_rejects_mismatched_fetched_agent_before_write() -> None:
    before = _bot_changeset(version=1)
    before["bot"]["cdsBotId"] = "00000000-0000-4000-8000-000000006666"
    client = FakeAlmClient(fetch_responses=[before])

    with pytest.raises(mos.MosStarterSetupError, match="does not match"):
        mos.enable_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    assert client.update_calls == []


def test_enable_alm_fails_when_read_back_does_not_persist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeAlmClient(
        fetch_responses=[
            _bot_changeset(version=1),
            _bot_changeset(version=2, alm_enabled=False),
        ],
        update_response=FakeHTTPResponse(200, json_body={"accepted": True}),
    )

    with pytest.raises(mos.MosStarterSetupError, match="read-back"):
        mos.enable_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    assert len(client.update_calls) == 1
    verify = json.loads(
        capsys.readouterr()
        .out.split("DA_MOS_STARTER_ALM_VERIFY_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert verify["outcome"] == "verification-failed"
    assert verify["persistedValue"] is False


def test_enable_alm_preserves_rejection_evidence(
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

    with pytest.raises(mos.MosStarterSetupError, match="rejected"):
        mos.enable_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    out = capsys.readouterr().out
    annotations = json.loads(
        out.split("DA_MOS_STARTER_ALM_ANNOTATIONS_JSON:", 1)[1].splitlines()[0]
    )
    response = json.loads(
        out.split("DA_MOS_STARTER_ALM_RESPONSE_JSON:", 1)[1].splitlines()[0]
    )
    assert annotations["outcome"] == "rejected"
    assert annotations["httpStatus"] == 409
    assert response["error"]["message"] == "service-owned detail"


def test_enable_alm_uncertain_transport_is_safely_reconcilable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport_error = requests.exceptions.ReadTimeout("read timed out")
    client = FakeAlmClient(
        fetch_responses=[_bot_changeset(version=1)],
        update_exception=transport_error,
    )

    with pytest.raises(mos.MosStarterSetupError, match="setting outcome is uncertain"):
        mos.enable_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    annotations = json.loads(
        capsys.readouterr()
        .out.split("DA_MOS_STARTER_ALM_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["outcome"] == "uncertain-transport"
    assert annotations["transportErrorType"] == "ReadTimeout"


def test_enable_alm_preserves_verification_rejection_evidence(
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
                request_id="req-verify",
                response=verification_response,
            ),
        ],
        update_response=FakeHTTPResponse(200, json_body={"accepted": True}),
    )

    with pytest.raises(mos.MosStarterSetupError, match="Verification did not complete"):
        mos.enable_alm(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )

    out = capsys.readouterr().out
    annotations = json.loads(
        out.split("DA_MOS_STARTER_ALM_VERIFY_ANNOTATIONS_JSON:", 1)[1]
        .splitlines()[0]
    )
    response = json.loads(
        out.split("DA_MOS_STARTER_ALM_VERIFY_RESPONSE_JSON:", 1)[1]
        .splitlines()[0]
    )
    assert annotations["outcome"] == "verification-rejected"
    assert annotations["requestId"] == "req-verify"
    assert response["error"]["message"] == "verification detail"


# --- bounded command surface ---------------------------------------------


def test_build_parser_exposes_only_bounded_mos_commands() -> None:
    parser = mos.build_parser()
    subparsers_action = next(
        action
        for action in parser._subparsers._group_actions
        if isinstance(action, argparse._SubParsersAction)
    )

    assert set(subparsers_action.choices) == {"list", "create", "enable-alm"}


@pytest.mark.parametrize(
    "attribute",
    [
        "resolve_starter_package",
        "PERSONA_TERMS",
        "PERSONAS",
        "ISV_TERMS",
        "SUPPORTED_ISVS",
        "HYBRID_ISV_OWNING_SKILL",
        "load_mos_starter_state",
        "MOS_STARTER_RECORDS",
        "attach_existing_dev",
    ],
)
def test_module_has_no_resolver_status_or_product_policy_surface(
    attribute: str,
) -> None:
    assert not hasattr(mos, attribute)


def test_main_does_not_flatten_unexpected_runtime_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_unexpectedly(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("unexpected implementation failure")

    monkeypatch.setattr(mos, "resolve_da_target", fail_unexpectedly)

    with pytest.raises(RuntimeError, match="unexpected implementation failure"):
        mos.main(["list", "--environment-id", ENVIRONMENT_ID])
