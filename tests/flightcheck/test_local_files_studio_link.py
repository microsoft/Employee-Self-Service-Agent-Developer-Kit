# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the Copilot Studio deep-link helpers in
``flightcheck.checks.local_files``.

These pin the CONFIG-007 remediation behavior the user surfaced: when a
check fails, the remediation must point the user directly at the
specific agent in Copilot Studio so they know where to click.

URL shape (verified against a live tenant in conversation):
    https://copilotstudio.microsoft.com/environments/{envId}/bots/{botId}/overview
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Make `flightcheck.*` importable from the kit's scripts dir."""
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "solutions" / "ess-maker-skills" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


def _fake_runner(env_id="env-guid-123", agents=None, single_agent=None):
    config = {}
    if agents is not None:
        config["agents"] = agents
    if single_agent is not None:
        config["agent"] = single_agent
    return SimpleNamespace(env_id=env_id, config=config)


def test_deep_link_built_from_runner_env_id_and_matching_agent_slug():
    from flightcheck.checks.local_files import _studio_agent_url

    runner = _fake_runner(
        env_id="11111111-2222-3333-4444-555555555555",
        agents=[
            {"slug": "agent-a", "botId": "bot-a-id"},
            {"slug": "agent-b", "botId": "bot-b-id"},
        ],
    )

    url = _studio_agent_url(runner, "agent-b")

    assert url == (
        "https://copilotstudio.microsoft.com/"
        "environments/11111111-2222-3333-4444-555555555555/"
        "bots/bot-b-id/overview"
    )


def test_deep_link_falls_back_to_single_agent_shape_when_slug_not_in_agents():
    """Older configs only have a top-level "agent" key, no "agents" list."""
    from flightcheck.checks.local_files import _studio_agent_url

    runner = _fake_runner(
        env_id="env-1",
        single_agent={"slug": "legacy-agent", "botId": "legacy-bot-id"},
    )

    # agent_name doesn't match the single-agent slug, but the helper
    # falls back to the single-agent shape — that's the whole point of
    # the fallback, otherwise older configs always lose the deep link.
    url = _studio_agent_url(runner, "any-name")

    assert url == (
        "https://copilotstudio.microsoft.com/"
        "environments/env-1/bots/legacy-bot-id/overview"
    )


def test_deep_link_returns_none_when_env_id_missing():
    from flightcheck.checks.local_files import _studio_agent_url

    runner = _fake_runner(env_id=None, agents=[{"slug": "a", "botId": "b"}])

    assert _studio_agent_url(runner, "a") is None


def test_deep_link_returns_none_when_bot_id_not_findable():
    from flightcheck.checks.local_files import _studio_agent_url

    runner = _fake_runner(env_id="e", agents=[{"slug": "other", "botId": "x"}])

    assert _studio_agent_url(runner, "missing-agent") is None


def test_deep_link_returns_none_when_runner_is_none():
    from flightcheck.checks.local_files import _studio_agent_url

    assert _studio_agent_url(None, "any-agent") is None


def test_studio_link_md_uses_deep_link_when_available():
    from flightcheck.checks.local_files import _studio_link_md

    runner = _fake_runner(env_id="e1", agents=[{"slug": "a", "botId": "b1"}])

    md = _studio_link_md(runner, "a", "the agent")

    assert md == (
        "[the agent]("
        "https://copilotstudio.microsoft.com/"
        "environments/e1/bots/b1/overview)"
    )


def test_studio_link_md_falls_back_to_homepage_when_no_deep_link():
    """Failing softly to the homepage keeps the remediation actionable
    even when env_id or botId are missing (e.g. setup half-completed)."""
    from flightcheck.checks.local_files import _studio_link_md

    md = _studio_link_md(None, "", "Copilot Studio")

    assert md == "[Copilot Studio](https://copilotstudio.microsoft.com/)"


def test_config_007_missing_instructions_remediation_includes_deep_link(
    tmp_path: Path,
):
    """When CONFIG-007 fails with 'no instructions block', the
    remediation string must include the deep link so the user knows
    EXACTLY where to go in Copilot Studio."""
    from flightcheck.checks.local_files import _check_agent_identity

    agent_dir = tmp_path / "my-agent"
    agent_dir.mkdir()
    # agent.mcs.yml exists but has no instructions block at all
    (agent_dir / "agent.mcs.yml").write_text(
        "kind: AgentDefinition\nname: My Agent\n",
        encoding="utf-8",
    )

    runner = _fake_runner(
        env_id="env-007",
        agents=[{"slug": "my-agent", "botId": "bot-007"}],
    )

    results = _check_agent_identity(agent_dir, "My Agent", runner, "my-agent")

    # find the FAILED CONFIG-007 row for "Agent instructions"
    failed = [
        r for r in results
        if r.checkpoint_id == "CONFIG-007"
        and r.status == "Failed"
        and "instructions" in r.description.lower()
    ]
    assert len(failed) == 1, [r.__dict__ for r in results]

    remediation = failed[0].remediation or ""
    assert (
        "https://copilotstudio.microsoft.com/environments/env-007/"
        "bots/bot-007/overview"
    ) in remediation


def test_config_007_remediation_falls_back_when_runner_unavailable(
    tmp_path: Path,
):
    """No runner / missing config -> remediation still links somewhere
    (the homepage) rather than leaving the user without a link."""
    from flightcheck.checks.local_files import _check_agent_identity

    agent_dir = tmp_path / "my-agent"
    agent_dir.mkdir()
    (agent_dir / "agent.mcs.yml").write_text(
        "kind: AgentDefinition\nname: My Agent\n",
        encoding="utf-8",
    )

    results = _check_agent_identity(agent_dir, "My Agent", None, "")

    failed = [
        r for r in results
        if r.checkpoint_id == "CONFIG-007" and r.status == "Failed"
    ]
    assert len(failed) == 1
    assert "https://copilotstudio.microsoft.com/" in (failed[0].remediation or "")
