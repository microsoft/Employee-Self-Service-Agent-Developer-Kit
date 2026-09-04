# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural guards for landing-page suggestion routing."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
SKILL_PATH = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "landing-page-config"
    / "SKILL.md"
)


def _section(text: str, heading: str) -> str:
    start = text.index(f"## {heading}")
    end = text.find("\n## ", start + len(heading) + 3)
    return text[start:] if end == -1 else text[start:end]


def test_router_distinguishes_explore_preview_and_direct_update() -> None:
    route = _section(SKILL_PATH.read_text(encoding="utf-8"), "Route the request")
    hard_rules = _section(SKILL_PATH.read_text(encoding="utf-8"), "Hard rules")

    assert "with `titleId` only" in route
    assert route.count("with `titleId` and `draft`") == 3
    assert route.count("`update_agent_config` -> report success") == 3
    assert '"Set my accent color to blue"' in route
    assert '"Change my light accent color to `#CCAA00`"' in route
    assert '"Update my starter prompts"' in hard_rules
    assert '"Set my accent color to blue"' in hard_rules
    assert '"Add a quick link for xyz"' in hard_rules
    assert "collects any missing `displayText` and" in hard_rules
    assert "`address`" in hard_rules
    assert '"Delete my starter prompts"' in hard_rules
    assert "`pivots: []`" in hard_rules
    assert (
        '"Upload these starter prompts: <attached CSV or inline list>"'
        in hard_rules
    )
    assert "complete `pivots` wire schema" in hard_rules


def test_suggested_preview_merges_and_validates_complete_sections() -> None:
    preview = _section(
        SKILL_PATH.read_text(encoding="utf-8"),
        "Preview suggested changes",
    )

    assert "Build the complete replacement section" in preview
    assert "call `get_agent_config`" in preview
    assert "merge the requested" in preview
    assert "against the matching surface schema" in preview
    assert "validate Quick Links and Starter" in preview
    assert "Prompts directly from those schemas" in preview
    assert "For a Branding proposal only" in preview
    assert "`scripts/validate_branding.py`" in preview
    assert "discard it" in preview
    assert "compliant candidate, and validate again" in preview
    assert "Open the proposal only after every" in preview
    assert "generated color passes" in preview
    assert "Do not surface failed generated candidates as" in preview
    assert "warnings in chat" in preview
    assert "The opener performs one server read and does not write." in preview
    assert "Do not issue a model-driven update after opening" in preview


def test_capability_help_advertises_context_grounded_suggestions() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    setup = _section(text, "Setup-state check")
    capabilities = _section(text, "Describe landing-page capabilities")

    assert "what this skill can do do not require" in setup
    assert "suggest context-grounded changes" in capabilities
    assert "unpublished widget draft" in capabilities
    assert "configured topics, connected integrations, workflows" in capabilities
    assert "knowledge" in capabilities
    assert "evaluations" in capabilities
    assert "begin with guiding questions" in capabilities


def test_content_suggestions_gather_context_before_drafting() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    context = _section(text, "Gather context for suggested content")
    route = _section(text, "Route the request")
    preview = _section(text, "Preview suggested changes")

    for expected in (
        "Draft generation follows after the",
        "HR, IT, and Core agents",
        "`topics/*.mcs.yml`",
        "`triggerQueries`",
        "`modelDescription`",
        "`InvokeFlowAction`",
        "`BeginDialog`",
        "`snapshot.md`",
        "`workflows/`",
        "`connectionreferences.mcs.yml`",
        "`knowledge/*.mcs.yml`",
        "existing evaluation cases",
        "`.local/connect/servicenow/steps.md`",
        "`.local/connect/workday/config.json`",
        "`ootbTopics.selected`",
        "bundled Workday, ServiceNow, Facilities",
    ):
        assert expected in context

    assert route.count("gather agent context and ask guiding questions") == 2
    assert "complete **Gather context for suggested content** first" in preview


def test_guiding_questions_protect_dynamic_content_quality() -> None:
    context = _section(
        SKILL_PATH.read_text(encoding="utf-8"),
        "Gather context for suggested content",
    )

    assert "exact employee-facing HTTPS URL" in context
    assert "maker supplies it or it is" in context
    assert "already verified in the target's authored content" in context
    assert "Never use a Dataverse," in context
    assert "which capabilities to feature" in context
    assert "employees, managers, HR, IT, or a mixture" in context
    assert "Offer a concise set of" in context
    assert "context-derived options" in context
    assert "Do not expose source internals, credentials" in context


def test_branding_warns_only_for_exact_maker_supplied_colors() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    hard_rules = _section(text, "Hard rules")
    branding = _section(text, "Branding")

    assert "A generated color proposal must pass contrast validation" in hard_rules
    assert "Do not show the failed candidate or" in hard_rules
    assert "warn the maker about it" in hard_rules
    assert "maker supplies an exact color" in hard_rules
    assert "Call `update_agent_config` only after the maker confirms" in hard_rules
    assert "For a generated proposal, discard the candidate" in branding
    assert "Do not open the widget or warn the maker" in branding
    assert "For an exact color supplied by the maker" in branding
    assert "ask whether to apply that value" in branding
    assert "only after the maker confirms" in branding


def test_suggested_preview_pins_consumer_wire_shapes() -> None:
    preview = _section(
        SKILL_PATH.read_text(encoding="utf-8"),
        "Preview suggested changes",
    )

    for field in (
        '"branding"',
        '"theming"',
        '"name"',
        '"accentColor"',
        '"quickLinksConfig"',
        '"quickLinks"',
        '"displayText"',
        '"address"',
        '"pivots"',
        '"displayName"',
        '"conversationStarterPrompts"',
        '"title"',
    ):
        assert field in preview

    for excluded in (
        "`titleId`",
        "`hoverColor`",
        "`activeColor`",
        "`quickLinksConfig.lastUpdatedAt`",
        "widget row keys",
    ):
        assert excluded in preview

    assert '`draft: { "pivots": [] }`' in preview
    assert "without a draft over an empty" in preview


def test_descriptive_accent_requests_preserve_an_untouched_theme() -> None:
    branding = _section(
        SKILL_PATH.read_text(encoding="utf-8"),
        "Branding",
    )

    assert "synthesize complete" in branding
    assert "six-digit light and dark values" in branding
    assert "preserve the untouched theme" in branding
    assert "only `name` and `accentColor`" in branding
