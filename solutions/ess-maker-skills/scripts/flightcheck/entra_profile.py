# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Aggregate public Microsoft 365 profile availability without retaining values."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from .graph_client import GraphClient


@dataclass(frozen=True)
class Attribute:
    family: str
    path: tuple[str, ...]


FIELDS = {
    "displayName": Attribute("names", ("displayName",)),
    "userPrincipalName": Attribute("account", ("userPrincipalName",)),
    "emails": Attribute("emails", ("address",)),
    **{
        name: Attribute("positions", ("detail", name))
        for name in ("jobTitle", "employeeType", "employeeId")
    },
    **{
        name: Attribute("positions", ("detail", "company", source))
        for name, source in (
            ("companyName", "displayName"), ("companyCode", "companyCode"),
            ("costCenter", "costCenter"), ("department", "department"),
            ("officeLocation", "officeLocation"),
        )
    },
    "workCountry": Attribute("positions", ("detail", "company", "address", "countryOrRegion")),
}
ATTRIBUTES = tuple(FIELDS)
SCOPES = {
    "me": ["https://graph.microsoft.com/User.Read"],
    "tenant": ["https://graph.microsoft.com/User.Read.All"],
}
SAMPLE_LIMIT = 100
TIME_BUDGET_SECONDS = 30
_MISSING = object()


def permission_unavailable_report() -> dict:
    return {
        "status": "Warning", "scope": "tenant", "coverageVerified": False,
        "apiVersion": "beta", "reason": "permission_unavailable",
        "requiredPermission": "User.Read.All",
        "message": "Not checked: directory or Microsoft 365 profile read access was unavailable; no coverage was calculated.",
    }


def _remaining(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("The coverage budget expired; no partial coverage is reported.")
    return remaining


def _value(row: dict, attribute: Attribute):
    value = row
    for component in attribute.path:
        if value is None:
            return "Empty", None
        if not isinstance(value, dict):
            raise ValueError("Graph returned an invalid nested profile property.")
        if "@odata.nextLink" in value or f"{component}@odata.nextLink" in value:
            return "Unverified", None
        if component not in value:
            return "Not returned", None
        value = value[component]
    if value is None:
        return "Empty", None
    if not isinstance(value, str):
        raise ValueError("Graph returned an invalid text profile property.")
    if not value.strip():
        return "Empty", None
    return "Available", value.strip().casefold()


def _availability(profile: dict, attribute: Attribute) -> str:
    family = profile.get(attribute.family, _MISSING)
    if family is _MISSING or family is None:
        return "Not returned"
    if not isinstance(family, list) or any(not isinstance(item, dict) for item in family):
        raise ValueError("Graph returned an invalid profile section.")
    if "@odata.nextLink" in profile or f"{attribute.family}@odata.nextLink" in profile:
        return "Unverified"
    if attribute.family == "emails":
        values = [_value(row, attribute)[0] for row in family]
        if "Available" in values:
            return "Available"
        if any(state in ("Not returned", "Unverified") for state in values):
            return "Unverified"
        return "Empty"
    if attribute.family == "positions":
        if any(type(position.get("isCurrent")) is not bool for position in family):
            return "Unverified"
        family = [position for position in family if position["isCurrent"]]
    if not family:
        return "Empty"
    values = [_value(row, attribute) for row in family]
    # Do not invent source precedence or silently choose the first current record.
    if all(value == values[0] for value in values):
        return values[0][0]
    return "Unverified"


def check_attributes(
    client: GraphClient, scope: str, attributes: list[str], *,
    time_budget: float = TIME_BUDGET_SECONDS,
) -> dict:
    if scope not in SCOPES or not attributes or any(name not in FIELDS for name in attributes):
        raise ValueError("Choose me/tenant scope and supported Microsoft 365 profile attributes.")
    deadline = monotonic() + time_budget
    attributes = list(dict.fromkeys(attributes))
    complete = True
    if scope == "me":
        profiles = [client.get_bounded_profile(params={}, time_budget=_remaining(deadline))]
    else:
        collection = client.get_bounded_collection(
            "/users", params={"$select": "id,userType", "$filter": "userType eq 'Member'", "$top": str(SAMPLE_LIMIT)},
            limit=SAMPLE_LIMIT, time_budget=_remaining(deadline),
        )
        identities = []
        for user in collection.items:
            _remaining(deadline)
            if not isinstance(user, dict) or user.get("userType") != "Member":
                raise ValueError("Graph returned a user outside the requested Member population.")
            if not isinstance(user.get("id"), str):
                raise ValueError("Graph returned a profile identity without a valid id.")
            identities.append(str(UUID(user["id"])))
        if not identities or len(identities) != len(set(identities)):
            raise ValueError("Graph returned an empty or duplicate user population; coverage was not calculated.")
        # Some advertised beta sections reject $select on live tenants. The
        # default profile read succeeds and keeps omissions explicitly unknown.
        profiles = client.get_bounded_profiles(identities, time_budget=_remaining(deadline))
        if len(profiles) != len(identities):
            raise ValueError("Graph returned incomplete profile coverage.")
        complete = collection.complete
    counts = {name: {"available": 0, "empty": 0, "notReturned": 0, "unverified": 0} for name in attributes}
    states = {"Available": "available", "Empty": "empty", "Not returned": "notReturned", "Unverified": "unverified"}
    for profile in profiles:
        _remaining(deadline)
        if not isinstance(profile, dict) or not profile or "error" in profile:
            raise ValueError("Graph returned an invalid profile resource.")
        for name in attributes:
            counts[name][states[_availability(profile, FIELDS[name])]] += 1
    results = []
    for name, count in counts.items():
        verified = not (count["notReturned"] or count["unverified"])
        percent = count["available"] * 100 / len(profiles) if verified else None
        if scope == "me":
            state = next(label for label, key in states.items() if count[key])
            results.append({"attribute": name, "availability": state})
        else:
            results.append({
                "attribute": name, **count,
                "coveragePercent": round(percent, 2) if percent is not None else None,
                "status": "Passed" if percent is not None and percent >= 95 else "Warning",
            })
    _remaining(deadline)
    passed = all(row.get("status") == "Passed" or row.get("availability") == "Available" for row in results)
    report = {
        "status": "Passed" if passed else "Warning", "scope": scope, "apiVersion": "beta",
        "usersChecked": len(profiles), "results": results,
        "coverageVerified": scope == "tenant" and all(row["coveragePercent"] is not None for row in results),
        "limitations": [
            "Returned profile availability does not prove which values an ESS search or answer will include.",
            "Omitted, truncated and conflicting source records are unverified, not empty.",
            "Profile enrichment opportunities are not deployment requirements.",
        ],
    }
    if scope == "me":
        report.update(profileVerified=True, message="Own profile only. Tenant-wide attribute coverage was not calculated.")
    else:
        report.update(
            population="Member users, including disabled and service accounts",
            populationComplete=complete, isSample=not complete, sampleLimit=SAMPLE_LIMIT,
            timeBudgetSeconds=TIME_BUDGET_SECONDS, thresholdPercent=95,
            coverageLabel=f"{'Tenant coverage' if complete else 'Sample coverage'} ({len(profiles):,} profiles checked)",
        )
    return report


def check_own_profile(client: GraphClient, *, time_budget: float) -> dict:
    report = check_attributes(client, "me", list(ATTRIBUTES), time_budget=time_budget)
    report.update(
        status="Warning", reason="permission_unavailable",
        message=(
            "Own profile only. Tenant-wide directory or profile-read access was unavailable for this run. "
            "Only your signed-in Microsoft 365 profile was checked; tenant-wide attribute coverage was not calculated."
        ),
    )
    return report
