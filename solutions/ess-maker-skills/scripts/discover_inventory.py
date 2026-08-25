# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Tenant Inventory Discovery (crawl) wrapper

Thin bridge that runs the admin-run tenant-inventory crawler implemented in
``tools/tenant-inventory-discovery`` and writes a results JSON the /discover
skill renders. This is the script the ``src/skills/discover/SKILL.md`` invokes.

The crawler enumerates a tenant's shared agent resources across eight kinds
(Environment, EntraApp, Connector, Connection, SharePointSite, KnowledgeSource,
ExtensionPack, ScenarioTemplate) and upserts each to the WeveNova Inventory API,
then signals a scoped server-side reconcile. The crawl is always scoped to the
**single environment configured during /setup** -- there is no full-tenant crawl.
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
     scope (and excluded from reconcile) rather than aborting the run.

   Write path (persisting is the default -- it is the point of a discovery pass):

   - default        -> the local WeveNova MCP server (``src/mcp/wevenova/server.py``),
     which proxies to the Inventory API at ``https://substrate.office.com/weveb2``.
     Override the origin with ``--base-url`` or ``WEVENOVA_BASE_URL`` for other rings
     and dev tunnels. The server resolves its own token: ``WEVENOVA_ACCESS_TOKEN``,
     else the saved ``.local/wevenova_token`` file, else a local PowerShell mint. This
     is the default because it is the only path that reads the saved token file, so it
     needs no interactive sign-in.
   - ``--direct``     -> call the Inventory API from this process instead. Acquires its
     own token from ``WEVENOVA_ACCESS_TOKEN``, else the kit's standard MSAL interactive
     sign-in against the shared ``.local/.token_cache.bin``. Does **not** read
     ``.local/wevenova_token``.
   - ``--local-only`` -> explicit opt-out: crawl, validate, and update the local
     mirror without contacting the service.

   The live path is pre-flighted before the crawl starts. If the endpoint is
   unreachable or the token is rejected, the run **degrades** to the local mirror,
   reports ``writeDegraded`` with the reason, and exits ``2`` -- the crawl results are
   still saved, but the run never claims to have persisted anything it did not.

   .. warning::
      The live write path needs the calling app id to be admitted by the service's
      ``ManageAgentConfigurationFromAuthorizedApp`` policy, which admits a single
      first-party app (Sydney). A token minted by this CLI is therefore rejected with
      403 -- which is why ``--direct`` generally degrades, and why the default path
      relies on a supplied token instead.

Exit codes:
   0 = crawl succeeded and the inventory was updated (or --local-only was requested)
   1 = the run aborted; nothing was reconciled and the local mirror was left untouched
   2 = the crawl succeeded but the inventory could not be updated (see writePathNote)

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
    ENV_ACCESS_TOKEN,
    ENV_BASE_URL,
    INVENTORY_SCOPE,
    DiscoveryConfig,
    is_loopback_url,
)
from tenant_inventory_discovery.discovery_skill import DiscoverySkill  # noqa: E402
from tenant_inventory_discovery.local_store import build_document  # noqa: E402
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
# transient results JSON, this file is merged across runs with the same per-scope
# reconcile semantics the server uses, so it stays a faithful offline picture.
DEFAULT_INVENTORY_OUT = os.path.join(".local", "inventory.json")

# Demo mode has no config, so it crawls this one representative environment (the tool
# only ever crawls a single environment -- there is no full-tenant crawl).
_DEMO_ENV_ID = "env-prod"

# First-party public client used across the kit (auth.py, flightcheck/*_client.py).
# Shares .local/.token_cache.bin, so a prior Dataverse sign-in often satisfies the
# Inventory API silently.
_MSAL_CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"


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

    Reading only the documented top-level `entraAppId` leaves the `EntraApp` scope
    permanently **Incomplete** even on a fully connected tenant, because the connect
    playbooks persist it elsewhere: Workday as `entraAppId` in
    `.local/connect/workday/config.json`, ServiceNow as `entra.appClientId` in
    `.local/connect/servicenow/config.json`. FlightCheck hit the same config drift and
    works around it the same way -- see
    `flightcheck/checks/_workday_app_assignment.py::_workday_hints`.

    Returns ``None`` when no connector has been connected yet. That is a legitimate
    state, not an error: there is simply no app registration to discover, and the
    caller reports the scope incomplete so nothing is retired for it.

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


def _live_platform():
    """Build the live Dataverse-backed platform (default crawl source).

    Reuses the kit's ``scripts/auth.py`` (delegated admin sign-in + paged Web API
    queries) via :class:`DataverseBackedPlatform`. The setup config binds a **single**
    environment (``dataverseEndpoint``); its identity is derived from that config URL
    (no environment discovery). The crawl is **always** scoped to that one environment
    -- there is no full-tenant crawl -- so the tenant-root exemption keeps the
    not-yet-wired tenant-root kinds out of reconcile (spec §6.3).
    """
    import auth
    from discover_dataverse_platform import DataverseBackedPlatform

    cfg = auth.load_config()
    env_url = cfg.get("dataverseEndpoint")
    if not env_url:
        raise SystemExit(
            "No 'dataverseEndpoint' in .local/config.json -- run /setup first."
        )

    platform = DataverseBackedPlatform(
        env_url,
        entra_app_id=_resolve_entra_app_id(cfg),
        bot_id=(cfg.get("agent") or {}).get("botId"),
    )
    return platform, platform.environment_id


def _acquire_inventory_token(tenant_id):
    """Return ``(token, source)`` for the Inventory API, or raise ``RuntimeError``.

    ``WEVENOVA_ACCESS_TOKEN`` wins when set -- it is the escape hatch for CI and for
    anyone holding a token the interactive flow cannot mint. Otherwise fall back to the
    kit's standard MSAL interactive flow against the shared ``.local/.token_cache.bin``
    cache, so a maker who already signed in for Dataverse usually gets a silent token.
    """
    token = os.environ.get(ENV_ACCESS_TOKEN)
    if token:
        return token, ENV_ACCESS_TOKEN

    try:
        import msal
    except ImportError as exc:  # pragma: no cover - msal is a kit dependency
        raise RuntimeError(
            f"msal is not installed and {ENV_ACCESS_TOKEN} is not set, so no "
            "Inventory API token could be acquired."
        ) from exc

    cache = msal.SerializableTokenCache()
    cache_path = os.path.join(".local", ".token_cache.bin")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as fh:
            cache.deserialize(fh.read())

    app = msal.PublicClientApplication(
        _MSAL_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent([INVENTORY_SCOPE], account=accounts[0])
    if not result or "access_token" not in result:
        print("Opening browser for WeveNova Inventory API sign-in...")
        result = app.acquire_token_interactive(
            [INVENTORY_SCOPE], prompt="select_account"
        )

    if "access_token" not in result:
        # Don't echo error_description: it can carry tenant ids and internal flow
        # details (CWE-209). Mirrors the auth.py / graph_client.py pattern.
        raise RuntimeError(
            f"Inventory API authentication failed "
            f"({result.get('error', 'unknown_error')})."
        )

    if cache.has_state_changed:
        os.makedirs(".local", exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(cache_path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(cache.serialize())

    return result["access_token"], "interactive sign-in"


def _build_inventory_client(
    base_url,
    local_only,
    tenant_id,
    config,
    insecure=False,
    via_mcp=False,
    explicit_base=None,
):
    """Pick the write path and return ``(client, write_path_label, degraded_reason)``.

    Persisting to WeveNova is the default: a discovery pass exists to update the
    tenant inventory, so writing is the intent and ``--local-only`` is the explicit
    opt-out. When the live path cannot be used the run does *not* silently succeed --
    it falls back to the local mirror, reports the failure, and exits non-zero.

    The live path is pre-flighted before the crawl so an unusable endpoint or a
    rejected token surfaces immediately instead of on the first upsert, after minutes
    of enumeration.
    """
    from tenant_inventory_discovery.in_memory_inventory import InMemoryInventoryClient

    if local_only:
        return InMemoryInventoryClient(caps=config.caps), "local-only", None

    if via_mcp:
        return _build_mcp_client(explicit_base, tenant_id, config, insecure)

    from tenant_inventory_discovery.inventory_client import HttpInventoryClient

    try:
        token, source = _acquire_inventory_token(tenant_id)
    except Exception as exc:  # noqa: BLE001 - degrade, never abort the crawl
        return (
            InMemoryInventoryClient(caps=config.caps),
            "local-only",
            f"could not acquire a token ({exc})",
        )

    config.inventory_base_url = base_url
    client = HttpInventoryClient(
        tenant_id,
        config=config,
        auth_token_provider=lambda: token,
        verify=not (insecure or is_loopback_url(base_url)),
    )
    try:
        client.probe()
    except Exception as exc:  # noqa: BLE001 - degrade, never abort the crawl
        client.close()
        return (
            InMemoryInventoryClient(caps=config.caps),
            "local-only",
            f"{base_url} rejected the pre-flight request using the token from "
            f"{source} ({exc}){_tls_hint(exc, insecure)}",
        )

    return client, base_url, None


def _build_mcp_client(explicit_base, tenant_id, config, insecure):
    """Route writes through the local WeveNova MCP server. This is the default path.

    The server resolves its own token (``WEVENOVA_ACCESS_TOKEN``, else the saved
    ``.local/wevenova_token`` file, else a local PowerShell mint) and handles the dev
    tunnel's self-signed certificate, so this path needs no interactive sign-in.
    Configuration is passed through the child's environment because that is the
    server's only input surface.

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
    return {
        "correlationId": summary.correlation_id,
        "passStartedAt": (
            summary.pass_started_at.isoformat() if summary.pass_started_at else None
        ),
        "aborted": summary.aborted,
        "retiredCounts": summary.retired_counts,
        "reconciled": [
            {
                "kind": r.kind.discriminator,
                "environmentId": r.environment_id,
                "evaluated": r.evaluated_count,
                "retired": r.retired_count,
            }
            for r in summary.reconciled
        ],
        "completedScopes": [
            {"environmentId": s.environment_id, "kind": s.kind.discriminator}
            for s in summary.completed_scopes
        ],
        "scopes": [
            {
                "environmentId": r.scope.environment_id,
                "kind": r.scope.kind.discriminator,
                "enumerated": r.enumerated,
                "upserted": r.upserted,
                "skippedInvalid": r.skipped_invalid,
                "capped": r.capped,
                "droppedAttributes": r.dropped_attributes,
                "retiredItemIds": r.retired_item_ids,
                "complete": r.complete,
                "error": r.error,
            }
            for r in summary.scopes
        ],
        "totals": {
            "kindsCrawled": len({r.scope.kind for r in summary.scopes}),
            "enumerated": sum(r.enumerated for r in summary.scopes),
            "upserted": sum(r.upserted for r in summary.scopes),
            "skippedInvalid": sum(r.skipped_invalid for r in summary.scopes),
            "incompleteScopes": sum(1 for r in summary.scopes if not r.complete),
            "cappedScopes": sum(1 for r in summary.scopes if r.capped),
            "retired": sum(len(r.retired_item_ids) for r in summary.scopes),
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

    # Best-effort config pointer -- never fatal.
    config_path = os.path.join(".local", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        if isinstance(cfg, dict):
            cfg["inventoryPath"] = path
            cfg["inventoryUpdatedAt"] = doc["updatedAt"]
            _atomic_write_json(config_path, cfg)
    except (OSError, ValueError):
        pass
    return doc


def _resolve_write_path(args):
    """Settle ``args.via_mcp`` from the write-path flags, rejecting contradictions.

    The MCP server is the default because it is the only path that reads the saved
    ``.local/wevenova_token`` file. The direct path acquires its own token, and the app
    id it can mint for is not admitted by the service's authorization policy, so
    defaulting to it makes an ordinary run degrade to the local mirror and exit 2.

    ``--via-mcp`` predates the flip and is now a no-op, kept so existing commands and
    docs keep working rather than failing on an unrecognized argument.
    """
    if args.via_mcp and args.direct:
        raise SystemExit("--via-mcp conflicts with --direct. Pick one write path.")
    if args.direct and args.local_only:
        raise SystemExit(
            "--direct conflicts with --local-only. Pick one write destination."
        )
    args.via_mcp = not args.direct
    return args


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
            "Deprecated and now the default; accepted so existing commands keep "
            "working. Use --direct to opt out."
        ),
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help=(
            "Call the Inventory API directly instead of going through the local "
            "WeveNova MCP server. The direct path acquires its own token "
            "(WEVENOVA_ACCESS_TOKEN, else an interactive MSAL sign-in) and does NOT "
            "read .local/wevenova_token."
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
    _resolve_write_path(args)

    config = DiscoveryConfig()
    base_url, local_only = _resolve_write_mode(args)

    # Warn about the origin that will actually be contacted. Under --via-mcp the bridge
    # opens no socket itself: the server does, against its own default unless an
    # explicit base URL was forwarded. Naming the bridge's production default here
    # would warn about a host nothing is going to talk to.
    tls_target = base_url
    if args.via_mcp:
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
        inner, write_path, degraded_reason = _build_inventory_client(
            base_url,
            local_only,
            args.tenant_id,
            config,
            args.insecure_skip_tls_verify,
            args.via_mcp,
            args.base_url or os.environ.get(ENV_BASE_URL),
        )
        if degraded_reason:
            progress.phase(
                "The inventory service is unavailable; recording locally only"
            )
        inventory = RecordingInventoryClient(inner)

        skill = DiscoverySkill(
            platform, inventory, config=config, progress=progress
        )

        aborted = False
        try:
            summary = skill.discover(args.tenant_id, environment_ids=environment_ids)
        except Exception as exc:  # crash path: nothing reconciled (crawler guarantees this)
            aborted = True
            summary = RunSummary(correlation_id="unknown")
            summary.aborted = True
            result = _summary_to_dict(summary)
            result["fatalError"] = str(exc)
        else:
            result = _summary_to_dict(summary)
    finally:
        progress.stop()

    result["mode"] = mode
    result["tenantId"] = args.tenant_id
    result["discovered"] = _discovered_from_inventory(inventory)
    result["writePath"] = write_path
    result["writeDegraded"] = degraded_reason is not None
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
    # never overwrites the last good picture (matching the "no reconcile on abort" rule).
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
    # Release the write path before reporting: for --via-mcp this shuts down the
    # server subprocess, and for the HTTP path it returns the pooled connection.
    close = getattr(inner, "close", None)
    if callable(close):
        close()

    print(
        json.dumps(
            {
                "status": "aborted" if (aborted or result["aborted"]) else "ok",
                "correlationId": result["correlationId"],
                "resultsPath": args.json_out,
                "inventoryPath": inventory_written,
                "writePath": write_path,
                "writeDegraded": degraded_reason is not None,
                "upserted": result["totals"]["upserted"],
                "incompleteScopes": result["totals"]["incompleteScopes"],
                "retired": result["retiredCounts"],
            }
        )
    )
    if degraded_reason:
        # Loud on stderr so it survives a caller that only parses stdout JSON.
        print(f"WRITE FAILED: {degraded_reason}", file=sys.stderr)
    if aborted or result["aborted"]:
        return 1
    # The crawl succeeded but the inventory was not updated. Exit non-zero so
    # automation notices; the local mirror was still written.
    return 2 if degraded_reason else 0


if __name__ == "__main__":
    sys.exit(main())
