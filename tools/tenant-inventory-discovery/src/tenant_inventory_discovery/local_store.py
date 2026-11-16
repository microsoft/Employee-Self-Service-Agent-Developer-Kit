"""Local tenant-inventory mirror document (build + cross-run merge).

The discovery skill's durable output is server-side (WeveNova). This module produces a
**local mirror** of that inventory -- a cache the ``/discover`` skill (and offline
planning) can render without the server.

The merge rule follows the service's, which under whole-inventory sync is now a single
run-level decision rather than eight per-scope ones:

- **The run synced.** The payload was the tenant's entire desired inventory and the
  service retired everything it omitted, so the mirror does the same: observed items
  are refreshed as ``Active``, and every prior record the payload did not carry is
  marked ``Retired``.
- **The run did not sync** (withheld, or aborted). *Nothing changed server-side*, so
  nothing changes here. The prior mirror is preserved verbatim, including the partial
  observations this run happened to make -- claiming them would show a tenant state
  that was never written.

That second branch is the whole safety story in miniature. Previously an incomplete
scope only forfeited its own retirements; now an incomplete anything forfeits the
entire write, and the mirror has to say so rather than quietly half-updating.

Retired drift is **kept for one run** (``state = "Retired"`` + ``retiredAt``) so a reader
can see what disappeared, then pruned on the next run.

This module is pure (no I/O, no network): the kit bridge owns reading/writing
``.local/inventory.json``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import RunSummary

SCHEMA_VERSION = 1
DOCUMENT_KIND = "tenant-inventory"


def now_iso() -> str:
    """Current UTC time as an ISO-8601 ``...Z`` string (second precision)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_from_item(item: Any, *, now: str, first_seen: str, state: str) -> dict:
    """Project one stored item into a mirror record (§5.3 attributes + local metadata)."""
    record: dict[str, Any] = {
        "naturalKey": item.natural_key,
        "environmentId": item.environment_id or "",
    }
    if getattr(item, "display_name", None):
        record["displayName"] = item.display_name
    record["attributes"] = dict(item.attributes)
    record["state"] = state
    record["firstSeenAt"] = first_seen
    record["lastSeenAt"] = now
    return record


def build_document(
    prior_doc: dict | None,
    stored_items: list[Any],
    summary: RunSummary,
    *,
    tenant_id: str,
    mode: str,
    write_path: str,
    now: str | None = None,
) -> dict:
    """Merge this run into the prior mirror and return the new mirror document.

    ``stored_items`` are the items the service actually stored (e.g.
    ``InMemoryInventoryClient.items``, or whatever ``RecordingInventoryClient``
    captured on the live path); each must expose ``kind`` (a
    :class:`~tenant_inventory_discovery.models.Kind`), ``natural_key``,
    ``attributes``, ``environment_id`` and ``state``. ``summary`` supplies whether the
    run earned the right to write at all.
    """
    now = now or now_iso()

    # -- index the prior mirror by (kind, naturalKey) ---------------------------------
    prior_resources: dict[str, list[dict]] = (
        (prior_doc or {}).get("resources", {}) if prior_doc else {}
    )
    prior_by_key: dict[tuple[str, str], dict] = {}
    for kind_disc, records in prior_resources.items():
        for rec in records:
            prior_by_key[(kind_disc, rec["naturalKey"])] = rec

    resources: dict[str, list[dict]] = {}

    def _emit(kind_disc: str, record: dict) -> None:
        resources.setdefault(kind_disc, []).append(record)

    if not summary.synced_ok:
        # Nothing reached the service, so the mirror must not move. Any items this run
        # did observe are discarded: showing them would assert a tenant state that was
        # never written, and the next successful sync will observe them again anyway.
        for kind_disc, records in prior_resources.items():
            for rec in records:
                _emit(kind_disc, rec)
    else:
        observed_keys: set[tuple[str, str]] = {
            (item.kind.discriminator, item.natural_key) for item in stored_items
        }

        # Refresh every stored item (carry firstSeenAt; revive if previously retired).
        for item in stored_items:
            kind_disc = item.kind.discriminator
            prior = prior_by_key.get((kind_disc, item.natural_key))
            first_seen = prior.get("firstSeenAt", now) if prior else now
            _emit(
                kind_disc,
                _record_from_item(
                    item, now=now, first_seen=first_seen, state="Active"
                ),
            )

        # Absence retires. The payload was the whole tenant, so anything prior that is
        # not in it was retired server-side and is shown retired here for one run.
        for kind_disc, records in prior_resources.items():
            for rec in records:
                if (kind_disc, rec["naturalKey"]) in observed_keys:
                    continue  # already re-emitted fresh above
                if rec.get("state") == "Retired":
                    continue  # already shown retired once -> prune now
                retired = dict(rec)
                retired["state"] = "Retired"
                retired["retiredAt"] = now
                _emit(kind_disc, retired)

    # Stable ordering: records by naturalKey within each kind.
    resources = {
        kind_disc: sorted(recs, key=lambda r: r["naturalKey"])
        for kind_disc, recs in sorted(resources.items())
        if recs
    }

    synced = summary.synced
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": DOCUMENT_KIND,
        "tenantId": tenant_id,
        "updatedAt": now,
        "lastRun": {
            "correlationId": summary.correlation_id,
            "mode": mode,
            "writePath": write_path,
            "aborted": summary.aborted,
            "synced": summary.synced_ok,
            "syncBlockedReason": summary.sync_blocked_reason,
            "submittedCount": len(summary.payload),
            "retiredCount": synced.retired_count if synced else 0,
            "failedItemIds": synced.failed_item_ids if synced else [],
        },
        "scopes": _scopes_section(summary),
        "resources": resources,
        "totals": _totals(resources, summary),
    }


def _scopes_section(summary: RunSummary) -> list[dict]:
    """Per-``(environmentId, kind)`` bookkeeping, tenant-root scopes first."""
    completed = set(summary.completed_scopes)
    authoritative = set(summary.authoritative_scopes)
    rows = []
    for report in summary.scopes:
        scope = report.scope
        rows.append(
            {
                "environmentId": scope.environment_id,
                "kind": scope.kind.discriminator,
                "tenantRoot": scope.kind.is_tenant_root,
                "complete": scope in completed,
                # Whether absence in this scope was allowed to mean deletion. A scope
                # can be complete without being authoritative -- that is the whole
                # point of the carry-forward rule.
                "authoritative": scope in authoritative,
                "enumerated": report.enumerated,
                "submitted": report.mapped,
                "skippedInvalid": report.skipped_invalid,
                "capped": report.capped,
                "truncated": report.truncated,
                "droppedAttributes": list(report.dropped_attributes),
                "error": report.error,
            }
        )
    rows.sort(key=lambda r: (r["environmentId"] != "", r["environmentId"], r["kind"]))
    return rows


def _totals(resources: dict[str, list[dict]], summary: RunSummary) -> dict:
    total = sum(len(recs) for recs in resources.values())
    active = sum(
        1 for recs in resources.values() for rec in recs if rec["state"] == "Active"
    )
    return {
        "resourceTypes": len(resources),
        "resources": total,
        "activeResources": active,
        "retired": total - active,
        "incompleteScopes": sum(1 for r in summary.scopes if not r.complete),
    }
