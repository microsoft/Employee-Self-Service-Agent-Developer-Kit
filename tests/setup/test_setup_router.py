# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural guards for Workday routing and the hybrid setup boundary."""

from __future__ import annotations

import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_BOUNDARY = _SOLUTION / "src" / "skills" / "setup" / "SKILL.md"
_CONNECT_STEP1 = _SOLUTION / "src" / "skills" / "connect" / "step1.md"
_CONNECT_SKILL = _SOLUTION / "src" / "skills" / "connect" / "SKILL.md"
_OLD_PROMPT = _SOLUTION / ".github" / "prompts" / "setup-workday.prompt.md"
_WORKDAY_PROVIDER_DIR = _SOLUTION / "src" / "skills" / "connect" / "workday"
_WORKDAY_PLAYBOOKS = (
    "provision-power-platform-environment.md",
    "install-ess.md",
    "provision-workday-entra-app.md",
    "configure-workday-tenant.md",
    "install-workday-extension-pack.md",
    "install-workday-ootb-topics.md",
    "create-new-topic.md",
)


def test_connect_workday_routes_by_architecture_and_install_state() -> None:
    text = _CONNECT_STEP1.read_text(encoding="utf-8")

    assert "src/skills/setup/workday-da/SKILL.md" in text
    assert "src/skills/connect/workday/SKILL.md" in text
    assert "WD-DA-PKG-001" in text
    assert "WD-PKG-001" in text
    assert "ESS DA Hub is not supported" in text
    assert "Passed` + simplified-install result" in text
    assert "Passed` + full / legacy result" in text
    assert "do not treat it as a fresh environment" in text
    assert "retired `selected_products` field" in text
    assert "Fresh CEA Workday\n  installation is not available" in text
    assert "connect/workday/step" not in text


def test_connect_workday_provider_contract_and_review_guards() -> None:
    contract_path = _WORKDAY_PROVIDER_DIR / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["detect"]["meansInstalled"] == "Passed"
    assert contract["detect"]["meansNotInstalled"] == "NotConfigured"
    assert (_WORKDAY_PROVIDER_DIR / "SKILL.md").is_file()
    assert not list(_WORKDAY_PROVIDER_DIR.glob("step*.md"))

    runner = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "shared"
        / "lifecycle-runner.md"
    ).read_text(encoding="utf-8")
    assert "checkpointAcknowledgements" in runner
    assert "allowed `Manual`/`Warning` result lacks" in runner

    da_skill = (
        _SOLUTION / "src" / "skills" / "setup" / "workday-da" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "canonical\n`.local/setup/config.json` `agents` record" in da_skill
    assert "stable slug,\n`botId`" in da_skill
    assert 'provider `status` to be `"ready"`' in da_skill

    updater = (
        _SOLUTION
        / "src"
        / "skills"
        / "setup"
        / "workday-da"
        / "shared"
        / "checklist-updater.md"
    ).read_text(encoding="utf-8")
    assert 'RESULT_SOURCE="external"' in updater
    assert "already shown `EXTERNAL_EVIDENCE`" in updater

    entra = (
        _SOLUTION
        / "src"
        / "skills"
        / "setup"
        / "workday-da"
        / "provision-entra-app.md"
    ).read_text(encoding="utf-8")
    assert "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$" in entra
    assert "label-to-app mapping" in entra

    power_platform = (
        _SOLUTION
        / "src"
        / "skills"
        / "setup"
        / "workday-da"
        / "configure-power-platform.md"
    ).read_text(encoding="utf-8")
    assert "exactly one MCSBot delegated authorization" in power_platform
    assert "contains no `[FAIL]` line" in power_platform

    install = (
        _SOLUTION
        / "src"
        / "skills"
        / "setup"
        / "workday-da"
        / "install-extension.md"
    ).read_text(encoding="utf-8")
    assert "sidecarDataverseEndpoint" in install
    assert '--connect-config ".local/connect/workday-da/config.json"' in install

    verify = (
        _SOLUTION
        / "src"
        / "skills"
        / "setup"
        / "workday-da"
        / "verify-connection.md"
    ).read_text(encoding="utf-8")
    assert '--connect-config ".local/connect/workday-da/config.json"' in verify
    assert "sidecarDataverseEndpoint" in power_platform


def test_hybrid_boundary_remains_non_mutating() -> None:
    text = _BOUNDARY.read_text(encoding="utf-8")

    assert "Hybrid Workday extension setup is not available" in text
    assert "Do not run the retained Workday setup playbooks" in text
    assert "no Dataverse environment, solution, connection" in text
    for playbook in _WORKDAY_PLAYBOOKS:
        assert playbook not in text


def test_retained_legacy_playbooks_are_not_directly_routed() -> None:
    playbook_dir = _SOLUTION / "src" / "skills" / "setup" / "workday"
    boundary = _BOUNDARY.read_text(encoding="utf-8")
    connect = _CONNECT_SKILL.read_text(encoding="utf-8")
    step1 = _CONNECT_STEP1.read_text(encoding="utf-8")

    for playbook in _WORKDAY_PLAYBOOKS:
        assert (playbook_dir / playbook).is_file(), playbook
        assert playbook not in boundary
        assert playbook not in connect
        assert playbook not in step1


def test_retired_workday_prompt_remains_absent() -> None:
    assert not _OLD_PROMPT.exists()
