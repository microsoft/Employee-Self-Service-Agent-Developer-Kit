# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _ROOT / "solutions" / "ess-maker-skills"
_CONNECT = _SOLUTION / "src" / "skills" / "connect"
_ACTIONS = _CONNECT / "servicenow-da-hrsd" / "actions"
sys.path.insert(0, str(_SOLUTION / "scripts"))
import connect_servicenow_da as snow  # noqa: E402

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
    other_provider_section = plan_section.split("### Other providers", 1)[1]
    assert other_provider_section.count("Ready to start?") == 1
    assert "DA ServiceNow business-group availability" in plan_section


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
                "Required evidence for the selected ServiceNow instance:",
                "Plugin id: `com.sn_hr_core`",
                "Version Details: `Installed`",
                "installed and ready for you to use",
                "Has the ServiceNow administrator confirmed",
            ),
        ),
        (
            _ACTIONS / "prepare-topics.md",
            (
                "Selected agent:",
                "Environment:",
                "Component hash:",
                "Current topic inventory:",
                "Inactive HRSD topics:",
                "Do you want to enable all listed inactive",
            ),
        ),
        (
            _ACTIONS / "connect-agent.md",
            (
                "Selected agent:",
                "Selected credential:",
                "Does the ServiceNow row currently show Connected",
                "Manual agent-binding evidence",
            ),
        ),
        (
            _ACTIONS / "test-connection.md",
            (
                "Selected agent:",
                "Required prompt: **List my open HR cases**",
                "exact saved draft and selected ServiceNow connection",
                "Return only Pass or Not pass",
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
            assert "{CURRENT_PROGRESS}" not in question["question"]
            assert "Connection progress:" not in question["question"]
            assert "**Phases**" not in question["question"]
        if path.name == "guide-entra-registration.md":
            assert "requirements above" in question["question"].casefold()
        else:
            assert "above" not in question["question"].casefold()


@pytest.mark.parametrize(
    "path",
    (
        _ACTIONS / "verify-plugin-prerequisites.md",
        _ACTIONS / "prepare-credential.md",
        _ACTIONS / "connect-agent.md",
        _ACTIONS / "prepare-topics.md",
        _ACTIONS / "configure-portal-url.md",
        _ACTIONS / "test-connection.md",
        _CONNECT
        / "servicenow-da-itsm"
        / "actions"
        / "prepare-credential.md",
        _CONNECT / "servicenow-da-itsm" / "actions" / "connect-agent.md",
        _CONNECT
        / "servicenow-da-itsm"
        / "actions"
        / "configure-portal-url.md",
        _CONNECT / "servicenow-da-itsm" / "actions" / "test-connection.md",
    ),
)
def test_modified_completion_cards_exclude_operational_instructions(
    path: Path,
) -> None:
    for payload in _payloads(path):
        question = _validate_payload(payload, required_phrases=())["question"]
        for forbidden in (
            "Purpose:",
            "Owner:",
            "What to do:",
            "Open Employee Self-Service",
            "Open HR Service Delivery Core",
            "1. Open ",
            "{COPILOT_STUDIO_AGENT_URL}",
            "{POWER_AUTOMATE_CONNECTIONS_URL}",
            "{POWER_APPS_URL}",
        ):
            assert forbidden not in question


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
            assert "{CURRENT_PROGRESS}" not in question["question"]
            assert "Connection progress:" not in question["question"]
            assert "**Phases**" not in question["question"]
            assert not any(
                option.get("recommended")
                for option in question.get("options") or []
            )
            labels = [
                option["label"]
                for option in question.get("options") or []
            ]
            if path.name == "guide-servicenow-oidc.md":
                assert labels == ["Yes", "No"]
            else:
                assert all(
                    label.strip()
                    and label.casefold() not in {"yes", "no"}
                    for label in labels
                )
            if question.get("allowFreeformInput") is True:
                assert path.name in allowed_freeform
            adapted = snow.adapt_question_to_ask_user(question)
            assert adapted["canonicalQuestion"] == question
            assert adapted["askUserArguments"]["message"] == (
                question["header"]
            )
            field = adapted["askUserArguments"]["requestedSchema"][
                "properties"
            ]["response"]
            assert field["description"] == question["question"]
            assert adapted["askUserArguments"]["requestedSchema"][
                "required"
            ] == ["response"]
            if question.get("options"):
                assert field["title"] == "Selection"
                assert [item["title"] for item in field["oneOf"]] == [
                    option["label"] for option in question["options"]
                ]
            else:
                assert field["title"] == "Input"
                assert "oneOf" not in field


def test_hr_plugin_completion_header_and_question_are_distinct() -> None:
    payload = _validate_payload(
        _payloads(_ACTIONS / "verify-plugin-prerequisites.md")[0],
        required_phrases=(
            "Required evidence for the selected ServiceNow instance:",
            "Has the ServiceNow administrator confirmed",
        ),
    )
    assert payload["header"] == "HR Service Delivery Core"
    assert payload["header"] != payload["question"]
    assert [option["label"] for option in payload["options"]] == [
        "Yes, all listed installed-and-ready evidence is present",
        "No, one or more required items are missing",
        "Not sure, the administrator still needs to check",
    ]


@pytest.mark.parametrize("provider", ("servicenow-da-hrsd", "servicenow-da-itsm"))
def test_identity_admin_guides_use_only_required_value_questions(
    provider: str,
) -> None:
    actions = _CONNECT / provider / "actions"
    entra = (actions / "guide-entra-registration.md").read_text(
        encoding="utf-8"
    )
    oidc = (actions / "guide-servicenow-oidc.md").read_text(
        encoding="utf-8"
    )

    assert "<!-- visible-handoff-question:v1-confirm-setup -->" not in entra
    assert "<!-- visible-handoff-question:v1-confirm-setup -->" not in oidc
    assert "{TOKEN_CLAIM_NAME}" not in oidc
    assert '"label": "Completed"' not in oidc
    assert "question itself must contain all seven operations" not in oidc
    assert "Render the returned `instructionTitle` and `instruction`" in entra
    assert "there is no\nseparate Entra completion question" in entra
    assert "identity-mapping-handoff --stage entra" in entra
    assert "send the\nreturned short `question` unchanged" in entra
    assert "accepts the local path of either the completed XLSX or CSV" in entra
    assert "completes the Manual Entra identity phase" in entra
    assert "does not prove app configuration" in entra
    assert "identity-mapping-handoff --stage servicenow" in oidc
    assert "collect only the actual\ninternal User Field" in oidc
    assert "record-identity-direct --stage servicenow" in oidc
    assert "atomically persists the mapping receipt and owning Manual" in oidc
    assert "Accept the local path of either the completed XLSX or CSV" in oidc
    assert "do not\nask a saved/configured" in oidc
    assert (
        "does not prove that the OIDC provider is saved or configured"
        in " ".join(oidc.split())
    )
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
            "Required connection match:",
            "Authentication Type: Microsoft Entra ID User Login",
            "Resource URI: `{APP_CLIENT_ID}`",
            "Instance Name: `{INSTANCE_NAME}`",
            "Current exact candidates:",
            "Display name `{CONNECTION_DISPLAY_NAME}` is optional guidance",
            "triggers one fresh supported connection inventory read",
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
        "Completed, the exact ServiceNow connection is Connected",
        "Not yet, the ServiceNow connection is not ready",
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
    expected = completion["question"]
    assert expected.index("Authentication Type:") < expected.index(
        "Resource URI:"
    )
    assert expected.index("Resource URI:") < expected.index("Instance Name:")
    assert "Purpose:" not in expected
    assert "Owner:" not in expected
    assert "What to do:" not in expected
    assert "{POWER_AUTOMATE_CONNECTIONS_URL}" not in expected
    assert "direct form/detail route is unverified" not in expected
    field_table = source_normalized.split(
        "Show the exact field table from the output:",
        1,
    )[1]
    display_index = field_table.index("Display name (optional)")
    auth_index = field_table.index("Authentication Type")
    resource_index = field_table.index("Resource URI")
    instance_index = field_table.index("Instance Name")
    assert display_index < auth_index < resource_index < instance_index
    assert "direct connector-form or connection-detail URL" in (
        source_normalized
    )
    assert "does not create, repair, sign in, submit, or prefill" in (
        source_normalized
    )
    assert "conditional remediation, not an observed current error" in (
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
def test_servicenow_test_question_has_explicit_result_choices(
    provider: str,
    prompt: str,
) -> None:
    payload = _validate_payload(
        _payloads(
            _CONNECT / provider / "actions" / "test-connection.md"
        )[0],
        required_phrases=(
            "Selected agent:",
            "Required prompt:",
            prompt,
            "exact saved draft and selected ServiceNow connection",
            "Return only Pass or Not pass",
        ),
    )

    product = "HRSD" if provider.endswith("hrsd") else "ITSM"
    assert [option["label"] for option in payload["options"]] == [
        f"Pass, the ServiceNow {product} capability worked correctly",
        "Not pass, it failed or could not be verified",
    ]
    assert not any(option.get("recommended") for option in payload["options"])
    assert payload["allowFreeformInput"] is False
    assert "Purpose:" not in payload["question"]
    assert "Owner:" not in payload["question"]
    assert "{COPILOT_STUDIO_AGENT_URL}" not in payload["question"]
    assert "Open the Test pane" not in payload["question"]


def test_portal_has_url_input_and_manual_fallback_payloads() -> None:
    payloads = _payloads(_ACTIONS / "configure-portal-url.md")
    assert len(payloads) == 2
    portal_input = _validate_payload(
        payloads[0],
        required_phrases=(
            "Target topic:",
            "{SERVICENOW_INSTANCE_ORIGIN}",
            "complete HTTPS employee portal URL",
            "Set ServiceNow Portal BaseURI",
            "will not infer `/sp`, `/esc`",
        ),
    )
    fallback = _validate_payload(
        payloads[1],
        required_phrases=(
            "guarded component API did not change the exact HR target topic",
            "ServiceNow HRSD Setup Configurations",
            "Set ServiceNow Portal BaseURI",
            "{PORTAL_URL}",
            "fresh read-only verification",
        ),
    )
    assert portal_input["allowFreeformInput"] is True
    assert [option["label"] for option in fallback["options"]] == [
        "Completed, the exact portal URL is saved",
        "Not yet, the portal URL is not saved",
    ]
    assert fallback["allowFreeformInput"] is False
    for payload in (portal_input, fallback):
        question = payload["question"]
        assert "Purpose:" not in question
        assert "Owner:" not in question
        assert "Open Copilot Studio" not in question
        assert "1. Open" not in question
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
    assert "show this manual fallback in the ordinary current-task reply" in (
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
