# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Infrastructure & Security (INFRA-xxx)

Extensible module for infrastructure pre-deployment checks. Currently
implements:
  - INFRA-001: Inbound connectivity to Microsoft services
  - INFRA-003: External endpoint reachability (Workday / ServiceNow / SAP /
    custom HTTP) — probes from the Power Platform environment's OWN egress
    via the opt-in --runtime-reachability flow (the kit's only mutating
    path); when that probe is unavailable it returns MANUAL guidance
    instead of a local probe

Adding a new INFRA-xxx check:
  1. Define a target discovery function or whatever inputs your check needs.
  2. Define a ``check_<descriptive_name>(runner) -> list[CheckResult]``
     orchestrator that discovers targets, probes/validates, and returns
     CheckResults using the shared helpers below.
  3. Register your orchestrator in ``_INFRA_CHECKS`` at the bottom of this
     file so ``run_infrastructure_checks()`` picks it up automatically.
  4. Add corresponding tests in ``tests/flightcheck/checks/test_infrastructure.py``.

Shared utilities available to all INFRA-xxx checks:
  - ProbeResult / probe_endpoint() — layer-by-layer TCP probe
  - _probe_to_check_result() — maps ProbeResult → CheckResult
  - _host_from_url() — extracts hostname from a URL

Design constraints (apply to all checks in this module):
  - Read-only and idempotent (AC7). No mutations, no credentials.
  - Python stdlib only (socket + ssl). No external dependencies.
  - No application-level data sent — only TCP SYN + TLS ClientHello.
"""

from __future__ import annotations

import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from auth import query_all  # scripts/auth.py, on path via cli.py
from ..runner import CheckResult, Priority, Role, Status
from .. import live_egress_probe
from .. import consent
from ._dlp_utils import (
    agent_connector_ids,
    evaluate_connector_classification,
    iter_effective_policies,
    policy_label,
    ppac_dlp_policies_url,
)


# ═══════════════════════════════════════════════════════════════════════
# SHARED UTILITIES — available to all INFRA-xxx checks
# ═══════════════════════════════════════════════════════════════════════


# ───────────────────────────────────────────────────────────────────────
# ProbeResult dataclass
# ───────────────────────────────────────────────────────────────────────


@dataclass
class ProbeResult:
    """Layer-by-layer network probe outcome."""

    host: str
    port: int
    dns_ok: bool = False
    tcp_ok: bool = False
    tls_ok: bool = False
    resolved_ip: str | None = None
    dns_ms: float = 0.0
    tcp_ms: float = 0.0
    tls_ms: float = 0.0
    tls_version: str | None = None
    error_layer: str | None = None  # "dns", "tcp", or "tls"
    error_message: str | None = None


# ───────────────────────────────────────────────────────────────────────
# probe_endpoint — the core network probe (reusable by all INFRA checks)
# ───────────────────────────────────────────────────────────────────────


def probe_endpoint(host: str, port: int = 443, timeout: float = 10.0) -> ProbeResult:
    """Probe network reachability layer-by-layer: DNS → TCP → TLS.

    Each layer depends on the previous succeeding. Stops at first failure.
    Read-only: no application data sent beyond TCP SYN and TLS ClientHello.
    """
    result = ProbeResult(host=host, port=port)

    # Layer 1: DNS resolution
    t0 = time.perf_counter()
    try:
        addr_info = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if not addr_info:
            result.error_layer = "dns"
            result.error_message = f"No address records returned for {host}"
            return result
        result.resolved_ip = addr_info[0][4][0]
        result.dns_ok = True
        result.dns_ms = round((time.perf_counter() - t0) * 1000, 1)
    except socket.gaierror as exc:
        result.error_layer = "dns"
        result.error_message = f"DNS resolution failed for {host}: {exc}"
        result.dns_ms = round((time.perf_counter() - t0) * 1000, 1)
        return result

    # Layer 2: TCP connect — try each resolved address (handles dual-stack /
    # broken IPv6 by falling through to IPv4 on ENETUNREACH or similar).
    t0 = time.perf_counter()
    sock = None
    last_err: OSError | None = None
    for family, socktype, proto, _canonname, sockaddr in addr_info:
        s = socket.socket(family, socktype, proto)
        s.settimeout(timeout)
        # Track the address being attempted so failure messages report the correct IP.
        result.resolved_ip = sockaddr[0]
        try:
            s.connect(sockaddr)
            sock = s
            break
        except OSError as exc:
            last_err = exc
            s.close()

    if sock is None:
        # All addresses failed — report the last error
        result.tcp_ms = round((time.perf_counter() - t0) * 1000, 1)
        if isinstance(last_err, socket.timeout):
            result.error_layer = "tcp"
            result.error_message = (
                f"TCP connection to {host}:{port} ({result.resolved_ip}) "
                f"timed out after {timeout}s — firewall may be silently dropping packets"
            )
        elif isinstance(last_err, ConnectionRefusedError):
            result.error_layer = "tcp"
            result.error_message = (
                f"TCP connection to {host}:{port} ({result.resolved_ip}) refused — "
                f"port closed or firewall sending RST"
            )
        else:
            result.error_layer = "tcp"
            result.error_message = f"TCP connection to {host}:{port} failed: {last_err}"
        return result

    result.tcp_ok = True
    result.tcp_ms = round((time.perf_counter() - t0) * 1000, 1)

    # Layer 3: TLS handshake
    t0 = time.perf_counter()
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            result.tls_ok = True
            result.tls_version = ssock.version()
            result.tls_ms = round((time.perf_counter() - t0) * 1000, 1)
    except ssl.SSLError as exc:
        result.error_layer = "tls"
        result.error_message = f"TLS handshake failed for {host}:{port}: {exc}"
        result.tls_ms = round((time.perf_counter() - t0) * 1000, 1)
    except OSError as exc:
        result.error_layer = "tls"
        result.error_message = f"TLS handshake error for {host}:{port}: {exc}"
        result.tls_ms = round((time.perf_counter() - t0) * 1000, 1)
    finally:
        sock.close()

    return result


# ───────────────────────────────────────────────────────────────────────
# _probe_to_check_result — maps ProbeResult → CheckResult (reusable)
# ───────────────────────────────────────────────────────────────────────

_DOC_LINK_INFRA_001 = (
    "https://learn.microsoft.com/en-us/power-platform/admin/online-requirements"
)


def _probe_to_check_result(
    checkpoint_id: str,
    target_name: str,
    probe: ProbeResult,
    *,
    doc_link: str,
    roles: list[str],
    accuracy_note: str = "",
) -> CheckResult:
    """Map a ProbeResult to a CheckResult with Shared Steps wording."""
    host_port = f"{probe.host}:{probe.port}"
    category = "Infrastructure"

    if probe.dns_ok and probe.tcp_ok and probe.tls_ok:
        # All layers passed
        note = f" {accuracy_note}" if accuracy_note else ""
        return CheckResult(
            checkpoint_id=checkpoint_id,
            category=category,
            priority=Priority.CRITICAL.value,
            status=Status.PASSED.value,
            description=f"Network connectivity to {target_name}",
            result=(
                f"{target_name} ({host_port}): Reachable. "
                f"DNS: {probe.dns_ms}ms → TCP: {probe.tcp_ms}ms → "
                f"{probe.tls_version or 'TLS'}: {probe.tls_ms}ms.{note}"
            ),
            doc_link=doc_link,
            roles=roles,
        )

    if probe.error_layer == "dns":
        return CheckResult(
            checkpoint_id=checkpoint_id,
            category=category,
            priority=Priority.CRITICAL.value,
            status=Status.FAILED.value,
            description=f"Network connectivity to {target_name}",
            result=(
                f"{target_name} ({host_port}): UNREACHABLE. "
                f"DNS resolution failed ({probe.dns_ms}ms)."
            ),
            remediation=(
                f"Impact: The hostname '{probe.host}' cannot be resolved from this "
                f"network. All services depending on {target_name} will be unreachable.\n\n"
                f"Probable cause: The hostname is incorrect, corporate DNS does not "
                f"have a record for it (split-horizon DNS), or DNS is misconfigured.\n\n"
                f"Next steps:\n"
                f"1. Verify the hostname is correct.\n"
                f"2. Check DNS settings with your network team.\n"
                f"3. Re-run /flightcheck --scope infrastructure."
            ),
            doc_link=doc_link,
            roles=roles,
        )

    if probe.error_layer == "tcp":
        ip_info = f" DNS resolved to {probe.resolved_ip} ({probe.dns_ms}ms)." if probe.resolved_ip else ""
        return CheckResult(
            checkpoint_id=checkpoint_id,
            category=category,
            priority=Priority.CRITICAL.value,
            status=Status.FAILED.value,
            description=f"Network connectivity to {target_name}",
            result=(
                f"{target_name} ({host_port}): UNREACHABLE.{ip_info} "
                f"TCP connection failed ({probe.tcp_ms}ms): {probe.error_message}"
            ),
            remediation=(
                f"Impact: No TCP connectivity to {target_name}. Services depending "
                f"on this endpoint will fail at runtime.\n\n"
                f"Probable cause: A firewall between this network and the target is "
                f"blocking or rejecting TCP connections on port {probe.port}.\n\n"
                f"Next steps:\n"
                f"1. Share this result with your network / InfoSec team.\n"
                f"2. Request allowlisting of HTTPS (port {probe.port}) traffic to {probe.host}.\n"
                f"3. Re-run /flightcheck --scope infrastructure."
            ),
            doc_link=doc_link,
            roles=roles,
        )

    # TLS failure — TCP connectivity exists but TLS negotiation failed
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category=category,
        priority=Priority.CRITICAL.value,
        status=Status.WARNING.value,
        description=f"Network connectivity to {target_name}",
        result=(
            f"{target_name} ({host_port}): Partially reachable. "
            f"DNS: {probe.dns_ms}ms → TCP: {probe.tcp_ms}ms → "
            f"TLS handshake FAILED ({probe.tls_ms}ms)."
        ),
        remediation=(
            f"Impact: TCP connectivity to {target_name} exists but TLS negotiation "
            f"failed. Runtime connectors may fail if the same issue affects their path.\n\n"
            f"Probable cause: A corporate proxy is intercepting HTTPS traffic, "
            f"a certificate mismatch exists, or the server requires a TLS version "
            f"not supported by this client.\n\n"
            f"Error detail: {probe.error_message}\n\n"
            f"Next steps:\n"
            f"1. Check if a proxy or WAF is intercepting HTTPS to this endpoint.\n"
            f"2. Verify the server certificate is valid and trusted.\n"
            f"3. Re-run /flightcheck --scope infrastructure."
        ),
        doc_link=doc_link,
        roles=roles,
    )


def _host_from_url(url: str | None) -> str | None:
    """Extract hostname from a URL, handling URLs with or without scheme."""
    if not url:
        return None
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    return parsed.hostname or None


def _port_from_url(url: str | None) -> int:
    """Extract the TCP port from a URL, defaulting by scheme (https→443, http→80).

    Retained after the local TCP probe was removed: the egress probe uses the
    full ``ep.url``, but ``port`` still keys endpoint de-duplication so two
    systems on the same host but different ports stay distinct (both probed).
    An explicit port in the URL (e.g. ``https://host:8443``) wins.
    """
    if not url:
        return 443
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.port:
        return parsed.port
    return 80 if (parsed.scheme or "").lower() == "http" else 443


# ═══════════════════════════════════════════════════════════════════════
# INDIVIDUAL INFRA-xxx CHECKS
#
# Each check follows the same pattern:
#   1. Discover targets (endpoints to probe)
#   2. Probe each target using shared utilities
#   3. Return list[CheckResult]
#
# After implementing, register in _INFRA_CHECKS at the bottom.
# ═══════════════════════════════════════════════════════════════════════


# ───────────────────────────────────────────────────────────────────────
# INFRA-001: Inbound connectivity to Microsoft services
#
# Probe accuracy: HIGH — maker's machine is behind the same corporate
# firewall that governs user/employee access to Microsoft 365 services.
# ───────────────────────────────────────────────────────────────────────

# Well-known Microsoft endpoints required by Power Platform / Copilot Studio.
# Source: https://learn.microsoft.com/en-us/power-platform/admin/online-requirements
_MICROSOFT_ENDPOINTS: dict[str, tuple[str, int]] = {
    "Entra ID": ("login.microsoftonline.com", 443),
    "Power Platform API": ("api.powerplatform.com", 443),
    "Power Apps API": ("api.powerapps.com", 443),
    "Power Virtual Agents": ("powerva.microsoft.com", 443),
    "Power Automate API": ("api.flow.microsoft.com", 443),
    "Microsoft Graph": ("graph.microsoft.com", 443),
}


def _discover_microsoft_service_targets(runner: Any) -> dict[str, tuple[str, int]]:
    """Assemble the list of Microsoft cloud endpoints to probe.

    Combines the well-known static endpoints (Entra, Graph, Power Platform)
    with the tenant-specific Dataverse URL from the runner's environment.
    """
    targets = dict(_MICROSOFT_ENDPOINTS)

    # Add the tenant-specific Dataverse URL from runner.env_url
    env_url = getattr(runner, "env_url", "") or ""
    host = _host_from_url(env_url)
    if host:
        targets["Dataverse"] = (host, 443)

    return targets


def check_microsoft_service_reachability(runner: Any) -> list[CheckResult]:
    """Verify the maker's machine can reach Microsoft cloud services (INFRA-001).

    Probes each required Microsoft endpoint (Entra ID, Power Platform,
    Dataverse, Copilot Studio, Microsoft Graph) with a layer-by-layer
    TCP probe. These are the services that Power Platform, Copilot Studio,
    and the ESS agent runtime depend on at deployment time and runtime.
    """
    targets = _discover_microsoft_service_targets(runner)
    results: list[CheckResult] = []

    for target_name, (host, port) in targets.items():
        probe = probe_endpoint(host, port)
        result = _probe_to_check_result(
            checkpoint_id="INFRA-001",
            target_name=target_name,
            probe=probe,
            doc_link=_DOC_LINK_INFRA_001,
            roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
        )
        results.append(result)

    env_url = getattr(runner, "env_url", "") or ""
    if not _host_from_url(env_url):
        results.append(
            CheckResult(
                checkpoint_id="INFRA-001",
                category="Infrastructure",
                priority=Priority.CRITICAL.value,
                status=Status.SKIPPED.value,
                description="Network connectivity to Dataverse",
                result="Dataverse target skipped: no Dataverse environment URL configured.",
                remediation=(
                    "Set dataverseEndpoint in .local/config.json or pass "
                    "--environment-url to include Dataverse in INFRA-001."
                ),
                doc_link=_DOC_LINK_INFRA_001,
                roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
            )
        )

    return results


# ───────────────────────────────────────────────────────────────────────
# INFRA-003: External endpoint reachability from Power Platform egress
#
# Enumerates the external system endpoints the agent's installed
# extensions use (Workday, ServiceNow, SAP SuccessFactors, custom HTTP)
# and verifies each is reachable FROM THE POWER PLATFORM ENVIRONMENT'S OWN
# EGRESS — the path the agent runtime actually uses.
#
# ONE PROBE, ONE FALLBACK (see docs/design-infra-003-endpoint-reachability.md):
#   - Egress probe (opt-in, --runtime-reachability): a transient cloud flow
#     that sends a real HTTP request from Power Platform's own egress and
#     returns the observed status code. This is the ONLY authoritative
#     signal and the kit's only tenant-mutating path.
#   - No egress probe available (flag not given, operator declined, or the
#     Dataverse / flow prerequisites are missing): the check returns MANUAL
#     guidance — re-run with --runtime-reachability, or verify allowlisting
#     manually. A local TCP/TLS probe from the maker's machine was removed
#     on purpose: it runs from the wrong network and never sends HTTP, so a
#     laptop PASS does NOT prove the runtime path.
# ───────────────────────────────────────────────────────────────────────

# Managed connectors outbound IP addresses (Power Platform egress ranges).
# Verified: same URL cited in src/reference/ess-docs/integrations/workday.md,
# .../integrations/sapsuccessfactors.md, and .../deployment/prepare.md.
_DOC_LINK_INFRA_003 = (
    "https://learn.microsoft.com/en-us/connectors/common/"
    "outbound-ip-addresses#power-platform"
)

# config.json `connections.<name>` keys that may carry an endpoint URL.
# Workday's `baseUrl` is confirmed by _resolve_workday_metadata() in
# checks/workday.py; the rest are common URL-bearing keys, whichever is present.
_EXTERNAL_SYSTEM_URL_KEYS = (
    "baseUrl", "instanceUrl", "apiUrl", "odataUrl", "url", "host", "endpoint",
)

# System-name substring → owning admin role. Unknown systems (custom HTTP)
# fall back to the Power Platform admin.
_KNOWN_SYSTEM_ROLES: tuple[tuple[str, str], ...] = (
    ("workday", Role.WORKDAY_ADMIN.value),
    ("servicenow", Role.SERVICENOW_ADMIN.value),
    ("successfactors", Role.SAP_ADMIN.value),
    ("sap", Role.SAP_ADMIN.value),
)


@dataclass
class _ExternalEndpoint:
    """One external system endpoint to probe."""

    system: str          # display name, e.g. "Workday"
    url: str             # configured endpoint URL
    host: str | None     # extracted hostname (None if unparseable)
    port: int            # TCP port (from the URL, default 443); keys dedup
    role: str            # Role enum value of the owning system admin


def _system_role(system_name: str) -> str:
    """Map a connections key (e.g. "Workday", "SAPSuccessFactors") to a role."""
    key = system_name.strip().lower().replace(" ", "").replace("-", "")
    for needle, role in _KNOWN_SYSTEM_ROLES:
        if needle in key:
            return role
    return Role.POWER_PLATFORM_ADMIN.value


def _extract_endpoint_url(entry: Any) -> str | None:
    """Return the first non-empty URL-ish value from a connections entry."""
    if isinstance(entry, str):
        return entry.strip() or None
    if not isinstance(entry, dict):
        return None
    for key in _EXTERNAL_SYSTEM_URL_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _discover_external_endpoints(runner: Any) -> list[_ExternalEndpoint]:
    """Enumerate external system endpoints from the agent's connection config.

    Endpoint URLs are not exposed on the BAP connection records (connector
    auth is configured in the Copilot Studio portal, not in code), so this
    reads the kit's own ``.local/config.json`` ``connections`` map — where the
    /connect skill records each system's non-secret endpoint metadata (e.g.
    Workday ``baseUrl``). One endpoint per configured system, de-duplicated by
    host. Read-only.
    """
    config = getattr(runner, "config", {}) or {}
    connections = config.get("connections", {})
    if not isinstance(connections, dict):
        return []

    endpoints: list[_ExternalEndpoint] = []
    seen_hosts: set[str] = set()
    for system_name, entry in connections.items():
        url = _extract_endpoint_url(entry)
        if not url:
            # A connected system with no endpoint URL recorded. Do NOT skip it
            # silently: surface it as an unverifiable endpoint (host=None) so the
            # orchestrator names it rather than dropping it. A check that claims
            # "every endpoint" must account for the ones it could not test.
            endpoints.append(
                _ExternalEndpoint(
                    system=str(system_name),
                    url="",
                    host=None,
                    port=443,
                    role=_system_role(str(system_name)),
                )
            )
            continue
        host = _host_from_url(url)
        port = _port_from_url(url)
        dedup_key = f"{(host or url).lower()}:{port}"
        if dedup_key in seen_hosts:
            continue
        seen_hosts.add(dedup_key)
        endpoints.append(
            _ExternalEndpoint(
                system=str(system_name),
                url=url,
                host=host,
                port=port,
                role=_system_role(str(system_name)),
            )
        )
    return endpoints


def _infra_003_manual_verification() -> str:
    """The manual allowlist-verification path (design Step G).

    Includes direct links to the official 'Managed connectors outbound IP
    addresses' article and the Azure service-tags / IP-ranges JSON download, so
    an operator who declines the egress probe can self-serve. Markdown link
    syntax renders clickable in report.html (runner._md_links_to_html)."""
    return (
        "Prefer to verify allowlisting manually:\n"
        "1. In the Power Platform admin center, note your environment's region.\n"
        "2. From Microsoft's [Managed connectors outbound IP addresses]"
        f"({consent.OUTBOUND_IP_ARTICLE_URL}) list, get the ranges for that "
        "region. For a custom HTTP endpoint, use the [Azure service tags / IP "
        f"ranges JSON]({consent.SERVICE_TAGS_JSON_URL}) instead.\n"
        "3. Work with your InfoSec / network team to confirm those ranges are "
        "allowlisted in the target system's firewall / WAF."
    )


def _infra_003_directive(
    *,
    cause: str,
    scope: str,
    implies: str,
    next_steps: str,
    responsible_role: str,
    probe_layer_note: str,
) -> str:
    """Assemble the five-field Shared Steps role-aware finding (design Step E / AC5).

    Fields, in the order defined by the Shared Steps output contract
    (docs/design-infra-003-endpoint-reachability.md): Probable cause /
    Configuration Area or Scope / What it implies / Next steps / Responsible
    role. The manual-verification block and the probe-layer caveat follow.
    """
    text = "\n\n".join(
        [
            f"Probable cause: {cause}",
            f"Configuration Area or Scope: {scope}",
            f"What it implies: {implies}",
            f"Next steps: {next_steps}",
            f"Responsible role: {responsible_role}",
            _infra_003_manual_verification(),
        ]
    )
    return text + "\n\n" + probe_layer_note


@dataclass
class _ProbeContext:
    """Describes whether the INFRA-003 egress probe ran, so the result text can
    state that reachability was confirmed from the Power Platform egress
    (--runtime-reachability) or explain why the probe did not run."""

    live_requested: bool = False   # --runtime-reachability flag was set
    live_ran: bool = False         # egress probe actually executed
    unavailable_reason: str = ""   # why live did not run (when requested)
    declined_by_user: bool = False  # operator declined the egress probe


def _infra_003_probe_layer_note() -> str:
    """The probe-layer annotation appended to every egress-probed INFRA-003 row.

    Only the egress probe produces reachable / unreachable rows now, so this is
    always the egress statement — the authoritative runtime path the agent
    actually uses.
    """
    return (
        "Probe layer: reachability was tested from the Power Platform "
        "environment's own egress via a transient probe flow "
        "(--runtime-reachability) — the authoritative runtime path the agent "
        "actually uses."
    )


def _infra_003_not_probed_reason(ctx: _ProbeContext) -> str:
    """Explain, on the MANUAL 'not probed' row, why the egress probe did not run."""
    if ctx.declined_by_user:
        return (
            "\n\nThe runtime-reachability egress probe was skipped by choice, so "
            "reachability from the Power Platform egress — including firewall / "
            "IP allowlisting — was NOT confirmed."
        )
    if ctx.live_requested:
        return (
            "\n\nNote: --runtime-reachability was requested but could not run "
            f"({ctx.unavailable_reason})."
        )
    return (
        "\n\nRe-run with --runtime-reachability to probe from the environment's "
        "own egress."
    )


def _infra_003_not_probed_row(
    endpoints: list[_ExternalEndpoint], ctx: _ProbeContext
) -> CheckResult:
    """One MANUAL row for when the egress probe did not run.

    The local TCP/TLS probe was removed on purpose: it runs from the maker's
    machine, not the Power Platform egress, and never sends HTTP, so it cannot
    prove the runtime path. Rather than a misleading local PASS, hand the
    operator the runtime-reachability re-run plus the manual
    allowlist-verification steps. The clickable links live in remediation (the
    linkified channel); result is escaped but not linkified.
    """
    listed = "\n".join(
        f"- {ep.system} ({ep.url})"
        if ep.url
        else f"- {ep.system} (no endpoint URL recorded)"
        for ep in endpoints
    )
    result = (
        "Reachability was NOT tested for the endpoint(s) below. FlightCheck "
        "verifies these only from the Power Platform environment's own egress "
        "— the path the agent runtime actually uses — and that egress probe "
        "did not run:\n"
        f"{listed}"
        f"{_infra_003_not_probed_reason(ctx)}"
    )
    remediation = (
        "Test reachability from the Power Platform egress by re-running with "
        "the runtime-reachability probe:\n"
        "  /flightcheck --scope infrastructure --runtime-reachability\n"
        "It stands up a transient probe flow, triggers it once from the "
        "environment's own egress, reads the HTTP status, then deletes it (the "
        "kit's only tenant-mutating step).\n\n"
        + _infra_003_manual_verification()
    )
    roles = sorted({ep.role for ep in endpoints} | {Role.POWER_PLATFORM_ADMIN.value})
    return _infra_003_row(
        status=Status.MANUAL.value,
        result=result,
        remediation=remediation,
        roles=roles,
    )


def _live_finding(
    ep: _ExternalEndpoint, res: "live_egress_probe.LiveProbeResult"
) -> tuple[str, str]:
    """Classify one endpoint from a live egress-probe result.

    Returns ``(bucket, line)`` where bucket is ``reachable`` / ``unreachable``
    / ``manual``. ``manual`` covers an indeterminate probe (``reachable is
    None`` — create / activate / trigger could not complete): there is no local
    fallback, so the operator verifies it manually.
    """
    label = f"{ep.system} ({ep.url})"
    if res.reachable is True:
        return (
            "reachable",
            f"{label}: Reachable from Power Platform egress ({res.detail}).",
        )
    if res.reachable is False:
        return (
            "unreachable",
            f"{label}: UNREACHABLE from Power Platform egress — {res.detail}.",
        )
    return (
        "manual",
        f"{label}: UNDETERMINED from the egress probe — {res.detail}.",
    )


def _live_probe_context(runner: Any) -> tuple[_ProbeContext, dict | None]:
    """Resolve --runtime-reachability prerequisites off the runner.

    Returns ``(ctx, live_env)`` where ``live_env`` is a dict of the resolved
    egress-probe inputs (or ``None`` when the live probe cannot run). Never
    raises: a missing prerequisite or token-acquisition failure records an
    explanatory reason on ``ctx`` and the caller reports MANUAL guidance (there
    is no local fallback).
    """
    ctx = _ProbeContext(
        live_requested=bool(getattr(runner, "runtime_reachability", False)),
        declined_by_user=bool(getattr(runner, "runtime_reachability_declined", False)),
    )
    if not ctx.live_requested:
        return ctx, None

    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    env_url = getattr(runner, "env_url", None)
    dv_token = getattr(runner, "dv_token", None)
    missing = []
    if pp is None:
        missing.append("Power Platform admin client")
    if not env_id:
        missing.append("environment id")
    if not env_url:
        missing.append("Dataverse URL")
    if not dv_token:
        missing.append("Dataverse token")
    if missing:
        ctx.unavailable_reason = "missing " + ", ".join(missing)
        return ctx, None

    try:
        flow_headers = pp.flow_headers
    except Exception as exc:  # pragma: no cover - defensive token failure
        ctx.unavailable_reason = (
            f"could not acquire a Power Automate token ({type(exc).__name__})"
        )
        return ctx, None

    ctx.live_ran = True
    return ctx, {
        "env_url": env_url,
        "dv_token": dv_token,
        "env_id": env_id,
        "flow_headers": flow_headers,
    }


def _infra_003_row(
    status: str, result: str, remediation: str, roles: list[str],
) -> CheckResult:
    return CheckResult(
        checkpoint_id="INFRA-003",
        category="Infrastructure",
        priority=Priority.CRITICAL.value,
        status=status,
        description="External endpoint reachability",
        result=result,
        remediation=remediation,
        doc_link=_DOC_LINK_INFRA_003,
        roles=roles,
    )


def check_external_endpoint_reachability(runner: Any) -> list[CheckResult]:
    """Verify the agent's external system endpoints are reachable (INFRA-003).

    Reachability is tested from the Power Platform environment's OWN egress —
    the path the agent runtime actually uses. The opt-in
    ``--runtime-reachability`` flow stands up a transient Power Automate probe
    flow, triggers it once to send a real HTTP request from that egress, reads
    the returned status code, then deletes the flow (the kit's only mutating
    path). When the egress probe is unavailable (flag not given, operator
    declined, or Dataverse / flow prerequisites missing) the check returns
    MANUAL guidance rather than a local probe: a laptop TCP/TLS probe runs from
    the wrong network and never sends HTTP, so it cannot prove the runtime
    path. Results are bucketed by outcome (one row per distinct status).

    Known limitations (documented so a result is not over-read):
    - DLP vs network block: if a Data Loss Prevention policy blocks the native
      HTTP action, the egress probe reports "blocked" identically to a firewall
      / DNS / TLS drop. It cannot tell them apart. FlightCheck has a separate
      DLP checkpoint; the unreachable finding cross-references it so a
      DLP-caused block is not mislabeled as a pure network problem.
    - Native HTTP vs managed connector: the probe uses a native HTTP action, not
      the managed connector the agent uses at runtime (e.g. shared_workdaysoap).
      For an IP-range firewall allowlist they share the same environment egress,
      so this is the correct reachability tool — but a PASS is not an absolute
      guarantee for a connector with exotic per-connector routing.
    - Installed vs connected: enumeration reads .local/config.json connections
      (written by /connect), which reflects CONNECTED systems and may undercount
      installed-but-not-yet-connected extensions. Any system with no recorded
      endpoint URL is surfaced as MANUAL (unverifiable) rather than dropped.
    """
    endpoints = _discover_external_endpoints(runner)

    if not endpoints:
        return [
            _infra_003_row(
                status=Status.NOT_CONFIGURED.value,
                result=(
                    "No external system endpoints found in the agent's "
                    "connection configuration. Nothing to probe for Workday / "
                    "ServiceNow / SAP SuccessFactors / custom HTTP."
                ),
                remediation=(
                    "If this agent integrates with an external HR system, record "
                    "its endpoint so reachability can be validated:\n"
                    "- Workday and ServiceNow: the /connect skill records the "
                    "endpoint automatically.\n"
                    "- SAP SuccessFactors or a custom HTTP system (no /connect "
                    "flow yet): add the endpoint URL to .local/config.json under "
                    "connections.<System> (for example "
                    'connections.SAPSuccessFactors.odataUrl = '
                    '"https://<api-server>/odata/v2").\n'
                    "Otherwise no action is needed."
                ),
                roles=[Role.POWER_PLATFORM_ADMIN.value],
            )
        ]

    ctx, live_env = _live_probe_context(runner)

    # The local TCP/TLS probe was removed: it runs from the maker's machine,
    # not the Power Platform egress, and never sends HTTP, so it cannot prove
    # the runtime path. When the egress probe is unavailable, hand back MANUAL
    # guidance instead of a misleading local result.
    if not (ctx.live_ran and live_env is not None):
        return [_infra_003_not_probed_row(endpoints, ctx)]

    # The kit's only mutating path. Sweep any flow leaked by a crashed prior
    # run first, guarantee a final sweep, and let run_live_probe delete each
    # flow it creates.
    findings: list[tuple[str, str, str]] = []  # (bucket, line, role)
    try:
        live_egress_probe.cleanup_orphan_probe_flows(
            live_env["env_url"], live_env["dv_token"]
        )
        for ep in endpoints:
            if not ep.host:
                # No probeable URL recorded for this system: it can never be
                # egress-tested, so surface it as MANUAL rather than dropping it.
                findings.append(
                    (
                        "manual",
                        f"{ep.system}: UNVERIFIABLE — no endpoint URL is "
                        f"recorded for this system, so its egress reachability "
                        f"could not be tested.",
                        ep.role,
                    )
                )
                continue
            res = live_egress_probe.run_live_probe(target_url=ep.url, **live_env)
            bucket, line = _live_finding(ep, res)
            findings.append((bucket, line, ep.role))
    finally:
        live_egress_probe.cleanup_orphan_probe_flows(
            live_env["env_url"], live_env["dv_token"]
        )

    reachable = [ln for b, ln, _ in findings if b == "reachable"]
    unreachable = [ln for b, ln, _ in findings if b == "unreachable"]
    manual_lines = [ln for b, ln, _ in findings if b == "manual"]
    reachable_roles = {r for b, _, r in findings if b == "reachable"}
    unreachable_roles = {r for b, _, r in findings if b == "unreachable"}
    manual_roles = {r for b, _, r in findings if b == "manual"}

    probe_layer_note = _infra_003_probe_layer_note()

    results: list[CheckResult] = []

    if unreachable:
        results.append(
            _infra_003_row(
                status=Status.FAILED.value,
                result="\n".join(unreachable),
                remediation=_infra_003_directive(
                    cause=(
                        "A firewall / WAF is refusing the connection, or DNS has "
                        "no record for the host. The egress HTTP probe only "
                        "distinguishes reached vs blocked — it cannot separate "
                        "DNS, TCP, or TLS."
                    ),
                    scope=(
                        "Network — the external system endpoint(s) named above "
                        "(Workday / ServiceNow / SAP SuccessFactors / custom HTTP)."
                    ),
                    implies=(
                        "The agent cannot reach the endpoint(s) above, so any "
                        "topic that calls the affected system will error for "
                        "every employee at runtime until the network path is "
                        "opened."
                    ),
                    next_steps=(
                        "Share the endpoint URL and the combined probable cause "
                        "above with your InfoSec / network team and request "
                        "allowlisting of HTTPS (port 443) to that host from the "
                        "Power Platform outbound IP ranges, then re-run "
                        "/flightcheck --scope infrastructure. If a Data Loss "
                        "Prevention (DLP) policy could be blocking the connector, "
                        "also review the DLP checkpoint — a DLP block looks "
                        "identical to a network block to this probe."
                    ),
                    responsible_role=(
                        "InfoSec / Network admin (allowlisting), with the Power "
                        "Platform admin to confirm the environment's egress "
                        "ranges."
                    ),
                    probe_layer_note=probe_layer_note,
                ),
                roles=sorted(unreachable_roles | {Role.POWER_PLATFORM_ADMIN.value}),
            )
        )

    if manual_lines:
        results.append(
            _infra_003_row(
                status=Status.MANUAL.value,
                result="\n".join(manual_lines) + "\n\n" + probe_layer_note,
                remediation=(
                    "The egress probe could not return a definite result for "
                    "the endpoint(s) above — either the transient flow could not "
                    "be created, activated, or triggered, or no endpoint URL is "
                    "recorded for the system. Re-run /flightcheck --scope "
                    "infrastructure --runtime-reachability to retry, confirm the "
                    "endpoint URL recorded during /connect is correct, or verify "
                    "allowlisting manually:\n\n"
                    + _infra_003_manual_verification()
                ),
                roles=sorted(manual_roles | {Role.POWER_PLATFORM_ADMIN.value}),
            )
        )

    if reachable:
        results.append(
            _infra_003_row(
                status=Status.PASSED.value,
                result="\n".join(reachable) + "\n\n" + probe_layer_note,
                remediation="",
                roles=sorted(reachable_roles | {Role.POWER_PLATFORM_ADMIN.value}),
            )
        )

    return results


# ───────────────────────────────────────────────────────────────────────
# INFRA-006: DLP policies permit every agent connector, co-grouped, none Blocked
#
# Deep counterpart to ENV-008 (which only checks whether *a* policy
# applies). Reconciles each connector the agent's solution depends on
# (resolved from Dataverse connection references) against the connector
# groups of every DLP policy effective on the environment, applying the
# platform's most-restrictive-policy-wins rule.
#
# Read-only and idempotent: lists apiPolicies + reads connectionreferences;
# never mutates. Classic data policies only — advanced connector policies
# (ACP) and tenant custom-connector URL patterns are out of scope (v1).
# ───────────────────────────────────────────────────────────────────────

_DOC_LINK_INFRA_006 = (
    "https://learn.microsoft.com/en-us/copilot/microsoft-365/"
    "employee-self-service/prepare#allow-the-external-systems-connector"
)


def _infra_006_row(status: str, result: str, remediation: str = "") -> CheckResult:
    return CheckResult(
        checkpoint_id="INFRA-006",
        category="Infrastructure",
        priority=Priority.CRITICAL.value,
        status=status,
        description="DLP policies permit every agent connector",
        result=result,
        remediation=remediation,
        doc_link=_DOC_LINK_INFRA_006,
        roles=[Role.POWER_PLATFORM_ADMIN.value],
    )


def _infra_006_could_not_determine_directive() -> str:
    return (
        "Probable cause: The kit could not read the DLP policies or the agent's "
        "connection references for this environment.\n\n"
        "Scope + confidence: Could not determine — no verdict was possible. "
        "Owner: Power Platform Administrator.\n\n"
        "Next step: Re-run FlightCheck signed in with the Power Platform "
        "Administrator role and a valid Dataverse connection.\n\n"
        "Still stuck? Verify the environment id and that the signed-in account "
        "has administrative access to it."
    )


def _infra_006_fail_directive(ev, policy_names: str) -> str:
    blocked_list = ", ".join(ev.blocked) or "the affected connectors"
    return (
        f"Probable cause: In the effective DLP policy/policies ({policy_names}), "
        f"these connectors are in the Blocked group: {blocked_list}. Power "
        "Platform applies the most restrictive policy, so a Blocked connector "
        "stops the agent from calling that system.\n\n"
        "Scope + confidence: High confidence — read directly from the apiPolicies "
        "admin endpoint for this environment. Owner: Power Platform Administrator.\n\n"
        f"Next step: Open the [Power Platform admin center Data policies]"
        f"({ppac_dlp_policies_url()}), edit the named policy, and move every "
        "connector the agent uses into the SAME allowed group (Business or "
        f"Non-Business) — none in Blocked. Connectors to fix: {blocked_list}.\n\n"
        "Still stuck? If a connector must stay Blocked for compliance, deploy the "
        "agent to a dedicated environment whose data policy allows the full "
        "connector set."
    )


def _infra_006_warn_directive(ev, policy_names: str) -> str:
    sections = []
    if ev.cross_group:
        groups = ", ".join(ev.cross_group_groups)
        sections.append(
            f"Cross-group (functional risk): in policy '{ev.cross_group_policy}', "
            f"the agent's connectors are all allowed but split across data-groups "
            f"({groups}). Power Platform blocks combining connectors from "
            "different groups in one app, flow, or agent action, so any agent "
            "action that uses two cross-grouped connectors together will fail at "
            "runtime. Fix: open the [Power Platform admin center Data policies]"
            f"({ppac_dlp_policies_url()}), edit that policy, and move every "
            "connector the agent uses into the SAME allowed group (Business or "
            "Non-Business)."
        )
    if ev.indeterminate:
        listed = ", ".join(ev.indeterminate)
        sections.append(
            f"Unclassified (medium confidence): these connectors are not "
            f"explicitly placed in a group: {listed}. New or unclassified "
            "connectors inherit the policy's default group (usually Non-Business), "
            "which the API does not report, so the kit cannot prove they are "
            "allowed and co-grouped with the agent's other connectors. Fix: open "
            f"the [Power Platform admin center Data policies]({ppac_dlp_policies_url()}) "
            "and explicitly classify the listed connectors into the same allowed "
            "group as the agent's other connectors. If the policy's default group "
            "is Blocked, they are effectively blocked and must be classified "
            "explicitly."
        )
    body = "\n\n".join(sections) or (
        "The effective DLP policy/policies could not fully classify the agent's "
        "connectors."
    )
    return (
        f"Probable cause: {body}\n\n"
        "Scope + confidence: Owner: Power Platform Administrator. Read from the "
        f"apiPolicies admin endpoint for this environment ({policy_names})."
    )


def check_dlp_connector_classification(runner: Any) -> list[CheckResult]:
    """Verify DLP policies permit every agent connector, co-grouped, none Blocked (INFRA-006).

    AC1 enumerates the DLP policies effective on the environment; AC2
    reconciles each agent connector against their classification; AC3/AC4/AC5
    map the outcome to PASS / FAIL / WARN. Defers DLP *coverage* (no policy
    at all) to ENV-008 — INFRA-006 never re-reports "no DLP policy found".
    """
    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    env_url = getattr(runner, "env_url", None)
    dv_token = getattr(runner, "dv_token", None)

    if not pp or not env_id:
        return [_infra_006_row(
            Status.SKIPPED.value,
            "Power Platform Admin API not available — cannot read DLP policies.",
            "Re-run FlightCheck signed in with the Power Platform Administrator role.",
        )]

    # ── AC1: enumerate effective policies ───────────────────────────────
    try:
        policies = iter_effective_policies(pp, env_id)
    except Exception as e:  # noqa: BLE001 — degrade to WARN, never false PASS
        return [_infra_006_row(
            Status.WARNING.value,
            f"DLP connector classification could not be determined: {e}",
            _infra_006_could_not_determine_directive(),
        )]

    if isinstance(policies, dict) and "_error" in policies:
        return [_infra_006_row(
            Status.WARNING.value,
            "DLP policies could not be read — the apiPolicies admin endpoint "
            "returned a permissions error.",
            _infra_006_could_not_determine_directive(),
        )]

    # Defend the get_dlp_policies_for_env contract (list | {"_error": ...}).
    # Any other shape (a truthy dict without _error, a scalar) is a contract
    # drift we must not iterate blindly — degrade to WARN, never crash to ERROR.
    if not isinstance(policies, list):
        return [_infra_006_row(
            Status.WARNING.value,
            "DLP policies could not be read — unexpected response shape from the "
            "apiPolicies admin endpoint.",
            _infra_006_could_not_determine_directive(),
        )]

    # Defer coverage to ENV-008: no policy applies → nothing to classify.
    if not policies:
        return [_infra_006_row(
            Status.SKIPPED.value,
            "No DLP policy applies to this environment — connector classification "
            "is not applicable (DLP coverage is reported by ENV-008).",
        )]

    # ── AC2: resolve the agent's connectors ─────────────────────────────
    if not env_url or not dv_token:
        return [_infra_006_row(
            Status.WARNING.value,
            "Dataverse access not available — cannot resolve the agent's "
            "connectors to classify against DLP.",
            _infra_006_could_not_determine_directive(),
        )]
    try:
        agent_ids = agent_connector_ids(env_url, dv_token)
    except Exception as e:  # noqa: BLE001 — degrade to WARN, never false PASS
        return [_infra_006_row(
            Status.WARNING.value,
            f"Could not resolve the agent's connection references: {e}",
            _infra_006_could_not_determine_directive(),
        )]

    if not agent_ids:
        return [_infra_006_row(
            Status.WARNING.value,
            "No connection references found for the agent — nothing to classify "
            "against DLP.",
            _infra_006_could_not_determine_directive(),
        )]

    # ── AC3/AC4/AC5: reconcile and verdict ──────────────────────────────
    ev = evaluate_connector_classification(agent_ids, policies)
    policy_names = ", ".join(policy_label(p) for p in policies)
    n_pol = len(policies)
    n_conn = len(agent_ids)

    if ev.verdict == "pass":
        # A PASS implies every connector is allowed and in one group, so
        # groups_seen collapses to a single distinct label.
        grp = sorted(set(ev.groups_seen.values()))[0]
        return [_infra_006_row(
            Status.PASSED.value,
            f"All {n_conn} agent connector(s) are allowed and in the same "
            f"data-group ({grp}) across {n_pol} effective DLP policy/policies.",
        )]

    if ev.verdict == "fail":
        # AC4: a Blocked connector is the only hard failure.
        return [_infra_006_row(
            Status.FAILED.value,
            f"DLP misclassification across {n_pol} effective policy/policies: "
            f"Blocked: {', '.join(ev.blocked)}.",
            _infra_006_fail_directive(ev, policy_names),
        )]

    # WARN — AC5 cross-group (all allowed but split) and/or indeterminate
    # (default-group fallthrough the API can't prove). Both share the WARNING
    # bucket, so they are reported in a single status-bucketed row.
    detail = []
    if ev.cross_group:
        groups = ", ".join(ev.cross_group_groups)
        detail.append(
            f"connectors are all allowed but split across data-groups ({groups}) "
            f"in policy '{ev.cross_group_policy}', so they cannot be combined in "
            "one agent action"
        )
    if ev.indeterminate:
        detail.append(
            "these connectors are not explicitly classified and fall into the "
            f"default group: {', '.join(ev.indeterminate)}"
        )
    return [_infra_006_row(
        Status.WARNING.value,
        f"DLP classification concern across {n_pol} effective policy/policies: "
        f"{'; '.join(detail)}.",
        _infra_006_warn_directive(ev, policy_names),
    )]


# ───────────────────────────────────────────────────────────────────────
# INFRA-011: Connector secret storage safety
#
# Verifies that connector credentials (secrets) are stored safely — in a
# platform-managed secret store (a Secret-type Power Platform environment
# variable, which is Azure Key Vault-backed) — and never pasted inline as
# plaintext into a Text environment variable.
#
# Detect-first gate (three outcomes, per the INFRA-011 design agreed with
# PM Senthil):
#   A. No secret-bearing auth present            → informational PASSED
#   B. Secret lives in a Power Platform env var:
#        B1. Secret-type env var (platform-managed / Key Vault-backed)
#            → PASSED for storage, plus a MANUAL vault-hardening directive
#        B2. Raw secret pasted into a Text env var → FAILED
#   C. Secret lives inside a connection (Workday legacy ISU, ServiceNow)
#      — the platform never returns connection secrets via any API
#            → MANUAL ("verify handling yourself")
#
# API tier: Dataverse Web API v9.2 (documented). Reads
# environmentvariabledefinitions / environmentvariablevalues /
# connectionreferences via auth.query_all — the same documented tier the
# Workday env var and package-flavor checks already use.
#
# No Azure Key Vault API is called. Vault hardening (soft-delete / purge /
# RBAC) degrades to MANUAL: the maker running FlightCheck rarely holds
# vault-plane RBAC, the Key Vault properties API is not in the kit's API
# tier registry, and no supported ESS connector ships a Key Vault-backed
# env var to probe (all real secrets live inside connections). Emitting a
# MANUAL directive is honest; a "cannot determine" WARNING would be noise.
# ───────────────────────────────────────────────────────────────────────

# environmentvariabledefinition.type option-set codes.
# Source: Dataverse environmentvariabledefinition entity reference.
_ENV_VAR_TYPE_STRING = 100000000
_ENV_VAR_TYPE_SECRET = 100000005

# Marker present in a Key Vault-backed environment variable value.
_KV_REFERENCE_MARKER = "/providers/Microsoft.KeyVault/vaults/"

# Schema-name substrings that mark an env var as *intended* to hold a
# secret. Used only to flag a secret pasted into a Text env var (B2).
#
# SCOPE (AC2): detection is by env var NAME, not by scanning the value
# for secret-shaped patterns. A secret pasted into a blandly named Text
# var (e.g. "new_Config1") is intentionally NOT flagged — value-based
# pattern matching is out of scope for v1 to keep the readiness-failing
# FAIL bucket free of false positives.
#
# The keyword list is split into two confidence tiers so a broad name
# never fails readiness on name evidence alone:
#
#   * HIGH — a Text env var whose name contains one of these almost
#     certainly holds a real secret. An inline (non-Key-Vault) value is
#     a readiness-blocking FAILED (B2a).
#   * BROAD — the name *may* indicate a secret, but also matches
#     ordinary config (e.g. "TokenEndpointUrl", "ApiKeyName"). Name-only
#     evidence is too weak to fail readiness, so an inline value is
#     surfaced as WARNING for the operator to confirm (B2b). This keeps
#     the FAILED bucket free of the "TokenEndpointUrl"-style false
#     positives while still surfacing the ambiguous case.
_SECRET_NAME_KEYWORDS_HIGH = (
    "secret",
    "password",
    "pwd",
    "clientsecret",
)

_SECRET_NAME_KEYWORDS_BROAD = (
    "apikey",
    "api_key",
    "token",
    "credential",
)

# Workday connection-reference suffixes that fingerprint the legacy ISU
# (Basic-auth service account) install. These connections carry a secret
# the platform never exposes. Simplified-install SSO (ff0df) is secretless.
_WORKDAY_ISU_SUFFIXES = ("0786a", "d6081")

# ServiceNow connector id markers. ServiceNow auth type (OAuth2 / Basic vs
# OIDC / certificate) is not readable from Dataverse, so any ServiceNow
# connection is surfaced as MANUAL for the operator to confirm.
_SERVICENOW_CONNECTOR_MARKERS = ("shared_service-now", "shared_servicenow")

_DOC_LINK_INFRA_011 = (
    "https://learn.microsoft.com/en-us/power-apps/maker/data-platform/"
    "environmentvariables-azure-key-vault-secrets"
)


def _is_kv_reference(value: str | None) -> bool:
    """True if an env var value is an Azure Key Vault reference, not a literal."""
    if not value:
        return False
    return _KV_REFERENCE_MARKER in value or value.startswith("@Microsoft.KeyVault(")


def _classify_secret_name(schema_name: str | None) -> str | None:
    """Classify how strongly an env var's schema name implies a secret.

    Returns ``"high"`` for names that almost certainly hold a secret
    (secret / password / ...), ``"broad"`` for ambiguous names that also
    match ordinary config (token / apikey / ...), or ``None`` when nothing
    matches. High-confidence names fail readiness (B2a); broad names only
    warn (B2b), so the readiness-blocking FAIL bucket stays free of
    "TokenEndpointUrl"-style false positives.
    """
    if not schema_name:
        return None
    lowered = schema_name.lower()
    if any(keyword in lowered for keyword in _SECRET_NAME_KEYWORDS_HIGH):
        return "high"
    if any(keyword in lowered for keyword in _SECRET_NAME_KEYWORDS_BROAD):
        return "broad"
    return None


def _classify_secret_connections(conn_refs: list[dict[str, Any]]) -> list[str]:
    """Return display strings for connections that carry a secret the
    platform never exposes via API (Workday legacy ISU, ServiceNow)."""
    findings: list[str] = []
    for ref in conn_refs:
        logical = (ref.get("connectionreferencelogicalname") or "").lower()
        connector = (ref.get("connectorid") or "").lower()
        display = ref.get("connectionreferencedisplayname") or logical or "(unnamed)"

        if any(logical.endswith(suffix) for suffix in _WORKDAY_ISU_SUFFIXES):
            findings.append(
                f"Workday legacy ISU connection '{display}' (Basic-auth service "
                f"account — secret stored inside the connection)"
            )
        elif any(marker in connector for marker in _SERVICENOW_CONNECTOR_MARKERS):
            findings.append(
                f"ServiceNow connection '{display}' (auth type not readable from "
                f"Dataverse — may store an OAuth2 / Basic secret in the connection)"
            )
    return findings


def check_connector_secret_storage(runner: Any) -> list[CheckResult]:
    """Verify connector secrets are stored safely, not inline (INFRA-011).

    Detect-first gate over Power Platform environment variables and
    connection references (read via the documented Dataverse Web API):

      * Secret-type env var → platform-managed / Key Vault-backed storage.
        PASSED for storage, plus a MANUAL directive to verify vault
        hardening (soft-delete / purge / RBAC) — the kit does not hold
        vault-plane rights to check those directly.
      * A high-confidence secret name (secret / password / ...) in a plain
        Text env var → FAILED. This is the inline-plaintext anti-pattern
        INFRA-011 exists to catch.
      * A broad/ambiguous secret name (token / apikey / credential) in a
        plain Text env var → WARNING. The name also fits ordinary config
        (e.g. "TokenEndpointUrl"), so name-only evidence warns for
        operator confirmation rather than failing readiness.
      * A secret-bearing connection (Workday legacy ISU, ServiceNow) →
        MANUAL. Connection secrets are never returned by any API, so the
        operator must confirm handling themselves.
      * None of the above → informational PASSED (no inline secrets).

    Read-only and idempotent. WARNING, MANUAL, and PASSED never fail
    readiness; only the high-confidence FAILED does.
    """
    roles_ppa = [Role.POWER_PLATFORM_ADMIN.value]
    env_url = getattr(runner, "env_url", "") or ""
    dv_token = getattr(runner, "dv_token", "") or ""

    if not env_url or not dv_token:
        return [
            CheckResult(
                checkpoint_id="INFRA-011",
                category="Infrastructure",
                priority=Priority.HIGH.value,
                status=Status.SKIPPED.value,
                description="Connector secret storage safety",
                result=(
                    "Dataverse environment URL or token not available — could not "
                    "read environment variables or connection references."
                ),
                remediation=(
                    "Run /flightcheck against a configured Dataverse environment "
                    "(set dataverseEndpoint in .local/config.json) with a valid "
                    "sign-in so INFRA-011 can inspect where connector secrets live."
                ),
                doc_link=_DOC_LINK_INFRA_011,
                roles=roles_ppa,
            )
        ]

    try:
        defs = query_all(
            env_url,
            dv_token,
            "environmentvariabledefinitions",
            "schemaname,displayname,type,defaultvalue,environmentvariabledefinitionid",
        )
        vals = query_all(
            env_url,
            dv_token,
            "environmentvariablevalues",
            "value,schemaname,_environmentvariabledefinitionid_value",
        )
        conn_refs = query_all(
            env_url,
            dv_token,
            "connectionreferences",
            "connectionreferencelogicalname,connectionreferencedisplayname,"
            "connectorid,connectionid,statuscode",
        )
    except Exception as exc:  # surface API failure as WARNING (principle 3)
        return [
            CheckResult(
                checkpoint_id="INFRA-011",
                category="Infrastructure",
                priority=Priority.HIGH.value,
                status=Status.WARNING.value,
                description="Connector secret storage safety",
                result=(
                    f"Could not read Dataverse environment variables or connection "
                    f"references: {exc}"
                ),
                remediation=(
                    "Impact: secret-storage safety could not be verified, so an "
                    "inline-plaintext secret would go undetected.\n\n"
                    "Next steps: re-run /flightcheck once Dataverse is reachable "
                    "and the sign-in is valid."
                ),
                doc_link=_DOC_LINK_INFRA_011,
                roles=roles_ppa,
            )
        ]

    # Index each definition's current-value override by definition id. An
    # environmentvariablevalue row exists only when a current value is set;
    # it holds the override, never the default.
    override_by_def_id: dict[Any, str] = {}
    for val in vals:
        def_id = val.get("_environmentvariabledefinitionid_value")
        if def_id is not None:
            override_by_def_id[def_id] = val.get("value") or ""

    secret_env_vars: list[str] = []      # Secret-type (B1, safe storage)
    plaintext_env_vars: list[str] = []   # high-confidence name (B2a, FAILED)
    suspect_env_vars: list[str] = []     # broad/ambiguous name (B2b, WARNING)

    # Iterate definitions (not value rows) and evaluate the *effective*
    # value: the current-value override when set and non-empty, otherwise
    # the definition's defaultvalue. A secret pasted into a definition's
    # defaultvalue produces NO environmentvariablevalue row, so a value-only
    # scan would miss it entirely — and solution-imported vars commonly ship
    # default-only, which is a primary inline-secret path this check exists
    # to catch.
    for definition in defs:
        def_id = definition.get("environmentvariabledefinitionid")
        var_type = definition.get("type")
        schema = definition.get("schemaname") or "(unknown env var)"
        override = override_by_def_id.get(def_id, "")
        default = definition.get("defaultvalue") or ""
        effective_value = override or default

        if var_type == _ENV_VAR_TYPE_SECRET:
            # A Secret-type var is asserted as safely stored only when it
            # actually holds a value (an override or a default Key Vault
            # reference). An unbound Secret-type definition proves nothing.
            if effective_value:
                secret_env_vars.append(schema)
        # `var_type is None` means the definition omitted its type. Treat it
        # as Text so a secret-named value is still evaluated: a genuinely
        # KV-backed secret carries a Key Vault reference in its value, which
        # `_is_kv_reference` filters out below, so this defensive default
        # cannot fail a correctly stored secret.
        elif var_type == _ENV_VAR_TYPE_STRING or var_type is None:
            if effective_value and not _is_kv_reference(effective_value):
                tier = _classify_secret_name(schema)
                if tier == "high":
                    plaintext_env_vars.append(schema)
                elif tier == "broad":
                    suspect_env_vars.append(schema)

    secret_connections = _classify_secret_connections(conn_refs)

    results: list[CheckResult] = []

    # ── B2a: high-confidence secret name in a Text env var → FAILED ─────
    if plaintext_env_vars:
        listed = "\n".join(f"  - {name}" for name in plaintext_env_vars)
        results.append(
            CheckResult(
                checkpoint_id="INFRA-011",
                category="Infrastructure",
                priority=Priority.CRITICAL.value,
                status=Status.FAILED.value,
                description="Connector secret storage safety",
                result=(
                    "Secret-looking value stored inline in a plain Text "
                    "environment variable (not a Key Vault reference):\n"
                    f"{listed}"
                ),
                remediation=(
                    "Impact: a plaintext secret in a Text environment variable is "
                    "readable by anyone with maker access to the solution and is "
                    "carried in solution exports — treat it as compromised.\n\n"
                    "Next steps:\n"
                    "1. Rotate the exposed secret at its source system.\n"
                    "2. Store the new secret in Azure Key Vault.\n"
                    "3. Recreate the environment variable(s) above as the Secret "
                    "type, referencing the Key Vault secret.\n"
                    "4. Re-run /flightcheck --scope infrastructure."
                ),
                doc_link=_DOC_LINK_INFRA_011,
                roles=roles_ppa,
            )
        )

    # ── B2b: broad/ambiguous secret name in a Text env var → WARNING ────
    #
    # The name matches a broad keyword (token / apikey / credential) that
    # also fits ordinary config such as "TokenEndpointUrl" or "ApiKeyName".
    # Name-only evidence is too weak to fail readiness, so surface it for
    # the operator to confirm instead of blocking deployment (per the B2
    # tiering in _classify_secret_name).
    if suspect_env_vars:
        listed = "\n".join(f"  - {name}" for name in suspect_env_vars)
        results.append(
            CheckResult(
                checkpoint_id="INFRA-011",
                category="Infrastructure",
                priority=Priority.MEDIUM.value,
                status=Status.WARNING.value,
                description="Connector secret storage safety",
                result=(
                    "Text environment variable(s) whose name suggests a secret "
                    "but whose value could not be confirmed as one (value is not "
                    "a Key Vault reference):\n"
                    f"{listed}"
                ),
                remediation=(
                    "Impact: if any value above is a real secret, a plaintext "
                    "secret in a Text environment variable is readable by anyone "
                    "with maker access and travels in solution exports. The name "
                    "alone is not conclusive, so this is flagged for confirmation "
                    "rather than as a hard failure.\n\n"
                    "Next steps:\n"
                    "1. Inspect each variable above. If it holds non-sensitive "
                    "config (e.g. an endpoint URL or a display name), no action "
                    "is needed.\n"
                    "2. If it holds a real secret, rotate it at the source, store "
                    "it in Azure Key Vault, and recreate the variable as the "
                    "Secret type referencing the vault.\n"
                    "3. Re-run /flightcheck --scope infrastructure."
                ),
                doc_link=_DOC_LINK_INFRA_011,
                roles=roles_ppa,
            )
        )

    # ── B1: Secret-type env var → PASSED for storage + MANUAL hardening ──
    #
    # FAST-FOLLOW (AC1/AC5): v1 degrades vault hardening to MANUAL for
    # everyone. A future revision may probe the backing vault via Azure
    # ARM (soft-delete / purge / RBAC) and emit WARNING when a property
    # is provably disabled, falling back to MANUAL only on 401/403/no
    # token. That requires registering the Azure Key Vault vault-
    # properties API in tests/fixtures/cassettes/INDEX.md first, plus an
    # Azure rights grant most makers running FlightCheck do not hold.
    if secret_env_vars:
        listed = "\n".join(f"  - {name}" for name in secret_env_vars)
        results.append(
            CheckResult(
                checkpoint_id="INFRA-011",
                category="Infrastructure",
                priority=Priority.HIGH.value,
                status=Status.PASSED.value,
                description="Connector secret storage safety",
                result=(
                    "Secret stored as a Key Vault-backed Secret-type environment "
                    "variable (not inline plaintext):\n"
                    f"{listed}"
                ),
                doc_link=_DOC_LINK_INFRA_011,
                roles=roles_ppa,
            )
        )
        results.append(
            CheckResult(
                checkpoint_id="INFRA-011",
                category="Infrastructure",
                priority=Priority.MEDIUM.value,
                status=Status.MANUAL.value,
                description="Key Vault hardening for connector secrets",
                result=(
                    "The environment variable(s) above reference an Azure Key "
                    "Vault. FlightCheck does not hold vault-plane rights, so vault "
                    "hardening (soft-delete, purge protection, RBAC) was not read."
                ),
                remediation=(
                    "Hardening recommendation (not a functional blocker): a "
                    "hardened vault prevents accidental or malicious secret "
                    "deletion and limits who can read the secret.\n\n"
                    "Verify in the Azure portal, on the backing Key Vault:\n"
                    "1. Soft-delete is enabled (default 90-day retention).\n"
                    "2. Purge protection is enabled.\n"
                    "3. Access uses Azure RBAC (not legacy access policies), "
                    "scoped to the minimum principals."
                ),
                doc_link=_DOC_LINK_INFRA_011,
                roles=roles_ppa,
            )
        )

    # ── C: secret inside a connection → MANUAL ──────────────────────────
    if secret_connections:
        listed = "\n".join(f"  - {finding}" for finding in secret_connections)
        conn_roles = list(roles_ppa)
        joined = " ".join(secret_connections).lower()
        if "workday" in joined:
            conn_roles.append(Role.WORKDAY_ADMIN.value)
        if "servicenow" in joined:
            conn_roles.append(Role.SERVICENOW_ADMIN.value)
        results.append(
            CheckResult(
                checkpoint_id="INFRA-011",
                category="Infrastructure",
                priority=Priority.HIGH.value,
                status=Status.MANUAL.value,
                description="Connector secret storage safety",
                result=(
                    "Secret-bearing connection(s) detected. The credential lives "
                    "inside the connection, which no API exposes, so the kit "
                    "cannot verify where or how it is stored:\n"
                    f"{listed}"
                ),
                remediation=(
                    "Impact: a credential stored inside a connection cannot be "
                    "auto-validated, so its handling must be confirmed manually.\n\n"
                    "Next steps for the connection(s) above:\n"
                    "1. Confirm the underlying secret was sourced from an approved "
                    "secret store (e.g. Azure Key Vault), not a shared document.\n"
                    "2. Confirm the secret is rotated on the source system's "
                    "schedule.\n"
                    "3. Confirm only the intended service account owns the "
                    "connection."
                ),
                doc_link=_DOC_LINK_INFRA_011,
                roles=conn_roles,
            )
        )

    # ── A: no secret-bearing auth anywhere → informational PASSED ───────
    if not results:
        results.append(
            CheckResult(
                checkpoint_id="INFRA-011",
                category="Infrastructure",
                priority=Priority.HIGH.value,
                status=Status.PASSED.value,
                description="Connector secret storage safety",
                result=(
                    "No inline connector secrets detected. No Secret-type or "
                    "plaintext-secret environment variables and no secret-bearing "
                    "connections (Workday legacy ISU, ServiceNow) are present."
                ),
                doc_link=_DOC_LINK_INFRA_011,
                roles=roles_ppa,
            )
        )

    return results


# ───────────────────────────────────────────────────────────────────────
# Check registry — add new INFRA-xxx orchestrators here
#
# Each entry is a callable (runner) -> list[CheckResult]. The public
# entry point run_infrastructure_checks() iterates this list in order.
# To add a new check, define your orchestrator above and append it here.
# ───────────────────────────────────────────────────────────────────────

_INFRA_CHECKS: list[Callable[[Any], list[CheckResult]]] = [
    check_microsoft_service_reachability,
    check_external_endpoint_reachability,
    check_dlp_connector_classification,
    check_connector_secret_storage,
    # Future checks — add here:
    # check_hr_system_reachability,
]


# ───────────────────────────────────────────────────────────────────────
# Public entry point
# ───────────────────────────────────────────────────────────────────────


def run_infrastructure_checks(runner: Any) -> list[CheckResult]:
    """Run all registered infrastructure checks (INFRA-xxx).

    Iterates the _INFRA_CHECKS registry and collects results. New checks
    only need to be appended to the registry list above.
    """
    results: list[CheckResult] = []
    for check_fn in _INFRA_CHECKS:
        results.extend(check_fn(runner))
    return results
