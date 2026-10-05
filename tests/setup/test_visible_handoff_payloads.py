# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _ROOT / "solutions" / "ess-maker-skills"
_CONNECT = _SOLUTION / "src" / "skills" / "connect"
_ACTIONS = _CONNECT / "servicenow-da-hrsd" / "actions"
_MARKER = re.compile(
    r"<!-- visible-handoff-question:v1(?:-[a-z-]+)? -->\s*"
    r"```json\s*(.*?)\s*```",
    re.DOTALL,
)
_ALLOWED_QUESTION_KEYS = {
    "header",
    "question",
    "options",
    "allowFreeformInput",
}
_ALLOWED_OPTION_KEYS = {"label", "recommended"}


def _payloads(path: Path) -> list[list[dict]]:
    text = path.read_text(encoding="utf-8")
    matches = _MARKER.findall(text)
    assert matches, f"{path} has no visible handoff question payload"
    return [json.loads(match) for match in matches]


def _validate_payload(
    payload: object,
    *,
    required_phrases: tuple[str, ...],
    minimum_length: int = 100,
    rendered: bool = False,
) -> dict:
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("visible handoff payload must contain one question")
    question = payload[0]
    if not isinstance(question, dict) or not set(question) <= _ALLOWED_QUESTION_KEYS:
        raise ValueError("visible handoff uses unsupported question fields")
    if not isinstance(question.get("header"), str) or not question["header"]:
        raise ValueError("visible handoff header is required")
    body = question.get("question")
    if not isinstance(body, str) or len(body) < minimum_length:
        raise ValueError("visible handoff question is missing complete instructions")
    for phrase in required_phrases:
        if phrase not in body:
            raise ValueError(f"visible handoff question omits {phrase}")
    if rendered and re.search(r"\{[^{}\n]+\}", body):
        raise ValueError("visible handoff question has unresolved placeholders")
    options = question.get("options")
    if options is not None:
        if not isinstance(options, list) or len(options) < 2:
            raise ValueError("visible handoff options are incomplete")
        for option in options:
            if (
                not isinstance(option, dict)
                or not set(option) <= _ALLOWED_OPTION_KEYS
                or not isinstance(option.get("label"), str)
                or not option["label"]
            ):
                raise ValueError("visible handoff option shape is invalid")
    if question.get("allowFreeformInput") not in {True, False, None}:
        raise ValueError("visible handoff freeform setting is invalid")
    return question


@pytest.mark.parametrize(
    ("path", "required_phrases"),
    [
        (
            _CONNECT / "shared" / "lifecycle-runner.md",
            (
                "Here's what I'll do",
                "numbered list of every phase label",
                "Access needed:",
                "Ready to start?",
            ),
        ),
        (
            _ACTIONS / "admin-preflight.md",
            (
                "Purpose:",
                "Owner:",
                "Current discovery:",
                "public ServiceNow HTTPS instance URL",
            ),
        ),
        (
            _ACTIONS / "verify-plugin-prerequisites.md",
            (
                "Purpose:",
                "Owner:",
                "{HR_CORE_PLUGIN_URL}",
                "Plugin ID: `com.sn_hr_core`",
                "Scope: `sn_hr_core`",
            ),
        ),
        (
            _ACTIONS / "guide-servicenow-oidc.md",
            (
                "Purpose:",
                "Owner:",
                "{SERVICENOW_INSTANCE_URL}",
                "Complete or re-verify all seven operations:",
                "1. Elevate to `security_admin`",
                "2. Open All -> System OAuth",
                "3. Select `Configure an OIDC provider",
                "4. Create or reuse `Microsoft Entra ID - ESS Copilot`",
                "metadata URL is already used",
                "do not assume a universal one-provider limit",
                "Do not duplicate the same metadata",
                "STOP, choose Not yet, and do not attest Completed",
                "5. Set metadata URL",
                "6. Set the verified User Claim/User Field mapping",
                "7. Confirm one real signed-in test user",
                "Have you completed or re-verified",
            ),
        ),
        (
            _ACTIONS / "prepare-topics.md",
            (
                "Purpose:",
                "Owner:",
                "Current topic inventory:",
                "Inactive HRSD topics:",
                "Enable all inactive",
            ),
        ),
        (
            _ACTIONS / "connect-agent.md",
            (
                "Purpose:",
                "Owner:",
                "{COPILOT_STUDIO_AGENT_URL}",
                "1. Open Settings -> Connection settings",
                "5. Save and confirm",
                "Does the ServiceNow row currently show Connected",
            ),
        ),
        (
            _ACTIONS / "test-connection.md",
            (
                "Purpose:",
                "Owner:",
                "1. Save the current authored draft",
                "3. Run exactly: **List my open HR cases**",
                "Pass only if",
                "What happened?",
            ),
        ),
        (
            _SOLUTION / "src" / "skills" / "setup" / "shared" / "permission-gate.md",
            (
                "requires the **{REQUIRED_ROLE}** role",
                "can't verify that automatically",
                "Do you have the {REQUIRED_ROLE} role",
            ),
        ),
        (
            _SOLUTION / "src" / "skills" / "setup" / "shared" / "checklist-updater.md",
            (
                "Status: {CHECKPOINT_RESULT}",
                "Result: {checkpoint result}",
                "Required action: {remediation and U.0a manual steps}",
                "Have you completed this step",
            ),
        ),
    ],
)
def test_visible_handoff_payloads_are_supported_and_complete(
    path: Path,
    required_phrases: tuple[str, ...],
) -> None:
    for payload in _payloads(path):
        question = _validate_payload(
            payload,
            required_phrases=required_phrases,
        )
        if path.parent == _ACTIONS:
            assert "{CURRENT_PROGRESS}" in question["question"]
        assert "above" not in question["question"].casefold()


def test_publish_has_complete_reconcile_and_publish_payloads() -> None:
    payloads = _payloads(_ACTIONS / "publish-agent.md")
    assert len(payloads) == 2
    reconcile = _validate_payload(
        payloads[0],
        required_phrases=(
            "Purpose:",
            "Owner:",
            "{COMPONENT_HASH}",
            "{SERVER_LAST_PUBLISHED_AT}",
            "never publishes or unpublishes",
            "still show Published",
        ),
    )
    publish = _validate_payload(
        payloads[1],
        required_phrases=(
            "Purpose:",
            "Owner:",
            "{DRAFT_SEMANTIC_HASH}",
            "{CONNECTION_ID}",
            "needs_remediation",
            "Publish this exact tested revision now?",
        ),
    )
    assert "{CURRENT_PROGRESS}" in reconcile["question"]
    assert "{CURRENT_PROGRESS}" in publish["question"]


def test_entra_has_complete_runbook_and_visible_guid_clarification() -> None:
    payloads = _payloads(_ACTIONS / "guide-entra-registration.md")
    assert len(payloads) == 2
    initial = _validate_payload(
        payloads[0],
        required_phrases=(
            "Purpose:",
            "Owner:",
            "https://entra.microsoft.com/",
            "Complete or re-verify all six operations:",
            "1. In App registrations",
            "2. In Token configuration",
            "3. In Expose an API",
            "4. In Authorized client applications",
            "5. In API permissions",
            "6. Grant tenant-wide admin consent",
            "What is the completed or reused Application (client) ID?",
        ),
    )
    clarification = _validate_payload(
        payloads[1],
        required_phrases=(
            "selected reuse/completion",
            "did not include",
            "non-secret client ID GUID",
            "six verified Entra settings",
            "What is the existing Application (client) ID?",
        ),
    )
    assert "{CURRENT_PROGRESS}" in initial["question"]
    assert "{CURRENT_PROGRESS}" not in clarification["question"]
    assert clarification["allowFreeformInput"] is True
    source = (
        _ACTIONS / "guide-entra-registration.md"
    ).read_text(encoding="utf-8")
    assert "do not tell them to restart `/connect`" in source
    assert "does not infer Entra configuration from the physical connection" in source


def test_credential_has_completed_question_and_bounded_candidate_selector() -> None:
    payloads = _payloads(_ACTIONS / "prepare-credential.md")
    assert len(payloads) == 2
    completion = _validate_payload(
        payloads[0],
        required_phrases=(
            "Purpose:",
            "Owner:",
            "Expected values:",
            "{POWER_AUTOMATE_CONNECTIONS_URL}",
            "1. If an exact candidate is unhealthy",
            "2. Only if no exact candidate exists",
            "3. If sign-in reports `Invalid redirect_uri`",
            "system will freshly discover the connection",
        ),
    )
    selector = _validate_payload(
        payloads[1],
        required_phrases=(
            "Fresh read-only inventory found multiple healthy exact",
            "Choose the connection to bind",
            "No new connection will be created",
        ),
    )
    assert [option["label"] for option in completion["options"]] == [
        "Completed",
        "Not yet",
    ]
    assert not any(
        option.get("recommended") for option in completion["options"]
    )
    assert completion["allowFreeformInput"] is False
    assert selector["allowFreeformInput"] is False
    assert "{CANDIDATE_LABEL_1}" in json.dumps(selector)
    source = (_ACTIONS / "prepare-credential.md").read_text(encoding="utf-8")
    source_normalized = " ".join(source.split())
    assert "Do not ask the Maker for a connection display name" in source_normalized
    assert "never ask them to copy the key or connection ID" in source_normalized
    assert "This is the only question for that path" in source_normalized
    assert "do not show the **Completed / Not yet**" in source_normalized
    assert (
        "payload only when an exact connection needs repair or no exact "
        "connection exists"
    ) in source_normalized
    assert "must never run for the multiple-healthy-candidate path" in (
        source_normalized
    )
    assert "build the supported selector options directly from" in (
        source_normalized
    )


def test_portal_has_url_input_and_manual_fallback_payloads() -> None:
    payloads = _payloads(_ACTIONS / "configure-portal-url.md")
    assert len(payloads) == 2
    portal_input = _validate_payload(
        payloads[0],
        required_phrases=(
            "Purpose:",
            "Owner:",
            "{SERVICENOW_INSTANCE_ORIGIN}",
            "complete HTTPS employee portal URL",
            "will not infer `/sp`, `/esc`",
            "Set ServiceNow Portal BaseURI",
            "guarded native component update",
            "Copilot Studio -> Topics -> ServiceNow HRSD Setup Configurations",
        ),
    )
    fallback = _validate_payload(
        payloads[1],
        required_phrases=(
            "guarded component API did not change the topic",
            "Topics -> ServiceNow HRSD Setup Configurations",
            "Set ServiceNow Portal BaseURI",
            "{PORTAL_URL}",
            "fresh read-only verification",
        ),
    )
    assert portal_input["allowFreeformInput"] is True
    assert [option["label"] for option in fallback["options"]] == [
        "Completed",
        "Not yet",
    ]
    assert fallback["allowFreeformInput"] is False
    source = (_ACTIONS / "configure-portal-url.md").read_text(
        encoding="utf-8"
    )
    source_normalized = " ".join(source.split())
    assert "--expected-portal-url <full-url>" in source
    assert "exactly matches the complete URL supplied by the Maker" in (
        source_normalized
    )
    assert "different same-instance HTTPS portal path is not sufficient" in (
        source_normalized
    )


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [{"header": "Entra", "question": "What is the client ID?"}],
        [
            {
                "header": "Entra",
                "question": (
                    "{CURRENT_PROGRESS}\n\nPurpose: configure the app.\n\n"
                    "Owner: admin.\n\n1. Create app.\n\nWhat is the client ID?"
                ),
                "allowFreeformInput": True,
            }
        ],
        [
            {
                "header": "Entra",
                "question": (
                    "Purpose: configure the app.\n\nOwner: admin.\n\n"
                    "1. Create app.\n2. Add claims.\n3. Add scope.\n"
                    "4. Preauthorize.\n5. Add permissions.\n6. Consent.\n\n"
                    "What is the client ID?"
                ),
                "allowFreeformInput": True,
            }
        ],
        [
            {
                "header": "Entra",
                "question": "x" * 250,
                "description": "unsupported",
            }
        ],
    ],
)
def test_visible_handoff_validator_rejects_omitted_truncated_or_question_only(
    payload: object,
) -> None:
    with pytest.raises(ValueError):
        _validate_payload(
            payload,
            required_phrases=(
                "{CURRENT_PROGRESS}",
                "Purpose:",
                "Owner:",
                "1.",
                "2.",
                "3.",
                "4.",
                "5.",
                "6.",
                "What is the client ID?",
            ),
            rendered=False,
        )


def test_rendered_visible_handoff_rejects_unresolved_placeholders() -> None:
    payload = [
        {
            "header": "Confirm role",
            "question": (
                "{CURRENT_PROGRESS}\n\nPurpose: authorize this step.\n\n"
                "Owner: {REQUIRED_ROLE}.\n\nInstructions: verify the role "
                "before continuing.\n\nDo you hold the required role?"
            ),
            "options": [{"label": "Yes"}, {"label": "No"}],
            "allowFreeformInput": False,
        }
    ]
    with pytest.raises(ValueError, match="unresolved placeholders"):
        _validate_payload(
            payload,
            required_phrases=("Purpose:", "Owner:", "Instructions:"),
            rendered=True,
        )
