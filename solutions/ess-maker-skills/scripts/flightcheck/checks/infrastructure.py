# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Infrastructure & Security (INFRA-xxx)

Extensible module for infrastructure pre-deployment checks. Currently
implements:
  - INFRA-001: Inbound connectivity to Microsoft services

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

from ..runner import CheckResult, Priority, Role, Status


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
        family, socktype, proto, _canonname, sockaddr = addr_info[0]
        result.resolved_ip = sockaddr[0]
        result.dns_ok = True
        result.dns_ms = round((time.perf_counter() - t0) * 1000, 1)
    except socket.gaierror as exc:
        result.error_layer = "dns"
        result.error_message = f"DNS resolution failed for {host}: {exc}"
        result.dns_ms = round((time.perf_counter() - t0) * 1000, 1)
        return result

    # Layer 2: TCP connect
    t0 = time.perf_counter()
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(timeout)
    try:
        sock.connect(sockaddr)
        result.tcp_ok = True
        result.tcp_ms = round((time.perf_counter() - t0) * 1000, 1)
    except socket.timeout:
        result.error_layer = "tcp"
        result.error_message = (
            f"TCP connection to {host}:{port} ({result.resolved_ip}) "
            f"timed out after {timeout}s — firewall may be silently dropping packets"
        )
        result.tcp_ms = round((time.perf_counter() - t0) * 1000, 1)
        sock.close()
        return result
    except ConnectionRefusedError:
        result.error_layer = "tcp"
        result.error_message = (
            f"TCP connection to {host}:{port} ({result.resolved_ip}) refused — "
            f"port closed or firewall sending RST"
        )
        result.tcp_ms = round((time.perf_counter() - t0) * 1000, 1)
        sock.close()
        return result
    except OSError as exc:
        result.error_layer = "tcp"
        result.error_message = f"TCP connection to {host}:{port} failed: {exc}"
        result.tcp_ms = round((time.perf_counter() - t0) * 1000, 1)
        sock.close()
        return result

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
    if env_url:
        parsed = urlparse(env_url)
        host = parsed.hostname
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
    if not env_url:
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
# Check registry — add new INFRA-xxx orchestrators here
#
# Each entry is a callable (runner) -> list[CheckResult]. The public
# entry point run_infrastructure_checks() iterates this list in order.
# To add a new check, define your orchestrator above and append it here.
# ───────────────────────────────────────────────────────────────────────

_INFRA_CHECKS: list[Callable[[Any], list[CheckResult]]] = [
    check_microsoft_service_reachability,
    # Future checks — add here:
    # check_hr_system_reachability,
    # check_dlp_policy_compliance,
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
