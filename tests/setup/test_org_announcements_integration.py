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

    assert "one deployed ESS agent in the authenticated tenant" in skill
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
    feature = _normalized(_SKILL)
    skill = feature + " " + _normalized(_SHARED_TITLE_REFERENCE)

    assert "`0 = Important`; `1 = Informational`" in skill
    assert 'send `"priority": 1`; for Important, send `"priority": 0`' in skill
    assert "When a successful search returns nothing" in skill
    assert (
        "An unresolved audience does not block opening a requested review-only "
        "create editor." in skill
    )
    assert "omit `suggestedDraft.audience`" in skill
    assert "`ess-org-announcements`" in feature
    assert "src/skills/shared/agent-title-resolution.md" in feature
    assert "provider's read-only `resolve_agent_title_id`" in skill
    assert (
        "GET /api/data/v9.2/bots(<botId>)?$select=botid,applicationmanifestinformation"
        in skill
    )
    assert "`applicationmanifestinformation` JSON string" in skill
    assert "`microsoft365.titleId`" in skill
    assert "`microsoft365.lobTitleId`" in skill
    assert "returned `botid` matches the selected bot" in skill
    assert "legacy fallback only for the unambiguous active agent" in skill
    assert "never an unbound non-active agent" in skill
    assert "Interactive Dataverse sign-in is limited to 300 seconds" in skill
    assert "retries do not start another lookup until it finishes" in skill
    assert "AgentBuilderClient" not in skill
    assert "list_agent_configs" not in feature
    assert "search_agents" not in feature
    assert "RegistrationRequired" in skill
    assert "Authentication, authorization, network, and malformed-response failures" in skill
    assert "Never call `create_agent_config` or `update_agent_config`" in skill
    assert "ess-landing-page-config" not in feature


def test_title_resolution_preserves_explicit_cached_and_per_agent_persistence() -> None:
    skill = _normalized(_SHARED_TITLE_REFERENCE)

    assert "explicit/cached-ID precedence" in skill
    assert "intentionally supplied scope ID wins" in skill
    assert "stored selected `titleId`" in skill
    assert "Match the selected entry in `agents` by the returned `botId`" in skill
    assert "normalizing both identifiers as GUIDs" in skill
    assert "Require exactly one match" in skill
    assert "Never persist by display name or by slug alone" in skill
    assert "copy that complete object into `agents`" in skill
    assert "Also update `agent.registrationTitleIds` when the target is active" in skill
    assert "If active markers conflict" in skill
    assert "stop before writing" in skill
    assert "Preserve all other fields and agents" in skill
    assert "reread to verify both the selected entry and active mirror" in skill


def test_skill_discovers_a_complete_pair_and_requires_an_explicit_registration_choice():
    skill = _normalized(_SHARED_TITLE_REFERENCE)

    assert "A legacy cache containing only a top-level `titleId` does not prove" in skill
    assert "reuse a non-null cached ID for an explicitly requested Regular or LOB" in skill
    assert "JSON `null` means unavailable" in skill
    assert "including JSON `null` for a known unavailable registration" in skill
    assert "Never copy `lobTitleId` into the pair's `titleId` or vice versa" in skill
    assert "An explicit Regular/LOB request takes precedence over a stored selection" in skill
    assert "If the maker requested **Regular**, use the regular `titleId`" in skill
    assert "if they requested **LOB**, use `lobTitleId`" in skill
    assert "ask the maker to choose **Regular registration** or **LOB registration**" in skill
    assert "Do not open a view or issue a feature mutation until they choose" in skill
    assert "Never silently fall back to the other registration" in skill
    assert "Pass the chosen non-null value as the calling feature tool's `titleId`" in skill
    assert "When the agent or chosen registration ID changes" in skill
    assert "Keep `titleId` and `lobTitleId` outside `suggestedDraft`" in _normalized(_SKILL)
    assert "Do not infer registration from announcement content" in skill
    assert "Never treat a pasted pair of metadata values as an implicit selection" in skill
    assert "An explicitly chosen `lobTitleId` is passed as the opener's `titleId`" in skill


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
