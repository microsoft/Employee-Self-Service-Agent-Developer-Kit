"""Pure build/merge semantics for the durable local inventory mirror (local_store)."""

from __future__ import annotations

from tenant_inventory_discovery.in_memory_inventory import StoredItem
from tenant_inventory_discovery.local_store import build_document
from tenant_inventory_discovery.models import (
    Kind,
    RunSummary,
    ScopeKey,
    ScopeReport,
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


def _report(kind, *, env="", complete=True, error=None, upserted=0, enumerated=0):
    scope = ScopeKey.for_kind(kind, env or None)
    return ScopeReport(
        scope=scope,
        enumerated=enumerated,
        upserted=upserted,
        fully_enumerated=complete,
        error=error,
    )


def _summary(reports, *, completed=None, correlation_id="run-1", aborted=False):
    s = RunSummary(correlation_id=correlation_id)
    s.scopes = reports
    s.completed_scopes = [r.scope for r in (completed or [])]
    s.aborted = aborted
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


def _solo(rep):
    return _summary([rep], completed=[rep])


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
    rep = _report(Kind.CONNECTION, env=ENV_A, complete=True, upserted=2, enumerated=2)
    summary = _summary([rep], completed=[rep])

    doc = _build(None, items, summary, now=T1)

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
    assert scope_row["reconciled"] is True
    assert scope_row["complete"] is True
    assert scope_row["tenantRoot"] is False


# -- reconciled scope: retire drift, keep-then-prune -------------------------------


def test_reconciled_scope_retires_then_prunes_drift():
    # Run 1: c-1, c-2 both present.
    items1 = [_item(Kind.CONNECTION, "c-1", env=ENV_A), _item(Kind.CONNECTION, "c-2", env=ENV_A)]
    rep1 = _report(Kind.CONNECTION, env=ENV_A, upserted=2, enumerated=2)
    doc1 = _build(None, items1, _summary([rep1], completed=[rep1]), now=T1)

    # Run 2: only c-1 observed -> c-2 becomes Retired (kept one run).
    items2 = [_item(Kind.CONNECTION, "c-1", env=ENV_A)]
    rep2 = _report(Kind.CONNECTION, env=ENV_A, upserted=1, enumerated=1)
    doc2 = _build(doc1, items2, _summary([rep2], completed=[rep2]), now=T2)

    c1 = _find(doc2, Kind.CONNECTION, "c-1")
    c2 = _find(doc2, Kind.CONNECTION, "c-2")
    assert c1["state"] == "Active" and c1["lastSeenAt"] == T2
    assert c2["state"] == "Retired" and c2["retiredAt"] == T2
    assert doc2["totals"]["retired"] == 1

    # Run 3: still only c-1 -> the already-Retired c-2 is pruned.
    items3 = [_item(Kind.CONNECTION, "c-1", env=ENV_A)]
    rep3 = _report(Kind.CONNECTION, env=ENV_A, upserted=1, enumerated=1)
    doc3 = _build(doc2, items3, _summary([rep3], completed=[rep3]), now=T3)

    assert _find(doc3, Kind.CONNECTION, "c-2") is None
    assert [r["naturalKey"] for r in _records(doc3, Kind.CONNECTION)] == ["c-1"]


# -- firstSeenAt carried forward, lastSeenAt bumped --------------------------------


def test_firstseen_carried_lastseen_bumped():
    rep1 = _report(Kind.CONNECTION, env=ENV_A, upserted=1)
    doc1 = _build(None, [_conn("c-1")], _solo(rep1), now=T1)

    rep2 = _report(Kind.CONNECTION, env=ENV_A, upserted=1)
    doc2 = _build(doc1, [_conn("c-1")], _solo(rep2), now=T2)

    rec = _find(doc2, Kind.CONNECTION, "c-1")
    assert rec["firstSeenAt"] == T1
    assert rec["lastSeenAt"] == T2


# -- incomplete scope preserves prior untouched ------------------------------------


def test_incomplete_scope_preserves_prior():
    rep1 = _report(Kind.CONNECTION, env=ENV_A, upserted=2)
    items1 = [_item(Kind.CONNECTION, "c-1", env=ENV_A), _item(Kind.CONNECTION, "c-2", env=ENV_A)]
    doc1 = _build(None, items1, _summary([rep1], completed=[rep1]), now=T1)

    # Run 2: scope failed to enumerate -> not complete, nothing upserted.
    rep2 = _report(Kind.CONNECTION, env=ENV_A, complete=False, error="boom", upserted=0)
    doc2 = _build(doc1, [], _summary([rep2], completed=[]), now=T2)

    # Both prior items preserved unchanged (no wipe, no retire).
    for nk in ("c-1", "c-2"):
        rec = _find(doc2, Kind.CONNECTION, nk)
        assert rec["state"] == "Active"
        assert rec["firstSeenAt"] == T1
        assert rec["lastSeenAt"] == T1  # not bumped
    assert doc2["totals"]["incompleteScopes"] == 1


# -- tenant-root exemption in subset mode ------------------------------------------


def test_tenant_root_complete_but_exempt_does_not_retire():
    # Run 1 (full crawl): connectors conn-1, conn-2 reconciled.
    items1 = [_item(Kind.CONNECTOR, "conn-1"), _item(Kind.CONNECTOR, "conn-2")]
    rep1 = _report(Kind.CONNECTOR, upserted=2)
    doc1 = _build(None, items1, _summary([rep1], completed=[rep1]), now=T1)

    # Run 2 (subset mode): connector scope enumerated fully (complete=True) but is
    # NOT reconcile-eligible (tenant-root exemption -> absent from completed_scopes).
    # conn-2 disappeared; it must be preserved, not retired.
    items2 = [_item(Kind.CONNECTOR, "conn-1")]
    rep2 = _report(Kind.CONNECTOR, complete=True, upserted=1)
    doc2 = _build(doc1, items2, _summary([rep2], completed=[]), now=T2)

    conn1 = _find(doc2, Kind.CONNECTOR, "conn-1")
    conn2 = _find(doc2, Kind.CONNECTOR, "conn-2")
    assert conn1["state"] == "Active" and conn1["lastSeenAt"] == T2  # refreshed
    assert conn2["state"] == "Active"  # preserved, NOT retired
    assert conn2["lastSeenAt"] == T1
    assert doc2["scopes"][0]["reconciled"] is False


# -- scope not crawled this run is preserved ---------------------------------------


def test_scope_absent_from_run_is_preserved():
    # Run 1 crawls two scopes.
    items1 = [
        _item(Kind.CONNECTION, "c-1", env=ENV_A),
        _item(Kind.EXTENSION_PACK, "ESS.HRSD", env=ENV_A, version="1.0"),
    ]
    reps1 = [
        _report(Kind.CONNECTION, env=ENV_A, upserted=1),
        _report(Kind.EXTENSION_PACK, env=ENV_A, upserted=1),
    ]
    doc1 = _build(None, items1, _summary(reps1, completed=reps1), now=T1)

    # Run 2 only crawls Connection; ExtensionPack scope is absent from the summary.
    rep2 = _report(Kind.CONNECTION, env=ENV_A, upserted=1)
    doc2 = _build(doc1, [_conn("c-1")], _solo(rep2), now=T2)

    pack = _find(doc2, Kind.EXTENSION_PACK, "ESS.HRSD")
    assert pack is not None and pack["state"] == "Active"
    assert pack["firstSeenAt"] == T1 and pack["lastSeenAt"] == T1  # untouched


# -- a retired item reappearing is revived -----------------------------------------


def test_retired_item_revived_on_reappearance():
    rep1 = _report(Kind.CONNECTION, env=ENV_A, upserted=2)
    doc1 = _build(
        None,
        [_item(Kind.CONNECTION, "c-1", env=ENV_A), _item(Kind.CONNECTION, "c-2", env=ENV_A)],
        _summary([rep1], completed=[rep1]),
        now=T1,
    )
    # c-2 disappears -> retired.
    rep2 = _report(Kind.CONNECTION, env=ENV_A, upserted=1)
    doc2 = _build(doc1, [_conn("c-1")], _solo(rep2), now=T2)
    assert _find(doc2, Kind.CONNECTION, "c-2")["state"] == "Retired"

    # c-2 comes back -> Active again, firstSeenAt preserved, no retiredAt.
    rep3 = _report(Kind.CONNECTION, env=ENV_A, upserted=2)
    doc3 = _build(
        doc2,
        [_item(Kind.CONNECTION, "c-1", env=ENV_A), _item(Kind.CONNECTION, "c-2", env=ENV_A)],
        _summary([rep3], completed=[rep3]),
        now=T3,
    )
    c2 = _find(doc3, Kind.CONNECTION, "c-2")
    assert c2["state"] == "Active"
    assert c2["firstSeenAt"] == T1
    assert "retiredAt" not in c2
