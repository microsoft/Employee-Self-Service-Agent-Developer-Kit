# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared strict parsing primitives for Workday administrator contracts."""

from __future__ import annotations

from datetime import datetime
import ipaddress
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from workday_connect_evidence_contracts import (
    WorkdayConnectContractError,
    required_text as required_text,
)


_SECRET_VALUE_MARKERS = (
    "-----begin certificate-----",
    "-----begin private key-----",
    "-----begin rsa private key-----",
    "client_secret=",
    '"client_secret"',
    '"access_token"',
    '"refresh_token"',
)


def _safe_nonsecret_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkdayConnectContractError(f"{label} is required.")
    if len(text) > 2048 or "\x00" in text:
        raise WorkdayConnectContractError(f"{label} exceeds the safe evidence limit.")
    normalized = text.casefold()
    if any(marker in normalized for marker in _SECRET_VALUE_MARKERS):
        raise WorkdayConnectContractError(
            f"{label} appears to contain secret or certificate material."
        )
    return text


def _reject_secret_like_value(value: Any, label: str) -> None:
    if isinstance(value, str):
        normalized = value.casefold()
        if (
            len(value) > 2048
            or "\x00" in value
            or any(marker in normalized for marker in _SECRET_VALUE_MARKERS)
        ):
            raise WorkdayConnectContractError(
                f"{label} appears to contain secret or certificate material."
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_secret_like_value(item, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_like_value(item, f"{label}[{index}]")


def _parse_labeled_worksheet(
    worksheet: str,
    *,
    labels: tuple[str, ...],
    label: str,
    multiline_labels: frozenset[str] = frozenset(),
) -> dict[str, str]:
    if not isinstance(worksheet, str) or not worksheet.strip():
        raise WorkdayConnectContractError(f"{label} is required.")
    if len(worksheet) > 16384 or "\x00" in worksheet:
        raise WorkdayConnectContractError(f"{label} exceeds the safe evidence limit.")
    normalized = worksheet.casefold()
    if any(marker in normalized for marker in _SECRET_VALUE_MARKERS):
        raise WorkdayConnectContractError(
            f"{label} appears to contain secret or certificate material."
        )
    values: dict[str, str] = {}
    current_label: str | None = None
    for line_number, raw_line in enumerate(worksheet.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        matched_label = next(
            (candidate for candidate in labels if line.startswith(candidate + ":")),
            None,
        )
        if matched_label is not None:
            if matched_label in values:
                raise WorkdayConnectContractError(
                    f"{label} contains duplicate label '{matched_label}'."
                )
            values[matched_label] = line[len(matched_label) + 1 :].strip()
            current_label = matched_label
            continue
        if current_label in multiline_labels:
            values[current_label] = "\n".join(
                value for value in (values[current_label], line) if value
            )
            continue
        raise WorkdayConnectContractError(
            f"{label} line {line_number} does not use a recognized exact label."
        )
    missing = [candidate for candidate in labels if candidate not in values]
    if missing:
        raise WorkdayConnectContractError(
            f"{label} is missing labels: " + ", ".join(missing) + "."
        )
    return values


def _worksheet_choice(
    values: Mapping[str, str],
    label: str,
    choices: Mapping[str, str],
) -> str:
    supplied = str(values.get(label) or "").strip()
    normalized = supplied.casefold()
    normalized_choices = {
        option.casefold(): mapped for option, mapped in choices.items()
    }
    if normalized not in normalized_choices:
        raise WorkdayConnectContractError(
            f"{label} must use one of the worksheet's listed successful answers."
        )
    return normalized_choices[normalized]


def _administrator_attestation(
    *,
    observed_value: str | None = None,
) -> dict[str, str]:
    result = {
        "outcome": "confirmed",
        "provenance": "administrator-attestation",
    }
    if observed_value is not None:
        result["observedValue"] = observed_value
    return result


def _certificate_thumbprint(value: Any, label: str) -> str:
    normalized = re.sub(r"[\s:]", "", str(value or ""))
    if not re.fullmatch(r"[0-9A-Fa-f]{4,128}", normalized):
        raise WorkdayConnectContractError(
            f"{label} must contain hexadecimal thumbprint characters only."
        )
    return normalized.upper()


def _normalized_uri(value: Any) -> str:
    return str(value or "").strip().rstrip("/").casefold()


def _https_url(value: Any, label: str) -> str:
    text = str(value or "").strip().rstrip("/")
    parsed = urlparse(text)
    try:
        port = parsed.port
    except ValueError as exc:
        raise WorkdayConnectContractError(f"{label} must be an HTTPS URL.") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise WorkdayConnectContractError(f"{label} must be an HTTPS URL.")
    hostname = parsed.hostname.casefold().rstrip(".")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise WorkdayConnectContractError(
            f"{label} must use a Workday service hostname, not an IP address."
        )
    if not hostname.endswith((".workday.com", ".myworkday.com")):
        raise WorkdayConnectContractError(
            f"{label} must use a Workday-owned service hostname."
        )
    return text


def _absolute_https_url(value: Any, label: str) -> str:
    text = str(value or "").strip().rstrip("/")
    parsed = urlparse(text)
    try:
        port = parsed.port
    except ValueError as exc:
        raise WorkdayConnectContractError(f"{label} must be an HTTPS URL.") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise WorkdayConnectContractError(f"{label} must be an HTTPS URL.")
    return text


def _safe_string_list(
    value: Any,
    label: str,
    *,
    allow_empty: bool,
) -> list[str]:
    if not isinstance(value, list):
        raise WorkdayConnectContractError(f"{label} must be an array.")
    if any(not isinstance(item, str) for item in value):
        raise WorkdayConnectContractError(f"{label} must contain strings.")
    normalized = [_safe_nonsecret_text(item, f"{label} item") for item in value]
    if any(not item for item in normalized):
        raise WorkdayConnectContractError(f"{label} must contain non-empty strings.")
    if not allow_empty and not normalized:
        raise WorkdayConnectContractError(f"{label} must contain at least one value.")
    if len(normalized) != len(set(normalized)):
        raise WorkdayConnectContractError(f"{label} must not contain duplicates.")
    return normalized


def _optional_domains(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise WorkdayConnectContractError("Workday optionalDomains must be an array.")
    normalized = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise WorkdayConnectContractError(
                "Every optional Workday domain must identify its supported scenario."
            )
        unexpected = sorted(set(item) - {"domain", "scenario"})
        if unexpected:
            raise WorkdayConnectContractError(
                "Optional Workday domain contains unsupported fields: "
                + ", ".join(unexpected)
            )
        domain = _safe_nonsecret_text(
            item.get("domain"),
            "Optional Workday domain",
        )
        scenario = _safe_nonsecret_text(
            item.get("scenario"),
            "Optional Workday domain supported scenario",
        )
        key = (domain.casefold(), scenario.casefold())
        if key in seen:
            raise WorkdayConnectContractError(
                "Workday optionalDomains must not contain duplicates."
            )
        seen.add(key)
        normalized.append({"domain": domain, "scenario": scenario})
    return normalized


def _require_endpoint_path(
    url: str,
    expected_path: str,
    label: str,
) -> None:
    observed_path = urlparse(url).path.rstrip("/")
    if observed_path.casefold() != expected_path.casefold():
        raise WorkdayConnectContractError(
            f"{label} must end exactly at {expected_path}."
        )


def _date_only(value: str, label: str) -> str:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError as exc:
        raise WorkdayConnectContractError(
            f"{label} must be an ISO-8601 date or timestamp."
        ) from exc
