# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Pure normalization helpers for connected knowledge-base search results."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal, Mapping
from urllib.parse import parse_qsl, unquote, urlsplit

_SYS_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")
_ARTICLE_NUMBER_PATTERN = re.compile(r"^KB[0-9]{7}$", re.IGNORECASE)

_SYS_ID_KEYS = frozenset({"sys_id", "sysid"})
_ARTICLE_NUMBER_KEYS = frozenset(
    {"number", "article_number", "articlenumber", "kb_number", "kbnumber"}
)
_URL_ALIAS_PRECEDENCE = ("url", "source_url", "sourceurl", "web_url", "weburl")
_URL_KEYS = frozenset(_URL_ALIAS_PRECEDENCE)
_URL_SYS_ID_QUERY_KEYS = frozenset({"sys_id", "sysparm_sys_id"})
_URL_ARTICLE_NUMBER_QUERY_KEYS = frozenset(
    {"sysparm_article", "article_number", "number"}
)
_SERVICENOW_CONNECTOR_ID = (
    "/providers/Microsoft.PowerApps/apis/shared_service-now".casefold()
)
_MISSING_IDENTIFIER_REASON = "No verified ServiceNow identifier found."


@dataclass(frozen=True)
class ServiceNowIdentifier:
    kind: Literal["sys_id", "number"]
    value: str


@dataclass(frozen=True)
class RankedExternalItem:
    rank: int
    hit_id: str
    title: str
    summary: str
    source_url: str
    properties: dict[str, Any]
    service_now_identifier: ServiceNowIdentifier | None
    skip_reason: str | None


@dataclass(frozen=True)
class ConnectionClassification:
    kind: Literal["servicenow", "other", "ambiguous"]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class _IdentifierResolution:
    identifier: ServiceNowIdentifier | None = None
    conflicted: bool = False


def normalize_external_item_hits(payload: Any) -> list[RankedExternalItem]:
    """Normalize documented Microsoft Search external-item hit containers."""
    if not isinstance(payload, Mapping):
        return []

    value = payload.get("value")
    if not isinstance(value, list):
        return []

    normalized: list[RankedExternalItem] = []
    seen_identifier_hosts: set[tuple[str, str, str]] = set()

    for response in value:
        if not isinstance(response, Mapping):
            continue
        containers = response.get("hitsContainers")
        if not isinstance(containers, list):
            continue
        for container in containers:
            if not isinstance(container, Mapping):
                continue
            hits = container.get("hits")
            if not isinstance(hits, list):
                continue
            for hit in hits:
                if not isinstance(hit, Mapping):
                    continue
                item = _normalize_hit(hit)
                identifier = item.service_now_identifier
                if identifier is not None:
                    hostname = _source_hostname_evidence(hit)
                    if hostname is not None:
                        canonical = (identifier.kind, identifier.value, hostname)
                        if canonical in seen_identifier_hosts:
                            continue
                        seen_identifier_hosts.add(canonical)
                normalized.append(item)

    return normalized


def extract_servicenow_identifier(resource: Any) -> ServiceNowIdentifier | None:
    """Extract a conservative ServiceNow identifier from recognized fields."""
    if not isinstance(resource, Mapping):
        return None

    properties = resource.get("properties")
    mappings = [
        resource,
        properties if isinstance(properties, Mapping) else {},
    ]

    sys_id_values = list(_alias_values_from_mappings(mappings, _SYS_ID_KEYS))
    article_number_values = list(
        _alias_values_from_mappings(mappings, _ARTICLE_NUMBER_KEYS)
    )
    for value in _alias_values_from_mappings(mappings, _URL_KEYS):
        url_sys_ids, url_article_numbers = _servicenow_url_identifier_values(value)
        sys_id_values.extend(url_sys_ids)
        article_number_values.extend(url_article_numbers)

    resolution = _resolve_identifier_sources(sys_id_values, article_number_values)
    if resolution.conflicted:
        return None
    return resolution.identifier


def classify_graph_connection(connection: Any) -> ConnectionClassification:
    """Classify a Graph connection using explicit metadata, never loose text."""
    if not isinstance(connection, Mapping):
        return ConnectionClassification("ambiguous", ())

    evidence: list[str] = []
    has_servicenow_hint = False
    has_connector_id = False
    connector_id = connection.get("connectorId")
    if isinstance(connector_id, str) and connector_id.strip():
        has_connector_id = True
        normalized_connector_id = connector_id.strip()
        folded_connector_id = normalized_connector_id.casefold()
        evidence.append(f"connectorId={normalized_connector_id}")
        if folded_connector_id == _SERVICENOW_CONNECTOR_ID:
            return ConnectionClassification("servicenow", tuple(evidence))
        has_servicenow_hint = _mentions_servicenow(normalized_connector_id)

    for field, label in (
        ("name", "name mentions ServiceNow"),
        ("description", "description mentions ServiceNow"),
    ):
        value = connection.get(field)
        if isinstance(value, str) and _mentions_servicenow(value):
            evidence.append(label)
            has_servicenow_hint = True

    if has_connector_id and not has_servicenow_hint:
        return ConnectionClassification("other", tuple(evidence))
    return ConnectionClassification("ambiguous", tuple(evidence))


def _normalize_hit(hit: Mapping[str, Any]) -> RankedExternalItem:
    resource = hit.get("resource")
    resource_mapping = resource if isinstance(resource, Mapping) else {}
    properties_value = resource_mapping.get("properties")
    properties = dict(properties_value) if isinstance(properties_value, Mapping) else {}
    identifier = extract_servicenow_identifier(resource_mapping)

    rank_value = hit.get("rank")
    rank = (
        rank_value
        if isinstance(rank_value, int) and not isinstance(rank_value, bool)
        else 0
    )

    return RankedExternalItem(
        rank=rank,
        hit_id=_string_value(hit.get("hitId")),
        title=_resource_text(resource_mapping, properties, ("title",)),
        summary=_string_value(hit.get("summary")),
        source_url=_resource_text(
            resource_mapping,
            properties,
            _URL_ALIAS_PRECEDENCE,
        ),
        properties=properties,
        service_now_identifier=identifier,
        skip_reason=None if identifier is not None else _MISSING_IDENTIFIER_REASON,
    )


def _resource_text(
    resource: Mapping[str, Any],
    properties: Mapping[str, Any],
    aliases: Iterable[str],
) -> str:
    for alias in aliases:
        for mapping in (resource, properties):
            for key, value in mapping.items():
                if (
                    isinstance(key, str)
                    and key.casefold() == alias
                    and isinstance(value, str)
                    and value.strip()
                ):
                    return value.strip()
    return ""


def _source_hostname_evidence(hit: Mapping[str, Any]) -> str | None:
    resource = hit.get("resource")
    if not isinstance(resource, Mapping):
        return None
    properties = resource.get("properties")
    mappings = [
        resource,
        properties if isinstance(properties, Mapping) else {},
    ]

    hostnames: set[str] = set()
    found_url = False
    for value in _alias_values_from_mappings(mappings, _URL_KEYS):
        if not isinstance(value, str) or not value.strip():
            continue
        found_url = True
        try:
            parsed = urlsplit(value.strip())
            hostname = parsed.hostname
        except ValueError:
            return None
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or not parsed.netloc
            or not hostname
            or not _is_servicenow_hostname(hostname)
        ):
            return None
        hostnames.add(hostname.casefold().rstrip("."))

    if not found_url or len(hostnames) != 1:
        return None
    return next(iter(hostnames))


def _alias_values(
    mapping: Mapping[str, Any],
    aliases: set[str] | frozenset[str],
):
    for key, value in mapping.items():
        if isinstance(key, str) and key.casefold() in aliases:
            yield value


def _alias_values_from_mappings(
    mappings: Iterable[Mapping[str, Any]],
    aliases: set[str] | frozenset[str],
) -> Iterable[Any]:
    for mapping in mappings:
        yield from _alias_values(mapping, aliases)


def _resolve_identifier_candidates(
    values: Iterable[Any],
    normalizer: Callable[[Any], ServiceNowIdentifier | None],
) -> _IdentifierResolution:
    identifiers = {
        identifier
        for value in values
        if (identifier := normalizer(value)) is not None
    }
    if len(identifiers) > 1:
        return _IdentifierResolution(conflicted=True)
    return _IdentifierResolution(next(iter(identifiers), None))


def _normalize_sys_id(value: Any) -> ServiceNowIdentifier | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not _SYS_ID_PATTERN.fullmatch(candidate):
        return None
    return ServiceNowIdentifier("sys_id", candidate.lower())


def _normalize_article_number(value: Any) -> ServiceNowIdentifier | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not _ARTICLE_NUMBER_PATTERN.fullmatch(candidate):
        return None
    return ServiceNowIdentifier("number", candidate.upper())


def _servicenow_url_identifier_values(value: Any) -> tuple[list[Any], list[Any]]:
    if not isinstance(value, str):
        return [], []
    source_url = value.strip()
    if not source_url:
        return [], []

    try:
        parsed = urlsplit(source_url)
        hostname = parsed.hostname
    except ValueError:
        return [], []
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or not _is_servicenow_hostname(hostname)
    ):
        return [], []

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    path_segments = [unquote(segment) for segment in parsed.path.split("/")]

    return (
        [
            query_value
            for query_key, query_value in query_pairs
            if query_key.casefold() in _URL_SYS_ID_QUERY_KEYS
        ]
        + path_segments,
        [
            query_value
            for query_key, query_value in query_pairs
            if query_key.casefold() in _URL_ARTICLE_NUMBER_QUERY_KEYS
        ]
        + path_segments,
    )


def _resolve_identifier_sources(
    sys_id_values: Iterable[Any],
    article_number_values: Iterable[Any],
) -> _IdentifierResolution:
    sys_id_resolution = _resolve_identifier_candidates(
        sys_id_values,
        _normalize_sys_id,
    )
    article_resolution = _resolve_identifier_candidates(
        article_number_values,
        _normalize_article_number,
    )
    if sys_id_resolution.conflicted or article_resolution.conflicted:
        return _IdentifierResolution(conflicted=True)
    if sys_id_resolution.identifier is not None:
        return sys_id_resolution
    return article_resolution


def _is_servicenow_hostname(hostname: str) -> bool:
    folded = hostname.casefold().rstrip(".")
    return (
        folded.endswith(".service-now.com")
        or folded.endswith(".servicenow.com")
        or folded in {"service-now.com", "servicenow.com"}
    )


def _mentions_servicenow(value: str) -> bool:
    return bool(re.search(r"service[\s_-]*now", value, re.IGNORECASE))


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
