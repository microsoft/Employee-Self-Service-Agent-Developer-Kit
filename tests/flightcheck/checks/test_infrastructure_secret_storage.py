# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for INFRA-011 (connector secret storage
safety) in solutions/ess-maker-skills/scripts/flightcheck/checks/infrastructure.py.

Mocks the three Dataverse reads the check makes (environment variable
definitions, environment variable values, connection references) with
`responses`, then runs the ACTUAL production check against the mocked
tenant state and asserts on the CheckResult list it produces.

Dataverse is the `documented` API tier (see tests/fixtures/cassettes/
INDEX.md), so these tests stub `auth.query_all` via `responses` — no
cassette. `require_validated_mock(dv)` enforces the tier gate.

Covers the INFRA-011 detect-first gate (three outcomes):
  A. No secret-bearing auth        → informational PASSED
  B1. Secret-type (KV-backed) env var → PASSED storage + MANUAL hardening
  B2. Raw secret in a Text env var    → FAILED
  C. Secret inside a connection       → MANUAL
Plus the missing-credentials SKIPPED path.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import responses

from flightcheck.checks.infrastructure import check_connector_secret_storage
from flightcheck.runner import Role, Status
from tests.conftest import require_validated_mock
from tests.mocks import dataverse as dv

require_validated_mock(dv)


# ───────────────────────────────────────────────────────────────────────
# Minimal runner — the check only reads .env_url and .dv_token.
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    env_url: str
    dv_token: str


@pytest.fixture
def runner(fake_dataverse_url: str, fake_token: str) -> _MinimalRunner:
    return _MinimalRunner(env_url=fake_dataverse_url, dv_token=fake_token)


# ───────────────────────────────────────────────────────────────────────
# Helper — register the three paginated Dataverse queries the check makes.
# Registered without a query string so `responses` matches regardless of
# the exact $select the production code builds.
# ───────────────────────────────────────────────────────────────────────


def _register_state(
    *,
    base_url: str,
    definitions: list[dict] | None = None,
    values: list[dict] | None = None,
    connection_refs: list[dict] | None = None,
) -> None:
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/environmentvariabledefinitions",
        json=dv.collection(definitions or []),
        status=200,
    )
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/environmentvariablevalues",
        json=dv.collection(values or []),
        status=200,
    )
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/connectionreferences",
        json=dv.collection(connection_refs or []),
        status=200,
    )


_DEF_ID = "00000000-0000-0000-0000-0000000060aa"


# ───────────────────────────────────────────────────────────────────────
# Outcome A — no secret-bearing auth → informational PASSED
# ───────────────────────────────────────────────────────────────────────


class TestOutcomeANoSecrets:
    @responses.activate
    def test_no_secrets_passes_informationally(self, runner):
        # Only a secretless simplified Workday SSO connection (ff0df) and a
        # plain non-secret config env var.
        _register_state(
            base_url=runner.env_url,
            definitions=[
                dv.env_var_def(
                    definition_id=_DEF_ID,
                    schema_name="new_ReportName",
                    type_value=100000000,
                )
            ],
            values=[
                dv.env_var_value(
                    definition_id=_DEF_ID,
                    schema_name="new_ReportName",
                    value="ESS_Worker_Data",
                )
            ],
            connection_refs=dv.workday_connection_refs_simplified(),
        )

        results = check_connector_secret_storage(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "INFRA-011"
        assert r.status == Status.PASSED.value
        assert "No inline connector secrets detected" in r.result
        assert r.remediation == ""  # PASSED rows carry no remediation


# ───────────────────────────────────────────────────────────────────────
# Outcome B1 — Secret-type (Key Vault-backed) env var
# ───────────────────────────────────────────────────────────────────────


class TestOutcomeB1KeyVaultBacked:
    @responses.activate
    def test_secret_env_var_passes_storage_and_manual_hardening(self, runner):
        _register_state(
            base_url=runner.env_url,
            definitions=[
                dv.env_var_def(
                    definition_id=_DEF_ID,
                    schema_name="new_WorkdayClientSecret",
                    type_value=100000005,  # Secret
                )
            ],
            values=[
                dv.env_var_value(
                    definition_id=_DEF_ID,
                    schema_name="new_WorkdayClientSecret",
                    value=(
                        "/subscriptions/00000000-0000-0000-0000-000000000000/"
                        "resourceGroups/ess/providers/Microsoft.KeyVault/vaults/"
                        "ess-kv/secrets/workday-client/1"
                    ),
                )
            ],
            connection_refs=[],
        )

        results = check_connector_secret_storage(runner)

        statuses = [r.status for r in results]
        assert Status.PASSED.value in statuses
        assert Status.MANUAL.value in statuses
        assert Status.FAILED.value not in statuses

        passed = next(r for r in results if r.status == Status.PASSED.value)
        assert "Key Vault-backed Secret-type environment variable" in passed.result
        assert "new_WorkdayClientSecret" in passed.result

        manual = next(r for r in results if r.status == Status.MANUAL.value)
        # Hardening WARNING/MANUAL framing is mandated by AGENTS.md principle 9.
        assert "Hardening recommendation (not a functional blocker)" in manual.remediation
        assert "Soft-delete" in manual.remediation
        assert "Purge protection" in manual.remediation


# ───────────────────────────────────────────────────────────────────────
# Outcome B2 — raw secret pasted into a Text env var → FAILED
# ───────────────────────────────────────────────────────────────────────


class TestOutcomeB2InlinePlaintext:
    @responses.activate
    def test_plaintext_secret_in_text_env_var_fails(self, runner):
        _register_state(
            base_url=runner.env_url,
            definitions=[
                dv.env_var_def(
                    definition_id=_DEF_ID,
                    schema_name="new_ClientSecret",
                    type_value=100000000,  # String / Text
                )
            ],
            values=[
                dv.env_var_value(
                    definition_id=_DEF_ID,
                    schema_name="new_ClientSecret",
                    value="s3cr3t-not-in-key-vault",
                )
            ],
            connection_refs=[],
        )

        results = check_connector_secret_storage(runner)

        assert len(results) == 1
        r = results[0]
        assert r.status == Status.FAILED.value
        assert "inline" in r.result.lower()
        assert "new_ClientSecret" in r.result
        # Remediation must lead with rotation (treat as compromised).
        assert "Rotate the exposed secret" in r.remediation
        assert "Key Vault" in r.remediation

    @responses.activate
    def test_multiple_plaintext_secrets_collapse_to_one_failed_row(self, runner):
        # Two high-confidence-name Text vars must bucket into ONE FAILED row
        # (principle 7) that lists both names.
        def_a = "00000000-0000-0000-0000-0000000060a1"
        def_b = "00000000-0000-0000-0000-0000000060a2"
        _register_state(
            base_url=runner.env_url,
            definitions=[
                dv.env_var_def(
                    definition_id=def_a,
                    schema_name="new_ClientSecret",
                    type_value=100000000,
                ),
                dv.env_var_def(
                    definition_id=def_b,
                    schema_name="new_DbPassword",  # exercises the "password" keyword
                    type_value=100000000,
                ),
            ],
            values=[
                dv.env_var_value(
                    definition_id=def_a,
                    schema_name="new_ClientSecret",
                    value="s3cr3t-1",
                ),
                dv.env_var_value(
                    definition_id=def_b,
                    schema_name="new_DbPassword",
                    value="hunter2-raw",
                ),
            ],
            connection_refs=[],
        )

        results = check_connector_secret_storage(runner)

        failed = [r for r in results if r.status == Status.FAILED.value]
        assert len(failed) == 1
        assert "new_ClientSecret" in failed[0].result
        assert "new_DbPassword" in failed[0].result
        assert "Rotate the exposed secret" in failed[0].remediation

    @responses.activate
    def test_kv_reference_in_text_var_is_not_flagged(self, runner):
        # A Text-type var whose value IS a Key Vault reference must not be
        # mistaken for inline plaintext.
        _register_state(
            base_url=runner.env_url,
            definitions=[
                dv.env_var_def(
                    definition_id=_DEF_ID,
                    schema_name="new_ClientSecret",
                    type_value=100000000,
                )
            ],
            values=[
                dv.env_var_value(
                    definition_id=_DEF_ID,
                    schema_name="new_ClientSecret",
                    value=(
                        "@Microsoft.KeyVault(SecretUri=https://ess-kv.vault.azure.net/"
                        "secrets/workday-client/)"
                    ),
                )
            ],
            connection_refs=[],
        )

        results = check_connector_secret_storage(runner)

        assert len(results) == 1
        assert results[0].status == Status.PASSED.value
        assert "No inline connector secrets detected" in results[0].result


# ───────────────────────────────────────────────────────────────────────
# Outcome B2b — broad/ambiguous secret name in a Text env var → WARNING
# ───────────────────────────────────────────────────────────────────────


class TestOutcomeB2bBroadKeywordWarns:
    @responses.activate
    def test_broad_keyword_name_warns_not_fails(self, runner):
        # A broad keyword ("token") is name-only evidence — surface as a
        # WARNING for confirmation, never a readiness-blocking FAILED.
        _register_state(
            base_url=runner.env_url,
            definitions=[
                dv.env_var_def(
                    definition_id=_DEF_ID,
                    schema_name="new_AccessToken",
                    type_value=100000000,  # String / Text
                )
            ],
            values=[
                dv.env_var_value(
                    definition_id=_DEF_ID,
                    schema_name="new_AccessToken",
                    value="ya29.raw-bearer-token",
                )
            ],
            connection_refs=[],
        )

        results = check_connector_secret_storage(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "INFRA-011"
        assert r.status == Status.WARNING.value
        assert Status.FAILED.value not in [x.status for x in results]
        assert "new_AccessToken" in r.result
        assert "could not be confirmed" in r.result
        # Remediation must frame the uncertainty (confirm) and the fix
        # path (rotate + Key Vault) without asserting it is definitely a leak.
        assert "flagged for confirmation" in r.remediation
        assert "no action" in r.remediation
        assert "Key Vault" in r.remediation

    @responses.activate
    def test_config_endpoint_name_is_warning_not_failure(self, runner):
        # "TokenEndpointUrl" is the canonical false-positive the tiering
        # exists to prevent: a broad keyword substring on ordinary config.
        # It must WARN (not FAIL) so readiness is not blocked by a URL.
        _register_state(
            base_url=runner.env_url,
            definitions=[
                dv.env_var_def(
                    definition_id=_DEF_ID,
                    schema_name="new_TokenEndpointUrl",
                    type_value=100000000,
                )
            ],
            values=[
                dv.env_var_value(
                    definition_id=_DEF_ID,
                    schema_name="new_TokenEndpointUrl",
                    value="https://wd.example.com/oauth2/token",
                )
            ],
            connection_refs=[],
        )

        results = check_connector_secret_storage(runner)

        assert len(results) == 1
        assert results[0].status == Status.WARNING.value
        assert Status.FAILED.value not in [x.status for x in results]

    @responses.activate
    def test_multiple_broad_keywords_collapse_to_one_warning_row(self, runner):
        # Two broad-keyword Text vars must bucket into ONE WARNING row
        # (principle 7) that lists both names.
        def_a = "00000000-0000-0000-0000-0000000060b1"
        def_b = "00000000-0000-0000-0000-0000000060b2"
        _register_state(
            base_url=runner.env_url,
            definitions=[
                dv.env_var_def(
                    definition_id=def_a,
                    schema_name="new_AccessToken",
                    type_value=100000000,
                ),
                dv.env_var_def(
                    definition_id=def_b,
                    schema_name="new_ApiKeyName",  # exercises the "apikey" keyword
                    type_value=100000000,
                ),
            ],
            values=[
                dv.env_var_value(
                    definition_id=def_a,
                    schema_name="new_AccessToken",
                    value="ya29.raw-bearer-token",
                ),
                dv.env_var_value(
                    definition_id=def_b,
                    schema_name="new_ApiKeyName",
                    value="primary-key",
                ),
            ],
            connection_refs=[],
        )

        results = check_connector_secret_storage(runner)

        warnings = [r for r in results if r.status == Status.WARNING.value]
        assert len(warnings) == 1
        assert "new_AccessToken" in warnings[0].result
        assert "new_ApiKeyName" in warnings[0].result
        assert Status.FAILED.value not in [x.status for x in results]

    @responses.activate
    def test_high_and_broad_split_into_failed_and_warning(self, runner):
        # A high-confidence name and a broad name in the same tenant must
        # produce TWO rows: FAILED lists only the high-confidence var,
        # WARNING lists only the broad var. No cross-contamination.
        def_high = "00000000-0000-0000-0000-0000000060c1"
        def_broad = "00000000-0000-0000-0000-0000000060c2"
        _register_state(
            base_url=runner.env_url,
            definitions=[
                dv.env_var_def(
                    definition_id=def_high,
                    schema_name="new_ClientSecret",
                    type_value=100000000,
                ),
                dv.env_var_def(
                    definition_id=def_broad,
                    schema_name="new_AccessToken",
                    type_value=100000000,
                ),
            ],
            values=[
                dv.env_var_value(
                    definition_id=def_high,
                    schema_name="new_ClientSecret",
                    value="s3cr3t-1",
                ),
                dv.env_var_value(
                    definition_id=def_broad,
                    schema_name="new_AccessToken",
                    value="ya29.raw-bearer-token",
                ),
            ],
            connection_refs=[],
        )

        results = check_connector_secret_storage(runner)

        failed = [r for r in results if r.status == Status.FAILED.value]
        warnings = [r for r in results if r.status == Status.WARNING.value]
        assert len(failed) == 1
        assert len(warnings) == 1
        assert "new_ClientSecret" in failed[0].result
        assert "new_AccessToken" not in failed[0].result
        assert "new_AccessToken" in warnings[0].result
        assert "new_ClientSecret" not in warnings[0].result


# ───────────────────────────────────────────────────────────────────────
# API error while reading Dataverse → WARNING (not a silent pass)
# ───────────────────────────────────────────────────────────────────────


class TestApiErrorWarns:
    @responses.activate
    def test_dataverse_read_error_warns(self, runner):
        # The first Dataverse read (definitions) fails with a 500. The check
        # must catch it and emit a single WARNING — never a false PASSED that
        # would hide an undetected inline secret (AGENTS.md principle 3).
        responses.add(
            method="GET",
            url=f"{runner.env_url}/api/data/v9.2/environmentvariabledefinitions",
            json={"error": {"code": "0x80040216", "message": "boom"}},
            status=500,
        )

        results = check_connector_secret_storage(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "INFRA-011"
        assert r.status == Status.WARNING.value
        assert "Could not read Dataverse" in r.result
        # Remediation must state the impact (undetected secret) and the fix.
        assert "secret-storage safety could not be verified" in r.remediation
        assert "re-run /flightcheck" in r.remediation.lower()


# ───────────────────────────────────────────────────────────────────────
# Outcome C — secret inside a connection → MANUAL
# ───────────────────────────────────────────────────────────────────────


class TestOutcomeCConnectionStored:
    @responses.activate
    def test_workday_legacy_isu_connection_is_manual(self, runner):
        results = _run_with_conns(runner, dv.workday_connection_refs_full())

        assert len(results) == 1
        r = results[0]
        assert r.status == Status.MANUAL.value
        assert "legacy ISU" in r.result
        # Multi-resource: both ISU connections collapse into ONE MANUAL row
        # (principle 7) and both are listed in that row's result.
        assert "Generic User" in r.result
        assert "Context Generic User" in r.result
        assert Role.WORKDAY_ADMIN.value in r.roles
        assert Role.POWER_PLATFORM_ADMIN.value in r.roles
        assert "cannot be auto-validated" in r.remediation

    @responses.activate
    def test_servicenow_connection_is_manual(self, runner):
        servicenow_ref = dv.connection_ref(
            logical_name="new_sharedservicenow_ab12c",
            display_name="ServiceNow Prod",
            connector_id="/providers/Microsoft.PowerApps/apis/shared_service-now",
            connection_id="shared-service-now-conn-0001",
        )
        results = _run_with_conns(runner, [servicenow_ref])

        assert len(results) == 1
        r = results[0]
        assert r.status == Status.MANUAL.value
        assert "ServiceNow" in r.result
        assert Role.SERVICENOW_ADMIN.value in r.roles
        assert "cannot be auto-validated" in r.remediation

    @responses.activate
    def test_simplified_sso_only_is_not_secret_bearing(self, runner):
        # ff0df-only (OAuthUser SSO) is secretless → Outcome A, not MANUAL.
        results = _run_with_conns(runner, dv.workday_connection_refs_simplified())

        assert len(results) == 1
        assert results[0].status == Status.PASSED.value


def _run_with_conns(runner, connection_refs):
    _register_state(
        base_url=runner.env_url,
        definitions=[],
        values=[],
        connection_refs=connection_refs,
    )
    return check_connector_secret_storage(runner)


# ───────────────────────────────────────────────────────────────────────
# Missing credentials → SKIPPED (no network call)
# ───────────────────────────────────────────────────────────────────────


class TestMissingCredentials:
    def test_no_token_skips(self):
        runner = _MinimalRunner(env_url="https://org.crm.dynamics.com", dv_token="")
        results = check_connector_secret_storage(runner)

        assert len(results) == 1
        assert results[0].status == Status.SKIPPED.value
        assert results[0].checkpoint_id == "INFRA-011"

    def test_no_env_url_skips(self):
        runner = _MinimalRunner(env_url="", dv_token="tok")
        results = check_connector_secret_storage(runner)

        assert len(results) == 1
        assert results[0].status == Status.SKIPPED.value
