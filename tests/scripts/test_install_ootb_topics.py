# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for solutions/ess-maker-skills/scripts/install_ootb_topics.py.

Pure-logic, no network (see tests/AGENTS.md — pure-logic helpers are exempt
from the cassette rule). These pin the behaviour that fixes the two bugs that
broke the optional OOTB Workday topics installer:

  1. Filenames must be clean PascalCase (no mangled "w-or-kd-ay-*" slugs).
  2. The installer must write TOPICS ONLY — never template-configs, which are
     managed components delivered by the Workday extension pack.
"""

from __future__ import annotations

from pathlib import Path

import install_ootb_topics as ioot


# --- naming (mangling prevention) -----------------------------------------

class TestTopicBasename:
    def test_strips_hyphens_to_pascalcase(self):
        assert ioot.topic_basename(
            "WorkdayManagersdirect-CompanyCode"
        ) == "WorkdayManagersdirectCompanyCode"

    def test_pascalcase_preserved(self):
        assert ioot.topic_basename(
            "WorkdayGetUserProfile") == "WorkdayGetUserProfile"

    def test_result_is_alphanumeric_only(self):
        for name in ("Weird Name!", "a-b-c", "Manager_Direct.Code"):
            out = ioot.topic_basename(name)
            assert out.isalnum(), f"{name!r} -> {out!r} not alnum"
            assert "-" not in out


# --- substitutions ---------------------------------------------------------

class TestRewriteTopic:
    def test_schema_prefix_repointed_for_all_topic_refs(self):
        content = (
            "dialog: msdyn_copilotforemployeeselfservicehr.topic."
            "WorkdaySystemGetCommonExecution\n"
            "other: msdyn_copilotforemployeeselfservicehr.topic."
            "GetReferenceData\n"
        )
        out = ioot.rewrite_topic(content, "msdyn_myagentschema", "tenantX")
        assert "msdyn_myagentschema.topic.WorkdaySystemGetCommonExecution" in out
        # The non-Workday-prefixed shared topic is repointed too.
        assert "msdyn_myagentschema.topic.GetReferenceData" in out
        assert "msdyn_copilotforemployeeselfservicehr.topic." not in out

    def test_tenant_placeholder_replaced(self):
        out = ioot.rewrite_topic("host: <TENANT_NAME>.workday.com",
                                 "s", "microsoft_dpt6")
        assert out == "host: microsoft_dpt6.workday.com"

    def test_no_tenant_leaves_placeholder(self):
        out = ioot.rewrite_topic("host: <TENANT_NAME>", "s", None)
        assert out == "host: <TENANT_NAME>"

    def test_noop_when_prefix_matches(self):
        content = ("dialog: msdyn_copilotforemployeeselfservicehr.topic."
                   "WorkdayManagerCheck\n")
        out = ioot.rewrite_topic(
            content, "msdyn_copilotforemployeeselfservicehr", "t")
        assert out == content


# --- discovery / selection against the vendored samples --------------------

class TestDiscover:
    def test_finds_employee_and_manager_scenarios(self):
        found = ioot.discover()
        cats = {s["category"] for s in found}
        assert cats == {"employee", "manager"}
        # Every discovered scenario yields an alphanumeric base name.
        for s in found:
            assert s["basename"].isalnum()

    def test_known_scenario_present_with_clean_name(self):
        found = ioot.discover()
        by_folder = {s["folder"]: s for s in found}
        assert "WorkdayManagersdirect-CompanyCode" in by_folder
        assert (by_folder["WorkdayManagersdirect-CompanyCode"]["basename"]
                == "WorkdayManagersdirectCompanyCode")


class TestSelect:
    def _sample(self):
        return [
            {"category": "employee", "folder": "WorkdayGetUserProfile",
             "basename": "WorkdayGetUserProfile", "topic_src": "x"},
            {"category": "manager", "folder": "WorkdayManagersdirect-CostCenter",
             "basename": "WorkdayManagersdirectCostCenter", "topic_src": "y"},
        ]

    def test_by_category(self):
        out = ioot.select(self._sample(), categories=["manager"])
        assert [s["folder"] for s in out] == ["WorkdayManagersdirect-CostCenter"]

    def test_by_name_matches_folder_or_basename_loosely(self):
        out = ioot.select(self._sample(),
                          names=["workdaymanagersdirectcostcenter"])
        assert len(out) == 1
        out2 = ioot.select(self._sample(),
                           names=["WorkdayManagersdirect-CostCenter"])
        assert len(out2) == 1

    def test_no_filter_returns_all(self):
        assert len(ioot.select(self._sample())) == 2


# --- install (topics only, idempotent) -------------------------------------

def _fake_samples(root: Path):
    """Build a minimal samples tree so install tests stay hermetic."""
    emp = (root / "src" / "examples" / "ess-samples" / "Workday"
           / "EmployeeScenarios" / "WorkdayGetUserProfile")
    emp.mkdir(parents=True)
    (emp / "topic.yaml").write_text(
        "kind: AdaptiveDialog\n"
        "dialog: msdyn_copilotforemployeeselfservicehr.topic."
        "WorkdaySystemGetCommonExecution\n"
        "host: <TENANT_NAME>.workday.com\n"
    )
    # A stray template-config XML that must NOT be copied by the installer.
    (emp / "msdyn_HRWorkdayHCMEmployeeGetUserProfile.xml").write_text(
        '<scenario name="msdyn_HRWorkdayHCMEmployeeGetUserProfile"/>')
    return root


class TestInstall:
    def test_writes_topic_only_with_substitutions(self, tmp_path: Path):
        _fake_samples(tmp_path)
        agent = tmp_path / "agent"
        agent.mkdir()
        selected = ioot.discover(str(tmp_path))
        result = ioot.install(selected, str(agent),
                              "msdyn_myschema", "acme_dpt")

        assert result["written"] == [
            "topics/WorkdayGetUserProfile.mcs.yml"]
        written = (agent / "topics" / "WorkdayGetUserProfile.mcs.yml").read_text()
        assert "msdyn_myschema.topic.WorkdaySystemGetCommonExecution" in written
        assert "acme_dpt.workday.com" in written
        # TOPICS ONLY: no template-configs directory is ever created.
        assert not (agent / "template-configs").exists()

    def test_idempotent_skips_existing(self, tmp_path: Path):
        _fake_samples(tmp_path)
        agent = tmp_path / "agent"
        agent.mkdir()
        selected = ioot.discover(str(tmp_path))
        ioot.install(selected, str(agent), "s", "t")
        again = ioot.install(selected, str(agent), "s", "t")
        assert again["written"] == []
        assert again["skipped"][0]["basename"] == "WorkdayGetUserProfile"

    def test_skips_when_present_in_baseline(self, tmp_path: Path):
        _fake_samples(tmp_path)
        agent = tmp_path / "agent"
        base = agent / ".baseline" / "topics"
        base.mkdir(parents=True)
        (base / "WorkdayGetUserProfile.mcs.yml").write_text("existing")
        selected = ioot.discover(str(tmp_path))
        result = ioot.install(selected, str(agent), "s", "t")
        assert result["written"] == []

    def test_dry_run_writes_nothing(self, tmp_path: Path):
        _fake_samples(tmp_path)
        agent = tmp_path / "agent"
        agent.mkdir()
        selected = ioot.discover(str(tmp_path))
        result = ioot.install(selected, str(agent), "s", "t", dry_run=True)
        assert result["written"] == ["topics/WorkdayGetUserProfile.mcs.yml"]
        assert not (agent / "topics").exists()


class TestWriteManifest:
    def test_manifest_contents(self, tmp_path: Path):
        manifest = tmp_path / "m.txt"
        ioot.write_manifest(str(manifest),
                            ["topics/A.mcs.yml", "topics/B.mcs.yml"])
        lines = manifest.read_text().splitlines()
        assert "topics/A.mcs.yml" in lines
        assert "topics/B.mcs.yml" in lines
        # First line is a comment header.
        assert lines[0].startswith("#")
