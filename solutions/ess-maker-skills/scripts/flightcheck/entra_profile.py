# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Aggregate standard Entra attribute presence without retaining profile values."""

from __future__ import annotations

from time import monotonic

from .graph_client import GraphClient


ATTRIBUTES = (
    "usageLocation", "preferredLanguage", "country", "officeLocation",
    "jobTitle", "department", "employeeType", "employeeId", "employeeHireDate",
)
SCOPES = {
    "me": ["https://graph.microsoft.com/User.Read"],
    "tenant": ["https://graph.microsoft.com/User.Read.All"],
}
SAMPLE_LIMIT = 10_000
TIME_BUDGET_SECONDS = 30


def permission_unavailable_report() -> dict:
    return {
        "status": "Warning",
        "scope": "tenant",
        "coverageVerified": False,
        "reason": "permission_unavailable",
        "requiredPermission": "User.Read.All",
        "message": (
            "Not checked: Graph read permission is unavailable for this run. "
            "Tenant coverage requires existing admin-consented User.Read.All; no coverage was calculated."
        ),
    }


def check_attributes(client: GraphClient, scope: str, attributes: list[str]) -> dict:
    if scope not in SCOPES or not attributes or any(name not in ATTRIBUTES for name in attributes):
        raise ValueError("Choose me/tenant scope and supported standard attributes.")
    started = monotonic()
    attributes = list(dict.fromkeys(attributes))
    selected = ["id", *attributes]
    complete = True
    if scope == "me":
        users = [client.get("/me", params={"$select": ",".join(selected)})]
    else:
        collection = client.get_bounded_collection(
            "/users",
            params={
                "$select": ",".join([*selected, "userType"]),
                "$filter": "userType eq 'Member'",
                "$top": "999",
            },
            limit=SAMPLE_LIMIT,
            time_budget=TIME_BUDGET_SECONDS,
        )
        users, complete = collection.items, collection.complete
    if not users:
        raise ValueError("No member users were returned; coverage cannot be calculated.")
    counts = {name: {"available": 0, "empty": 0, "notReturned": 0} for name in attributes}
    seen = set()
    for user in users:
        if scope == "tenant" and monotonic() - started >= TIME_BUDGET_SECONDS:
            raise TimeoutError("The 30-second coverage budget expired; no partial coverage is reported.")
        if not isinstance(user, dict) or not isinstance(user.get("id"), str) or not user["id"].strip():
            raise ValueError("Graph returned a profile without a valid id.")
        identity = user["id"].casefold()
        if identity in seen:
            raise ValueError("Graph returned duplicate users; coverage was not calculated.")
        seen.add(identity)
        if scope == "tenant" and user.get("userType") != "Member":
            raise ValueError("Graph returned a user outside the requested Member population.")
        for name in attributes:
            if name not in user:
                counts[name]["notReturned"] += 1
                continue
            value = user[name]
            if value is not None and not isinstance(value, str):
                raise ValueError(f"Graph returned an invalid type for {name}.")
            counts[name]["available" if value is not None and value.strip() else "empty"] += 1
    results = []
    for name, count in counts.items():
        percent = count["available"] * 100 / len(users)
        results.append({
            "attribute": name,
            **count,
            "coveragePercent": round(percent, 2),
            "status": "Passed" if percent >= 95 and count["notReturned"] == 0 else "Warning",
        })
    if scope == "tenant" and monotonic() - started >= TIME_BUDGET_SECONDS:
        raise TimeoutError("The 30-second coverage budget expired; no partial coverage is reported.")
    is_sample = scope == "tenant" and not complete
    label = "Profile coverage" if scope == "me" else "Sample coverage" if is_sample else "Tenant coverage"
    return {
        "status": "Warning" if any(row["status"] == "Warning" for row in results) else "Passed",
        "coverageVerified": True,
        "scope": scope,
        "population": "signed-in user" if scope == "me" else "Member users, including disabled and service accounts",
        "usersChecked": len(users),
        "populationComplete": complete,
        "isSample": is_sample,
        "coverageLabel": f"{label} ({len(users):,} accounts checked)",
        "sampleLimit": SAMPLE_LIMIT if scope == "tenant" else None,
        "timeBudgetSeconds": TIME_BUDGET_SECONDS if scope == "tenant" else None,
        "thresholdPercent": 95,
        "results": results,
        "hrCountryComparison": {
            "status": "NotApplicable",
            "reason": "No HR country source is configured in this Entra-only checker.",
        },
        "limitations": [
            "Attribute presence does not establish correctness or availability through People/Sydney.",
            "Manager/direct-report relationships are not scalar attributes and are not checked.",
            "usageLocation is a licensing location, not a verified HR work country.",
            *(
                ["This bounded sample follows Graph page order; it is not random or a tenant-wide estimate."]
                if is_sample else []
            ),
        ],
    }
