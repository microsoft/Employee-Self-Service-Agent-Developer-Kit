# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Regression tests for the /review conformance engine's correctness gates.

These pin three defects surfaced by an external review of the /review skill:

  * F-1 -- ``merge_findings._hashes_match`` must judge evidence staleness
    independently of the current working directory. It regressed when the
    security pass anchored ``evidence_hashes`` on the skill root but left the
    match side re-hashing a cwd-relative path, so a finding read as "fresh"
    from the repo root and "stale" from ``scripts/``.
  * F-2 -- the ``scan_*`` detectors must not print a clean all-clear when a
    topic could not be read: an unreadable topic is skipped, so the result
    does not cover it. They must warn and say coverage is incomplete.
  * F-4 -- ``validate_current_findings`` / ``validate_resolutions`` must reject
    out-of-enum ``reachability`` / ``verification`` / ``resolution`` values
    rather than silently coercing them (the ledger is append-only, so a
    coerced dismissal would be misrecorded permanently).

The detector tests spawn each script as a subprocess against a throwaway agent
created under the gitignored ``workspace/agents/`` tree, mirroring how the
skill invokes them.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import merge_findings

# scripts/ live directly under the maker-skills root; workspace/agents/ is a
# sibling of scripts/ and is gitignored, so throwaway agents leave no git trace.
_SKILL_ROOT = Path(merge_findings.__file__).resolve().parent.parent
_SCRIPTS_DIR = _SKILL_ROOT / "scripts"
_AGENTS_DIR = _SKILL_ROOT / "workspace" / "agents"

# A real in-tree file, used as stable evidence for the staleness tests.
_EVIDENCE_REL = "scripts/merge_findings.py"


def _finding(**overrides) -> dict:
    """A minimal finding that passes validate_current_findings, with overrides."""
    finding = {
        "id": "sample-finding",
        "title": "Sample finding",
        "severity": "MEDIUM",
        "reachability": "REACHABLE_NORMAL_UI",
        "root_cause": "Something is wrong.",
        "concrete_fix": "Fix the thing.",
        "files": [{"path": _EVIDENCE_REL}],
    }
    finding.update(overrides)
    return finding


# --------------------------------------------------------------------------- #
# F-1 -- staleness is cwd-independent
# --------------------------------------------------------------------------- #

def test_hashes_match_is_cwd_independent(monkeypatch, tmp_path):
    stored = merge_findings.evidence_hashes(_finding())
    assert stored and stored[0]["sha256"], "evidence hash should be populated"

    monkeypatch.chdir(_SKILL_ROOT)
    assert merge_findings._hashes_match(stored) is True

    # From an unrelated directory the verdict must not flip.
    monkeypatch.chdir(tmp_path)
    assert merge_findings._hashes_match(stored) is True

    monkeypatch.chdir(_SCRIPTS_DIR)
    assert merge_findings._hashes_match(stored) is True


def test_hashes_match_rejects_null_and_escaping():
    # A stored hash of None (file was unreadable at store time) is a mismatch,
    # never "unchanged".
    assert merge_findings._hashes_match([{"file": _EVIDENCE_REL, "sha256": None}]) is False
    # An empty ledger of hashes is a mismatch, not a vacuous match.
    assert merge_findings._hashes_match([]) is False
    # A path that escapes the skill tree cannot be silently treated as fresh.
    assert merge_findings._hashes_match([{"file": "../../etc/hosts", "sha256": "deadbeef"}]) is False


# --------------------------------------------------------------------------- #
# F-4 -- enum validation rejects, never coerces
# --------------------------------------------------------------------------- #

def test_valid_finding_passes():
    assert merge_findings.validate_current_findings([_finding()]) == []


@pytest.mark.parametrize(
    "override",
    [
        {"reachability": "confirmed"},          # not an enum value (the F-4 example bug)
        {"verification": "runtime"},            # not static / needs-runtime-test
        {"severity": "CRITICAL"},               # not HIGH / MEDIUM / LOW
        {"files": [{"path": "../../secret"}]},  # escapes the workspace
        {"files": []},                          # no path -> evidence_hashes empty
    ],
)
def test_invalid_finding_is_rejected(override):
    errors = merge_findings.validate_current_findings([_finding(**override)])
    assert errors, f"expected a validation error for {override}"


def test_resolution_validation():
    assert merge_findings.validate_resolutions([{"id": "x", "resolution": "fixed"}]) == []
    # An absent resolution is legitimate (defaults to "fixed"); a wrong one is not.
    assert merge_findings.validate_resolutions([{"id": "x"}]) == []
    assert merge_findings.validate_resolutions([{"id": "x", "resolution": "resolved"}])


# --------------------------------------------------------------------------- #
# F-2 -- an unreadable topic never yields a clean all-clear
# --------------------------------------------------------------------------- #

@pytest.fixture
def temp_agent():
    """Create a throwaway agent with one readable and one undecodable topic.

    Lives under the gitignored workspace/agents/ tree so it never pollutes git
    status; removed on teardown.
    """
    name = f"_pytest_{uuid.uuid4().hex}"
    agent_dir = _AGENTS_DIR / name
    topics = agent_dir / "topics"
    topics.mkdir(parents=True)
    (agent_dir / "variables").mkdir()

    good = (
        "kind: AdaptiveDialog\n"
        "beginDialog:\n"
        "  kind: OnRecognizedIntent\n"
        "  actions: []\n"
    )
    (topics / "good.mcs.yml").write_text(good, encoding="utf-8", newline="\r\n")
    # Bytes that decode cleanly as neither UTF-8 nor UTF-16 -> read is skipped.
    (topics / "bad.mcs.yml").write_bytes(b"\xff\xfe\x00\x80\x81\xff")

    try:
        yield name
    finally:
        shutil.rmtree(agent_dir, ignore_errors=True)


@pytest.mark.parametrize("script", ["scan_globals.py", "scan_bindings.py", "scan_config.py"])
def test_detector_flags_incomplete_coverage_on_unreadable_topic(temp_agent, script):
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / script), "--agent", temp_agent],
        capture_output=True,
        text=True,
    )
    combined = proc.stdout + proc.stderr
    # The skill reads detector output; a non-zero exit could abort the flow, so
    # the detector must stay exit 0 while disclosing the gap.
    assert proc.returncode == 0, combined
    assert "NOT analyzed" in combined, combined
    assert "coverage is incomplete" in proc.stdout, combined
