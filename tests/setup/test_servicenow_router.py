# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural consistency guard for the ServiceNow setup orchestrator (router)
and the ``/connect servicenow`` entry point that reaches it.

Pure-logic, no network (see ``tests/AGENTS.md`` — pure-logic helpers are exempt
from the cassette rule). Mirrors ``test_setup_router.py`` (Workday) for the
ServiceNow orchestrator introduced when ``/connect servicenow`` was migrated
from the monolithic ``connect/servicenow/stepN`` flow to the Workday-style
setup orchestrator.

The router ``src/skills/setup/servicenow/SKILL.md`` is a Message-block
dispatcher reached via ``/connect servicenow`` (its ServiceNow branch in
``connect/step1.md`` delegates here). If a routed playbook path drifts
(renamed/typo'd playbook, moved template) the orchestrator silently dead-ends
at setup time. This test pins the router's wiring so drift is caught at CI time.
"""

from __future__ import annotations

from pathlib import Path

# tests/setup/test_servicenow_router.py -> repo root is parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_SN = _SOLUTION / "src" / "skills" / "setup" / "servicenow"
_ROUTER = _SN / "SKILL.md"
_TASKS = _SN / "tasks.md"
_CONNECT_STEP1 = _SOLUTION / "src" / "skills" / "connect" / "step1.md"
_CONNECT_SKILL = _SOLUTION / "src" / "skills" / "connect" / "SKILL.md"

# Every playbook the router must dispatch to, keyed by the Step-ID group it owns.
_PLAYBOOKS = {
    "S1.1/S1.2": "provision-power-platform-environment.md",
    "S2.1": "install-ess.md",
    "S3.1-S3.3": "capture-servicenow-config.md",
    "S4.1-S4.4 (entra_user)": "provision-servicenow-entra-user.md",
    "S5.1-S5.3 (entra_certificate)": "provision-servicenow-certificate.md",
    "S6.1-S6.4": "install-servicenow-extension-pack.md",
    "S7.1/S7.2": "validate-and-handoff.md",
}


class TestServiceNowRouter:
    def test_router_exists(self):
        assert _ROUTER.is_file(), f"missing ServiceNow setup router: {_ROUTER}"

    def test_tasks_checklist_exists(self):
        assert _TASKS.is_file(), f"missing ServiceNow tasks checklist: {_TASKS}"

    def test_connect_servicenow_branch_routes_to_orchestrator(self):
        # /connect servicenow no longer runs a connect/servicenow/ monolith —
        # its ServiceNow branch delegates to the setup orchestrator.
        text = _CONNECT_STEP1.read_text(encoding="utf-8")
        assert "src/skills/setup/servicenow/SKILL.md" in text, (
            "connect/step1.md ServiceNow branch must route to the ServiceNow "
            "setup orchestrator"
        )

    def test_connect_skill_routes_servicenow_to_orchestrator(self):
        skill = _CONNECT_SKILL.read_text(encoding="utf-8")
        assert "src/skills/setup/servicenow/SKILL.md" in skill, (
            "connect/SKILL.md must route ServiceNow to its setup orchestrator"
        )

    def test_connect_servicenow_monolith_removed(self):
        # The connect/servicenow/ step monolith was retired when ServiceNow
        # moved to the setup orchestrator (matching the Workday migration).
        monolith = _SOLUTION / "src" / "skills" / "connect" / "servicenow"
        assert not monolith.exists(), (
            "the connect/servicenow/ monolith must be deleted"
        )
        skill = _CONNECT_SKILL.read_text(encoding="utf-8")
        step1 = _CONNECT_STEP1.read_text(encoding="utf-8")
        assert "connect/servicenow/step" not in skill, (
            "connect/SKILL.md must not reference the retired monolith step files"
        )
        assert "connect/servicenow/step" not in step1, (
            "connect/step1.md must not reference the retired monolith step files"
        )

    def test_router_dispatches_to_every_playbook(self):
        text = _ROUTER.read_text(encoding="utf-8")
        for group, filename in _PLAYBOOKS.items():
            playbook = _SN / filename
            assert playbook.is_file(), (
                f"missing ServiceNow playbook for {group}: {playbook}"
            )
            assert f"src/skills/setup/servicenow/{filename}" in text, (
                f"router must dispatch {group} to {filename}"
            )

    def test_router_renders_auth_path_variant(self):
        # Groups 4 (entra_user) and 5 (entra_certificate) are mutually
        # exclusive; the router reads authType from the durable config and
        # renders only the matching group.
        text = _ROUTER.read_text(encoding="utf-8")
        assert "authType" in text, (
            "router must read authType to select the auth-path variant"
        )
        assert "entra_user" in text and "entra_certificate" in text, (
            "router must handle both entra_user and entra_certificate auth paths"
        )

    def test_router_never_automates_servicenow_oidc(self):
        # Spec constraint: the agent must never automate ServiceNow-internal
        # OIDC (S4.3/S4.4/S5.3 are attest-only rows).
        text = _ROUTER.read_text(encoding="utf-8")
        assert "attest" in text, (
            "router must mark the ServiceNow-side OIDC rows as attest-only"
        )
