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
  * WD-REST-001 — AgentBuilder components check
    (sharedConnectionParameters.values.restBaseUri trimmed to '/api').
  * WD-REST-002 — pure local-file check (user-context redirect topic);
    SKIPPED on the legacy install path.
  * WD-NET-001 — always-MANUAL InfoSec/IT attestation (never PASSED).

Every GOOD/BAD/MANUAL assertion pins a phrase from BOTH ``result`` and
``remediation`` (tests/AGENTS.md), and the never-raise WARNING guard is
exercised directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as ab
from tests.mocks import dataverse as dv
from tests.mocks import pp_admin as pp

require_validated_mock(ab)
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


class _FakeAgentBuilder:
    """Stand-in for FlightCheckRunner.agentbuilder. Only ``fetch_components``
    is consumed (WD-REST-001's connection-reference read)."""

    def __init__(self, components: dict[str, Any]):
        self._components = components

    def fetch_components(self, _agent_id: str):
        return self._components


class _PerBotAgentBuilder:
    """Stand-in for FlightCheckRunner.agentbuilder that routes
    ``fetch_components`` by agent id, so multi-agent selection can be
    exercised. Component shapes come from the validated
    ``agentbuilder_connectivity`` builders."""

    def __init__(self, components_by_bot: dict[str, Any]):
        self._components_by_bot = components_by_bot

    def fetch_components(self, agent_id: str):
        return self._components_by_bot[agent_id]


@dataclass
class _Runner:
    config: Any = field(default_factory=dict)
    agent_slug: str | None = None
    env_url: str | None = None
    dv_token: str | None = None
    pp_admin: Any = None
    agentbuilder: Any = None
    env_id: str | None = None
    agent_slug: str = ""
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

    def test_runtime_reference_is_used_for_auth_echo(self):
        conn = pp.connection(
            name="wd-runtime-conn",
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
                dv.workday_connection_refs_runtime()[0]
                | {"connectionid": "wd-runtime-conn"}
            ],
        )

        r = _by_id(
            wx.run_workday_extension_checks(runner)
        )["WD-CONN-AUTH-001"]

        assert r.status == Status.MANUAL.value
        assert "entraIntegrated" in r.result
        assert "maker@contoso.com" in r.result

    def test_mixed_runtime_and_legacy_auth_refs_do_not_select_by_order(self):
        runner = _Runner(
            _workday_connection_refs=[
                dv.connection_ref(
                    logical_name="new_sharedworkdaysoap_ff0df",
                    display_name="OAuthUser",
                    connector_id=dv.WORKDAY_SOAP_CONNECTOR_ID,
                    connection_id="legacy-conn",
                ),
                dv.workday_connection_refs_runtime()[0]
                | {"connectionid": "runtime-conn"},
            ],
        )

        r = _by_id(
            wx.run_workday_extension_checks(runner)
        )["WD-CONN-AUTH-001"]

        assert r.status == Status.MANUAL.value
        assert "multiple Workday connection references" in r.result
        assert "cannot determine which connection is active" in r.result

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
    def test_runtime_dataverse_reference_passes(
        self, fake_dataverse_url, fake_token
    ):
        runtime_ref = dv.workday_connection_refs_runtime()[1]
        _register_refs(fake_dataverse_url, [runtime_ref])
        runner = _Runner(
            env_url=fake_dataverse_url,
            dv_token=fake_token,
        )

        r = _by_id(
            wx.run_workday_extension_checks(runner)
        )["DV-CONN-001"]

        assert r.status == Status.PASSED.value
        assert (
            "msdyn_sharedcommondataserviceforapps_workdayruntime"
            in r.result
        )

    @responses.activate
    def test_mixed_runtime_and_legacy_dataverse_refs_warn(
        self, fake_dataverse_url, fake_token
    ):
        runtime_ref = dv.workday_connection_refs_runtime()[1]
        _register_refs(
            fake_dataverse_url,
            [_dv_ref(connection_id="legacy-dv"), runtime_ref],
        )
        runner = _Runner(
            env_url=fake_dataverse_url,
            dv_token=fake_token,
        )

        r = _by_id(wx.run_workday_extension_checks(runner))["DV-CONN-001"]

        assert r.status == Status.WARNING.value
        assert "Multiple ESS Dataverse connection references" in r.result
        assert "Remove obsolete Workday package references" in r.remediation

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


def _runner_with_refs(references, *, pp_admin=None, env_id=None):
    """A runner whose faked ``agentbuilder.fetch_components`` returns the given
    connection references and whose config names an active agent (botId)."""
    components = ab.components_with_references(references=references)
    return _Runner(
        config={"agent": {"botId": ab.MOCK_AGENT_ID}},
        agentbuilder=_FakeAgentBuilder(components),
        pp_admin=pp_admin,
        env_id=env_id,
    )


class TestRestBaseUrl:
    def _runner(self, *, rest_base_uri: str | None):
        return _runner_with_refs(
            [
                ab.workday_connection_reference(
                    shared_connection_parameters=(
                        ab.shared_connection_parameters(
                            rest_base_uri=rest_base_uri
                        )
                    )
                )
            ]
        )

    def test_trimmed_url_passes(self):
        runner = self._runner(rest_base_uri="https://wd.example.com/ccx/api")
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.PASSED.value
        assert "trimmed to '/api'" in r.result
        assert "https://wd.example.com/ccx/api" in r.result

    def test_trimmed_url_can_be_on_later_workday_ref(self):
        runner = _runner_with_refs(
            [
                ab.workday_connection_reference(
                    connection_id="mock-obo-connection",
                    logical_name=(
                        "gptagent_mockemployeeselfservice."
                        "msdyn_sharedworkdaysoap_ff0df"
                    ),
                ),
                ab.workday_connection_reference(
                    connection_id="mock-isu-connection",
                    logical_name=(
                        "gptagent_mockemployeeselfservice."
                        "msdyn_sharedworkdaysoap_0786a"
                    ),
                    shared_connection_parameters=(
                        ab.shared_connection_parameters(
                            rest_base_uri="https://wd.example.com/ccx/api"
                        )
                    ),
                ),
                ab.workday_connection_reference(
                    connection_id="mock-context-isu-connection",
                    logical_name=(
                        "gptagent_mockemployeeselfservice."
                        "msdyn_sharedworkdaysoap_d6081"
                    ),
                ),
            ]
        )

        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.PASSED.value
        assert "https://wd.example.com/ccx/api" in r.result

    def test_trailing_slash_still_passes(self):
        runner = self._runner(rest_base_uri="https://wd.example.com/ccx/api/")
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.PASSED.value

    def test_untrimmed_url_fails(self):
        runner = self._runner(
            rest_base_uri="https://wd.example.com/ccx/api/staffing/v1"
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.FAILED.value
        assert "not trimmed to '/api'" in r.result
        assert "https://wd.example.com/ccx/api/staffing/v1" in r.result
        assert "restBaseUri" in r.remediation
        assert "remove any trailing path" in r.remediation

    def test_absent_url_fails(self):
        runner = self._runner(rest_base_uri=None)
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.FAILED.value
        assert "restBaseUri is missing or empty" in r.result
        assert "restBaseUri is captured" in r.remediation

    def test_no_workday_ref_is_not_configured(self):
        """No Workday connection reference at all means Workday was never set
        up. WD-REST-001 must report NOT_CONFIGURED (which does not fail
        readiness), mirroring DV-CONN-001's "no ref" contract, rather than a
        hard FAILED that misfires on non-Workday tenants."""
        # components() carries only the ServiceNow reference, no Workday one.
        runner = _Runner(
            config={"agent": {"botId": ab.MOCK_AGENT_ID}},
            agentbuilder=_FakeAgentBuilder(ab.components()),
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.NOT_CONFIGURED.value
        assert "No Workday connection reference" in r.result
        assert "shared_workdaysoap" in r.result
        assert "install/repair the Workday extension pack" in r.remediation
        assert "If Workday is not used here" in r.remediation

    def test_no_agentbuilder_client_skips(self):
        runner = _Runner(config={"agent": {"botId": ab.MOCK_AGENT_ID}})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.SKIPPED.value
        assert "not available" in r.result
        assert "native AgentBuilder access" in r.remediation

    def test_no_active_agent_botid_skips(self):
        runner = _Runner(
            config={},
            agentbuilder=_FakeAgentBuilder(ab.components_with_references()),
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.SKIPPED.value
        assert "active-agent botId" in r.result
        assert "configured active-agent botId" in r.remediation

    def test_malformed_components_shape_degrades_to_warning(self):
        runner = _Runner(
            config={"agent": {"botId": ab.MOCK_AGENT_ID}},
            agentbuilder=_FakeAgentBuilder(
                {"connectionReferenceChanges": {"unexpected": "dict"}}
            ),
        )
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-001"]

        assert r.status == Status.WARNING.value
        assert "Unable to run WD-REST-001" in r.result
        assert "WD-REST-001" in r.remediation


# ─────────────────────────────────────────────────────────────────────
# WD-REST-002 — user-context redirect wired (S5.7, local YAML).
# ─────────────────────────────────────────────────────────────────────


def _write_component_map(
    tmp_path,
    agent: str,
    *,
    setup_file: str = "Setusercontext.mcs.yml",
    setup_path: str | None = None,
    target_file: str = "WorkdaySystemGetUserContextV2.mcs.yml",
    target_path: str | None = None,
    dialog: str | None = None,
):
    agent_dir = tmp_path / "workspace" / "agents" / agent
    agent_dir.mkdir(parents=True, exist_ok=True)
    component_map_path = agent_dir / ".component-map.json"
    component_map = (
        json.loads(component_map_path.read_text(encoding="utf-8"))
        if component_map_path.exists()
        else {}
    )
    component_map.update({
        setup_path or f"topics/{setup_file}": {
            "componentKind": "DialogComponent",
            "displayName": "[Admin] - User Context - Setup",
            "schemaName": "contoso.topic.Setusercontext",
        }
    })
    if dialog:
        component_map[target_path or f"topics/{target_file}"] = {
            "componentKind": "DialogComponent",
            "displayName": "Workday [System] - 1: Set User Context V2",
            "schemaName": dialog,
        }
    component_map_path.write_text(
        json.dumps(component_map),
        encoding="utf-8",
    )


def _write_topic(tmp_path, agent: str, body: str):
    topics = tmp_path / "workspace" / "agents" / agent / "topics"
    topics.mkdir(parents=True, exist_ok=True)
    (topics / "Setusercontext.mcs.yml").write_text(body, encoding="utf-8")
    _write_component_map(tmp_path, agent)


def _write_installed_topic(
    tmp_path,
    agent: str,
    dialog: str,
    *,
    create_file: bool = True,
):
    _write_component_map(tmp_path, agent, dialog=dialog)
    if create_file:
        topics = tmp_path / "workspace" / "agents" / agent / "topics"
        topics.mkdir(parents=True, exist_ok=True)
        (topics / "WorkdaySystemGetUserContextV2.mcs.yml").write_text(
            "kind: AdaptiveDialog\n",
            encoding="utf-8",
        )


class TestUserContextRedirect:
    def test_legacy_install_path_skips(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = _Runner(config={"installPath": "legacy"})
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.SKIPPED.value
        assert "legacy install path" in r.result

    def test_no_agents_dir_not_configured(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = _Runner(config={}, agent_slug="acme")
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.NOT_CONFIGURED.value
        assert "No agent workspace found" in r.result
        assert "fetch_and_setup" in r.remediation

    def test_agents_dir_but_no_topic_file_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "workspace" / "agents" / "acme" / "topics").mkdir(
            parents=True
        )
        _write_component_map(
            tmp_path,
            "acme",
            dialog="cr123_WorkdaySystemGetUserContextV3",
        )
        runner = _Runner(config={}, agent_slug="acme")
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "No mapped admin user-context topic found" in r.result
        assert "selected agent 'acme'" in r.result
        assert "mapped Workday user-context" in r.remediation

    def test_topic_missing_redirect_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(tmp_path, "acme", "kind: AdaptiveDialog\n# no redirect here\n")
        _write_installed_topic(
            tmp_path,
            "acme",
            "cr123_WorkdaySystemGetUserContextV3",
        )
        runner = _Runner(config={}, agent_slug="acme")
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "does not redirect" in r.result
        assert "WorkdaySystemGetUserContextV3" in r.result
        assert "BeginDialog" in r.remediation

    def test_wired_topic_passes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "acme",
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  kind: BeginDialog\n"
            "  dialog: cr123_WorkdaySystemGetUserContextV3\n",
        )
        _write_installed_topic(
            tmp_path,
            "acme",
            "cr123_WorkdaySystemGetUserContextV3",
        )
        runner = _Runner(config={}, agent_slug="acme")
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.PASSED.value
        assert "WorkdaySystemGetUserContextV3" in r.result
        assert "acme" in r.result

    def test_missing_mapped_target_topic_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "acme",
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  kind: BeginDialog\n"
            "  dialog: cr123_WorkdaySystemGetUserContextV3\n",
        )
        _write_installed_topic(
            tmp_path,
            "acme",
            "cr123_WorkdaySystemGetUserContextV3",
            create_file=False,
        )
        runner = _Runner(config={}, agent_slug="acme")

        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "No mapped Workday User Context V2 topic found" in r.result
        assert "mapped Workday user-context" in r.remediation

    def test_unsafe_mapped_target_topic_path_fails(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "acme",
            "kind: AdaptiveDialog\n",
        )
        _write_component_map(
            tmp_path,
            "acme",
            target_file="../outside.mcs.yml",
            dialog="cr123_WorkdaySystemGetUserContextV3",
        )
        runner = _Runner(config={}, agent_slug="acme")

        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "Workday User Context V2 topic path is unsafe" in r.result
        assert "mapped Workday user-context" in r.remediation

    @pytest.mark.parametrize(
        "mapped_path",
        [
            r"\outside.mcs.yml",
            r"D:outside.mcs.yml",
        ],
    )
    def test_windows_mapped_setup_topic_escape_fails(
        self,
        tmp_path,
        monkeypatch,
        mapped_path,
    ):
        monkeypatch.chdir(tmp_path)
        _write_component_map(
            tmp_path,
            "acme",
            setup_path=mapped_path,
            dialog="cr123_WorkdaySystemGetUserContextV3",
        )
        runner = _Runner(config={}, agent_slug="acme")

        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "admin user-context topic path is unsafe" in r.result
        assert "mapped Workday user-context" in r.remediation

    @pytest.mark.parametrize(
        "mapped_path",
        [
            r"\outside.mcs.yml",
            r"D:outside.mcs.yml",
        ],
    )
    def test_windows_mapped_target_topic_escape_fails(
        self,
        tmp_path,
        monkeypatch,
        mapped_path,
    ):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "acme",
            "kind: AdaptiveDialog\n",
        )
        _write_component_map(
            tmp_path,
            "acme",
            target_path=mapped_path,
            dialog="cr123_WorkdaySystemGetUserContextV3",
        )
        runner = _Runner(config={}, agent_slug="acme")

        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "Workday User Context V2 topic path is unsafe" in r.result
        assert "mapped Workday user-context" in r.remediation

    def test_comment_or_unrelated_field_does_not_count_as_redirect(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "acme",
            "kind: AdaptiveDialog\n"
            "# kind: BeginDialog\n"
            "# dialog: cr123_WorkdaySystemGetUserContextV3\n"
            "description: cr123_WorkdaySystemGetUserContextV3\n",
        )
        _write_installed_topic(
            tmp_path,
            "acme",
            "cr123_WorkdaySystemGetUserContextV3",
        )
        runner = _Runner(config={}, agent_slug="acme")

        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value

    def test_selected_agent_ignores_wired_sibling(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "wired",
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  kind: BeginDialog\n"
            "  dialog: cr123_WorkdaySystemGetUserContextV3\n",
        )
        _write_topic(tmp_path, "broken", "kind: AdaptiveDialog\n")
        _write_installed_topic(
            tmp_path,
            "wired",
            "cr123_WorkdaySystemGetUserContextV3",
        )
        _write_installed_topic(
            tmp_path,
            "broken",
            "cr999_WorkdaySystemGetUserContextV4",
        )
        runner = _Runner(config={}, agent_slug="broken")
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "WorkdaySystemGetUserContextV4" in r.result
        assert "WorkdaySystemGetUserContextV3" not in r.result

    def test_missing_selected_agent_does_not_scan_siblings(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "wired",
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  kind: BeginDialog\n"
            "  dialog: cr123_WorkdaySystemGetUserContextV3\n",
        )
        _write_installed_topic(
            tmp_path,
            "wired",
            "cr123_WorkdaySystemGetUserContextV3",
        )
        runner = _Runner(config={}, agent_slug="missing")
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "selected agent 'missing'" in r.result
        assert "wired" not in r.result

    def test_active_agent_scope_ignores_unrelated_unwired_agent(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "active",
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  kind: BeginDialog\n"
            "  dialog: WorkdaySystemGetUserContextV2\n",
        )
        _write_installed_topic(
            tmp_path,
            "active",
            "WorkdaySystemGetUserContextV2",
        )
        _write_topic(tmp_path, "unrelated", "kind: AdaptiveDialog\n")

        runner = _Runner(config={}, agent_slug="active")
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.PASSED.value
        assert "active" in r.result
        assert "unrelated" not in r.result

    def test_active_agent_scope_does_not_pass_from_other_agent(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        _write_topic(
            tmp_path,
            "other",
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  kind: BeginDialog\n"
            "  dialog: WorkdaySystemGetUserContextV2\n",
        )
        _write_installed_topic(
            tmp_path,
            "other",
            "WorkdaySystemGetUserContextV2",
        )
        _write_installed_topic(
            tmp_path,
            "active",
            "WorkdaySystemGetUserContextV3",
        )
        _write_topic(tmp_path, "active", "kind: AdaptiveDialog\n")

        runner = _Runner(config={}, agent_slug="active")
        r = _by_id(wx.run_workday_extension_checks(runner))["WD-REST-002"]

        assert r.status == Status.FAILED.value
        assert "active" in r.result
        assert "other" not in r.result


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
