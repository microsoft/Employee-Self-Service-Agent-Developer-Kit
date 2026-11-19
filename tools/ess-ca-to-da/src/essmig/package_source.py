"""Discover customizations from an *exported CA solution package* instead of Dataverse.

Some customers cannot run the tool's Dataverse queries (no CLI access, restricted
tenant). They can still **export their customization solution** from
make.powerapps.com (Solutions -> Export) and hand over the ``.zip``. This module
reads that export into the very same :class:`~essmig.discovery.DiscoveryResult` the
Dataverse path produces, so ``inspect`` and ``migrate`` behave identically no
matter where the customizations came from.

An exported solution unzips to the same shape the tool already vendors for its
baseline (:func:`essmig.reference._read_ca_baseline`):

* ``solution.xml`` — the manifest. Its ``<UniqueName>`` names the customer's
  solution, and its ``<MissingDependencies>`` list every out-of-box component the
  solution *edits in place*, each tagged with the managed solution (and version)
  it descends from — exactly the provenance the Dataverse path reads from solution
  layers.
* ``botcomponents/<name>/botcomponent.xml`` + ``data`` — one folder per component
  (``schemaname``, ``componenttype``, ``name``, ``statecode`` in the XML; the
  component definition in ``data``).

Classification is reused wholesale. Rather than re-implement the layer logic, this
module reconstructs the same synthetic ``msdyn_componentlayers`` rows the Dataverse
path builds and calls :func:`essmig.discovery._classify`:

* an **edit** of an out-of-box component (its schema name appears as a self
  dependency in ``<MissingDependencies>``, or its suffix is in the vendored
  baseline) becomes two layers — a bare managed base layer naming the owning OOB
  solution (so extension-pack detection still fires) and the customer's overlay
  carrying the edited ``data``;
* a **net-new** component becomes a single overlay layer in the customer's own
  (non-OOB) solution.

``_classify`` then applies the identical "customized and owned by this agent"
filter, so the kept set, the skipped reasons, ``is_net_new`` and ``.solutions``
all match the Dataverse path.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from xml.etree import ElementTree as ET

from essmig.discovery import AgentMetadata, DiscoveryResult, _classify
from essmig.ess import (
    CA_AGENT_SCHEMANAMES,
    CA_SOLUTION_BY_VERTICAL,
    TARGETS,
    schema_prefix,
    schema_suffix,
)
from essmig.flows import CarriedFlow, FlowExport, canonical_id
from essmig.reference import ReferenceSet, load

_AGENT_GPT_SUFFIX = "gpt.default"
_AGENT_NAME_KEYS = ("name", "displayname")
_AGENT_DESCRIPTION_KEYS = ("description",)
_SOLUTION_NAME_FIELD = "msdyn_solutionname"
_COMPONENT_JSON_FIELD = "msdyn_componentjson"


def package_targets(path: str | Path) -> list[str]:
    """The ESS agents a package carries components for, in canonical order.

    Mirrors :func:`essmig.discovery.installed_targets` for the package source: it
    lets the CLI migrate every agent a package contains without the caller naming
    each one. A component's owning agent is read from its schema-name prefix, which
    every real topic, variable, GPT and knowledge source carries (test-harness
    components with a publisher GUID prefix are ignored here, exactly as the
    Dataverse owned-component sweep ignores them).
    """
    by_prefix = {prefix: vertical for vertical, prefix in CA_AGENT_SCHEMANAMES.items()}
    present: set[str] = set()
    with _package_root(path) as root:
        for schemaname, _ in _iter_botcomponents(root):
            vertical = by_prefix.get(schema_prefix(schemaname).lower())
            if vertical is not None:
                present.add(vertical)
    return [vertical for vertical in TARGETS if vertical in present]


def discover_from_package(
    path: str | Path,
    vertical: str,
    reference: ReferenceSet | None = None,
    *,
    preferred_solution: str | None = None,
) -> DiscoveryResult:
    """Read an exported CA solution package into a :class:`DiscoveryResult`.

    ``reference`` supplies the vendored baseline used to recognise in-place edits
    and to read the agent's shipped display name; it is loaded on demand when not
    given. ``preferred_solution`` is accepted for signature parity with
    :func:`essmig.discovery.discover` but ignored — an export already *is* the set
    of components the customer chose to ship.
    """
    del preferred_solution  # the export is the scope; nothing to narrow.
    if vertical not in CA_AGENT_SCHEMANAMES:
        raise ValueError(
            f"Unknown vertical {vertical!r}; expected one of {list(CA_AGENT_SCHEMANAMES)}."
        )
    if reference is None:
        reference = load(vertical)

    with _package_root(path) as root:
        solution_name = _solution_unique_name(root)
        edits = _in_place_edits(root)
        prefix = CA_AGENT_SCHEMANAMES[vertical]

        layers_by_component: dict[str, list[dict[str, Any]]] = {}
        for schemaname, folder in _iter_botcomponents(root):
            if schema_prefix(schemaname).lower() != prefix:
                # Owned by another agent (or a publisher-prefixed test component);
                # _classify would drop it anyway. Skip early so it never appears.
                continue
            suffix = schema_suffix(schemaname)
            oob_solution = edits.get(schemaname)
            if oob_solution is None and suffix in reference.baseline:
                oob_solution = reference.baseline[suffix].solution or CA_SOLUTION_BY_VERTICAL[
                    vertical
                ]
            layers_by_component[schemaname] = _synth_layers(folder, schemaname, oob_solution)

        components, skipped = _classify(layers_by_component, vertical)

    return DiscoveryResult(
        vertical=vertical,
        solution_unique_name=solution_name,
        solution_id="",
        components=components,
        skipped=skipped,
        agent=_agent_metadata(layers_by_component, prefix, reference),
    )


def read_flow_export(path: str | Path) -> FlowExport | None:
    """Read the cloud flows an exported CA solution carries, ready to re-emit.

    Returns ``None`` when the export declares no flows. Otherwise returns every
    flow in the package (its id, name and — read from the flow definition — its
    input/output parameter schemas and connectors) together with the raw
    ``solution.xml``, ``customizations.xml`` and ``Workflows/`` parts, so
    :func:`essmig.flows.build_solution_zip` can re-emit them near-verbatim.

    Flows travel across the whole package, not per vertical: a cloud flow is not
    owned by one ESS agent, and the same flow may be invoked by topics in more than
    one of them. The caller decides, per agent, which of these are actually
    referenced and need carrying.
    """
    with _package_root(path) as root:
        customizations = root / "customizations.xml"
        solution = root / "solution.xml"
        if not customizations.is_file() or not solution.is_file():
            return None
        customizations_xml = customizations.read_text(encoding="utf-8-sig")
        entries = _workflow_entries(customizations_xml)
        if not entries:
            return None

        workflow_files: dict[str, bytes] = {}
        flows: list[CarriedFlow] = []
        for entry in entries:
            part = entry["json_name"]
            definition_path = root / "Workflows" / part
            data = definition_path.read_bytes() if definition_path.is_file() else b""
            if data:
                workflow_files[part] = data
            inputs, outputs, connectors = _flow_definition(data)
            flows.append(
                CarriedFlow(
                    workflow_id=canonical_id(entry["workflow_id"]),
                    name=entry["name"],
                    description=entry["description"],
                    json_name=part,
                    input_schema=inputs,
                    output_schema=outputs,
                    connectors=connectors,
                )
            )
        return FlowExport(
            flows=tuple(flows),
            solution_xml=solution.read_text(encoding="utf-8-sig"),
            customizations_xml=customizations_xml,
            workflow_files=workflow_files,
        )


def read_env_var_values(path: str | Path) -> dict[str, str]:
    """The environment-variable values an exported CA solution carries, by suffix.

    A ServiceNow (or other Graph-connector) knowledge source resolves its
    connection through an environment variable, and that variable's *value* — the
    Graph connector's connection id — is what binds the source. An export carries
    each variable under ``environmentvariabledefinitions/<schema>/`` with the
    variable's ``environmentvariabledefinition.xml`` (its ``defaultvalue``) and,
    when a value was set, an ``environmentvariablevalues.json``.

    Returns a map from the agent-independent schema *suffix* (``envVar.<id>``) to
    the set value, falling back to the default. Keyed by suffix so a CA
    ``msdyn_*`` variable matches the ``gptagent_*`` reference the migrated agent
    carries. Empty when the export defines no variables.
    """
    with _package_root(path) as root:
        definitions = root / "environmentvariabledefinitions"
        if not definitions.is_dir():
            return {}
        values: dict[str, str] = {}
        for folder in sorted(definitions.iterdir()):
            if not folder.is_dir():
                continue
            value = _env_var_value(folder)
            if value is not None:
                values[schema_suffix(folder.name)] = value
        return values


def _env_var_value(folder: Path) -> str | None:
    """The set value of one environment variable, falling back to its default."""
    values_file = folder / "environmentvariablevalues.json"
    if values_file.is_file():
        try:
            document = json.loads(values_file.read_text(encoding="utf-8-sig"))
        except ValueError:
            document = None
        wrapper = document.get("environmentvariablevalues") if isinstance(document, dict) else None
        entry = wrapper.get("environmentvariablevalue") if isinstance(wrapper, dict) else None
        value = entry.get("value") if isinstance(entry, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    definition = folder / "environmentvariabledefinition.xml"
    if definition.is_file():
        try:
            default = ET.parse(definition).getroot().findtext("defaultvalue")
        except ET.ParseError:
            default = None
        if isinstance(default, str) and default.strip():
            return default.strip()
    return None


def _workflow_entries(customizations_xml: str) -> list[dict[str, str]]:
    """``id``/``name``/``description``/``json_name`` for each ``<Workflow>`` in the export."""
    try:
        root = ET.fromstring(customizations_xml)
    except ET.ParseError:
        return []
    entries: list[dict[str, str]] = []
    for workflow in root.iter("Workflow"):
        workflow_id = workflow.get("WorkflowId")
        json_file = (workflow.findtext("JsonFileName") or "").strip()
        if not workflow_id or not json_file:
            continue
        entries.append(
            {
                "workflow_id": workflow_id,
                "name": workflow.get("Name") or "",
                "description": workflow.get("Description") or "",
                # The manifest path is POSIX and absolute (``/Workflows/<file>``);
                # the archive stores the part under ``Workflows/`` by its base name.
                "json_name": json_file.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1],
            }
        )
    return entries


def _flow_definition(data: bytes) -> tuple[dict[str, Any], dict[str, Any], tuple[str, ...]]:
    """A flow's ``(input_schema, output_schema, connectors)`` from its definition JSON."""
    if not data:
        return {}, {}, ()
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return {}, {}, ()
    properties = document.get("properties") if isinstance(document, dict) else None
    if not isinstance(properties, dict):
        return {}, {}, ()

    definition = properties.get("definition")
    definition = definition if isinstance(definition, dict) else {}
    input_schema = _request_trigger_schema(definition.get("triggers"))
    output_schema = _response_action_schema(definition.get("actions"))
    connectors = _connectors(properties.get("connectionReferences"))
    return input_schema, output_schema, connectors


def _request_trigger_schema(triggers: Any) -> dict[str, Any]:
    if isinstance(triggers, dict):
        for trigger in triggers.values():
            if isinstance(trigger, dict) and trigger.get("type") == "Request":
                schema = trigger.get("inputs", {}).get("schema")
                if isinstance(schema, dict):
                    return schema
    return {}


def _response_action_schema(actions: Any) -> dict[str, Any]:
    if isinstance(actions, dict):
        for action in actions.values():
            if isinstance(action, dict) and action.get("type") == "Response":
                schema = action.get("inputs", {}).get("schema")
                if isinstance(schema, dict):
                    return schema
    return {}


def _connectors(connection_references: Any) -> tuple[str, ...]:
    if not isinstance(connection_references, dict):
        return ()
    names: dict[str, None] = {}
    for reference in connection_references.values():
        api = reference.get("api") if isinstance(reference, dict) else None
        name = api.get("name") if isinstance(api, dict) else None
        if isinstance(name, str) and name:
            names.setdefault(name, None)
    return tuple(names)


# --- package layout ---------------------------------------------------------


@contextmanager
def _package_root(path: str | Path) -> Iterator[Path]:
    """Yield a directory holding the unpacked solution (extracting a ``.zip`` first)."""
    source = Path(path)
    if source.is_dir():
        yield _solution_dir(source)
        return
    if source.is_file() and zipfile.is_zipfile(source):
        with TemporaryDirectory(prefix="essmig-pkg-") as tmp:
            with zipfile.ZipFile(source) as archive:
                archive.extractall(tmp)
            yield _solution_dir(Path(tmp))
        return
    raise FileNotFoundError(
        f"{source} is not an exported solution: expected a .zip or a folder "
        "containing solution.xml and a botcomponents/ directory."
    )


def _solution_dir(root: Path) -> Path:
    """The directory that actually holds ``solution.xml`` (some zips nest one level)."""
    if (root / "solution.xml").is_file():
        return root
    for candidate in sorted(root.rglob("solution.xml")):
        return candidate.parent
    raise FileNotFoundError(
        f"No solution.xml found under {root}; this does not look like an exported "
        "CA solution package."
    )


def _iter_botcomponents(root: Path) -> Iterator[tuple[str, Path]]:
    """``(schemaname, folder)`` for every botcomponent in the package."""
    components_dir = root / "botcomponents"
    if not components_dir.is_dir():
        return
    for folder in sorted(components_dir.iterdir()):
        manifest = folder / "botcomponent.xml"
        if not manifest.is_file():
            continue
        schemaname = ET.parse(manifest).getroot().get("schemaname")
        if isinstance(schemaname, str) and schemaname:
            yield schemaname, folder


def _synth_layers(folder: Path, schemaname: str, oob_solution: str | None) -> list[dict[str, Any]]:
    """Reconstruct the solution-layer rows the Dataverse path would have read.

    The customer overlay carries the component's attributes (from ``botcomponent.xml``
    and ``data``). When the component edits an out-of-box one, a bare managed base
    layer is prepended so it classifies as an edit (two layers) and its owning pack
    is visible to extension-pack detection.
    """
    manifest = ET.parse(folder / "botcomponent.xml").getroot()
    data_file = folder / "data"
    data = data_file.read_text(encoding="utf-8-sig") if data_file.is_file() else None

    overlay = _overlay_layer(
        solution=_CUSTOMER_LAYER,
        schemaname=schemaname,
        name=manifest.findtext("name") or "",
        componenttype=_int_or_none(manifest.findtext("componenttype")),
        data=data,
        statecode=_int_or_none(manifest.findtext("statecode")),
        statuscode=_int_or_none(manifest.findtext("statuscode")),
    )
    if oob_solution:
        # Base layer first (managed OOB), customer overlay second — matching the
        # base-first order _component_attributes expects so the overlay wins.
        return [{_SOLUTION_NAME_FIELD: oob_solution}, overlay]
    return [overlay]


def _overlay_layer(
    *,
    solution: str,
    schemaname: str,
    name: str,
    componenttype: int | None,
    data: str | None,
    statecode: int | None,
    statuscode: int | None,
) -> dict[str, Any]:
    """A synthetic ``msdyn_componentlayers`` row with its attributes JSON-wrapped."""
    attributes: list[dict[str, Any]] = [
        {"Key": "schemaname", "Value": schemaname},
        {"Key": "name", "Value": name},
        {"Key": "componenttype", "Value": {"Value": componenttype}},
    ]
    if data is not None:
        attributes.append({"Key": "data", "Value": data})
    if statecode is not None:
        attributes.append({"Key": "statecode", "Value": statecode})
    if statuscode is not None:
        attributes.append({"Key": "statuscode", "Value": statuscode})
    return {
        _SOLUTION_NAME_FIELD: solution,
        _COMPONENT_JSON_FIELD: json.dumps({"Attributes": attributes}),
    }


# The unmanaged-overlay solution name. It only needs to be a value that is *not*
# one of the OOB ESS solutions, so a net-new component reads as customer-authored
# and an edit's overlay sorts above the managed base.
_CUSTOMER_LAYER = "Active"


def _solution_unique_name(root: Path) -> str:
    manifest = root / "solution.xml"
    if not manifest.is_file():
        return ""
    name = ET.parse(manifest).getroot().findtext("./SolutionManifest/UniqueName")
    return name.strip() if name else ""


def _in_place_edits(root: Path) -> dict[str, str]:
    """Map each edited out-of-box component's schema name to its owning OOB solution.

    Read from ``solution.xml``'s ``<MissingDependencies>``: a dependency whose
    *Required* and *Dependent* name the same component is an in-place edit — the
    customer's solution carries an overlay of a component that lives in the managed
    ``Required`` solution. The solution attribute carries a trailing version in
    parentheses (``msdyn_EssHRServiceNowHRSD (1.2.0.1)``) which is stripped.
    """
    manifest = root / "solution.xml"
    if not manifest.is_file():
        return {}
    edits: dict[str, str] = {}
    for dependency in ET.parse(manifest).getroot().iter("MissingDependency"):
        required = dependency.find("Required")
        dependent = dependency.find("Dependent")
        if required is None or dependent is None:
            continue
        schemaname = required.get("id.schemaname")
        if not schemaname or dependent.get("id.schemaname") != schemaname:
            continue
        solution = required.get("solution") or ""
        edits[schemaname] = solution.split(" (", 1)[0].strip() or solution.strip()
    return edits


def _agent_metadata(
    layers_by_component: dict[str, list[dict[str, Any]]],
    prefix: str,
    reference: ReferenceSet,
) -> AgentMetadata | None:
    """The agent's own display name / description, effective and shipped-baseline.

    Reads the effective name/description from the ``gpt.default`` component's overlay
    attributes (the ``name`` column and, for the Overview description, the
    ``description`` column). The shipped baseline name comes from the vendored
    ``gpt.default`` ``data`` (its ``displayName``); the baseline description is not
    carried in the vendored data, so it degrades to ``None`` — the merge then treats
    a description edit as a review rather than a silent overwrite.
    """
    schemaname = f"{prefix}.{_AGENT_GPT_SUFFIX}"
    layers = layers_by_component.get(schemaname)
    if not layers:
        return None
    attributes = _overlay_attributes(layers)

    metadata = AgentMetadata(
        name=_pick(attributes, _AGENT_NAME_KEYS),
        description=_pick(attributes, _AGENT_DESCRIPTION_KEYS),
        baseline_name=_baseline_display_name(reference),
        baseline_description=None,
    )
    if metadata.name is None and metadata.description is None:
        return None
    return metadata


def _overlay_attributes(layers: list[dict[str, Any]]) -> dict[str, Any]:
    """The attribute map from the customer overlay layer (the one carrying JSON)."""
    for layer in layers:
        raw = layer.get(_COMPONENT_JSON_FIELD)
        if not isinstance(raw, str) or not raw:
            continue
        payload = json.loads(raw)
        entries = payload.get("Attributes") if isinstance(payload, dict) else None
        if isinstance(entries, list):
            return {
                entry["Key"]: entry.get("Value")
                for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get("Key"), str)
            }
    return {}


def _baseline_display_name(reference: ReferenceSet) -> str | None:
    """The shipped ``gpt.default`` display name, from the vendored baseline ``data``."""
    baseline = reference.baseline.get(_AGENT_GPT_SUFFIX)
    if baseline is None or not baseline.data:
        return None
    for line in baseline.data.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("displayName:"):
            value = stripped.split(":", 1)[1].strip().strip("'\"")
            return value or None
    return None


def _pick(attributes: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    lowered = {str(key).lower(): value for key, value in attributes.items()}
    for key in keys:
        value = lowered.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _int_or_none(value: str | None) -> int | None:
    try:
        return int((value or "").strip())
    except ValueError:
        return None
