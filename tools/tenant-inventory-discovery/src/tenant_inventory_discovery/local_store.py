"""Local tenant-inventory mirror document (build + cross-run merge).

The discovery skill's durable output is server-side (WeveNova). This module produces a
**local mirror** of that inventory -- a cache the ``/discover`` skill (and offline
planning) can render without the server. It applies the same per-scope gating the
server-side retire phase does (spec §6.3), so the local file never claims something
the server would not:

- **Reconciled scope** (in :attr:`RunSummary.completed_scopes`): the freshly observed set
  is authoritative -- items are refreshed and drift (prior keys not observed) is retired.
- **Complete-but-exempt scope** (fully enumerated, no error, but tenant-root during a
  subset crawl -- the tenant-root exemption): observed items are refreshed, but prior
  items are **kept** (the server would not retire them either).
- **Incomplete / capped / not-crawled scope**: prior items are preserved untouched -- a
  partial crawl never wipes the mirror.

The mirror diffs *observed keys* rather than replaying the server's ``UpdatedAt``
watermark: locally it has the exact observed set, which is a stronger signal than a
timestamp and needs no clock-skew allowance.

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


def _scope_of_record(kind_discriminator: str, record: dict) -> tuple[str, str]:
    return (record.get("environmentId", "") or "", kind_discriminator)


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

    ``stored_items`` are the run's upserted items (e.g. ``InMemoryInventoryClient.items``
    or whatever ``RecordingInventoryClient`` captured on the live path);
    each must expose ``kind`` (a :class:`~tenant_inventory_discovery.models.Kind`),
    ``natural_key``, ``attributes``, ``environment_id`` and ``state``.
    ``summary`` supplies per-scope completeness and the reconcile-eligible set.
    """
    now = now or now_iso()

    # -- index the prior mirror by (kind, naturalKey) and by scope --------------------
    prior_resources: dict[str, list[dict]] = (
        (prior_doc or {}).get("resources", {}) if prior_doc else {}
    )
    prior_by_key: dict[tuple[str, str], dict] = {}
    prior_by_scope: dict[tuple[str, str], list[dict]] = {}
    for kind_disc, records in prior_resources.items():
        for rec in records:
            prior_by_key[(kind_disc, rec["naturalKey"])] = rec
            prior_by_scope.setdefault(_scope_of_record(kind_disc, rec), []).append(rec)

    # -- group this run's observed items by scope ------------------------------------
    observed_by_scope: dict[tuple[str, str], list[Any]] = {}
    observed_keys_by_scope: dict[tuple[str, str], set[str]] = {}
    for item in stored_items:
        scope = (item.environment_id or "", item.kind.discriminator)
        observed_by_scope.setdefault(scope, []).append(item)
        observed_keys_by_scope.setdefault(scope, set()).add(item.natural_key)

    # -- scope status ----------------------------------------------------------------
    reconciled_scopes = {
        (s.environment_id, s.kind.discriminator) for s in summary.completed_scopes
    }
    report_by_scope = {
        (r.scope.environment_id, r.scope.kind.discriminator): r for r in summary.scopes
    }

    all_scopes = set(report_by_scope) | set(prior_by_scope)

    # -- merge, scope by scope -------------------------------------------------------
    resources: dict[str, list[dict]] = {}

    def _emit(kind_disc: str, record: dict) -> None:
        resources.setdefault(kind_disc, []).append(record)

    for scope in all_scopes:
        env_id, kind_disc = scope
        report = report_by_scope.get(scope)
        prior_recs = prior_by_scope.get(scope, [])

        # Not crawled this run -> preserve prior untouched.
        if report is None:
            for rec in prior_recs:
                _emit(kind_disc, rec)
            continue

        # Incomplete crawl -> preserve prior untouched; ignore any partial observations.
        if not report.complete:
            for rec in prior_recs:
                _emit(kind_disc, rec)
            continue

        observed = observed_by_scope.get(scope, [])
        observed_keys = observed_keys_by_scope.get(scope, set())
        is_reconciled = scope in reconciled_scopes

        # Refresh every observed item (carry firstSeenAt; revive if previously retired).
        for item in observed:
            prior = prior_by_key.get((kind_disc, item.natural_key))
            first_seen = prior.get("firstSeenAt", now) if prior else now
            _emit(
                kind_disc,
                _record_from_item(
                    item, now=now, first_seen=first_seen, state="Active"
                ),
            )

        # Reconcile drift only for reconcile-eligible scopes (server parity, §6.3).
        for rec in prior_recs:
            if rec["naturalKey"] in observed_keys:
                continue  # already re-emitted fresh above
            if not is_reconciled:
                _emit(kind_disc, rec)  # complete-but-exempt: keep prior, never retire
                continue
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
        },
        "scopes": _scopes_section(summary, reconciled_scopes),
        "resources": resources,
        "totals": _totals(resources, summary),
    }


def _scopes_section(
    summary: RunSummary, reconciled_scopes: set[tuple[str, str]]
) -> list[dict]:
    """Per-``(environmentId, kind)`` bookkeeping, tenant-root scopes first."""
    rows = []
    for report in summary.scopes:
        scope = report.scope
        rows.append(
            {
                "environmentId": scope.environment_id,
                "kind": scope.kind.discriminator,
                "tenantRoot": scope.kind.is_tenant_root,
                "complete": report.complete,
                "reconciled": (scope.environment_id, scope.kind.discriminator)
                in reconciled_scopes,
                "enumerated": report.enumerated,
                "recorded": report.upserted,
                "skippedInvalid": report.skipped_invalid,
                "capped": report.capped,
                "droppedAttributes": list(report.dropped_attributes),
                "retiredItemIds": list(report.retired_item_ids),
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
