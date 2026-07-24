# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Infrastructure & Security (INFRA-xxx)

Extensible module for infrastructure pre-deployment checks. Currently
implements:
  - INFRA-001: Inbound connectivity to Microsoft services
  - INFRA-002: HR-system reachability from Power Platform's egress boundary

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

  EXCEPTION — INFRA-002 live network probe: when (and only when) the maker
  grants explicit consent via the ``--live-network-probe`` flag, INFRA-002
  temporarily creates + deletes a Power Platform cloud flow (a Dataverse
  mutation) to measure reachability from Power Platform's own egress rather
  than the maker's machine. The flow issues a single unauthenticated HEAD
  request (no business data, no credentials to the target) and is always
  deleted net-zero. The flow lifecycle lives in ``flow_probe.py`` and is
  lazy-imported inside the consent-gated branch so the default TCP path stays
  stdlib-only. Without consent, INFRA-002 falls back to a local TCP probe and
  honours every constraint above.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from ..runner import CheckResult, Priority, Role, Status
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
# INFRA-002: HR-system reachability from Power Platform's egress boundary
#
# Probe accuracy: HIGH (live path) — the reachability request originates from
# Power Platform's OWN service boundary via a temporary cloud flow, which is
# the boundary the deployed agent's connectors actually use. This answers the
# firewall/allowlist question INFRA-001's local TCP probe cannot: "can Power
# Platform reach Workday?", not "can the maker's laptop reach Workday?".
#
# The live path is CONSENT-GATED (``--live-network-probe``) because it
# temporarily creates + deletes a Power Platform flow (see the module header
# EXCEPTION note and flow_probe.py). Without consent — or if the live probe
# cannot run (missing sign-in context, DLP blocks the HTTP connector,
# insufficient permissions) — INFRA-002 falls back to a local TCP probe
# (accuracy: MEDIUM — maker's network, not Power Platform's) so the check
# always returns an actionable result.
#
# Verdict: PASS iff the target is reachable AND the instance URL is valid.
# Authorization is deliberately NOT tested — the probe sends no credentials,
# so a login redirect (302) counts as reachable+valid, not as a failure.
# ───────────────────────────────────────────────────────────────────────

# No public MS Learn page documents this ESS-specific check yet.
# TODO(INFRA-002): set doc_link once the readiness-guide page is published.
_DOC_LINK_INFRA_002 = ""

# Workday redirects an unrecognized instance URL to its invalid-url landing
# page; a Location containing one of these means reachable-but-invalid-instance.
_INFRA_002_INVALID_URL_MARKERS = ("/invalid-url", "community.workday.com/invalid-url")


def _load_workday_connect_config() -> dict:
    """Best-effort load of ``.local/connect/workday/config.json`` (never raises)."""
    try:
        path = os.path.join(".local", "connect", "workday", "config.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — missing/invalid config → no target
        return {}


def _resolve_probe_target(runner: Any) -> str | None:
    """Resolve the HR-system URL to probe.

    Precedence: explicit ``--probe-target-url`` override, then the Workday
    connect config's ``baseUrl`` / ``restBaseUrl`` / ``soapBaseUrl``.
    """
    override = str(getattr(runner, "probe_target_url", "") or "").strip()
    if override:
        return override
    cfg = _load_workday_connect_config()
    for key in ("baseUrl", "restBaseUrl", "soapBaseUrl"):
        val = str(cfg.get(key) or "").strip()
        if val:
            return val
    return None


def _infra_002_row(
    status: str,
    result: str,
    *,
    remediation: str = "",
    roles: list[str] | None = None,
) -> CheckResult:
    return CheckResult(
        checkpoint_id="INFRA-002",
        category="Infrastructure",
        priority=Priority.HIGH.value,
        status=status,
        description="HR-system reachability from Power Platform",
        result=result,
        remediation=remediation,
        doc_link=_DOC_LINK_INFRA_002,
        roles=roles or [Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
    )


def _infra_002_from_live(target_url: str, host: str, verdict: dict[str, Any]) -> CheckResult:
    """Map a live flow-probe verdict → CheckResult (PASS iff reachable + valid)."""
    reachable = bool(verdict.get("reachable"))
    instance_valid = bool(verdict.get("instance_valid"))
    http_status = verdict.get("http_status")
    status_hint = f" (HTTP {http_status})" if http_status else ""

    if not reachable:
        err = verdict.get("error")
        err_note = f" Probe error: {err}." if err else ""
        status = Status.FAILED.value
        result = (
            f"{host}: UNREACHABLE from Power Platform's service boundary. The "
            f"temporary probe flow's HEAD request to {target_url} returned no HTTP "
            f"response — DNS resolution failed or the connection timed out.{err_note}"
        )
        remediation = (
            f"Impact: The deployed ESS agent's connectors run from Power Platform's "
            f"egress and will not be able to reach {host} at runtime.\n\n"
            f"Probable cause: A firewall or network allowlist is blocking outbound "
            f"traffic from Power Platform to {host}.\n\n"
            f"Next steps:\n"
            f"1. Share this result with your network / InfoSec team.\n"
            f"2. Request allowlisting of outbound HTTPS from Power Platform to {host} "
            f"(see the Power Platform IP ranges / service tags for your region).\n"
            f"3. Re-run /flightcheck --scope full --live-network-probe."
        )
        roles = [Role.POWER_PLATFORM_ADMIN.value, Role.WORKDAY_ADMIN.value]
    elif not instance_valid:
        redirect = verdict.get("redirect_location")
        redirect_note = f" (redirected to {redirect})" if redirect else ""
        status = Status.FAILED.value
        result = (
            f"{host}: Reachable from Power Platform, but the instance URL "
            f"'{target_url}' is NOT valid{status_hint}{redirect_note}. The HR system "
            f"redirected the probe to its invalid-URL page, so the network path is "
            f"open but the configured endpoint is wrong."
        )
        remediation = (
            f"Impact: Connectivity is fine, but '{target_url}' is not a real HR-system "
            f"instance URL — connectors pointed at it will fail.\n\n"
            f"Next steps:\n"
            f"1. Confirm your Workday tenant/instance URL (e.g. "
            f"https://<host>/<tenant>) with your Workday administrator.\n"
            f"2. Update baseUrl in .local/connect/workday/config.json (or pass "
            f"--probe-target-url) and re-run /flightcheck --scope full "
            f"--live-network-probe."
        )
        roles = [Role.WORKDAY_ADMIN.value, Role.ESS_MAKER.value]
    else:
        status = Status.PASSED.value
        result = (
            f"{host}: Reachable from Power Platform's service boundary. The HEAD "
            f"request to {target_url} succeeded{status_hint} — your network allowlist "
            f"permits Power Platform → HR-system connectivity. "
            f"(Connectivity only; authorization was not tested.)"
        )
        remediation = ""
        roles = [Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value]

    # Net-zero cleanup: if the temporary flow could not be auto-deleted, the
    # environment is NOT left clean — surface it (downgrade a PASS to WARNING,
    # and always append manual-deletion guidance). The maker emphasised that
    # flow deletion matters.
    if verdict.get("flow_id") and not verdict.get("deleted"):
        cleanup = verdict.get("cleanup_note") or (
            f"The temporary probe flow '{verdict.get('flow_name')}' "
            f"(workflowid {verdict.get('flow_id')}) could not be deleted "
            f"automatically. Delete it manually at "
            f"https://make.powerautomate.com (My flows)."
        )
        if status == Status.PASSED.value:
            status = Status.WARNING.value
            result += " NOTE: the temporary probe flow could not be auto-deleted."
        remediation = (remediation + "\n\n" if remediation else "") + f"Cleanup: {cleanup}"

    return _infra_002_row(status, result, remediation=remediation, roles=roles)


def _infra_002_tcp(target_url: str, host: str, *, fallback_reason: str | None) -> CheckResult:
    """Local TCP-probe path (default, and fallback when the live probe can't run)."""
    prefix = ""
    if fallback_reason:
        prefix = (
            f"Live probe unavailable ({fallback_reason}); fell back to a local "
            f"TCP probe from this machine. "
        )

    probe = probe_endpoint(host, 443)
    host_port = f"{host}:443"

    if probe.dns_ok and probe.tcp_ok and probe.tls_ok:
        return _infra_002_row(
            Status.PASSED.value,
            (
                f"{prefix}{host_port} ({target_url}): Reachable from THIS MACHINE "
                f"(DNS {probe.dns_ms}ms → TCP {probe.tcp_ms}ms → "
                f"{probe.tls_version or 'TLS'} {probe.tls_ms}ms). NOTE: this probes "
                f"from the maker's network, not Power Platform's egress boundary. To "
                f"confirm Power Platform itself can reach {host}, re-run with "
                f"--live-network-probe under --scope full."
            ),
            roles=[Role.ESS_MAKER.value, Role.WORKDAY_ADMIN.value],
        )

    if probe.error_layer == "dns":
        detail = f"DNS resolution failed ({probe.dns_ms}ms)."
    elif probe.error_layer == "tcp":
        ip = f" DNS resolved to {probe.resolved_ip}." if probe.resolved_ip else ""
        detail = f"TCP connection failed ({probe.tcp_ms}ms): {probe.error_message}.{ip}"
    else:
        detail = f"TLS handshake failed ({probe.tls_ms}ms): {probe.error_message}."

    return _infra_002_row(
        Status.FAILED.value,
        (
            f"{prefix}{host_port} ({target_url}): UNREACHABLE from this machine. "
            f"{detail}"
        ),
        remediation=(
            f"Impact: {host} is not reachable from this network. If the deployed "
            f"agent runs from the same network boundary, its connectors will fail.\n\n"
            f"Probable cause: A firewall/DNS restriction is blocking HTTPS to {host}.\n\n"
            f"Next steps:\n"
            f"1. Verify the HR-system URL is correct.\n"
            f"2. Ask your network team to allowlist HTTPS to {host}.\n"
            f"3. For an authoritative Power-Platform-side result, re-run with "
            f"--live-network-probe under --scope full."
        ),
        roles=[Role.ESS_MAKER.value, Role.WORKDAY_ADMIN.value],
    )


def check_hr_system_reachability(runner: Any) -> list[CheckResult]:
    """Verify the HR system is reachable from Power Platform's egress (INFRA-002).

    Default path: a local TCP probe from this machine (read-only, stdlib).

    Consent-gated live path (``runner.live_network_probe`` — set by the
    ``--live-network-probe`` flag after the maker approves the network-probe
    consent prompt): temporarily creates a Power Platform cloud flow that
    issues a HEAD request to the HR-system URL from Power Platform's OWN
    service boundary, reads the reachability result, then deletes the flow
    (net-zero). Falls back to the local TCP probe if the live probe cannot run
    (missing sign-in context, insufficient permissions, DLP blocks the HTTP
    connector, transient failure).

    PASS iff the target is reachable AND the instance URL is valid;
    authorization is not tested.
    """
    target_url = _resolve_probe_target(runner)
    if not target_url:
        return [_infra_002_row(
            Status.SKIPPED.value,
            "HR-system reachability skipped: no target URL configured.",
            remediation=(
                "Set baseUrl in .local/connect/workday/config.json (run /connect for "
                "Workday) or pass --probe-target-url to include INFRA-002."
            ),
        )]

    host = _host_from_url(target_url)
    if not host:
        return [_infra_002_row(
            Status.SKIPPED.value,
            f"HR-system reachability skipped: '{target_url}' is not a valid URL.",
            remediation=(
                "Provide a full HR-system URL (e.g. https://<host>/<tenant>) via "
                "baseUrl in .local/connect/workday/config.json or --probe-target-url."
            ),
        )]

    if not bool(getattr(runner, "live_network_probe", False)):
        return [_infra_002_tcp(target_url, host, fallback_reason=None)]

    # Consent granted — attempt the live Power Platform egress probe.
    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    env_url = getattr(runner, "env_url", None)
    dv_token = getattr(runner, "dv_token", None)
    if not (pp and env_id and env_url and dv_token):
        return [_infra_002_tcp(
            target_url,
            host,
            fallback_reason=(
                "sign-in context for the live probe was unavailable — the live path "
                "requires --scope full with Power Platform and Dataverse access"
            ),
        )]

    try:
        from ..flow_probe import FlowProbeError, run_live_probe

        verdict = run_live_probe(
            env_url=env_url,
            dv_token=dv_token,
            pp_admin=pp,
            env_id=env_id,
            target_url=target_url,
        )
    except Exception as exc:  # noqa: BLE001 — FlowProbeError + any client error → TCP fallback
        return [_infra_002_tcp(target_url, host, fallback_reason=str(exc))]

    return [_infra_002_from_live(target_url, host, verdict)]


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
# Check registry — add new INFRA-xxx orchestrators here
#
# Each entry is a callable (runner) -> list[CheckResult]. The public
# entry point run_infrastructure_checks() iterates this list in order.
# To add a new check, define your orchestrator above and append it here.
# ───────────────────────────────────────────────────────────────────────

_INFRA_CHECKS: list[Callable[[Any], list[CheckResult]]] = [
    check_microsoft_service_reachability,
    check_hr_system_reachability,
    check_dlp_connector_classification,
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
