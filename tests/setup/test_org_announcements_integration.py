# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural guards for Org Announcements entry points and CI wiring."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_REPO_INSTRUCTIONS = _REPO_ROOT / ".github" / "copilot-instructions.md"
_SETUP_README = _REPO_ROOT / "setup" / "README.md"
_PROFILE_README = _REPO_ROOT / "tools" / "ess-maker-profile" / "README.md"
_PROFILE_EXTENSION = (
    _REPO_ROOT / "tools" / "ess-maker-profile" / "extension" / "extension.js"
)
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_INSTRUCTIONS = _SOLUTION / ".github" / "copilot-instructions.md"
_MENU = _SOLUTION / ".github" / "prompts" / "menu.prompt.md"
_PROMPT = _SOLUTION / ".github" / "prompts" / "org-announcements.prompt.md"
_FOUNDATION = _SOLUTION / "src" / "skills" / "foundation-setup" / "SKILL.md"
_SKILL = _SOLUTION / "src" / "skills" / "org-announcements" / "SKILL.md"
_SHARED_TITLE_REFERENCE = (
    _SOLUTION / "src" / "skills" / "shared" / "agent-title-resolution.md"
)
_MCP_DEFAULTS = _SOLUTION / ".vscode" / "mcp.defaults.json"
_SCRIPT_REQUIREMENTS = _SOLUTION / "scripts" / "requirements.txt"
_FEATURE_REQUIREMENTS = (
    _SOLUTION
    / "src"
    / "mcp"
    / "agentconfig_org_announcements"
    / "requirements.txt"
)


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_prompt_routes_to_the_setup_gated_skill() -> None:
    prompt = _PROMPT.read_text(encoding="utf-8")
    skill = _normalized(_SKILL)

    assert "mode: agent" in prompt
    assert "src/skills/org-announcements/SKILL.md" in prompt
    assert (
        'If the file does not exist, or its `setup` value is not `"complete"`'
        in skill
    )
    assert (
        "Before using `/org-announcements`, type `/setup` to set up your "
        "environment." in skill
    )
    assert "mcp_config.py validate --server ess-org-announcements" in skill
    assert "mcp_config.py materialize-defaults" in skill


def test_skill_preserves_agent_scope_and_read_only_opening() -> None:
    skill = _normalized(_SKILL)

    assert "one deployed ESS agent registration in the authenticated tenant" in skill
    assert "required `titleId`" in skill
    assert "100-current-item limit and latest-50 archived window" in skill
    assert "never supply `tenantId` to a tool" in skill
    assert "at most once per maker turn" in skill
    assert "`open_org_announcements` reads only" in skill
    assert (
        "Do not call `save_bulletin`, `transition_bulletin`, or "
        "`duplicate_bulletin`" in skill
    )
    assert "Never infer that an announcement was created, saved, published" in skill


def test_skill_preserves_priority_audience_and_discovery_contracts() -> None:
    skill = _normalized(_SKILL)

    assert "`0 = Important`; `1 = Informational`" in skill
    assert 'send `"priority": 1`; for Important, send `"priority": 0`' in skill
    assert "When a successful search returns nothing" in skill
    assert (
        "An unresolved audience does not block opening a requested review-only "
        "create editor." in skill
    )
    assert "omit `suggestedDraft.audience`" in skill
    assert "`resolve_agent_title_id`" in skill
    assert "Do not use `list_agent_configs`, `search_agents`" in skill
    assert "Never call `create_agent_config` or `update_agent_config`" in skill
    assert "ess-landing-page-config" not in skill


def test_shared_title_guidance_preserves_cache_selection_and_strict_persistence():
    shared = _normalized(_SHARED_TITLE_REFERENCE)
    landing = _normalized(
        _SOLUTION / "src" / "skills" / "landing-page-config" / "SKILL.md"
    )
    announcements = _normalized(_SKILL)
    for skill in (landing, announcements):
        assert "src/skills/shared/agent-title-resolution.md" in skill
    for phrase in (
        "stored selected `titleId`",
        "An explicit Regular/LOB request takes precedence",
        "Never treat a pasted pair of metadata values as an implicit selection",
        "If both IDs are available and different",
        "If both fields contain the same ID",
        "Never silently fall back to the other registration",
        "normalizing both identifiers as GUIDs",
        "Require exactly one match",
        "If active markers conflict",
        "Preserve all other fields and agents",
        "Write valid JSON and reread to verify",
        "An explicitly chosen `lobTitleId` is passed as the opener's `titleId`",
        "Do not rewrite canonical setup state",
    ):
        assert phrase in shared
    assert "pair's regular identity" in announcements
    assert "Discovery does not establish that a landing-page configuration exists" in landing


def test_shared_title_guidance_pins_native_sources_and_explains_the_choice():
    shared = _normalized(_SHARED_TITLE_REFERENCE)
    for phrase in (
        "bot.teamsAppInformation.microsoft365.titleId",
        "channels/m365/publish?api-version=2024-10-01",
        "supplies the canonical `lobTitleId`, not the regular title",
        "Never POST `/publish`",
        "HTTP 404 as `NotFound`",
        "offline-tested, not live-established",
        "minimum endpoint permissions have not been established",
        "expand **LOB** as **line-of-business**",
        "two Microsoft 365 app registrations of the same agent",
        "changes for one are not automatically applied to the other",
        "Do not guess a deployment or distribution channel from the labels or IDs",
        "does not require another question when an explicit, verified, or compatible cached selection",
        "limited to 300 seconds",
        "leaves its lookup tracked until its worker finishes",
    ):
        assert phrase in shared
    assert "**LOB means line-of-business.**" in _normalized(_SOLUTION / "README.md")


def test_announcements_are_registered_across_current_entry_points() -> None:
    repo_instructions = _REPO_INSTRUCTIONS.read_text(encoding="utf-8")
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    menu = _MENU.read_text(encoding="utf-8")
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    setup_readme = _SETUP_README.read_text(encoding="utf-8")
    profile_readme = _PROFILE_README.read_text(encoding="utf-8")
    extension = _PROFILE_EXTENSION.read_text(encoding="utf-8")

    assert "`/org-announcements`" in repo_instructions
    assert '"Create an organization announcement"' in repo_instructions
    assert '"Post an announcement"' in repo_instructions
    assert "src/skills/org-announcements/SKILL.md" in instructions
    assert "`ess-org-announcements` MCP server" in instructions
    assert "`/org-announcements`" in menu
    assert "`/org-announcements`" in foundation
    assert "(Setup, Customize landing page, Post an announcement" in setup_readme
    assert "**Post an announcement**" in profile_readme
    assert "query: 'Create an organization announcement'" in extension
    assert "label: 'Post an announcement'" in extension


def test_runtime_dependencies_and_mcp_defaults_cover_announcements() -> None:
    defaults = json.loads(_MCP_DEFAULTS.read_text(encoding="utf-8"))
    scripts = _SCRIPT_REQUIREMENTS.read_text(encoding="utf-8")
    feature = _FEATURE_REQUIREMENTS.read_text(encoding="utf-8")

    server = defaults["servers"]["ess-org-announcements"]
    assert server["args"] == ["server.py"]
    assert server["cwd"].endswith("/src/mcp/agentconfig_org_announcements")
    for requirement in ("mcp>=", "httpx>=", "msal>="):
        assert requirement in scripts
        assert requirement in feature
    assert "-r ../src/mcp/agentconfig_core/requirements.txt" in scripts
    assert "-r ../agentconfig_core/requirements.txt" in feature


def test_ci_runs_announcements_separately_on_supported_targets() -> None:
    workflow = yaml.load(
        _WORKFLOW.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    expected_branches = ["main", "main-ca", "release/**"]
    assert workflow["on"]["push"]["branches"] == expected_branches
    assert workflow["on"]["pull_request"]["branches"] == expected_branches
    jobs = workflow["jobs"]
    assert "org-announcements" in jobs
    commands = "\n".join(
        step.get("run", "") for step in jobs["org-announcements"]["steps"]
    )
    assert "agentconfig_org_announcements/requirements.txt" in commands
    assert "tests/mcp/agentconfig_org_announcements" in commands
    assert "tests/setup/test_org_announcements_integration.py" in commands
