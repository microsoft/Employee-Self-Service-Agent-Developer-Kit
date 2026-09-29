# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Resolve seeded and workspace-observed DA product identities."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "reference"
    / "da-product-setup-registry.json"
)
OBSERVATIONS_PATH = Path(".local/setup/da-product-observations.json")
_PRODUCT_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class DAProductRegistryError(RuntimeError):
    """Raised when the DA product registry is malformed or ambiguous."""


def _exact_names(value: Any, field: str, product_key: str) -> set[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise DAProductRegistryError(
            f"Product {product_key!r} has invalid {field}."
        )
    return {item.strip().casefold() for item in value}


def _required_connection(value: Any, product_key: str) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DAProductRegistryError(
            f"Product {product_key!r} has an invalid requiredConnection."
        )
    display_name = value.get("displayName")
    connector_api_name = value.get("connectorApiName")
    if (
        not isinstance(display_name, str)
        or not display_name.strip()
        or not isinstance(connector_api_name, str)
        or not connector_api_name.strip().casefold().startswith("shared_")
    ):
        raise DAProductRegistryError(
            f"Product {product_key!r} has an invalid requiredConnection."
        )
    return {
        "displayName": display_name.strip(),
        "connectorApiName": connector_api_name.strip().casefold(),
    }


def load_product_registry(
    path: Path = REGISTRY_PATH,
) -> dict[str, dict[str, Any]]:
    """Load and validate the stable DA product setup registry."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DAProductRegistryError(
            "The DA product setup registry could not be read."
        ) from exc
    products = payload.get("products") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 1
        or not isinstance(products, dict)
    ):
        raise DAProductRegistryError(
            "The DA product setup registry has an unsupported shape."
        )

    normalized: dict[str, dict[str, Any]] = {}
    for product_key, product in products.items():
        if (
            not isinstance(product_key, str)
            or not product_key.strip()
            or not isinstance(product, dict)
        ):
            raise DAProductRegistryError(
                "The DA product setup registry contains an invalid product."
            )
        normalized[product_key] = {
            "catalogNames": _exact_names(
                product.get("catalogNames"),
                "catalogNames",
                product_key,
            ),
            "agentSchemaNames": _exact_names(
                product.get("agentSchemaNames"),
                "agentSchemaNames",
                product_key,
            ),
            "requiredConnection": _required_connection(
                product.get("requiredConnection"),
                product_key,
            ),
        }
    return normalized


def resolve_product_setup(
    *,
    catalog_name: str | None = None,
    agent_schema_name: str | None = None,
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, Any] | None:
    """Resolve one exact product without inferring from partial names."""
    catalog = str(catalog_name or "").strip().casefold()
    schema = str(agent_schema_name or "").strip().casefold()
    matches: list[tuple[str, str, dict[str, Any]]] = []
    for product_key, product in load_product_registry(registry_path).items():
        if catalog and catalog in product["catalogNames"]:
            matches.append((product_key, "catalog-name", product))
        if schema and schema in product["agentSchemaNames"]:
            matches.append((product_key, "agent-schema-name", product))

    product_keys = {product_key for product_key, _, _ in matches}
    if len(product_keys) > 1:
        raise DAProductRegistryError(
            "The DA product setup registry matched more than one product."
        )
    if not matches:
        return None
    product_key = matches[0][0]
    product = matches[0][2]
    matched_by = sorted({match_type for _, match_type, _ in matches})
    return {
        "productKey": product_key,
        "matchedBy": matched_by,
        "requiredConnection": copy.deepcopy(product["requiredConnection"]),
    }


def _observation_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DAProductRegistryError(
            f"Product observation {field!r} must be a non-empty string."
        )
    return value.strip()


def _normalize_observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DAProductRegistryError(
            "The product observations file contains an invalid entry."
        )
    product_key = _observation_text(value.get("productKey"), "productKey")
    if _PRODUCT_KEY_PATTERN.fullmatch(product_key) is None:
        raise DAProductRegistryError(
            "Product observation 'productKey' must use lowercase kebab-case."
        )
    installed = value.get("installed", False)
    if not isinstance(installed, bool):
        raise DAProductRegistryError(
            "Product observation 'installed' must be a boolean."
        )
    environment_id = str(value.get("environmentId") or "").strip()
    ring = str(value.get("ring") or "").strip().casefold()
    return {
        "productKey": product_key,
        "packageId": _observation_text(value.get("packageId"), "packageId"),
        "catalogName": _observation_text(
            value.get("catalogName"),
            "catalogName",
        ),
        "agentSchemaName": _observation_text(
            value.get("agentSchemaName"),
            "agentSchemaName",
        ),
        "source": _observation_text(value.get("source"), "source"),
        "observedAt": _observation_text(
            value.get("observedAt"),
            "observedAt",
        ),
        "environmentId": environment_id,
        "ring": ring,
        "installed": installed,
    }


def load_product_observations(kit_root: Path) -> list[dict[str, Any]]:
    """Load the workspace-local product identity overlay."""
    path = kit_root.resolve() / OBSERVATIONS_PATH
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DAProductRegistryError(
            "The workspace product observations could not be read."
        ) from exc
    observations = (
        payload.get("observations") if isinstance(payload, dict) else None
    )
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 1
        or not isinstance(observations, list)
    ):
        raise DAProductRegistryError(
            "The workspace product observations have an unsupported shape."
        )
    return [_normalize_observation(item) for item in observations]


def _write_observations(
    path: Path,
    observations: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary)
    try:
        try:
            stream = os.fdopen(
                handle,
                "w",
                encoding="utf-8",
                newline="",
            )
        except BaseException:
            os.close(handle)
            raise
        with stream:
            json.dump(
                {
                    "schemaVersion": 1,
                    "observations": observations,
                },
                stream,
                indent=2,
                ensure_ascii=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def observe_product_mapping(
    kit_root: Path,
    *,
    product_key: str,
    package_id: str,
    catalog_name: str,
    agent_schema_name: str,
    source: str,
    environment_id: str,
    ring: str,
) -> dict[str, Any]:
    """Record one product identity and target-scoped installed observation."""
    observation = _normalize_observation(
        {
            "productKey": product_key,
            "packageId": package_id,
            "catalogName": catalog_name,
            "agentSchemaName": agent_schema_name,
            "source": source,
            "observedAt": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "environmentId": _observation_text(
                environment_id,
                "environmentId",
            ),
            "ring": _observation_text(ring, "ring").casefold(),
            "installed": True,
        }
    )
    observations = load_product_observations(kit_root)
    product = observation["productKey"].casefold()
    environment = observation["environmentId"].casefold()
    observed_ring = observation["ring"]
    observations = [
        item
        for item in observations
        if not (
            item["productKey"].casefold() == product
            and item["environmentId"].casefold() == environment
            and item["ring"] == observed_ring
        )
    ]
    observations.append(observation)
    path = kit_root.resolve() / OBSERVATIONS_PATH
    _write_observations(path, observations)
    return {**observation, "path": OBSERVATIONS_PATH.as_posix()}


def resolve_product_identity(
    *,
    package_id: str | None = None,
    catalog_name: str | None = None,
    agent_schema_name: str | None = None,
    environment_id: str | None = None,
    ring: str | None = None,
    kit_root: Path | None = None,
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, Any] | None:
    """Resolve workspace observations before the checked-in seed."""
    package = str(package_id or "").strip().casefold()
    catalog = str(catalog_name or "").strip().casefold()
    schema = str(agent_schema_name or "").strip().casefold()
    environment = str(environment_id or "").strip().casefold()
    normalized_ring = str(ring or "").strip().casefold()
    if kit_root is not None:
        observations = list(reversed(load_product_observations(kit_root)))
        match_tiers: list[
            list[tuple[dict[str, Any], list[str]]]
        ] = []
        if package and catalog:
            match_tiers.append(
                [
                    (
                        observation,
                        [
                            "workspace-package-id",
                            "workspace-catalog-name",
                        ],
                    )
                    for observation in observations
                    if observation["packageId"].casefold() == package
                    and observation["catalogName"].casefold() == catalog
                ]
            )
        if package:
            match_tiers.append(
                [
                    (observation, ["workspace-package-id"])
                    for observation in observations
                    if observation["packageId"].casefold() == package
                ]
            )
        if schema:
            match_tiers.append(
                [
                    (observation, ["workspace-agent-schema-name"])
                    for observation in observations
                    if observation["agentSchemaName"].casefold() == schema
                ]
            )
        if catalog:
            match_tiers.append(
                [
                    (observation, ["workspace-catalog-name"])
                    for observation in observations
                    if observation["catalogName"].casefold() == catalog
                ]
            )
        matches: list[tuple[dict[str, Any], list[str]]] = []
        for tier in match_tiers:
            if not tier:
                continue
            if len({item[0]["productKey"] for item in tier}) == 1:
                matches = tier
            break
        selected = next(
            (
                match
                for match in matches
                if environment
                and normalized_ring
                and match[0]["environmentId"].casefold() == environment
                and match[0]["ring"] == normalized_ring
            ),
            matches[0] if matches else None,
        )
        if selected is not None:
            observation, matched_by = selected
            seeded = load_product_registry(registry_path).get(
                observation["productKey"]
            )
            installed = bool(
                observation["installed"]
                and environment
                and normalized_ring
                and observation["environmentId"].casefold() == environment
                and observation["ring"] == normalized_ring
            )
            result = {
                "productKey": observation["productKey"],
                "agentSchemaName": observation["agentSchemaName"],
                "matchedBy": matched_by,
                "identitySource": "workspace-observation",
                "requiredConnection": copy.deepcopy(
                    seeded["requiredConnection"] if seeded else None
                ),
            }
            if installed:
                result["installed"] = True
            return result
    seeded = resolve_product_setup(
        catalog_name=catalog_name,
        agent_schema_name=agent_schema_name,
        registry_path=registry_path,
    )
    if seeded is None:
        return None
    return {
        **seeded,
        "identitySource": "checked-in-seed",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Maintain workspace-observed DA product identities."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    observe = commands.add_parser(
        "observe",
        help="Record operation-established product identity and installation.",
    )
    observe.add_argument("--kit-root", type=Path, default=Path.cwd())
    observe.add_argument("--product-key", required=True)
    observe.add_argument("--package-id", required=True)
    observe.add_argument("--catalog-name", required=True)
    observe.add_argument("--agent-schema-name", required=True)
    observe.add_argument("--source", required=True)
    observe.add_argument("--environment-id", required=True)
    observe.add_argument("--ring", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = observe_product_mapping(
            args.kit_root,
            product_key=args.product_key,
            package_id=args.package_id,
            catalog_name=args.catalog_name,
            agent_schema_name=args.agent_schema_name,
            source=args.source,
            environment_id=args.environment_id,
            ring=args.ring,
        )
    except DAProductRegistryError as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    print(
        "DA_PRODUCT_OBSERVATION_JSON:"
        f"{json.dumps(result, ensure_ascii=True)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
