# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Metadata-scoped documentation routing, without live network dependencies."""

import json
from dataclasses import asdict

import pytest

from flightcheck.agent_scope import is_declarative_agent
from flightcheck.checks.local_files import run_local_file_checks
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


@pytest.fixture
def mixed_agent_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for slug in ("hr", "legacy"):
        folder = tmp_path / "workspace" / "agents" / slug
        (folder / "topics").mkdir(parents=True)
        (folder / "agent.mcs.yml").write_text('instructions: ""\n', encoding="utf-8")
        (folder / "topics" / "response-preparation.mcs.yml").write_text(
            "kind: AdaptiveDialog\n", encoding="utf-8",
        )
    return tmp_path


@pytest.mark.parametrize("selected", ["hr", "legacy"])
@pytest.mark.parametrize("reverse_records", [False, True])
@pytest.mark.parametrize("checkpoint", [None, "TOPIC-010"])
def test_mixed_local_reports_route_each_subject_not_active_agent(
    mixed_agent_workspace, selected, reverse_records, checkpoint,
):
    agents = [
        {"slug": "hr", "releaseLine": " DA "},
        {"slug": "legacy", "releaseLine": "cea"},
    ]
    if reverse_records:
        agents.reverse()
    matcher = None if checkpoint is None else lambda value: value == checkpoint
    runner = FlightCheckRunner(scope="local", target_matcher=matcher)
    runner.config = {"activeAgent": selected, "agents": agents}
    runner.register("Local Files", run_local_file_checks)
    before = run_local_file_checks(runner)
    if checkpoint is not None:
        before = [row for row in before if row.checkpoint_id == checkpoint]

    report = runner.run()
    output = mixed_agent_workspace / "report"
    save_results(report, str(output))

    saved = json.loads((output / "results.json").read_text(encoding="utf-8"))
    cards = (output / "report.html").read_text(encoding="utf-8").split('<div class="check"')[1:]
    contracts = saved["contract"]["results"]
    assert len(report.results) == len(before) == len(saved["results"]) == len(contracts) == len(cards)
    for original, actual, persisted, contract in zip(
        before, report.results, saved["results"], contracts, strict=True,
    ):
        slug = "hr" if original.category.endswith("(Hr)") else "legacy"
        expected_url = resolve_documentation_links(original.doc_link, declarative=slug == "hr")
        assert actual.doc_link == persisted["doc_link"] == expected_url
        assert contract["docLink"] == expected_url
        assert actual.evidence["agentSlug"] == persisted["evidence"]["agentSlug"] == slug
        assert contract["evidence"] == actual.evidence
        assert contract["status"] == original.status
        original_fields, actual_fields = asdict(original), asdict(actual)
        original_fields.pop("doc_link")
        actual_fields.pop("doc_link")
        assert actual_fields == original_fields
        card = next(card for card in cards if f'{actual.description}<span class="id">' in card)
        if expected_url:
            assert f'href="{expected_url}"' in card

    topic_rows = [row for row in report.results if row.checkpoint_id == "TOPIC-010"]
    assert [row.doc_link for row in topic_rows] == [
        f"{DOC_BASE}/declarative-agent-customize#customize-topics",
        f"{DOC_BASE}/customize#customize-topics",
    ]
    for row in topic_rows:
        assert row.status == "Warning"
        assert row.result == "Required topic not found in extracted files"
        assert "Verify 'Ambiguity Clarification' exists" in row.remediation


@pytest.mark.parametrize("sibling_records", [
    [],
    [{"slug": "legacy"}],
    [{"slug": "legacy", "releaseLine": None}],
    [{"slug": "legacy", "releaseLine": ""}],
    [{"slug": "legacy", "releaseLine": False}],
    [{"slug": "legacy", "releaseLine": 0}],
    [{"slug": "legacy", "releaseLine": 42}],
    [{"slug": "legacy", "releaseLine": []}],
    [{"slug": "legacy", "releaseLine": {}}],
    [{"slug": "legacy", "releaseLine": "cea"}],
    [{"slug": "legacy", "releaseLine": "da"}, {"slug": "legacy", "releaseLine": "da"}],
])
def test_unknown_or_non_da_sibling_never_inherits_run_context(
    mixed_agent_workspace, sibling_records,
):
    runner = FlightCheckRunner(scope="local")
    runner.config = {
        "activeAgent": "hr", "releaseLine": "da",
        "agent": {"slug": "hr", "releaseLine": "da"},
        "agents": [{"slug": "hr", "releaseLine": "da"}, *sibling_records],
    }
    runner.workday_da_profile = True
    runner.register("Local Files", run_local_file_checks)

    report = runner.run()

    row = next(row for row in report.results if (
        row.checkpoint_id == "TOPIC-010" and row.category == "Topics (Legacy)"
    ))
    assert row.doc_link == f"{DOC_BASE}/customize#customize-topics"
    assert row.status == "Warning"
    assert row.result == "Required topic not found in extracted files"
    assert "Verify 'Ambiguity Clarification' exists" in row.remediation


@pytest.mark.parametrize("workspace_marker,profile", [("da", False), (None, True)])
def test_local_selected_subject_keeps_eligible_run_fallback(
    mixed_agent_workspace, workspace_marker, profile,
):
    runner = FlightCheckRunner(scope="local")
    runner.config = {
        "activeAgent": "hr", "releaseLine": workspace_marker,
        "agents": [{"slug": "hr"}, {"slug": "legacy"}],
    }
    runner.workday_da_profile = profile
    runner.register("Local Files", run_local_file_checks)

    rows = [row for row in runner.run().results if row.checkpoint_id == "TOPIC-010"]

    assert [row.doc_link for row in rows] == [
        f"{DOC_BASE}/declarative-agent-customize#customize-topics",
        f"{DOC_BASE}/customize#customize-topics",
    ]


@pytest.mark.parametrize("subject", [None, "", False, 0, [], {}, "missing"])
def test_invalid_explicit_result_subject_cannot_inherit_selected_da(subject):
    runner = FlightCheckRunner()
    runner.config = {"agent": {"slug": "hr", "releaseLine": "da"}}
    runner.workday_da_profile = True
    runner.register("Docs", lambda _: [
        CheckResult(
            "DOC-TEST", "Docs", "High", "Warning", "Subject", "Observed",
            doc_link=f"{DOC_BASE}/customize", evidence={"agentSlug": subject},
        ),
    ])

    row = runner.run().results[0]

    assert row.doc_link == f"{DOC_BASE}/customize"


@pytest.mark.parametrize("subject,expected", [
    ("hr", False), ("legacy", True), ("", False), ("missing", False),
])
def test_subject_context_uses_cli_selection_not_workspace_selection(subject, expected):
    runner = FlightCheckRunner()
    runner.config = {
        "activeAgent": "hr", "releaseLine": "da",
        "agents": [{"slug": "hr"}, {"slug": "legacy"}],
    }
    runner.agent_slug = "legacy"
    runner.workday_da_profile = True

    assert is_declarative_agent(runner, subject_slug=subject) is expected


@pytest.mark.parametrize("release_line", ["", False, 0, "cea"])
def test_selected_subject_explicit_non_da_value_vetoes_fallback(release_line):
    runner = FlightCheckRunner()
    runner.config = {
        "activeAgent": "hr", "releaseLine": "da",
        "agents": [{"slug": "hr", "releaseLine": release_line}],
    }
    runner.workday_da_profile = True

    assert is_declarative_agent(runner, subject_slug="hr") is False


def test_known_subject_resolves_without_an_active_agent():
    runner = FlightCheckRunner()
    runner.config = {"agents": [{"slug": "hr", "releaseLine": "da"}, {"slug": "legacy"}]}
    runner.workday_da_profile = True

    assert is_declarative_agent(runner, subject_slug="hr") is True
    assert is_declarative_agent(runner, subject_slug="legacy") is False
    assert is_declarative_agent(runner) is False
