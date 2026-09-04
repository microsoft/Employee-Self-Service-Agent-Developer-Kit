# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for scripts/fetch_and_setup.py refresh-target resolution.

`--refresh` historically read the stored config's env/bot verbatim, so it
could not retarget an agent to a second environment (it re-fetched the old
env, ignoring `--url`). `_resolve_refresh_target` lets explicit CLI overrides
win so `--refresh --url <new-env> --bot-id <new-bot>` cleanly retargets.
"""

from __future__ import annotations

from types import SimpleNamespace

import fetch_and_setup


def _args(url=None, bot_id=None, name=None, schema=None, managed=False):
    return SimpleNamespace(
        url=url, bot_id=bot_id, name=name, schema=schema, managed=managed,
        refresh=True,
    )


def _config(**overrides):
    cfg = {
        "dataverseEndpoint": "https://old-env.crm.dynamics.com",
        "agent": {
            "botId": "old-bot",
            "name": "Old Agent",
            "schemaName": "msdyn_oldagent",
            "isManaged": True,
        },
    }
    cfg.update(overrides)
    return cfg


class TestResolveRefreshTarget:
    def test_falls_back_to_config_when_no_overrides(self):
        env, bot, name, schema, managed = \
            fetch_and_setup._resolve_refresh_target(_args(), _config())
        assert env == "https://old-env.crm.dynamics.com"
        assert bot == "old-bot"
        assert name == "Old Agent"
        assert schema == "msdyn_oldagent"
        assert managed is True

    def test_url_override_retargets_env(self):
        env, bot, *_ = fetch_and_setup._resolve_refresh_target(
            _args(url="https://new-env.crm.dynamics.com/", bot_id="new-bot"),
            _config(),
        )
        assert env == "https://new-env.crm.dynamics.com"  # trailing slash stripped
        assert bot == "new-bot"

    def test_partial_overrides_prefer_args_then_config(self):
        env, bot, name, schema, _ = fetch_and_setup._resolve_refresh_target(
            _args(url="https://new-env.crm.dynamics.com", name="New Name"),
            _config(),
        )
        assert env == "https://new-env.crm.dynamics.com"
        assert bot == "old-bot"       # not overridden → config
        assert name == "New Name"     # overridden
        assert schema == "msdyn_oldagent"

    def test_managed_reflects_flag_only_when_retargeting(self):
        # Retargeting (--url given): managed reflects the flag literally.
        _, _, _, _, managed = fetch_and_setup._resolve_refresh_target(
            _args(url="https://new-env.crm.dynamics.com", managed=False),
            _config(),
        )
        assert managed is False  # new env declared unmanaged

    def test_managed_keeps_config_on_plain_refresh(self):
        # Plain refresh (no --url): managed comes from config, not the
        # default-False flag, so a plain refresh never downgrades managed.
        _, _, _, _, managed = fetch_and_setup._resolve_refresh_target(
            _args(managed=False), _config(),
        )
        assert managed is True
