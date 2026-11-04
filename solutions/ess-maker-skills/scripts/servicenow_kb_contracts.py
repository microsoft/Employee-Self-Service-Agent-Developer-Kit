# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Non-secret configuration and evidence contracts for guided Knowledge setup."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from workday_connect_workbook import (
    read_administrator_workbook,
    write_administrator_workbook,
)

DOC_BASE = "https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/"
ADMIN_DOC = DOC_BASE + "servicenow-knowledge-admin-setup"
DEPLOY_DOC = DOC_BASE + "servicenow-knowledge-deployment"
SCRIPTS_DOC = DOC_BASE + "servicenow-knowledge-setup-scripts"
CONNECTOR_APP_ID = "933838e2-bec1-440f-a634-9363c82e5b6d"
QUERY_RE = re.compile(
    r"active=true\^workflow_state=published"
    r"(?:\^kb_knowledge_base(?:=[a-f0-9]{32}|IN[a-f0-9]{32}(?:,[a-f0-9]{32})*))?"
)
SECRET_RE = re.compile(
    r"-----BEGIN|(?:password|client_secret|access_token|refresh_token|"
    r"authorization|cookie)\s*[:=]|eyJ[\w-]+\.[\w-]+\.[\w-]+",
    re.IGNORECASE,
)


class KnowledgeConnectError(ValueError):
    """An input or evidence contract could not be satisfied."""


def text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 2048
        or any(ord(character) < 32 for character in value)
        or SECRET_RE.search(value)
    ):
        raise KnowledgeConnectError(f"{label}: supply a non-secret, single-line value.")
    return value.strip()


def guid(value: Any, label: str) -> str:
    value = text(value, label)
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise KnowledgeConnectError(f"{label}: supply a GUID.") from exc
    if parsed.int == 0:
        raise KnowledgeConnectError(f"{label}: an empty GUID is not valid.")
    return str(parsed)


def https_url(value: Any, label: str) -> str:
    value = text(value, label)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or any(
            not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", part)
            for part in parsed.hostname.split(".")
        )
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise KnowledgeConnectError(
            f"{label}: supply an HTTPS origin without credentials."
        )
    try:
        parsed.port
    except ValueError as exc:
        raise KnowledgeConnectError(f"{label}: invalid port.") from exc
    return value.rstrip("/")


def content_query(value: Any) -> str:
    value = text(value, "Content query")
    if not QUERY_RE.fullmatch(value):
        raise KnowledgeConnectError(
            "Content query: use active=true^workflow_state=published, optionally "
            "followed by ^kb_knowledge_base=<sys_id> or ^kb_knowledge_baseIN<sys_ids>."
        )
    return value


def target_reference(scope: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(scope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


PROPERTY_ACCESS_UNRESOLVED = {
    "unreadable",
    "unverified",
    "deferred-to-admin",
    "proceed-without-access",
}

# These prerequisites are defined once; both flows consume the same contract.
COMMON_FIELDS = {
    "Service principal object ID": (
        "Microsoft Entra enterprise applications",
        "Record the tenant-local object ID for Microsoft's connector application "
        f"{CONNECTOR_APP_ID}; not its application ID or ServiceNow sys_id.",
        "11111111-2222-4333-8444-555555555555",
    ),
    "Assessment date": (
        "ServiceNow knowledge/security owner",
        "Record the date of the scope-specific permission assessment.",
        "2026-11-02",
    ),
    "Scope assessment": (
        "ServiceNow User Criteria and Knowledge administration",
        "Confirm all included KB/article read, deny and contributor paths, custom "
        "dependencies and scopes were assessed. A global advanced=true result is "
        "only a discovery flag. Choose confirmed only for the stated permission flow.",
        "confirmed",
    ),
    "Federated Auth": (
        "ServiceNow > System OAuth > Application Registry",
        "Confirm saved provider, metadata tenant, useraccount scope, matched machine "
        "user and the connector's Federated Auth selection. For a new draft, "
        "use Custom setup > Authorize and confirm its actual "
        "success before Create. Pause on failure or an unavailable action. Do not "
        "infer sample-fetch success. Verify ingestion after Create. Reuse healthy "
        "existing connections without recreating them.",
        "confirmed",
    ),
    "Common table reads": (
        "ServiceNow Access Analyzer and supported permission checks",
        "Confirm actual crawler reads of KBs/articles, criteria relationships, "
        "users/roles/groups, templates and included associated content. "
        "A 200 response with missing rows/fields is not a pass. Do not add blanket ACLs.",
        "confirmed",
    ),
    "Permission property reads": (
        "ServiceNow > System Properties",
        "Check crawler reads of name and value for both permission-policy properties. "
        "Record confirmed for verified reads, unreadable for reported blocked access "
        "or unverified for an inconclusive check. For unresolved access, explain the "
        "Microsoft warning, refer to the ServiceNow administrator and ask whether to "
        "continue. Record proceed-without-access only after an explicit Yes; No pauses. "
        "Preserve policy values.",
        "confirmed, unreadable, unverified or proceed-without-access",
    ),
    "Identity mapping": (
        "ServiceNow users and connector identity mapping",
        "Confirm representative ServiceNow emails resolve to intended Entra UPN/Mail, "
        "or the approved custom mapping. Do not return identities or membership exports.",
        "confirmed",
    ),
    "HR scoped reads": (
        "ServiceNow HR knowledge/security owner",
        "If HRSD-scoped content is included, confirm the applicable content-reader "
        "role and scoped reads. Record not-applicable only after the administrator "
        "reviews scope and confirms no HRSD content is included. Do not infer this "
        "from the target agent being IT or an unanswered maker question.",
        "confirmed or not-applicable",
    ),
}
FLOW_FIELDS = {
    "simple": {
        "Simple attribute reads": (
            "ServiceNow Access Analyzer",
            "Confirm crawler reads on sys_user_grmember, cmn_location, cmn_department "
            "and core_company. The shared 16-table script alone does not prove these reads.",
            "confirmed",
        ),
    },
    "advanced": {
        "Advanced namespace": (
            "ServiceNow > System Web Services > Scripted REST APIs",
            "Record the namespace of the approved microsoft_copilot API, used by "
            "POST /user_criteria_v2. Do not return an endpoint token.",
            "1234567",
        ),
        "Advanced API security": (
            "ServiceNow > Scripted REST APIs > POST user_criteria_v2",
            "Confirm the protected V2 API/resource, authentication and ACL enforcement, "
            "and approved caller access. Review results for per-user errors as well "
            "as HTTP status. Do not install optional user_changes/auditing for this MVP.",
            "confirmed",
        ),
    },
}
M365_FIELDS = {
    "Connection name": (
        "Microsoft 365 admin center > Copilot > Connectors > connection details",
        "Record the actual connection display name used to select this source in "
        "ESS Knowledge. Do not request a technical Connection ID.",
        "ServiceNow Knowledge - HR",
    ),
    "Connector configuration": (
        "Microsoft 365 admin center > Copilot > Connectors",
        "Confirm this is the ServiceNow Knowledge gallery connection for the stated "
        "instance, scope, permission flow and Federated Auth. Advanced also needs "
        "the returned namespace. Do not create a custom Graph connection as a substitute.",
        "confirmed",
    ),
    "Source permissions": (
        "Connector > Custom setup > Users",
        "Confirm Only people with access to this data source; never Everyone "
        "as a permissions workaround.",
        "confirmed",
    ),
    "Audience": (
        "Connector rollout settings",
        "Explain organization-wide (limited-audience toggle off) and selected-users "
        "(toggle on); ask which applies, without assuming a default. Reuse an explicit "
        "choice for this deployment. Both preserve ServiceNow source permissions.",
        "organization-wide or selected-users",
    ),
    "Connection ready": (
        "Connector details, statistics and errors",
        "After Create, confirm actual connector operation for the exact connection: "
        "review authentication/connectivity errors, completed relevant content/identity "
        "processing and expected ingested records. Ready or creation alone is not proof.",
        "confirmed",
    ),
    "Schedules reviewed": (
        "Connector > Sync",
        "Confirm the actual content/full/identity schedules meet approved expectations. "
        "Record deviations with the operations owner; schedules are not revocation SLAs.",
        "confirmed",
    ),
}


def fields_for(
    owner: str, scope: dict[str, Any], *, legacy_connection: bool = False
) -> dict[str, tuple[str, str, str]]:
    if owner == "servicenow":
        return {**COMMON_FIELDS, **FLOW_FIELDS[scope["flow"]]}
    if owner == "m365":
        if legacy_connection:
            return {
                "Connection ID" if label == "Connection name" else label: details
                for label, details in M365_FIELDS.items()
            }
        return M365_FIELDS
    raise KnowledgeConnectError("Choose the ServiceNow or Microsoft 365 configuration.")


def configuration_steps(scope: dict[str, Any]) -> list[dict[str, Any]]:
    definitions = [
        ("scope-assessment", "servicenow", "Scope assessment", False, False),
        ("assessment-date", "servicenow", "Assessment date", False, False),
        (
            "service-principal",
            "servicenow",
            "Service principal object ID",
            False,
            False,
        ),
        ("oidc-provider", "servicenow", "Federated Auth", True, True),
        ("integration-user", "servicenow", "Federated Auth", True, True),
        ("integration-roles", "servicenow", "Common table reads", True, True),
        ("permission-setup", "servicenow", "Common table reads", True, True),
        ("identity-mapping", "servicenow", "Identity mapping", False, False),
    ]
    if scope["flow"] == "advanced":
        definitions.extend(
            [
                ("advanced-api", "servicenow", "Advanced API security", True, True),
                (
                    "advanced-namespace",
                    "servicenow",
                    "Advanced namespace",
                    False,
                    False,
                ),
            ]
        )
    definitions.extend(
        [
            ("table-reads", "servicenow", "Common table reads", False, True),
            ("property-reads", "servicenow", "Permission property reads", False, True),
            ("hr-reads", "servicenow", "HR scoped reads", False, True),
        ]
    )
    if scope["flow"] == "simple":
        definitions.append(
            ("simple-reads", "servicenow", "Simple attribute reads", False, True)
        )
    else:
        definitions.append(
            ("advanced-security", "servicenow", "Advanced API security", False, True)
        )
    definitions.extend(
        [
            ("federated-auth", "servicenow", "Federated Auth", False, False),
            ("connector-config", "m365", "Connector configuration", False, True),
            ("source-permissions", "m365", "Source permissions", False, True),
            ("audience", "m365", "Audience", False, True),
            ("schedules", "m365", "Schedules reviewed", False, True),
            ("connection-name", "m365", "Connection name", False, True),
            ("connection-ready", "m365", "Connection ready", True, False),
            ("test-article", "validation", "articleNumber", True, False),
            ("test-kb", "validation", "knowledgeBaseId", True, False),
            ("article-indexed", "validation", "articleIndexed", True, False),
            ("allowed-native", "validation", "allowedNative", True, False),
            ("allowed-indexed", "validation", "allowedIndexed", True, False),
            ("denied-native", "validation", "deniedNative", True, False),
            ("denied-indexed", "validation", "deniedIndexed", True, False),
            ("source-attached", "validation", "sourceAttached", True, True),
            ("source-isolated", "validation", "exactSourceIsolated", True, True),
            ("answer-citation", "validation", "answerWithCitation", True, False),
            ("observation-time", "validation", "observedAt", True, False),
        ]
    )
    return [
        {
            "id": step_id,
            "owner": owner,
            "field": field,
            "checkpoint": checkpoint,
            "requiresApproval": approval,
            "guide": f"configuration.md#{step_id}",
        }
        for step_id, owner, field, checkpoint, approval in definitions
    ]


def validate_step_answer(
    step: dict[str, Any], value: Any, scope: dict[str, Any]
) -> str:
    if step["id"] == "property-reads" and value == "deferred-to-admin":
        raise KnowledgeConnectError(
            "Check property access first. For unresolved access, show the warning "
            "and record proceed-without-access only after an explicit Yes."
        )
    if step["owner"] != "validation" and not step["checkpoint"]:
        return validate_answer(step["field"], value, scope)
    value = text(value, step["field"])
    if step["owner"] == "validation":
        validate_reader_value(step["field"], value, scope)
    elif value != "confirmed":
        raise KnowledgeConnectError(
            f"{step['id']}: remains unverified; confirm the observed configuration."
        )
    return value


def validate_answer(label: str, value: Any, scope: dict[str, Any]) -> str:
    value = text(value, label)
    if label == "Service principal object ID":
        value = guid(value, label)
        if value == CONNECTOR_APP_ID:
            raise KnowledgeConnectError(
                f"{label}: use the tenant-local object ID, not app ID."
            )
    elif label == "Assessment date":
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise KnowledgeConnectError(f"{label}: use YYYY-MM-DD.") from exc
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise KnowledgeConnectError(f"{label}: use YYYY-MM-DD.")
        if parsed > datetime.now(timezone.utc).date():
            raise KnowledgeConnectError(
                f"{label}: a future assessment is not evidence."
            )
    elif label == "Advanced namespace":
        if not re.fullmatch(r"[A-Za-z0-9_]{1,100}", value):
            raise KnowledgeConnectError(f"{label}: supply the API namespace only.")
    elif label == "Connection ID":
        if not re.fullmatch(r"[A-Za-z0-9]{3,32}", value) or value.startswith(
            "Microsoft"
        ):
            raise KnowledgeConnectError(
                f"{label}: supply a valid external connection ID."
            )
    elif label == "Audience":
        if value not in {"organization-wide", "selected-users"}:
            raise KnowledgeConnectError(
                f"{label}: choose organization-wide or selected-users."
            )
    elif label == "Permission property reads":
        if value not in PROPERTY_ACCESS_UNRESOLVED | {"confirmed"}:
            raise KnowledgeConnectError(
                f"{label}: use confirmed for verified reads, unreadable for blocked "
                "access, unverified for inconclusive checks, or proceed-without-access "
                "only after an explicit Yes to continue."
            )
    elif label == "HR scoped reads" and scope["hrContent"] is not True:
        if value not in {"confirmed", "not-applicable"}:
            raise KnowledgeConnectError(
                f"{label}: confirm reads or verified non-applicability."
            )
    elif label != "Connection name" and value != "confirmed":
        raise KnowledgeConnectError(
            f"{label}: remains unverified; owner confirmation is required."
        )
    return value


def _handoff_context(scope: dict[str, Any]) -> dict[str, str]:
    return {
        "Target reference": target_reference(scope),
        "Instance URL": scope["instance"],
        "Microsoft Entra tenant ID": scope["target"]["tenantId"],
        "Content query": scope["query"],
        "Permission flow": scope["flow"],
        "HRSD content included": (
            "Administrator assessment"
            if scope["hrContent"] is None
            else "yes"
            if scope["hrContent"]
            else "no"
        ),
    }


def write_handoff(path, owner: str, scope: dict[str, Any], answers: dict[str, str]):
    context = _handoff_context(scope)
    instructions = [
        {
            "information": label,
            "portalLocation": "Approved target and scope",
            "instruction": "Do not change this context. Return to the maker if the target changed.",
            "exampleValue": value,
        }
        for label, value in context.items()
    ]
    for label, (location, instruction, example) in fields_for(owner, scope).items():
        instructions.append(
            {
                "information": label,
                "portalLocation": location,
                "instruction": instruction,
                "exampleValue": example,
            }
        )
    return write_administrator_workbook(
        path,
        title=f"ServiceNow Knowledge - {scope['flow']} - {owner} handoff",
        administrator_role="ServiceNow administrator"
        if owner == "servicenow"
        else "Microsoft 365 AI administrator",
        actions=[
            f"Review shared prerequisites and source permissions: {ADMIN_DOC}",
            f"Follow Federated Auth and the selected flow in: {DEPLOY_DOC}",
            f"ServiceNow administrators may review and execute setup scripts: {SCRIPTS_DOC}. "
            "ADK does not execute them. Review the actual version and existing-record "
            "changes; field ACLs are conditional, not a default step.",
            "Existing confirmed values are prefilled to avoid repeating healthy work. "
            "Reconfirm or correct them; fill every remaining answer. Do not send secrets.",
            "Network access is conditional: coordinate with its owner only when blocked.",
        ],
        capture_instructions=instructions,
        answers={**context, **answers},
    )


def read_handoff(path, owner: str, scope: dict[str, Any]) -> dict[str, str]:
    worksheet = read_administrator_workbook(path)
    values: dict[str, str] = {}
    for line in worksheet.splitlines():
        label, separator, value = line.partition(":")
        if not separator or label in values:
            raise KnowledgeConnectError(
                "Workbook has missing or duplicate information labels."
            )
        values[label] = value.strip()
    context = _handoff_context(scope)
    fields = fields_for(owner, scope)
    if owner == "m365" and "Connection ID" in values:
        fields = fields_for(owner, scope, legacy_connection=True)
    expected = set(context) | set(fields)
    if set(values) != expected:
        raise KnowledgeConnectError(
            "Workbook labels are missing, duplicated or unsupported."
        )
    if any(values[label] != value for label, value in context.items()):
        raise KnowledgeConnectError(
            "Workbook belongs to a different target or scope; no evidence accepted."
        )
    return {label: values[label] for label in fields}


DENIED_READER_FIELDS = ("deniedNative", "deniedIndexed")


def validate_reader_value(label: str, value: str, scope: dict[str, Any]) -> None:
    if label == "articleNumber":
        if not re.fullmatch(r"KB[0-9]+", value):
            raise KnowledgeConnectError(
                "articleNumber: supply the tested KB article number."
            )
    elif label == "knowledgeBaseId":
        if not re.fullmatch(r"[a-f0-9]{32}", value):
            raise KnowledgeConnectError("knowledgeBaseId: supply the tested KB sys_id.")
        if "^kb_knowledge_base" in scope["query"]:
            kb_filter = scope["query"].split("^kb_knowledge_base", 1)[1]
            kb_ids = kb_filter[1:] if kb_filter.startswith("=") else kb_filter[2:]
            if value not in kb_ids.split(","):
                raise KnowledgeConnectError(
                    "The tested KB is outside the approved ingestion scope."
                )
    elif label == "observedAt":
        try:
            observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise KnowledgeConnectError(
                "observedAt: supply an ISO-8601 observation timestamp."
            ) from exc
        if observed.tzinfo is None or observed > datetime.now(timezone.utc):
            raise KnowledgeConnectError(
                "observedAt: include a timezone and no future observation."
            )
    elif label in DENIED_READER_FIELDS and value == "skipped":
        return
    elif value != "confirmed":
        raise KnowledgeConnectError(
            f"{label}: the requested case remains unverified or failed."
        )


def validate_acceptance(
    value: dict[str, Any],
    scope: dict[str, Any],
    connection_reference: str | None,
    *,
    legacy_connection: bool = False,
) -> dict[str, str]:
    connection_field = "connectionId" if legacy_connection else "connectionName"
    expected = {
        "targetReference",
        connection_field,
        "articleNumber",
        "knowledgeBaseId",
        "observedAt",
        "sourceAttached",
        "articleIndexed",
        "allowedNative",
        "allowedIndexed",
        "deniedNative",
        "deniedIndexed",
        "answerWithCitation",
        "exactSourceIsolated",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise KnowledgeConnectError(
            "Validation must contain exactly the documented non-secret fields."
        )
    result = {key: text(item, key) for key, item in value.items()}
    if (
        result["targetReference"] != target_reference(scope)
        or result[connection_field] != connection_reference
    ):
        raise KnowledgeConnectError(
            "Validation refers to a different target, scope or connection."
        )
    for key in expected - {"targetReference", connection_field}:
        validate_reader_value(key, result[key], scope)
    if any(result[key] == "skipped" for key in DENIED_READER_FIELDS) and not all(
        result[key] == "skipped" for key in DENIED_READER_FIELDS
    ):
        raise KnowledgeConnectError(
            "Skip the whole denied-reader comparison, not an individual result."
        )
    return result
