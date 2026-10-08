"""Deliver the migrated customizations straight into a live Declarative Agent.

This is the *prod-capable* write path, and the counterpart to :mod:`essmig.deliver`.
Where :mod:`deliver` posts a whole ALM package to ``minimalBots/alm/import`` — an
endpoint that only exists on the development rings and so can never reach a
customer's production agent — this module speaks the **MinimalBot components API**
that Copilot Studio itself uses to author an agent, and which is reachable on every
ring (test / preprod / prod)::

    POST {host}/copilotstudio/minimalBots/api/{botId}/components?api-version=...
        -> all components + a changeToken   (read, non-mutating)
    PUT  {host}/copilotstudio/minimalBots/api/{botId}/components?api-version=...
        {changeToken, botComponentChanges:[...], ...}   (write, concurrency-guarded)

The host is derived from the target environment GUID and the ring the agent lives
on, exactly as the shipping ADK does (``solutions/ess-maker-skills`` —
``minimalbot_evaluation.py`` / ``agentbuilder.RING_CONFIG``). The ring in turn is
derived from the agent's ``powerPlatformApiEndpoint`` and defaults to **prod** when
unknown, so a real customer agent is never assumed to be on a test ring.

What we deliver is the *delta*, not the whole agent — and the delivery is a
**hybrid** of two mechanisms, because the on-disk ALM authoring form and the
components-API runtime form are not the same shape:

* :attr:`Outcome.MERGED` — a customer edit to a topic the template already ships.
  The template topic already lives on the target in the API's *expanded runtime*
  form (typed expression objects, structured condition ASTs, tokenized message
  templates). The migration's merged ``agent.yml`` is the *compact ALM authoring*
  form (expressions as strings). Rather than compile the compact form up to the
  runtime graph (a large, fragile ALM→runtime compiler), we **overlay** just the
  customer's plain-text field edits onto the live component that is already valid
  by construction — see :func:`overlay_edits`. This is delivered live, on any ring.
* :attr:`Outcome.CARRIED_NEW` — a brand-new, customer-authored topic with no
  template counterpart. There is no live component to overlay onto and its compact
  body cannot be faithfully compiled to the runtime form, so it is **not** written
  through the components API; it is **routed to the ALM package import** instead
  (see :mod:`essmig.deliver`) and reported as such.

Everything the migration left on the template (``UNCHANGED``), could not carry
(``MANUAL`` / ``BLOCKED`` / ``LOCKED`` / ``NO_TARGET`` / ``FAILED``) or kept the
template's side of (``CONFLICTED``) is intentionally *not* written here, so the
blast radius is exactly the set of customizations the tool could apply.

.. note::
   The components API is the same transport the shipping ADK uses for *evaluation*
   components (``TestCaseComponent``); overlaying a customer's text edits onto an
   existing *topic / dialog / gpt* component has been exercised against a live
   Cosmos-backed ESS DA GA (read + update succeed). For safety the delivery still
   runs in **dry-run by default**: it reads the target, builds and prints the exact
   change set, and writes nothing until the operator passes ``--deliver-apply``.
   Validate the printed change set before a customer run.
"""

from __future__ import annotations

import copy
import re
import socket
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from essmig.auth import TokenProvider
from essmig.ess import schema_suffix

# --- Ring / host / scope ----------------------------------------------------
#
# Mirrors ``solutions/ess-maker-skills/scripts/agentbuilder.RING_CONFIG``. Kept as
# a local copy (the two projects do not share a package) so the migration tool has
# no import-time dependency on the ADK.
RING_CONFIG: dict[str, dict[str, Any]] = {
    "prod": {
        "audience": "https://api.powerplatform.com",
        "host_suffix": "environment.api.powerplatform.com",
        "primary_split": 30,
    },
    "preprod": {
        "audience": "https://api.preprod.powerplatform.com",
        "host_suffix": "environment.api.preprod.powerplatform.com",
        "primary_split": 31,
    },
    "test": {
        "audience": "https://api.test.powerplatform.com",
        "host_suffix": "environment.api.test.powerplatform.com",
        "primary_split": 31,
    },
}
DEFAULT_RING = "prod"
COMPONENTS_API_VERSION = "2022-03-01-preview"

# The components API is an UPSERT keyed by (component id, version): every change is
# sent as a BotComponentInsert, and the service decides insert-vs-update from whether
# the id already exists (confirmed live — re-sending an existing component as
# BotComponentInsert returns 200 and the service echoes it back as a
# "BotComponentUpdate" with the version bumped). An update therefore must carry the
# component's *current* server-side version; the service increments it.
INSERT_KIND = "BotComponentInsert"
# The service's echo discriminator for an upsert that hit an existing component. We
# never send this kind; it is here only to name what comes back on a verify read.
UPDATE_KIND = "BotComponentUpdate"

_DELIVER_TIMEOUT_SECONDS = 300.0
_GUID_RE = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


def _auth_headers(token_provider: TokenProvider, scope: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token_provider.get_token(scope)}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


class DeliveryError(ValueError):
    """The delivery target is not usable as given."""


def ring_for_endpoint(endpoint: str | None) -> str:
    """Map a ``powerPlatformApiEndpoint`` host to its ring, defaulting to prod.

    An absent or unrecognised endpoint resolves to ``prod`` so a real agent is
    never assumed to be on a development ring — the same conservative default the
    ADK uses.
    """
    host = (endpoint or "").strip()
    if not host:
        return DEFAULT_RING
    hostname = (urlparse(host).hostname or host).casefold().rstrip(".")
    for ring, config in RING_CONFIG.items():
        if hostname.endswith(f".{str(config['host_suffix']).casefold()}") or (
            hostname == str(config["host_suffix"]).casefold()
        ):
            return ring
    return DEFAULT_RING


def audience_for_ring(ring: str) -> str:
    config = RING_CONFIG.get(ring) or RING_CONFIG[DEFAULT_RING]
    return str(config["audience"])


# The delegated Copilot Studio MinimalBot scope the ADK uses (``agentbuilder``
# ``minimal_bot_scope``). ``ReadWrite`` covers both the listing/metadata/component
# reads and the component write, so a single interactively-consented token serves
# the whole flow. Requesting this *specific* scope (rather than ``/.default``)
# triggers incremental consent, so the token actually carries MinimalBot
# permissions — with ``/.default`` the listing can come back empty when those
# permissions were never statically consented for the first-party client.
_MINIMALBOT_SCOPE_SUFFIX = "CopilotStudio.MinimalBot.ReadWrite"


def scope_for_ring(ring: str) -> str:
    """The delegated Copilot Studio MinimalBot (read/write) scope for ``ring``."""
    return f"{audience_for_ring(ring)}/{_MINIMALBOT_SCOPE_SUFFIX}"


def environment_host(
    environment_id: str,
    ring: str,
    *,
    resolver: Any = socket.getaddrinfo,
) -> str:
    """Derive the environment API host from an environment GUID for ``ring``.

    Copilot Studio addresses each environment at ``https://{split-guid}.{suffix}``
    where the split index and suffix are ring-specific (see :data:`RING_CONFIG`).
    The standard split occasionally differs by one, so — exactly as the ADK's
    ``derive_environment_host`` does — both candidate splits are probed by DNS and
    the one that resolves is used, falling back to the ring's primary split when
    neither can be checked (e.g. offline).
    """
    config = RING_CONFIG.get(ring) or RING_CONFIG[DEFAULT_RING]
    suffix = str(config["host_suffix"])
    primary = int(config["primary_split"])
    compact = uuid.UUID(environment_id).hex
    for split in (primary, 31 if primary == 30 else 30):
        hostname = f"{compact[:split]}.{compact[split:]}.{suffix}"
        try:
            resolver(hostname, 443)
        except OSError:
            continue
        return f"https://{hostname}"
    return f"https://{compact[:primary]}.{compact[primary:]}.{suffix}"


@dataclass(frozen=True)
class MinimalBotTarget:
    """Everything needed to address one live Declarative Agent's component store."""

    bot_id: str
    environment_id: str
    tenant_id: str
    ring: str = DEFAULT_RING
    host: str | None = None
    api_version: str = COMPONENTS_API_VERSION

    def __post_init__(self) -> None:
        if not _GUID_RE.match(self.bot_id.strip()):
            raise DeliveryError(f"target bot id is not a GUID: {self.bot_id!r}")
        if not _GUID_RE.match(self.environment_id.strip()):
            raise DeliveryError(
                f"target environment id is not a GUID: {self.environment_id!r}"
            )
        if not self.tenant_id.strip():
            raise DeliveryError("target tenant id must not be empty.")
        if self.ring not in RING_CONFIG:
            raise DeliveryError(
                f"unknown ring {self.ring!r}; expected one of {sorted(RING_CONFIG)}."
            )
        if self.host is None:
            object.__setattr__(
                self, "host", environment_host(self.environment_id.strip(), self.ring)
            )
        parsed = urlparse(str(self.host))
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise DeliveryError(f"target host must be an HTTPS URL: {self.host!r}")

    @property
    def scope(self) -> str:
        return scope_for_ring(self.ring)

    @property
    def components_url(self) -> str:
        return (
            f"{str(self.host).rstrip('/')}/copilotstudio/minimalBots/api/"
            f"{self.bot_id}/components?api-version={self.api_version}"
        )


@dataclass(frozen=True)
class PlannedChange:
    """One component the delivery would write, for the report and the console."""

    schema_name: str
    kind: str
    action: str  # "update" (overlay sent live) | "package" (routed to ALM import)


@dataclass
class MinimalBotDeliveryResult:
    """The outcome of a delivery attempt (or dry-run), for the report and console."""

    ok: bool
    dry_run: bool
    endpoint: str
    bot_id: str
    ring: str
    planned: list[PlannedChange] = field(default_factory=list)
    deferred: list[PlannedChange] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    inserted: int = 0
    updated: int = 0
    renamed_to: str | None = None
    status: int | None = None
    detail: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dryRun": self.dry_run,
            "endpoint": self.endpoint,
            "botId": self.bot_id,
            "ring": self.ring,
            "inserted": self.inserted,
            "updated": self.updated,
            "renamedTo": self.renamed_to,
            "status": self.status,
            "detail": self.detail,
            "changes": [
                {"schemaName": c.schema_name, "kind": c.kind, "action": c.action}
                for c in self.planned
            ],
            "deferredToPackage": [
                {"schemaName": c.schema_name, "kind": c.kind}
                for c in self.deferred
            ],
            "unappliedEdits": list(self.notes),
        }


# --- Change-set construction ------------------------------------------------

# Outcomes whose component we deliver. Everything else is, by design, left on the
# target's template (or could not be carried) and so is never written here.
_DELIVERABLE = frozenset({"merged", "carried-new"})


# --- The customer-edit overlay ---------------------------------------------
#
# A topic the template ships already lives on the target in the components API's
# *expanded runtime* form. The migration's merged agent.yml is the *compact ALM*
# form. We never compile compact->runtime; instead we overlay the customer's
# plain-text field edits onto the live (already-valid) component. The overlay
# walks the merged (compact) entry and the live (expanded) component in parallel:
#
#   * two plain scalars that differ  -> the customer edited it; write merged->live
#   * a scalar over a runtime object -> an expression field (value/condition/…).
#     We reconstruct the object's compact form and, only if it differs from the
#     merged scalar, record an "unapplied edit" note (an edit we cannot compile).
#   * keys/list items in the package but absent on the live component are a
#     structural/template-version difference (authoring metadata, a newer template
#     action), NOT a customer text edit. The hybrid carries only edits to fields
#     that exist on the live component, so these are left off deliberately and
#     silently — surfacing them would bury the real edits in noise.
#   * keys absent in merged (e.g. a removed node) are a known MVP gap: the walk is
#     merged-driven, so a live-only key is simply left in place.

# Keys used to align list items across the two shapes (fall back to position).
_ITEM_KEYS = ("id", "propertyName", "schemaName", "name", "variable")


def _item_key(item: Any) -> tuple[str, str] | None:
    if isinstance(item, Mapping):
        for key in _ITEM_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return (key, value)
    return None


def _compact_of_expression(live: Mapping[str, Any]) -> tuple[bool, Any]:
    """Reconstruct the compact ALM string a runtime expression object came from.

    Returns ``(known, compact)``. ``known`` is ``False`` when the object is a shape
    we do not reconstruct (message templates, adaptive cards, nested typed graphs);
    the caller then declines to judge whether a compact scalar is an edit.
    """
    kind = str(live.get("$kind") or "")
    if "literalValue" in live:
        return True, live["literalValue"]
    if "variableReference" in live:
        return True, f"={live['variableReference']}"
    if "expressionText" in live:
        if kind == "AdaptiveCardExpression":
            return False, None
        return True, f"={live['expressionText']}"
    return False, None


# ``${config.values["KEY"]}`` ALM pointers are substituted at *import* time. The
# components API is written directly, bypassing that import, so any pointer the
# merged agent.yml left in place (e.g. the agent's display name resolves from
# ``gptDisplayName``) must be resolved here or it would land on the live agent as a
# literal token.
_CONFIG_TOKEN_RE = re.compile(r'\$\{config\.values\["([^"]+)"\]\}')


def _resolve_config_tokens(value: Any, values: Mapping[str, Any]) -> Any:
    """Resolve ``${config.values["KEY"]}`` ALM pointers against ``values``.

    Strings, mappings and lists are walked. A pointer with no matching value is
    left intact; the overlay then declines to write an unresolved token over the
    live value (see :func:`_overlay_node`).
    """
    if isinstance(value, str):
        return _CONFIG_TOKEN_RE.sub(
            lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0),
            value,
        )
    if isinstance(value, Mapping):
        return {key: _resolve_config_tokens(item, values) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_config_tokens(item, values) for item in value]
    return value


def overlay_edits(
    live: Mapping[str, Any],
    merged: Mapping[str, Any],
    values: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Overlay the customer's plain-text edits (from ``merged``) onto ``live``.

    ``live`` is the component as the components API returned it (expanded runtime
    form, valid by construction); ``merged`` is the migration's compact agent.yml
    entry for the same schema. ``values`` is the package's ``config.values`` map,
    used to resolve ``${config.values[...]}`` pointers (e.g. the display name)
    before they are overlaid. Returns ``(patched_live, notes)`` where ``notes``
    lists edits that could not be safely applied (expression/structural edits).
    """
    notes: list[str] = []
    resolved = _resolve_config_tokens(merged, values or {})
    patched = _overlay_node(copy.deepcopy(dict(live)), resolved, "", notes)
    if not isinstance(patched, dict):  # pragma: no cover - live is always a dict
        return dict(live), notes
    return patched, notes


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _overlay_node(live: Any, merged: Any, path: str, notes: list[str]) -> Any:
    if isinstance(merged, Mapping):
        if not isinstance(live, dict):
            if merged != live:
                notes.append(f"{path or '.'}: structural change not applied")
            return live
        for key, mval in merged.items():
            wire_key = "$kind" if key == "kind" else key
            if wire_key in live:
                live[wire_key] = _overlay_node(
                    live[wire_key], mval, _join(path, wire_key), notes
                )
            # A key present in the package but absent on the live component is a
            # structural/template-version difference (e.g. authoring metadata or a
            # newer template action), NOT a customer text edit. The hybrid carries
            # only edits to fields that exist on the live component, so it is left
            # off deliberately and silently — surfacing it would be pure noise.
        return live
    if isinstance(merged, list):
        if not isinstance(live, list):
            if merged != live:
                notes.append(f"{path or '.'}: list change not applied")
            return live
        return _overlay_list(live, merged, path, notes)
    # merged is a scalar.
    if isinstance(merged, str) and _CONFIG_TOKEN_RE.search(merged):
        # An ALM config pointer we could not resolve (no matching config value).
        # Writing the literal token onto the live agent is worse than leaving the
        # target's own value in place, so decline the edit.
        notes.append(f"{path or '.'}: unresolved config pointer left as-is")
        return live
    if isinstance(live, Mapping):
        if live.get("$kind") == "TemplateLine" and isinstance(merged, str):
            return _overlay_template_line(live, merged, path, notes)
        known, compact = _compact_of_expression(live)
        if known and compact != merged:
            notes.append(f"{path or '.'}: edit to an expression field not applied")
        return live
    if isinstance(live, list):
        return live
    return merged if merged != live else live


def _overlay_list(
    live: list[Any], merged: list[Any], path: str, notes: list[str]
) -> list[Any]:
    live_by_key: dict[tuple[str, str], int] = {}
    for index, item in enumerate(live):
        key = _item_key(item)
        if key is not None and key not in live_by_key:
            live_by_key[key] = index
    used: set[int] = set()
    for position, mitem in enumerate(merged):
        mkey = _item_key(mitem)
        live_index: int | None = None
        if mkey is not None and mkey in live_by_key:
            live_index = live_by_key[mkey]
        elif mkey is None and position < len(live):
            live_index = position
        if live_index is None or live_index in used:
            # A package list item with no live counterpart is a structural/template
            # difference, not a customer edit — left off deliberately and silently.
            continue
        used.add(live_index)
        label = mkey[1] if mkey is not None else str(position)
        live[live_index] = _overlay_node(
            live[live_index], mitem, f"{path}[{label}]", notes
        )
    return live


# --- GPT instruction overlay (TemplateLine) --------------------------------
#
# The agent's instructions live on the target as a TemplateLine: an alternating
# run of TextSegment (plain prose) and ExpressionSegment (a typed variable
# reference, e.g. ``{System.User.DisplayName}``). The merged agent.yml carries the
# same instructions as a single compact string with ``{token}`` interpolations.
# To deliver the customer's edits we rebuild the whole TemplateLine from the merged
# string: each ``{token}`` becomes an ExpressionSegment (reusing the live segment
# object where a leading token matches, and otherwise cloning a live segment's
# shape for newer-template references the target did not yet have — a form the
# components API accepts), with the merged prose carried verbatim between them.

_TEMPLATE_TOKEN_RE = re.compile(r"\{([^{}]*)\}")


def _expr_segment_token(segment: Mapping[str, Any]) -> str | None:
    expression = segment.get("expression")
    if not isinstance(expression, Mapping):
        return None
    for key in ("variableReference", "expressionText"):
        value = expression.get(key)
        if isinstance(value, str):
            return value
    if "literalValue" in expression:
        return str(expression["literalValue"])
    return None


def _split_template_line(
    line: Mapping[str, Any],
) -> tuple[list[str], list[tuple[str, Mapping[str, Any]]]] | None:
    """Split a live TemplateLine into (text runs, expression tokens+segments).

    Returns ``None`` when the line holds a segment kind we do not model, so the
    caller falls back to keeping the live value untouched.
    """
    segments = line.get("segments")
    if not isinstance(segments, list):
        return None
    texts: list[str] = [""]
    exprs: list[tuple[str, Mapping[str, Any]]] = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            return None
        kind = segment.get("$kind")
        if kind == "TextSegment":
            value = segment.get("value")
            if not isinstance(value, str):
                return None
            texts[-1] += value
        elif kind == "ExpressionSegment":
            token = _expr_segment_token(segment)
            if token is None:
                return None
            exprs.append((token, segment))
            texts.append("")
        else:
            return None
    return texts, exprs


def _split_compact_instructions(text: str) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    tokens: list[str] = []
    last = 0
    for match in _TEMPLATE_TOKEN_RE.finditer(text):
        texts.append(text[last : match.start()])
        tokens.append(match.group(1))
        last = match.end()
    texts.append(text[last:])
    return texts, tokens


def _join_compact_instructions(texts: list[str], tokens: list[str]) -> str:
    out = texts[0]
    for index, token in enumerate(tokens):
        out += "{" + token + "}" + texts[index + 1]
    return out


def _text_segment(value: str) -> dict[str, Any]:
    return {"$kind": "TextSegment", "value": value}


def _expr_segment_shape(
    live_exprs: list[tuple[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    """A deep copy of a live ExpressionSegment to clone for fabricated tokens.

    Cloning a real live segment preserves the exact ``$kind`` nesting the target
    uses (e.g. ``ValueExpression``/``variableReference``), so a fabricated segment
    for a newer-template token matches the shape the service already accepts.
    Falls back to the canonical ``ValueExpression`` shape when the live line has no
    expression segment to copy.
    """
    if live_exprs:
        return copy.deepcopy(dict(live_exprs[0][1]))
    return {
        "$kind": "ExpressionSegment",
        "expression": {"$kind": "ValueExpression", "variableReference": ""},
    }


def _make_expr_segment(shape: Mapping[str, Any], token: str) -> dict[str, Any]:
    """Clone ``shape`` and point it at ``token`` (the ``{...}`` interior)."""
    seg = copy.deepcopy(dict(shape))
    expr = seg.get("expression")
    if isinstance(expr, dict):
        for key in ("variableReference", "expressionText"):
            if key in expr:
                expr[key] = token
                break
        else:
            expr["variableReference"] = token
    return seg


def _overlay_template_line(
    live: Mapping[str, Any], merged: str, path: str, notes: list[str]
) -> Any:
    split = _split_template_line(live)
    if split is None:
        notes.append(f"{path or '.'}: instructions kept as-is (unmodelled segment)")
        return live
    live_texts, live_exprs = split
    live_tokens = [token for token, _ in live_exprs]

    # Guard against literal braces in the merged prose: if splitting the merged
    # instructions into {token} runs and rejoining them does not round-trip, our
    # parser is unsafe here, so keep the live value rather than risk corrupting it.
    merged_texts, merged_tokens = _split_compact_instructions(merged)
    if _join_compact_instructions(merged_texts, merged_tokens) != merged:
        notes.append(f"{path or '.'}: instructions kept as-is (ambiguous braces)")
        return live

    if _join_compact_instructions(live_texts, live_tokens) == merged:
        return live  # nothing changed

    # Rebuild the entire TemplateLine from the customer's merged instructions.
    # Every {token} becomes an ExpressionSegment: where a leading token matches the
    # live line we reuse the live segment object verbatim; newer-template tokens the
    # target did not have are fabricated by cloning a live segment's shape (proven
    # accepted by the components API). This carries the customer's full prose —
    # including text past the last shared expression — not just the common prefix.
    shape = _expr_segment_shape(live_exprs)
    new_segments: list[Any] = [_text_segment(merged_texts[0])]
    for index, token in enumerate(merged_tokens):
        if index < len(live_exprs) and live_tokens[index] == token:
            new_segments.append(dict(live_exprs[index][1]))
        else:
            new_segments.append(_make_expr_segment(shape, token))
        new_segments.append(_text_segment(merged_texts[index + 1]))

    patched = dict(live)
    patched["segments"] = new_segments
    return patched


def _schema_of(entry: Mapping[str, Any]) -> str:
    return str(entry.get("schemaName") or "").strip()


def _deliverable_suffixes(results: Iterable[Any]) -> set[str]:
    """The agent-independent suffixes the migration marked MERGED or CARRIED_NEW.

    The component *schema name* carries an agent-specific prefix that differs
    between the source CA (e.g. ``msdyn_...``) and the target DA (``gptagent_...``),
    so the stable join key is the suffix (``topic.ConversationStart``). A
    :class:`~essmig.merge.ComponentResult` exposes it directly as ``suffix``; for a
    duck-typed result it is derived from ``schemaname``.
    """
    suffixes: set[str] = set()
    for result in results:
        if str(getattr(result, "outcome", "")) not in _DELIVERABLE:
            continue
        suffix = str(getattr(result, "suffix", "") or "").strip()
        if not suffix:
            suffix = schema_suffix(str(getattr(result, "schemaname", "") or "").strip())
        if suffix:
            suffixes.add(suffix)
    return suffixes


def plan_changes(
    agent: Mapping[str, Any],
    results: Iterable[Any],
    existing: Mapping[str, OnTargetComponent],
    config_values: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[PlannedChange], list[PlannedChange], list[str]]:
    """Build the hybrid change set: overlays to send live + topics to route to import.

    ``agent`` is the merged ``agent.yml`` document (a ``BotDefinition`` with a
    ``components`` list); ``results`` are the per-component :class:`Outcome`s;
    ``existing`` maps an on-target component's ``schemaName`` to its id, current
    version and live body (from :func:`existing_components`). ``config_values`` is
    the package's ``config.values`` map, used to resolve ``${config.values[...]}``
    pointers (e.g. the agent display name) before they are overlaid.

    Returns ``(changes, planned, deferred, notes)``:

    * ``changes`` — ``botComponentChanges`` to PUT. Each is a ``BotComponentInsert``
      wrapping the **live** component with the customer's plain-text edits overlaid,
      carried at its current id + version (the API is an upsert; the service bumps
      the version). Only components that already exist on the target produce a
      change — those are the shipped topics the customer edited.
    * ``planned`` — the human-readable plan for ``changes`` (action ``update``).
    * ``deferred`` — components with no live counterpart (new, customer-authored
      topics). These cannot be compiled to the runtime form, so they are routed to
      the ALM package import (action ``package``), not written here.
    * ``notes`` — per-field edits that could not be safely overlaid (edits to
      expression/structured fields), for the report.

    The schema prefix differs between the CA and the DA, so the suffix is the join
    key for selecting deliverable components (see :func:`_deliverable_suffixes`).
    """
    deliverable = _deliverable_suffixes(results)
    components = agent.get("components")
    if not isinstance(components, list):
        return [], [], [], []

    changes: list[dict[str, Any]] = []
    planned: list[PlannedChange] = []
    deferred: list[PlannedChange] = []
    notes: list[str] = []
    for entry in components:
        if not isinstance(entry, Mapping):
            continue
        schema = _schema_of(entry)
        if not schema or schema_suffix(schema) not in deliverable:
            continue
        kind = str(entry.get("kind") or "").strip()
        if not kind:
            continue

        on_target = existing.get(schema)
        if on_target is None:
            # No live counterpart: a brand-new topic. It cannot be compiled to the
            # runtime form, so route it to the ALM package import instead.
            deferred.append(PlannedChange(schema_name=schema, kind=kind, action="package"))
            continue

        # Overlay the customer's plain-text edits onto the live (valid) component,
        # then address it for the upsert at its current id + version.
        component, component_notes = overlay_edits(on_target.body, entry, config_values)
        component["id"] = on_target.id
        component["version"] = on_target.version
        component["extensionData"] = {"UseProvidedBotComponentId": True}

        changes.append({"$kind": INSERT_KIND, "component": component})
        planned.append(PlannedChange(schema_name=schema, kind=kind, action="update"))
        notes += [f"{schema}: {note}" for note in component_notes]
    return changes, planned, deferred, notes


def plan_bot_entity_update(
    agent: Mapping[str, Any],
    read_body: Mapping[str, Any],
    config_values: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Overlay the customer's agent display name onto the live BotEntity.

    The *main-panel* agent name is the Dataverse ``BotEntity``'s ``displayName`` —
    a record the component upsert never touches. (The upsert only sets the
    ``GptComponent``'s own displayName, which is what the *test panel* shows.) To
    rename the agent itself the fetched bot entity is sent back with its displayName
    overlaid, exactly as Copilot Studio's own authoring does — a PUT carrying
    ``{"bot": <entity>, "botComponentChanges": []}`` (see the ESS ADK
    ``agentbuilder.update_bot_entity``).

    Returns ``(patched_bot, new_name)``, or ``(None, None)`` when the target returned
    no bot entity, the merged agent carries no display name, the name is unchanged,
    or the name is an unresolved ``${config.values[...]}`` pointer.
    """
    live_bot = read_body.get("bot")
    if not isinstance(live_bot, Mapping):
        return None, None
    entity = agent.get("entity")
    if not isinstance(entity, Mapping):
        return None, None
    desired = _resolve_config_tokens(entity.get("displayName"), config_values or {})
    if not isinstance(desired, str) or not desired.strip():
        return None, None
    if _CONFIG_TOKEN_RE.search(desired):
        return None, None
    if str(live_bot.get("displayName") or "") == desired:
        return None, None
    patched = copy.deepcopy(dict(live_bot))
    patched["displayName"] = desired
    return patched, desired


# --- Transport --------------------------------------------------------------


class MinimalBotComponentsClient:
    """Thin client over the MinimalBot components API (read + concurrency-guarded put).

    Mirrors the ADK's ``MinimalBotEvaluationClient`` transport: a POST with an empty
    body reads every component and the current ``changeToken``; a PUT applies a
    change set under that token. Read-retries are disabled so a mutating PUT is
    never silently replayed; the ``changeToken`` is the optimistic-concurrency
    guard on top.
    """

    def __init__(
        self,
        target: MinimalBotTarget,
        token_provider: TokenProvider,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._target = target
        self._tokens = token_provider
        self._client = client or httpx.Client(timeout=_DELIVER_TIMEOUT_SECONDS)

    def _headers(self) -> dict[str, str]:
        return _auth_headers(self._tokens, self._target.scope)

    def read_components(self) -> dict[str, Any]:
        """Read all components and the current ``changeToken`` (a non-mutating POST)."""
        response = self._client.post(
            self._target.components_url, json={}, headers=self._headers()
        )
        if response.status_code != 200:
            raise DeliveryError(
                f"component read failed (HTTP {response.status_code}): "
                f"{_error_detail(response)}"
            )
        body = response.json()
        if not isinstance(body, dict):
            raise DeliveryError("component read returned an unexpected payload.")
        return body

    def put_changes(
        self,
        change_token: str,
        bot_component_changes: list[dict[str, Any]],
        bot: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        """Apply ``bot_component_changes`` (and an optional ``bot`` entity) under the token."""
        payload: dict[str, Any] = {
            "changeToken": change_token,
            "botComponentChanges": bot_component_changes,
            "connectionReferenceChanges": [],
            "connectorDefinitionChanges": [],
        }
        if bot is not None:
            payload["bot"] = bot
        return self._client.put(
            self._target.components_url, json=payload, headers=self._headers()
        )


# --- Bot-id targeting ------------------------------------------------------
#
# The botId is a per-install GUID. For a Cosmos-backed Declarative Agent (the
# ESS DA GA) it is NOT discoverable from any listing: the agent has no Dataverse
# ``bot`` row and does not appear in ``GET /copilotstudio/minimalBots/api`` (that
# surface lists only natively-authored agents, and comes back empty here), and
# there is no ``/copilotstudio/environments/{env}/bots`` collection route
# (confirmed 404 against the live prod service). The one place the botId is always
# available is the Copilot Studio agent URL the maker is already looking at:
#
#     https://copilotstudio.microsoft.com/environments/{env}/copilots/{botId}/details
#
# so the tool parses the botId (and the environment id) straight out of that URL,
# or takes an explicit ``--target-bot-id``.

_AGENT_URL_RE = re.compile(
    r"/environments/(?P<env>[0-9a-fA-F-]{36})"
    r"/(?:copilots|bots)/(?P<bot>[0-9a-fA-F-]{36})",
)


def parse_agent_url(url: str) -> tuple[str, str]:
    """Return ``(environment_id, bot_id)`` parsed from a Copilot Studio agent URL.

    Accepts the maker-facing link, e.g.
    ``https://copilotstudio.microsoft.com/environments/<env>/copilots/<botId>/details``
    (``/bots/<botId>`` is also accepted). Raises :class:`DeliveryError` when the
    URL does not carry both GUIDs.
    """
    match = _AGENT_URL_RE.search(url.strip())
    if match is None:
        raise DeliveryError(
            "could not find an environment id and botId in the agent URL "
            f"{url!r}; expected a Copilot Studio link of the form "
            "https://copilotstudio.microsoft.com/environments/<env>/copilots/<botId>/details"
        )
    env = match.group("env")
    bot = match.group("bot")
    if not _GUID_RE.match(env):
        raise DeliveryError(f"the environment id in the agent URL is not a GUID: {env!r}")
    if not _GUID_RE.match(bot):
        raise DeliveryError(f"the botId in the agent URL is not a GUID: {bot!r}")
    return env, bot


def existing_component_ids(read_body: Mapping[str, Any]) -> dict[str, str]:
    """Map ``schemaName -> id`` from a :meth:`read_components` payload."""
    ids: dict[str, str] = {}
    for change in read_body.get("botComponentChanges", []):
        component = change.get("component") if isinstance(change, Mapping) else None
        if not isinstance(component, Mapping):
            continue
        schema = str(component.get("schemaName") or "").strip()
        component_id = str(component.get("id") or "").strip()
        if schema and component_id:
            ids[schema] = component_id
    return ids


@dataclass(frozen=True)
class OnTargetComponent:
    """A component already on the target: its id, current version and live body.

    ``body`` is the component exactly as the components API returned it (expanded
    runtime form), which :func:`overlay_edits` patches the customer's edits onto.
    """

    id: str
    version: int
    body: Mapping[str, Any] = field(default_factory=dict)


def existing_components(read_body: Mapping[str, Any]) -> dict[str, OnTargetComponent]:
    """Map ``schemaName -> (id, version, body)`` from a :meth:`read_components` payload.

    The version is required to address an existing component for an upsert: the
    service checks it for optimistic concurrency and then increments it. A missing
    or non-integer version defaults to 1 (the service's initial version). The full
    component body is retained so the customer's edits can be overlaid onto it.
    """
    out: dict[str, OnTargetComponent] = {}
    for change in read_body.get("botComponentChanges", []):
        component = change.get("component") if isinstance(change, Mapping) else None
        if not isinstance(component, Mapping):
            continue
        schema = str(component.get("schemaName") or "").strip()
        component_id = str(component.get("id") or "").strip()
        if not (schema and component_id):
            continue
        raw_version = component.get("version")
        version = raw_version if isinstance(raw_version, int) else 1
        out[schema] = OnTargetComponent(
            id=component_id, version=version, body=dict(component)
        )
    return out


def deliver_minimalbot(
    target: MinimalBotTarget,
    agent: Mapping[str, Any],
    results: Iterable[Any],
    token_provider: TokenProvider,
    *,
    dry_run: bool = True,
    client: httpx.Client | None = None,
    config_values: Mapping[str, Any] | None = None,
) -> MinimalBotDeliveryResult:
    """Deliver the migration delta to ``target``. Returns a result; never raises on HTTP.

    The target is read first (to classify each change as insert vs update and to
    obtain the ``changeToken``). In ``dry_run`` mode nothing is written — the built
    change set is returned for the operator to inspect. Otherwise the change set is
    PUT under the token and the target is re-read to verify every intended
    component is present.
    """
    endpoint = target.components_url
    results = list(results)

    try:
        api = MinimalBotComponentsClient(target, token_provider, client=client)
        read_body = api.read_components()
    except Exception as error:  # noqa: BLE001 — surfaced to the operator as a result
        # Reading the target failed (token, transport or a non-200). Without the
        # live components there is nothing to overlay onto, so every deliverable is
        # reported as routed-to-package; a live run cannot proceed at all.
        _changes, _planned, deferred, _notes = plan_changes(
            agent, results, {}, config_values
        )
        detail = (
            "could not read the target; no overlay could be built "
            f"(every customized topic would route to the package import): {error}"
            if dry_run
            else f"could not read the target; nothing was written: {error}"
        )
        return MinimalBotDeliveryResult(
            ok=False,
            dry_run=dry_run,
            endpoint=endpoint,
            bot_id=target.bot_id,
            ring=target.ring,
            deferred=deferred,
            detail=detail,
        )

    existing = existing_components(read_body)
    changes, planned, deferred, notes = plan_changes(
        agent, results, existing, config_values
    )
    updated = len(planned)
    bot_update, renamed_to = plan_bot_entity_update(agent, read_body, config_values)

    if not changes and bot_update is None:
        detail = "nothing to deliver live: no customer edits to shipped topics."
        if deferred:
            detail += (
                f" {len(deferred)} new topic(s) route to the ALM package import."
            )
        return MinimalBotDeliveryResult(
            ok=True,
            dry_run=dry_run,
            endpoint=endpoint,
            bot_id=target.bot_id,
            ring=target.ring,
            deferred=deferred,
            notes=notes,
            detail=detail,
        )

    deferred_note = (
        f" {len(deferred)} new topic(s) route to the package import."
        if deferred
        else ""
    )
    rename_note = f" Renames the agent to \"{renamed_to}\"." if renamed_to else ""

    if dry_run:
        return MinimalBotDeliveryResult(
            ok=True,
            dry_run=True,
            endpoint=endpoint,
            bot_id=target.bot_id,
            ring=target.ring,
            planned=planned,
            deferred=deferred,
            notes=notes,
            updated=updated,
            renamed_to=renamed_to,
            detail=(
                f"dry-run: {updated} shipped-topic edit(s) prepared as overlays; "
                f"nothing written.{rename_note}{deferred_note} "
                "Re-run with --deliver-apply to write."
            ),
        )

    change_token = str(read_body.get("changeToken") or "")
    if not change_token:
        return MinimalBotDeliveryResult(
            ok=False,
            dry_run=False,
            endpoint=endpoint,
            bot_id=target.bot_id,
            ring=target.ring,
            planned=planned,
            deferred=deferred,
            notes=notes,
            updated=updated,
            renamed_to=renamed_to,
            detail="the target did not return a changeToken; refusing to write.",
        )

    try:
        response = api.put_changes(change_token, changes, bot_update)
    except httpx.HTTPError as error:
        return MinimalBotDeliveryResult(
            ok=False,
            dry_run=False,
            endpoint=endpoint,
            bot_id=target.bot_id,
            ring=target.ring,
            planned=planned,
            deferred=deferred,
            notes=notes,
            updated=updated,
            renamed_to=renamed_to,
            detail=f"the write request failed: {error}",
        )

    if response.status_code != 200:
        return MinimalBotDeliveryResult(
            ok=False,
            dry_run=False,
            endpoint=endpoint,
            bot_id=target.bot_id,
            ring=target.ring,
            planned=planned,
            deferred=deferred,
            notes=notes,
            updated=updated,
            renamed_to=renamed_to,
            status=response.status_code,
            detail=_error_detail(response),
        )

    missing = _verify(api, {c["component"]["schemaName"] for c in changes})
    if missing:
        return MinimalBotDeliveryResult(
            ok=False,
            dry_run=False,
            endpoint=endpoint,
            bot_id=target.bot_id,
            ring=target.ring,
            planned=planned,
            deferred=deferred,
            notes=notes,
            updated=updated,
            renamed_to=renamed_to,
            status=response.status_code,
            detail=f"write accepted but verification missed: {sorted(missing)}",
        )

    return MinimalBotDeliveryResult(
        ok=True,
        dry_run=False,
        endpoint=endpoint,
        bot_id=target.bot_id,
        ring=target.ring,
        planned=planned,
        deferred=deferred,
        notes=notes,
        updated=updated,
        renamed_to=renamed_to,
        status=response.status_code,
        detail=(
            f"delivered {updated} shipped-topic edit(s) to the "
            f"{target.ring} ring.{rename_note}{deferred_note}"
        ),
    )


def _verify(api: MinimalBotComponentsClient, expected: set[str]) -> set[str]:
    """Return the expected schema names absent from a fresh read (best-effort)."""
    try:
        after = existing_component_ids(api.read_components())
    except DeliveryError:
        return set()
    return {schema for schema in expected if schema not in after}


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:300] if text else f"HTTP {response.status_code} with no body."
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])[:300]
        if isinstance(body.get("message"), str):
            return str(body["message"])[:300]
    return str(body)[:300]


__all__ = [
    "COMPONENTS_API_VERSION",
    "DEFAULT_RING",
    "DeliveryError",
    "INSERT_KIND",
    "MinimalBotComponentsClient",
    "MinimalBotDeliveryResult",
    "MinimalBotTarget",
    "OnTargetComponent",
    "PlannedChange",
    "UPDATE_KIND",
    "audience_for_ring",
    "deliver_minimalbot",
    "environment_host",
    "existing_component_ids",
    "existing_components",
    "overlay_edits",
    "parse_agent_url",
    "plan_bot_entity_update",
    "plan_changes",
    "ring_for_endpoint",
    "scope_for_ring",
]
