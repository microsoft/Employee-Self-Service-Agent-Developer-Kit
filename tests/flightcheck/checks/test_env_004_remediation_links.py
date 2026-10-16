# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ENV-004 (Declarative Agent connection references + GRS commit pin).

ENV-004 was re-pointed from the Dataverse ``connectionreference`` table to the
Declarative Agent minimalBots components + ALM configure API (validated tier;
the same ``connectionReferenceChanges`` shape the shipped native ``DA-CONN-001``
check consumes). This module drives ``_check_connections_and_refs`` directly
against a faked ``runner.agentbuilder`` built from the validated
``agentbuilder_connectivity`` mocks.

Two halves are covered:
  * Connection-reference classification — bound (PASS) vs unbound (FAIL), the
    per-ref ``ENV-004-UR-*`` detail rows, and the SKIP/WARNING guards.
  * GRS commit pin (``ENV-004-GRS``) — opt-in SKIP, PASS on a matching commit,
    FAIL on mismatch, WARNING on a configure read error, and the fold of the
    GRS verdict into the ENV-004 summary status.

Per tests/AGENTS.md, every GOOD/BAD/WARNING assertion pins a phrase from both
``result`` and ``remediation``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy

import pytest

from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as ab

require_validated_mock(ab)


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Make ``flightcheck.*`` importable from the kit's scripts dir."""
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


# ─────────────────────────────────────────────────────────────────────
# Fakes. The check reads only runner.agentbuilder (fetch_components +
# get_realm_configuration), runner.config (agent botId + GRS keys), and
# runner.env_id (best-effort remediation deep link).
# ─────────────────────────────────────────────────────────────────────

_MISSING = object()
_BOT_IDS = {
    "hr": "00000000-0000-4000-8000-00000000aaaa",
    "it": "00000000-0000-4000-8000-00000000bbbb",
}


def _active_components(payload):
    """Remediation-only mutations of the captured native action contract.

    End-to-end response-shape coverage lives in test_env_004_workday_coverage
    and replays env004_dependencies.yaml through the real HTTP clients.
    """
    payload = deepcopy(payload)
    references = payload.get("connectionReferenceChanges")
    if isinstance(references, list):
        payload["botComponentChanges"] = [{
            "component": {
                "$kind": "DialogComponent", "status": "Active",
                "dialog": {"actions": [{
                    "$kind": "InvokeConnectorAction",
                    "connectionReference": row["connectionReference"]["connectionReferenceLogicalName"],
                } for row in references]},
            },
        }]
    return payload


class _FakeAgentBuilder:
    def __init__(
        self,
        *,
        components=_MISSING,
        configuration=None,
        configure_error=None,
    ):
        self._components = (
            ab.components_with_references()
            if components is _MISSING
            else components
        )
        self._configuration = configuration
        self._configure_error = configure_error

    def fetch_components(self, _agent_id):
        return _active_components(self._components)

    def get_agent(self, agent_id):
        return {"botId": agent_id}

    def get_realm_configuration(self, _agent_id, realm):
        # Mirror the real client's contract so a test can't pass an int-typed
        # realm the production code would reject.
        if type(realm) is not int:
            raise ValueError("Realm must be the numeric Dev/Test/Prod value.")
        if self._configure_error is not None:
            raise self._configure_error
        return self._configuration


class _PerBotAgentBuilder:
    """AgentBuilder fake that returns a distinct configure result per botId.

    Lets a test set up one agent that reports a mismatched commit and another
    whose configure read raises, to prove a confirmed mismatch (FAILED) wins
    over a later agent's transient read error (WARNING) across agents.
    """

    def __init__(self, *, components, configs=None, errors=None):
        self._components = components
        self._configs = configs or {}
        self._errors = errors or {}
        self.configure_calls = []

    def fetch_components(self, _agent_id):
        return _active_components(self._components)

    def get_agent(self, agent_id):
        return {"botId": agent_id}

    def get_realm_configuration(self, agent_id, realm):
        self.configure_calls.append((agent_id, realm))
        if type(realm) is not int:
            raise ValueError("Realm must be the numeric Dev/Test/Prod value.")
        if agent_id in self._errors:
            raise self._errors[agent_id]
        return self._configs.get(agent_id)


def _runner(*, agentbuilder=None, config=_MISSING, env_id="env-deeplinks"):
    references = (
        agentbuilder._components.get("connectionReferenceChanges", [])
        if agentbuilder is not None else []
    )
    physical = {}
    if isinstance(references, list):
        for row in references:
            ref = row["connectionReference"]
            if ref.get("connectionId") is not None:
                physical[ref["connectionId"]] = {
                    "name": ref["connectionId"],
                    "properties": {"apiId": ref["connectorId"]},
                }
    return SimpleNamespace(
        agentbuilder=agentbuilder,
        config=(
            {"agent": {"botId": ab.MOCK_AGENT_ID}}
            if config is _MISSING
            else config
        ),
        env_id=env_id,
        connectivity=SimpleNamespace(list_connections=lambda _env: list(physical.values())),
    )


def _check(runner):
    from flightcheck.checks.environment import _check_connections_and_refs

    return _check_connections_and_refs(runner)


def _by_id(results):
    return {r.checkpoint_id: r for r in results}


def _bound(connector="shared_service-now", connection_id="conn-good"):
    return ab.connection_reference_change(
        connector=connector, connection_id=connection_id
    )


def _unbound(connector="shared_service-now"):
    return ab.connection_reference_change(connector=connector, connection_id=None)


# ─────────────────────────────────────────────────────────────────────
# Connection-reference classification.
# ─────────────────────────────────────────────────────────────────────


class TestConnectionReferences:
    def test_all_bound_passes(self):
        components = ab.components_with_references(
            references=[_bound(), _bound(connector="shared_workdaysoap", connection_id="conn-workday")]
        )
        runner = _runner(agentbuilder=_FakeAgentBuilder(components=components))

        summary = _by_id(_check(runner))["ENV-004"]

        assert summary.status == "Passed"
        assert "2 required reference(s)" in summary.result
        assert "2 bound" in summary.result
        assert "unbound" not in summary.result

    def test_unbound_ref_fails_with_detail_row(self):
        components = ab.components_with_references(
            references=[_bound(), _unbound(connector="shared_workdaysoap")]
        )
        runner = _runner(agentbuilder=_FakeAgentBuilder(components=components))

        results = _check(runner)
        by_id = _by_id(results)
        summary = by_id["ENV-004"]

        assert summary.status == "Failed"
        assert "1 unbound" in summary.result
        # Detail row names the offending ref and points at the Objects pane.
        detail = by_id["ENV-004-UR-001"]
        assert detail.status == "Failed"
        assert "shared_workdaysoap" in detail.description
        assert "No connection bound to this reference" in detail.result
        assert "Connection references" in detail.remediation
        assert "bind" in detail.remediation.lower()

    def test_failed_summary_deep_links_to_solutions_and_ref_doc(self):
        components = ab.components_with_references(references=[_unbound()])
        runner = _runner(agentbuilder=_FakeAgentBuilder(components=components))

        summary = _by_id(_check(runner))["ENV-004"]

        assert summary.status == "Failed"
        assert (
            "make.powerapps.com/environments/env-deeplinks/solutions"
            in summary.remediation
        )
        assert "create-connection-reference" in summary.doc_link

    def test_unbound_without_env_id_falls_back_to_prose(self):
        components = ab.components_with_references(references=[_unbound()])
        runner = _runner(
            agentbuilder=_FakeAgentBuilder(components=components), env_id=None
        )

        summary = _by_id(_check(runner))["ENV-004"]

        assert summary.status == "Failed"
        assert "make.powerapps.com" not in summary.remediation
        assert "Connection references" in summary.remediation

    def test_no_agentbuilder_client_skips(self):
        summary = _by_id(_check(_runner(agentbuilder=None)))["ENV-004"]

        assert summary.status == "Blocked"
        assert "exact agent target and AgentBuilder read access" in summary.result
        assert "--agent-id" in summary.remediation

    def test_no_configured_botid_skips(self):
        runner = _runner(
            agentbuilder=_FakeAgentBuilder(), config={}
        )
        summary = _by_id(_check(runner))["ENV-004"]

        assert summary.status == "Blocked"
        assert "exact agent target" in summary.result

    def test_malformed_changeset_degrades_to_warning(self):
        runner = _runner(
            agentbuilder=_FakeAgentBuilder(
                components={"connectionReferenceChanges": {"unexpected": "dict"}}
            )
        )
        summary = _by_id(_check(runner))["ENV-004"]

        assert summary.status == "Warning"
        assert "dependency discovery incomplete" in summary.result
        assert "ValueError" in summary.result
        assert "Restore read access" in summary.remediation

    def test_references_unioned_across_configured_agents(self):
        # A logical name is local to an agent, never a cross-agent dedup key.
        shared = ab.connection_reference_change(
            connector="shared_service-now",
            connection_id=None,
            logical_name="gptagent_ess.shared_ref",
        )

        class _TwoAgent(_FakeAgentBuilder):
            def fetch_components(self, _agent_id):
                return _active_components(ab.components_with_references(references=[shared]))

        runner = _runner(
            agentbuilder=_TwoAgent(),
            config={
                "agents": [
                    {"botId": "00000000-0000-0000-0000-000000001001"},
                    {"botId": "00000000-0000-0000-0000-000000001002"},
                ]
            },
        )
        results = _check(runner)
        by_id = _by_id(results)

        assert by_id["ENV-004"].result.startswith("2 required reference(s)")
        assert "ENV-004-UR-001" in by_id
        assert "ENV-004-UR-002" in by_id


# ─────────────────────────────────────────────────────────────────────
# GRS commit pin (ENV-004-GRS).
# ─────────────────────────────────────────────────────────────────────


class TestGrsCommitPin:
    @pytest.mark.parametrize("active_slug", ["hr", "it"])
    def test_each_agent_uses_its_own_pin_and_realm(self, active_slug):
        client = _PerBotAgentBuilder(
            components=ab.components_with_references(references=[_bound()]),
            configs={
                _BOT_IDS["hr"]: ab.configuration(commit_sha="aaaa"),
                _BOT_IDS["it"]: ab.configuration(commit_sha="bbbb"),
            },
        )
        runner = _runner(agentbuilder=client, config={
            "activeAgent": active_slug,
            "agents": [
                {"slug": "hr", "botId": _BOT_IDS["hr"],
                 "expectedGrsCommitSha": "aaaa", "grsRealm": "Dev"},
                {"slug": "it", "botId": _BOT_IDS["it"],
                 "expectedGrsCommitSha": "bbbb", "grsRealm": "Prod"},
            ],
        })

        grs = _by_id(_check(runner))["ENV-004-GRS"]

        assert grs.status == "Passed"
        assert client.configure_calls == [(_BOT_IDS["hr"], 0), (_BOT_IDS["it"], 2)]
        assert "aaaa" in grs.result and "bbbb" in grs.result
        assert grs.remediation == ""

    @pytest.mark.parametrize("pinned_slug", ["hr", "it"])
    def test_agent_pin_does_not_opt_in_unpinned_sibling(self, pinned_slug):
        client = _PerBotAgentBuilder(
            components=ab.components_with_references(references=[_bound()]),
            configs={_BOT_IDS[pinned_slug]: ab.configuration()},
        )
        agents = [
            {"slug": slug, "botId": _BOT_IDS[slug]} for slug in ("hr", "it")
        ]
        next(a for a in agents if a["slug"] == pinned_slug)[
            "expectedGrsCommitSha"
        ] = ab.COMMIT_SHA

        grs = _by_id(_check(_runner(agentbuilder=client, config={
            "activeAgent": "hr", "agents": agents,
        })))["ENV-004-GRS"]

        assert grs.status == "Passed"
        assert client.configure_calls == [(_BOT_IDS[pinned_slug], 0)]
        assert "not judged" in grs.result
        assert grs.remediation == ""

    def test_agent_override_and_global_default_are_independent(self):
        client = _PerBotAgentBuilder(
            components=ab.components_with_references(references=[_bound()]),
            configs={
                _BOT_IDS["hr"]: ab.configuration(commit_sha="aaaa"),
                _BOT_IDS["it"]: ab.configuration(commit_sha="bbbb"),
            },
        )

        grs = _by_id(_check(_runner(agentbuilder=client, config={
            "expectedGrsCommitSha": "bbbb", "grsRealm": "Prod",
            "agents": [
                {"botId": _BOT_IDS["hr"], "expectedGrsCommitSha": "aaaa", "grsRealm": 0},
                {"botId": _BOT_IDS["it"]},
            ],
        })))["ENV-004-GRS"]

        assert grs.status == "Passed"
        assert client.configure_calls == [(_BOT_IDS["hr"], 0), (_BOT_IDS["it"], 2)]
        assert "realm Dev" in grs.result and "realm Prod" in grs.result
        assert grs.remediation == ""

    @pytest.mark.parametrize("realm", [0, 1, 2])
    def test_numeric_agent_realm_overrides_global(self, realm):
        client = _PerBotAgentBuilder(
            components=ab.components_with_references(references=[_bound()]),
            configs={_BOT_IDS["hr"]: ab.configuration()},
        )

        grs = _by_id(_check(_runner(agentbuilder=client, config={
            "expectedGrsCommitSha": ab.COMMIT_SHA, "grsRealm": "Prod",
            "agent": {"botId": _BOT_IDS["hr"], "minimalBotsAlmRealm": realm},
        })))["ENV-004-GRS"]

        assert grs.status == "Passed"
        assert client.configure_calls == [(_BOT_IDS["hr"], realm)]
        assert ab.COMMIT_SHA in grs.result
        assert grs.remediation == ""

    @pytest.mark.parametrize("value", ["", False, 3])
    def test_invalid_present_realm_does_not_fall_back(self, value):
        client = _PerBotAgentBuilder(
            components=ab.components_with_references(references=[_bound()]),
            configs={_BOT_IDS["hr"]: ab.configuration()},
        )

        grs = _by_id(_check(_runner(agentbuilder=client, config={
            "expectedGrsCommitSha": ab.COMMIT_SHA, "grsRealm": "Prod",
            "agent": {"botId": _BOT_IDS["hr"], "minimalBotsAlmRealm": value},
        })))["ENV-004-GRS"]

        assert grs.status == "Failed"
        assert client.configure_calls == []
        assert "is invalid" in grs.result
        assert "Dev, Test, or Prod" in grs.remediation

    def test_empty_agent_pin_does_not_inherit_global_pin(self):
        client = _PerBotAgentBuilder(
            components=ab.components_with_references(references=[_bound()]),
        )

        grs = _by_id(_check(_runner(agentbuilder=client, config={
            "expectedGrsCommitSha": ab.COMMIT_SHA,
            "agent": {"botId": _BOT_IDS["hr"], "expectedGrsCommitSha": ""},
        })))["ENV-004-GRS"]

        assert grs.status == "Skipped"
        assert client.configure_calls == []
        assert "No expected GRS commit SHA" in grs.result

    def test_null_agent_settings_allow_shared_defaults(self):
        client = _PerBotAgentBuilder(
            components=ab.components_with_references(references=[_bound()]),
            configs={_BOT_IDS["hr"]: ab.configuration(), _BOT_IDS["it"]: ab.configuration()},
        )

        grs = _by_id(_check(_runner(agentbuilder=client, config={
            "expectedGrsCommitSha": ab.COMMIT_SHA, "grsRealm": "Test",
            "agents": [
                {"botId": _BOT_IDS["hr"], "expectedGrsCommitSha": None, "grsRealm": None},
                {"botId": _BOT_IDS["it"]},
            ],
        })))["ENV-004-GRS"]

        assert grs.status == "Passed"
        assert client.configure_calls == [(_BOT_IDS["hr"], 1), (_BOT_IDS["it"], 1)]
        assert ab.COMMIT_SHA in grs.result
        assert grs.remediation == ""

    @pytest.mark.parametrize("value", [False, 0])
    def test_invalid_present_pin_does_not_inherit_global_pin(self, value):
        client = _PerBotAgentBuilder(
            components=ab.components_with_references(references=[_bound()]),
        )

        grs = _by_id(_check(_runner(agentbuilder=client, config={
            "expectedGrsCommitSha": ab.COMMIT_SHA,
            "agent": {"botId": _BOT_IDS["hr"], "expectedGrsCommitSha": value},
        })))["ENV-004-GRS"]

        assert grs.status == "Failed"
        assert client.configure_calls == []
        assert "commit SHA must be a string" in grs.result
        assert "expectedGrsCommitSha" in grs.remediation

    def test_missing_subject_id_never_borrows_sibling(self):
        from flightcheck.checks.environment import _env004_grs_commit_pin_result

        client = _PerBotAgentBuilder(components=ab.components_with_references())
        runner = _runner(agentbuilder=client, config={
            "activeAgent": "hr",
            "agents": [
                {"slug": "hr", "expectedGrsCommitSha": ab.COMMIT_SHA},
                {"slug": "it", "botId": _BOT_IDS["it"]},
            ],
        })

        grs = _env004_grs_commit_pin_result(runner)

        assert grs.status == "Warning"
        assert client.configure_calls == []
        assert "hr" in grs.result and "botId not available" in grs.result
        assert "records the agent botId" in grs.remediation

    def test_single_agent_copy_does_not_override_canonical_sibling(self):
        client = _PerBotAgentBuilder(
            components=ab.components_with_references(references=[_bound()]),
            configs={_BOT_IDS["hr"]: ab.configuration(commit_sha="aaaa")},
        )

        grs = _by_id(_check(_runner(agentbuilder=client, config={
            "agents": [{"botId": _BOT_IDS["hr"], "expectedGrsCommitSha": "aaaa"}],
            "agent": {"botId": _BOT_IDS["hr"].upper(), "expectedGrsCommitSha": "stale"},
        })))["ENV-004-GRS"]

        assert grs.status == "Passed"
        assert client.configure_calls == [(_BOT_IDS["hr"], 0)]
        assert "aaaa" in grs.result
        assert grs.remediation == ""

    def test_pin_skipped_and_omitted_from_summary_when_no_expected_sha(self):
        components = ab.components_with_references(references=[_bound()])
        runner = _runner(agentbuilder=_FakeAgentBuilder(components=components))

        results = _check(runner)
        by_id = _by_id(results)

        assert by_id["ENV-004-GRS"].status == "Skipped"
        assert "No expected GRS commit SHA is configured" in by_id["ENV-004-GRS"].result
        # A SKIPPED pin does not appear in the summary and does not change PASS.
        assert by_id["ENV-004"].status == "Passed"
        assert "GRS commit pin" not in by_id["ENV-004"].result

    def test_matching_commit_passes_and_folds_into_summary(self):
        components = ab.components_with_references(references=[_bound()])
        runner = _runner(
            agentbuilder=_FakeAgentBuilder(
                components=components, configuration=ab.configuration()
            ),
            config={
                "agent": {"botId": ab.MOCK_AGENT_ID},
                "expectedGrsCommitSha": ab.COMMIT_SHA,
            },
        )
        by_id = _by_id(_check(runner))

        assert by_id["ENV-004-GRS"].status == "Passed"
        assert ab.COMMIT_SHA in by_id["ENV-004-GRS"].result
        assert by_id["ENV-004"].status == "Passed"
        assert "GRS commit pin: Passed" in by_id["ENV-004"].result

    def test_mismatched_commit_fails_and_forces_summary_fail(self):
        components = ab.components_with_references(references=[_bound()])
        runner = _runner(
            agentbuilder=_FakeAgentBuilder(
                components=components,
                configuration=ab.configuration(commit_sha="deadbeef"),
            ),
            config={
                "agent": {"botId": ab.MOCK_AGENT_ID},
                "expectedGrsCommitSha": ab.COMMIT_SHA,
            },
        )
        by_id = _by_id(_check(runner))

        grs = by_id["ENV-004-GRS"]
        assert grs.status == "Failed"
        assert "deadbeef" in grs.result
        assert "Publish or import the ESS agent solution" in grs.remediation
        # Even though every reference is bound, the GRS mismatch fails ENV-004.
        assert by_id["ENV-004"].status == "Failed"
        assert "GRS commit pin: Failed" in by_id["ENV-004"].result
        # A targeted `--checkpoint ENV-004` run filters out the ENV-004-GRS
        # detail row, so the summary must carry the GRS reason + remediation.
        assert "deadbeef" in by_id["ENV-004"].result
        assert (
            "Publish or import the ESS agent solution"
            in by_id["ENV-004"].remediation
        )

    def test_mismatch_wins_over_later_read_error_across_agents(self):
        """A confirmed commit mismatch must not be masked by a later agent's
        transient configure read error.

        Regression: the GRS loop used to early-return WARNING on the first
        read error, so a real mismatch on an earlier agent was downgraded to
        a soft warning when a subsequent agent's read flaked. FAILED (a
        confirmed bad deploy) must win over WARNING (a transient read error).
        """
        components = ab.components_with_references(references=[_bound()])
        runner = _runner(
            agentbuilder=_PerBotAgentBuilder(
                components=components,
                configs={"00000000-0000-0000-0000-000000001001": ab.configuration(commit_sha="deadbeef")},
                errors={"00000000-0000-0000-0000-000000001002": RuntimeError("boom")},
            ),
            config={
                "agents": [
                    {"slug": "hr", "botId": "00000000-0000-0000-0000-000000001001"},
                    {"slug": "it", "botId": "00000000-0000-0000-0000-000000001002"},
                ],
                "expectedGrsCommitSha": ab.COMMIT_SHA,
            },
        )
        by_id = _by_id(_check(runner))

        grs = by_id["ENV-004-GRS"]
        assert grs.status == "Failed"
        assert "deadbeef" in grs.result
        assert "Publish or import the ESS agent solution" in grs.remediation
        # The GRS mismatch forces the ENV-004 summary to FAILED, not WARNING.
        assert by_id["ENV-004"].status == "Failed"
        assert "GRS commit pin: Failed" in by_id["ENV-004"].result

    def test_missing_commit_in_configure_fails(self):
        components = ab.components_with_references(references=[_bound()])
        runner = _runner(
            agentbuilder=_FakeAgentBuilder(
                components=components,
                configuration=ab.configuration(commit_sha=""),
            ),
            config={
                "agent": {"botId": ab.MOCK_AGENT_ID},
                "expectedGrsCommitSha": ab.COMMIT_SHA,
            },
        )
        grs = _by_id(_check(runner))["ENV-004-GRS"]

        assert grs.status == "Failed"
        assert "returned no commitSha" in grs.result
        assert "Publish or import the ESS agent solution" in grs.remediation

    def test_configure_read_error_warns(self):
        components = ab.components_with_references(references=[_bound()])
        runner = _runner(
            agentbuilder=_FakeAgentBuilder(
                components=components,
                configure_error=RuntimeError("boom"),
            ),
            config={
                "agent": {"botId": ab.MOCK_AGENT_ID},
                "expectedGrsCommitSha": ab.COMMIT_SHA,
            },
        )
        by_id = _by_id(_check(runner))

        grs = by_id["ENV-004-GRS"]
        assert grs.status == "Warning"
        assert "Could not read minimalBots ALM configure" in grs.result
        assert "RuntimeError: boom" in grs.result
        assert "signed in to Copilot Studio" in grs.remediation
        # A GRS WARNING folds into the summary as a WARNING (refs all bound).
        assert by_id["ENV-004"].status == "Warning"
        assert "GRS commit pin: Warning" in by_id["ENV-004"].result
        # The summary carries the GRS reason + remediation for targeted runs.
        assert "Could not read minimalBots ALM configure" in by_id["ENV-004"].result
        assert "signed in to Copilot Studio" in by_id["ENV-004"].remediation

    def test_invalid_realm_fails(self):
        components = ab.components_with_references(references=[_bound()])
        runner = _runner(
            agentbuilder=_FakeAgentBuilder(
                components=components, configuration=ab.configuration()
            ),
            config={
                "agent": {"botId": ab.MOCK_AGENT_ID},
                "expectedGrsCommitSha": ab.COMMIT_SHA,
                "grsRealm": "Staging",
            },
        )
        grs = _by_id(_check(runner))["ENV-004-GRS"]

        assert grs.status == "Failed"
        assert "'Staging' is invalid" in grs.result
        assert "Dev, Test, or Prod" in grs.remediation

    def test_dev_realm_zero_is_valid(self):
        # Regression guard: realm Dev maps to the int 0, which is falsy; the
        # check must treat 0 as a valid realm, not as "unconfigured".
        components = ab.components_with_references(references=[_bound()])
        runner = _runner(
            agentbuilder=_FakeAgentBuilder(
                components=components, configuration=ab.configuration()
            ),
            config={
                "agent": {"botId": ab.MOCK_AGENT_ID},
                "expectedGrsCommitSha": ab.COMMIT_SHA,
                "grsRealm": "Dev",
            },
        )
        grs = _by_id(_check(runner))["ENV-004-GRS"]

        assert grs.status == "Passed"
        assert "realm Dev" in grs.result


# ─────────────────────────────────────────────────────────────────────
# Maker URL builders (generic helpers ENV-004 remediations rely on).
# ─────────────────────────────────────────────────────────────────────


def test_maker_solutions_url_targets_powerapps():
    from flightcheck.checks._maker_urls import maker_solutions_url

    assert maker_solutions_url("env-123") == (
        "https://make.powerapps.com/environments/env-123/solutions"
    )
