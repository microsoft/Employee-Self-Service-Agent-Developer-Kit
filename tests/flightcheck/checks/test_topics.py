# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for checks/topics.py (skill-6, create-new-topic).

Both checkpoints (``TOPIC-TRIGGER-*`` / ``TOPIC-INTEGRATION-*``) are pure
local-file family checks — they walk ``workspace/agents/*/topics/*.mcs.yml``,
diff each against the agent's OOTB ``.baseline/`` snapshot, and emit one row per
new/custom topic. No client, no cassette (per tests/AGENTS.md, pure-logic /
local-file checks are exempt from the mock-tier rule).

Each GOOD/BAD test asserts phrases from BOTH ``result`` and ``remediation``
(or, for a PASS whose caveat lives in ``result``, the caveat phrase).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flightcheck.checks import topics as tp
from flightcheck.runner import Priority, Role, Status


# ─────────────────────────────────────────────────────────────────────
# Minimal runner — the emitters ignore it (they walk the filesystem), but
# the signature keeps parity with the other check modules.
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _Runner:
    config: Any = field(default_factory=dict)


def _write_topic(tmp_path, agent, filename, body, baseline=None):
    """Write a working-copy topic; optionally seed a ``.baseline/`` copy."""
    topics = tmp_path / "workspace" / "agents" / agent / "topics"
    topics.mkdir(parents=True, exist_ok=True)
    (topics / filename).write_text(body, encoding="utf-8")
    if baseline is not None:
        bdir = tmp_path / "workspace" / "agents" / agent / ".baseline" / "topics"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / filename).write_text(baseline, encoding="utf-8")


def _by_id(results):
    return {r.checkpoint_id: r for r in results}


# A well-formed, fully-wired custom topic: intent-routed with trigger phrases
# and a resolved Workday system-topic call (no placeholders).
GOOD_TOPIC = """kind: AdaptiveDialog
modelDescription: |-
  Use this topic when the user wants to request time off.
  Trigger phrases:
  - "Request time off"
  - "I need to submit time off"
beginDialog:
  kind: OnRecognizedIntent
  intent: {}
  actions:
    - kind: BeginDialog
      dialog: WorkdaySystemRequestTimeOffExecution
    - kind: SetVariable
      variable: Topic.ScenarioName
      value: RequestTimeOff
"""


# ─────────────────────────────────────────────────────────────────────
# TOPIC-TRIGGER-* (S6.1)
# ─────────────────────────────────────────────────────────────────────


class TestTopicTriggers:
    def test_valid_intent_topic_passes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(tmp_path, "acme", "WorkdayRequestTimeOff.mcs.yml", GOOD_TOPIC)
        results = tp._check_topic_triggers(_Runner())
        assert [r.checkpoint_id for r in results] == ["TOPIC-TRIGGER-001"]
        r = results[0]
        assert r.status == Status.PASSED.value
        assert r.category == "Workday Topics"
        assert r.roles == [Role.ESS_MAKER.value]
        assert "WorkdayRequestTimeOff" in r.result
        assert "trigger phrases" in r.result

    def test_missing_adaptive_dialog_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path, "acme", "Bad.mcs.yml",
            "beginDialog:\n  kind: OnRecognizedIntent\n",
        )
        r = tp._check_topic_triggers(_Runner())[0]
        assert r.status == Status.FAILED.value
        assert "kind: AdaptiveDialog" in r.result
        assert "AdaptiveDialog" in r.remediation

    def test_intent_without_phrases_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path, "acme", "NoPhrases.mcs.yml",
            "kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRecognizedIntent\n"
            "  intent: {}\n  actions: []\n",
        )
        r = tp._check_topic_triggers(_Runner())[0]
        assert r.status == Status.FAILED.value
        assert "trigger phrases" in r.result
        assert "modelDescription" in r.remediation

    def test_triggerqueries_satisfies_phrases(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path, "acme", "TQ.mcs.yml",
            "kind: AdaptiveDialog\ntriggerQueries:\n  - hello\nbeginDialog:\n"
            "  kind: OnRecognizedIntent\n  intent: {}\n",
        )
        r = tp._check_topic_triggers(_Runner())[0]
        assert r.status == Status.PASSED.value

    def test_system_topic_onredirect_passes_without_phrases(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path, "acme", "SysExec.mcs.yml",
            "kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRedirect\n"
            "  actions: []\n",
        )
        r = tp._check_topic_triggers(_Runner())[0]
        assert r.status == Status.PASSED.value
        assert "trigger" in r.result

    def test_no_trigger_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path, "acme", "NoTrigger.mcs.yml",
            "kind: AdaptiveDialog\nmodelDescription: |-\n  Something\n",
        )
        r = tp._check_topic_triggers(_Runner())[0]
        assert r.status == Status.FAILED.value
        assert "no trigger" in r.result
        assert "beginDialog" in r.remediation


# ─────────────────────────────────────────────────────────────────────
# TOPIC-INTEGRATION-* (S6.2)
# ─────────────────────────────────────────────────────────────────────


class TestTopicIntegration:
    def test_resolved_wiring_passes_with_sme_note(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(tmp_path, "acme", "WorkdayRequestTimeOff.mcs.yml", GOOD_TOPIC)
        results = tp._check_topic_integration(_Runner())
        assert [r.checkpoint_id for r in results] == ["TOPIC-INTEGRATION-001"]
        r = results[0]
        assert r.status == Status.PASSED.value
        assert r.roles == [Role.ESS_MAKER.value]
        assert "resolves" in r.result
        # The SME caveat rides on result (not remediation) so the prog row
        # auto-completes on PASS.
        assert "Workday SME" in r.result
        assert r.remediation == ""

    def test_double_brace_placeholder_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        body = GOOD_TOPIC.replace(
            "value: RequestTimeOff", "value: {{SCENARIO_NAME}}"
        )
        _write_topic(tmp_path, "acme", "T.mcs.yml", body)
        r = tp._check_topic_integration(_Runner())[0]
        assert r.status == Status.FAILED.value
        assert "{{SCENARIO_NAME}}" in r.result
        assert "tenant values" in r.remediation

    def test_uppercase_angle_placeholder_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        body = GOOD_TOPIC + (
            "    - kind: SetVariable\n"
            "      variable: Topic.WorkdayUrl\n"
            "      value: https://impl.workday.com/<TENANT_NAME>/home.htmld\n"
        )
        _write_topic(tmp_path, "acme", "T.mcs.yml", body)
        r = tp._check_topic_integration(_Runner())[0]
        assert r.status == Status.FAILED.value
        assert "<TENANT_NAME>" in r.result
        assert "Time Off Type ID" in r.remediation

    def test_lowercase_angle_slot_not_flagged(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Trigger-phrase slot examples like <date> are lowercase and must NOT
        # be treated as unresolved tenant placeholders.
        body = GOOD_TOPIC.replace(
            '- "I need to submit time off"',
            '- "Request time off from <date> to <date> for <reason>"',
        )
        _write_topic(tmp_path, "acme", "T.mcs.yml", body)
        r = tp._check_topic_integration(_Runner())[0]
        assert r.status == Status.PASSED.value

    def test_no_wiring_topic_passes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path, "acme", "Chit.mcs.yml",
            "kind: AdaptiveDialog\nmodelDescription: |-\n  A greeting.\n"
            "beginDialog:\n  kind: OnRecognizedIntent\n  intent: {}\n"
            "  actions:\n    - kind: SendActivity\n      activity: Hi!\n",
        )
        # SendActivity-only topic has no BeginDialog/InvokeFlowAction/etc.
        r = tp._check_topic_integration(_Runner())[0]
        assert r.status == Status.PASSED.value
        assert "no external integration wiring" in r.result


# ─────────────────────────────────────────────────────────────────────
# Enumeration / OOTB-baseline diff
# ─────────────────────────────────────────────────────────────────────


class TestEnumeration:
    def test_no_workspace_not_configured(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for fn, cid in (
            (tp._check_topic_triggers, "TOPIC-TRIGGER-001"),
            (tp._check_topic_integration, "TOPIC-INTEGRATION-001"),
        ):
            r = fn(_Runner())[0]
            assert r.checkpoint_id == cid
            assert r.status == Status.NOT_CONFIGURED.value
            assert "No agent workspace" in r.result
            assert "fetch_and_setup" in r.remediation

    def test_no_new_topics_not_configured(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # An OOTB topic identical to its baseline copy is not "new".
        _write_topic(tmp_path, "acme", "Ootb.mcs.yml", GOOD_TOPIC, baseline=GOOD_TOPIC)
        r = tp._check_topic_triggers(_Runner())[0]
        assert r.checkpoint_id == "TOPIC-TRIGGER-001"
        assert r.status == Status.NOT_CONFIGURED.value
        assert "No custom topics" in r.result
        assert "create-new-topic" in r.remediation

    def test_baseline_identical_topic_skipped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(tmp_path, "acme", "Ootb.mcs.yml", GOOD_TOPIC, baseline=GOOD_TOPIC)
        _write_topic(tmp_path, "acme", "New.mcs.yml", GOOD_TOPIC)
        results = tp._check_topic_triggers(_Runner())
        assert [r.checkpoint_id for r in results] == ["TOPIC-TRIGGER-001"]
        assert "New" in results[0].result
        assert "Ootb" not in results[0].result

    def test_changed_ootb_topic_is_new(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Present in baseline but modified in the working copy => custom/new.
        modified = GOOD_TOPIC + "# operator tweak\n"
        _write_topic(tmp_path, "acme", "Edited.mcs.yml", modified, baseline=GOOD_TOPIC)
        results = tp._check_topic_triggers(_Runner())
        assert [r.checkpoint_id for r in results] == ["TOPIC-TRIGGER-001"]
        assert "Edited" in results[0].result

    def test_whitespace_only_diff_not_new(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Trailing whitespace per line must normalise equal to the baseline
        # (push writes both copies, so only cosmetic whitespace can differ).
        working = "\n".join(line + "   " for line in GOOD_TOPIC.split("\n"))
        _write_topic(tmp_path, "acme", "Ootb.mcs.yml", working, baseline=GOOD_TOPIC)
        r = tp._check_topic_triggers(_Runner())[0]
        assert r.status == Status.NOT_CONFIGURED.value
        assert "No custom topics" in r.result

    def test_multiple_new_topics_numbered_and_sorted(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(tmp_path, "acme", "Bravo.mcs.yml", GOOD_TOPIC)
        _write_topic(tmp_path, "acme", "Alpha.mcs.yml", GOOD_TOPIC)
        results = tp._check_topic_triggers(_Runner())
        assert [r.checkpoint_id for r in results] == [
            "TOPIC-TRIGGER-001",
            "TOPIC-TRIGGER-002",
        ]
        # Sorted by filename: Alpha before Bravo.
        assert "Alpha" in results[0].result
        assert "Bravo" in results[1].result


# ─────────────────────────────────────────────────────────────────────
# Dispatcher — run_topic_checks
# ─────────────────────────────────────────────────────────────────────


class TestDispatcher:
    def test_emits_both_families(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(tmp_path, "acme", "New.mcs.yml", GOOD_TOPIC)
        ids = [r.checkpoint_id for r in tp.run_topic_checks(_Runner())]
        assert ids == ["TOPIC-TRIGGER-001", "TOPIC-INTEGRATION-001"]

    def test_emitter_failure_degrades_to_warning(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(tmp_path, "acme", "New.mcs.yml", GOOD_TOPIC)

        def _boom(_runner):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(tp, "_check_topic_triggers", _boom)
        results = tp.run_topic_checks(_Runner())
        by_id = _by_id(results)
        assert by_id["TOPIC-TRIGGER-001"].status == Status.WARNING.value
        assert "Unable to run TOPIC-TRIGGER-*" in by_id["TOPIC-TRIGGER-001"].result
        assert by_id["TOPIC-TRIGGER-001"].roles == [Role.ESS_MAKER.value]
        # The integration family still emitted normally.
        assert by_id["TOPIC-INTEGRATION-001"].status == Status.PASSED.value

    def test_enumeration_failure_degrades_both_to_warning(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        def _boom(_runner):
            raise RuntimeError("fs blew up")

        monkeypatch.setattr(tp, "_enumerate_new_topics", _boom)
        results = tp.run_topic_checks(_Runner())
        by_id = _by_id(results)
        assert by_id["TOPIC-TRIGGER-001"].status == Status.WARNING.value
        assert by_id["TOPIC-INTEGRATION-001"].status == Status.WARNING.value
        for r in results:
            assert r.priority == Priority.HIGH.value
            assert r.roles == [Role.ESS_MAKER.value]
