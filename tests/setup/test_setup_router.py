# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural consistency guard for the Workday setup orchestrator (router) and
the ``/connect workday`` entry point that reaches it.

Pure-logic, no network (see ``tests/AGENTS.md`` — pure-logic helpers are exempt
from the cassette rule). The router ``src/skills/setup/SKILL.md`` is a
Message-block dispatcher reached via ``/connect workday`` (its Workday branch in
``connect/step1.md`` delegates here; the standalone ``/setup-workday`` command was
retired). If a routed file path drifts (renamed/typo'd playbook, moved template)
the orchestrator silently dead-ends at setup time. This test pins the router's
wiring so that drift is caught at CI time instead.
"""

from __future__ import annotations

import re
from pathlib import Path

# tests/setup/test_setup_router.py -> repo root is parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_ROUTER = _SOLUTION / "src" / "skills" / "setup" / "SKILL.md"
_CONNECT_STEP1 = _SOLUTION / "src" / "skills" / "connect" / "step1.md"
_CONNECT_SKILL = _SOLUTION / "src" / "skills" / "connect" / "SKILL.md"
_OLD_PROMPT = _SOLUTION / ".github" / "prompts" / "setup-workday.prompt.md"
_WORKDAY_PROVIDER_DIR = _SOLUTION / "src" / "skills" / "connect" / "workday"
_TEMPLATE = _SOLUTION / "src" / "skills" / "setup" / "workday" / "tasks.md"
_SKILL1 = (
    _SOLUTION / "src" / "skills" / "setup" / "workday"
    / "provision-power-platform-environment.md"
)
_SKILL2 = (
    _SOLUTION / "src" / "skills" / "setup" / "workday" / "install-ess.md"
)
_SKILL3 = (
    _SOLUTION / "src" / "skills" / "setup" / "workday"
    / "provision-workday-entra-app.md"
)
_SKILL4 = (
    _SOLUTION / "src" / "skills" / "setup" / "workday"
    / "configure-workday-tenant.md"
)
_SKILL5 = (
    _SOLUTION / "src" / "skills" / "setup" / "workday"
    / "install-workday-extension-pack.md"
)
_SKILL6 = (
    _SOLUTION / "src" / "skills" / "setup" / "workday"
    / "create-new-topic.md"
)
_OOTB = (
    _SOLUTION / "src" / "skills" / "setup" / "workday"
    / "install-workday-ootb-topics.md"
)

# Backtick-quoted repo-relative markdown paths the router points at.
_PATH_RE = re.compile(r"`(src/skills/[^`]+?\.md)`")


class TestSetupRouter:
    def test_router_exists(self):
        assert _ROUTER.is_file(), f"missing setup router: {_ROUTER}"

    def test_connect_workday_branch_routes_by_architecture_and_install_state(self):
        # DA routes to setup; an installed CEA extension routes to the
        # provider lifecycle; a fresh CEA setup still routes to setup.
        text = _CONNECT_STEP1.read_text(encoding="utf-8")
        assert "src/skills/setup/SKILL.md" in text, (
            "connect/step1.md Workday branch must route to the setup orchestrator"
        )
        assert "src/skills/connect/workday/SKILL.md" in text, (
            "connect/step1.md must route an installed CEA extension to the "
            "provider lifecycle"
        )
        assert "WD-DA-PKG-001" in text
        assert "WD-PKG-001" in text
        assert "ESS IT Agent isn't supported" in text
        assert "Stop immediately" in text
        assert 'status: "ready"' in text
        assert "DA setup row through `DA5.1`" in text
        assert (
            "ServiceNow integration with an ESS Declarative Agent isn't supported"
            in text
        )
        assert "Do not create ServiceNow state" in text
        assert "Route by the resolved active agent's architecture" in text
        assert "active CEA agent" in text
        assert "DA and CEA products are" in text
        da_skill = (
            _SOLUTION / "src" / "skills" / "setup" / "workday-da" / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert "ESS IT Agent isn't supported" in da_skill
        assert "without creating or updating any Workday state" in da_skill
        assert "src/skills/setup/workday-da/configure-power-platform.md" in da_skill
        assert "DA4.1 through DA4.8" in da_skill
        assert "DA5.1" in da_skill
        assert "Show the readiness briefing" in da_skill
        assert "Entra Application Administrator" in da_skill
        assert "Workday Administrator" in da_skill
        assert "Dataverse System Administrator" in da_skill
        assert "InfoSec or network administrator" in da_skill
        assert "Workday test employee" in da_skill
        da_power_platform = (
            _SOLUTION
            / "src"
            / "skills"
            / "setup"
            / "workday-da"
            / "configure-power-platform.md"
        )
        assert da_power_platform.is_file()
        da_power_platform_text = da_power_platform.read_text(encoding="utf-8")
        assert "new_sharedworkdaysoap_ff0df" in da_power_platform_text
        assert "msviess_sharedcommondataserviceforapps_92b66" in da_power_platform_text
        assert "Allow permission to share parameters" in da_power_platform_text
        assert "Enable-CosmosDAFlowAuthorization.ps1" in da_power_platform_text
        assert "Do not translate, regenerate, or replace" in da_power_platform_text
        assert "with Python" in da_power_platform_text
        assert "brand-new environment" in da_power_platform_text
        assert "would create" in da_power_platform_text
        assert 'STEP_ID="DA4.6"' in da_power_platform_text
        assert 'CHECKPOINT_RESULT="PASSED"' in da_power_platform_text
        assert "connectionparametersetconfig" in da_power_platform_text
        assert "signed-in-user context" in da_power_platform_text
        assert "connect/workday/step" not in text, (
            "connect/step1.md must not reference the retired connect/workday monolith"
        )
        da_install = (
            _SOLUTION
            / "src"
            / "skills"
            / "setup"
            / "workday-da"
            / "install-extension.md"
        ).read_text(encoding="utf-8")
        assert "No ESS DA HR agent was found in this environment" in da_install
        assert (
            "The Workday extension package is not installed for the"
            in da_install
        )
        assert "Any other **`FAILED`** result" in da_install

    def test_setup_workday_command_removed(self):
        # The /setup-workday command was retired; /connect workday is the sole
        # entry point to the orchestrator.
        assert not _OLD_PROMPT.exists(), (
            "the /setup-workday prompt must be removed (retired command)"
        )

    def test_connect_workday_provider_uses_contract_not_step_monolith(self):
        assert (_WORKDAY_PROVIDER_DIR / "contract.json").is_file()
        assert (_WORKDAY_PROVIDER_DIR / "SKILL.md").is_file()
        assert not list(_WORKDAY_PROVIDER_DIR.glob("step*.md")), (
            "the provider lifecycle must not restore the retired step-file monolith"
        )
        skill = _CONNECT_SKILL.read_text(encoding="utf-8")
        assert "connect/workday/step" not in skill, (
            "connect/SKILL.md must not reference the retired monolith step files"
        )
        # ServiceNow routing must remain intact.
        assert "src/skills/connect/servicenow/" in skill, (
            "connect/SKILL.md must still route ServiceNow"
        )

    def test_router_dispatches_to_skill1_playbook(self):
        text = _ROUTER.read_text(encoding="utf-8")
        assert (
            "src/skills/setup/workday/provision-power-platform-environment.md" in text
        ), "router must dispatch S1.1/S1.2 to the skill-1 playbook"
        assert _SKILL1.is_file(), f"missing skill-1 playbook: {_SKILL1}"

    def test_router_dispatches_to_skill2_playbook(self):
        text = _ROUTER.read_text(encoding="utf-8")
        assert (
            "src/skills/setup/workday/install-ess.md" in text
        ), "router must dispatch S2.1 to the skill-2 install-ess playbook"
        assert _SKILL2.is_file(), f"missing skill-2 playbook: {_SKILL2}"
        # Every skill (S1-S6) is now wired: no not-available-yet stub remains.
        assert "not available yet" not in text, (
            "router must not carry a not-available-yet stub once skill-6 is wired"
        )

    def test_router_dispatches_to_skill3_playbook(self):
        text = _ROUTER.read_text(encoding="utf-8")
        assert (
            "src/skills/setup/workday/provision-workday-entra-app.md" in text
        ), "router must dispatch S3.1-S3.7 to the skill-3 Entra-app playbook"
        assert _SKILL3.is_file(), f"missing skill-3 playbook: {_SKILL3}"
        # S3.x must no longer be in the not-available-yet stub range.
        assert "S3.1 through S6.2 — not available yet" not in text, (
            "router stub range must start at S5.1 once skill-4 is wired"
        )

    def test_router_dispatches_to_skill4_playbook(self):
        text = _ROUTER.read_text(encoding="utf-8")
        assert (
            "src/skills/setup/workday/configure-workday-tenant.md" in text
        ), "router must dispatch S4.1-S4.4 to the skill-4 tenant playbook"
        assert _SKILL4.is_file(), f"missing skill-4 playbook: {_SKILL4}"
        # S4.x must no longer be in the not-available-yet stub range.
        assert "S4.1 through S6.2 — not available yet" not in text, (
            "router stub range must start at S5.1 once skill-4 is wired"
        )

    def test_router_dispatches_to_skill5_playbook(self):
        text = _ROUTER.read_text(encoding="utf-8")
        assert (
            "src/skills/setup/workday/install-workday-extension-pack.md" in text
        ), "router must dispatch S5.1-S5.8 to the skill-5 extension-pack playbook"
        assert _SKILL5.is_file(), f"missing skill-5 playbook: {_SKILL5}"
        # S5.x must no longer be in the not-available-yet stub range.
        assert "S5.1 through S6.2 — not available yet" not in text, (
            "router stub range must start at S6.1 once skill-5 is wired"
        )

    def test_router_dispatches_to_skill6_playbook(self):
        text = _ROUTER.read_text(encoding="utf-8")
        assert (
            "src/skills/setup/workday/create-new-topic.md" in text
        ), "router must dispatch S6.1-S6.3 to the skill-6 create-new-topic playbook"
        assert _SKILL6.is_file(), f"missing skill-6 playbook: {_SKILL6}"
        # skill-6 is the last skill: the not-available-yet stub must be gone.
        assert "not available yet" not in text, (
            "router must not carry a not-available-yet stub once skill-6 is wired"
        )

    def test_router_offers_optional_ootb_topics_between_skill5_and_skill6(self):
        # The optional ready-made-topics installer is offered after skill-5 and
        # before skill-6. It is an opt-in interstitial (not a tracked S-row),
        # gated by ootbTopics.state so a resumed setup never re-prompts.
        text = _ROUTER.read_text(encoding="utf-8")
        assert (
            "src/skills/setup/workday/install-workday-ootb-topics.md" in text
        ), "router must offer the optional OOTB-topics installer playbook"
        assert _OOTB.is_file(), f"missing OOTB installer playbook: {_OOTB}"
        assert "ootbTopics" in text, (
            "router must gate the optional offer on ootbTopics.state so it is "
            "not re-prompted after install/decline"
        )
        # The offer must sit between the skill-5 and skill-6 dispatch blocks.
        pack_idx = text.index("install-workday-extension-pack.md")
        ootb_idx = text.index("install-workday-ootb-topics.md")
        create_idx = text.index("create-new-topic.md")
        assert pack_idx < ootb_idx < create_idx, (
            "the OOTB-topics offer must appear after the skill-5 dispatch and "
            "before the skill-6 dispatch"
        )

    def test_ootb_offer_gated_on_persistent_state_not_transient_resume(self):
        # Regression: the offer used to be gated on the transient "first
        # non-done row is S6.1" resume condition, so once S6 completed the
        # offer was never shown again and was silently skipped in the S5->S6
        # handoff. It must instead be anchored to the persistent
        # ootbTopics.state flag in two places: (1) a gate at the S6 dispatch
        # entry (runs before skill-6), and (2) an All-done safety net for a
        # setup that reached S6 before the offer was ever shown.
        text = _ROUTER.read_text(encoding="utf-8")

        # (1) The S6 dispatch block gates on ootbTopics.state BEFORE it reads
        # the skill-6 playbook.
        s6_idx = text.index("### S6.1 through S6.3")
        create_idx = text.index("create-new-topic.md")
        s6_gate = text[s6_idx:create_idx]
        assert "ootbTopics.state" in s6_gate, (
            "the S6 dispatch block must run the OOTB offer gated on "
            "ootbTopics.state BEFORE reading create-new-topic.md, so the offer "
            "cannot be skipped in the S5->S6 handoff"
        )

        # (2) The All-done path rescues a setup that never saw the offer.
        done_idx = text.index("If **every** item is `done`")
        assert "ootbTopics" in text[done_idx:done_idx + 600], (
            "the All-done path must run the OOTB offer as a safety net when "
            "ootbTopics.state is unset, so a setup that reached S6 before the "
            "offer was shown still gets it"
        )

    def test_router_renders_from_template(self):
        text = _ROUTER.read_text(encoding="utf-8")
        assert "src/skills/setup/workday/tasks.md" in text, (
            "router must render the working copy from the checklist template"
        )
        assert _TEMPLATE.is_file(), f"missing checklist template: {_TEMPLATE}"

    def test_router_resumes_from_setupstatus(self):
        text = _ROUTER.read_text(encoding="utf-8")
        assert "setupStatus" in text, (
            "router must resume from setupStatus (durable source of truth)"
        )
        assert ".local/connect/workday/config.json" in text, (
            "router must read setupStatus from .local/connect/workday/config.json"
        )

    def test_router_uses_local_state_paths(self):
        # DD-CW5: state lives under .local/, never the plan's stale my/ prefix.
        text = _ROUTER.read_text(encoding="utf-8")
        assert ".local/setup/workday/tasks.md" in text
        assert "my/setup/workday" not in text

    def test_all_referenced_paths_resolve(self):
        text = _ROUTER.read_text(encoding="utf-8")
        referenced = set(_PATH_RE.findall(text))
        assert referenced, "router references no src/skills paths — wiring changed?"
        missing = [p for p in sorted(referenced) if not (_SOLUTION / p).is_file()]
        assert not missing, f"router references missing files: {missing}"

    def test_router_checklist_mirrors_template(self):
        # The router renders the resume checklist grouped exactly like the
        # template. Its Message block duplicates the template's group headings and
        # item titles, so pin parity: every heading/title in the template must
        # appear in the router, or the displayed checklist silently drifts.
        router = _ROUTER.read_text(encoding="utf-8")
        template = _TEMPLATE.read_text(encoding="utf-8")

        titles = re.findall(
            r"^- \[[ xX]\]\s+\*\*(.+?)\*\*\s+\u2014", template, re.MULTILINE
        )
        assert len(titles) == 25, (
            f"expected 25 item titles in template, parsed {len(titles)}"
        )
        missing_titles = [t for t in titles if t not in router]
        assert not missing_titles, (
            f"router checklist is missing item titles from the template: {missing_titles}"
        )

        headings = re.findall(r"^###\s+\d+\.\s+(.+?)\s*$", template, re.MULTILINE)
        assert headings, "no group headings parsed from the template"
        missing_headings = [h for h in headings if h not in router]
        assert not missing_headings, (
            f"router checklist is missing group headings from the template: {missing_headings}"
        )
