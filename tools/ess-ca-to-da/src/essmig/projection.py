"""Project a CA ``botcomponent`` into the shape of a DA ``agent.yml`` component.

A CA component's ``data`` is a standalone YAML document whose ``kind`` names the
component type::

    kind: AdaptiveDialog
    beginDialog:
      kind: OnRedirect
      ...

The DA nests that same tree — minus the ``kind`` line — under a payload key of a
wrapper object that carries the identity and ALM metadata::

    - kind: DialogComponent
      schemaName: gptagent_copilotforemployeeselfservicehr.topic.Foo
      displayName: ...
      state: Active
      dialog:
        beginDialog:
          kind: OnRedirect
          ...

So projection is: parse the CA ``data``, strip its top-level ``kind``, rewrite every
agent-qualified schema reference from the ``msdyn_`` prefix to the ``gptagent_``
one, and hang the result off the right payload key.

The measured reality: after projection, only a minority of DA components are
identical to their CA ancestor — ESS rewrote much of the content when it built the
DA. Projection therefore produces a *comparable* value for the 3-way merge, not a
drop-in replacement. See :mod:`essmig.merge`.
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from essmig.discovery import CaComponent
from essmig.ess import CA_AGENT_SCHEMANAMES, DA_SCHEMANAME_BY_VERTICAL


@dataclass(frozen=True)
class DaShape:
    """How one CA component type appears in ``agent.yml``."""

    da_kind: str
    payload_key: str
    ca_kind: str


DA_SHAPE_BY_COMPONENT_TYPE: dict[int, DaShape] = {
    9: DaShape("DialogComponent", "dialog", "AdaptiveDialog"),
    12: DaShape("GlobalVariableComponent", "variable", "Variable"),
    15: DaShape("GptComponent", "metadata", "GptComponentMetadata"),
    16: DaShape("KnowledgeSourceComponent", "configuration", "KnowledgeSourceConfiguration"),
}

# Component types the Declarative Agent supports, but *not* as ``agent.yml``
# components — they are settings on the agent itself, so a package cannot carry
# them. These are re-created by hand in the agent's settings after import. The
# tool reproduces the customer's configuration in the report so there is nothing
# to go back to the Custom Engine Agent for.
#
# This is emphatically **not** the same as "cannot be migrated". Do not add a type
# here on the grounds that the ESS template happens not to ship one — knowledge
# sources (type 16) were once wrongly listed here, yet the DA carries them as
# ``KnowledgeSourceComponent`` entries (see DA_SHAPE_BY_COMPONENT_TYPE), confirmed
# against a real published ESS DA export.
CONFIGURED_ON_AGENT: dict[int, str] = {
    14: (
        "File attachments are not carried in the package. Re-upload this file in "
        "the agent's knowledge/attachment settings after import — the package "
        "cannot carry the file's bytes. Its configuration is reproduced below."
    ),
    18: (
        "Copilot settings are agent-level configuration, not a package component. "
        "Re-apply these settings in the agent's configuration after import — your "
        "values are reproduced below."
    ),
    19: (
        "Evaluations (test cases) are not carried in the package. Re-create this "
        "test in the agent's evaluation settings after import — its definition is "
        "reproduced below."
    ),
    20: (
        "Custom metric definitions are not carried in the package. Re-create this "
        "metric in the agent's analytics settings if you still need it — its "
        "definition is reproduced below."
    ),
}

_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"


class ProjectionError(RuntimeError):
    """A CA component could not be projected into a DA component."""


class ManualConfigurationRequired(ProjectionError):
    """The component migrates, but by hand — it is agent configuration, not content.

    Distinct from :class:`ProjectionError` because the difference matters to the
    customer: this is a task, not a loss.
    """


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    return yaml


def prefix_map(vertical: str) -> list[tuple[str, str]]:
    """CA → DA schema-prefix rewrites, longest source first.

    Every first-class agent's CA prefix is repointed at its *own* DA prefix, not at
    the migrating target's. A component migrating into HR may embed a cross-agent
    reference to a Core (hub) topic; that reference must land on the Core DA agent,
    not be rewritten to HR. ``vertical`` is retained for the migrating component's
    own identity (see :func:`project`); the reference rewrites themselves are
    global. Longest-first ordering matters so a longer prefix is not shadowed by a
    shorter one that is its proper prefix.
    """
    del vertical
    pairs = {
        CA_AGENT_SCHEMANAMES[bucket]: da
        for bucket, da in DA_SCHEMANAME_BY_VERTICAL.items()
        if bucket in CA_AGENT_SCHEMANAMES
    }
    sources = sorted(pairs, key=len, reverse=True)
    return [(f"{source}.", f"{pairs[source]}.") for source in sources]


def rewrite_prefixes(text: str, vertical: str) -> str:
    """Repoint every agent-qualified schema reference at the DA agent.

    Cross-topic references (``BeginDialog``, variable scopes, trigger targets)
    embed the full schema name, so they must be rewritten alongside the component's
    own identity or the migrated topic will point at an agent that no longer exists.
    """
    for source, target in prefix_map(vertical):
        text = text.replace(source, target)
    return text


def parse_ca_data(data: str, vertical: str) -> Any:
    """Parse a CA component's ``data`` YAML with its schema references repointed.

    Copilot Studio serialises component ``data`` with a lenient YAML writer that
    emits two shapes a strict reader rejects:

    * mapping keys and scalars beginning with the reserved indicators ``@`` or
      `` ` `` (most commonly ``@odata.type`` inside connector-action payloads), and
    * block-mapping entries with **no space after the colon**
      (``connectionReference:esshr_HRSystemsConnectionConnRef``).

    :func:`_normalize_copilot_yaml` repairs both so the data round-trips. A component
    whose ``data`` still cannot be read is raised as a :class:`ProjectionError`, never
    a bare YAML exception, so one malformed component is reported as a single failed
    row instead of aborting the whole migration.
    """
    prepared = _normalize_copilot_yaml(rewrite_prefixes(data, vertical))
    try:
        return _yaml().load(prepared)
    except YAMLError as error:
        first_line = str(error).splitlines()[0] if str(error) else error.__class__.__name__
        raise ProjectionError(f"could not parse component 'data' as YAML: {first_line}") from error


# A block-scalar header — ``foo: |`` / ``foo:|`` / ``foo: >-`` / a lone ``- |`` —
# introduces a literal/folded body whose lines are free text and must never be touched.
_BLOCK_HEADER = re.compile(r"(?::|^\s*-)\s*[|>][+-]?\d*\s*(?:#.*)?$")
# A block-mapping entry written with no space after the colon: ``key:value``. The key
# is a bare YAML identifier and the value is present and does not begin with ``/`` (so
# ``http://…`` style scalars are left alone).
_MISSING_KEY_SPACE = re.compile(
    r"^(?P<indent>\s*(?:-\s+)?)(?P<key>[A-Za-z_][\w.\-]*):(?P<value>(?![\s/])\S.*?)(?P<eol>\s*)$"
)
# A mapping key that begins with a reserved indicator, e.g. ``@odata.type:``.
_RESERVED_KEY = re.compile(r"^(?P<indent>\s*(?:-\s+)?)(?P<key>[@`][^:#\n]*?)(?P<sep>:(?:\s|$))")
# A scalar value that begins with a reserved indicator, e.g. ``type: @Type``.
_RESERVED_VALUE = re.compile(r"^(?P<pre>.*?:\s+)(?P<val>[@`][^\n]*?)\s*$")


def _double_quote(scalar: str) -> str:
    return '"' + scalar.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _repair_line(line: str) -> str:
    """Repair one non-block-scalar line: add a missing key space, then quote reserved scalars."""
    space = _MISSING_KEY_SPACE.match(line)
    if space:
        line = f"{space['indent']}{space['key']}: {space['value']}{space['eol']}"

    key = _RESERVED_KEY.match(line)
    if key:
        return f"{key['indent']}{_double_quote(key['key'])}{key['sep']}{line[key.end():]}"

    value = _RESERVED_VALUE.match(line)
    if value:
        return f"{value['pre']}{_double_quote(value['val'])}"

    return line


def _normalize_copilot_yaml(text: str) -> str:
    """Make Copilot Studio's lenient YAML acceptable to a strict reader.

    Repairs missing key spaces and quotes scalars that begin with a YAML reserved
    indicator (``@``/`` ` ``). Both repairs are value-preserving. Block-scalar bodies
    (a topic's ``instructions``, say) are passed through untouched so prose is never
    rewritten. Line endings are normalised to ``\\n`` first so CRLF data is handled.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    block_indent: int | None = None
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if block_indent is not None:
            if stripped == "" or indent > block_indent:
                out.append(line)  # inside a block-scalar body — leave verbatim
                continue
            block_indent = None  # dedented back out of the block

        if _BLOCK_HEADER.search(line):
            block_indent = indent
            out.append(line)
            continue

        out.append(_repair_line(line))
    return "\n".join(out)


def project(component: CaComponent, vertical: str) -> dict[str, Any]:
    """Return the DA-shaped payload fragment for a CA component.

    The result is ``{"kind": <DA kind>, "schemaName": ..., <payload_key>: <tree>}``
    — the parts that come from the customer. Identity/ALM metadata is filled in by
    :func:`as_new_component` or carried from the DA template by the merge.
    """
    shape = shape_for(component)
    if component.data is None:
        raise ProjectionError(f"{component.schemaname} has no 'data' to project.")

    tree = parse_ca_data(component.data, vertical)
    if not isinstance(tree, dict):
        raise ProjectionError(
            f"{component.schemaname} 'data' is not a YAML mapping; cannot project."
        )

    declared_kind = tree.get("kind")
    if declared_kind is not None and declared_kind != shape.ca_kind:
        raise ProjectionError(
            f"{component.schemaname} declares kind {declared_kind!r} but component type "
            f"{component.component_type} implies {shape.ca_kind!r}."
        )
    payload = {key: value for key, value in tree.items() if key != "kind"}

    return {
        "kind": shape.da_kind,
        "schemaName": rewrite_prefixes(component.schemaname, vertical),
        shape.payload_key: payload,
    }


def as_new_component(component: CaComponent, vertical: str) -> dict[str, Any]:
    """A complete, self-contained ``agent.yml`` entry for a net-new customer component.

    Used when the customer authored something the DA template has no counterpart
    for. It is marked unmanaged and customizable — it is the customer's content, so
    a future template upgrade must not claim ownership of it.

    Each component needs a unique ``id`` for the import to bind it into the agent —
    the ESS template gives every component a real GUID and leaves ``parentBotId``
    empty for the import to stamp. A zero ``id`` fails binding ("could not be bound
    into a valid Dev agent"), so mint a fresh one here.
    """
    projected = project(component, vertical)
    shape = shape_for(component)
    if shape.da_kind == "KnowledgeSourceComponent":
        return _as_new_knowledge_source(component, vertical, projected)
    entry: dict[str, Any] = {
        "kind": projected["kind"],
        "version": 1,
        "managedProperties": {"isManaged": False, "isCustomizable": True},
        "id": str(uuid.uuid4()),
        "parentBotId": _EMPTY_GUID,
        "shareContext": {},
        "state": _state_of(component),
        "status": _state_of(component),
        "schemaName": projected["schemaName"],
    }
    display_name = component.name or _display_name_from(projected[shape.payload_key])
    if display_name and shape.da_kind != "GlobalVariableComponent":
        entry["displayName"] = display_name
    entry[shape.payload_key] = projected[shape.payload_key]
    return entry


def _as_new_knowledge_source(
    component: CaComponent, vertical: str, projected: dict[str, Any]
) -> dict[str, Any]:
    """A net-new ``KnowledgeSourceComponent`` entry shaped like a real DA export.

    A knowledge source is not a dialog: the import validator rejects the generic
    net-new shape (``state``/``status``/``shareContext`` and a ``topic.*`` schema
    name) that fits topics and variables. A valid knowledge source is namespaced
    under ``knowledge.<Name>`` and omits those lifecycle fields, carrying instead a
    ``description`` and a ``source`` that declares ``cascadeShare``. Match that
    shape so the migrated source binds into the agent.
    """
    configuration = projected["configuration"]
    source = configuration.get("source") if isinstance(configuration, dict) else None
    if isinstance(source, dict) and source.get("kind") == "SharePointSearchSource":
        source.setdefault("cascadeShare", False)

    name = component.name or _display_name_from(configuration) or "KnowledgeSource"
    prefix = DA_SCHEMANAME_BY_VERTICAL[vertical]
    schema_name = f"{prefix}.knowledge.{_schema_safe(name)}"

    entry: dict[str, Any] = {
        "kind": "KnowledgeSourceComponent",
        "version": 1,
        "managedProperties": {"isManaged": False, "isCustomizable": True},
        "id": str(uuid.uuid4()),
        "parentBotId": _EMPTY_GUID,
        "displayName": name,
        "schemaName": schema_name,
    }
    site = source.get("site") if isinstance(source, dict) else None
    if isinstance(site, str) and site:
        entry["description"] = (
            f"This knowledge source provides information found in {site} SharePoint"
        )
    entry["configuration"] = configuration
    return entry


def _schema_safe(name: str) -> str:
    """A schema-name suffix from a display name: alphanumerics only.

    The DA export names a knowledge source ``knowledge.<DisplayNameNoSpaces>`` —
    e.g. ``Communication site`` becomes ``Communicationsite``.
    """
    return "".join(ch for ch in name if ch.isalnum())


def shape_for(component: CaComponent) -> DaShape:
    component_type = component.component_type
    if component_type in CONFIGURED_ON_AGENT:
        raise ManualConfigurationRequired(CONFIGURED_ON_AGENT[component_type])
    shape = DA_SHAPE_BY_COMPONENT_TYPE.get(component_type) if component_type is not None else None
    if shape is None:
        raise ProjectionError(
            f"No Declarative Agent shape is defined for component type {component_type} "
            f"({component.component_type_label}). This is a gap in the tool, not "
            f"necessarily in the Declarative Agent — check by hand before assuming "
            f"the configuration is lost."
        )
    return shape


def describe(component: CaComponent, vertical: str) -> str:
    """The customer's configuration, as YAML, for a component that must be re-created.

    Deliberately forgiving: the point is to put everything the customer configured
    in front of them, not to understand it. An unparseable payload is reproduced
    verbatim rather than dropped.
    """
    if not component.data:
        return ""
    try:
        tree = parse_ca_data(component.data, vertical)
    except Exception:
        return rewrite_prefixes(component.data, vertical)
    if isinstance(tree, dict):
        tree = {key: value for key, value in tree.items() if key != "kind"}
    return dump(tree)


def dump(node: Any) -> str:
    """Serialize a fragment back to YAML — used for diffing and reporting."""
    stream = io.StringIO()
    _yaml().dump(node, stream)
    return stream.getvalue()


def load_fragment(text: str) -> Any:
    """Parse a YAML fragment back into a value — the inverse of :func:`dump`.

    Used by the interactive hand-merge: the text a human edits and saves is loaded
    with the same YAML machinery that produced it, so quoting and structure round
    trip. No schema-prefix rewriting — the fragment is already DA-shaped.
    """
    return _yaml().load(text)


def _state_of(component: CaComponent) -> str:
    """Map the CA ``statecode`` (0 = active, 1 = inactive) onto the DA state string."""
    statecode = component.statecode
    if isinstance(statecode, dict):
        statecode = statecode.get("Value")
    return "Inactive" if statecode == 1 else "Active"


def _display_name_from(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("displayName", "name"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return ""
