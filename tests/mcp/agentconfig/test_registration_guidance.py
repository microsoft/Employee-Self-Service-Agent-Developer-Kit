# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline guards for landing-page scope choice and verified local persistence."""

from pathlib import Path

import pytest


SKILLS = (
    Path(__file__).resolve().parents[3]
    / "solutions" / "ess-maker-skills" / "src" / "skills"
)


def _section(text, heading):
    start = text.index(f"## {heading}")
    end = text.find("\n## ", start + len(heading) + 3)
    return " ".join((text[start:] if end == -1 else text[start:end]).split())


@pytest.fixture
def reference():
    return (SKILLS / "shared" / "agent-title-resolution.md").read_text(encoding="utf-8")


def test_landing_identity_discovery_is_separate_from_configuration_creation():
    skill = (SKILLS / "landing-page-config" / "SKILL.md").read_text(encoding="utf-8")
    resolve = _section(skill, "Resolve the target")
    persist = _section(skill, "Persist a discovered title ID")
    delete = _section(skill, "Delete all landing-page configuration")
    assert "src/skills/shared/agent-title-resolution.md" in resolve
    assert "`ess-landing-page-config`" in resolve
    assert "call `get_agent_config` once with the chosen ID" in resolve
    assert "Do not call `list_agent_configs` or `search_agents`" in resolve
    assert "GUID exactly after normalization" in persist
    assert "reject conflicting active markers" in persist
    assert "never fabricate a partial agent" in persist
    assert "Complete any regular/LOB choice and the verified persistence gate" in delete
    assert "Missing registration is not evidence that defaults are active" in delete
    assert "Obtain explicit confirmation immediately before the delete call" in delete


def test_scope_selection_preserves_explicit_verified_and_cached_precedence(reference):
    identity = _section(reference, "Identity and cache")
    choose = _section(reference, "Resolve and choose")
    assert "top-level `titleId` is the **selected scope**" in identity
    assert "an intentionally supplied scope ID wins" in identity
    assert "An explicit Regular/LOB request takes precedence over a stored selection" in identity
    assert "Never treat a pasted pair of metadata values as an implicit selection" in identity
    assert "a verified conversation choice for the same bot and ID" in choose
    assert "do not force discovery merely to reopen an established scope" in choose
    assert "If both IDs are available and different, ask the maker" in choose
    assert "If both fields contain the same ID" in choose
    assert "Never silently fall back to the other registration" in choose
    assert "never as a new opener parameter" in choose


def test_needed_lob_choice_is_explained_without_guessing_a_deployment_channel(reference):
    explain = _section(reference, "Explain the registration choice")
    assert "**LOB** as **line-of-business**" in explain
    assert "two Microsoft 365 app registrations of the same agent" in explain
    assert "not different bots or audience groups" in explain
    assert "not automatically applied to the other" in explain
    assert "Do not guess a deployment or distribution channel" in explain
    assert "does not require another question" in explain
    assert "an explicit, verified, or compatible cached selection already exists" in explain


def test_persistence_matches_guids_and_preserves_canonical_pair_and_active_markers(reference):
    persist = _section(reference, "Persistence gate")
    assert "normalizing both identifiers as GUIDs" in persist
    assert "Require exactly one match" in persist
    assert "Never persist by display name or by slug alone" in persist
    assert "copy that complete object into `agents`" in persist
    assert "GUID and environment have not changed during discovery" in persist
    assert "If active markers conflict" in persist
    assert "stop before writing" in persist
    assert "including JSON `null` for a known unavailable registration" in persist
    assert "Preserve the existing selected scalar until a scope has been chosen" in persist
    assert "leave `agent` and `activeAgent` unchanged" in persist
    assert "Do not change cached values after failed discovery" in persist
    assert "reread to verify both the selected entry and active mirror" in persist
    assert "neither may transfer to a different bot" in persist


def test_discovery_cannot_substitute_other_ids_or_guess_a_legacy_environment(reference):
    choose = _section(reference, "Resolve and choose")
    errors = _section(reference, "Errors and in-flight work")
    assert "Both registration keys are always returned" in choose
    assert "At least one ID must be available" in choose
    assert "Do not use `list_agent_configs`, `search_agents`, name search, MinimalBot" in choose
    assert "never an unbound non-active agent" in errors
    assert "own endpoint; never inherit another agent's binding" in errors
    assert "Never synthesize a title as `T_{botId}`" in errors
    assert "Interactive Dataverse sign-in is limited to 300 seconds" in errors
    assert "retries do not start another lookup until it finishes" in errors
