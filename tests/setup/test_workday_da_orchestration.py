# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contracts for the runnable Workday DA setup orchestration."""

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKDAY_DA = (
    _REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "setup"
    / "workday-da"
)


def test_orchestrator_resumes_durable_state_without_restarting_setup() -> None:
    text = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "pick the first whose state is not `done`" in text
    assert "must not** batch those writes" in text
    assert 'provider `status` to be `"ready"`' in text
    assert ".local/connect/workday-da/tasks.md" in text
    assert ".local/setup/workday-da/tasks.md" in text
    assert "move that exact file to the canonical path" in normalized
    assert "you do not need to run `/setup` again" in normalized
    assert "Here's the plan for connecting Workday to your ESS HR agent" in text
    assert "- {m} Verify employee SAML sign-in policy" in text
    assert "Your ESS HR agent is connected to Workday" in text


def test_extension_install_uses_the_ring_aware_runtime_installer() -> None:
    text = (_WORKDAY_DA / "install-extension.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "install_workday_da_extension.py" in text
    assert '--package-flavor "{PACKAGE_FLAVOR}"' in text
    assert '--ring "{RING}"' in text
    assert "managed-pac.nuget.config" in text
    assert "Do not present .NET and PAC as unexplained product setup steps" in normalized
    assert "do not restart the Workday checklist" in normalized


def test_connections_are_created_before_binding_and_flow_activation() -> None:
    text = (_WORKDAY_DA / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )

    prepare = text.index("## DA4.0 — Prepare the connections page")
    bind = text.index("## DA4.3 — Bind the extension connections")

    assert prepare < bind
    assert "make.preprod.powerautomate.com" in text
    assert "make.powerautomate.com" in text
    assert "Workday and Dataverse connections show **Connected**" in text
    assert "msdyn_sharedworkdaysoap_workdayruntime" in text
    assert "msdyn_sharedcommondataserviceforapps_workdayruntime" in text


def test_topic_and_authorization_guidance_matches_the_supported_runtime() -> None:
    text = (_WORKDAY_DA / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )

    assert "Enable all Workday topics" in text
    assert "Choose specific Workday topics" in text
    assert "legacy ISU/RaaS" not in text
    assert "Prefer: return=representation" in text
    assert "fails closed on these" in text
    assert "Do not rely on the script's exit code" not in text


def test_readiness_requires_a_signed_in_runtime_scenario() -> None:
    text = (_WORKDAY_DA / "verify-connection.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Run one enabled Workday scenario" in text
    assert "returns real Workday data" in normalized
    assert 'status: "ready"' in text
    assert "does not prove the live" in text
