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
from urllib.parse import quote

# Reserved separator between natural-key segments, and between the kind and the
# natural key in an item id. Matches the server's
# ``AgentConfigurationInventoryNaturalKey.KindSeparator``.
NATURAL_KEY_DELIMITER = ":"

# Tenant-root kinds carry an empty EnvironmentId. We model "no environment" as the
# empty string to match the server's ``(EnvironmentId, Kind)`` scoping where
# EnvironmentId is empty.
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
    """One unit of crawl bookkeeping: ``(EnvironmentId, Kind)``.

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
class FailedSyncItem:
    """One item the service accepted the call for but could not apply.

    ``failedItems`` is **partial success, not failure**: a 200 carrying entries here
    means every other item in the payload applied. The documented cause is a payload
    that carries a child while omitting the environment that contains it, so the
    remedy is a corrected payload on the next sync rather than a retry of this one.
    """

    item_id: str
    reason: str = ""


@dataclass
class SyncResult:
    """Outcome of one ``syncInventory`` call over the tenant's whole inventory.

    The submitted payload *is* the desired end state: the service upserts everything
    in it and retires every Active row it omits. There is no client-side diff, no
    per-row precondition, and no id list naming what to delete -- absence alone is the
    instruction.

    :attr:`retired_item_ids` is therefore the only place the caller learns what was
    removed, and it is worth surfacing verbatim: an unexpected entry there is the
    first visible symptom of a payload that was missing rows it should have carried.
    """

    submitted_count: int = 0
    upserted_count: int = 0
    retired_count: int = 0
    retired_item_ids: list[str] = field(default_factory=list)
    failed_items: list[FailedSyncItem] = field(default_factory=list)

    @property
    def failed_item_ids(self) -> list[str]:
        """Just the ids from :attr:`failed_items`, for logging and diagnostics."""
        return [f.item_id for f in self.failed_items]


@dataclass
class ScopeReport:
    """Per-scope crawl bookkeeping -- what the run may claim about one slice.

    Two different judgements live here, and conflating them is the mistake this class
    exists to prevent:

    - :attr:`complete` -- *was this scope read without error?* A failed or partial
      enumeration is not complete.
    - :attr:`authoritative` -- *does this run know everything that exists in this
      scope?* Only an authoritative scope may let absence mean deletion.

    A scope can be complete without being authoritative. The ESS kit reads its
    ``Connector`` scope perfectly, but only sees the connectors used by one
    environment, so a connector it did not list may simply live elsewhere.
    """

    scope: ScopeKey
    enumerated: int = 0
    # Items mapped successfully and included in the sync payload.
    mapped: int = 0
    skipped_invalid: int = 0
    fully_enumerated: bool = False
    error: str | None = None
    # Natural keys carried into the payload for this scope, for reporting and to make
    # duplicate detection attributable to a scope rather than a bare id.
    observed_keys: list[str] = field(default_factory=list)
    # True when the scope held more resources than the server's per-(tenant, kind) row
    # cap and was truncated to fit. Unlike an enumeration failure this does *not* block
    # the sync: the server cannot store more than the cap either, so the truncated set
    # is the most complete picture the inventory is able to hold.
    capped: bool = False
    # Resources dropped by that truncation, for reporting.
    truncated: int = 0
    # Schema-unlisted attribute keys dropped before mapping, for diagnostics.
    dropped_attributes: list[str] = field(default_factory=list)
    # Set by the runner: the platform surface vouches for seeing all of this scope.
    # See :attr:`authoritative`.
    covered: bool = False

    @property
    def complete(self) -> bool:
        """Was this scope read without error, and fully paged?

        Gated on :attr:`skipped_invalid`: an item that failed to map is a resource the
        crawl proved exists but cannot describe, so the payload will not carry it and
        the run cannot claim to have listed everything here.
        """
        return (
            self.fully_enumerated
            and self.error is None
            and self.skipped_invalid == 0
        )

    @property
    def authoritative(self) -> bool:
        """May absence in this scope be read as deletion?

        Both halves are required. :attr:`complete` says the read succeeded;
        :attr:`covered` says the surface was looking at the whole scope while it did.
        A truncated scope is deliberately excluded -- the rows beyond the cap were
        never sent, so treating them as absent would retire resources that exist.
        """
        return self.complete and self.covered and not self.capped


@dataclass
class RunSummary:
    """Structured per-run telemetry.

    ``correlation_id`` is a **local-only** log/trace id -- it is never sent to the
    Inventory API and never stamped onto rows.
    """

    correlation_id: str = ""
    scopes: list[ScopeReport] = field(default_factory=list)
    #: Scopes the run read completely *and* saw all of. Only these may have their
    #: absences read as deletions; everything else is carried forward untouched.
    authoritative_scopes: list[ScopeKey] = field(default_factory=list)
    #: Every item the crawl mapped, in the order collected, plus the rows carried
    #: forward from the service for scopes this run could not vouch for. This *is* the
    #: sync payload -- the tenant's whole desired inventory, all kinds mixed.
    payload: list[InventoryItem] = field(default_factory=list)
    #: False when the caller named specific environments rather than crawling every
    #: environment the Environment kind yielded. Reported, but not a gate: the rows of
    #: an environment that was never visited are carried forward, not dropped.
    full_crawl: bool = True
    #: Rows re-sent verbatim from the service purely so they are not retired.
    carried_forward: int = 0
    #: The service's response, or None when the run never earned the right to sync.
    synced: SyncResult | None = None
    #: Items carried in the payload, by ``kind`` discriminator.
    submitted_counts: dict[str, int] = field(default_factory=dict)
    retired_counts: dict[str, int] = field(default_factory=dict)
    aborted: bool = False
    #: Why the sync was withheld, when it was. Empty on a run that synced.
    sync_blocked_reason: str = ""
    #: True when the payload already matched the service, so the sync was skipped as a
    #: provable no-op. Distinct from a withheld run: nothing was wrong, and nothing
    #: needed doing.
    sync_unchanged: bool = False

    @property
    def completed_scopes(self) -> list[ScopeKey]:
        """Scopes read without error. A superset of :attr:`authoritative_scopes`."""
        return [r.scope for r in self.scopes if r.complete]

    @property
    def synced_ok(self) -> bool:
        """True when the tenant's inventory is known to match :attr:`payload`.

        Two runs satisfy that: one whose payload the service applied, and one whose
        payload the service already matched (so it was never sent). Both end with the
        same guarantee -- the server's state *is* the payload -- which is exactly what
        callers use this for: the local mirror refreshes off it, and refreshing is
        correct in both cases. A withheld or aborted run gives no such guarantee.
        """
        return (self.synced is not None or self.sync_unchanged) and not self.aborted
