# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the local-file check helpers that lacked coverage:
``_check_topic_inventory`` (TOPIC-011), ``_check_variables`` (CONFIG-012),
``_check_template_configs`` (LOCAL-TC-001), and the ``LOCAL-001``
agent-discovery branch of ``run_local_file_checks``.

These checks read only the local agent working copy under
``workspace/agents/{slug}/`` — no network, no cassettes — so they are
pure-logic tests per tests/AGENTS.md.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
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


def _result_by_id(results, cid):
    return next(r for r in results if r.checkpoint_id == cid)


# --------------------------------------------------------------------------
# _check_topic_inventory — TOPIC-011
# --------------------------------------------------------------------------

def test_topic_inventory_passes_with_enough_topics(tmp_path):
    from flightcheck.checks.local_files import _check_topic_inventory
    topics = tmp_path / "topics"
    topics.mkdir()
    for i in range(5):
        (topics / f"topic{i}.mcs.yml").write_text("kind: x", encoding="utf-8")

    results = _check_topic_inventory(tmp_path, "Agent A")
    r = _result_by_id(results, "TOPIC-011")
    assert r.status == "Passed"
    assert "5 topic(s)" in r.result


def test_topic_inventory_warns_when_too_few(tmp_path):
    from flightcheck.checks.local_files import _check_topic_inventory
    topics = tmp_path / "topics"
    topics.mkdir()
    (topics / "only.mcs.yml").write_text("kind: x", encoding="utf-8")

    results = _check_topic_inventory(tmp_path, "Agent A")
    r = _result_by_id(results, "TOPIC-011")
    assert r.status == "Warning"
    assert "1 topic(s)" in r.result
    assert "20+ topics" in r.remediation


def test_topic_inventory_skipped_when_no_topics_dir(tmp_path):
    from flightcheck.checks.local_files import _check_topic_inventory
    assert _check_topic_inventory(tmp_path, "Agent A") == []


# --------------------------------------------------------------------------
# _check_variables — CONFIG-012
# --------------------------------------------------------------------------

def test_variables_pass_when_present(tmp_path):
    from flightcheck.checks.local_files import _check_variables
    vars_dir = tmp_path / "variables"
    vars_dir.mkdir()
    (vars_dir / "UserContext.mcs.yml").write_text("kind: v", encoding="utf-8")

    r = _result_by_id(_check_variables(tmp_path, "Agent A"), "CONFIG-012")
    assert r.status == "Passed"
    assert "1 variable(s) found" in r.result


def test_variables_warn_when_dir_empty(tmp_path):
    from flightcheck.checks.local_files import _check_variables
    (tmp_path / "variables").mkdir()

    r = _result_by_id(_check_variables(tmp_path, "Agent A"), "CONFIG-012")
    assert r.status == "Warning"
    assert "0 variable(s) found" in r.result
    assert "Create User Context variables" in r.remediation


def test_variables_warn_when_dir_missing(tmp_path):
    from flightcheck.checks.local_files import _check_variables
    r = _result_by_id(_check_variables(tmp_path, "Agent A"), "CONFIG-012")
    assert r.status == "Warning"
    assert "Variables directory not found" in r.result
    assert "/setup" in r.remediation


# --------------------------------------------------------------------------
# _check_template_configs — LOCAL-TC-001
# --------------------------------------------------------------------------

def test_template_configs_counts_files(tmp_path):
    from flightcheck.checks.local_files import _check_template_configs
    tc = tmp_path / "template-configs"
    tc.mkdir()
    (tc / "a.xml").write_text("<x/>", encoding="utf-8")
    (tc / "b.xml").write_text("<x/>", encoding="utf-8")
    (tc / "a.meta.json").write_text("{}", encoding="utf-8")

    r = _result_by_id(_check_template_configs(tmp_path, "Agent A"), "LOCAL-TC-001")
    assert r.status == "Passed"
    assert "2 XML template(s)" in r.result
    assert "1 metadata file(s)" in r.result


def test_template_configs_skipped_when_no_dir(tmp_path):
    from flightcheck.checks.local_files import _check_template_configs
    assert _check_template_configs(tmp_path, "Agent A") == []


# --------------------------------------------------------------------------
# run_local_file_checks — LOCAL-001 agent-discovery branch
# --------------------------------------------------------------------------

def _runner():
    return SimpleNamespace(env_id="env-guid", config={})


def test_local_001_skipped_when_workspace_missing(tmp_path, monkeypatch):
    from flightcheck.checks.local_files import run_local_file_checks
    monkeypatch.chdir(tmp_path)  # no workspace/agents/ here
    results = run_local_file_checks(_runner())
    r = _result_by_id(results, "LOCAL-001")
    assert r.status == "Skipped"
    assert "workspace/agents/ directory not found" in r.result
    assert "/setup" in r.remediation


def test_local_001_skipped_when_no_agent_folders(tmp_path, monkeypatch):
    from flightcheck.checks.local_files import run_local_file_checks
    (tmp_path / "workspace" / "agents").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    results = run_local_file_checks(_runner())
    r = _result_by_id(results, "LOCAL-001")
    assert r.status == "Skipped"
    assert "No agent folders found" in r.result
