# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Regenerate the checked-in Workday administrator workbook templates."""

from __future__ import annotations

from pathlib import Path

from workday_connect_entra_contracts import build_entra_handoff
from workday_connect_model import PhaseStatus, default_state
from workday_connect_workbook import (
    ENTRA_ADMIN_WORKBOOK_PATH,
    WORKBOOK_ASSET_DIRECTORY,
    WORKDAY_ADMIN_WORKBOOK_PATH,
    write_administrator_workbook,
)
from workday_connect_workday_admin_contracts import build_workday_admin_packet


def _template_state() -> dict:
    state = default_state()
    state["scope"].update(
        {
            "workdayTenant": "XXXX",
            "entraTenantId": "XXXX",
        }
    )
    state["phases"]["preflight"]["status"] = PhaseStatus.COMPLETE.value
    state["identifiers"].update(
        {
            "workdaySamlEntityId": "http://www.workday.com/XXXX",
            "entraAppIdUri": "api://XXXX",
            "microsoftEntraIdentifier": "https://sts.windows.net/XXXX/",
            "entraLoginUrl": (
                "https://login.microsoftonline.com/XXXX/saml2"
            ),
            "replyUrl": "https://XXXX",
            "signingCertificate": {
                "thumbprint": "XXXX",
                "validTo": "2099-12-31",
            },
        }
    )
    return state


def generate_workbooks(
    output_directory: Path = WORKBOOK_ASSET_DIRECTORY,
) -> tuple[Path, Path]:
    """Generate both checked-in administrator workbook templates."""
    state = _template_state()
    entra_packet = build_entra_handoff(state)
    workday_packet = build_workday_admin_packet(state)
    for instruction in workday_packet["captureInstructions"]:
        if instruction["information"] == "SAML row settings":
            instruction["instruction"] = (
                "Compare the enabled Microsoft Entra row with the exact "
                "Issuer, Service Provider ID, SSO service URL, and redirect "
                "URL shown in the agent handoff."
            )
        elif instruction["information"] == "Certificate expiration":
            instruction["instruction"] = (
                "Compare its expiration date with the verified Entra date "
                "shown by the agent."
            )
    workday_actions = [
        workday_packet["actions"][0],
        (
            "If the enabled row already uses Microsoft Entra, update only the "
            "intended Microsoft Entra row and preserve unrelated settings."
        ),
        (
            "If the enabled row uses another provider, preserve that row and "
            "follow the customer-approved coexistence or controlled-transition "
            "path shown in the agent handoff."
        ),
        (
            "If there is no enabled SAML row, create the new Microsoft Entra "
            "row for the intended employee environment."
        ),
        *[
            action.replace(
                "http://www.workday.com/XXXX",
                "the exact Service Provider ID shown in the agent handoff",
            )
            .replace(
                "https://login.microsoftonline.com/XXXX/saml2",
                "the exact Microsoft Entra login URL shown in the agent handoff",
            )
            .replace(
                "https://XXXX",
                "the exact Workday reply URL shown in the agent handoff",
            )
            for action in workday_packet["actions"][1:]
        ],
    ]
    entra_path = write_administrator_workbook(
        output_directory / ENTRA_ADMIN_WORKBOOK_PATH.name,
        title="Microsoft Entra administrator handoff",
        administrator_role=entra_packet["administratorRole"],
        actions=entra_packet["actions"],
        capture_instructions=entra_packet["captureInstructions"],
    )
    workday_path = write_administrator_workbook(
        output_directory / WORKDAY_ADMIN_WORKBOOK_PATH.name,
        title="Workday administrator handoff",
        administrator_role=workday_packet["administratorRole"],
        actions=workday_actions,
        capture_instructions=workday_packet["captureInstructions"],
    )
    return entra_path, workday_path


if __name__ == "__main__":
    for generated_path in generate_workbooks():
        print(generated_path)
