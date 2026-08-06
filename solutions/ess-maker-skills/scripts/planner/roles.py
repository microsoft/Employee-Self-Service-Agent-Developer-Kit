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
    (or resolving the caller via Work IQ).

A concrete source (Entra security groups via Graph, Work IQ, a static tenant
map, ...) can be injected later without touching the Plan schema or the skill.
No network here — the facade is pure; a backing source may do IO.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

# A well-formed role id is a lowercase, hyphen-joined token, e.g.
# "power-platform-admin", "integration-owner", "eval-author".
_ROLE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def is_well_formed_role_id(role_id: str) -> bool:
    """True if ``role_id`` looks like a role handle (the absent-safe check)."""
    return bool(role_id) and bool(_ROLE_ID_RE.match(role_id))


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
