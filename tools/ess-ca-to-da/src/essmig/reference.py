"""Reference data: the two halves of the merge base that ESS owns.

A 3-way merge needs three inputs. Two of them come from ESS's own product sources
rather than from the customer, so they are *vendored* into this tool and used
offline:

* **base** — the CA component exactly as ESS shipped it, from
  ``sources/dev/solutions/<Solution>/Solution/botcomponents/<name>/data``.
* **theirs** — the DA component ESS ships today, from
  ``sources/dev/AgentTemplates/<Template>/Plugin/Agents/<schema>/agent.yml``.

(The third, *ours*, is the customer's Dataverse overlay — see ``discovery``.)

``vendor()`` extracts both from a local ESSVivaCopilot clone into
``reference/<vertical>/``; ``load()`` reads that vendored snapshot back. Vendoring
is a maintainer step run when ESS ships a new template version, not something a
customer does — which is why the tool needs no access to ESSVivaCopilot at
migration time.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from essmig.ess import (
    CA_AGENT_SCHEMANAMES,
    DA_SCHEMANAME_BY_VERTICAL,
    DA_TEMPLATE_FOLDER_BY_VERTICAL,
    OOB_CA_SOLUTIONS,
    TARGETS,
    schema_prefix,
    schema_suffix,
)

REFERENCE_ROOT = Path(__file__).resolve().parents[2] / "reference"

_BASELINE_FILE = "ca-baseline.json"
_PROVENANCE_FILE = "reference.json"
_AGENT_FILE = "agent.yml"
_CONFIG_FILE = "app.config.dev.json"
_PACKAGE_FILE = "package.json"
_OVERLAYS_FILE = "Overlays.json"

# Where a solution folder declares its Dataverse unique name.
_SOLUTION_MANIFESTS = ("Solution/Other/Solution.xml", "Solution/Solution.xml")


_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"


def keep_timestamps_verbatim(yaml: YAML) -> None:
    """Stop ruamel parsing ISO-8601 scalars into ``datetime``.

    The ESS template's ``auditInfo`` timestamps carry seven sub-second digits
    (``...T19:13:15.0000000Z``). Parsed to a ``datetime`` and re-emitted they lose
    the trailing zeros, so a plain round-trip silently rewrites *every* component's
    audit metadata. Removing the timestamp resolver keeps them as verbatim strings —
    loaded unchanged and dumped unquoted, exactly as the platform wrote them.
    """
    versioned = yaml.resolver.versioned_resolver
    for first_char in list(versioned):
        versioned[first_char] = [
            (tag, regexp)
            for tag, regexp in versioned[first_char]
            if tag != _TIMESTAMP_TAG
        ]


def _yaml() -> YAML:
    """A round-trip YAML instance: preserves key order, comments and literal blocks."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    keep_timestamps_verbatim(yaml)
    return yaml


@dataclass(frozen=True)
class BaselineComponent:
    """A CA component as ESS shipped it — the merge *base*."""

    suffix: str
    schemaname: str
    component_type: int | None
    solution: str
    data: str | None


@dataclass
class ReferenceSet:
    """Everything the tool knows about one vertical, offline."""

    vertical: str
    agent: Any
    """The DA ``agent.yml`` document, round-trip parsed."""
    config: dict[str, Any]
    package: dict[str, Any]
    overlays: dict[str, Any] | None
    baseline: dict[str, BaselineComponent]
    provenance: dict[str, Any]

    @property
    def da_schemaname(self) -> str:
        entity = self.agent.get("entity") if isinstance(self.agent, dict) else None
        name = entity.get("schemaName") if isinstance(entity, dict) else None
        return name if isinstance(name, str) and name else DA_SCHEMANAME_BY_VERTICAL[self.vertical]

    @property
    def da_components(self) -> dict[str, Any]:
        """DA components keyed by schema-name suffix — the merge *theirs* side."""
        components = self.agent.get("components") if isinstance(self.agent, dict) else None
        if not isinstance(components, list):
            return {}
        return {
            suffix: component
            for component in components
            if isinstance(component, dict)
            and (suffix := schema_suffix(str(component.get("schemaName") or "")))
        }


def load(vertical: str, root: Path = REFERENCE_ROOT) -> ReferenceSet:
    """Read the vendored reference data for one vertical."""
    directory = root / vertical
    if not directory.is_dir():
        raise FileNotFoundError(
            f"No vendored reference data for '{vertical}' at {directory}. "
            "Run `ess-ca-to-da vendor --ess-root <path-to-ESSVivaCopilot>` first."
        )
    yaml = _yaml()
    agent = yaml.load((directory / _AGENT_FILE).read_text(encoding="utf-8-sig"))
    overlays_path = directory / _OVERLAYS_FILE
    return ReferenceSet(
        vertical=vertical,
        agent=agent,
        config=_read_json(directory / _CONFIG_FILE),
        package=_read_json(directory / _PACKAGE_FILE),
        overlays=_read_json(overlays_path) if overlays_path.is_file() else None,
        baseline=_read_baseline(root / _BASELINE_FILE, vertical),
        provenance=_read_json(directory / _PROVENANCE_FILE),
    )


def vendor(ess_root: Path, root: Path = REFERENCE_ROOT) -> list[str]:
    """Extract base + theirs from an ESSVivaCopilot clone. Returns the verticals written.

    ``ess_root`` is the repo root or its ``sources/dev`` directory.
    """
    dev = ess_root if (ess_root / "AgentTemplates").is_dir() else ess_root / "sources" / "dev"
    templates_dir = dev / "AgentTemplates"
    solutions_dir = dev / "solutions"
    if not templates_dir.is_dir() or not solutions_dir.is_dir():
        raise FileNotFoundError(
            f"Expected 'AgentTemplates' and 'solutions' under {dev}. "
            "Point --ess-root at an ESSVivaCopilot clone."
        )

    baseline = _read_ca_baseline(solutions_dir)
    root.mkdir(parents=True, exist_ok=True)
    # Stored once at the reference root, bucketed by owning agent, because the same
    # suffix can exist under the HR agent, the IT agent and the shared core agent
    # with genuinely different content.
    (root / _BASELINE_FILE).write_text(
        json.dumps(
            {
                bucket: {
                    suffix: {
                        "suffix": component.suffix,
                        "schemaname": component.schemaname,
                        "component_type": component.component_type,
                        "solution": component.solution,
                        "data": component.data,
                    }
                    for suffix, component in sorted(components.items())
                }
                for bucket, components in sorted(baseline.items())
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    written: list[str] = []
    for vertical in TARGETS:
        plugin = templates_dir / DA_TEMPLATE_FOLDER_BY_VERTICAL[vertical] / "Plugin"
        agent_yml = next(iter(sorted((plugin / "Agents").glob("*/agent.yml"))), None)
        if agent_yml is None:
            continue
        destination = root / vertical
        destination.mkdir(parents=True, exist_ok=True)

        _copy(agent_yml, destination / _AGENT_FILE)
        _copy(agent_yml.parent / _CONFIG_FILE, destination / _CONFIG_FILE)
        _copy(plugin / _PACKAGE_FILE, destination / _PACKAGE_FILE)
        _copy(plugin / _OVERLAYS_FILE, destination / _OVERLAYS_FILE)

        package = _read_json(destination / _PACKAGE_FILE)
        (destination / _PROVENANCE_FILE).write_text(
            json.dumps(
                {
                    "vertical": vertical,
                    "vendored_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                    "ess_root": str(dev),
                    "da_agent_folder": agent_yml.parent.name,
                    "template_version": package.get("templateVersion"),
                    "package_type": package.get("packageType"),
                    "publisher": package.get("publisher"),
                    "baseline_components": len(baseline.get(vertical, {})),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        written.append(vertical)
    return written


def _read_ca_baseline(solutions_dir: Path) -> dict[str, dict[str, BaselineComponent]]:
    """Collect every OOB CA component, bucketed by owning agent and keyed by suffix.

    The buckets are ``"hr"``, ``"it"`` and ``"core"``, taken from the component's own
    schema-name prefix rather than from the solution it happens to live in. This
    matters: ``gpt.default`` exists under the HR agent, the IT agent and the shared
    core agent with materially different instructions, so a single pooled baseline
    would silently diff a customer's HR edit against IT's shipped content.

    Solutions are selected by the ``<UniqueName>`` in their manifest, matched against
    :data:`essmig.ess.OOB_CA_SOLUTIONS`. Folder names must **not** be used: the tree
    also holds Declarative Agent preview and proof-of-concept solutions, and several
    shipping solutions' unique names differ from their folder names outright
    (``EssHRWorkdayHCM`` → ``msdyn_EssHRWorkday``).
    """
    buckets: dict[str, dict[str, BaselineComponent]] = {target: {} for target in TARGETS}
    by_prefix = {CA_AGENT_SCHEMANAMES[bucket]: bucket for bucket in buckets}

    for solution in sorted(solutions_dir.iterdir()):
        if not solution.is_dir():
            continue
        unique_name = _solution_unique_name(solution)
        if unique_name not in OOB_CA_SOLUTIONS:
            continue
        components_dir = solution / "Solution" / "botcomponents"
        if not components_dir.is_dir():
            continue
        for component_dir in sorted(components_dir.iterdir()):
            manifest = component_dir / "botcomponent.xml"
            if not manifest.is_file():
                continue
            root = ET.parse(manifest).getroot()
            schemaname = root.get("schemaname") or ""
            bucket = by_prefix.get(schema_prefix(schemaname).lower())
            suffix = schema_suffix(schemaname)
            if bucket is None or not suffix or suffix in buckets[bucket]:
                continue
            data_file = component_dir / "data"
            buckets[bucket][suffix] = BaselineComponent(
                suffix=suffix,
                schemaname=schemaname,
                component_type=_int_or_none(root.findtext("componenttype")),
                solution=unique_name or solution.name,
                data=data_file.read_text(encoding="utf-8-sig") if data_file.is_file() else None,
            )
    return buckets


def _solution_unique_name(solution: Path) -> str | None:
    for relative in _SOLUTION_MANIFESTS:
        manifest = solution.joinpath(*relative.split("/"))
        if manifest.is_file():
            name = ET.parse(manifest).getroot().findtext("./SolutionManifest/UniqueName")
            return name.strip() if name else None
    return None


def _read_baseline(path: Path, vertical: str) -> dict[str, BaselineComponent]:
    """The baseline for one target: its own agent's shipped components.

    Each first-class agent (core, hr, it) is migrated independently against its own
    baseline. Core is a standalone hub agent, not shared library content, so it is
    **not** folded into the domain agents — HR and IT already ship their own copy of
    every suffix they share with Core (e.g. ConversationStart), and the hub's
    router topics belong to the Core package alone.
    """
    document = _read_json(path)
    resolved: dict[str, BaselineComponent] = {}
    entries = document.get(vertical)
    if isinstance(entries, dict):
        for suffix, entry in entries.items():
            if isinstance(entry, dict):
                resolved[suffix] = BaselineComponent(
                    suffix=entry.get("suffix") or suffix,
                    schemaname=entry.get("schemaname", ""),
                    component_type=entry.get("component_type"),
                    solution=entry.get("solution", ""),
                    data=entry.get("data"),
                )
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _copy(source: Path, destination: Path) -> None:
    if source.is_file():
        destination.write_bytes(source.read_bytes())


def _int_or_none(value: str | None) -> int | None:
    try:
        return int((value or "").strip())
    except ValueError:
        return None
