# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import argparse
import base64
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import workday_assisted_browser
from workday_assisted_browser import (
    CompanionHandler,
    AssistedBrowserError,
    CompanionState,
    _Server,
    classify_layout,
    decode_shared_browser_capture,
    normalize_shared_browser_targets,
    sanitize_browser_url,
    sanitize_browser_evidence_text,
    surface_url,
    target_pointer_position,
    validate_search_control,
    validate_search_value,
    validate_reveal_control,
    validate_view,
    validate_navigation_url,
)


def _view() -> dict:
    return {
        "schemaVersion": 1,
        "phase": "Connections",
        "title": "Create the Workday connection",
        "status": "waiting",
        "summary": "Use the displayed non-secret values.",
        "steps": ["Select the authentication type.", "Choose Create."],
        "fields": [{"label": "Tenant name", "value": "example"}],
        "waitingFor": "Return after the connection shows Connected.",
    }


def test_view_contract_accepts_only_constrained_content() -> None:
    assert validate_view(_view()) == _view()

    invalid = _view() | {"html": "<button>Approve</button>"}
    with pytest.raises(AssistedBrowserError, match="unsupported fields: html"):
        validate_view(invalid)


def test_view_contract_rejects_unknown_nested_field() -> None:
    invalid = _view()
    invalid["fields"] = [
        {"label": "Tenant", "value": "example", "action": "copy"}
    ]

    with pytest.raises(AssistedBrowserError, match="unsupported fields: action"):
        validate_view(invalid)


def test_view_contract_accepts_only_named_collection_operation() -> None:
    view = _view() | {
        "action": {
            "label": "Navigate and collect",
            "operation": "entra-directory-display-name",
        }
    }

    assert validate_view(view) == (
        view
        | {
            "action": {
                **view["action"],
                "mode": "navigate-and-capture",
            }
        }
    )

    with pytest.raises(
        AssistedBrowserError,
        match="not a supported collection operation",
    ):
        validate_view(
            _view()
            | {
                "action": {
                    "label": "Navigate anywhere",
                    "operation": "arbitrary-url",
                }
            }
        )


def test_view_contract_accepts_row_confirmation_without_collection_action() -> None:
    confirmation = {
        "operation": "entra-reply-url",
        "prompt": "Is this the intended Reply URL?",
        "confirmLabel": "Confirm Reply URL",
        "rejectLabel": "Search again",
    }
    view = _view() | {"confirmation": confirmation}

    assert validate_view(view) == view

    with pytest.raises(
        AssistedBrowserError,
        match="only one interaction",
    ):
        validate_view(
            view
            | {
                "action": {
                    "label": "Navigate and collect",
                    "operation": "entra-reply-url",
                }
            }
        )


def test_view_contract_accepts_final_worksheet_confirmation_only() -> None:
    confirmation = {
        "operation": "entra-final-worksheet",
        "prompt": (
            "Do these final worksheet values accurately reflect the completed "
            "Microsoft Entra setup?"
        ),
        "confirmLabel": "Send values to ADK",
        "rejectLabel": "Review worksheet rows",
    }
    view = _view() | {
        "title": "Review final Microsoft Entra worksheet",
        "fields": [
            {"label": f"Worksheet row {index}", "value": f"Value {index}"}
            for index in range(14)
        ],
        "confirmation": confirmation,
    }

    assert validate_view(view) == view

    with pytest.raises(
        AssistedBrowserError,
        match="fields must be an array with at most 16 items",
    ):
        validate_view(
            view
            | {
                "fields": [
                    {"label": f"Worksheet row {index}", "value": f"Value {index}"}
                    for index in range(17)
                ]
            }
        )

    with pytest.raises(
        AssistedBrowserError,
        match="not a supported collection operation",
    ):
        validate_view(
            _view()
            | {
                "action": {
                    "label": "Navigate only",
                    "operation": "entra-final-worksheet",
                }
            }
        )


def test_view_contract_accepts_navigation_and_capture_choices_together() -> None:
    view = _view() | {
        "actions": [
            {
                "label": "Navigate only",
                "operation": "entra-certificate-thumbprint",
                "mode": "navigate-only",
            },
            {
                "label": "Navigate and capture",
                "operation": "entra-certificate-thumbprint",
                "mode": "navigate-and-capture",
            },
        ]
    }

    assert validate_view(view) == view


@pytest.mark.parametrize(
    ("operation", "worksheet_row"),
    [
        (
            "entra-directory-display-name",
            "Directory name",
        ),
        (
            "entra-enterprise-application-display-name",
            "Enterprise application",
        ),
        (
            "entra-application-id",
            "Application ID",
        ),
        (
            "entra-reply-url",
            "Selected Reply URL",
        ),
        (
            "entra-name-id-source",
            "NameID source",
        ),
        (
            "entra-saml-signing-option",
            "SAML signing",
        ),
        (
            "entra-certificate-thumbprint",
            "Certificate thumbprint (active certificate row)",
        ),
        (
            "entra-certificate-expiration",
            "Certificate expiration date (active certificate row)",
        ),
        (
            "entra-saml-configuration",
            "SAML configuration",
        ),
    ],
)
def test_entra_collection_operations_have_row_scoped_definitions(
    operation: str,
    worksheet_row: str,
) -> None:
    definition = workday_assisted_browser._COLLECTION_OPERATION_DEFINITIONS[
        operation
    ]

    assert definition["worksheetRow"] == worksheet_row
    assert definition["worksheetField"]


def test_browser_url_redacts_query_and_fragment_secrets() -> None:
    assert sanitize_browser_url(
        "http://127.0.0.1:43127/#token=secret"
    ) == "http://127.0.0.1:43127/"
    assert sanitize_browser_url(
        "https://login.example/callback?code=secret&state=x"
    ) == "https://login.example/callback"


def test_browser_evidence_redacts_unrelated_account_context() -> None:
    assert (
        sanitize_browser_evidence_text(
            "Account menu Currently signed in as user@example.com"
        )
        == "[REDACTED_ACCOUNT_CONTEXT]"
    )
    assert (
        sanitize_browser_evidence_text("Owner user@example.com")
        == "Owner [REDACTED_EMAIL]"
    )


def test_search_fill_accepts_only_nonsecret_search_controls_and_values() -> None:
    validate_search_control(
        {
            "tag": "input",
            "type": "search",
            "role": "searchbox",
            "ariaLabel": "Search box",
        }
    )
    assert validate_search_value("Workday") == "Workday"

    with pytest.raises(AssistedBrowserError, match="search or filter"):
        validate_search_control(
            {
                "tag": "input",
                "type": "text",
                "ariaLabel": "Application name",
            }
        )
    assert (
        validate_search_value("access token=search phrase")
        == "access token=search phrase"
    )


def test_target_pointer_maps_application_position_into_vertical_rail() -> None:
    centered = target_pointer_position(
        {"y": 350, "height": 100},
        800,
    )
    approximate = target_pointer_position(
        {"y": 10, "height": 40},
        800,
    )

    assert centered == {
        "positionRatio": 0.5,
        "centered": True,
    }
    assert approximate == {
        "positionRatio": 0.05,
        "centered": False,
    }


def test_reveal_requires_edit_control_named_by_row_instructions() -> None:
    assert (
        validate_reveal_control(
            "entra-saml-configuration",
            {
                "tag": "div",
                "role": "button",
                "ariaLabel": "Edit basic SAML configuration",
            },
        )
        == "Edit basic SAML configuration"
    )

    assert (
        validate_reveal_control(
            "entra-saml-configuration",
            {
                "tag": "div",
                "role": "button",
                "ariaLabel": "Edit SAML signing certificate",
            },
        )
        == "Edit SAML signing certificate"
    )
    with pytest.raises(AssistedBrowserError, match="Edit button"):
        validate_reveal_control(
            "entra-saml-configuration",
            {
                "tag": "a",
                "role": "link",
                "ariaLabel": "Edit basic SAML configuration",
            },
        )


def test_authorized_navigation_accepts_https_links() -> None:
    assert (
        validate_navigation_url(
            "https://entra.microsoft.com/",
            "/#view/Microsoft_AAD_IAM/ApplicationsListBlade",
        )
        == "https://entra.microsoft.com/"
        "#view/Microsoft_AAD_IAM/ApplicationsListBlade"
    )
    assert (
        validate_navigation_url(
            "https://entra.microsoft.com/",
            "https://example.com/",
        )
        == "https://example.com/"
    )
    with pytest.raises(AssistedBrowserError, match="HTTPS destination"):
        validate_navigation_url(
            "https://entra.microsoft.com/",
            "http://example.com/",
        )


def test_entra_surface_opens_bounded_admin_center_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workday_assisted_browser,
        "_active_scope",
        lambda _root: (
            {
                "environmentId": "00000000-0000-0000-0000-000000000001",
                "entraTenantId": "00000000-0000-0000-0000-000000000003",
                "ring": "test",
            },
            {"botId": "00000000-0000-0000-0000-000000000002"},
        ),
    )

    assert (
        surface_url(Path("unused"), "entra-configuration")
        == "https://entra.microsoft.com/"
    )


def test_entra_surface_requires_authoritative_tenant_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workday_assisted_browser,
        "_active_scope",
        lambda _root: (
            {"environmentId": "not-used", "ring": "test"},
            {"botId": "not-used"},
        ),
    )

    with pytest.raises(
        AssistedBrowserError,
        match="Recorded Microsoft Entra tenant ID must be text",
    ):
        surface_url(Path("unused"), "entra-configuration")


def test_vscode_session_metadata_does_not_require_cdp(
    tmp_path: Path,
) -> None:
    session_path = workday_assisted_browser._session_path(tmp_path)
    workday_assisted_browser._write_json(
        session_path,
        {
            "schemaVersion": 1,
            "port": 54321,
            "token": "test-token",
            "pid": 1234,
            "browserMode": "vscode",
        },
    )

    session = workday_assisted_browser._load_session(tmp_path)

    assert session["browserMode"] == "vscode"
    assert "cdpEndpoint" not in session


def test_vscode_start_returns_manual_shared_browser_handoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    written = []
    monkeypatch.setattr(
        workday_assisted_browser,
        "surface_url",
        lambda _root, _surface: "https://entra.microsoft.com/",
    )
    monkeypatch.setattr(
        workday_assisted_browser,
        "_start_server",
        lambda _root, endpoint, mode: (
            {
                "schemaVersion": 1,
                "port": 54321,
                "token": "test-token",
                "pid": 1234,
                "browserMode": mode,
            },
            True,
        ),
    )
    monkeypatch.setattr(
        workday_assisted_browser,
        "_write_json",
        lambda path, value: written.append((path, dict(value))),
    )
    args = argparse.Namespace(
        surface="entra-configuration",
        vscode=True,
        launch=False,
        attach_existing=False,
        cdp=workday_assisted_browser.DEFAULT_CDP,
    )

    result = workday_assisted_browser._start(args, tmp_path)

    assert result == {
        "started": True,
        "serverStarted": True,
        "browserLaunched": False,
        "surface": "entra-configuration",
        "browserMode": "vscode",
        "applicationUrl": "https://entra.microsoft.com/",
        "manualBrowserRequired": True,
        "shareWithAgentRequired": True,
    }
    assert written[-1][1]["browserMode"] == "vscode"
    assert written[-1][1]["applicationUrl"] == "https://entra.microsoft.com/"
    assert "cdpEndpoint" not in written[-1][1]


def test_vscode_collection_authorizes_shared_browser_without_cdp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workday_assisted_browser,
        "_load_session",
        lambda _root: {"browserMode": "vscode"},
    )
    monkeypatch.setattr(
        workday_assisted_browser,
        "_navigate_application",
        lambda *_args, **_kwargs: pytest.fail(
            "VS Code mode must not navigate through CDP"
        ),
    )

    result = workday_assisted_browser._authorize_collection_operation(
        Path("unused"),
        "entra-directory-display-name",
        mode="navigate-and-capture",
    )

    assert result["status"] == "authorized"
    assert result["sharedBrowserRequired"] is True
    assert result["targetUrl"].startswith("https://entra.microsoft.com/")


def test_shared_browser_targets_preserve_companion_pointer_contract() -> None:
    assert normalize_shared_browser_targets(
        [
            {
                "label": "EmployeeHub",
                "positionRatio": 0.5,
                "centered": True,
            }
        ]
    ) == [
        {
            "label": "EmployeeHub",
            "positionRatio": 0.5,
            "centered": True,
        }
    ]

    distributed = normalize_shared_browser_targets(
        [{"label": "First"}, {"label": "Second"}]
    )
    assert [target["positionRatio"] for target in distributed] == [
        0.3333,
        0.6667,
    ]
    assert all(target["centered"] is False for target in distributed)


def test_shared_browser_capture_requires_bounded_png() -> None:
    content = b"\x89PNG\r\n\x1a\nbounded"
    assert (
        decode_shared_browser_capture(base64.b64encode(content).decode("ascii"))
        == content
    )

    with pytest.raises(AssistedBrowserError, match="must be a PNG"):
        decode_shared_browser_capture(base64.b64encode(b"not-an-image").decode("ascii"))


def test_vscode_capture_uses_shared_browser_image_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content = b"\x89PNG\r\n\x1a\nbounded"
    image = tmp_path / "target.png"
    image.write_bytes(content)
    monkeypatch.setattr(
        workday_assisted_browser,
        "_load_session",
        lambda _root: {"browserMode": "vscode"},
    )
    requested = {}

    def fake_request(
        _session: dict,
        path: str,
        *,
        value: dict,
        timeout: float,
    ) -> dict:
        requested.update(
            {
                "path": path,
                "value": value,
                "timeout": timeout,
            }
        )
        return {"evidenceImage": {"label": value["label"]}}

    monkeypatch.setattr(
        workday_assisted_browser,
        "_api_request",
        fake_request,
    )
    result = workday_assisted_browser._capture(
        argparse.Namespace(
            operation="entra-directory-display-name",
            selector=None,
            frame_index=None,
            match_index=None,
            image_file=image,
            label="Directory name",
        ),
        tmp_path,
    )

    assert result == {"evidenceImage": {"label": "Directory name"}}
    assert requested["path"] == "/api/capture"
    assert base64.b64decode(requested["value"]["imageBase64"]) == content


def test_shared_browser_completion_unlocks_manual_entry() -> None:
    state = CompanionState()
    action_view = _view() | {
        "action": {
            "label": "Navigate",
            "operation": "entra-application-id",
            "mode": "navigate-only",
        }
    }
    published = state.publish(action_view)
    state.begin_collection(
        revision=published["revision"],
        operation="entra-application-id",
        mode="navigate-only",
    )
    state.complete_collection(
        {
            "operation": "entra-application-id",
            "mode": "navigate-only",
            "status": "authorized",
            "authorizedAt": workday_assisted_browser._now_iso(),
        }
    )

    completed = state.complete_shared_browser_operation(
        operation="entra-application-id",
        status="navigated",
    )
    entry = state.publish(
        _view()
        | {
            "entry": {
                "operation": "entra-application-id",
                "label": "Application ID",
                "placeholder": "00000000-0000-0000-0000-000000000000",
                "submitLabel": "Use this value",
            }
        }
    )

    assert completed["status"] == "navigated"
    assert entry["revision"] == published["revision"] + 1


def test_shared_browser_completion_rejects_unmatched_operation() -> None:
    state = CompanionState()

    with pytest.raises(
        AssistedBrowserError,
        match="does not match an authorized worksheet operation",
    ):
        state.complete_shared_browser_operation(
            operation="entra-application-id",
            status="navigated",
        )


def test_vscode_session_rejects_cdp_only_operations() -> None:
    with pytest.raises(
        AssistedBrowserError,
        match="VS Code Integrated Browser",
    ):
        workday_assisted_browser._require_edge_browser(
            {"browserMode": "vscode"}
        )


def test_close_owned_browser_terminates_exact_pid_and_verifies_cdp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed = []
    monkeypatch.setattr(
        workday_assisted_browser.os,
        "kill",
        lambda pid, sig: killed.append((pid, sig)),
    )
    monkeypatch.setattr(
        workday_assisted_browser,
        "is_cdp_up",
        lambda _endpoint: False,
    )

    closed = workday_assisted_browser._close_owned_browser(
        {"browserPid": 1234, "cdpEndpoint": "http://localhost:9237"}
    )

    assert closed is True
    assert killed == [(1234, workday_assisted_browser.signal.SIGTERM)]


def test_stale_render_event_cannot_acknowledge_latest_revision() -> None:
    state = CompanionState()
    first = state.publish(_view())
    second = state.publish(_view() | {"title": "Next step"})

    state.event(
        {
            "type": "rendered",
            "revision": first["revision"],
            "visible": True,
        }
    )
    status = state.status()

    assert status["revision"] == second["revision"]
    assert status["renderedRevision"] is None


def test_fetch_and_current_render_are_reported_separately() -> None:
    state = CompanionState()
    published = state.publish(_view())

    fetched = state.fetch()
    state.event(
        {
            "type": "rendered",
            "revision": published["revision"],
            "visible": True,
        }
    )
    status = state.status()

    assert fetched["revision"] == published["revision"]
    assert status["fetchedRevision"] == published["revision"]
    assert status["renderedRevision"] == published["revision"]
    assert status["visible"] is True
    assert status["connected"] is True


def test_collection_requires_current_view_authorization() -> None:
    state = CompanionState()
    published = state.publish(
        _view()
        | {
            "action": {
                "label": "Navigate and collect",
                "operation": "entra-directory-display-name",
            }
        }
    )

    state.begin_collection(
        revision=published["revision"],
        operation="entra-directory-display-name",
    )
    result = state.complete_collection(
        {
            "operation": "entra-directory-display-name",
            "status": "authorized",
            "worksheetRow": "Directory name",
        }
    )

    assert result["status"] == "authorized"
    assert state.status()["collection"] == result
    assert (
        state.require_authorized_collection(
            "entra-directory-display-name"
        )
        == result
    )
    with pytest.raises(AssistedBrowserError, match="does not match"):
        state.begin_collection(
            revision=published["revision"] - 1,
            operation="entra-directory-display-name",
        )


def test_playwright_reads_remain_available_after_inspection_error() -> None:
    state = CompanionState()
    published = state.publish(
        _view()
        | {
            "action": {
                "label": "Navigate and collect",
                "operation": "entra-directory-display-name",
            }
        }
    )
    state.begin_collection(
        revision=published["revision"],
        operation="entra-directory-display-name",
    )
    state.complete_collection(
        {
            "operation": "entra-directory-display-name",
            "status": "authorized",
        }
    )

    first = state.require_authorized_collection(
        "entra-directory-display-name"
    )
    second = state.require_authorized_collection(
        "entra-directory-display-name"
    )

    assert first == second


def test_search_navigation_is_available_in_either_assistance_mode() -> None:
    for mode, status in (
        ("navigate-only", "navigated"),
        ("navigate-and-capture", "authorized"),
    ):
        state = CompanionState()
        revision = state.publish(
            _view()
            | {
                "action": {
                    "label": mode,
                    "operation": "entra-certificate-thumbprint",
                    "mode": mode,
                }
            }
        )["revision"]
        state.begin_collection(
            revision=revision,
            operation="entra-certificate-thumbprint",
            mode=mode,
        )
        result = {
            "operation": "entra-certificate-thumbprint",
            "mode": mode,
            "status": status,
        }
        state.complete_collection(result)

        assert (
            state.require_navigation_collection(
                "entra-certificate-thumbprint"
            )
            == result
        )
        state.set_evidence_image(
            operation="entra-certificate-thumbprint",
            content=b"png",
            metadata={"label": "Search box"},
        )
        pointer = state.set_target_pointer(
            operation="entra-certificate-thumbprint",
            metadata={
                "label": "Search box",
                "positionRatio": 0.5,
                "centered": True,
            },
        )
        assert state.status()["targetPointer"] == pointer
        second_pointer = state.set_target_pointer(
            operation="entra-certificate-thumbprint",
            metadata={
                "label": "Second result",
                "positionRatio": 0.7,
                "centered": False,
            },
            append=True,
        )
        assert state.status()["targetPointers"] == [pointer, second_pointer]
        assert state.status()["targetPointer"] == second_pointer
        grouped = state.set_target_pointers(
            operation="entra-certificate-thumbprint",
            metadata=[
                {
                    "label": "First value",
                    "positionRatio": 0.3,
                    "centered": False,
                },
                {
                    "label": "Second value",
                    "positionRatio": 0.7,
                    "centered": False,
                },
            ],
        )
        assert state.status()["targetPointers"] == grouped
        assert [pointer["label"] for pointer in grouped] == [
            "First value",
            "Second value",
        ]
        state.clear_target_pointer(operation="entra-certificate-thumbprint")
        assert state.status()["targetPointer"] is None
        assert state.status()["targetPointers"] == []


@pytest.mark.parametrize(
    ("operation", "worksheet_row", "worksheet_field"),
    [
        (
            "entra-signing-certificate-check",
            "Signing certificate",
            "entraChecks.signingCertificate",
        ),
        (
            "entra-authorized-connector",
            "Authorized connector",
            "entraChecks.connectorPreauthorized",
        ),
        (
            "entra-permissions-consent",
            "Permissions and consent",
            "entraChecks.graphDelegatedPermissions,entraChecks.adminConsent",
        ),
        (
            "entra-employee-assignment",
            "Employee assignment",
            "entraChecks.userAssignment",
        ),
        (
            "entra-existing-configuration",
            "Existing configuration",
            (
                "entraChecks.existingScopesPreserved,"
                "entraChecks.authorizedClientsPreserved,"
                "entraChecks.permissionsPreserved"
            ),
        ),
    ],
)
def test_remaining_entra_check_operations_are_row_scoped(
    operation: str,
    worksheet_row: str,
    worksheet_field: str,
) -> None:
    state = CompanionState()
    revision = state.publish(
        _view()
        | {
            "action": {
                "label": "Navigate only",
                "operation": operation,
                "mode": "navigate-only",
            }
        }
    )["revision"]

    state.begin_collection(
        revision=revision,
        operation=operation,
        mode="navigate-only",
    )
    collection = state.complete_collection(
        {
            "operation": operation,
            "mode": "navigate-only",
            "status": "navigated",
            "worksheetRow": worksheet_row,
            "worksheetField": worksheet_field,
        }
    )

    assert collection["worksheetRow"] == worksheet_row
    assert collection["worksheetField"] == worksheet_field


def test_reveal_requires_row_specific_companion_disclaimer() -> None:
    state = CompanionState()
    revision = state.publish(
        _view()
        | {
            "action": {
                "label": "Navigate only",
                "operation": "entra-saml-configuration",
                "mode": "navigate-only",
                "disclaimer": (
                    "Navigation includes clicking Edit basic SAML "
                    "configuration only to display the SAML values."
                ),
            }
        }
    )["revision"]
    state.begin_collection(
        revision=revision,
        operation="entra-saml-configuration",
        mode="navigate-only",
    )
    state.complete_collection(
        {
            "operation": "entra-saml-configuration",
            "mode": "navigate-only",
            "status": "navigated",
        }
    )

    state.require_reveal_disclaimer(
        "entra-saml-configuration",
        "Edit basic SAML configuration",
    )

    state.publish(
        _view()
        | {
            "action": {
                "label": "Navigate only",
                "operation": "entra-saml-configuration",
                "mode": "navigate-only",
            }
        }
    )
    with pytest.raises(AssistedBrowserError, match="must disclose"):
        state.require_reveal_disclaimer(
            "entra-saml-configuration",
            "Edit basic SAML configuration",
        )


def test_reveal_accepts_dynamic_edit_control_named_by_disclaimer() -> None:
    state = CompanionState()
    revision = state.publish(
        _view()
        | {
            "action": {
                "label": "Navigate only",
                "operation": "entra-saml-configuration",
                "mode": "navigate-only",
                "disclaimer": (
                    "Navigation includes clicking Edit advanced display values "
                    "only to reveal the values for manual comparison."
                ),
            }
        }
    )["revision"]
    state.begin_collection(
        revision=revision,
        operation="entra-saml-configuration",
        mode="navigate-only",
    )
    state.complete_collection(
        {
            "operation": "entra-saml-configuration",
            "mode": "navigate-only",
            "status": "navigated",
        }
    )

    control_label = validate_reveal_control(
        "entra-saml-configuration",
        {
            "tag": "button",
            "role": "button",
            "text": "Edit advanced display values",
        },
    )
    state.require_reveal_disclaimer(
        "entra-saml-configuration",
        control_label,
    )


def test_confirmation_preserves_row_authorization_after_rejection() -> None:
    state = CompanionState()
    action_view = _view() | {
        "action": {
            "label": "Navigate and collect",
            "operation": "entra-reply-url",
        }
    }
    action_revision = state.publish(action_view)["revision"]
    state.begin_collection(
        revision=action_revision,
        operation="entra-reply-url",
    )
    authorization = state.complete_collection(
        {
            "operation": "entra-reply-url",
            "status": "authorized",
        }
    )
    confirmation_view = _view() | {
        "confirmation": {
            "operation": "entra-reply-url",
            "prompt": "Is this the intended Reply URL?",
            "confirmLabel": "Confirm Reply URL",
            "rejectLabel": "Search again",
        }
    }
    confirmation_revision = state.publish(confirmation_view)["revision"]

    result = state.decide_confirmation(
        revision=confirmation_revision,
        operation="entra-reply-url",
        decision="rejected",
    )

    assert result["status"] == "rejected"
    assert state.require_authorized_collection("entra-reply-url") == authorization
    assert state.status()["confirmation"] == result


def test_confirmation_rejects_stale_revision() -> None:
    state = CompanionState()
    confirmation_view = _view() | {
        "confirmation": {
            "operation": "entra-reply-url",
            "prompt": "Is this the intended Reply URL?",
            "confirmLabel": "Confirm Reply URL",
            "rejectLabel": "Search again",
        }
    }
    first = state.publish(confirmation_view)
    state.publish(confirmation_view | {"title": "New candidate"})

    with pytest.raises(AssistedBrowserError, match="current guidance"):
        state.decide_confirmation(
            revision=first["revision"],
            operation="entra-reply-url",
            decision="confirmed",
        )


def test_context_screenshot_is_row_scoped_and_preserved_for_same_operation() -> None:
    state = CompanionState()
    action_view = _view() | {
        "action": {
            "label": "Navigate and collect",
            "operation": "entra-saml-signing-option",
        }
    }
    revision = state.publish(action_view)["revision"]
    state.begin_collection(
        revision=revision,
        operation="entra-saml-signing-option",
    )
    state.complete_collection(
        {
            "operation": "entra-saml-signing-option",
            "status": "authorized",
        }
    )

    metadata = state.set_evidence_image(
        operation="entra-saml-signing-option",
        content=b"png",
        metadata={
            "label": "Edit SAML signing certificate",
            "capturedAt": "2026-01-01T00:00:00Z",
        },
    )
    state.publish(action_view | {"title": "Open the certificate settings"})

    assert metadata["operation"] == "entra-saml-signing-option"
    assert state.fetch()["evidenceImage"] == metadata
    assert state.evidence_image() == b"png"

    state.publish(
        _view()
        | {
            "action": {
                "label": "Navigate and collect",
                "operation": "entra-reply-url",
            }
        }
    )
    with pytest.raises(AssistedBrowserError, match="No contextual screenshot"):
        state.evidence_image()


def test_manual_entry_requires_prior_navigation_authorization() -> None:
    state = CompanionState()
    entry_view = _view() | {
        "entry": {
            "operation": "entra-certificate-thumbprint",
            "label": "Certificate thumbprint",
            "placeholder": "Paste the displayed thumbprint",
            "submitLabel": "Submit worksheet value",
        }
    }

    with pytest.raises(AssistedBrowserError, match="only after Navigate only"):
        state.publish(entry_view)

    action_view = _view() | {
        "action": {
            "label": "Navigate only",
            "operation": "entra-certificate-thumbprint",
            "mode": "navigate-only",
        }
    }
    revision = state.publish(action_view)["revision"]
    state.begin_collection(
        revision=revision,
        operation="entra-certificate-thumbprint",
        mode="navigate-only",
    )
    state.complete_collection(
        {
            "operation": "entra-certificate-thumbprint",
            "mode": "navigate-only",
            "status": "navigated",
        }
    )
    entry_revision = state.publish(entry_view)["revision"]

    result = state.submit_entry(
        revision=entry_revision,
        operation="entra-certificate-thumbprint",
        value="AA:11:BB:22",
    )

    assert result["status"] == "submitted"
    assert result["value"] == "AA:11:BB:22"


def test_manual_entry_rejects_secret_like_value() -> None:
    state = CompanionState()
    action_view = _view() | {
        "action": {
            "label": "Navigate only",
            "operation": "entra-certificate-thumbprint",
            "mode": "navigate-only",
        }
    }
    revision = state.publish(action_view)["revision"]
    state.begin_collection(
        revision=revision,
        operation="entra-certificate-thumbprint",
        mode="navigate-only",
    )
    state.complete_collection(
        {
            "operation": "entra-certificate-thumbprint",
            "mode": "navigate-only",
            "status": "navigated",
        }
    )
    entry_revision = state.publish(
        _view()
        | {
            "entry": {
                "operation": "entra-certificate-thumbprint",
                "label": "Certificate thumbprint",
                "placeholder": "Paste the displayed thumbprint",
                "submitLabel": "Submit worksheet value",
            }
        }
    )["revision"]

    assert state.submit_entry(
        revision=entry_revision,
        operation="entra-certificate-thumbprint",
        value="client secret = worksheet text",
    )["status"] == "submitted"


def test_loopback_api_requires_bearer_and_tracks_render() -> None:
    server = _Server(("127.0.0.1", 0), CompanionHandler)
    assert isinstance(server, ThreadingHTTPServer)
    server.token = "test-token"
    server.companion_state = CompanionState()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        try:
            urlopen(f"{origin}/api/status", timeout=2)
        except HTTPError as unauthorized:
            assert unauthorized.code == 401
            unauthorized.close()
        else:
            pytest.fail("Unauthenticated status request unexpectedly succeeded.")

        headers = {
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
        }
        request = Request(
            f"{origin}/api/present",
            data=json.dumps(_view()).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            revision = json.loads(response.read())["revision"]

        fetch = Request(f"{origin}/api/view", headers=headers)
        with urlopen(fetch, timeout=2) as response:
            assert json.loads(response.read())["revision"] == revision

        event = Request(
            f"{origin}/api/event",
            data=json.dumps(
                {
                    "type": "rendered",
                    "revision": revision,
                    "visible": True,
                }
            ).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(event, timeout=2):
            pass

        status = Request(f"{origin}/api/status", headers=headers)
        with urlopen(status, timeout=2) as response:
            payload = json.loads(response.read())
        assert payload["renderedRevision"] == revision
        assert payload["visible"] is True
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_vscode_loopback_accepts_shared_target_and_capture_evidence(
    tmp_path: Path,
) -> None:
    server = _Server(("127.0.0.1", 0), CompanionHandler)
    server.token = "test-token"
    server.root = tmp_path
    server.browser_mode = "vscode"
    server.cdp_endpoint = ""
    server.companion_state = CompanionState()
    view = _view() | {
        "action": {
            "label": "Navigate and capture",
            "operation": "entra-directory-display-name",
            "mode": "navigate-and-capture",
        }
    }
    revision = server.companion_state.publish(view)["revision"]
    server.companion_state.begin_collection(
        revision=revision,
        operation="entra-directory-display-name",
        mode="navigate-and-capture",
    )
    server.companion_state.complete_collection(
        {
            "operation": "entra-directory-display-name",
            "mode": "navigate-and-capture",
            "status": "authorized",
            "authorizedAt": workday_assisted_browser._now_iso(),
        }
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    headers = {
        "Authorization": "******",
        "Content-Type": "application/json",
    }
    headers["Authorization"] = "Bearer " + server.token
    try:
        point_request = Request(
            f"{origin}/api/point-targets",
            data=json.dumps(
                {
                    "operation": "entra-directory-display-name",
                    "targets": [
                        {
                            "label": "EmployeeHub",
                            "positionRatio": 0.5,
                            "centered": True,
                        }
                    ],
                }
            ).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(point_request, timeout=2) as response:
            pointers = json.loads(response.read())["targetPointers"]
        assert pointers[0]["label"] == "EmployeeHub"

        content = b"\x89PNG\r\n\x1a\nbounded"
        capture_request = Request(
            f"{origin}/api/capture",
            data=json.dumps(
                {
                    "operation": "entra-directory-display-name",
                    "imageBase64": base64.b64encode(content).decode("ascii"),
                    "label": "EmployeeHub",
                }
            ).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(capture_request, timeout=2) as response:
            metadata = json.loads(response.read())["evidenceImage"]
        assert metadata["label"] == "EmployeeHub"

        status_request = Request(f"{origin}/api/status", headers=headers)
        with urlopen(status_request, timeout=2) as response:
            status = json.loads(response.read())
        assert status["targetPointers"][0]["label"] == "EmployeeHub"
        assert status["evidenceImage"]["label"] == "EmployeeHub"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_wait_matches_only_current_published_collection() -> None:
    status = {
        "revision": 4,
        "publishedAt": "2026-10-13T18:00:00+00:00",
        "collection": {
            "operation": "entra-employee-assignment",
            "status": "navigated",
            "authorizedAt": "2026-10-13T18:00:01+00:00",
        },
    }

    assert workday_assisted_browser._interaction_completed_after_publication(
        status,
        operation="entra-employee-assignment",
        interaction="collection",
        revision=4,
    ) == status["collection"]

    status["collection"]["authorizedAt"] = "2026-10-13T17:59:59+00:00"
    assert (
        workday_assisted_browser._interaction_completed_after_publication(
            status,
            operation="entra-employee-assignment",
            interaction="collection",
            revision=4,
        )
        is None
    )


def test_wait_matches_terminal_confirmation_for_revision() -> None:
    status = {
        "revision": 7,
        "publishedAt": "2026-10-13T18:00:00+00:00",
        "confirmation": {
            "operation": "entra-employee-assignment",
            "status": "confirmed",
            "revision": 7,
        },
    }

    assert workday_assisted_browser._interaction_completed_after_publication(
        status,
        operation="entra-employee-assignment",
        interaction="confirmation",
        revision=7,
    ) == status["confirmation"]

    status["confirmation"]["status"] = "waiting"
    assert (
        workday_assisted_browser._interaction_completed_after_publication(
            status,
            operation="entra-employee-assignment",
            interaction="confirmation",
            revision=7,
        )
        is None
    )


def test_layout_requires_same_visible_window_and_split_sizing() -> None:
    application = {
        "windowId": 10,
        "visibility": "visible",
        "innerWidth": 740,
        "windowWidth": 1500,
    }
    companion = {
        "windowId": 10,
        "visibility": "visible",
        "innerWidth": 740,
        "windowWidth": 1500,
    }

    assert classify_layout(application, companion) == {
        "sameWindow": True,
        "bothVisible": True,
        "splitScreenReady": True,
        "reason": "paired",
    }


def test_layout_rejects_tabs_that_share_window_but_are_not_both_visible() -> None:
    application = {
        "windowId": 10,
        "visibility": "hidden",
        "innerWidth": 1500,
        "windowWidth": 1500,
    }
    companion = {
        "windowId": 10,
        "visibility": "visible",
        "innerWidth": 1500,
        "windowWidth": 1500,
    }

    result = classify_layout(application, companion)

    assert result["sameWindow"] is True
    assert result["bothVisible"] is False
    assert result["splitScreenReady"] is False
    assert result["reason"] == "one-pane-not-visible"
