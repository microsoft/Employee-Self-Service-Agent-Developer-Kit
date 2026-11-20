"""Crawler declaration type (spec §4)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from ..models import Kind
from ..platform_clients import Page, PlatformSurface

# A tenant-root enumerator: (platform, page_size) -> pages.
TenantRootEnumerator = Callable[[PlatformSurface, int], Iterator[Page]]
# An env-scoped enumerator: (platform, environment_id, page_size) -> pages.
EnvEnumerator = Callable[[PlatformSurface, str, int], Iterator[Page]]


@dataclass(frozen=True)
class Crawler:
    """Binds a :class:`Kind` to the platform surface that enumerates it (spec §4).

    Exactly one of ``tenant_root`` / ``env_scoped`` is set, matching ``kind.scope``.
    """

    kind: Kind
    tenant_root: TenantRootEnumerator | None = None
    env_scoped: EnvEnumerator | None = None

    def __post_init__(self) -> None:
        if self.kind.is_tenant_root and self.tenant_root is None:
            raise ValueError(f"{self.kind} is tenant-root but no tenant_root enumerator")
        if self.kind.is_env_scoped and self.env_scoped is None:
            raise ValueError(f"{self.kind} is env-scoped but no env_scoped enumerator")
