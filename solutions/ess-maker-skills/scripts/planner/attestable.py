# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS Maker Kit — Planner: the closed attestable-role catalogue (scripts-tree mirror).

The shared planner service can only pool/attest a task against a **closed** set of
roles — the backend registry ``AttestableAuthorizationRoles`` mirrored in
``src/mcp/agentconfig_planner/roles_surface.py``. That MCP module can't be imported
from the scripts tree (it pulls in ``_odata`` and the pythonpath deliberately
excludes ``src/mcp``), so this is a hand-maintained mirror kept in lockstep with the
registry by ``tests/planner/test_attestable.py`` (AST-parsing the source, no import).

Its one job for the planner: turn a **maker-supplied** role label (from an uploaded
plan, which may be a compact id, the wire display name, or a spaced/hyphenated
variant of either) into the canonical compact id the service accepts — or ``None``
when the label isn't attestable, so ingest can record a gap and ask instead of
persisting a role the service will reject on publish.
"""

from __future__ import annotations

import re

# Compact id -> wire display name. Mirrors ``roles_surface.py`` exactly (the
# lockstep test asserts these agree with the backend registry). Ordered by owning
# provider (External, Entra, Power Platform) to match the source of truth.
ATTESTABLE_ROLE_WIRE_NAMES: dict[str, str] = {
    # External — upstream systems with no queryable Microsoft directory.
    "WorkdayAdmin": "Workday administrator",
    "ServiceNowAdmin": "ServiceNow Administrator",
    "ServiceNowKnowledgeManager": "ServiceNow Knowledge Manager",
    # Entra — Microsoft Entra ID directory roles.
    "EntraGlobalAdministrator": "Global Administrator",
    "EntraNetworkAdministrator": "Network Administrator",
    "EntraUserAdministrator": "User Administrator",
    "EntraPowerPlatformAdministrator": "Power Platform Administrator",
    "EntraApplicationAdministrator": "Application Administrator",
    "EntraCloudApplicationAdministrator": "Cloud Application Administrator",
    # Power Platform — Dataverse / environment roles.
    "PowerPlatformEnvironmentMaker": "Environment Maker",
    "PowerPlatformEnvironmentAdministrator": "Environment Administrator",
    "PowerPlatformSystemAdministrator": "System Administrator",
}

# The compact role ids, in registry order.
ATTESTABLE_ROLES: tuple[str, ...] = tuple(ATTESTABLE_ROLE_WIRE_NAMES)


def _normalize(label: str) -> str:
    """Fold a role label for matching: lower-case, strip every non-alphanumeric.

    So ``"Power Platform Administrator"``, ``"power-platform-administrator"`` and
    ``"PowerPlatformAdministrator"`` all collapse to the same key — a maker who
    wrote the display name, the slug, or the compact id still resolves.
    """
    return re.sub(r"[^a-z0-9]+", "", (label or "").lower())


# Normalised compact-id AND wire-display -> canonical compact id.
_LOOKUP: dict[str, str] = {}
for _cid, _wire in ATTESTABLE_ROLE_WIRE_NAMES.items():
    _LOOKUP[_normalize(_cid)] = _cid
    _LOOKUP[_normalize(_wire)] = _cid


def is_attestable_role(label: str) -> bool:
    """True when ``label`` resolves to one of the closed attestable roles."""
    return resolve_attestable_role_id(label) is not None


def resolve_attestable_role_id(label: str) -> str | None:
    """Resolve a role label to its canonical **compact id**, or ``None``.

    Accepts the compact id (``WorkdayAdmin``), the wire display name (``Workday
    administrator``), or a spaced/hyphenated variant of either. Returns ``None``
    for anything not in the closed catalogue — the caller decides whether to drop,
    reject, or ask.
    """
    if not label:
        return None
    return _LOOKUP.get(_normalize(label))
