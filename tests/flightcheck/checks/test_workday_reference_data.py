# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for WD-REF-001 (Workday write-scenario reference-data availability).

The check reconciles the reference picklists each Workday topic REQUESTS from
the shared GetReferenceData topic (``referenceDataKey: KEY``) against the keys
GetReferenceData SUPPORTS (its ``referenceDataKey = "KEY"`` switch). Both come
from Dataverse ``botcomponents`` via ``query_all`` (documented tier — stubbed
here). The request-template ID types are deliberately NOT used (they don't map
1:1 to GetReferenceData keys and would false-positive on OOTB scenarios — see
the WD-REF-001 comment in checks/workday.py).
"""

from __future__ import annotations

from types import SimpleNamespace


# ── pure-logic extractor tests (no network) ───────────────────────────────

def test_extract_supported_keys_reads_the_switch():
    from flightcheck.checks.workday import _extract_supported_reference_keys

    data = (
        'condition: =Topic.referenceDataKey = "Phone_Device_Type_ID"\n'
        "condition: =Topic.referenceDataKey = 'Related_Person_Relationship_ID'\n"
        # input declaration (no value on the line) must NOT count as supported
        "referenceDataKey:\n  displayName: referenceDataKey\n"
    )
    assert _extract_supported_reference_keys(data) == {
        "Phone_Device_Type_ID", "Related_Person_Relationship_ID",
    }


def test_extract_requested_keys_reads_literal_call_inputs():
    from flightcheck.checks.workday import _extract_requested_reference_keys

    data = (
        "referenceDataKey: Phone_Device_Type_ID\n"
        "referenceDataKey: Country_Phone_Code_ID\n"
        # a Power Fx expression value is not a static key -> not matched
        "referenceDataKey: =SomeDynamic(Expr)\n"
        # the switch form (=) is a SUPPORTED marker, not a request -> not matched
        'condition: =Topic.referenceDataKey = "Marital_Status_ID"\n'
    )
    assert _extract_requested_reference_keys(data) == {
        "Phone_Device_Type_ID", "Country_Phone_Code_ID",
    }


# ── integration tests (stubbed query_all) ─────────────────────────────────

_GETREF = {
    "name": "Workday System Get ReferenceData",
    "schemaname": "msdyn_copilotforemployeeselfservicehr.topic.GetReferenceData",
    "data": (
        'condition: =Topic.referenceDataKey = "Phone_Device_Type_ID"\n'
        'condition: =Topic.referenceDataKey = "Country_Phone_Code_ID"\n'
        'condition: =Topic.referenceDataKey = "Related_Person_Relationship_ID"\n'
        "referenceDataKey:\n  displayName: referenceDataKey\n"
    ),
}
_PHONE = {
    "name": "Workday Update PhoneNumber",
    "schemaname": "msdyn_copilotforemployeeselfservicehr.topic.EmployeeUpdatePhoneNumber",
    "data": "referenceDataKey: Phone_Device_Type_ID\nreferenceDataKey: Country_Phone_Code_ID\n",
}
_DEPENDENT = {
    "name": "Workday Add Dependent",
    "schemaname": "msdyn_copilotforemployeeselfservicehr.topic.WorkdayAddDependent",
    "data": "referenceDataKey: Related_Person_Relationship_ID\n",
}
_BAD = {
    "name": "Workday Custom Marital Status",
    "schemaname": "msdyn_copilotforemployeeselfservicehr.topic.CustomMaritalStatus",
    "data": "referenceDataKey: Marital_Status_ID\n",  # NOT in _GETREF's switch
}


def _runner():
    return SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")


def _stub(monkeypatch, topics):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: list(topics))


def _run():
    from flightcheck.checks.workday import _check_workday_reference_data
    results = _check_workday_reference_data(_runner())
    assert len(results) == 1
    assert results[0].checkpoint_id == "WD-REF-001"
    return results[0]


def test_all_requested_keys_supported_passes(monkeypatch):
    _stub(monkeypatch, [_GETREF, _PHONE, _DEPENDENT])
    r = _run()
    assert r.status == "Passed"
    assert "request only keys GetReferenceData supports" in r.result
    assert r.remediation == ""


def test_topic_requesting_unsupported_key_fails(monkeypatch):
    _stub(monkeypatch, [_GETREF, _PHONE, _BAD])
    r = _run()
    assert r.status == "Failed"
    assert "1 of 2 Workday topic(s)" in r.result
    assert "Workday Custom Marital Status" in r.result
    assert "Marital_Status_ID" in r.result
    # The other (valid) topic must NOT be reported as a gap.
    assert "Update PhoneNumber" not in r.result
    assert "GetReferenceData" in r.remediation
    # A clickable fix-link to Copilot Studio is present in the remediation.
    assert "copilotstudio.microsoft.com" in r.remediation
    assert "](" in r.remediation  # markdown link


def test_failure_remediation_contains_resolved_studio_deeplink(monkeypatch):
    # A runner whose parsed config carries env_id + agents[] (the real shape
    # produced by setup.py / cli.py) must yield a *resolved* deep link to the
    # agent's overview page — not the generic homepage fallback.
    _stub(monkeypatch, [_GETREF, _PHONE, _BAD])
    from flightcheck.checks.workday import _check_workday_reference_data

    runner = SimpleNamespace(
        env_url="https://org.crm.dynamics.com",
        dv_token="t",
        env_id="ENV-123",
        config={
            "activeAgent": "esshrwdayonlyoauth",
            "agents": [{"slug": "esshrwdayonlyoauth", "botId": "BOT-456"}],
        },
    )
    r = _check_workday_reference_data(runner)[0]
    assert r.status == "Failed"
    assert (
        "/environments/ENV-123/bots/BOT-456/overview" in r.remediation
    ), r.remediation


def test_deeplink_resolves_from_agents_when_activeagent_absent(monkeypatch):
    # Defensive fallback: even without activeAgent/agent.slug, the first
    # agents[] entry resolves the deep link (covers the silent-homepage path
    # raised in review).
    _stub(monkeypatch, [_GETREF, _PHONE, _BAD])
    from flightcheck.checks.workday import _check_workday_reference_data

    runner = SimpleNamespace(
        env_url="https://org.crm.dynamics.com",
        dv_token="t",
        env_id="ENV-123",
        config={"agents": [{"slug": "esshrwdayonlyoauth", "botId": "BOT-456"}]},
    )
    r = _check_workday_reference_data(runner)[0]
    assert r.status == "Failed"
    assert "/environments/ENV-123/bots/BOT-456/overview" in r.remediation


def test_getreferencedata_missing_fails(monkeypatch):
    _stub(monkeypatch, [_PHONE, _DEPENDENT])  # no GetReferenceData topic
    r = _run()
    assert r.status == "Failed"
    assert "'GetReferenceData' topic is not installed" in r.result
    assert "Install/repair the Workday extension" in r.remediation


def test_no_topic_requests_reference_data_is_not_configured(monkeypatch):
    # Only GetReferenceData present; its own declaration/switch is not a request.
    _stub(monkeypatch, [_GETREF])
    r = _run()
    assert r.status == "NotConfigured"
    assert "No Workday topic requests a reference-data picklist" in r.result


def test_missing_dataverse_token_is_skipped(monkeypatch):
    from flightcheck.checks.workday import _check_workday_reference_data
    r = _check_workday_reference_data(
        SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token=None)
    )[0]
    assert r.status == "Skipped"
    assert "Dataverse token not available" in r.result


def test_query_error_is_skipped(monkeypatch):
    import auth

    def _boom(*a, **kw):
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(auth, "query_all", _boom)
    r = _run()
    assert r.status == "Skipped"
    assert "Unable to read Dataverse topic configuration" in r.result
    assert "403 Forbidden" in r.result
