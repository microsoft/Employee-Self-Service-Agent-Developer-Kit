# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DA applicability must follow the selected subject, not a sibling agent."""

from types import SimpleNamespace

import pytest

from flightcheck.agent_scope import is_declarative_agent


@pytest.mark.parametrize("config,slug,profile,expected", [
    ({}, None, False, False),
    ({"releaseLine": "da"}, "", False, True),
    ({"agents": [{"slug": "hr", "releaseLine": "da"}]}, "", False, False),
    ({"releaseLine": "da", "dataverseEndpoint": "https://example.invalid"}, None, False, True),
    ({"releaseLine": "cea"}, None, False, False),
    ({}, None, True, True),
    ({"releaseLine": "cea"}, None, True, False),
    ({"activeAgent": "hr", "agents": [{"slug": "hr", "releaseLine": "DA"}]}, None, False, True),
    ({"releaseLine": "da", "agents": [{"slug": "hr", "releaseLine": "cea"}]}, "hr", False, False),
    ({"releaseLine": "da", "agents": [{"slug": "hr", "releaseLine": ""}]}, "hr", False, False),
    ({"releaseLine": "da", "agents": [{"slug": "hr", "releaseLine": False}]}, "hr", False, False),
    ({"releaseLine": "da", "agents": [{"slug": "hr", "releaseLine": 0}]}, "hr", True, False),
    ({"releaseLine": "da", "agents": [{"slug": "hr", "releaseLine": None}]}, "hr", False, True),
    ({"releaseLine": None}, None, True, True),
    ({"releaseLine": None}, None, False, False),
    ({"agents": [{"slug": "hr", "releaseLine": None}]}, "hr", True, True),
    ({"agents": [{"slug": "hr", "releaseLine": "da"}, {"slug": "it"}]}, "it", False, False),
    ({"releaseLine": "da", "agents": [{"slug": "hr", "releaseLine": "da"}]}, "missing", False, False),
    ({"agents": [{"slug": "hr", "releaseLine": "da"}, {"slug": "hr"}]}, "hr", False, False),
    ({"agents": [{"slug": "hr", "releaseLine": "da"}, {"slug": "it"}]}, None, False, False),
    ({"agent": {"releaseLine": "da"}}, None, False, True),
    ({"activeAgent": "hr", "releaseLine": "da", "agents": [{"slug": "hr"}]}, None, False, True),
    ({"activeAgent": "hr", "releaseLine": "da", "agents": [{"slug": "hr", "releaseLine": "da"}, {"slug": "it"}]}, "it", False, False),
    ({"activeAgent": "hr", "releaseLine": "cea", "agents": [{"slug": "hr"}, {"slug": "it", "releaseLine": "da"}]}, "it", False, True),
    ({"activeAgent": "hr", "releaseLine": "da", "agents": [{"slug": "hr"}, {"slug": "it"}]}, "it", True, True),
    ({"releaseLine": "da"}, 0, False, False),
    ({"agents": [{"slug": "hr", "releaseLine": "cea"}]}, "hr", True, False),
    ({"agents": [{"slug": "hr", "releaseLine": "da"}]}, "missing", True, False),
    ({"agents": [{"slug": "hr", "releaseLine": "da"}, {"slug": "hr"}]}, "hr", True, False),
    ({"releaseLine": "da"}, 0, True, False),
])
def test_da_context_requires_selected_metadata(config, slug, profile, expected):
    runner = SimpleNamespace(config=config, agent_slug=slug, workday_da_profile=profile)

    assert is_declarative_agent(runner) is expected


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("profile", [True, False, None, 1, "true"])
@pytest.mark.parametrize("workspace_metadata,allows_profile", [
    ({}, True),
    ({"releaseLine": None}, True),
    ({"releaseLine": "da"}, True),
    ({"releaseLine": " DA "}, True),
    ({"releaseLine": "cea"}, False),
    ({"releaseLine": ""}, False),
    ({"releaseLine": False}, False),
    ({"releaseLine": 0}, False),
])
def test_unselected_agents_allow_only_explicit_da_profile(
    workspace_metadata, allows_profile, profile, reverse,
):
    # Arrange.
    agents = [
        {"slug": "hr", "releaseLine": "da"},
        {"slug": "legacy", "releaseLine": "cea"},
    ]
    if reverse:
        agents.reverse()
    config = {**workspace_metadata, "agents": agents}
    runner = SimpleNamespace(config=config, agent_slug="", workday_da_profile=profile)

    # Act.
    actual = is_declarative_agent(runner)

    # Assert.
    assert actual is (profile is True and allows_profile)
    assert runner.agent_slug == ""
