# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the deploy-target resolution + environment-SKU caching in
``push.py`` (ADO 7609605).

``_resolve_deploy_target`` classifies an agent.deploy telemetry event into
``sandbox`` vs ``production`` from the target environment's Power Platform SKU.
The resolution priority is:
  1. explicit ``ESS_ADK_DEPLOY_TARGET`` override (returned verbatim),
  2. ``environmentSku`` cached in config,
  3. best-effort silent BAP lookup (cached back to config),
  4. ``production`` default.

The silent BAP lookup itself (network + MSAL) is intentionally NOT unit-tested
here — it is best-effort and swallows all errors — so these tests monkeypatch
``_lookup_environment_sku_silent``/``_cache_environment_sku`` to pin only the
orchestration logic.
"""

from __future__ import annotations

import json
import os

import push


class TestResolveDeployTarget:
    def test_explicit_override_wins_verbatim(self, monkeypatch):
        # Override is returned as-is (self-declared escape hatch) and short-
        # circuits both the cached SKU and any lookup.
        monkeypatch.setenv("ESS_ADK_DEPLOY_TARGET", "custom-label")
        monkeypatch.setattr(
            push, "_lookup_environment_sku_silent",
            lambda url: (_ for _ in ()).throw(AssertionError("must not be called")),
        )
        assert push._resolve_deploy_target(
            {"environmentSku": "Sandbox"}, "https://x.crm.dynamics.com"
        ) == "custom-label"

    def test_blank_override_is_ignored(self, monkeypatch):
        monkeypatch.setenv("ESS_ADK_DEPLOY_TARGET", "   ")
        assert push._resolve_deploy_target({"environmentSku": "Sandbox"}, "") == "sandbox"

    def test_cached_sku_classified_without_lookup(self, monkeypatch):
        monkeypatch.delenv("ESS_ADK_DEPLOY_TARGET", raising=False)
        monkeypatch.setattr(
            push, "_lookup_environment_sku_silent",
            lambda url: (_ for _ in ()).throw(AssertionError("cached SKU should win")),
        )
        assert push._resolve_deploy_target({"environmentSku": "Sandbox"}, "url") == "sandbox"
        assert push._resolve_deploy_target({"environmentSku": "Production"}, "url") == "production"

    def test_silent_lookup_used_and_cached_when_no_cached_sku(self, monkeypatch):
        monkeypatch.delenv("ESS_ADK_DEPLOY_TARGET", raising=False)
        monkeypatch.setattr(push, "_lookup_environment_sku_silent", lambda url: "Sandbox")
        cached = {}
        monkeypatch.setattr(
            push, "_cache_environment_sku", lambda sku: cached.__setitem__("sku", sku)
        )
        assert push._resolve_deploy_target({}, "https://x.crm.dynamics.com") == "sandbox"
        assert cached["sku"] == "Sandbox"  # discovered SKU is persisted

    def test_defaults_to_production_when_lookup_returns_none(self, monkeypatch):
        monkeypatch.delenv("ESS_ADK_DEPLOY_TARGET", raising=False)
        monkeypatch.setattr(push, "_lookup_environment_sku_silent", lambda url: None)
        monkeypatch.setattr(push, "_cache_environment_sku", lambda sku: None)
        assert push._resolve_deploy_target({}, "") == "production"


class TestCacheEnvironmentSku:
    def test_writes_sku_into_config(self, chdir_kit_root):
        push._cache_environment_sku("Sandbox")
        with open(os.path.join(".local", "config.json"), encoding="utf-8") as f:
            data = json.load(f)
        assert data["environmentSku"] == "Sandbox"

    def test_empty_sku_is_noop(self, chdir_kit_root):
        push._cache_environment_sku("")
        with open(os.path.join(".local", "config.json"), encoding="utf-8") as f:
            data = json.load(f)
        assert "environmentSku" not in data
