# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit + integration tests for checks/workday_extension.py (skill-5
install-workday-extension-pack, master-checklist rows S5.3-S5.5, S5.7, S5.8).

Coverage per emitter:
  * WD-CONN-AUTH-001 — always-MANUAL echo (never PASSED); echoes the observed
    connection auth parameter set + owner when the ff0df ref resolves to a BAP
    connection, degrades gracefully when it does not. Cached-ref read + a
    best-effort Power Platform admin owner echo — no cassette required (the
    admin connections listing is the ``validated`` pp_admin mock).
  * DV-CONN-001 — PASS/FAIL/NOT_CONFIGURED/SKIPPED over a documented-tier
    Dataverse ``connectionreferences`` read (stubbed with ``responses``); owner
    echo via the ``validated`` pp_admin mock.
  * WD-REST-001 — pure-config check (restBaseUrl trimmed to '/api').
  * WD-REST-002 — pure local-file check (user-context redirect topic);
    SKIPPED on the legacy install path.
  * WD-NET-001 — always-MANUAL InfoSec/IT attestation (never PASSED).

Every GOOD/BAD/MANUAL assertion pins a phrase from BOTH ``result`` and
``remediation`` (tests/AGENTS.md), and the never-raise WARNING guard is
exercised directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import dataverse as dv
from tests.mocks import pp_admin as pp

require_validated_mock(dv)
require_validated_mock(pp)

from flightcheck.checks import workday_extension as wx  # noqa: E402
from flightcheck.runner import Priority, Role, Status  # noqa: E402

_DV_CONNECTOR_ID = (
    "/providers/Microsoft.PowerApps/apis/shared_commondataserviceforapps"
)


# ─────────────────────────────────────────────────────────────────────
# Minimal runner. The emitters read only these attributes; anything the
# test does not set defaults to "unavailable" so each branch is reachable.
# ─────────────────────────────────────────────────────────────────────


class _FakePPAdmin:
    """Stand-in for FlightCheckRunner.pp_admin. Only ``get_connections`` is
    consumed (owner/auth echo)."""

    def __init__(self, connections: list[dict[str, Any]] | dict[str, Any]):
        self._connections = connections

    def get_connections(self, _env_id: str):
        return self._connections


@dataclass
class _Runner:
    config: Any = field(default_factory=dict)
    env_url: str | None = None
    dv_token: str | None = None
    pp_admin: Any = None
    env_id: str | None = None
    _workday_connection_refs: list[dict[str, Any]] = field(default_factory=list)


class _BoomConfig:
    """A config whose ``.get`` raises — exercises the per-emitter WARNING
    guard for the config-reading emitters. Truthy so ``config or {}`` keeps
    it."""

    def __bool__(self) -> bool:
        return True

    def get(self, *_a: Any, **_k: Any):
        raise RuntimeError("boom")


def _by_id(results):
    return {r.checkpoint_id: r for r in results}


def _dv_ref(*, connection_id, statuscode=1):
    """A Dataverse connection reference matching the extension pack's shipped
    ref (connector shared_commondataserviceforapps, logical-name suffix
    92b66)."""
    return dv.connection_ref(
        logical_name="msdyn_sharedcommondataserviceforapps_92b66",
        display_name="Microsoft Dataverse",
        connector_id=_DV_CONNECTOR_ID,
        connection_id=connection_id,
        statuscode=statuscode,
    )


def _register_refs(base_url: str, refs: list[dict[str, Any]]) -> None:
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/connectionreferences",
        json=dv.collection(refs),
        status=200,
    )


# ─────────────────────────────────────────────────────────────────────
# WD-CONN-AUTH-001 — always MANUAL echo (S5.3).
# ─────────────────────────────────────────────────────────────────────


class TestConnectionAuth:
    def test_echoes_observed_param_set_and_owner_but_stays_manual(self):
        conn = pp.connection(
            name="wd-conn-1",
            api_name="shared_workdaysoap",
            extra_properties={
                "connectionParametersSet": {"name": "entraIntegrated"},
                "accountName": "maker@contoso.com",
            },
        )
        runner = _Runner(
            pp_admin=_FakePPAdmin([conn]),
            env_id="env-1",
            _workday_connection_refs=[
                dv.connection_ref(
                    logical_name="new_sharedworkdaysoap_ff0df",
                    display_name="OAuthUser",
                    connector_id=dv.WORKDAY_SOAP_CONNECTOR_ID,
                    connection_id="wd-conn-1",
                )
            ],
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-CONN-AUTH-001"]

        assert r.status == Status.MANUAL.value
        assert r.category == "Workday Extension"
        assert r.priority == Priority.HIGH.value
        assert r.roles == [Role.ESS_MAKER.value]
        # Echoes the observed parameter-set value + owner for confirmation.
        assert "entraIntegrated" in r.result
        assert "maker@contoso.com" in r.result
        assert "Microsoft Entra ID Integrated" in r.result
        # Remediation names the exact auth type + the re-create path.
        assert "Microsoft Entra ID Integrated" in r.remediation
        assert "re-create" in r.remediation.lower()

    def test_ref_present_but_connection_not_found_still_manual(self):
        runner = _Runner(
            pp_admin=_FakePPAdmin([]),
            env_id="env-1",
            _workday_connection_refs=[
                dv.connection_ref(
                    logical_name="new_sharedworkdaysoap_ff0df",
                    display_name="OAuthUser",
                    connector_id=dv.WORKDAY_SOAP_CONNECTOR_ID,
                    connection_id="missing-conn",
                )
            ],
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-CONN-AUTH-001"]

        assert r.status == Status.MANUAL.value
        assert "could not be read" in r.result
        assert "Microsoft Entra ID Integrated" in r.remediation

    def test_no_cached_ref_still_manual(self):
        runner = _Runner(_workday_connection_refs=[])
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-CONN-AUTH-001"]

        assert r.status == Status.MANUAL.value
        assert "not found in the cached" in r.result
        assert "Microsoft Entra ID Integrated" in r.remediation

    def test_never_passes_regardless_of_state(self):
        # Even with a fully-resolved connection this checkpoint is an echo,
        # never an automated PASS — the fingerprint is unconfirmed.
        conn = pp.connection(
            name="wd-conn-1",
            api_name="shared_workdaysoap",
            extra_properties={
                "connectionParametersSet": {"name": "anything"},
            },
        )
        runner = _Runner(
            pp_admin=_FakePPAdmin([conn]),
            env_id="env-1",
            _workday_connection_refs=[
                dv.connection_ref(
                    logical_name="new_sharedworkdaysoap_ff0df",
                    display_name="OAuthUser",
                    connector_id=dv.WORKDAY_SOAP_CONNECTOR_ID,
                    connection_id="wd-conn-1",
                )
            ],
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-CONN-AUTH-001"]
        assert r.status != Status.PASSED.value


# ─────────────────────────────────────────────────────────────────────
# DV-CONN-001 — Dataverse connection binding (S5.4, PASS/FAIL).
# ─────────────────────────────────────────────────────────────────────


class TestDataverseConnection:
    @responses.activate
    def test_bound_active_with_owner_echo_passes(
        self, fake_dataverse_url, fake_token
    ):
        _register_refs(
            fake_dataverse_url,
            [_dv_ref(connection_id="dv-conn-active", statuscode=1)],
        )
        owner_conn = pp.connection(
            name="dv-conn-active",
            api_name="shared_commondataserviceforapps",
            extra_properties={"accountName": "maker@contoso.com"},
        )
        runner = _Runner(
            env_url=fake_dataverse_url,
            dv_token=fake_token,
            pp_admin=_FakePPAdmin([owner_conn]),
            env_id="env-1",
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["DV-CONN-001"]

        assert r.status == Status.PASSED.value
        assert "bound to an active" in r.result
        assert "maker@contoso.com" in r.result
        assert "your own account" in r.result

    @responses.activate
    def test_passes_without_pp_admin_notes_owner_unreadable(
        self, fake_dataverse_url, fake_token
    ):
        _register_refs(
            fake_dataverse_url,
            [_dv_ref(connection_id="dv-conn-active", statuscode=1)],
        )
        runner = _Runner(env_url=fake_dataverse_url, dv_token=fake_token)
        r = _by_id(wx.run_workday_extension_checks(runner))["DV-CONN-001"]

        assert r.status == Status.PASSED.value
        assert "owner could not be read" in r.result
        assert "your own account" in r.result

    @responses.activate
    def test_unbound_fails(self, fake_dataverse_url, fake_token):
        _register_refs(
            fake_dataverse_url, [_dv_ref(connection_id=None, statuscode=1)]
        )
        runner = _Runner(env_url=fake_dataverse_url, dv_token=fake_token)
        r = _by_id(wx.run_workday_extension_checks(runner))["DV-CONN-001"]

        assert r.status == Status.FAILED.value
        assert "unbound" in r.result
        assert "connectionid=null" in r.result
        assert "bind the Dataverse connection reference" in r.remediation

    @responses.activate
    def test_inactive_statuscode_fails(self, fake_dataverse_url, fake_token):
        _register_refs(
            fake_dataverse_url,
            [_dv_ref(connection_id="dv-conn-inactive", statuscode=2)],
        )
        runner = _Runner(env_url=fake_dataverse_url, dv_token=fake_token)
        r = _by_id(wx.run_workday_extension_checks(runner))["DV-CONN-001"]

        assert r.status == Status.FAILED.value
        assert "inactive" in r.result
        assert "statuscode=2" in r.result
        assert "Re-authenticate or re-bind" in r.remediation

    @responses.activate
    def test_missing_ref_not_configured(self, fake_dataverse_url, fake_token):
        # Only a Workday ref present — no Dataverse (92b66) ref.
        _register_refs(
            fake_dataverse_url,
            [
                dv.connection_ref(
                    logical_name="new_sharedworkdaysoap_ff0df",
                    display_name="OAuthUser",
                    connector_id=dv.WORKDAY_SOAP_CONNECTOR_ID,
                    connection_id="wd-conn-1",
                )
            ],
        )
        runner = _Runner(env_url=fake_dataverse_url, dv_token=fake_token)
        r = _by_id(wx.run_workday_extension_checks(runner))["DV-CONN-001"]

        assert r.status == Status.NOT_CONFIGURED.value
        assert "was not found in this environment" in r.result
        assert "Install/repair the Workday extension pack" in r.remediation

    def test_no_dv_token_skips(self):
        runner = _Runner(env_url="https://x.crm.dynamics.com", dv_token="")
        r = _by_id(wx.run_workday_extension_checks(runner))["DV-CONN-001"]

        assert r.status == Status.SKIPPED.value
        assert "Dataverse token not available" in r.result


# ─────────────────────────────────────────────────────────────────────
# WD-REST-001 — REST base URL trimmed to /api (S5.5).
# ─────────────────────────────────────────────────────────────────────


class TestRestBaseUrl:
    def test_trimmed_url_passes(self):
        runner = _Runner(config={"restBaseUrl": "https://wd.example.com/ccx/api"})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.PASSED.value
        assert "trimmed to '/api'" in r.result
        assert "https://wd.example.com/ccx/api" in r.result

    def test_trailing_slash_still_passes(self):
        runner = _Runner(config={"restBaseUrl": "https://wd.example.com/ccx/api/"})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.PASSED.value

    def test_untrimmed_url_fails(self):
        runner = _Runner(
            config={"restBaseUrl": "https://wd.example.com/ccx/api/staffing/v1"}
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.FAILED.value
        assert "not trimmed to '/api'" in r.result
        assert "https://wd.example.com/ccx/api/staffing/v1" in r.result
        assert "remove any trailing path" in r.remediation

    def test_absent_url_not_configured(self):
        runner = _Runner(config={})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.NOT_CONFIGURED.value
        assert "restBaseUrl is empty" in r.result
        assert "trim it to end at '/api'" in r.remediation


# ─────────────────────────────────────────────────────────────────────
# WD-REST-002 — user-context redirect wired (S5.7, local YAML).
# ─────────────────────────────────────────────────────────────────────


def _write_topic(tmp_path, agent: str, body: str):
    topics = tmp_path / "workspace" / "agents" / agent / "topics"
    topics.mkdir(parents=True, exist_ok=True)
    (topics / "user-context-setup.mcs.yml").write_text(body, encoding="utf-8")


class TestUserContextRedirect:
    def test_legacy_install_path_skips(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = _Runner(config={"installPath": "legacy"})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.SKIPPED.value
        assert "legacy install path" in r.result

    def test_no_agents_dir_not_configured(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = _Runner(config={})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.NOT_CONFIGURED.value
        assert "No agent workspace found" in r.result
        assert "fetch_and_setup" in r.remediation

    def test_agents_dir_but_no_topic_file_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "workspace" / "agents" / "acme" / "topics").mkdir(
            parents=True
        )
        runner = _Runner(config={})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "No user-context-setup.mcs.yml found" in r.result
        assert "WorkdaySystemGetUserContextV2" in r.remediation

    def test_topic_missing_redirect_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(tmp_path, "acme", "kind: AdaptiveDialog\n# no redirect here\n")
        runner = _Runner(config={})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "is missing for: acme" in r.result
        assert "WorkdaySystemGetUserContextV2" in r.result
        assert "BeginDialog" in r.remediation

    def test_wired_topic_passes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "acme",
            "kind: AdaptiveDialog\n"
            "  - kind: BeginDialog\n"
            "    dialog: cr123_WorkdaySystemGetUserContextV2\n",
        )
        runner = _Runner(config={})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.PASSED.value
        assert "WorkdaySystemGetUserContextV2" in r.result
        assert "acme" in r.result

    def test_one_of_two_agents_unwired_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "wired",
            "  - kind: BeginDialog\n    dialog: WorkdaySystemGetUserContextV2\n",
        )
        _write_topic(tmp_path, "broken", "kind: AdaptiveDialog\n")
        runner = _Runner(config={})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "broken" in r.result
        assert "wired" not in r.result.split("missing for:")[1]


# ─────────────────────────────────────────────────────────────────────
# WD-NET-001 — firewall allowlisting (S5.8, always MANUAL attestation).
# ─────────────────────────────────────────────────────────────────────


class TestNetworkAllowlist:
    def test_echoes_rest_and_soap_hosts_and_stays_manual(self):
        runner = _Runner(
            config={
                "restBaseUrl": "https://wd-rest.example.com/ccx/api",
                "soapBaseUrl": "https://wd-soap.example.com/ccx/service",
            }
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-NET-001"]

        assert r.status == Status.MANUAL.value
        assert r.roles == [Role.POWER_PLATFORM_ADMIN.value]
        assert "REST: wd-rest.example.com" in r.result
        assert "SOAP: wd-soap.example.com" in r.result
        assert "InfoSec/IT" in r.remediation
        assert "managed connectors" in r.remediation

    def test_missing_endpoints_show_marker_still_manual(self):
        runner = _Runner(config={})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-NET-001"]

        assert r.status == Status.MANUAL.value
        assert wx._NOT_CAPTURED in r.result

    def test_never_passes(self):
        runner = _Runner(
            config={"restBaseUrl": "https://h/ccx/api", "soapBaseUrl": "https://h/s"}
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-NET-001"]
        assert r.status != Status.PASSED.value


# ─────────────────────────────────────────────────────────────────────
# Dispatcher contract — emits all five, never raises.
# ─────────────────────────────────────────────────────────────────────


class TestDispatcher:
    def test_emits_all_five_checkpoints(self):
        runner = _Runner(config={})
        ids = [r.checkpoint_id for r in wx.run_workday_extension_checks(runner)]
        assert ids == [
            "WD-CONN-AUTH-001",
            "DV-CONN-001",
            "WD-REST-001",
            "WD-REST-002",
            "WD-NET-001",
        ]

    def test_emitter_failure_degrades_to_warning(self, monkeypatch):
        # A raising emitter must degrade to a WARNING for its own checkpoint
        # without aborting the remaining four.
        def _boom(_runner):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(wx, "_check_rest_base_url", _boom)
        results = wx.run_workday_extension_checks(_Runner(config={}))
        by_id = _by_id(results)

        assert len(results) == 5
        assert by_id["WD-REST-001"].status == Status.WARNING.value
        assert "Unable to run WD-REST-001" in by_id["WD-REST-001"].result
        assert by_id["WD-REST-001"].roles == [Role.ESS_MAKER.value]
        # The other four still emitted normally.
        assert by_id["WD-NET-001"].status == Status.MANUAL.value

    def test_config_reading_emitters_warn_on_boom_config(self):
        # A config whose .get raises breaks the three config-reading emitters;
        # each degrades to WARNING and the run still returns all five rows.
        results = wx.run_workday_extension_checks(_Runner(config=_BoomConfig()))
        by_id = _by_id(results)

        assert len(results) == 5
        for cp in ("WD-REST-001", "WD-REST-002", "WD-NET-001"):
            assert by_id[cp].status == Status.WARNING.value
            assert f"Unable to run {cp}" in by_id[cp].result
