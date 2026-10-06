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

_WORKSHEET_TABLE_HEADERS = (
    "Information to capture",
    "Where to find it",
    "What to record",
    "Example value",
    "Your tenant values",
)


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        raise ValueError
    cells: list[str] = []
    current: list[str] = []
    index = 1
    while index < len(stripped) - 1:
        character = stripped[index]
        if (
            character == "\\"
            and index + 1 < len(stripped) - 1
            and stripped[index + 1] == "|"
        ):
            current.append("|")
            index += 2
            continue
        if character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        index += 1
    cells.append("".join(current).strip())
    return cells


def _parse_markdown_worksheet(
    lines: list[str],
    *,
    labels: tuple[str, ...],
    label: str,
    multiline_labels: frozenset[str],
) -> dict[str, str]:
    if len(lines) < 2:
        raise WorkdayConnectContractError(
            f"{label} table must include a header and separator row."
        )
    try:
        headers = _split_markdown_table_row(lines[0])
        separators = _split_markdown_table_row(lines[1])
    except ValueError as exc:
        raise WorkdayConnectContractError(
            f"{label} must use a complete Markdown table."
        ) from exc
    if tuple(headers) != _WORKSHEET_TABLE_HEADERS:
        raise WorkdayConnectContractError(
            f"{label} table must use the expected five column headers."
        )
    if len(separators) != len(headers) or any(
        re.fullmatch(r":?-{3,}:?", cell) is None for cell in separators
    ):
        raise WorkdayConnectContractError(
            f"{label} table separator row is invalid."
        )

    values: dict[str, str] = {}
    for line_number, line in enumerate(lines[2:], start=3):
        try:
            cells = _split_markdown_table_row(line)
        except ValueError as exc:
            raise WorkdayConnectContractError(
                f"{label} table row {line_number} is invalid."
            ) from exc
        if len(cells) != len(headers):
            raise WorkdayConnectContractError(
                f"{label} table row {line_number} must contain five columns."
            )
        row_label = cells[0]
        if row_label not in labels:
            raise WorkdayConnectContractError(
                f"{label} contains unknown information label '{row_label}'."
            )
        if row_label in values:
            raise WorkdayConnectContractError(
                f"{label} contains duplicate label '{row_label}'."
            )
        replacement = "\n" if row_label in multiline_labels else " "
        values[row_label] = re.sub(
            r"<br\s*/?>",
            replacement,
            cells[4],
            flags=re.IGNORECASE,
        ).strip()

    missing = [candidate for candidate in labels if candidate not in values]
    if missing:
        raise WorkdayConnectContractError(
            f"{label} is missing labels: " + ", ".join(missing) + "."
        )
    return values


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
    label_aliases: Mapping[str, str] | None = None,
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
    lines = [line.strip() for line in worksheet.splitlines() if line.strip()]
    if lines and lines[0].startswith("|"):
        return _parse_markdown_worksheet(
            lines,
            labels=labels,
            label=label,
            multiline_labels=multiline_labels,
        )
    normalized_labels = {
        re.sub(r"[^a-z0-9]+", " ", candidate.casefold()).strip(): candidate
        for candidate in labels
    }
    for alias, canonical in (label_aliases or {}).items():
        if canonical not in labels:
            raise ValueError(f"Unknown canonical worksheet label: {canonical}")
        normalized_alias = re.sub(
            r"[^a-z0-9]+",
            " ",
            alias.casefold(),
        ).strip()
        existing = normalized_labels.get(normalized_alias)
        if existing is not None and existing != canonical:
            raise ValueError(f"Ambiguous worksheet label alias: {alias}")
        normalized_labels[normalized_alias] = canonical
    values: dict[str, str] = {}
    current_label: str | None = None
    for line_number, raw_line in enumerate(worksheet.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        supplied_label, separator, supplied_value = line.partition(":")
        normalized_label = re.sub(
            r"[^a-z0-9]+",
            " ",
            re.sub(r"^(?:[-*]|\d+[.)])\s*", "", supplied_label).casefold(),
        ).strip()
        matched_label = (
            normalized_labels.get(normalized_label) if separator else None
        )
        if matched_label is not None:
            if matched_label in values:
                raise WorkdayConnectContractError(
                    f"{label} contains duplicate label '{matched_label}'."
                )
            values[matched_label] = supplied_value.strip()
            current_label = matched_label
            continue
        if current_label in multiline_labels:
            values[current_label] = "\n".join(
                value for value in (values[current_label], line) if value
            )
            continue
        raise WorkdayConnectContractError(
            f"{label} line {line_number} does not use a recognized label."
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
    text = str(value or "").strip()
    if not text:
        raise WorkdayConnectContractError(f"{label} is required.")
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        pass

    without_ordinals = re.sub(
        r"(?<=\d)(st|nd|rd|th)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    named_patterns = (
        re.compile(
            r"^(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),?\s+"
            r"(?P<year>\d{4})\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+),?\s+"
            r"(?P<year>\d{4})\b",
            re.IGNORECASE,
        ),
    )
    for pattern in named_patterns:
        match = pattern.match(without_ordinals)
        if match is None:
            continue
        month_text = match.group("month")
        month = None
        for month_format in ("%B", "%b"):
            try:
                month = datetime.strptime(
                    month_text,
                    month_format,
                ).month
                break
            except ValueError:
                continue
        if month is None:
            continue
        try:
            return datetime(
                int(match.group("year")),
                month,
                int(match.group("day")),
            ).date().isoformat()
        except ValueError:
            break

    numeric = re.match(
        r"^(?P<first>\d{1,4})(?P<separator>[./-])"
        r"(?P<second>\d{1,2})(?P=separator)(?P<third>\d{1,4})\b",
        text,
    )
    if numeric is not None:
        first = int(numeric.group("first"))
        second = int(numeric.group("second"))
        third = int(numeric.group("third"))
        if len(numeric.group("first")) == 4:
            candidates = ((first, second, third),)
        elif len(numeric.group("third")) == 4:
            candidates = (
                (third, first, second),
                (third, second, first),
            )
        else:
            candidates = ()
        valid_dates = []
        for year, month, day in candidates:
            try:
                valid_dates.append(datetime(year, month, day).date())
            except ValueError:
                continue
        unique_dates = {candidate.isoformat() for candidate in valid_dates}
        if len(unique_dates) == 1:
            return unique_dates.pop()
        if len(unique_dates) > 1:
            return numeric.group(0)

    raise WorkdayConnectContractError(
        f"{label} must be a recognizable calendar date. A time is optional "
        "and is ignored."
    )
