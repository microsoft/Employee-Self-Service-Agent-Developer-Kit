"""Core domain models for the Tenant Inventory discovery skill.

Grounding: ``Tenant-Inventory-DesignSpec.md`` (§5 model, §5.5 graph edges) and the
companion ADK implementation spec. Server-side storage/projection/redaction and the
``ensure-parent`` materialization are out of scope here -- these types model only what
the *skill* produces and sends on the wire.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote

# Reserved separator between natural-key segments, and between the kind and the
# natural key in an item id. Matches the server's
# ``AgentConfigurationInventoryNaturalKey.KindSeparator``.
NATURAL_KEY_DELIMITER = ":"

# Tenant-root kinds carry an empty EnvironmentId; reconcile treats them specially
# (spec §6.3 tenant-root exemption). We model "no environment" as the empty string to
# match the server's ``(EnvironmentId, Kind)`` scoping where EnvironmentId is empty.
TENANT_ROOT_ENVIRONMENT_ID = ""


class Scope(enum.Enum):
    """Whether a kind is enumerated once per tenant or once inside each environment."""

    TENANT_ROOT = "tenant-root"
    ENVIRONMENT = "env-scoped"


class Kind(enum.Enum):
    """The eight inventory kinds (spec §4).

    Each member records its crawl scope and the ordered set of attribute keys that
    compose its ``naturalKey``. Env-scoped kinds always lead with ``environmentId`` so
    the composed key is unique per environment.
    """

    ENVIRONMENT = ("Environment", Scope.TENANT_ROOT, ("environmentId",))
    ENTRA_APP = ("EntraApp", Scope.TENANT_ROOT, ("appId",))
    CONNECTOR = ("Connector", Scope.TENANT_ROOT, ("connectorId",))
    CONNECTION = ("Connection", Scope.ENVIRONMENT, ("environmentId", "connectionId"))
    SHAREPOINT_SITE = ("SharePointSite", Scope.TENANT_ROOT, ("siteUrl",))
    KNOWLEDGE_SOURCE = (
        "KnowledgeSource",
        Scope.ENVIRONMENT,
        ("environmentId", "botId", "sourceId"),
    )
    # The server's ExtensionPack schema carries no identity attribute of its own
    # (installed/hrsd/itsm/flavor/flowCount are all facts *about* one environment's
    # pack install), so the environment is the identity: one ExtensionPack row per
    # environment.
    EXTENSION_PACK = ("ExtensionPack", Scope.ENVIRONMENT, ("environmentId",))
    SCENARIO_TEMPLATE = (
        "ScenarioTemplate",
        Scope.ENVIRONMENT,
        ("environmentId", "uniqueName"),
    )

    def __init__(self, discriminator: str, scope: Scope, key_fields: tuple[str, ...]):
        self.discriminator = discriminator
        self.scope = scope
        self.key_fields = key_fields

    @property
    def is_env_scoped(self) -> bool:
        return self.scope is Scope.ENVIRONMENT

    @property
    def is_tenant_root(self) -> bool:
        return self.scope is Scope.TENANT_ROOT

    @classmethod
    def from_discriminator(cls, discriminator: str) -> Kind:
        for member in cls:
            if member.discriminator == discriminator:
                return member
        raise ValueError(f"Unknown kind discriminator: {discriminator!r}")

    def compose_natural_key(self, attributes: Mapping[str, object]) -> str:
        """Compose the natural key from the kind's identity fields.

        Mirrors the server's ``AgentConfigurationInventoryNaturalKey``:

        - A **single-segment** kind's natural key is the raw, un-encoded value
          (``Encode`` percent-encodes the whole thing when building the item id).
        - A **composite** kind uses ``ComposeNaturalKey``: each segment is
          percent-encoded independently and then joined with
          :data:`NATURAL_KEY_DELIMITER`, so the split stays unambiguous even when a
          segment itself contains the separator (a SharePoint ``siteUrl``, say).
        """
        parts: list[str] = []
        for field_name in self.key_fields:
            value = attributes.get(field_name)
            if value is None or value == "":
                raise ValueError(
                    f"{self.discriminator}: missing natural-key field {field_name!r}"
                )
            parts.append(str(value))

        if len(parts) == 1:
            return parts[0]
        return NATURAL_KEY_DELIMITER.join(quote(part, safe="") for part in parts)


def encode_item_id(kind: Kind, natural_key: str) -> str:
    """Build the opaque ``kind:naturalKey`` item id the service addresses rows by.

    Mirrors ``AgentConfigurationInventoryNaturalKey.Encode``. This is the value that
    goes in the ``agentConfigurationInventoryItems('<id>')`` route segment and comes
    back as ``agentConfigurationInventoryItemId``.
    """
    return f"{kind.discriminator}{NATURAL_KEY_DELIMITER}{quote(natural_key, safe='')}"


@dataclass(frozen=True)
class ScopeKey:
    """A reconcile scope: ``(EnvironmentId, Kind)`` (spec §6.3).

    Tenant-root kinds use :data:`TENANT_ROOT_ENVIRONMENT_ID` (empty string) for the
    environment component.
    """

    environment_id: str
    kind: Kind

    @classmethod
    def for_kind(cls, kind: Kind, environment_id: str | None = None) -> ScopeKey:
        if kind.is_tenant_root:
            return cls(TENANT_ROOT_ENVIRONMENT_ID, kind)
        if not environment_id:
            raise ValueError(f"{kind.discriminator} is env-scoped and needs environment_id")
        return cls(environment_id, kind)


@dataclass
class InventoryItem:
    """One resource mapped to a single inventory row.

    The skill sets only the fields below. It deliberately does **not** set
    ``source``/``submittedById``/``state``/``createdAt``/``updatedAt``/``version`` --
    the server stamps provenance (``Source = Discovered``), audit, and concurrency.
    """

    kind: Kind
    natural_key: str
    attributes: dict[str, object]
    environment_id: str | None = None  # containment edge; set for env-scoped kinds
    display_name: str | None = None
    description: str | None = None

    @property
    def scope_key(self) -> ScopeKey:
        return ScopeKey.for_kind(self.kind, self.environment_id)

    @property
    def item_id(self) -> str:
        """The opaque ``kind:naturalKey`` id the service addresses this row by."""
        return encode_item_id(self.kind, self.natural_key)


@dataclass
class UpsertResult:
    """Outcome of a single upsert POST."""

    natural_key: str
    kind: Kind
    item_id: str = ""
    etag: str | None = None
    created: bool = False


@dataclass
class ReconcileResult:
    """Outcome of one ``reconcile`` pass over a single (kind, environmentId) scope.

    Mirrors the service's ``AgentConfigurationInventoryReconcileResult``. A
    :attr:`retired_count` close to :attr:`evaluated_count` is the signal that the
    crawl that triggered it was incomplete.
    """

    kind: Kind
    environment_id: str
    evaluated_count: int = 0
    retired_count: int = 0
    retired_item_ids: list[str] = field(default_factory=list)


@dataclass
class ScopeReport:
    """Per-scope crawl bookkeeping -- the reconcile gate."""

    scope: ScopeKey
    enumerated: int = 0
    upserted: int = 0
    skipped_invalid: int = 0
    fully_enumerated: bool = False
    error: str | None = None
    # Natural keys successfully upserted in this scope. Used to diff against the
    # server's current rows when retiring drift for tenant-rooted kinds, which the
    # server-side reconcile refuses to handle.
    observed_keys: list[str] = field(default_factory=list)
    # True when the scope hit the server's per-(tenant, kind) row cap and was
    # truncated. A capped scope is never complete: retiring on a truncated view
    # would delete rows the crawl simply never reached.
    capped: bool = False
    # Schema-unlisted attribute keys dropped before upsert, for diagnostics.
    dropped_attributes: list[str] = field(default_factory=list)
    # Item ids retired by the client-side drift sweep (tenant-rooted kinds).
    retired_item_ids: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Reconcile-eligible only if fully enumerated, uncapped, and error-free."""
        return self.fully_enumerated and self.error is None and not self.capped


@dataclass
class RunSummary:
    """Structured per-run telemetry.

    ``correlation_id`` is a **local-only** log/trace id -- it is never sent to the
    Inventory API and never stamped onto rows. ``pass_started_at`` *is* sent: it is
    the watermark the server's reconcile uses to decide which rows this pass did not
    observe, so it must be captured before the first enumeration.
    """

    correlation_id: str = ""
    pass_started_at: datetime | None = None
    scopes: list[ScopeReport] = field(default_factory=list)
    completed_scopes: list[ScopeKey] = field(default_factory=list)
    reconciled: list[ReconcileResult] = field(default_factory=list)
    retired_counts: dict[str, int] = field(default_factory=dict)
    aborted: bool = False
