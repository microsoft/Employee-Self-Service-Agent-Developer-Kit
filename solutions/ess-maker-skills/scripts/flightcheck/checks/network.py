# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Vendor Network Reachability (NET-001, NET-002, NET-003)

"Shift-left" pre-deployment validator that probes outbound TCP + HTTPS
reachability to the vendor hostnames that the Employee Self-Service (ESS)
agent's connectors need at runtime. Catches missing firewall allow-list
entries, SSL inspection, and proxy interference WEEKS before the ESS
deployment cutover, when network-team change requests still have time to
land.

Vendor scope only: Workday, ServiceNow, SAP SuccessFactors. Microsoft
endpoints (Power Platform, Entra ID, Dataverse, Copilot Studio) are
documented authoritatively by Microsoft — see
https://learn.microsoft.com/en-us/power-platform/admin/online-requirements
— and this check deliberately does NOT duplicate that allowlist.

Cardinal-rule note (see scripts/flightcheck/AGENTS.md): this is a
transport-level diagnostic. It does NOT consume vendor API response
contracts, so the validated/validatable/documented tier system does not
apply. Instead the production code uses injectable `TcpProber` /
`HttpsProber` implementations so tests can substitute deterministic
fakes for the six relevant failure modes (refused, timeout, DNS failure,
TLS error, 4xx, 5xx). The tier registry in
`tests/fixtures/cassettes/INDEX.md` has a dedicated
"Vendor TCP/HTTPS reachability" row documenting this exception.

Ported from ess-preflight-validator commit 9ed2055
(`PowerShell/Test-NetworkConnectivity.ps1`).
"""

from __future__ import annotations

import json
import os
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Protocol

import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    SSLError as RequestsSSLError,
    Timeout as RequestsTimeout,
)

from ..runner import CheckResult, Priority, Status

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"

DEFAULT_TIMEOUT_SECS = 5.0
DEFAULT_MAX_WORKERS = 8

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config",
    "required-endpoints.json",
)


# ---------------------------------------------------------------------------
# Probe protocol — injectable so tests can substitute deterministic fakes.
# Production implementations live below; tests pass their own.
# ---------------------------------------------------------------------------

class ProbeStatus:
    """String constants for probe outcomes. Stable, used in tests."""

    REACHABLE = "reachable"        # TCP open, HTTPS 2xx/3xx/4xx (auth-required)
    HTTP_5XX = "http_5xx"          # TCP open, HTTPS 5xx (server-side problem)
    TLS_ERROR = "tls_error"        # TCP open, TLS handshake failed (likely SSL inspection)
    REFUSED = "refused"            # TCP connection actively refused (firewall block)
    TIMEOUT = "timeout"            # TCP / HTTPS exceeded timeout (silent drop)
    DNS_FAILURE = "dns_failure"    # Hostname did not resolve
    SKIPPED = "skipped"            # Placeholder host left unresolved (e.g. {instance})


@dataclass
class ProbeResult:
    host: str
    port: int
    status: str           # ProbeStatus.*
    detail: str = ""      # Human-readable explanation
    latency_ms: int = 0   # Set when probe completed


class TcpProber(Protocol):
    def probe(self, host: str, port: int, timeout: float) -> ProbeResult: ...


class HttpsProber(Protocol):
    def probe(self, host: str, port: int, timeout: float) -> ProbeResult: ...


class _StdlibTcpProber:
    """Production TCP prober — uses ``socket.create_connection``."""

    def probe(self, host: str, port: int, timeout: float) -> ProbeResult:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return ProbeResult(host=host, port=port, status=ProbeStatus.REACHABLE,
                                   detail=f"TCP {port} open")
        except socket.gaierror as e:
            return ProbeResult(host=host, port=port, status=ProbeStatus.DNS_FAILURE,
                               detail=f"DNS resolution failed: {e}")
        except socket.timeout:
            return ProbeResult(host=host, port=port, status=ProbeStatus.TIMEOUT,
                               detail=f"TCP {port} timed out after {timeout}s (firewall silent drop?)")
        except (ConnectionRefusedError, OSError) as e:
            # OSError covers "no route to host", "network unreachable", and refused.
            # We treat them all as REFUSED for remediation purposes (firewall is
            # blocking us); the detail line carries the underlying message.
            return ProbeResult(host=host, port=port, status=ProbeStatus.REFUSED,
                               detail=f"TCP {port} refused/unreachable: {e}")


class _RequestsHttpsProber:
    """Production HTTPS prober — uses ``requests`` HEAD against ``https://host:port/``.

    A HEAD request is enough to detect TLS interception and reach the application
    layer. We accept ANY HTTP status code as "reachable" — even 401 / 403 / 404 —
    because the goal is to confirm the connector can complete a TLS handshake
    and exchange HTTP framing, not to authenticate or authorize.
    """

    def probe(self, host: str, port: int, timeout: float) -> ProbeResult:
        url = f"https://{host}" if port == 443 else f"https://{host}:{port}"
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=False)
            if resp.status_code >= 500:
                return ProbeResult(host=host, port=port, status=ProbeStatus.HTTP_5XX,
                                   detail=f"HTTPS {resp.status_code} server error")
            return ProbeResult(host=host, port=port, status=ProbeStatus.REACHABLE,
                               detail=f"HTTPS {resp.status_code}")
        except RequestsSSLError as e:
            return ProbeResult(host=host, port=port, status=ProbeStatus.TLS_ERROR,
                               detail=f"TLS handshake failed (SSL inspection?): {e}")
        except ssl.SSLError as e:
            return ProbeResult(host=host, port=port, status=ProbeStatus.TLS_ERROR,
                               detail=f"TLS error: {e}")
        except RequestsTimeout:
            return ProbeResult(host=host, port=port, status=ProbeStatus.TIMEOUT,
                               detail=f"HTTPS timed out after {timeout}s")
        except RequestsConnectionError as e:
            return ProbeResult(host=host, port=port, status=ProbeStatus.REFUSED,
                               detail=f"HTTPS connection failed: {e}")


# ---------------------------------------------------------------------------
# Checkpoint mapping — one integration name -> one NET-* checkpoint id.
# Order is stable and matches the JSON config's `integrations` array.
# ---------------------------------------------------------------------------

_CHECKPOINT_IDS: dict[str, str] = {
    "Workday": "NET-001",
    "ServiceNow": "NET-002",
    "SAP SuccessFactors": "NET-003",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_network_checks(
    runner,
    *,
    tcp_prober: Optional[TcpProber] = None,
    https_prober: Optional[HttpsProber] = None,
    config_path: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_SECS,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[CheckResult]:
    """Run TCP + HTTPS reachability probes against vendor endpoints.

    Reads the endpoint catalog from ``required-endpoints.json``. Per-customer
    selection comes from ``runner.config['network']``:

      - ``network.integrations``: list of integration names to probe.
        Defaults to every integration in the JSON marked ``required: true``.
      - ``network.servicenow_instance``: substitutes ``{instance}`` in
        ServiceNow endpoint hostnames. Required if "ServiceNow" is selected
        (otherwise the ServiceNow row is emitted as ``Skipped``).

    Workday and SuccessFactors endpoints are data-center-based, NOT
    tenant-prefixed, so there is intentionally no ``workday_tenant`` or
    ``successfactors_tenant`` knob. See the JSON's ``_hostingNote``.

    The ``tcp_prober`` and ``https_prober`` keyword arguments exist for tests.
    Production callers pass nothing and get the stdlib / requests-backed
    implementations.
    """
    tcp = tcp_prober or _StdlibTcpProber()
    https = https_prober or _RequestsHttpsProber()
    path = config_path or CONFIG_PATH

    try:
        with open(path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
    except FileNotFoundError:
        return [CheckResult(
            checkpoint_id="NET-CONFIG", category="Network",
            priority=Priority.HIGH.value, status=Status.ERROR.value,
            description="Network endpoint catalog",
            result=f"required-endpoints.json not found at {path}",
            remediation="Restore required-endpoints.json from the kit's scripts/flightcheck/config/ directory.",
        )]

    network_config = (runner.config or {}).get("network", {}) if hasattr(runner, "config") else {}
    selected = network_config.get("integrations")
    servicenow_instance = network_config.get("servicenow_instance")

    results: list[CheckResult] = []
    integrations = catalog.get("integrations", [])

    # Default to all required integrations if the user didn't specify.
    if selected is None:
        selected_names = {it["name"] for it in integrations if it.get("required")}
    else:
        selected_names = set(selected)

    for integration in integrations:
        name = integration.get("name", "")
        checkpoint_id = _CHECKPOINT_IDS.get(name)
        if not checkpoint_id:
            continue  # Catalog has a new integration we don't have an ID for yet.

        if name not in selected_names:
            # Skipped: customer didn't opt in. Don't emit noise — but DO emit
            # one Skipped line so customers can confirm the check at least
            # saw the integration.
            results.append(CheckResult(
                checkpoint_id=checkpoint_id, category="Network",
                priority=Priority.MEDIUM.value, status=Status.SKIPPED.value,
                description=f"{name} outbound reachability",
                result=f"Skipped — not in network.integrations",
                remediation=(
                    f"Add \"{name}\" to network.integrations in .local/config.json "
                    "to probe its endpoints."
                ),
            ))
            continue

        results.append(_probe_integration(
            integration=integration,
            checkpoint_id=checkpoint_id,
            tcp=tcp,
            https=https,
            timeout=timeout,
            max_workers=max_workers,
            servicenow_instance=servicenow_instance,
        ))

    return results


def _probe_integration(
    *,
    integration: dict,
    checkpoint_id: str,
    tcp: TcpProber,
    https: HttpsProber,
    timeout: float,
    max_workers: int,
    servicenow_instance: Optional[str],
) -> CheckResult:
    """Probe every endpoint for a single integration and aggregate to one CheckResult."""
    name = integration.get("name", "")
    endpoints = integration.get("endpoints", [])
    resolved, skipped_hosts = _resolve_hosts(endpoints, servicenow_instance)

    if not resolved and skipped_hosts:
        # Every endpoint was a placeholder we couldn't resolve. Skip the whole
        # integration with a remediation pointing at the missing config key.
        return CheckResult(
            checkpoint_id=checkpoint_id, category="Network",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=f"{name} outbound reachability",
            result=f"Skipped — {len(skipped_hosts)} placeholder host(s) had no value",
            remediation=(
                f"Set network.servicenow_instance in .local/config.json to your ServiceNow "
                "instance prefix (e.g. \"contoso\") so {instance} can be substituted."
            ) if name == "ServiceNow" else "Configure the placeholder substitution for this integration.",
        )

    # Probe TCP + HTTPS concurrently across all resolved endpoints.
    probe_results: list[tuple[dict, ProbeResult, ProbeResult]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_probe_one, ep, tcp, https, timeout): ep
            for ep in resolved
        }
        for future in futures:
            ep = futures[future]
            tcp_res, https_res = future.result()
            probe_results.append((ep, tcp_res, https_res))

    # Aggregate: one CheckResult per integration; per-host detail in the result field.
    reachable_count = sum(
        1 for _, t, h in probe_results
        if t.status == ProbeStatus.REACHABLE and h.status == ProbeStatus.REACHABLE
    )
    warning_count = sum(
        1 for _, t, h in probe_results
        if t.status == ProbeStatus.REACHABLE
        and h.status in (ProbeStatus.HTTP_5XX, ProbeStatus.TLS_ERROR)
    )
    failed_count = sum(
        1 for _, t, h in probe_results
        if t.status in (ProbeStatus.REFUSED, ProbeStatus.TIMEOUT, ProbeStatus.DNS_FAILURE)
    )
    total = len(probe_results)

    detail_lines = []
    for ep, t, h in probe_results:
        host_port = f"{ep['host']}:{ep.get('port', 443)}"
        if t.status == ProbeStatus.REACHABLE and h.status == ProbeStatus.REACHABLE:
            detail_lines.append(f"  [OK] {host_port} — {h.detail}")
        elif t.status == ProbeStatus.REACHABLE:
            detail_lines.append(f"  [WARN] {host_port} — TCP open but HTTPS: {h.detail}")
        else:
            detail_lines.append(f"  [FAIL] {host_port} — {t.detail}")
    for placeholder in skipped_hosts:
        detail_lines.append(f"  [SKIP] {placeholder} — placeholder not resolved")

    summary = f"{reachable_count}/{total} reachable"
    if warning_count:
        summary += f", {warning_count} warning"
    if failed_count:
        summary += f", {failed_count} failed"
    if skipped_hosts:
        summary += f", {len(skipped_hosts)} skipped"

    result_text = summary + "\n" + "\n".join(detail_lines)

    if failed_count > 0:
        status = Status.FAILED.value
        remediation = (
            "Open the affected hostnames + port 443 on your outbound firewall. "
            f"Use `python solutions/ess-maker-skills/scripts/flightcheck/cli.py "
            f"--export-firewall-requirements` to generate a network-team handoff doc. "
            f"Vendor IP ranges: {integration.get('ipRangeNote', 'see vendor documentation')}."
        )
    elif warning_count > 0:
        status = Status.WARNING.value
        remediation = (
            "TCP reachable but HTTPS layer failed for at least one host. Common causes: "
            "TLS inspection / SSL bumping by a corporate proxy, or vendor-side 5xx during the probe. "
            "Retry; if persistent, ask your network team to confirm TLS interception is disabled for these hosts."
        )
    else:
        status = Status.PASSED.value
        remediation = ""

    return CheckResult(
        checkpoint_id=checkpoint_id, category="Network",
        priority=Priority.HIGH.value if integration.get("required") else Priority.MEDIUM.value,
        status=status,
        description=f"{name} outbound reachability",
        result=result_text,
        remediation=remediation,
        doc_link=DOC_BASE,
    )


def _probe_one(
    endpoint: dict,
    tcp: TcpProber,
    https: HttpsProber,
    timeout: float,
) -> tuple[ProbeResult, ProbeResult]:
    """Probe a single endpoint: TCP first, then HTTPS (only if TCP succeeded)."""
    host = endpoint["host"]
    port = endpoint.get("port", 443)
    tcp_res = tcp.probe(host, port, timeout)
    if tcp_res.status != ProbeStatus.REACHABLE:
        # Don't bother with HTTPS probe if TCP is blocked — short-circuit.
        return tcp_res, ProbeResult(host=host, port=port, status=ProbeStatus.SKIPPED,
                                    detail="HTTPS not probed (TCP failed)")
    https_res = https.probe(host, port, timeout)
    return tcp_res, https_res


def _resolve_hosts(
    endpoints: list[dict],
    servicenow_instance: Optional[str],
) -> tuple[list[dict], list[str]]:
    """Resolve ``{instance}`` placeholders and partition into resolved vs skipped.

    Workday and SAP SuccessFactors endpoints are NOT tenant-prefixed (per the
    JSON's ``_hostingNote``); only ServiceNow uses ``{instance}``.
    """
    resolved: list[dict] = []
    skipped: list[str] = []
    for ep in endpoints:
        host = ep.get("host", "")
        if "{instance}" in host:
            if not servicenow_instance:
                skipped.append(host)
                continue
            ep = {**ep, "host": host.replace("{instance}", servicenow_instance)}
        resolved.append(ep)
    return resolved, skipped
