# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Resolve DA foundation requirements from the local product registry."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "reference"
    / "da-product-setup-registry.json"
)


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
