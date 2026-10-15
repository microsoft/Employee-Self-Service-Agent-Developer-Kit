# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Published ESS documentation routes shared by all FlightCheck reports."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import CheckResult

DOC_BASE = "https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service"

_ESS_URL = re.compile(
    r"https://learn\.microsoft\.com/(?:en-us/)?"
    r"(?:copilot/microsoft-365|microsoft-365/copilot)/employee-self-service/"
    r"(?P<page>[a-z0-9-]+)(?:#(?P<anchor>[a-z0-9-]+))?"
)

# Article and fragment IDs verified against published Learn pages. Do not
# carry a custom-engine anchor onto a DA article unless that section exists.
_COMMON_ROUTES = {
    "sap-successfactors": "sapsuccessfactors",
    "prepare#allow-the-external-systems-connector":
        "prepare#allow-the-external-systems-connector-within-power-platform",
    "workday#topics": "workday#copilot-studio-customizations",
    "workday#step-3-connection-references":
        "workday#install-the-workday-extension-pack-for-the-employee-self-service-agent",
    "workday#step-4-environment-variables":
        "workday#install-the-workday-extension-pack-for-the-employee-self-service-agent",
}
_DA_PAGES = {
    "prerequisites": "maker-journey-declarative-agent#before-you-install",
    "prepare": "maker-journey-declarative-agent#before-you-install",
    "install": "maker-journey-declarative-agent#install-an-employee-self-service-agent-template",
    "workday": "declarative-agent-workday",
    "workday-simplified-setup": "declarative-agent-workday",
    "workday-extensibility": "declarative-agent-customize#customize-topics",
    "servicenow": "declarative-agent-servicenow-hr-it",
    "servicenow-hrsd-itsm": "declarative-agent-servicenow-hr-it",
    "customize": "declarative-agent-customize",
    "publish": "declarative-agent-publish",
    "deploy-overview-alm": "alm-declarative-agent",
    "evaluations": "declarative-agent-evaluations",
    "known-issues-limitations": "declarative-agent-known-issues-limitations",
}
_DA_SECTIONS = {
    "customize#customize-topics": "declarative-agent-customize#customize-topics",
    "customize#customize-starter-prompts": "declarative-agent-customize#customize-starter-prompts",
    "workday#copilot-studio-customizations": "declarative-agent-workday#phase-5-configure-the-runtime",
    "workday#install-the-workday-extension-pack-for-the-employee-self-service-agent":
        "declarative-agent-workday#phase-5-configure-the-runtime",
    "workday#task-1-create-the-x509-public-key":
        "declarative-agent-workday-reference#workday-task-2-add-the-microsoft-entra-signing-certificate",
}


def resolve_documentation_links(text: str, *, declarative: bool = False) -> str:
    """Repair ESS URLs in plain text/Markdown; leave other products untouched.

    Without explicit DA context, retain custom-engine article selection.
    Existing DA links are never downgraded to custom-engine links.
    """
    def replace(match: re.Match[str]) -> str:
        page = match["page"]
        anchor = match["anchor"]
        route = page + (f"#{anchor}" if anchor else "")
        route = _COMMON_ROUTES.get(route, route)
        if declarative:
            route = _DA_SECTIONS.get(route, _DA_PAGES.get(route.split("#", 1)[0], route))
        return f"{DOC_BASE}/{route}"

    return _ESS_URL.sub(replace, text)


def apply_documentation_context(result: CheckResult, *, declarative: bool) -> None:
    """Resolve all human-readable links before JSON, HTML and console output."""
    for field in ("doc_link", "result", "remediation"):
        setattr(result, field, resolve_documentation_links(
            getattr(result, field), declarative=declarative,
        ))
    if declarative and result.doc_link == f"{DOC_BASE}/sapsuccessfactors":
        # The published SAP article describes the custom-engine extension.
        # Do not invent a DA counterpart or silently point to unrelated setup.
        result.doc_link = ""
        result.doc_label = ""
        note = "No DA-specific SAP SuccessFactors setup guide has been verified."
        if note not in result.remediation:
            result.remediation = f"{result.remediation}\n\n{note}".strip()
