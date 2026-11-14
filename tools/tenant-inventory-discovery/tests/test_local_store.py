"""Pure build/merge semantics for the durable local inventory mirror (local_store).

The mirror mimics the *service's* rules so an offline reader sees the same picture the
tenant has. Under whole-inventory sync those rules collapsed into one decision, taken
once per run rather than once per scope:

* the sync succeeded -> the payload **was** the tenant, so refresh what it carried and
  retire what it omitted;
* the sync did not happen -> the tenant did not change, so the prior mirror is still
  correct and this run's observations are discarded rather than displayed.

Discarding observations on a withheld sync is deliberate. Showing them would assert a
tenant state that was never written, and the next successful sync re-observes them
anyway.
"""

from __future__ import annotations

from tenant_inventory_discovery.in_memory_inventory import StoredItem
from tenant_inventory_discovery.local_store import build_document
from tenant_inventory_discovery.models import (
    Kind,
    RunSummary,
    ScopeKey,
    ScopeReport,
    SyncResult,
)

T1 = "2024-01-01T00:00:00Z"
T2 = "2024-01-02T00:00:00Z"
T3 = "2024-01-03T00:00:00Z"
ENV_A = "env-aaaa"


def _item(kind, natural_key, *, env="", **attrs):
    attributes = {"naturalKey": natural_key, **attrs}
    return StoredItem(
        kind=kind,
        natural_key=natural_key,
        attributes=attributes,
        environment_id=env,
    )


def _report(kind, *, env="", complete=True, error=None, mapped=0, enumerated=0):
    scope = ScopeKey.for_kind(kind, env or None)
    return ScopeReport(
        scope=scope,
        enumerated=enumerated,
        mapped=mapped,
        fully_enumerated=complete,
        covered=True,
        error=error,
    )


def _summary(reports, *, synced=True, correlation_id="run-1", aborted=False, blocked=""):
    """A run summary. ``synced`` decides which of the two merge branches applies."""
    s = RunSummary(correlation_id=correlation_id)
    s.scopes = reports
    s.authoritative_scopes = [r.scope for r in reports if r.authoritative]
    s.aborted = aborted
    s.sync_blocked_reason = blocked
    if synced:
        s.synced = SyncResult(submitted_count=0, upserted_count=0, retired_count=0)
    return s


def _build(prior, items, summary, *, now):
    return build_document(
        prior,
        items,
        summary,
        tenant_id="t1",
        mode="demo",
        write_path="local-only",
        now=now,
    )


def _records(doc, kind):
    return doc["resources"].get(kind.discriminator, [])


def _conn(nk):
    return _item(Kind.CONNECTION, nk, env=ENV_A)


def _find(doc, kind, natural_key):
    for rec in _records(doc, kind):
        if rec["naturalKey"] == natural_key:
            return rec
    return None


# -- fresh build -------------------------------------------------------------------


def test_fresh_build_shape_and_timestamps():
    items = [
        _item(Kind.CONNECTION, "c-1", env=ENV_A, connectorId="shared_sn"),
        _item(Kind.CONNECTION, "c-2", env=ENV_A),
    ]
    rep = _report(Kind.CONNECTION, env=ENV_A, mapped=2, enumerated=2)
    doc = _build(None, items, _summary([rep]), now=T1)

    assert doc["schemaVersion"] == 1
    assert doc["kind"] == "tenant-inventory"
    assert doc["tenantId"] == "t1"
    assert doc["updatedAt"] == T1
    assert doc["lastRun"]["correlationId"] == "run-1"
    recs = _records(doc, Kind.CONNECTION)
    assert [r["naturalKey"] for r in recs] == ["c-1", "c-2"]  # sorted
    for rec in recs:
        assert rec["state"] == "Active"
        assert rec["firstSeenAt"] == T1
        assert rec["lastSeenAt"] == T1
    # The connector edge is an attribute, not a top-level field: the server models it
    # inside the attribute bag for Connection/ScenarioTemplate.
    assert (
        _find(doc, Kind.CONNECTION, "c-1")["attributes"]["connectorId"] == "shared_sn"
    )
    assert "connectorId" not in _find(doc, Kind.CONNECTION, "c-2")
    assert doc["totals"] == {
        "resourceTypes": 1,
        "resources": 2,
        "activeResources": 2,
        "retired": 0,
        "incompleteScopes": 0,
    }
    scope_row = doc["scopes"][0]
    assert scope_row["complete"] is True
    assert scope_row["authoritative"] is True
    assert scope_row["tenantRoot"] is False


def test_the_run_record_carries_the_sync_outcome():
    rep = _report(Kind.CONNECTION, env=ENV_A, mapped=1, enumerated=1)
    summary = _summary([rep])
    summary.synced = SyncResult(
        submitted_count=1, upserted_count=1, retired_count=2,
        retired_item_ids=["Connection:gone"],
    )
    doc = _build(None, [_conn("c-1")], summary, now=T1)

    assert doc["lastRun"]["synced"] is True
    assert doc["lastRun"]["retiredCount"] == 2
    assert doc["lastRun"]["syncBlockedReason"] == ""


# -- a successful sync: absence retires, then prunes --------------------------------


def test_a_synced_run_retires_then_prunes_drift():
    # Run 1: c-1, c-2 both present.
    items1 = [_conn("c-1"), _conn("c-2")]
    rep1 = _report(Kind.CONNECTION, env=ENV_A, mapped=2, enumerated=2)
    doc1 = _build(None, items1, _summary([rep1]), now=T1)

    # Run 2: only c-1 in the payload -> c-2 was retired server-side, shown for one run.
    rep2 = _report(Kind.CONNECTION, env=ENV_A, mapped=1, enumerated=1)
    doc2 = _build(doc1, [_conn("c-1")], _summary([rep2]), now=T2)

    c1 = _find(doc2, Kind.CONNECTION, "c-1")
    c2 = _find(doc2, Kind.CONNECTION, "c-2")
    assert c1["state"] == "Active" and c1["lastSeenAt"] == T2
    assert c2["state"] == "Retired" and c2["retiredAt"] == T2
    assert doc2["totals"]["retired"] == 1

    # Run 3: still only c-1 -> the already-Retired c-2 is pruned.
    rep3 = _report(Kind.CONNECTION, env=ENV_A, mapped=1, enumerated=1)
    doc3 = _build(doc2, [_conn("c-1")], _summary([rep3]), now=T3)

    assert _find(doc3, Kind.CONNECTION, "c-2") is None
    assert [r["naturalKey"] for r in _records(doc3, Kind.CONNECTION)] == ["c-1"]


def test_firstseen_carried_lastseen_bumped():
    rep1 = _report(Kind.CONNECTION, env=ENV_A, mapped=1)
    doc1 = _build(None, [_conn("c-1")], _summary([rep1]), now=T1)

    rep2 = _report(Kind.CONNECTION, env=ENV_A, mapped=1)
    doc2 = _build(doc1, [_conn("c-1")], _summary([rep2]), now=T2)

    rec = _find(doc2, Kind.CONNECTION, "c-1")
    assert rec["firstSeenAt"] == T1
    assert rec["lastSeenAt"] == T2


def test_a_retired_item_revives_on_reappearance():
    rep1 = _report(Kind.CONNECTION, env=ENV_A, mapped=2)
    doc1 = _build(None, [_conn("c-1"), _conn("c-2")], _summary([rep1]), now=T1)

    rep2 = _report(Kind.CONNECTION, env=ENV_A, mapped=1)
    doc2 = _build(doc1, [_conn("c-1")], _summary([rep2]), now=T2)
    assert _find(doc2, Kind.CONNECTION, "c-2")["state"] == "Retired"

    rep3 = _report(Kind.CONNECTION, env=ENV_A, mapped=2)
    doc3 = _build(doc2, [_conn("c-1"), _conn("c-2")], _summary([rep3]), now=T3)

    c2 = _find(doc3, Kind.CONNECTION, "c-2")
    assert c2["state"] == "Active"
    assert c2["firstSeenAt"] == T1
    assert "retiredAt" not in c2


def test_carried_forward_rows_keep_the_mirror_whole():
    """The payload includes rows the crawl did not observe; the mirror must show them.

    Otherwise a narrow run would blank the mirror for every environment it skipped --
    the same absence bug as the service, one layer down.
    """
    items1 = [_conn("c-1"), _item(Kind.CONNECTION, "other", env="env-bbbb")]
    rep1 = _report(Kind.CONNECTION, env=ENV_A, mapped=2)
    doc1 = _build(None, items1, _summary([rep1]), now=T1)

    # Run 2 observes only c-1 but carries "other" forward, so both are in the payload.
    rep2 = _report(Kind.CONNECTION, env=ENV_A, mapped=1)
    doc2 = _build(doc1, items1, _summary([rep2]), now=T2)

    assert _find(doc2, Kind.CONNECTION, "other")["state"] == "Active"


# -- a run that did not sync must not move the mirror -------------------------------


def test_a_withheld_sync_preserves_the_prior_mirror_exactly():
    items1 = [_conn("c-1"), _conn("c-2")]
    rep1 = _report(Kind.CONNECTION, env=ENV_A, mapped=2)
    doc1 = _build(None, items1, _summary([rep1]), now=T1)

    # Run 2 crawled but never wrote. The tenant is unchanged, so the mirror is too.
    rep2 = _report(Kind.CONNECTION, env=ENV_A, complete=False, error="boom")
    doc2 = _build(
        doc1, [], _summary([rep2], synced=False, blocked="inventory unreadable"), now=T2
    )

    for nk in ("c-1", "c-2"):
        rec = _find(doc2, Kind.CONNECTION, nk)
        assert rec["state"] == "Active"
        assert rec["firstSeenAt"] == T1
        assert rec["lastSeenAt"] == T1  # not bumped -- nothing was confirmed
    assert doc2["totals"]["incompleteScopes"] == 1
    assert doc2["lastRun"]["synced"] is False
    assert doc2["lastRun"]["syncBlockedReason"] == "inventory unreadable"


def test_a_withheld_sync_discards_this_runs_observations():
    """Showing them would claim a tenant state that was never written."""
    rep1 = _report(Kind.CONNECTION, env=ENV_A, mapped=1)
    doc1 = _build(None, [_conn("c-1")], _summary([rep1]), now=T1)

    rep2 = _report(Kind.CONNECTION, env=ENV_A, mapped=2)
    doc2 = _build(
        doc1, [_conn("c-1"), _conn("c-new")], _summary([rep2], synced=False), now=T2
    )

    assert _find(doc2, Kind.CONNECTION, "c-new") is None
    assert _find(doc2, Kind.CONNECTION, "c-1")["lastSeenAt"] == T1


def test_a_withheld_sync_never_retires():
    """The failure direction that matters: no write means no deletion, ever."""
    rep1 = _report(Kind.CONNECTION, env=ENV_A, mapped=2)
    doc1 = _build(None, [_conn("c-1"), _conn("c-2")], _summary([rep1]), now=T1)

    rep2 = _report(Kind.CONNECTION, env=ENV_A, mapped=1)
    doc2 = _build(doc1, [_conn("c-1")], _summary([rep2], synced=False), now=T2)

    assert _find(doc2, Kind.CONNECTION, "c-2")["state"] == "Active"
    assert doc2["totals"]["retired"] == 0


def test_an_aborted_run_leaves_the_mirror_alone():
    rep1 = _report(Kind.CONNECTION, env=ENV_A, mapped=1)
    doc1 = _build(None, [_conn("c-1")], _summary([rep1]), now=T1)

    doc2 = _build(doc1, [], _summary([], synced=False, aborted=True), now=T2)

    assert _find(doc2, Kind.CONNECTION, "c-1")["state"] == "Active"
    assert doc2["lastRun"]["aborted"] is True


# -- scope bookkeeping ---------------------------------------------------------------


def test_a_non_authoritative_scope_is_recorded_as_such():
    """Complete but not vouched-for: enumerated fine, coverage too narrow to trust."""
    rep = _report(Kind.CONNECTOR, mapped=1, enumerated=1)
    rep.covered = False  # e.g. the kit's Connector, derived from one environment
    doc = _build(None, [_item(Kind.CONNECTOR, "conn-1")], _summary([rep]), now=T1)

    row = doc["scopes"][0]
    assert row["complete"] is True
    assert row["authoritative"] is False


def test_a_failed_scope_records_its_error():
    rep = _report(Kind.CONNECTION, env=ENV_A, complete=False, error="403 forbidden")
    doc = _build(None, [], _summary([rep], synced=False), now=T1)

    row = doc["scopes"][0]
    assert row["error"] == "403 forbidden"
    assert row["complete"] is False
    assert row["authoritative"] is False
