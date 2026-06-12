# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the basic Power Platform environment checks that
lacked assertions: ENV-001 (environment exists), ENV-002 (Dataverse
provisioned), ENV-003 (environment type).

ENV-004 / ENV-008 / ENV-009 are covered by their own test files; here
``query_all`` (ENV-004) is stubbed to [] and the BAP environment record
is supplied via a minimal fake PP Admin client mirroring
``test_env_008_dlp_remediation.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    repo_root = Path(__file__).resolve().parents[3]
    scripts_dir = repo_root / "solutions" / "ess-maker-skills" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


class _FakePPAdmin:
    def __init__(self, *, env_props=None, env_error=None):
        self._env_props = env_props if env_props is not None else {
            "displayName": "Test Env",
            "linkedEnvironmentMetadata": {"resourceProvisioningState": "Succeeded"},
            "databaseType": "CommonDataService",
            "environmentSku": "Production",
        }
        self._env_error = env_error

    def get_environment(self, _env_id):
        if self._env_error is not None:
            return {"_error": self._env_error}
        return {"properties": self._env_props}

    def get_dlp_policies_for_env(self, _env_id):
        return []

    def get_connections(self, _env_id):
        return []


def _runner(pp_admin):
    return SimpleNamespace(
        pp_admin=pp_admin, env_id="env-guid",
        env_url="https://example.crm.dynamics.com", dv_token="t",
    )


@pytest.fixture(autouse=True)
def _stub_query_all(monkeypatch):
    """Neutralize ENV-004's Dataverse call so these tests stay offline."""
    from flightcheck.checks import environment as env_mod
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])


def _by_id(results, cid):
    matches = [r for r in results if r.checkpoint_id == cid]
    assert len(matches) == 1, [r.checkpoint_id for r in results]
    return matches[0]


def _run(pp_admin):
    from flightcheck.checks.environment import run_environment_checks
    return run_environment_checks(_runner(pp_admin))


def test_env_001_002_003_pass():
    results = _run(_FakePPAdmin())

    env001 = _by_id(results, "ENV-001")
    assert env001.status == "Passed"
    assert "Test Env" in env001.result

    env002 = _by_id(results, "ENV-002")
    assert env002.status == "Passed"
    assert "Succeeded" in env002.result

    env003 = _by_id(results, "ENV-003")
    assert env003.status == "Passed"
    assert "Production" in env003.result


def test_env_002_fails_when_no_dataverse():
    results = _run(_FakePPAdmin(env_props={"displayName": "No DB Env"}))
    env002 = _by_id(results, "ENV-002")
    assert env002.status == "Failed"
    assert "Enable Dataverse database" in env002.remediation


def test_env_001_warns_on_api_error():
    results = _run(_FakePPAdmin(env_error="403 Forbidden"))
    env001 = _by_id(results, "ENV-001")
    assert env001.status == "Warning"
    assert "Unable to query environment" in env001.result
    assert "Power Platform Administrator role" in env001.remediation
