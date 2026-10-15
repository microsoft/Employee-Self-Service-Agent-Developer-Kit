# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Metadata-scoped documentation routing, without live network dependencies."""

import json

import pytest

from flightcheck.documentation import DOC_BASE, resolve_documentation_links
from flightcheck.runner import CheckResult, FlightCheckRunner, save_results


@pytest.mark.parametrize("source,target", [
    ("workday", "declarative-agent-workday"),
    ("workday-simplified-setup", "declarative-agent-workday"),
    ("workday#topics", "declarative-agent-workday#phase-5-configure-the-runtime"),
    ("workday#step-3-connection-references", "declarative-agent-workday#phase-5-configure-the-runtime"),
    ("workday#step-4-environment-variables", "declarative-agent-workday#phase-5-configure-the-runtime"),
    ("workday#task-1-create-the-x509-public-key", "declarative-agent-workday-reference#workday-task-2-add-the-microsoft-entra-signing-certificate"),
    ("workday-extensibility", "declarative-agent-customize#customize-topics"),
    ("servicenow", "declarative-agent-servicenow-hr-it"),
    ("prerequisites#licensing", "maker-journey-declarative-agent#before-you-install"),
    ("prerequisites#required-roles", "maker-journey-declarative-agent#before-you-install"),
    ("prerequisites#identity-authentication-and-single-sign-on-sso", "maker-journey-declarative-agent#before-you-install"),
    ("prerequisites#set-up-prepaid-messages", "maker-journey-declarative-agent#before-you-install"),
    ("prepare#allow-the-external-systems-connector", "maker-journey-declarative-agent#before-you-install"),
    ("install#set-up-a-preferred-solution", "maker-journey-declarative-agent#install-an-employee-self-service-agent-template"),
    ("customize#customize-topics", "declarative-agent-customize#customize-topics"),
    ("customize#customize-starter-prompts", "declarative-agent-customize#customize-starter-prompts"),
    ("publish", "declarative-agent-publish"),
    ("evaluations", "declarative-agent-evaluations"),
    ("deploy-overview-alm", "alm-declarative-agent"),
    ("known-issues-limitations", "declarative-agent-known-issues-limitations"),
])
@pytest.mark.parametrize("base", [
    "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service",
    "https://learn.microsoft.com/microsoft-365/copilot/employee-self-service",
    DOC_BASE,
])
def test_da_routes_article_and_anchor_in_embedded_links(source, target, base):
    text = f"Read [setup]({base}/{source}), then retry."

    actual = resolve_documentation_links(text, declarative=True)

    assert actual == f"Read [setup]({DOC_BASE}/{target}), then retry."
    assert resolve_documentation_links(actual, declarative=True) == actual


@pytest.mark.parametrize("url", [
    "https://learn.microsoft.com/graph/api/overview",
    "https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial",
    "https://example.invalid/employee-self-service/workday",
    f"{DOC_BASE}/declarative-agent-workday#phase-4-create-connections",
])
def test_unrelated_and_existing_da_links_are_unchanged(url):
    assert resolve_documentation_links(url, declarative=True) == url


@pytest.mark.parametrize("config", [{}, {"releaseLine": "cea"}])
def test_unknown_and_custom_engine_context_keep_custom_engine_docs(config):
    runner = FlightCheckRunner()
    runner.config = config
    runner.register("Workday", lambda _: [
        CheckResult("WD-TEST", "Workday", "High", "Passed", "Test", "Observed",
                    doc_link=f"{DOC_BASE}/workday-simplified-setup")
    ])

    report = runner.run()

    assert report.results[0].doc_link == f"{DOC_BASE}/workday-simplified-setup"


def test_report_json_and_html_share_resolved_da_links(tmp_path):
    runner = FlightCheckRunner(scope="workday")
    runner.config = {"releaseLine": "da"}
    runner.register("Workday", lambda _: [
        CheckResult(
            "WD-TEST", "Workday", "High", "Warning", "Test",
            f"See {DOC_BASE}/workday#topics.",
            remediation=f"Read [instructions]({DOC_BASE}/workday-simplified-setup).",
            doc_link=f"{DOC_BASE}/workday",
        ),
    ])

    report = runner.run()
    save_results(report, str(tmp_path))

    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert data["results"][0]["doc_link"] == f"{DOC_BASE}/declarative-agent-workday"
    assert f'href="{DOC_BASE}/declarative-agent-workday"' in html
    for output in (json.dumps(data), html):
        assert "/workday-simplified-setup" not in output
        assert "/workday#topics" not in output
        assert "declarative-agent-workday#phase-5-configure-the-runtime" in output


def test_missing_da_sap_guide_is_explicit_not_a_custom_engine_link():
    runner = FlightCheckRunner()
    runner.config = {"releaseLine": "da"}
    runner.register("External", lambda _: [
        CheckResult("EXT-003", "External", "High", "NotConfigured", "SAP", "Absent",
                    doc_link=f"{DOC_BASE}/sap-successfactors")
    ])

    row = runner.run().results[0]

    assert row.doc_link == ""
    assert "No DA-specific SAP SuccessFactors setup guide" in row.remediation


def test_custom_engine_sap_link_uses_published_slug():
    row = CheckResult("EXT-003", "External", "High", "NotConfigured", "SAP", "Absent",
                      doc_link=f"{DOC_BASE}/sap-successfactors")

    assert row.doc_link == f"{DOC_BASE}/sapsuccessfactors"
