# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the shared active-agent resolver in ``agent_scope``.

ESS-SOLN-001, DV-CONN-001, and DA-CONN-001 all resolve the active agent (and
its ``botId``) through these helpers, so a divergence here would silently make
one check target a different agent than another.
"""

from flightcheck.agent_scope import active_agent, active_agent_bot_id


def test_active_agent_prefers_active_slug_match():
    config = {
        "activeAgent": "beta",
        "agents": [
            {"slug": "alpha", "botId": "id-alpha"},
            {"slug": "beta", "botId": "id-beta"},
        ],
    }

    assert active_agent(config)["slug"] == "beta"
    assert active_agent_bot_id(config) == "id-beta"


def test_active_agent_falls_back_to_single_agent_copy():
    config = {"agent": {"slug": "solo", "botId": "id-solo"}}

    assert active_agent(config)["slug"] == "solo"
    assert active_agent_bot_id(config) == "id-solo"


def test_active_agent_falls_back_to_first_listed_agent():
    config = {"agents": [{"slug": "first", "botId": "id-first"}]}

    assert active_agent(config)["slug"] == "first"
    assert active_agent_bot_id(config) == "id-first"


def test_bot_id_uses_slug_from_agent_copy_against_agents_list():
    config = {
        "agent": {"slug": "beta"},
        "agents": [
            {"slug": "alpha", "botId": "id-alpha"},
            {"slug": "beta", "botId": "id-beta"},
        ],
    }

    assert active_agent_bot_id(config) == "id-beta"


def test_bot_id_never_substitutes_a_sibling_when_active_agent_lacks_bot_id():
    """Subject-identity invariant: a per-agent check must read the selected
    agent or refuse. When the active agent (beta) has no botId, the resolver
    must return None, NOT a healthy sibling's (alpha) botId, so ESS-SOLN-001 /
    DV-CONN-001 never silently verify the wrong agent."""
    config = {
        "activeAgent": "beta",
        "agents": [
            {"slug": "alpha", "botId": "id-alpha"},
            {"slug": "beta"},
        ],
    }

    assert active_agent_bot_id(config) is None


def test_bot_id_strips_whitespace_and_ignores_blank():
    assert active_agent_bot_id({"agent": {"botId": "  id-padded  "}}) == "id-padded"
    assert active_agent_bot_id({"agent": {"botId": "   "}}) is None


def test_none_and_empty_config_are_safe():
    assert active_agent(None) == {}
    assert active_agent({}) == {}
    assert active_agent_bot_id(None) is None
    assert active_agent_bot_id({}) is None
