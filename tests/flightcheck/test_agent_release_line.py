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
])
def test_da_context_requires_selected_metadata(config, slug, profile, expected):
    runner = SimpleNamespace(config=config, agent_slug=slug, workday_da_profile=profile)

    assert is_declarative_agent(runner) is expected
