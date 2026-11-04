# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Command integration alongside the existing unavailable action provider."""

import json
from pathlib import Path

SOLUTION = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills"


def test_knowledge_registration_and_alias_are_separate_from_actions():
    providers = SOLUTION / "src" / "skills" / "connect"
    knowledge = json.loads(
        (providers / "servicenow-kb" / "integration.json").read_text(encoding="utf-8")
    )
    actions = json.loads(
        (providers / "servicenow" / "integration.json").read_text(encoding="utf-8")
    )
    assert knowledge["availability"] == "available"
    assert actions["availability"] == "unavailable"
    assert not (set(knowledge["aliases"]) & ({"servicenow"} | set(actions["aliases"])))
    for key in ("entryDoc", "statusDoc"):
        assert (providers / "servicenow-kb" / knowledge[key]).is_file()


def test_alias_routes_before_setup_and_is_publicly_discoverable():
    prompt = (
        SOLUTION / ".github" / "prompts" / "connect-servicenow-kb.prompt.md"
    ).read_text(encoding="utf-8")
    assert "`servicenow-kb` supplied" in prompt
    assert "connect.prompt.md" in prompt
    instructions = (SOLUTION / ".github" / "copilot-instructions.md").read_text(
        encoding="utf-8"
    )
    assert instructions.index("typed `/connect-servicenow-kb`") < instructions.index(
        "### Setup gate"
    )
    for path in (
        SOLUTION / ".github" / "prompts" / "menu.prompt.md",
        SOLUTION / "README.md",
    ):
        assert "| `/connect-servicenow-kb` |" in path.read_text(encoding="utf-8")


def test_guidance_keeps_remote_and_acl_evidence_boundaries_explicit():
    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    assert "both flows" in (provider / "shared.md").read_text(encoding="utf-8")
    assert "does not prove universal ACL parity" in skill
    assert "schema creation" in skill
    assert "Only people with access to this data source" in skill
    assert "EXT-002-ACL" in skill
    assert "Everyone" in skill
    assert "cross-machine progress sync" in skill


def test_maker_questions_have_two_flows_and_no_hrsd_prompt():
    skill = (
        SOLUTION / "src" / "skills" / "connect" / "servicenow-kb" / "SKILL.md"
    ).read_text(encoding="utf-8")
    choices = skill.split("must show exactly two explicit choices:", 1)[1].split(
        'Do not offer "Unknown"', 1
    )[0]
    assert [
        line.split("**")[1] for line in choices.splitlines() if line.startswith("- **")
    ] == [
        "Simple",
        "Advanced",
    ]
    assert "Do not ask the maker whether the scope includes HRSD content" in skill
    example = skill.split(r"python scripts\servicenow_kb_connect.py start", 1)[1].split(
        "```", 1
    )[0]
    assert "--hr-content" not in example
    assert "**HR scoped reads** guided check" in skill


def test_each_guided_configuration_step_has_a_walkthrough_without_excel_commands():
    import servicenow_kb_contracts as contracts

    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    for flow in ("simple", "advanced"):
        for step in contracts.configuration_steps({"flow": flow}):
            assert f"\n## {step['id']}\n" in walkthrough
    assert ".xlsx" not in skill
    assert " import-handoff " not in skill
    assert " handoff --owner " not in skill
    assert " confirm --step " in skill
    assert "Do not run confirmations in a prefilled" in skill
    assert "obtain explicit approval" in skill.lower()


def test_guidance_does_not_ask_for_date_after_current_assessment():
    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    assert "Do not ask for an\nassessment completion date" in skill
    assert "automatically records its UTC date" in skill
    assert "**Automatic bookkeeping, not a normal user question.**" in walkthrough


def test_guidance_avoids_extra_notes_and_introduces_federated_auth_before_object_id():
    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    assert 'Do not add an optional "Non-secret findings or blocker" question' in skill
    assert "if it fails\nor is blocked, report that explicitly" in skill
    assert "Before requesting the `service-principal` Object ID" in skill
    principal = walkthrough.split("\n## service-principal\n", 1)[1].split(
        "\n## oidc-provider\n", 1
    )[0]
    assert principal.index("Next, we'll configure Federated Auth") < principal.index(
        "Open Microsoft Entra admin center"
    )
    assert "not an Entra app registration's" in principal
    assert "scope.target.tenantId" in principal
    assert "environment.tenant_id" in principal
    assert "integration user's User ID" in principal
    assert "**Add filters > Application ID > starts with**" in principal
    assert "Do not enter the tenant ID in application search" in principal
    assert "select **Overview**, and copy **Object ID**" in principal


def test_every_user_facing_step_uses_act_then_verify_without_bypassing_approval():
    import servicenow_kb_contracts as contracts

    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    status = (provider / "status.md").read_text(encoding="utf-8")
    for flow in ("simple", "advanced"):
        for step in contracts.configuration_steps({"flow": flow}):
            section = walkthrough.split(f"\n## {step['id']}\n", 1)[1].split("\n## ", 1)[
                0
            ]
            if step["id"] == "assessment-date":
                assert (
                    "**Automatic bookkeeping, not a normal user question.**" in section
                )
                assert "**Act:**" not in section
                continue
            assert section.index("**Act:**") < section.index("**Verify:**")
    assert "Create or verify the ServiceNow integration user" in skill
    assert "Do not begin with a matching questionnaire" in skill
    assert "guide the authorized user directly" in skill
    assert (
        "Failed verification leads to targeted correction and re-verification" in skill
    )
    assert "For read-only steps, Act\n   means inspect, retrieve" in skill
    assert "**Act**, then **Verify**" in status
    assert "Reuse healthy setup without repeating writes" in status


def test_missing_manual_setup_items_do_not_trigger_an_extra_approval_question():
    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    assert 'Do not ask a separate\n   "Do you want to add it?"' in skill
    assert "Honor required administrator authorization" in skill
    assert "Obtain explicit approval for actions outside the approved scope" in skill
    assert "does not authorize assistant-made remote writes" in skill
    roles = walkthrough.split("\n## integration-roles\n", 1)[1].split(
        "\n## table-reads\n", 1
    )[0]
    assert "If the user reports no roles, guide **Roles > Edit**" in roles
    assert 'Do not insert an "Approval for documented roles" questionnaire' in roles
    assert "resolve that actual prerequisite" in roles
    assert roles.index("If the user reports no roles") < roles.index("**Verify:**")


def test_existence_check_precedes_configuration_and_is_not_checkpoint_evidence():
    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    status = (provider / "status.md").read_text(encoding="utf-8")
    assert "Do not mix creation instructions" in skill
    assert "**Yes**, **No**,\nand **I can't check**, all initially unset" in skill
    assert "do not pass Yes/No to `confirm`" in skill
    assert "First-party Entra application absence remains a blocker" in skill
    assert "Do not add this question to read-only diagnostics or completed" in skill
    assert "current-scope answer already supplied" in status
    for step in ("oidc-provider", "integration-user", "advanced-api"):
        section = walkthrough.split(f"\n## {step}\n", 1)[1].split("\n## ", 1)[0]
        assert section.index("**Check existence:**") < section.index("**Act:**")
        assert section.index("**Act:**") < section.index("**Verify:**")
        assert "For **Yes**" in section
        assert "For **No**" in section
    oidc = walkthrough.split("\n## oidc-provider\n", 1)[1].split("\n## ", 1)[0]
    check = oidc.split("**Act:**", 1)[0]
    assert "**Does this registration exist?**" in check
    assert "Client ID `933838e2-bec1-440f-a634-9363c82e5b6d`" in check
    assert "**I can't check**" in check
    assert "For **No**, guide **New**" in oidc
    assert "No means guide creation below" in check


def test_workday_style_walkthrough_is_visible_before_the_scope_result_question():
    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    status = (provider / "status.md").read_text(encoding="utf-8")
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    assert "numbered walkthrough as a visible chat message before" in skill
    assert "do not bury the walkthrough inside a long question detail" in skill
    assert "Keep Act / Verify labels, checkpoint IDs" in skill
    assert "Ask one concise result question after the walkthrough" in skill
    assert (
        "numbered walkthrough in visible chat before its short result question"
        in status
    )
    scope = walkthrough.split("\n## scope-assessment\n", 1)[1].split("\n## ", 1)[0]
    assert scope.index("1. Open the saved ServiceNow instance") < scope.index(
        "**Did the review confirm"
    )
    assert "**All > Knowledge > Administration >\n   Knowledge Bases**" in scope
    assert "inspect **Advanced**" in scope
    assert "inspect the **Script** field" in scope
    assert "inspect their **Can Read**\n   and **Cannot Read** fields" in scope
    assert "all pages of each list" in scope
    assert "do not interpret\n   hidden fields as no restrictions" in scope
    assert "The review is incomplete; help me finish it" in scope
    assert "An unsuitable or incomplete\nreview does not pass" in scope


def test_oidc_walkthrough_supplies_names_and_does_not_reuse_unrelated_defaults():
    walkthrough = (
        SOLUTION / "src" / "skills" / "connect" / "servicenow-kb" / "configuration.md"
    ).read_text(encoding="utf-8")
    oidc = walkthrough.split("\n## oidc-provider\n", 1)[1].split("\n## ", 1)[0]
    assert "| Name | `Microsoft Entra ID` |" in oidc
    assert "| Provider name | Select **Microsoft** from the dropdown |" in oidc
    assert "do not ask the user to enter a custom provider label" in oidc
    assert "OIDC provider / OIDC provider name" in oidc
    assert "**Create a new configuration**" in oidc
    assert "Do not accept an unrelated preselected configuration" in oidc
    assert "or edit that shared configuration" in oidc
    assert "actual saved tenant ID, not the placeholder" in oidc
    assert "| User field | `User ID`, not the default Email |" in oidc
    assert "| OIDC configuration cache lifespan (hours) | `120` |" in oidc


def test_first_time_permissions_are_configured_before_the_separate_validation_phase():
    import servicenow_kb_contracts as contracts

    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    setup = walkthrough.split("\n## permission-setup\n", 1)[1].split("\n## ", 1)[0]
    assert "save role assignments and any specifically identified" in setup
    assert "**Type = record**, **Operation = read**" in setup
    assert "**Requires role / Roles**" in setup
    assert "**sn_hr_core.content_reader**" in setup
    assert "Do not add blanket **table.*** field ACLs" in setup
    assert "**Permissions configured; access tests pending**" in setup
    assert "Do not record Common table reads" in setup
    assert "Do not start Access Analyzer or a read-test questionnaire here" in skill
    for flow in ("simple", "advanced"):
        ids = [step["id"] for step in contracts.configuration_steps({"flow": flow})]
        assert ids.index("integration-roles") < ids.index("permission-setup")
        assert ids.index("permission-setup") < ids.index("federated-auth")
        for check in (
            "table-reads",
            "property-reads",
            "hr-reads",
            "simple-reads" if flow == "simple" else "advanced-security",
        ):
            assert ids.index(check) < ids.index("federated-auth")


def test_simple_guidance_is_standalone_and_does_not_require_the_advanced_custom_role():
    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    roles = walkthrough.split("\n## integration-roles\n", 1)[1].split("\n## ", 1)[0]
    simple = roles.split("For **Simple**", 1)[1].split("For **Advanced**", 1)[0]
    assert "A custom connector role is not a mandatory Simple prerequisite" in simple
    assert (
        "Do not import\nthe role or ACL script from our previous Advanced setup"
        in simple
    )
    assert "copilot_connector" not in simple
    assert "Do not require `copilot_connector` or another custom" in skill
    setup = walkthrough.split("\n## permission-setup\n", 1)[1].split("\n## ", 1)[0]
    assert (
        "Show this manual ACL procedure only for an additional required grant" in setup
    )
    reads = walkthrough.split("\n## table-reads\n", 1)[1].split("\n## ", 1)[0]
    assert "omit the associated-content rows unless" in reads
    assert "not the default Simple instructions" in setup


def test_simple_role_confirmation_defers_table_review_and_keeps_actions_in_chat():
    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    setup = walkthrough.split("\n## permission-setup\n", 1)[1].split("\n## ", 1)[0]
    simple = setup.split("**Default Simple path:**", 1)[1].split(
        "Show this manual ACL procedure", 1
    )[0]
    assert "**Roles > Edit**" in simple
    assert "required READ access not yet verified" in simple
    assert "Reuse a current-scope confirmation" in simple
    assert "Have the three role assignments been saved?" in setup
    assert "Have the required role assignments and read grants been saved?" not in setup
    assert "| Purpose | Tables |" not in setup
    assert "granting-table-access-servicenow-knowledge" not in setup
    assert "**All > User Administration > Roles > New**" in setup
    assert "**All > System Security > Access Control (ACL)**" in setup
    assert "**Type = record**, **Operation = read**" in setup
    reads = walkthrough.split("\n## table-reads\n", 1)[1].split("\n## ", 1)[0]
    assert "| Purpose | Tables |" in reads
    assert "guide the applicable approved correction" in reads
    assert "inline, then retest" in reads


def test_custom_setup_authorizes_before_create_without_bypassing_runtime_checks():
    import servicenow_kb_contracts as contracts

    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    assert "This draft authorization is necessary" not in skill
    assert "After draft authorization" not in skill
    assert (
        "do not assume an authenticated gallery session exists before Create" in skill
    )
    draft = walkthrough.split("\n## federated-auth\n", 1)[1].split("\n## ", 1)[0]
    assert "choose **Custom setup**" in draft
    assert "Select **Authorize** in Custom setup" in draft
    assert "Did Authorize succeed for these connection settings?" in draft
    assert "**Succeeded / Failed / I can't verify**" in draft
    assert "Do not continue on a failure" in draft
    assert "If Authorize is unexpectedly absent" in draft
    assert "pause and inspect the actual Custom setup screen" in draft
    assert "do not\nask whether authentication and sample fetch" in draft
    assert "portal separately displays it" in draft
    assert (
        "settings-only confirmation does not establish authorization success" in draft
    )
    assert (
        draft.index("Select **Authorize**")
        < draft.index("After authorization succeeds")
        < draft.index("Select **Create**")
    )
    assert "no pre-Create\nauthorization/validation" not in skill
    creation = walkthrough.split("\n## connection-name\n", 1)[1].split("\n## ", 1)[0]
    assert "Custom setup's **Authorize** succeeded" in creation
    assert "settings-only confirmation is not proof" in creation
    assert "Custom setup > Authorize" in contracts.COMMON_FIELDS["Federated Auth"][1]
    resume = (provider / "status.md").read_text(encoding="utf-8")
    assert "even when the configuration checkpoint was already" in resume
    assert "Do not recreate an existing connection" in resume
    shared = (provider / "shared.md").read_text(encoding="utf-8")
    assert "**Custom setup > Authorize** before Create" in shared
    ready = walkthrough.split("\n## connection-ready\n", 1)[1].split("\n## ", 1)[0]
    assert (
        "verify actual operation after Create for the recorded connection name" in ready
    )
    assert "**Statistics** and **Error**" in ready
    assert "known expected records" in ready
    assert "--connection-name" in ready
    assert "grouped legacy Ready flag" in ready
    assert "retain the recorded connection name" in ready
    for flow in ("simple", "advanced"):
        steps = contracts.configuration_steps({"flow": flow})
        ids = [step["id"] for step in steps]
        assert ids.index("federated-auth") < ids.index("connection-name")
        assert ids.index("connection-name") < ids.index("connection-ready")
        assert ids.index("connection-ready") < ids.index("test-article")
        assert next(step for step in steps if step["id"] == "connection-ready")[
            "checkpoint"
        ]


def test_source_checks_precede_the_uninterrupted_connector_wizard():
    import servicenow_kb_contracts as contracts

    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    assert "These must pass before opening the connector wizard" in skill
    draft = walkthrough.split("\n## federated-auth\n", 1)[1].split("\n## ", 1)[0]
    assert "Do not interrupt this wizard for Access" in draft
    assert "continue directly through content/mappings" in draft
    assert "do not select **Create** here" not in draft
    for flow in ("simple", "advanced"):
        ids = [step["id"] for step in contracts.configuration_steps({"flow": flow})]
        source_checks = (
            "table-reads",
            "property-reads",
            "hr-reads",
            "simple-reads" if flow == "simple" else "advanced-security",
        )
        for check in source_checks:
            assert ids.index(check) < ids.index("federated-auth")
            assert walkthrough.index(f"\n## {check}\n") < walkthrough.index(
                "\n## federated-auth\n"
            )
        assert ids[ids.index("federated-auth") : ids.index("connection-name") + 1] == [
            "federated-auth",
            "connector-config",
            "source-permissions",
            "audience",
            "schedules",
            "connection-name",
        ]


def test_index_and_permission_checks_finish_before_switching_to_ess():
    import servicenow_kb_contracts as contracts

    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    expected = [
        "connection-ready",
        "test-article",
        "test-kb",
        "article-indexed",
        "allowed-native",
        "allowed-indexed",
        "denied-native",
        "denied-indexed",
        "source-attached",
        "source-isolated",
        "answer-citation",
        "observation-time",
    ]
    for flow in ("simple", "advanced"):
        ids = [step["id"] for step in contracts.configuration_steps({"flow": flow})]
        assert ids[ids.index("connection-ready") :] == expected
    assert [walkthrough.index(f"\n## {step}\n") for step in expected] == sorted(
        walkthrough.index(f"\n## {step}\n") for step in expected
    )
    indexed = walkthrough.split("\n## article-indexed\n", 1)[1].split("\n## ", 1)[0]
    assert "do not\nmove to ESS attachment as a workaround" in indexed
    attachment = walkthrough.split("\n## source-attached\n", 1)[1].split("\n## ", 1)[0]
    assert (
        "after indexed-content and allowed/denied permission verification" in attachment
    )
    resume = (provider / "status.md").read_text(encoding="utf-8")
    assert "resume the earliest pending index check" in resume
    assert "do not\ninterpret existing attachment as passed indexing" in resume
    skill = (provider / "SKILL.md").read_text(encoding="utf-8")
    assert "Finish connector/index verification before opening ESS" in skill
    shared = (provider / "shared.md").read_text(encoding="utf-8")
    assert "checks before opening ESS" in shared


def test_ess_connection_name_is_reused_without_requesting_a_technical_id():
    import servicenow_kb_contracts as contracts

    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    creation = walkthrough.split("\n## connection-name\n", 1)[1].split("\n## ", 1)[0]
    assert "What connection name\nwill you select in ESS Knowledge?" in creation
    assert "do not ask the user to enter it again" in creation
    assert "Do not request a technical Connection ID" in creation
    assert "multiple connections have the same name" in creation
    attachment = walkthrough.split("\n## source-attached\n", 1)[1].split("\n## ", 1)[0]
    assert "by the saved connection name" in attachment
    assert "Show\nthat name" in attachment
    assert "do not ask for a Connection ID" in attachment
    assert "Connection name" in contracts.M365_FIELDS
    assert "Connection ID" not in contracts.M365_FIELDS
    resume = (provider / "status.md").read_text(encoding="utf-8")
    assert "Never infer the name from the\nID" in resume
    assert "does\nnot erase historical checks" in resume


def test_integration_user_name_is_shown_and_used_for_access_checks():
    walkthrough = (
        SOLUTION / "src" / "skills" / "connect" / "servicenow-kb" / "configuration.md"
    ).read_text(encoding="utf-8")
    user = walkthrough.split("\n## integration-user\n", 1)[1].split("\n## ", 1)[0]
    assert "**Name (display name)** alongside **User ID**" in user
    assert "do not infer a name" in user
    assert "rename a healthy existing user" in user
    reads = walkthrough.split("\n## table-reads\n", 1)[1].split("\n## ", 1)[0]
    assert "**Select user**, use the verified" in reads
    assert "names need not be unique" in reads
    assert "reopen the user\nby its exact User ID" in reads


def test_property_access_checks_precede_warning_and_explicit_continuation_choice():
    provider = SOLUTION / "src" / "skills" / "connect" / "servicenow-kb"
    walkthrough = (provider / "configuration.md").read_text(encoding="utf-8")
    properties = walkthrough.split("\n## property-reads\n", 1)[1].split("\n## ", 1)[0]
    assert "glide.knowman.apply_article_read_criteria" in properties
    assert "glide.knowman.block_access_with_no_user_criteria" in properties
    assert "silently defaults both settings to `true`" in properties
    assert "blocks articles without explicit" in properties
    assert "no error shown in the admin" in properties
    assert "Consult your ServiceNow administrator" in properties
    assert "**Select field = Name (`name`)**" in properties
    assert "**Select field = Value (`value`)**" in properties
    assert "actual name and User ID" in properties
    assert "Can the integration user read name and value" in properties
    assert "If all reads pass, record `confirmed`" in properties
    assert "Do not show the missing-access" in properties
    assert "record `unreadable`" in properties
    assert "record `unverified`; do not call it blocked" in properties
    assert "Would you like to continue setup without this access?" in properties
    assert "only after an explicit\nYes to this separate question" in properties
    assert "No pauses setup at this step" in properties
    assert "silence, cancellation or No is not consent" in properties
    assert (
        properties.index("**Select field = Name")
        < properties.index("**Verify:**")
        < properties.index("> **Permission-property access warning")
        < properties.index("**Would you like to continue")
    )
    common = walkthrough.split("\n## table-reads\n", 1)[1].split("\n## ", 1)[0]
    assert "hidden requirement of this common-table confirmation" in common
    status = (provider / "status.md").read_text(encoding="utf-8")
    assert "Display returned `warnings`" in status
    assert "even if representative guided validation" in status
    assert "automatic deferral, not consent" in status
