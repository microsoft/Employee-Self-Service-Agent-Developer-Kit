# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: the roles-source seam (absent-safe).

Task assignment is role-first: the *role* a Task needs is grounded from the
Learn docs, and the sponsor then picks a *person* who holds that role (Flow 1),
while a person can ask which Tasks are waiting on their role(s) (Flow 2). Both
flows need a **roles source** — a role catalogue + membership directory — that
this design deliberately does not own. It is a separate, currently-unbuilt
workstream (see the Step-2 §7.4 "open question #7").

The planner depends only on the narrow :class:`RoleSource` contract and ships
**absent-safe**: with no backing source wired,

  * ``is_valid_role`` degrades to a well-formed-id check,
  * ``holds`` returns ``None`` ("unknown") rather than failing,
  * ``list_holders`` returns ``[]`` -> the skill falls back to letting the
    sponsor type the person, and
  * ``roles_of`` returns ``[]`` -> the skill falls back to self-selection
    (or resolving the caller by name via the WeveNova people directory).

A concrete source (the WeveNova people directory, Entra security groups via
Graph, a static tenant map, ...) can be injected later without touching the Plan
schema or the skill.
No network here — the facade is pure; a backing source may do IO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, runtime_checkable

# A well-formed role id is a lowercase, hyphen-joined token, e.g.
# "some-handle". This shape check is a *fallback* only (used by the absent-safe
# membership directory below). It is **not** how task roles are validated: task
# and attestable roles are looked up **verbatim** in the WeveNova registry
# (:data:`DEFAULT_REGISTRY`) — ordinal, case-sensitive, no slugifying.
_ROLE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def is_well_formed_role_id(role_id: str) -> bool:
    """True if ``role_id`` looks like a role handle (the absent-safe fallback)."""
    return bool(role_id) and bool(_ROLE_ID_RE.match(role_id))


def slugify_role_id(label: str) -> str:
    """Generic label -> lowercase-hyphen slug utility.

    .. deprecated:: role integration
       Task/attestable roles are **no longer slugified**. WeveNova stores the
       role id verbatim and validates it ordinally against the registry
       (:data:`DEFAULT_REGISTRY`), so a slug like ``power-platform-administrator``
       is *rejected* — the wire id is ``"Power Platform Administrator"``. Emit the
       exact registry id (see :meth:`RoleRegistry.find`); this helper remains only
       for non-role, generic slug needs.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    return slug


# --------------------------------------------------------------------------- #
# Role registry — the WeveNova valid-role catalogue.
#
# The role *catalogue* (which roles exist) is distinct from the membership
# *directory* (who holds a role — the RoleSource seam further below). This is the
# catalogue, grounded verbatim in the server's ``list_task_roles`` /
# ``list_attestable_roles`` tools.
#
# CRITICAL — the wire format is exact. WeveNova matches role ids **ordinally and
# case-sensitively** and does **no** normalization (no trimming, lowercasing, or
# slugifying). What the planner emits for ``AssignedToRoleId`` / an attestation
# ``role`` is stored verbatim and must equal a registry id character-for-
# character, including capitals and internal single spaces. External roles use
# the compact ``RoleId`` (``WorkdayAdmin``), NOT the display name
# (``Workday Administrator``); Entra / PowerPlatform roles have id == display.
# --------------------------------------------------------------------------- #

# Attestation is only defined for provider-owned roles from these three providers
# (never the internal ``AgentConfiguration`` authority roles).
ATTESTATION_PROVIDERS = ("External", "Entra", "PowerPlatform")


@dataclass(frozen=True)
class RoleDef:
    """One entry in the role catalogue (a task-groundable role)."""

    role: str          # the exact wire id (case-sensitive) — AssignedToRoleId / attest `role`
    provider: str      # AgentConfiguration | External | Entra | PowerPlatform
    display_name: str  # user-facing label (== role for Entra/PowerPlatform/internal)
    attestable: bool   # True iff a human can attest a person to it (provider-owned)


# Internal authority roles — task-groundable, never attestable.
_INTERNAL_ROLES: tuple[RoleDef, ...] = (
    RoleDef("AgentOwner", "AgentConfiguration", "AgentOwner", False),
    RoleDef("AgentEditor", "AgentConfiguration", "AgentEditor", False),
    RoleDef("AgentAnnotator", "AgentConfiguration", "AgentAnnotator", False),
    RoleDef("AgentViewer", "AgentConfiguration", "AgentViewer", False),
)

# Provider-owned attestable roles (the ``/attest`` universe). Grounded in
# ``list_attestable_roles``; External ids are the compact token, not the display.
_ATTESTABLE_ROLES: tuple[RoleDef, ...] = (
    RoleDef("WorkdayAdmin", "External", "Workday Administrator", True),
    RoleDef("ServiceNowAdmin", "External", "ServiceNow Administrator", True),
    RoleDef("ServiceNowKnowledgeManager", "External", "ServiceNow Knowledge Manager", True),
    RoleDef("Global Administrator", "Entra", "Global Administrator", True),
    RoleDef("Network Administrator", "Entra", "Network Administrator", True),
    RoleDef("User Administrator", "Entra", "User Administrator", True),
    RoleDef("Power Platform Administrator", "Entra", "Power Platform Administrator", True),
    RoleDef("Environment Maker", "PowerPlatform", "Environment Maker", True),
)

# The full valid universe for task grounding / pooled role assignment.
DEFAULT_TASK_ROLES: tuple[RoleDef, ...] = _INTERNAL_ROLES + _ATTESTABLE_ROLES


class RoleRegistry:
    """The role catalogue: ordinal, case-sensitive lookup of known roles.

    Built from the static ground truth by default; :meth:`from_mcp` refreshes it
    live from the ``weve-plan`` server (``list_task_roles`` /
    ``list_attestable_roles``) and falls back to the static set when the server
    is unreachable, so the catalogue is always available offline.
    """

    def __init__(self, roles: Iterable[RoleDef] = DEFAULT_TASK_ROLES) -> None:
        self._by_id: dict[str, RoleDef] = {}
        for r in roles:
            self._by_id[r.role] = r  # ordinal key — exact match only

    # -- membership (ordinal / case-sensitive) --------------------------- #

    def get(self, role_id: str) -> RoleDef | None:
        return self._by_id.get(role_id)

    def is_known_task_role(self, role_id: str) -> bool:
        """True iff ``role_id`` is a valid role for task grounding (exact match)."""
        return role_id in self._by_id

    def is_attestable(self, role_id: str) -> bool:
        r = self._by_id.get(role_id)
        return bool(r and r.attestable)

    def provider_of(self, role_id: str) -> str | None:
        r = self._by_id.get(role_id)
        return r.provider if r else None

    def display_name(self, role_id: str) -> str:
        r = self._by_id.get(role_id)
        return r.display_name if r else role_id

    # -- enumerations ---------------------------------------------------- #

    def task_role_ids(self) -> list[str]:
        return list(self._by_id)

    def attestable_roles(self) -> list[RoleDef]:
        return [r for r in self._by_id.values() if r.attestable]

    def allowed_task_names(self) -> list[str]:
        """User-facing valid-role list for a "not a valid role" nudge.

        Renders ``Display Name (id)`` when the two differ (External roles), else
        just the id — matching WeveNova's ``GetAllowedNames`` presentation.
        """
        return [self._render(r) for r in self._by_id.values()]

    def allowed_attestable_names(self, provider: str | None = None) -> list[str]:
        return [
            self._render(r)
            for r in self._by_id.values()
            if r.attestable and (provider is None or r.provider == provider)
        ]

    @staticmethod
    def _render(r: RoleDef) -> str:
        return r.role if r.display_name == r.role else f"{r.display_name} ({r.role})"

    # -- resolution ------------------------------------------------------ #

    def find(self, text: str) -> RoleDef | None:
        """Resolve free-typed text to the canonical role, for the skill's local
        pre-validation. Tries (1) an exact ordinal id match, then (2) a
        case-insensitive match against id or display name. Returns ``None`` if it
        can't map — the caller then shows :meth:`allowed_task_names`. This is a
        *convenience* for interpreting a maker's answer; the value ultimately
        emitted must be the exact :attr:`RoleDef.role` string.
        """
        if not text:
            return None
        if text in self._by_id:  # exact wire id
            return self._by_id[text]
        folded = text.strip().casefold()
        for r in self._by_id.values():
            if folded in (r.role.casefold(), r.display_name.casefold()):
                return r
        return None

    # -- live refresh ---------------------------------------------------- #

    @classmethod
    def from_mcp(cls, client: Any) -> "RoleRegistry":
        """Build the registry from the live server, falling back to the static
        catalogue on any error. ``client`` is an :class:`McpClient`-like object
        exposing ``call_tool``."""
        try:
            payload = client.call_tool("list_task_roles", {})
        except Exception:
            return cls()
        rows = payload.get("roles") if isinstance(payload, dict) else None
        if not rows:
            return cls()
        defs: list[RoleDef] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("role"):
                continue
            defs.append(
                RoleDef(
                    role=row["role"],
                    provider=row.get("provider", "") or "",
                    display_name=row.get("displayName") or row["role"],
                    attestable=bool(row.get("attestable")),
                )
            )
        return cls(defs) if defs else cls()


# The static ground-truth catalogue, usable with no network.
DEFAULT_REGISTRY = RoleRegistry()


@runtime_checkable
class RoleSource(Protocol):
    """The contract a real roles source implements. Every method may return
    ``None`` to mean "I can't answer that" — the directory then degrades."""

    def is_valid_role(self, role_id: str) -> bool | None: ...

    def holds(self, person_oid: str, role_id: str) -> bool | None: ...

    def list_holders(self, role_id: str) -> list[dict[str, Any]] | None:
        """People holding ``role_id`` as ``[{"oid", "displayName"}]`` (Flow 1)."""
        ...

    def roles_of(self, person_oid: str) -> list[dict[str, Any]] | None:
        """Roles ``person_oid`` holds as ``[{"roleId", "displayName"}]`` (Flow 2)."""
        ...


class RoleDirectory:
    """Absent-safe facade over an optional :class:`RoleSource`.

    The skill always talks to a ``RoleDirectory``; whether a real source is
    wired is invisible to callers except via :attr:`available` (used to decide
    whether to show a pick-list or fall back to free text).
    """

    def __init__(self, source: RoleSource | None = None) -> None:
        self.source = source

    @property
    def available(self) -> bool:
        """True when a real roles source backs this directory."""
        return self.source is not None

    def is_valid_role(self, role_id: str) -> bool:
        if self.source is not None:
            verdict = self.source.is_valid_role(role_id)
            if verdict is not None:
                return verdict
        return is_well_formed_role_id(role_id)

    def holds(self, person_oid: str, role_id: str) -> bool | None:
        """True/False if known, ``None`` if there is no source to ask."""
        if self.source is not None:
            return self.source.holds(person_oid, role_id)
        return None

    def list_holders(self, role_id: str) -> list[dict[str, Any]]:
        """Holders of ``role_id`` (Flow 1). Empty when no source is wired —
        the skill then asks the sponsor to type the person."""
        if self.source is not None:
            holders = self.source.list_holders(role_id)
            if holders is not None:
                return holders
        return []

    def roles_of(self, person_oid: str) -> list[dict[str, Any]]:
        """Roles ``person_oid`` holds (Flow 2). Empty when no source is wired —
        the skill then asks the person to self-select their role(s)."""
        if self.source is not None:
            roles = self.source.roles_of(person_oid)
            if roles is not None:
                return roles
        return []


class StaticRoleSource:
    """A trivial in-memory :class:`RoleSource` backed by a role -> holders map.

    Useful for local demos and tests, and as a template for a real source. The
    map is ``{role_id: [{"oid", "displayName"}, ...]}``.
    """

    def __init__(self, role_holders: dict[str, list[dict[str, Any]]]) -> None:
        self._holders = {rid: list(people) for rid, people in role_holders.items()}

    def is_valid_role(self, role_id: str) -> bool:
        return role_id in self._holders or is_well_formed_role_id(role_id)

    def holds(self, person_oid: str, role_id: str) -> bool:
        return any(p.get("oid") == person_oid for p in self._holders.get(role_id, []))

    def list_holders(self, role_id: str) -> list[dict[str, Any]]:
        return list(self._holders.get(role_id, []))

    def roles_of(self, person_oid: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for role_id, people in self._holders.items():
            if any(p.get("oid") == person_oid for p in people):
                out.append({"roleId": role_id, "displayName": role_id})
        return out
