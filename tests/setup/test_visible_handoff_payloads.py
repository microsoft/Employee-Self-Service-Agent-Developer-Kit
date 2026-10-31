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


def _visible_prose_budget(text: str) -> tuple[int, int]:
    without_links = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    without_literals = re.sub(r"`[^`]+`", "", without_links)
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", without_literals)
    lines = [line for line in text.splitlines() if line.strip()]
    return len(words), len(lines)


def test_lifecycle_plan_confirmation_is_exact_and_separate_from_reply() -> None:
    path = _CONNECT / "shared" / "lifecycle-runner.md"
    assert _payloads(path) == [
        [
            {
                "header": "Start connection",
                "question": "Ready to start?",
                "options": [
                    {"label": "Yes, let's go"},
                    {"label": "Not now"},
                ],
                "allowFreeformInput": False,
            }
        ]
    ]
    source = path.read_text(encoding="utf-8")
    plan_section = source.split("## L.1", 1)[1].split("## L.2", 1)[0]
    assert plan_section.index("**Message:**") < plan_section.index(
        "**End message.**"
    ) < plan_section.index("<!-- visible-handoff-question:v1 -->")
    ordinary_reply = plan_section.split("**Message:**", 1)[1].split(
        "**End message.**", 1
    )[0]
    assert "Ready to start?" not in ordinary_reply
    assert plan_section.count("Ready to start?") == 1


@pytest.mark.parametrize(
    ("provider", "phase_count", "expected_roles"),
    [
        (
            "servicenow-da-hrsd",
            9,
            [
                "ESS Maker / Agent Developer",
                "ServiceNow Admin / security_admin",
                "Microsoft Entra Application Administrator or higher",
                "Power Platform Maker / Admin",
            ],
        ),
        (
            "servicenow-da-itsm",
            8,
            [
                "ESS Maker / Agent Developer",
                "ServiceNow Admin / security_admin",
                "Microsoft Entra Application Administrator or higher",
                "Power Platform Maker / Admin",
            ],
        ),
        ("workday", 3, ["Environment Maker"]),
    ],
)
def test_lifecycle_ordinary_plan_renders_complete_contract_in_order(
    provider: str,
    phase_count: int,
    expected_roles: list[str],
) -> None:
    source = (_CONNECT / "shared" / "lifecycle-runner.md").read_text(
        encoding="utf-8"
    )
    plan_section = source.split("## L.1", 1)[1].split("## L.2", 1)[0]
    template = plan_section.split("**Message:**", 1)[1].split(
        "**End message.**", 1
    )[0].strip()
    assert template == (
        "Here's what I'll do to connect this agent to {displayName}:\n\n"
        "{numbered list of every phase label, in contract order}\n\n"
        "Access needed: {comma-separated required and display-only plan roles}."
        "\n\nI'll check as I go and stop to explain anything that needs "
        "attention.\n\nCurrent step: Awaiting approval to start."
    )

    contract = json.loads(
        (_CONNECT / provider / "contract.json").read_text(encoding="utf-8")
    )
    labels = [phase["label"] for phase in contract["phases"]]
    roles = list(
        dict.fromkeys(
            [
                phase["requiredRole"]
                for phase in contract["phases"]
                if phase["mutates"]
            ] + contract.get("planRoles", [])
        )
    )
    assert len(labels) == phase_count
    assert roles == expected_roles
    rendered = template.format_map(
        {
            "displayName": contract["displayName"],
            "numbered list of every phase label, in contract order": "\n".join(
                f"{index}. {label}"
                for index, label in enumerate(labels, start=1)
            ),
            "comma-separated required and display-only plan roles": ", ".join(roles),
        }
    )

    assert not re.search(r"\{[^{}\n]+\}", rendered)
    assert rendered.split("\n\n")[1].splitlines() == [
        f"{index}. {label}" for index, label in enumerate(labels, start=1)
    ]
    for label in labels:
        assert rendered.count(label) == 1
    for role in expected_roles:
        assert rendered.count(role) == 1
    assert f"Access needed: {', '.join(expected_roles)}." in rendered
    assert contract["displayName"] in rendered
    assert rendered.endswith("Current step: Awaiting approval to start.")
    assert "Ready to start?" not in rendered
    assert "Complete" not in rendered
    assert "Executing" not in rendered
    assert ".local" not in rendered
    assert not any(f"`{phase['id']}`" in rendered for phase in contract["phases"])


@pytest.mark.parametrize(
    ("path", "required_phrases"),
    [
        (
            _ACTIONS / "admin-preflight.md",
            (
                "For {AGENT_DISPLAY_NAME}",
                "`https://dev184242.service-now.com`",
                "ask your ServiceNow administrator",
                "public ServiceNow HTTPS root URL",
                "portal or module path",
                "password",
                "token",
            ),
        ),
        (
            _ACTIONS / "verify-plugin-prerequisites.md",
            (
                "Purpose:",
                "Owner:",
                "{HR_CORE_PLUGIN_URL}",
                "Plugin id: `com.sn_hr_core`",
                "Version Details: `Installed`",
                "installed and ready for you to use",
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
                "4. Decide whether the ServiceNow functionality worked correctly",
                "What was the result?",
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


def test_publish_action_is_retired_without_visible_question() -> None:
    text = (_ACTIONS / "publish-agent.md").read_text(encoding="utf-8")
    assert "<!-- visible-handoff-question:" not in text
    assert "This action is retired" in text
    assert "Do not invoke `publish`" in text
    assert "historical evidence" in text


def test_servicenow_questions_use_buttons_and_bounded_freeform() -> None:
    allowed_freeform = {
        "admin-preflight.md",
        "configure-portal-url.md",
    }
    paths = [
        *(_CONNECT / "servicenow-da-hrsd" / "actions").glob("*.md"),
        *(_CONNECT / "servicenow-da-itsm" / "actions").glob("*.md"),
    ]

    for path in paths:
        for payload in _payloads(path) if _MARKER.search(
            path.read_text(encoding="utf-8")
        ) else []:
            question = _validate_payload(payload, required_phrases=())
            assert question["question"].strip().splitlines()[0] != (
                question["header"]
            )
            assert not any(
                option.get("recommended")
                for option in question.get("options") or []
            )
            if question.get("allowFreeformInput") is True:
                assert path.name in allowed_freeform


@pytest.mark.parametrize("provider", ("servicenow-da-hrsd", "servicenow-da-itsm"))
def test_identity_admin_guides_use_only_executable_stage_questions(
    provider: str,
) -> None:
    actions = _CONNECT / provider / "actions"
    entra = (actions / "guide-entra-registration.md").read_text(
        encoding="utf-8"
    )
    entra_normalized = " ".join(entra.split())
    oidc = (actions / "guide-servicenow-oidc.md").read_text(
        encoding="utf-8"
    )
    oidc_normalized = " ".join(oidc.split())

    assert "<!-- visible-handoff-question:" not in entra
    assert "<!-- visible-handoff-question:" not in oidc
    assert "{TOKEN_CLAIM_NAME}" not in oidc
    assert '"label": "Completed"' not in oidc
    assert "question itself must contain all seven operations" not in oidc
    assert "send the returned `question` object unchanged" in entra
    assert "identity-mapping-handoff --stage entra" in entra
    assert "instructionTitle`, `instruction`, and one short" in entra
    assert "`allowFreeformInput: true`" in entra
    assert (
        "`Please enter the returned Entra admin handoff workbook URL.`"
        in entra
    )
    assert "generated workbook link" in entra
    assert "not the returned answer" in entra_normalized
    assert "successful validation and import are still\nrequired" in entra
    assert "missing actual claim\nnames" in entra
    assert "There is no separate client-ID question" in entra
    assert "Before the single visible handoff, run:" in oidc
    assert "identity-mapping-handoff --stage servicenow" in oidc
    assert "Render the exact returned `instructionTitle` and `instruction`" in (
        oidc
    )
    assert "`allowFreeformInput: true`" in oidc
    assert (
        "`Please enter the returned ServiceNow admin handoff workbook URL.`"
        in oidc
    )
    assert "they are not the returned answer" in oidc_normalized
    assert "Import only the exact local path returned by the question" in oidc
    assert "record-identity-mapping" in entra
    assert "record-identity-mapping" in oidc


@pytest.mark.parametrize(
    "provider",
    ("servicenow-da-hrsd", "servicenow-da-itsm"),
)
def test_credential_has_completed_question_and_bounded_candidate_selector(
    provider: str,
) -> None:
    action = _CONNECT / provider / "actions" / "prepare-credential.md"
    payloads = _payloads(action)
    assert len(payloads) == 2
    completion = _validate_payload(
        payloads[0],
        required_phrases=(
            "Purpose:",
            "Owner:",
            "Expected values:",
            "{POWER_AUTOMATE_CONNECTIONS_URL}",
            "1. If an exact candidate is unhealthy",
            "2. Only if no usable exact candidate exists",
            "search box in the upper-right to search `ServiceNow`",
            "Microsoft-published `ServiceNow` connector using its `+` action",
            "choose Microsoft Entra ID User Login",
            "enter the exact Instance Name and Resource URI",
            "3. If sign-in reports `Invalid redirect_uri`",
            "current maker's own Microsoft account",
            "do not impersonate that owner",
            "Never ask for or display passwords",
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
    source = action.read_text(encoding="utf-8")
    source_normalized = " ".join(source.split())
    assert "Do not ask the Maker for a connection display name" in source_normalized
    assert "never ask them to copy the key or connection ID" in source_normalized
    assert "This is the only question for that path" in source_normalized
    assert "do not show the **Completed / Not yet**" in source_normalized
    assert "Never ask for or display a password" in source_normalized
    assert "another maker owns it" in source_normalized
    assert "never an observed failed-connection value" in source_normalized
    assert (
        "payload only when an exact connection needs repair or no exact "
        "connection exists"
    ) in source_normalized
    assert "must never run for the multiple-healthy-candidate path" in (
        source_normalized
    )
    assert source_normalized.index("choose `New connection`") < (
        source_normalized.index("search box in the upper-right")
    )
    assert source_normalized.index("search box in the upper-right") < (
        source_normalized.index("connector published by **Microsoft**")
    )
    assert source_normalized.index("connector published by **Microsoft**") < (
        source_normalized.index("Choose `Microsoft Entra ID User Login`")
    )
    assert "build the supported selector options directly from" in (
        source_normalized
    )


@pytest.mark.parametrize(
    ("provider", "prompt"),
    (
        ("servicenow-da-hrsd", "List my open HR cases"),
        ("servicenow-da-itsm", "List my open IT tickets"),
    ),
)
def test_servicenow_test_question_has_only_neutral_pass_choices(
    provider: str,
    prompt: str,
) -> None:
    payload = _validate_payload(
        _payloads(
            _CONNECT / provider / "actions" / "test-connection.md"
        )[0],
        required_phrases=(
            "verify whether ServiceNow functionality works correctly",
            "{COPILOT_STUDIO_AGENT_URL}",
            "Save the current authored draft",
            prompt,
            "Do not include or return",
        ),
    )

    assert [option["label"] for option in payload["options"]] == [
        "Pass",
        "Not pass",
    ]
    assert not any(option.get("recommended") for option in payload["options"])
    assert payload["allowFreeformInput"] is False


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
            "Use the instance root only when the administrator explicitly",
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
