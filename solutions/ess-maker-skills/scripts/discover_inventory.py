# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Tenant Inventory Discovery (crawl) wrapper

Thin bridge that runs the admin-run tenant-inventory crawler implemented in
``tools/tenant-inventory-discovery`` and writes a results JSON the /discover
skill renders. This is the script the ``src/skills/discover/SKILL.md`` invokes.

The crawler enumerates a tenant's shared agent resources across eight kinds
(Environment, EntraApp, Connector, Connection, SharePointSite, KnowledgeSource,
ExtensionPack, ScenarioTemplate) and submits them to the WeveNova Inventory API as a
single whole-inventory ``syncInventory`` call. The crawl is always scoped to the
**single environment configured during /setup** -- there is no full-tenant crawl.

.. warning::
   ``syncInventory`` retires by absence: anything currently Active that the submitted
   payload omits is deleted. Because this crawl only ever sees one environment, the
   crawler first reads the existing inventory and **carries forward** every Active row
   it cannot vouch for, so resources in other environments survive. If that read fails,
   the sync is withheld entirely rather than submitted incomplete. See
   ``tools/tenant-inventory-discovery`` ``discovery_skill.py`` for the full rule.

.. note::
   Two independent switches: where the crawl **reads** from, and where it **writes** to.

   Crawl source:

   - ``--demo``  -> in-memory ``FakePlatform`` (a small representative environment).
   - default     -> live enumeration of all eight kinds for the configured environment:
     Dataverse (``Connection``, ``ExtensionPack``, ``ScenarioTemplate``) via
     ``scripts/auth.py``; Microsoft Graph (``EntraApp``, ``SharePointSite``) via the
     kit's ``GraphClient``; the BAP admin API (``Connector``) via ``PPAdminClient``; and
     Copilot Studio (``KnowledgeSource``, and the sites behind ``SharePointSite``) via
     ``PVAClient``. Any kind whose platform call fails is reported as an incomplete
     scope; its existing rows are carried forward unchanged rather than retired, so a
     partial crawl costs freshness, never data.

   Write path (persisting is the default -- it is the point of a discovery pass):

   - default        -> the ess-planner MCP server
     (``src/mcp/agentconfig_planner/server.py``), which owns the inventory write path
     and proxies to the Inventory API at ``https://substrate.office.com/weveb2``.
     Override the origin with ``--base-url`` or ``WEVENOVA_BASE_URL`` for other rings
     and dev tunnels. The server resolves its own token: ``WEVENOVA_ACCESS_TOKEN``,
     else the planner's cached MSAL sign-in (shared with the planner skill). This is
     the default because it reuses that existing sign-in, so a crawl persists through
     the same MCP without a second credential.
   - ``--local-only`` -> explicit opt-out: crawl, validate, and update the local
     mirror without contacting the service.

   The live path is pre-flighted before the crawl starts. If the endpoint is
   unreachable or the token is rejected, the run **degrades** to the local mirror,
   reports ``writeDegraded`` with the reason, and exits ``2`` -- the crawl results are
   still saved, but the run never claims to have persisted anything it did not.

   .. note::
      The live write path runs entirely through the ess-planner MCP server, which signs
      in as the AgentConfiguration client WeveNova preauthorizes for the
      ``weve/.default`` scope and admits under its
      ``ManageAgentConfigurationFromAuthorizedApp`` policy. When that server cannot be
      reached the run degrades to the local mirror and exits ``2``; re-running once the
      MCP path is healthy reconciles the mirror to the service -- a sync is a full
      upsert/retire against the crawled end state, so nothing is lost in the meantime.

Exit codes:
   0 = crawl succeeded and the inventory was updated (or --local-only was requested)
   1 = the run aborted; nothing was written and the local mirror was left untouched
   2 = the crawl succeeded but the inventory was not updated -- either the write path
       failed (see writePathNote) or the sync was withheld for safety (see
       syncWithheldNote). In both cases nothing was deleted.

Usage:
   # Live crawl of the configured environment, persisted to WeveNova (the default;
   # prompts for admin sign-in, requires /setup completed):
   python scripts/discover_inventory.py --tenant-id contoso

   # Same crawl, but explicitly opting out of persisting:
   python scripts/discover_inventory.py --tenant-id contoso --local-only

   # Point at a non-production ring or dev tunnel:
   python scripts/discover_inventory.py --tenant-id contoso \
       --base-url https://<inventory-host>

   # Offline demo against sample data:
   python scripts/discover_inventory.py --tenant-id contoso --demo --local-only \
       --json-out workspace/discover/results.json
"""

import argparse
import json
import os
import sys
from urllib.parse import urlparse

# Make the standalone crawler package importable without installing it. The module
# lives at repo-root: tools/tenant-inventory-discovery/src (three levels up from here:
# scripts/ -> ess-maker-skills/ -> solutions/ -> repo root).
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
_CRAWLER_SRC = os.path.join(
    _REPO_ROOT, "tools", "tenant-inventory-discovery", "src"
)
if _CRAWLER_SRC not in sys.path:
    sys.path.insert(0, _CRAWLER_SRC)

from tenant_inventory_discovery.config import (  # noqa: E402
    DEFAULT_INVENTORY_BASE_URL,
    ENV_BASE_URL,
    DiscoveryConfig,
    is_loopback_url,
)
from tenant_inventory_discovery.discovery_skill import DiscoverySkill  # noqa: E402
from tenant_inventory_discovery.local_store import build_document  # noqa: E402
from tenant_inventory_discovery.lock import FileRunLock  # noqa: E402
from tenant_inventory_discovery.models import RunSummary  # noqa: E402
from tenant_inventory_discovery.progress import (  # noqa: E402
    DEFAULT_HEARTBEAT_SECONDS,
    ConsoleProgressReporter,
    NullProgressReporter,
)
from tenant_inventory_discovery.recording import (  # noqa: E402
    RecordingInventoryClient,
)

DEFAULT_JSON_OUT = "workspace/discover/results.json"

# Durable local mirror of the (server-authoritative) tenant inventory. Unlike the
# transient results JSON, this file is merged across runs with the same whole-inventory
# semantics the server uses, so it stays a faithful offline picture.
DEFAULT_INVENTORY_OUT = os.path.join(".local", "inventory.json")

# Demo mode has no config, so it crawls this one representative environment (the tool
# only ever crawls a single environment -- there is no full-tenant crawl).
_DEMO_ENV_ID = "env-prod"


def _demo_platform_and_inventory():
    """Build the in-memory fake platform with a small representative tenant."""
    from tenant_inventory_discovery.platform_clients import FakePlatform

    platform = FakePlatform(
        environments=[
            {"environmentId": "env-prod", "displayName": "Contoso Prod"},
            {"environmentId": "env-test", "displayName": "Contoso Test"},
        ],
        entra_apps=[{"appId": "app-ess", "displayName": "ESS Agent App"}],
        connectors=[
            {"connectorId": "shared_service-now", "displayName": "ServiceNow"},
            {"connectorId": "shared_workdaysoap", "displayName": "Workday"},
        ],
        sharepoint_sites=[
            {"siteUrl": "https://contoso.sharepoint.com/hr", "siteId": "site-hr"}
        ],
        connections={
            "env-prod": [
                {
                    "environmentId": "env-prod",
                    "connectionId": "sn-1",
                    "connectorId": "shared_service-now",
                    "status": "Connected",
                }
            ],
        },
        knowledge_sources={
            "env-prod": [
                {
                    "environmentId": "env-prod",
                    "botId": "bot-ess",
                    "sourceId": "ks-hr",
                    "sourceType": "SharePoint",
                }
            ],
        },
        extension_packs={
            "env-prod": [
                {
                    "environmentId": "env-prod",
                    "installed": True,
                    "hrsd": True,
                    "itsm": False,
                    "flavor": "ServiceNow",
                    "flowCount": 8,
                }
            ],
        },
        scenario_templates={
            "env-prod": [
                {
                    "environmentId": "env-prod",
                    "uniqueName": "GetPayslip",
                    "operation": "GetPayslip",
                    "status": "Active",
                }
            ],
        },
    )
    return platform, _DEMO_ENV_ID


def _dig(mapping, *path):
    """Read a nested key path, tolerating missing or oddly-typed intermediates."""
    current = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


# Where the Entra app (client) id is *actually* persisted, in precedence order.
# `setup/shared/config-schema.md` documents `entraAppId` as a top-level key of
# `.local/config.json`, but no playbook writes it there -- each connector's
# `/connect` flow keeps it in its own file under its own key.
_ENTRA_APP_ID_FALLBACKS = (
    (("connect", "workday", "config.json"), ("entraAppId",)),
    (("connect", "servicenow", "config.json"), ("entra", "appClientId")),
)


def _resolve_entra_app_id(cfg, local_state_dir=".local"):
    """Find the agent's Entra app (client) id wherever `/connect` actually wrote it.

    This is a **hint, not a requirement**. `EntraApp` discovery enumerates the tenant's
    app registrations regardless; the id is used only to pin the agent's own app to the
    front of that listing so it survives the server's per-kind row cap on a large
    directory.

    Reading only the documented top-level `entraAppId` would miss it on a fully
    connected tenant, because the connect playbooks persist it elsewhere: Workday as
    `entraAppId` in `.local/connect/workday/config.json`, ServiceNow as
    `entra.appClientId` in `.local/connect/servicenow/config.json`. FlightCheck hit the
    same config drift and works around it the same way -- see
    `flightcheck/checks/_workday_app_assignment.py::_workday_hints`.

    Returns ``None`` when no connector has been connected yet. That is a legitimate
    state, not an error: the crawl simply has no app to prioritise.

    Any read/parse failure degrades to "not found" rather than raising -- a malformed
    connect config must not take down a crawl of seven other kinds.
    """
    documented = str(_dig(cfg, "entraAppId") or "").strip()
    if documented:
        return documented

    for parts, key_path in _ENTRA_APP_ID_FALLBACKS:
        path = os.path.join(local_state_dir, *parts)
        try:
            with open(path, encoding="utf-8") as fh:
                connect_cfg = json.load(fh)
        except Exception:  # noqa: BLE001 - missing/invalid connect config -> no hint
            continue
        found = str(_dig(connect_cfg, *key_path) or "").strip()
        if found:
            return found
    return None


# Rings `/setup` saves an environment list for. The ring also names the evidence file,
# so any other value is ignored rather than joined into a path.
_SETUP_RINGS = frozenset({"prod", "preprod", "test"})

# Where a Dataverse URL can sit on one raw environment-list record, in precedence order.
_ENVIRONMENT_URL_PATHS = (
    ("url",),
    ("instanceUrl",),
    ("properties", "linkedEnvironmentMetadata", "instanceUrl"),
    ("properties", "linkedEnvironmentMetadata", "instanceApiUrl"),
)


def _read_json_object(path):
    """Return the JSON object at ``path``, or ``None`` when it is missing or invalid."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 - missing/invalid evidence -> no hint
        return None
    return data if isinstance(data, dict) else None


def _bare_environment_id(value):
    """Normalize a Power Platform environment id for comparison.

    Setup stores the bare GUID, while the environment list can name the default
    environment ``Default-<guid>``.
    """
    text = str(value or "").strip().casefold()
    return text.removeprefix("default-")


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _url(value):
    return _text(value).rstrip("/")


def _resolve_dataverse_endpoint(cfg, local_state_dir=".local"):
    """Find the Dataverse URL of the single environment `/setup` configured.

    Classic setup writes it as ``dataverseEndpoint`` in `.local/config.json`, and that
    key still wins. DA setup never writes it: it records the Power Platform
    ``environmentId`` and ``ring`` instead. For a DA workspace the URL is recovered from
    evidence already on disk, matched to that exact environment id:

    1. the environment list `/setup` saved for the ring
       (`.local/setup/environment-list-{ring}.json`), then
    2. the Workday connect scope (`.local/connect/workday-da/config.json`), which records
       the ``dataverseUrl`` it proved for its ``environmentId``.

    This follows `workday_connect_preflight.resolve_target` without its live PAC lookup,
    so finding the URL never needs another sign-in.

    Returns ``None`` when no source names the URL. A read/parse failure, an ambiguous
    environment list, or evidence for a different environment degrades to "not found"
    rather than raising, so the caller can tell the maker what to fix.
    """
    documented = _url(_dig(cfg, "dataverseEndpoint"))
    if documented:
        return documented

    environment_id = _bare_environment_id(_dig(cfg, "environmentId"))
    if not environment_id:
        return None

    ring = _text(_dig(cfg, "ring")).casefold() or "prod"
    if ring in _SETUP_RINGS:
        listing = _read_json_object(
            os.path.join(local_state_dir, "setup", f"environment-list-{ring}.json")
        )
        records = _dig(listing, "environments")
        if isinstance(records, list):
            matches = [
                record
                for record in records
                if isinstance(record, dict)
                and _bare_environment_id(record.get("id")) == environment_id
            ]
            if len(matches) == 1:
                for path in _ENVIRONMENT_URL_PATHS:
                    url = _url(_dig(matches[0], *path))
                    if url:
                        return url

    scope = _dig(
        _read_json_object(
            os.path.join(local_state_dir, "connect", "workday-da", "config.json")
        ),
        "scope",
    )
    if _bare_environment_id(_dig(scope, "environmentId")) == environment_id:
        return _url(_dig(scope, "dataverseUrl")) or None
    return None


def _live_platform():
    """Build the live Dataverse-backed platform (default crawl source).

    Reuses the kit's ``scripts/auth.py`` (delegated admin sign-in + paged Web API
    queries) via :class:`DataverseBackedPlatform`. Setup binds a **single** environment;
    :func:`_resolve_dataverse_endpoint` finds its Dataverse URL from the saved setup
    state, and the environment's identity is derived from that URL (no live environment
    discovery). The crawl is **always** scoped to that one environment -- there is no
    full-tenant crawl -- so the platform declares ``EntraApp`` as its only genuinely
    tenant-wide kind (``tenant_wide_kinds``) and everything else is carried forward
    rather than retired by absence.
    """
    import auth
    from discover_dataverse_platform import DataverseBackedPlatform

    cfg = auth.load_config()
    env_url = _resolve_dataverse_endpoint(cfg)
    if not env_url:
        environment_id = _text(_dig(cfg, "environmentId"))
        if not environment_id:
            raise SystemExit(
                "Setup has not recorded an environment for this workspace. "
                "Run /setup, then run /discover again."
            )
        # Never suggest adding 'dataverseEndpoint': a DA workspace with that key is
        # treated as classic by other skills (minimalbot_evaluation.is_minimalbot).
        raise SystemExit(
            f"Discover could not find a Dataverse URL for environment {environment_id}, "
            "which /setup selected. Discover reads that environment's Dataverse "
            "database, and DA setup can select an environment without one. Check in "
            "the Power Platform admin center that the environment has a Dataverse "
            "database."
        )

    platform = DataverseBackedPlatform(
        env_url,
        entra_app_id=_resolve_entra_app_id(cfg),
        bot_id=(cfg.get("agent") or {}).get("botId"),
    )
    return platform, platform.environment_id


def _build_inventory_client(
    local_only, tenant_id, config, insecure=False, explicit_base=None
):
    """Pick the write path and return ``(client, write_path_label, degraded_reason)``.

    Persisting to WeveNova is the default: a discovery pass exists to update the tenant
    inventory, so writing is the intent and ``--local-only`` is the explicit opt-out.
    The live path runs through the ess-planner MCP server -- the same server, process,
    and identity the planner skill uses. When it cannot be used the run does *not*
    silently succeed: it falls back to the local mirror, reports the failure, and exits
    non-zero so a later run can reconcile the mirror to the service.
    """
    from tenant_inventory_discovery.in_memory_inventory import InMemoryInventoryClient

    if local_only:
        return InMemoryInventoryClient(caps=config.caps), "local-only", None

    return _build_mcp_client(explicit_base, tenant_id, config, insecure)


def _build_mcp_client(explicit_base, tenant_id, config, insecure):
    """Route writes through the ess-planner MCP server. This is the default path.

    The server resolves its own token (``WEVENOVA_ACCESS_TOKEN``, else the planner's
    cached MSAL sign-in shared with the planner skill) and handles the dev tunnel's
    self-signed certificate, so this path reuses the existing sign-in rather than
    acquiring a second credential. Configuration is passed through the child's
    environment because that is the server's only input surface.

    ``explicit_base`` is the origin the *user* asked for, not the bridge's production
    default. Forwarding that default would silently override the server's own
    dev-tunnel default and point an MCP run at production.
    """
    from tenant_inventory_discovery.in_memory_inventory import InMemoryInventoryClient
    from tenant_inventory_discovery.mcp_inventory import (
        McpInventoryClient,
        default_server_argv,
    )

    env = dict(os.environ)
    if explicit_base:
        env[ENV_BASE_URL] = explicit_base
    else:
        env.pop(ENV_BASE_URL, None)
    if insecure:
        # An explicit --insecure-skip-tls-verify forces verification off wherever the
        # server ends up pointing. Otherwise say nothing and let the server apply the
        # loopback rule against its own effective base URL, which it knows and this
        # process does not.
        env["WEVENOVA_VERIFY_TLS"] = "false"
    else:
        env.pop("WEVENOVA_VERIFY_TLS", None)

    try:
        client = McpInventoryClient(
            tenant_id, server_argv=default_server_argv(_REPO_ROOT), env=env
        )
    except Exception as exc:  # noqa: BLE001 - degrade, never abort the crawl
        return (
            InMemoryInventoryClient(caps=config.caps),
            "local-only",
            f"could not start the WeveNova MCP server ({exc})",
        )

    try:
        info = client.server_info()
        if not _same_tenant(info.get("tenantId"), tenant_id):
            raise ValueError(
                "tenant identity mismatch or missing MCP tenant: "
                f"requested {tenant_id!r}, MCP {info.get('tenantId')!r}; "
                "shared inventory writes are disabled"
            )
        client.probe()
    except Exception as exc:  # noqa: BLE001 - degrade, never abort the crawl
        client.close()
        return (
            InMemoryInventoryClient(caps=config.caps),
            "local-only",
            f"the WeveNova MCP server could not reach the Inventory API "
            f"({exc}){_tls_hint(exc, insecure)}",
        )

    return client, f"mcp:{info.get('baseUrl', explicit_base or 'unknown')}", None


def _same_tenant(actual, requested):
    """Unknown authorities are not tenant identities."""
    if not isinstance(actual, str) or not isinstance(requested, str):
        return False
    actual, requested = actual.strip().casefold(), requested.strip().casefold()
    return bool(actual) and actual not in {"organizations", "common", "consumers"} and (
        actual == requested
    )


def _source_tenant_error(platform, requested):
    try:
        source = platform.authenticated_tenant_id()
        if not _same_tenant(source, requested):
            raise ValueError(
                f"source tenant {source!r} does not match requested tenant {requested!r}"
            )
    except Exception as exc:
        return f"source tenant could not be verified ({exc}); shared inventory writes are disabled"
    return None


def _run_lock_dir():
    # All checkouts for this OS user must contend on the same tenant lock.
    return os.path.join(os.path.expanduser("~"), ".ess-adk", "discovery-locks")


def _tls_hint(exc, insecure):
    """Name the fix for the one failure whose message does not suggest it.

    httpx validates against certifi rather than the Windows certificate store, so it
    rejects a host that PowerShell and Insomnia reach happily -- which makes this look
    like a service problem instead of a trust-store difference.

    Loopback targets are no longer verified at all, so reaching this means the target is
    a real host (or ``WEVENOVA_VERIFY_TLS`` forced the check on). The likeliest cause is
    therefore a base URL that does not point where the developer thinks it does, and
    that is what the hint leads with -- suggesting ``--insecure-skip-tls-verify`` first
    would talk someone into disabling verification against a genuinely remote host.
    """
    if insecure:
        return ""
    text = str(exc).lower()
    if "certificate" in text or "ssl" in text:
        return (
            ". This is a TLS trust failure, not an API error: httpx validates against "
            "certifi, while PowerShell and Insomnia use the Windows certificate store. "
            "Local dev tunnels (localhost, 127.0.0.1, ::1) are not verified, so this "
            "target is not one -- check --base-url / WEVENOVA_BASE_URL first. If the "
            "host is genuinely remote and you accept the interception risk, "
            "--insecure-skip-tls-verify forces past it."
        )
    return ""


def _resolve_write_mode(args):
    """Resolve the write destination. Writing to WeveNova is the default.

    ``--base-url`` (or ``WEVENOVA_BASE_URL``) overrides the production origin for other
    rings and dev tunnels. ``--local-only`` is the explicit opt-out and conflicts with
    an explicitly supplied base URL -- but not with the built-in default, which carries
    no user intent.
    """
    explicit_base = args.base_url or os.environ.get(ENV_BASE_URL)
    if args.local_only and explicit_base:
        raise SystemExit(
            "--local-only conflicts with --base-url"
            f"{f' (from {ENV_BASE_URL})' if not args.base_url else ''}. "
            "Pick one write destination."
        )
    if args.local_only:
        return None, True
    return explicit_base or DEFAULT_INVENTORY_BASE_URL, False


def _summary_to_dict(summary: RunSummary) -> dict:
    """Serialize a RunSummary into a stable, render-friendly JSON shape."""
    sync = summary.synced
    return {
        "correlationId": summary.correlation_id,
        "aborted": summary.aborted,
        "retiredCounts": summary.retired_counts,
        "sync": {
            "attempted": sync is not None,
            "unchanged": summary.sync_unchanged,
            "blockedReason": summary.sync_blocked_reason,
            "submitted": sync.submitted_count if sync else 0,
            "upserted": sync.upserted_count if sync else 0,
            "retired": sync.retired_count if sync else 0,
            "retiredItemIds": list(sync.retired_item_ids) if sync else [],
            "failed": [
                {"itemId": f.item_id, "reason": f.reason} for f in sync.failed_items
            ]
            if sync
            else [],
        },
        # Scopes this run vouched for: absence here was allowed to mean deletion.
        "authoritativeScopes": [
            {
                "environmentId": s.environment_id, "kind": s.kind.discriminator,
                **({"botId": s.bot_id} if s.bot_id else {}),
            }
            for s in summary.authoritative_scopes
        ],
        "completedScopes": [
            {
                "environmentId": s.environment_id, "kind": s.kind.discriminator,
                **({"botId": s.bot_id} if s.bot_id else {}),
            }
            for s in summary.completed_scopes
        ],
        "scopes": [
            {
                "environmentId": r.scope.environment_id,
                "kind": r.scope.kind.discriminator,
                **({"botId": r.scope.bot_id} if r.scope.bot_id else {}),
                "enumerated": r.enumerated,
                "mapped": r.mapped,
                "skippedInvalid": r.skipped_invalid,
                "capped": r.capped,
                "droppedAttributes": r.dropped_attributes,
                "complete": r.complete,
                "authoritative": r.authoritative,
                "error": r.error,
            }
            for r in summary.scopes
        ],
        "totals": {
            "kindsCrawled": len({r.scope.kind for r in summary.scopes}),
            "enumerated": sum(r.enumerated for r in summary.scopes),
            "mapped": sum(r.mapped for r in summary.scopes),
            "carriedForward": summary.carried_forward,
            "submitted": len(summary.payload),
            "skippedInvalid": sum(r.skipped_invalid for r in summary.scopes),
            "incompleteScopes": sum(1 for r in summary.scopes if not r.complete),
            "cappedScopes": sum(1 for r in summary.scopes if r.capped),
            "retired": sync.retired_count if sync else 0,
        },
    }


def _discovered_from_inventory(inventory) -> dict:
    """Group the run's applied items by kind for the results JSON.

    Reads the recorder rather than the server, so the payload shows exactly what this
    crawl observed (natural key + §5.3 attributes + state) in both write modes.
    """
    out: dict[str, list[dict]] = {}
    for stored in inventory.items.values():
        out.setdefault(stored.kind.discriminator, []).append(
            {
                "naturalKey": stored.natural_key,
                "attributes": stored.attributes,
                "state": stored.state,
            }
        )
    for rows in out.values():
        rows.sort(key=lambda r: r["naturalKey"])
    return out


def _load_prior_inventory(path: str) -> dict | None:
    """Read the existing local mirror if present; treat any problem as 'no prior'."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def _atomic_write_json(path: str, doc: dict) -> None:
    """Write ``doc`` to ``path`` atomically (temp file in the same dir + os.replace)."""
    out_dir = os.path.dirname(path) or "."
    os.makedirs(out_dir, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp, path)


def _persist_local_inventory(inventory, summary, *, tenant_id, mode, write_path, path):
    """Merge this run into the durable local mirror and update the config pointer."""
    prior = _load_prior_inventory(path)
    doc = build_document(
        prior,
        list(inventory.items.values()),
        summary,
        tenant_id=tenant_id,
        mode=mode,
        write_path=write_path,
    )
    _atomic_write_json(path, doc)

    # Best-effort config pointer -- never fatal, but never silent either: a pointer
    # that quietly fails to move leaves later runs reading a stale inventoryPath with
    # nothing in the output to explain why.
    config_path = os.path.join(".local", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        # No config yet is the normal state for a first run, not a problem to report.
        cfg = None
    except (OSError, ValueError) as exc:
        print(
            f"note: could not read {config_path} to update the inventory pointer "
            f"({exc}); the mirror at {path} is still current.",
            file=sys.stderr,
        )
        cfg = None
    if cfg is not None and not isinstance(cfg, dict):
        print(
            f"note: {config_path} is not a JSON object, so the inventory pointer was "
            f"left alone; the mirror at {path} is still current.",
            file=sys.stderr,
        )
    elif isinstance(cfg, dict):
        cfg["inventoryPath"] = path
        cfg["inventoryUpdatedAt"] = doc["updatedAt"]
        try:
            _atomic_write_json(config_path, cfg)
        except (OSError, ValueError, TypeError) as exc:
            print(
                f"note: could not write the inventory pointer into {config_path} "
                f"({exc}); the mirror at {path} is still current.",
                file=sys.stderr,
            )
    return doc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="discover_inventory.py",
        description="Run the tenant inventory discovery crawl and write results JSON.",
    )
    parser.add_argument("--tenant-id", required=True, help="Tenant identifier to crawl.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run against in-memory fakes (until live API/clients are wired).",
    )
    parser.add_argument(
        "--json-out",
        default=DEFAULT_JSON_OUT,
        help=f"Path to write the results JSON (default: {DEFAULT_JSON_OUT}).",
    )
    parser.add_argument(
        "--inventory-out",
        default=DEFAULT_INVENTORY_OUT,
        help=(
            "Path to the durable local inventory mirror, merged across runs "
            f"(default: {DEFAULT_INVENTORY_OUT})."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Override the WeveNova Inventory API origin (default: "
            f"{DEFAULT_INVENTORY_BASE_URL}). Falls back to {ENV_BASE_URL}. "
            "Mutually exclusive with --local-only."
        ),
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help=(
            "Opt out of persisting: crawl, validate, and update the local mirror "
            "without writing to the WeveNova Inventory API. By default a run DOES "
            "persist to the service."
        ),
    )
    parser.add_argument(
        "--insecure-skip-tls-verify",
        action="store_true",
        help=(
            "Force TLS certificate verification off. Not needed for a local dev "
            "tunnel (https://localhost:444): verification already follows the target, "
            "so loopback hosts are not verified and every other host is. Use this only "
            "to reach a non-local host with an untrusted certificate."
        ),
    )
    parser.add_argument(
        "--via-mcp",
        action="store_true",
        help=(
            "Deprecated no-op, accepted so existing commands keep working. The "
            "ess-planner MCP server is now the only live write path; --local-only is "
            "the opt-out."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=(
            "Suppress the live progress narration on stderr. The final status JSON on "
            "stdout is unaffected."
        ),
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=DEFAULT_HEARTBEAT_SECONDS,
        help=(
            "How long the run may stay silent before printing a 'still working' line. "
            f"0 disables the heartbeat (default: {DEFAULT_HEARTBEAT_SECONDS:g})."
        ),
    )
    args = parser.parse_args(argv)

    # Anonymous capability telemetry, emitted here -- right after argparse
    # succeeds, so `--help` and bad arguments don't count -- rather than at the
    # end. The "Capability Usage by Type" donut measures that a maker *used*
    # /discover, not whether the crawl happened to succeed; gating the emit on
    # a clean exit would silently undercount precisely the runs worth looking
    # into. Demo runs count too: they still represent a maker driving the skill.
    #
    # This is the ONLY capability emit for /discover, and deliberately so. It is
    # NOT also wired through scripts/emit_capability.py: emit_capability_use()
    # does not dedupe, so a SKILL.md shim step layered on top of this would
    # double-count every single run. The shim exists for skills that have no
    # script to hook -- /discover always runs this one.
    try:
        import adk_telemetry

        # block=True: short-lived CLI process, emit synchronously so the event
        # isn't dropped when the interpreter exits and kills a daemon thread.
        adk_telemetry.emit_capability_use("discover", block=True)
    except Exception:  # noqa: BLE001 — telemetry must never break the flow
        pass

    config = DiscoveryConfig()
    _, local_only = _resolve_write_mode(args)

    # Warn about the origin that will actually be contacted. The ess-planner MCP server
    # opens the socket, not this process, and only against an explicitly supplied base
    # URL -- otherwise it uses its own dev-tunnel default, a host this process cannot
    # name, so there is nothing to warn about.
    tls_target = args.base_url or os.environ.get(ENV_BASE_URL)

    if args.insecure_skip_tls_verify and tls_target:
        if not is_loopback_url(tls_target):
            host = urlparse(tls_target).hostname or ""
            print(
                f"WARNING: --insecure-skip-tls-verify disables certificate "
                f"verification against {host}, which is not a local host. This "
                "exposes the bearer token to interception.",
                file=sys.stderr,
            )

    # Narrate to stderr, not stdout: the final status JSON on stdout is a contract, and
    # a crawl is otherwise silent for minutes while it signs in and POSTs every row --
    # which reads as a hung command to anyone (or anything) watching the terminal.
    progress = (
        NullProgressReporter()
        if args.quiet
        else ConsoleProgressReporter(
            sys.stderr, heartbeat_seconds=max(0.0, args.heartbeat_seconds)
        )
    )
    progress.start()

    # Bound before the try so the cleanup below is safe even if the client is never
    # built -- an UnboundLocalError there would replace the real diagnostic with a
    # bogus one, at the exact moment the operator most needs the real one.
    inner = None
    try:
        if args.demo:
            progress.phase("Loading sample tenant data")
            platform, env_id = _demo_platform_and_inventory()
            mode = "demo"
        else:
            progress.phase("Signing in to Power Platform")
            platform, env_id = _live_platform()
            mode = "live-crawl"
        environment_ids = [env_id]

        progress.phase("Checking where the inventory will be recorded")
        source_error = (
            _source_tenant_error(platform, args.tenant_id)
            if not args.demo and not local_only
            else None
        )
        inner, write_path, degraded_reason = _build_inventory_client(
            local_only or bool(source_error),
            args.tenant_id,
            config,
            args.insecure_skip_tls_verify,
            args.base_url or os.environ.get(ENV_BASE_URL),
        )
        degraded_reason = source_error or degraded_reason
        if degraded_reason:
            progress.phase(
                "The inventory service is unavailable; recording locally only"
            )
        inventory = RecordingInventoryClient(inner)

        skill = DiscoverySkill(
            platform, inventory, config=config, progress=progress,
            run_lock=(
                FileRunLock(_run_lock_dir(), ttl_seconds=config.run_lock_ttl_seconds)
                if not local_only and not degraded_reason else None
            ),
        )

        aborted = False
        try:
            summary = skill.discover(
                args.tenant_id.strip().casefold(), environment_ids=environment_ids
            )
        except Exception as exc:  # crash path: nothing synced (crawler guarantees this)
            aborted = True
            summary = RunSummary(correlation_id="unknown")
            summary.aborted = True
            result = _summary_to_dict(summary)
            result["fatalError"] = str(exc)
        else:
            if summary.sync_unchanged:
                # The skipped sync sent nothing for the recorder to capture, yet the
                # service provably holds this payload. Record it before the results and
                # the mirror read the recorder, or both would show an empty tenant.
                inventory.record_unchanged(summary.payload)
            result = _summary_to_dict(summary)
    finally:
        progress.stop()
        # Release the write path here rather than after the summary is assembled:
        # everything below this point is pure local bookkeeping, and a failure in it
        # (full disk, bad path, a malformed prior mirror) must not strand the MCP
        # subprocess or leak the pooled HTTP connection.
        close = getattr(inner, "close", None)
        if callable(close):
            close()

    result["mode"] = mode
    result["tenantId"] = args.tenant_id
    result["discovered"] = _discovered_from_inventory(inventory)
    result["writePath"] = write_path
    result["writeDegraded"] = degraded_reason is not None
    # A withheld sync is not a write-path failure: the service was reachable, but this
    # crawl could not describe the tenant safely enough to submit a whole-inventory
    # payload. Surfaced separately so the operator does not chase a connectivity bug.
    withheld = result["sync"]["blockedReason"] if not aborted else ""
    if withheld:
        result["syncWithheldNote"] = (
            "SYNC WITHHELD: the tenant inventory was NOT updated. Under the "
            "whole-inventory contract, anything the payload omits is retired, so the "
            "crawler refuses to submit a payload it cannot vouch for. Reason: "
            f"{withheld}. Nothing was deleted; re-run once the cause is resolved."
        )
    if degraded_reason:
        result["writePathNote"] = (
            "WRITE FAILED: the WeveNova Inventory API could not be used, so discovered "
            "items were mirrored locally only and the tenant inventory was NOT "
            f"updated. Reason: {degraded_reason}. The crawl itself succeeded and the "
            "local mirror is up to date; re-run once the write path works to persist "
            "these results."
        )
    elif write_path == "local-only":
        result["writePathNote"] = (
            "--local-only was requested, so discovered items were mirrored locally "
            "and NOT persisted to the WeveNova Inventory API."
        )

    out_path = os.path.abspath(args.json_out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    # Merge into the durable local mirror. Skip on abort so a partial/crashed run
    # never overwrites the last good picture (matching the "no sync on abort" rule).
    inventory_written = None
    if not (aborted or result["aborted"]):
        inventory_written = args.inventory_out
        _persist_local_inventory(
            inventory,
            summary,
            tenant_id=args.tenant_id,
            mode=mode,
            write_path=result.get("writePath", "local-only"),
            path=args.inventory_out,
        )
    print(
        json.dumps(
            {
                "status": "aborted" if (aborted or result["aborted"]) else "ok",
                "correlationId": result["correlationId"],
                "resultsPath": args.json_out,
                "inventoryPath": inventory_written,
                "writePath": write_path,
                "writeDegraded": degraded_reason is not None,
                "syncWithheld": bool(withheld),
                "syncUnchanged": result["sync"]["unchanged"],
                "submitted": result["totals"]["submitted"],
                "carriedForward": result["totals"]["carriedForward"],
                "incompleteScopes": result["totals"]["incompleteScopes"],
                "retired": result["retiredCounts"],
            }
        )
    )
    if degraded_reason:
        # Loud on stderr so it survives a caller that only parses stdout JSON.
        print(f"WRITE FAILED: {degraded_reason}", file=sys.stderr)
    if withheld:
        print(f"SYNC WITHHELD: {withheld}", file=sys.stderr)
    if aborted or result["aborted"]:
        return 1
    # The crawl succeeded but the inventory was not updated. Exit non-zero so
    # automation notices; the local mirror was still written.
    return 2 if (degraded_reason or withheld) else 0


if __name__ == "__main__":
    sys.exit(main())
