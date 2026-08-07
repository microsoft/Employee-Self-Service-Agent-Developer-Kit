# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Durable connect-state persistence for the ESS setup **action** scripts.

The setup playbook (``install-servicenow-extension-pack.md``) requires that after
each major gate the connect config is merged with the new state and persisted
immediately, so that a resume (and later skills like ``/create topic``) can see
what already succeeded. Historically that merge lived only as prose instructions
to the driving agent, which did the work but recorded nothing. A script-first
drive therefore left
``.local/connect/<connector>/config.json`` with ``packs.<product> = "pending"``,
``connections = {}`` and no ``setupStatus`` for the S6.x steps even though the
environment was fully wired.

This module provides the recorder helpers that close that gap: a caller records
on **confirmed** success, writing the factual artifact it just
produced plus the ``setupStatus`` step it owns. Every write is a *merge* — it
never drops keys written by earlier setup skills — and callers are expected to
wrap invocations so a persistence hiccup can never change the script's exit code.

Layout (relative to the current working directory, matching the rest of the kit):
  * ``.local/connect/<connector>/config.json`` — the per-connector connect config.
  * ``.local/config.json``                     — the root ESS config (legacy
    connection summary only, via :func:`record_legacy_servicenow_summary`).
"""

from __future__ import annotations

import datetime
import json
import os

_CONNECT_DIR = os.path.join(".local", "connect")
_ROOT_CONFIG = os.path.join(".local", "config.json")


def config_path(connector: str) -> str:
    """Path to a connector's connect config, relative to the current directory."""
    return os.path.join(_CONNECT_DIR, connector, "config.json")


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: str, data: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _deep_merge(base: dict, patch: dict) -> dict:
    """Recursively merge ``patch`` into ``base`` (nested dicts merged, not replaced)."""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load(connector: str) -> dict:
    """Read a connector's connect config (``{}`` when absent or unreadable)."""
    return _read_json(config_path(connector))


def merge(connector: str, patch: dict) -> dict:
    """Deep-merge ``patch`` into the connector config and persist it. Merge-only."""
    path = config_path(connector)
    data = _read_json(path)
    _deep_merge(data, patch)
    _write_json(path, data)
    return data


def record_packs(connector: str, products, state: str = "installed") -> dict | None:
    """Record ``packs.<product> = state`` for each product (preserves installMode)."""
    products = [p for p in (products or []) if p]
    if not products:
        return None
    return merge(connector, {"packs": {p: state for p in products}})


def record_connections(connector: str, connections: dict) -> dict | None:
    """Merge connection state (e.g. ``{"servicenow": {...}, "dataverse": {...}}``)."""
    if not connections:
        return None
    return merge(connector, {"connections": connections})


def record_status(connector: str, status: str) -> dict:
    """Set the top-level connector ``status`` (e.g. ``"connected"``)."""
    return merge(connector, {"status": status})


def record_setup_step(
    connector: str,
    step_id: str,
    checkpoint: str,
    *,
    gate: str = "prog",
    verified_by: str = "programmatic",
    state: str = "done",
    note: str | None = None,
) -> dict:
    """Record a ``setupStatus`` entry for a master-checklist step (e.g. ``S6.2``).

    ``note`` is an optional human-readable one-liner explaining what the stage is
    about; when provided it is stored under a ``note`` key alongside the standard
    ``state``/``checkpoint``/``gate``/``verifiedBy`` fields. When omitted the key
    is not written (and any note recorded by an earlier merge is preserved).
    """
    entry = {
        "state": state,
        "checkpoint": checkpoint,
        "gate": gate,
        "verifiedBy": verified_by,
    }
    if note:
        entry["note"] = note
    return merge(connector, {"setupStatus": {step_id: entry}})


def record_product_setup_step(
    connector: str,
    product: str,
    step_id: str,
    checkpoint: str,
    *,
    gate: str = "prog",
    verified_by: str = "programmatic",
    state: str = "done",
    note: str | None = None,
) -> dict | None:
    """Record a **per-product** ``setupStatus`` entry under ``productStatus``.

    ServiceNow installs are per-product (HRSD / ITSM): the same master step (e.g.
    ``S6.1`` install, ``S6.6`` portal URL, and future HR-only steps such as the
    ``sn_hr_core`` plugin) can be at a different state for each product. Those
    steps are mirrored under ``productStatus.<product>.<step_id>`` instead of the
    shared, product-agnostic ``setupStatus`` block (bind / activate / connect /
    share, which act on the single shared ServiceNow connection).

    ``product`` is the short scope key (``"hrsd"`` / ``"itsm"``). The write is a
    deep merge, so it never drops the other product's block or any sibling key.
    ``note`` behaves exactly as in :func:`record_setup_step` (written only when
    provided; an earlier note is preserved when omitted).
    """
    if not product or not step_id:
        return None
    entry = {
        "state": state,
        "checkpoint": checkpoint,
        "gate": gate,
        "verifiedBy": verified_by,
    }
    if note:
        entry["note"] = note
    return merge(connector, {"productStatus": {product: {step_id: entry}}})


def record_legacy_servicenow_summary(summary: dict) -> dict:
    """Merge the legacy ServiceNow connection summary into the root ESS config.

    Older scan/report flows discover the ServiceNow connection via
    ``.local/config.json`` ``connections.ServiceNow``. Preserve every other key.
    """
    data = _read_json(_ROOT_CONFIG)
    connections = data.setdefault("connections", {})
    if not isinstance(connections, dict):
        connections = data["connections"] = {}
    connections["ServiceNow"] = {k: v for k, v in summary.items() if v is not None}
    _write_json(_ROOT_CONFIG, data)
    return data


def today_iso() -> str:
    """Today's date as an ISO ``YYYY-MM-DD`` string (for ``connectedAt`` stamps)."""
    return datetime.date.today().isoformat()
