# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Real-model evaluation harness with synthetic curator files and commands."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
from typing import Any
from urllib.parse import urlparse

from jsonschema import ValidationError, validate


REPO_ROOT = Path(__file__).parents[3]
SOLUTION_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills"
PROMPT_PATH = SOLUTION_ROOT / ".github" / "prompts" / "evaluate.prompt.md"
DISPATCHER_PATH = SOLUTION_ROOT / "src" / "skills" / "evaluations" / "dispatcher" / "SKILL.md"
WRAPPER_PATH = SOLUTION_ROOT / "src" / "skills" / "evaluations" / "curate" / "SKILL.md"
REAL_CURATOR_PATH = (
    SOLUTION_ROOT / "src" / "skills" / "evaluations" / "curate" / "curator" / "curate-evals.md"
)
VALIDATOR_SKILL_PATH = (
    SOLUTION_ROOT / "src" / "skills" / "evaluations" / "validate" / "SKILL.md"
)
QUALITY_FIX_FLOW_FILE = (
    SOLUTION_ROOT / "src" / "skills" / "evaluations" / "quality-fix-flow.md"
)
UPDATE_SKILL_FILE = (
    SOLUTION_ROOT / "src" / "skills" / "evaluations" / "update" / "SKILL.md"
)

SYNTHETIC_REPO_ROOT = REPO_ROOT / ".synthetic-eval-repo"
SYNTHETIC_SOLUTION_ROOT = SYNTHETIC_REPO_ROOT / "solutions" / "ess-maker-skills"
EVALUATE_PROMPT_PATH = ".github/prompts/evaluate.prompt.md"
DISPATCHER_SKILL_PATH = "src/skills/evaluations/dispatcher/SKILL.md"
WRAPPER_SKILL_PATH = "src/skills/evaluations/curate/SKILL.md"
CURATOR_SKILL_PATH = "src/skills/evaluations/curate/curator/curate-evals.md"
STRUCTURAL_VALIDATOR_PATH = "src/skills/evaluations/curate/curator/check_eval_artifacts.py"
KNOWLEDGE_PATH = "fixtures/knowledge/leave-policy.md"
AGENT_INSTRUCTIONS_PATH = "fixtures/agent/instructions.md"
MAKER_VALIDATOR_SKILL_PATH = "src/skills/evaluations/validate/SKILL.md"
QUALITY_FIX_FLOW_PATH = "src/skills/evaluations/quality-fix-flow.md"
UPDATE_SKILL_PATH = "src/skills/evaluations/update/SKILL.md"
SYNTHETIC_SOLUTION_PATH_KEYS = (
    EVALUATE_PROMPT_PATH,
    DISPATCHER_SKILL_PATH,
    WRAPPER_SKILL_PATH,
    CURATOR_SKILL_PATH,
    STRUCTURAL_VALIDATOR_PATH,
    KNOWLEDGE_PATH,
    AGENT_INSTRUCTIONS_PATH,
    MAKER_VALIDATOR_SKILL_PATH,
    QUALITY_FIX_FLOW_PATH,
    UPDATE_SKILL_PATH,
    "scripts/evaluate_evals.py",
    "scripts/push.py",
)
DEFAULT_MODEL = "gpt-5.4"
MAX_CALLS = 40
TURN_TIMEOUT = 120

KNOWLEDGE_TEXT = """# Leave policy

## Annual leave

Employees receive 20 days of annual leave each calendar year. Up to 5 unused
days carry into the next calendar year and must be used by March 31.

## Sick leave

Employees should notify their manager before the start of the workday when
they need sick leave. A medical certificate is required after three
consecutive sick days.
"""

AGENT_INSTRUCTIONS_TEXT = """# HR policy assistant

Answer only questions about the supplied HR policies. Use a concise,
professional, and empathetic tone. If the supplied policy does not contain
the answer, say that the information is unavailable and offer to connect the
employee with HR. Do not provide legal advice or invent policy details.
"""

SYNTHETIC_KB_ARTICLES: dict[str, dict[str, str]] = {
    "kb0001": {
        "title": "Password reset policy",
        "body": (
            "Employees reset passwords via the self-service portal; lockouts "
            "clear after 30 minutes."
        ),
    },
    "kb0002": {
        "title": "VPN access request",
        "body": (
            "Request VPN access through the IT catalog; approval is by the "
            "employee's manager."
        ),
    },
    "kb0003": {
        "title": "Multi-factor authentication enrollment",
        "body": (
            "Enroll in multi-factor authentication from the security settings "
            "page; the network team can reset a lost authenticator device."
        ),
    },
    "kb0004": {
        "title": "Paid time off accrual",
        "body": (
            "PTO accrues monthly and unused PTO rolls over up to 40 hours into "
            "the next year."
        ),
    },
    "kb0005": {
        "title": "Requesting extended leave",
        "body": (
            "Submit a leave request at least two weeks in advance; HR reviews "
            "and approves extended leave case by case."
        ),
    },
}

# Deliberately has no matching articles above, so a search for this subject
# returns zero results.
SYNTHETIC_KB_EMPTY_SUBJECT = "relocation reimbursement"
SERVICENOW_KB_FIELDS = (
    "sys_id,number,short_description,text,kb_knowledge_base,workflow_state"
)
SERVICENOW_CONNECTION_ID = "ServiceNowKB63"
SERVICENOW_INSTANCE_URL = "https://fake.service-now.com"
DEFAULT_SERVICENOW_TARGETED_HITS = (
    {
        "title": "Parental leave policy",
        "sys_id": "sys-parental-leave",
        "sourceUrl": f"{SERVICENOW_INSTANCE_URL}/kb?id=sys-parental-leave",
    },
    {
        "title": "PTO rollover policy",
        "number": "KB009876",
        "sourceUrl": f"{SERVICENOW_INSTANCE_URL}/kb?number=KB009876",
    },
    {
        "title": "Unmapped policy overview",
        "sourceUrl": f"{SERVICENOW_INSTANCE_URL}/kb?article=overview",
    },
)
SERVICENOW_RECORDS = {
    "sys-parental-leave": {
        "sys_id": "sys-parental-leave",
        "number": "KB001234",
        "short_description": "Parental leave policy",
        "text": "Eligible employees receive twelve weeks of parental leave.",
        "kb_knowledge_base": "HR",
        "workflow_state": "published",
    },
    "KB009876": {
        "sys_id": "sys-pto-rollover",
        "number": "KB009876",
        "short_description": "PTO rollover policy",
        "text": "Unused PTO rolls over up to forty hours.",
        "kb_knowledge_base": "HR",
        "workflow_state": "published",
    },
    "sys-sick-leave": {
        "sys_id": "sys-sick-leave",
        "number": "KB004444",
        "short_description": "Sick leave policy",
        "text": "Notify your manager before the start of the workday.",
        "kb_knowledge_base": "HR",
        "workflow_state": "published",
    },
}


@dataclass(frozen=True)
class ServiceNowLiveScenario:
    classification: str = "servicenow"
    graph_failure: str | None = None
    mcp_failure: str | None = None
    maker_confirmed: bool = True
    targeted_hits: tuple[dict[str, str], ...] | None = None
    fetch_failures: frozenset[str] = frozenset()
    returned_identifier_overrides: dict[str, dict[str, str]] = field(
        default_factory=dict
    )

_SEARCH_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "is", "are",
    "my", "how", "do", "i", "with", "what",
}


def _search_tokens(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"\w+", text.lower())
        if word not in _SEARCH_STOPWORDS and len(word) >= 3
    }


def _normalized_url_hostname(value: str) -> str | None:
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not hostname:
        return None
    return hostname.lower().rstrip(".")


def _is_servicenow_hostname(hostname: str) -> bool:
    return re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.service-now\.com",
        hostname,
    ) is not None


@dataclass(frozen=True)
class ToolContract:
    name: str
    description: str
    parameters: dict[str, Any]


def tool_contracts() -> list[ToolContract]:
    return [
        ToolContract(
            "read_file",
            (
                "Read one complete synthetic workspace file. Available files include "
                "the curator contract paths, sample knowledge, sample agent instructions, "
                "and Maker Kit validator skill."
            ),
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        ToolContract(
            "write_file",
            (
                "Record a requested synthetic workspace file write. Only paths beneath "
                "workspace/evaluations are accepted; no host file is changed."
            ),
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        ),
        ToolContract(
            "run_command",
            (
                "Record and simulate only the structural validator, Maker Kit "
                "evaluation validator, and scoped push commands. No command, network "
                "request, tenant operation, or push is executed."
            ),
            {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        ),
        ToolContract(
            "search",
            (
                "Search the synthetic connected knowledge base for a query and "
                "return a ranked list of matching article summaries."
            ),
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        ToolContract(
            "fetch",
            (
                "Fetch the full content of one synthetic knowledge base article "
                "by id."
            ),
            {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        ),
        ToolContract(
            "graph_external_item_search",
            (
                "Search one explicitly scoped synthetic Graph external connection. "
                "Records content source, query, limit, ordering, and orchestration phase."
            ),
            {
                "type": "object",
                "properties": {
                    "contentSources": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "orderBy": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["classification", "broad", "targeted"],
                    },
                },
                "required": [
                    "contentSources",
                    "query",
                    "limit",
                    "orderBy",
                    "phase",
                ],
                "additionalProperties": False,
            },
        ),
        ToolContract(
            "get_record",
            "Fetch one synthetic ServiceNow knowledge article by sys_id.",
            {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "sys_id": {"type": "string"},
                    "fields": {"type": "string"},
                },
                "required": ["table", "sys_id", "fields"],
                "additionalProperties": False,
            },
        ),
        ToolContract(
            "query_table",
            "Fetch synthetic ServiceNow knowledge articles by bounded numberIN query.",
            {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "query": {"type": "string"},
                    "fields": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["table", "query", "fields", "limit"],
                "additionalProperties": False,
            },
        ),
    ]


@dataclass
class RecordedCall:
    turn: int
    name: str
    arguments: dict[str, Any]
    result: Any
    failed: bool = False
    kind: str = "other"
    validator_type: str | None = None


@dataclass
class FakeEvaluationWorkspace:
    calls: list[RecordedCall] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    turn: int = 0
    limit_exceeded: bool = False
    contract_by_name: dict[str, ToolContract] = field(default_factory=dict)
    _servicenow_scenario: ServiceNowLiveScenario | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.files.update(
            {
                EVALUATE_PROMPT_PATH: PROMPT_PATH.read_text(encoding="utf-8"),
                DISPATCHER_SKILL_PATH: DISPATCHER_PATH.read_text(encoding="utf-8"),
                WRAPPER_SKILL_PATH: WRAPPER_PATH.read_text(encoding="utf-8"),
                CURATOR_SKILL_PATH: REAL_CURATOR_PATH.read_text(encoding="utf-8"),
                KNOWLEDGE_PATH: KNOWLEDGE_TEXT,
                AGENT_INSTRUCTIONS_PATH: AGENT_INSTRUCTIONS_TEXT,
                MAKER_VALIDATOR_SKILL_PATH: VALIDATOR_SKILL_PATH.read_text(
                    encoding="utf-8"
                ),
                QUALITY_FIX_FLOW_PATH: QUALITY_FIX_FLOW_FILE.read_text(encoding="utf-8"),
                UPDATE_SKILL_PATH: UPDATE_SKILL_FILE.read_text(encoding="utf-8"),
            }
        )

    def invoke(self, name: str, arguments: dict[str, Any]) -> RecordedCall:
        if len(self.calls) >= MAX_CALLS:
            self.limit_exceeded = True
            raise RuntimeError(f"Evaluation exceeded the {MAX_CALLS}-tool-call limit.")
        try:
            validate(arguments, self.contract_by_name[name].parameters)
        except (KeyError, ValidationError):
            return self._record(
                name, arguments, {"error": "Invalid tool invocation."}, failed=True
            )

        if name == "read_file":
            path = self._normalize(arguments["path"])
            file_key = self._matching_file_key(path)
            if file_key is None:
                return self._record(
                    name, arguments, {"error": "Synthetic file not found."}, failed=True
                )
            return self._record(name, arguments, self.files[file_key], kind="read")

        if name == "write_file":
            path = self._normalize(arguments["path"])
            if (
                ".." in PurePosixPath(path).parts
                or not path.startswith("workspace/evaluations/")
                or path.endswith("/")
            ):
                return self._record(
                    name,
                    arguments,
                    {"error": "Writes are restricted to workspace/evaluations."},
                    failed=True,
                    kind="write",
                )
            self.files[path] = arguments["content"]
            return self._record(
                name, arguments, {"path": path, "written": True}, kind="write"
            )

        if name == "search":
            query = arguments["query"]
            query_tokens = _search_tokens(query)
            results = []
            if query_tokens:
                for article_id, article in SYNTHETIC_KB_ARTICLES.items():
                    article_tokens = _search_tokens(
                        f"{article['title']} {article['body']}"
                    )
                    if query_tokens & article_tokens:
                        results.append(
                            {
                                "id": article_id,
                                "title": article["title"],
                                "snippet": article["body"][:80],
                            }
                        )
            return self._record(name, arguments, results, kind="search")

        if name == "fetch":
            article_id = arguments["id"]
            article = SYNTHETIC_KB_ARTICLES.get(article_id)
            if article is None:
                return self._record(
                    name,
                    arguments,
                    {"error": "Synthetic file not found."},
                    failed=True,
                    kind="fetch",
                )
            return self._record(
                name,
                arguments,
                {"title": article["title"], "body": article["body"]},
                kind="fetch",
            )

        if name == "graph_external_item_search":
            content_sources = arguments["contentSources"]
            if (
                len(content_sources) != 1
                or content_sources[0]
                != f"/external/connections/{SERVICENOW_CONNECTION_ID}"
                or not arguments["query"].strip()
                or arguments["limit"] <= 0
                or not arguments["orderBy"]
            ):
                return self._record(
                    name,
                    arguments,
                    {"error": "Graph search requires one bounded connection scope."},
                    failed=True,
                    kind="graph_search",
                )
            scenario = self._servicenow_scenario
            if scenario is not None and scenario.graph_failure is not None:
                return self._record(
                    name,
                    arguments,
                    {"error": f"Graph {scenario.graph_failure} failure."},
                    failed=True,
                    kind="graph_search",
                )
            if arguments["phase"] == "targeted":
                results = list(
                    scenario.targeted_hits
                    if scenario is not None and scenario.targeted_hits is not None
                    else DEFAULT_SERVICENOW_TARGETED_HITS
                )
            else:
                results = [
                    {"title": "Leave policies"},
                    {"title": "Paid time off"},
                ][: arguments["limit"]]
            return self._record(
                name,
                arguments,
                {
                    "connection": SERVICENOW_CONNECTION_ID,
                    "query": arguments["query"],
                    "limit": arguments["limit"],
                    "orderBy": arguments["orderBy"],
                    "hits": results,
                },
                kind="graph_search",
            )

        if name == "get_record":
            error = self._servicenow_contract_error(arguments)
            if error is not None or not arguments["sys_id"].strip():
                return self._record(
                    name,
                    arguments,
                    {"error": error or "sys_id must not be blank."},
                    failed=True,
                    kind="servicenow_fetch",
                )
            return self._servicenow_record_result(
                name, arguments, arguments["sys_id"]
            )

        if name == "query_table":
            error = self._servicenow_contract_error(arguments)
            query = arguments["query"].strip()
            number_match = re.fullmatch(r"numberIN([^,\s]+(?:,[^,\s]+)*)", query)
            if (
                error is not None
                or not query
                or "title" in query.lower()
                or "short_description" in query.lower()
                or number_match is None
            ):
                return self._record(
                    name,
                    arguments,
                    {"error": error or "Only bounded numberIN queries are allowed."},
                    failed=True,
                    kind="servicenow_fetch",
                )
            numbers = number_match.group(1).split(",")
            if arguments["limit"] != len(numbers):
                return self._record(
                    name,
                    arguments,
                    {"error": "numberIN limit must match the requested number count."},
                    failed=True,
                    kind="servicenow_fetch",
                )
            if len(numbers) != 1:
                records = [
                    self._servicenow_record(numbers_item)
                    for numbers_item in numbers
                    if numbers_item in SERVICENOW_RECORDS
                ]
                return self._record(
                    name,
                    arguments,
                    {"result": records},
                    kind="servicenow_fetch",
                )
            return self._servicenow_record_result(name, arguments, numbers[0])

        return self._run_command(arguments)

    def run_servicenow_live(self, scenario: ServiceNowLiveScenario) -> None:
        self._servicenow_scenario = scenario
        self._record(
            "resolve_kb_connection",
            {"reference": SERVICENOW_CONNECTION_ID},
            {
                "connection": {
                    "id": SERVICENOW_CONNECTION_ID,
                    "source": "ServiceNow",
                }
            },
            kind="resolve",
        )
        self._record(
            "maker_confirmation",
            {
                "connection_id": SERVICENOW_CONNECTION_ID,
                "confirmed": scenario.maker_confirmed,
            },
            {"confirmed": scenario.maker_confirmed},
            failed=not scenario.maker_confirmed,
            kind="confirm",
        )

        if scenario.classification == "other":
            self.invoke(
                "graph_external_item_search",
                {
                    "contentSources": [
                        f"/external/connections/{SERVICENOW_CONNECTION_ID}"
                    ],
                    "query": "source classification probe",
                    "limit": 5,
                    "orderBy": ["rank desc"],
                    "phase": "classification",
                },
            )
            self._record(
                "generic_flow_continuation",
                {"classification": "other"},
                {"discarded_specialized_results": True},
                kind="generic_continuation",
            )
            return

        for query in (
            "employee leave policies",
            "paid time off policies",
            "workplace access policies",
            "employee support policies",
        ):
            search = self.invoke(
                "graph_external_item_search",
                {
                    "contentSources": [
                        f"/external/connections/{SERVICENOW_CONNECTION_ID}"
                    ],
                    "query": query,
                    "limit": 7,
                    "orderBy": ["rank desc"],
                    "phase": "broad",
                },
            )
            if search.failed:
                self._record(
                    "guidance",
                    {"graph_failure": scenario.graph_failure},
                    {
                        "action": "restart_with_local_files",
                        "message": "Graph search failed; restart curation with local files.",
                    },
                    kind="guidance",
                )
                return

        targeted = self.invoke(
            "graph_external_item_search",
            {
                "contentSources": [
                    f"/external/connections/{SERVICENOW_CONNECTION_ID}"
                ],
                "query": "confirmed leave and paid time off topic",
                "limit": 15,
                "orderBy": ["rank desc"],
                "phase": "targeted",
            },
        )
        if targeted.failed:
            self._record(
                "guidance",
                {"graph_failure": scenario.graph_failure},
                {
                    "action": "restart_with_local_files",
                    "message": "Graph search failed; restart curation with local files.",
                },
                kind="guidance",
            )
            return

        mapped_hits = [
            hit
            for hit in targeted.result["hits"]
            if hit.get("sys_id") or hit.get("number")
        ]
        configured_hostname = _normalized_url_hostname(SERVICENOW_INSTANCE_URL)
        source_hostnames: list[str] = []
        identity_failure: str | None = None
        for hit in mapped_hits:
            source_url = hit.get("sourceUrl")
            hostname = (
                _normalized_url_hostname(source_url)
                if isinstance(source_url, str)
                else None
            )
            if hostname is None:
                identity_failure = "missing_source_hostname"
                break
            if not _is_servicenow_hostname(hostname):
                identity_failure = "invalid_servicenow_hostname"
                break
            source_hostnames.append(hostname)

        unique_hostnames = sorted(set(source_hostnames))
        if identity_failure is None:
            if len(unique_hostnames) != 1:
                identity_failure = "conflicting_source_hostnames"
            elif unique_hostnames[0] != configured_hostname:
                identity_failure = "configured_instance_mismatch"
            elif not scenario.maker_confirmed:
                identity_failure = "unconfirmed_maker_identity"

        identity = self._record(
            "servicenow_host_identity",
            {
                "classification": scenario.classification,
                "mapped_source_urls": [
                    hit.get("sourceUrl") for hit in mapped_hits
                ],
                "configured_mcp_instance": SERVICENOW_INSTANCE_URL,
                "maker_confirmed": scenario.maker_confirmed,
            },
            {
                "classification": "servicenow",
                "source_hostname": (
                    unique_hostnames[0] if len(unique_hostnames) == 1 else None
                ),
                "configured_hostname": configured_hostname,
                "matches_configured_mcp_instance": identity_failure is None,
                "confirmed": identity_failure is None,
                "failure": identity_failure,
            },
            failed=identity_failure is not None,
            kind="host_identity",
        )
        if identity.failed:
            self._record(
                "guidance",
                {"host_identity": identity_failure},
                {
                    "action": "reconfigure_servicenow_identity",
                    "message": "Confirm one configured ServiceNow MCP instance that "
                    "matches every mapped targeted hit source URL.",
                },
                kind="guidance",
            )
            return

        if scenario.mcp_failure == "missing":
            self._record(
                "guidance",
                {"mcp_failure": scenario.mcp_failure},
                {
                    "action": "start_or_fix_servicenow_mcp",
                    "message": "Run /connect ServiceNow, then start or fix authentication "
                    "for the configured ServiceNow MCP server.",
                },
                kind="guidance",
            )
            return

        grounded_ids: list[str] = []
        for hit in targeted.result["hits"]:
            identifier_type = "sys_id" if hit.get("sys_id") else "number"
            identifier = hit.get(identifier_type)
            if identifier is None:
                self._record(
                    "disclose_unmapped_hit",
                    {"hit": hit},
                    {"reason": "unmapped", "title": hit["title"]},
                    kind="disclosure",
                )
                continue
            self._record(
                "map_servicenow_identifier",
                {"title": hit["title"]},
                {"type": identifier_type, "value": identifier},
                kind="identifier_mapping",
            )
            if identifier_type == "sys_id":
                fetch = self.invoke(
                    "get_record",
                    {
                        "table": "kb_knowledge",
                        "sys_id": identifier,
                        "fields": SERVICENOW_KB_FIELDS,
                    },
                )
            else:
                fetch = self.invoke(
                    "query_table",
                    {
                        "table": "kb_knowledge",
                        "query": f"numberIN{identifier}",
                        "fields": SERVICENOW_KB_FIELDS,
                        "limit": 1,
                    },
                )
            if fetch.failed:
                if scenario.mcp_failure == "authentication":
                    self._record(
                        "guidance",
                        {"mcp_failure": scenario.mcp_failure},
                        {
                            "action": "start_or_fix_servicenow_mcp",
                            "message": "Run /connect ServiceNow, then start or fix "
                            "authentication for the configured ServiceNow MCP server.",
                        },
                        kind="guidance",
                    )
                    return
                self._record(
                    "disclose_fetch_failure",
                    {"identifier": identifier},
                    {"reason": "fetch_failed", "identifier": identifier},
                    kind="disclosure",
                )
                continue
            record = fetch.result["result"]
            if (
                identifier_type == "sys_id"
                and record["sys_id"] != identifier
                or identifier_type == "number"
                and record["number"] != identifier
            ):
                self._record(
                    "disclose_identifier_mismatch",
                    {"identifier": identifier},
                    {
                        "reason": "identifier_mismatch",
                        "identifier": identifier,
                        "returned": {
                            "sys_id": record["sys_id"],
                            "number": record["number"],
                        },
                    },
                    kind="disclosure",
                )
                continue
            grounded_ids.append(record["sys_id"])
            self._record(
                "ground_servicenow_record",
                {"identifier": identifier},
                {
                    "sys_id": record["sys_id"],
                    "number": record["number"],
                    "grounded": True,
                },
                kind="grounding",
            )

        if grounded_ids:
            grounded_ids_content = "\n".join(
                f"  - {record_id}" for record_id in grounded_ids
            )
            self.invoke(
                "write_file",
                {
                    "path": "workspace/evaluations/servicenow-live/live.mcs.yml",
                    "content": (
                        "kind: EvaluationSet\n"
                        "groundedRecordIds:\n"
                        f"{grounded_ids_content}\n"
                    ),
                },
            )

    @staticmethod
    def _servicenow_contract_error(arguments: dict[str, Any]) -> str | None:
        if arguments["table"] != "kb_knowledge":
            return "Only kb_knowledge is allowed."
        if arguments["fields"] != SERVICENOW_KB_FIELDS:
            return "ServiceNow knowledge fields must use the exact projection."
        return None

    def _servicenow_record_result(
        self, name: str, arguments: dict[str, Any], identifier: str
    ) -> RecordedCall:
        scenario = self._servicenow_scenario
        if scenario is not None and (
            scenario.mcp_failure == "authentication"
            or identifier in scenario.fetch_failures
        ):
            return self._record(
                name,
                arguments,
                {
                    "error": (
                        "Synthetic ServiceNow authentication failed."
                        if scenario.mcp_failure == "authentication"
                        else f"Synthetic fetch failed for {identifier}."
                    )
                },
                failed=True,
                kind="servicenow_fetch",
            )
        if identifier not in SERVICENOW_RECORDS:
            return self._record(
                name,
                arguments,
                {"error": "Synthetic ServiceNow record not found."},
                failed=True,
                kind="servicenow_fetch",
            )
        return self._record(
            name,
            arguments,
            {"result": self._servicenow_record(identifier)},
            kind="servicenow_fetch",
        )

    def _servicenow_record(self, identifier: str) -> dict[str, str]:
        record = deepcopy(SERVICENOW_RECORDS[identifier])
        scenario = self._servicenow_scenario
        if scenario is not None:
            record.update(scenario.returned_identifier_overrides.get(identifier, {}))
        return record

    def _run_command(self, arguments: dict[str, Any]) -> RecordedCall:
        command = arguments["command"]
        normalized = command.replace("\\", "/")
        try:
            tokens = shlex.split(normalized, posix=True)
        except ValueError:
            return self._record(
                "run_command",
                arguments,
                {"exitCode": 2, "stderr": "Invalid command."},
                failed=True,
                kind="command",
            )
        cleaned = [token.strip("\"'") for token in tokens]

        if self._matching_token_index(cleaned, STRUCTURAL_VALIDATOR_PATH) is not None:
            evaluation_folder, error = self._validated_evaluation_folder(cleaned)
            if error is not None:
                return self._validation_failure(arguments, error, "structural")
            return self._record(
                "run_command",
                arguments,
                {
                    "exitCode": 0,
                    "stdout": "Structural validation passed.",
                    "evaluationFolder": evaluation_folder,
                },
                kind="structural_validation",
                validator_type="structural",
            )

        if self._matching_token_index(cleaned, "scripts/evaluate_evals.py") is not None:
            evaluation_folder, error = self._validated_evaluation_folder(cleaned)
            if error is not None:
                return self._validation_failure(arguments, error, "maker_kit")
            validator_read_index = self._last_matching_read_index(
                MAKER_VALIDATOR_SKILL_PATH
            )
            if validator_read_index is None:
                return self._validation_failure(
                    arguments,
                    "Maker validator skill must be read before Maker Kit validation.",
                    "maker_kit",
                )
            last_write_index = self._last_set_write_index(evaluation_folder)
            structural_index = self._last_structural_validation_index(
                evaluation_folder
            )
            if structural_index is None or (
                last_write_index is not None and structural_index < last_write_index
            ):
                return self._validation_failure(
                    arguments,
                    "Maker Kit validation requires structural validation for the "
                    "same evaluation set after its final write.",
                    "maker_kit",
                )
            missing_structural = [
                generated_folder
                for generated_folder in sorted(self.generated_set_folders())
                if not self._has_current_structural_validation(generated_folder)
            ]
            if missing_structural:
                return self._validation_failure(
                    arguments,
                    "Maker Kit validation requires successful structural validation "
                    "for every generated evaluation set after its latest write; "
                    f"missing {missing_structural}.",
                    "maker_kit",
                )
            return self._record(
                "run_command",
                arguments,
                {
                    "exitCode": 0,
                    "stdout": json.dumps(
                        {
                            "overallScore": 5,
                            "gate": "passed",
                            "flaggedCases": [],
                        }
                    ),
                    "evaluationFolder": evaluation_folder,
                },
                kind="maker_kit_validation",
                validator_type="maker_kit",
            )

        if self._matching_token_index(cleaned, "scripts/push.py") is not None:
            return self._record(
                "run_command",
                arguments,
                {"exitCode": 2, "stderr": "Synthetic pushes are disabled."},
                failed=True,
                kind="push",
            )

        return self._record(
            "run_command",
            arguments,
            {"exitCode": 2, "stderr": "Command is not available in this evaluation."},
            failed=True,
            kind="command",
        )

    @staticmethod
    def _normalize(path: str) -> str:
        return str(PurePosixPath(path.replace("\\", "/").removeprefix("./")))

    @classmethod
    def path_matches(cls, path: str, expected_key: str) -> bool:
        normalized_path = cls._normalize(path)
        normalized_key = cls._normalize(expected_key)
        repo_prefix = "solutions/ess-maker-skills/"
        if (
            ".." in PurePosixPath(normalized_path).parts
            or ".." in PurePosixPath(normalized_key).parts
        ):
            return False

        solution_key = (
            normalized_key.removeprefix(repo_prefix)
            if normalized_key.startswith(repo_prefix)
            else normalized_key
        )
        if solution_key not in SYNTHETIC_SOLUTION_PATH_KEYS:
            return False
        allowed_relative = {
            solution_key,
            f"{repo_prefix}{solution_key}",
        }
        allowed_absolute = cls._normalize(
            str(SYNTHETIC_SOLUTION_ROOT / solution_key)
        )
        return normalized_path in allowed_relative | {allowed_absolute}

    def _matching_file_key(self, path: str) -> str | None:
        return next(
            (
                file_key
                for file_key in self.files
                if self.path_matches(path, file_key)
            ),
            None,
        )

    @classmethod
    def _matching_token_index(
        cls, tokens: list[str], expected_suffix: str
    ) -> int | None:
        return next(
            (
                index
                for index, token in enumerate(tokens)
                if cls.path_matches(token, expected_suffix)
            ),
            None,
        )

    @classmethod
    def evaluation_folder_from_command(cls, command: str) -> str | None:
        try:
            tokens = shlex.split(command.replace("\\", "/"), posix=True)
        except ValueError:
            return None
        return cls._evaluation_folder_from_tokens(tokens)

    @classmethod
    def _evaluation_folder_from_tokens(cls, tokens: list[str]) -> str | None:
        option = "--evaluation-folder"
        for index, token in enumerate(tokens):
            cleaned = token.strip("\"'")
            if cleaned == option:
                if index + 1 >= len(tokens):
                    return None
                return cls._normalize(tokens[index + 1].strip("\"'"))
            if cleaned.startswith(f"{option}="):
                return cls._normalize(cleaned.removeprefix(f"{option}="))
        return None

    def generated_set_folders(self, *, before_index: int | None = None) -> set[str]:
        folders: set[str] = set()
        for index, call in enumerate(self.calls):
            if before_index is not None and index >= before_index:
                break
            if call.name != "write_file" or call.failed:
                continue
            path = self._normalize(call.arguments["path"])
            if not path.endswith(".mcs.yml"):
                continue
            parts = PurePosixPath(path).parts
            if (
                len(parts) >= 4
                and parts[:2] == ("workspace", "evaluations")
                and parts[2] != "exports"
            ):
                folders.add("/".join(parts[:3]))
        return folders

    def _validated_evaluation_folder(
        self, tokens: list[str]
    ) -> tuple[str | None, str | None]:
        evaluation_folder = self._evaluation_folder_from_tokens(tokens)
        if evaluation_folder is None:
            return None, "Missing --evaluation-folder value."
        if ".." in PurePosixPath(evaluation_folder).parts:
            return None, "Evaluation folder cannot contain parent traversal."

        generated_folders = self.generated_set_folders()
        matching_folder = next(
            (
                generated_folder
                for generated_folder in generated_folders
                if evaluation_folder
                in {
                    generated_folder,
                    self._normalize(
                        str(SYNTHETIC_REPO_ROOT / generated_folder)
                    ),
                }
            ),
            None,
        )
        if matching_folder is None:
            return (
                None,
                "Validator must target one of the generated evaluation set folders "
                f"{sorted(generated_folders)}; got {evaluation_folder}.",
            )
        return matching_folder, None

    def _last_set_write_index(
        self, evaluation_folder: str, *, before_index: int | None = None
    ) -> int | None:
        folder_prefix = f"{evaluation_folder}/"
        search_end = len(self.calls) if before_index is None else before_index
        return next(
            (
                index
                for index in range(search_end - 1, -1, -1)
                if self.calls[index].name == "write_file"
                and not self.calls[index].failed
                and self._normalize(
                    self.calls[index].arguments["path"]
                ).startswith(folder_prefix)
                and self._normalize(
                    self.calls[index].arguments["path"]
                ).endswith(".mcs.yml")
            ),
            None,
        )

    def _last_structural_validation_index(
        self, evaluation_folder: str, *, before_index: int | None = None
    ) -> int | None:
        search_end = len(self.calls) if before_index is None else before_index
        return next(
            (
                index
                for index in range(search_end - 1, -1, -1)
                if self.calls[index].kind == "structural_validation"
                and not self.calls[index].failed
                and self.calls[index].result.get("evaluationFolder")
                == evaluation_folder
            ),
            None,
        )

    def _has_current_structural_validation(
        self, evaluation_folder: str, *, before_index: int | None = None
    ) -> bool:
        last_write_index = self._last_set_write_index(
            evaluation_folder, before_index=before_index
        )
        structural_index = self._last_structural_validation_index(
            evaluation_folder, before_index=before_index
        )
        return structural_index is not None and (
            last_write_index is None or structural_index > last_write_index
        )

    def maker_validation_ordering_violations(self) -> list[str]:
        violations: list[str] = []
        for attempt_index, call in enumerate(self.calls):
            if call.validator_type != "maker_kit":
                continue
            generated_folders = sorted(
                self.generated_set_folders(before_index=attempt_index)
            )
            missing_structural = [
                folder
                for folder in generated_folders
                if not self._has_current_structural_validation(
                    folder, before_index=attempt_index
                )
            ]
            if missing_structural:
                violations.append(
                    "Maker Kit validation attempt at call "
                    f"{attempt_index} occurred before current structural validation "
                    f"for every generated set; missing {missing_structural}."
                )
        return violations

    def _last_matching_read_index(self, expected_key: str) -> int | None:
        return next(
            (
                index
                for index in range(len(self.calls) - 1, -1, -1)
                if self.calls[index].name == "read_file"
                and not self.calls[index].failed
                and self.path_matches(
                    self.calls[index].arguments["path"], expected_key
                )
            ),
            None,
        )

    def _validation_failure(
        self, arguments: dict[str, Any], message: str, validator_type: str
    ) -> RecordedCall:
        return self._record(
            "run_command",
            arguments,
            {"exitCode": 2, "stderr": message},
            failed=True,
            kind="validation",
            validator_type=validator_type,
        )

    def _record(
        self,
        name: str,
        arguments: dict[str, Any],
        result: Any,
        *,
        failed: bool = False,
        kind: str = "other",
        validator_type: str | None = None,
    ) -> RecordedCall:
        call = RecordedCall(
            self.turn,
            name,
            deepcopy(arguments),
            deepcopy(result),
            failed,
            kind,
            validator_type,
        )
        self.calls.append(call)
        return call


@dataclass(frozen=True)
class EvalTurn:
    prompt: str


@dataclass(frozen=True)
class EvalResult:
    replies: list[str]
    trace_path: Path


def _github_token() -> str:
    __tracebackhide__ = True
    result = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Skill evals require an authenticated gh CLI with Copilot access.")
    return result.stdout.strip()


def session_options(
    model: str, tools: list[Any], available_tools: Any, directory: Path
) -> dict[str, Any]:
    instructions = "\n\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROMPT_PATH, DISPATCHER_PATH, WRAPPER_PATH)
    )
    return {
        "model": model,
        "tools": tools,
        "available_tools": available_tools,
        "working_directory": str(directory),
        "skip_custom_instructions": True,
        "enable_config_discovery": False,
        "enable_skills": False,
        "enable_file_hooks": False,
        "enable_host_git_operations": False,
        "enable_session_store": False,
        "memory": {"enabled": False},
        "mcp_servers": {},
        "custom_agents": [],
        "plugin_directories": [],
        "infinite_sessions": {"enabled": False},
        "session_limits": {"max_ai_credits": 30},
        "system_message": {
            "mode": "replace",
            "content": (
                "You are the ESS Maker Kit assistant in a synthetic evaluation. "
                "Follow the supplied Maker Kit instructions completely. Use only the "
                "provided tools. read_file exposes only synthetic contract, skill, "
                "knowledge, and agent-instruction data. write_file records writes "
                "without changing the host. run_command records validator calls but "
                "never executes commands or contacts a tenant. Do not push unless the "
                "maker gives a separate explicit push approval after all prior gates.\n\n"
                + instructions
            ),
        },
    }


@asynccontextmanager
async def model_client(directory: Path) -> AsyncIterator[Any]:
    __tracebackhide__ = True
    from copilot import CopilotClient

    class ClosingCopilotClient(CopilotClient):
        async def start(self) -> None:
            __tracebackhide__ = True
            try:
                await super().start()
            except (OSError, ValueError, subprocess.SubprocessError):
                raise RuntimeError("Could not start the isolated model runtime.") from None

        async def stop(self) -> None:
            process = self._cli_process
            try:
                await super().stop()
            finally:
                if process is not None:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()

    try:
        client = ClosingCopilotClient(
            mode="empty",
            github_token=_github_token(),
            working_directory=str(directory),
            base_directory=str(directory / "host"),
            log_level="error",
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RuntimeError("Could not initialize the isolated model runtime.") from None
    async with client:
        yield client


async def send_turn(
    session: Any, prompt: str, events: list[str], *, timeout: float = TURN_TIMEOUT
) -> str:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    def on_event(event: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    unsubscribe = session.on(on_event)
    reply: str | None = None
    try:
        async with asyncio.timeout(timeout):
            message_id = await session.send(prompt, agent_mode="interactive")
            while True:
                event = await queue.get()
                kind = getattr(event.type, "value", str(event.type))
                events.append(kind)
                if kind == "session.error":
                    raise RuntimeError(f"Model session failed: {event.data.message}")
                if kind == "assistant.message":
                    origin = getattr(event.data, "originating_message_id", message_id)
                    if origin == message_id:
                        reply = (
                            None
                            if getattr(event.data, "tool_requests", None)
                            else event.data.content
                        )
                if kind in {"assistant.turn_end", "session.idle"} and reply:
                    return reply
    except TimeoutError:
        await session.abort()
        raise
    finally:
        unsubscribe()


async def run_eval(
    backend: FakeEvaluationWorkspace,
    turns: list[EvalTurn],
    directory: Path,
) -> EvalResult:
    try:
        from copilot import ToolSet
        from copilot.tools import Tool, ToolResult
    except ImportError as error:
        raise RuntimeError(
            "Install the skill-eval extra: python -m pip install -e '.[test,skill-eval]'"
        ) from error

    model = os.environ.get("ESS_SKILL_EVAL_MODEL", DEFAULT_MODEL)
    contracts = tool_contracts()
    backend.contract_by_name = {contract.name: contract for contract in contracts}
    allowed = ToolSet()
    tools = []

    def handle(invocation: Any) -> Any:
        call = backend.invoke(invocation.tool_name, invocation.arguments)
        text = call.result if isinstance(call.result, str) else json.dumps(call.result)
        return ToolResult(
            text_result_for_llm=text,
            result_type="failure" if call.failed else "success",
            error="Synthetic tool failure." if call.failed else None,
        )

    for contract in contracts:
        allowed.add_custom(contract.name)
        tools.append(
            Tool(
                name=contract.name,
                description=contract.description,
                parameters=contract.parameters,
                handler=handle,
                skip_permission=True,
                overrides_built_in_tool=contract.name == "read_file",
            )
        )

    replies: list[str] = []
    events: list[str] = []
    trace_path = directory / "trace.json"
    try:
        async with (
            asyncio.timeout(TURN_TIMEOUT * len(turns) + 60),
            model_client(directory) as client,
        ):
            async with await client.create_session(
                **session_options(model, tools, allowed, directory)
            ) as session:
                for index, turn in enumerate(turns):
                    backend.turn = index
                    reply = await send_turn(session, turn.prompt, events)
                    if backend.limit_exceeded:
                        raise RuntimeError(
                            f"Evaluation exceeded the {MAX_CALLS}-tool-call limit."
                        )
                    replies.append(reply)
    finally:
        trace_path.write_text(
            json.dumps(
                {
                    "model": model,
                    "wrapper_sha256": hashlib.sha256(WRAPPER_PATH.read_bytes()).hexdigest(),
                    "curator_sha256": hashlib.sha256(
                        REAL_CURATOR_PATH.read_bytes()
                    ).hexdigest(),
                    "tool_names": [contract.name for contract in contracts],
                    "turns": [turn.prompt for turn in turns],
                    "calls": [asdict(call) for call in backend.calls],
                    "replies": replies,
                    "event_types": events,
                    "completed": len(replies) == len(turns),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return EvalResult(replies, trace_path)
