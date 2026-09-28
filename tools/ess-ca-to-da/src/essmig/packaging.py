"""Emit the migrated Declarative Agent as an ALM package.

The tool never writes to the customer's tenant. Its deliverable is a package the
customer imports themselves::

    POST .../copilotstudio/tenants/{tid}/environments/{eid}/minimalBots/alm/import

with the zip as the payload and ``schemaName`` set to the existing agent to take
the overwrite path (import returns 409 if the agent already exists and no
``schemaName`` was supplied). Import is a clean replace into **Dev only**;
Test and Prod are untouched until the customer promotes.

The on-disk layout mirrors the ESS template's ``Plugin`` folder, and the ``Plugin``
folder is itself the top-level entry inside the zip (the import API requires a
``Plugin/Agents/<schema>/agent.yml`` entry)::

    Plugin/package.json
    Plugin/Overlays.json
    Plugin/Agents/<agent schema name>/agent.yml
    Plugin/Agents/<agent schema name>/app.config.dev.json

Environment-specific values never travel in the package: per §6.1 the config file
carries *pointers*, and the concrete connection ids and secrets are bound in the
destination environment. :func:`scrub_config` enforces that.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from essmig.reference import ReferenceSet, keep_timestamps_verbatim

PLUGIN_DIRNAME = "Plugin"
AGENTS_DIRNAME = "Agents"
AGENT_FILE = "agent.yml"
CONFIG_FILE = "app.config.dev.json"
PACKAGE_FILE = "package.json"
OVERLAYS_FILE = "Overlays.json"


class UnboundPointerError(RuntimeError):
    """A required configuration pointer has no value and the package would fail to publish."""


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    # The ESS template ships agent.yml with block sequences indented under their key
    # (dash at offset 2 within a 4-space sequence indent) and never wraps long
    # scalars. Reproduce both exactly: a wrapped scalar folds newlines to spaces on
    # re-parse — which silently corrupts the base64 agent icon — and a strict import
    # binder is unforgiving of a package whose agent.yml differs structurally from
    # what the platform emits. An effectively unlimited width disables all wrapping.
    yaml.width = 1 << 30
    yaml.indent(mapping=2, sequence=4, offset=2)
    keep_timestamps_verbatim(yaml)
    return yaml


def write_package(
    destination: Path, reference: ReferenceSet, agent: Any, *, created_by: str = "ess-ca-to-da"
) -> Path:
    """Write the package tree under ``destination`` and return the ``Plugin`` folder."""
    schema_name = reference.da_schemaname
    plugin = destination / PLUGIN_DIRNAME
    agent_dir = plugin / AGENTS_DIRNAME / schema_name
    agent_dir.mkdir(parents=True, exist_ok=True)

    with (agent_dir / AGENT_FILE).open("w", encoding="utf-8", newline="\n") as stream:
        _yaml().dump(agent, stream)

    _write_json(agent_dir / CONFIG_FILE, scrub_config(reference.config))
    _write_json(plugin / PACKAGE_FILE, _package_metadata(reference, created_by))
    if reference.overlays:
        _write_json(plugin / OVERLAYS_FILE, reference.overlays)
    return plugin


def zip_package(plugin: Path, archive: Path) -> Path:
    """Zip the package with the ``Plugin`` folder as the archive's top-level entry."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(plugin.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(plugin.parent).as_posix())
    return archive


def scrub_config(config: dict[str, Any]) -> dict[str, Any]:
    """Strip environment-bound values from ``app.config.<realm>.json``.

    Connection ids and secret values belong to the environment the package is
    imported into, not to the package. A connection is left *unbound* by setting
    its ``connectionId`` to ``null`` — the ESS template ships exactly this shape and
    the import binding step relies on the key being present. Removing the key
    entirely makes the package fail to bind into a valid Dev agent.
    """
    scrubbed: dict[str, Any] = json.loads(json.dumps(config))
    connections = scrubbed.get("connections")
    if isinstance(connections, dict):
        for connection in connections.values():
            if isinstance(connection, dict) and "connectionId" in connection:
                connection["connectionId"] = None
    elif isinstance(connections, list):
        for connection in connections:
            if isinstance(connection, dict) and "connectionId" in connection:
                connection["connectionId"] = None

    secrets = scrubbed.get("secrets")
    if isinstance(secrets, dict):
        for key, value in list(secrets.items()):
            # Only key-vault *references* may travel; a literal is a leaked secret.
            if not (isinstance(value, str) and value.startswith("kv://")):
                secrets.pop(key)
    return scrubbed


def check_pointers(agent: Any, config: dict[str, Any]) -> list[str]:
    """Return the config keys referenced by pointers in ``agent.yml`` but not defined.

    Publishing fails hard on an unbound pointer, so the tool surfaces them here
    rather than letting the customer discover them at import time. Connection ids
    and secrets are expected to be unbound in the package and are not reported.
    """
    values = config.get("values")
    defined = set(values) if isinstance(values, dict) else set()
    referenced = _referenced_value_keys(agent)
    return sorted(referenced - defined)


def _referenced_value_keys(node: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for value in node.values():
            keys |= _referenced_value_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _referenced_value_keys(item)
    elif isinstance(node, str):
        marker = '${config.values["'
        start = node.find(marker)
        while start != -1:
            end = node.find('"]}', start)
            if end == -1:
                break
            keys.add(node[start + len(marker) : end])
            start = node.find(marker, end)
    return keys


def _package_metadata(reference: ReferenceSet, created_by: str) -> dict[str, Any]:
    """Carry the template's package identity forward, restamping authorship.

    ``packageType``, ``publisher`` and ``templateVersion`` must stay as ESS shipped
    them — they are what marks the agent as a *templated* agent eligible for future
    platform upgrades.
    """
    package = dict(reference.package)
    package.setdefault("formatVersion", "1.0")
    package["createdBy"] = created_by
    package["createdUtc"] = datetime.now(UTC).isoformat(timespec="seconds")
    return package


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def package_bytes(plugin: Path) -> bytes:
    """The package zip as bytes, for callers that do not want a file on disk."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(plugin.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(plugin.parent).as_posix())
    return buffer.getvalue()
