"""Per-kind attribute schemas and caps.

This module is a **verbatim mirror of the server's authoritative schema**, so a
pre-validated item is one the service will accept:

- ``AgentConfigurationInventoryAttributeSchema.cs`` -- the per-kind allow-list
  (which keys are accepted, which are required, and the logical type each value
  must coerce to).
- ``AgentConfigurationInventoryConstants.Limits`` -- the hard caps.
- ``AgentConfigurationInventoryAttributeValidator.cs`` -- the validation order and
  semantics reproduced by :func:`validate_attributes`.

Two server behaviors drive the shape of this module:

1. **Attribute values are always strings on the wire.** ``Boolean``/``Integer``
   keys are *coerce-then-validated*: the value travels as a string that must parse
   to that type (``"true"``, ``"42"``), and is never re-serialized to a native JSON
   type. :func:`encode_attribute_value` produces that form.
2. **Unknown keys are rejected outright, not silently dropped** (the server's
   "D-validation" rule). The crawler therefore drops unlisted keys *itself* via
   :func:`drop_unlisted` before validating, so a discovered field the schema does
   not model can never fail the whole item.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from .models import Kind


class AttributeType(enum.Enum):
    """Logical type an attribute value must coerce to (server ``AttributeType``)."""

    STRING = "String"
    BOOLEAN = "Boolean"
    INTEGER = "Integer"


@dataclass(frozen=True)
class AttributeCaps:
    """Hard server-enforced limits (``AgentConfigurationInventoryConstants.Limits``).

    The skill pre-checks these to fail one item fast rather than have the service
    reject the request.
    """

    max_attribute_count: int = 32
    max_key_length: int = 128
    max_value_length: int = 1024
    max_display_name_length: int = 200
    max_description_length: int = 4000
    max_natural_key_length: int = 2048
    max_environment_id_length: int = 200

    # Max Active rows per (tenant, kind). The server throws an invariant violation on
    # the create that would exceed it, so the runner stops a scope at this many items
    # and reports it Incomplete rather than failing mid-crawl.
    max_items_per_tenant_and_kind: int = 50


@dataclass(frozen=True)
class AttributeSpec:
    """One entry of a kind's attribute allow-list."""

    key: str
    required: bool
    type: AttributeType


@dataclass(frozen=True)
class KindSchema:
    """The ordered, authoritative attribute allow-list for a kind."""

    kind: Kind
    entries: tuple[AttributeSpec, ...]

    @property
    def required(self) -> frozenset[str]:
        return frozenset(e.key for e in self.entries if e.required)

    @property
    def optional(self) -> frozenset[str]:
        return frozenset(e.key for e in self.entries if not e.required)

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(e.key for e in self.entries)

    def spec_for(self, key: str) -> AttributeSpec | None:
        for entry in self.entries:
            if entry.key == key:
                return entry
        return None


def _req(key: str, type_: AttributeType = AttributeType.STRING) -> AttributeSpec:
    return AttributeSpec(key, required=True, type=type_)


def _opt(key: str, type_: AttributeType = AttributeType.STRING) -> AttributeSpec:
    return AttributeSpec(key, required=False, type=type_)


_BOOL = AttributeType.BOOLEAN
_INT = AttributeType.INTEGER


# Mirrors AgentConfigurationInventoryAttributeSchema.SchemasByKind exactly. Keep the
# ordering and the required/optional split in sync with the server.
_SCHEMAS: dict[Kind, KindSchema] = {
    Kind.ENVIRONMENT: KindSchema(
        Kind.ENVIRONMENT,
        (
            _req("environmentId"),
            _opt("environmentUrl"),
            _opt("region"),
            _opt("type"),
        ),
    ),
    Kind.ENTRA_APP: KindSchema(
        Kind.ENTRA_APP,
        (
            _req("appId"),
            _opt("objectId"),
            _opt("tenantId"),
            _opt("displayName"),
        ),
    ),
    Kind.CONNECTOR: KindSchema(
        Kind.CONNECTOR,
        (
            _req("connectorId"),
            _opt("publisher"),
            _opt("tier"),
            _opt("displayName"),
        ),
    ),
    Kind.CONNECTION: KindSchema(
        Kind.CONNECTION,
        (
            _req("connectionId"),
            _req("environmentId"),
            _opt("connectorId"),
            _opt("connectionReferenceName"),
            _opt("connectionReferenceLogicalName"),
            _opt("status"),
            _opt("displayName"),
        ),
    ),
    Kind.SHAREPOINT_SITE: KindSchema(
        Kind.SHAREPOINT_SITE,
        (
            _req("siteUrl"),
            _opt("siteId"),
            _opt("listId"),
            _opt("displayName"),
        ),
    ),
    Kind.KNOWLEDGE_SOURCE: KindSchema(
        Kind.KNOWLEDGE_SOURCE,
        (
            _req("sourceId"),
            _req("environmentId"),
            _req("botId"),
            _opt("sourceType"),
            _opt("uri"),
            _opt("displayName"),
        ),
    ),
    Kind.EXTENSION_PACK: KindSchema(
        Kind.EXTENSION_PACK,
        (
            _req("installed", _BOOL),
            _req("environmentId"),
            _opt("flowCount", _INT),
            _opt("hrsd", _BOOL),
            _opt("itsm", _BOOL),
            _opt("flavor"),
        ),
    ),
    Kind.SCENARIO_TEMPLATE: KindSchema(
        Kind.SCENARIO_TEMPLATE,
        (
            _req("uniqueName"),
            _req("environmentId"),
            _opt("connectorId"),
            _opt("operation"),
            _opt("status"),
        ),
    ),
}


def schema_for(kind: Kind) -> KindSchema:
    return _SCHEMAS[kind]


class AttributeValidationError(ValueError):
    """Raised when an item's attributes violate the server schema or caps."""


def encode_attribute_value(value: object) -> str:
    """Render an attribute value in the server's wire form (always a string).

    ``bool`` is emitted lowercase so it round-trips through .NET ``bool.TryParse``;
    everything else falls back to ``str``. ``None`` becomes an empty string rather
    than the literal ``"None"``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def drop_unlisted(
    kind: Kind, attributes: dict[str, object]
) -> tuple[dict[str, object], list[str]]:
    """Split ``attributes`` into the schema-allowed subset and the dropped keys.

    The server rejects an unknown key outright, which would fail the entire item, so
    the crawler drops what the schema does not model and keeps the rest. Returns
    ``(kept, dropped_keys)``; ``dropped_keys`` is sorted for stable logging.
    """
    allowed = schema_for(kind).allowed
    kept = {k: v for k, v in attributes.items() if k in allowed}
    dropped = sorted(k for k in attributes if k not in allowed)
    return kept, dropped


def _coerces_to(value: object, type_: AttributeType) -> bool:
    """Mirror of the server's ``ValidateCoercesToType`` over the *string* wire form."""
    raw = encode_attribute_value(value)
    if type_ is AttributeType.BOOLEAN:
        return raw.strip().lower() in {"true", "false"}
    if type_ is AttributeType.INTEGER:
        try:
            int(raw.strip())
        except ValueError:
            return False
        return True
    return True


def validate_attributes(
    kind: Kind,
    attributes: dict[str, object],
    caps: AttributeCaps | None = None,
) -> None:
    """Pre-validate attributes against the server schema and caps.

    Reproduces ``AgentConfigurationInventoryAttributeValidator`` in the same order:
    attribute count cap, per-key/value length caps, unknown keys, missing required
    keys, then type coercion. A missing **required** key is never silently dropped --
    the item is failed and the caller logs and skips it, which makes its scope
    incomplete.
    """
    caps = caps or AttributeCaps()
    schema = schema_for(kind)

    if len(attributes) > caps.max_attribute_count:
        raise AttributeValidationError(
            f"{kind.discriminator}: attributes has {len(attributes)} entries; max is "
            f"{caps.max_attribute_count}"
        )

    for key, value in attributes.items():
        if len(key) > caps.max_key_length:
            raise AttributeValidationError(
                f"{kind.discriminator}: attribute key {key!r} exceeds the maximum "
                f"length of {caps.max_key_length}"
            )
        if len(encode_attribute_value(value)) > caps.max_value_length:
            raise AttributeValidationError(
                f"{kind.discriminator}: value for {key!r} exceeds the maximum length "
                f"of {caps.max_value_length}"
            )

    unlisted = attributes.keys() - schema.allowed
    if unlisted:
        raise AttributeValidationError(
            f"{kind.discriminator}: not an allowed attribute: {sorted(unlisted)}"
        )

    missing = schema.required - attributes.keys()
    if missing:
        raise AttributeValidationError(
            f"{kind.discriminator}: missing required attribute(s): {sorted(missing)}"
        )

    for entry in schema.entries:
        if entry.key not in attributes:
            continue
        if not _coerces_to(attributes[entry.key], entry.type):
            raise AttributeValidationError(
                f"{kind.discriminator}: {entry.key!r} must be a "
                f"{entry.type.value.lower()}; got "
                f"{encode_attribute_value(attributes[entry.key])!r}"
            )
