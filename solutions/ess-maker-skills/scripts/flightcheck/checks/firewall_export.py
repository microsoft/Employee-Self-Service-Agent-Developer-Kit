# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Firewall requirements export — emits a markdown handoff doc for the
customer's network team.

Pure file-render helper. Does NOT make any network calls or consume any
external API contracts, so the cardinal rule does not apply. The same
required-endpoints.json that ``checks/network.py`` reads is the
authoritative source.

Ported from ess-preflight-validator commit 9ed2055
(`PowerShell/Export-FirewallRequirements.ps1`).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config",
    "required-endpoints.json",
)


def export_firewall_requirements(
    config: dict,
    out_path: str,
    *,
    catalog_path: str | None = None,
    now: datetime | None = None,
) -> str:
    """Render the firewall-requirements markdown doc and write it to ``out_path``.

    Parameters
    ----------
    config:
        The customer's ``.local/config.json`` (used only to surface
        ``network.servicenow_instance`` if set, so the network team sees a
        resolved hostname instead of ``{instance}``).
    out_path:
        Path of the file to write.
    catalog_path:
        Optional override for the ``required-endpoints.json`` location.
        Defaults to the kit-shipped copy under
        ``solutions/ess-maker-skills/scripts/flightcheck/config/``.
    now:
        Optional ``datetime`` for the document's "generated at" stamp.
        Defaults to ``datetime.now(timezone.utc)``. Exposed so tests can
        pin a deterministic timestamp for golden-file comparison.

    Returns
    -------
    The absolute path of the written file. Existence of the parent
    directory is the caller's responsibility (``cli.py`` creates it).
    """
    path = catalog_path or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    servicenow_instance = (config.get("network") or {}).get("servicenow_instance")
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = []
    lines.append("# ESS Firewall Allow-List Requirements")
    lines.append("")
    lines.append(f"_Generated: {stamp}_")
    lines.append("")
    lines.append(
        "This document lists the outbound network endpoints the Employee "
        "Self-Service (ESS) Copilot Studio agent's connectors need to reach. "
        "Hand it to your corporate IT / network team and ask them to allow "
        "outbound HTTPS (TCP 443) to every host listed below."
    )
    lines.append("")
    lines.append("**Scope:** Vendor endpoints only (Workday, ServiceNow, SAP SuccessFactors).")
    lines.append("Microsoft endpoints are documented authoritatively by Microsoft:")
    for link in catalog.get("microsoftEndpointsReference", {}).get("links", []):
        lines.append(f"- [{link.get('title', '')}]({link.get('url', '')})")
    lines.append("")
    lines.append("---")
    lines.append("")

    for integration in catalog.get("integrations", []):
        name = integration.get("name", "")
        required = integration.get("required", False)
        hosting = integration.get("hostingPattern", "")
        ip_note = integration.get("ipRangeNote", "")

        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"- **Required:** {'Yes' if required else 'Optional'}")
        lines.append(f"- **Hosting pattern:** {hosting}")
        if ip_note:
            lines.append(f"- **IP range guidance:** {ip_note}")
        lines.append("")
        lines.append("| Host | Port | Purpose |")
        lines.append("|---|---|---|")
        for endpoint in integration.get("endpoints", []):
            host = endpoint.get("host", "")
            port = endpoint.get("port", 443)
            purpose = endpoint.get("purpose", "")
            display_host = host
            if "{instance}" in host:
                if servicenow_instance:
                    display_host = host.replace("{instance}", servicenow_instance)
                else:
                    display_host = host + " _(set `network.servicenow_instance` in `.local/config.json` to resolve)_"
            lines.append(f"| `{display_host}` | {port} | {purpose} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Notes for the network team")
    lines.append("")
    lines.append(
        "- All listed hosts must be reachable on **TCP port 443** outbound from "
        "the Power Platform and Copilot Studio runtime infrastructure as well "
        "as from the customer's deployment workstations."
    )
    lines.append(
        "- **TLS inspection (SSL bumping)** between Power Platform and these "
        "vendor hosts can break the connectors. If TLS inspection is in place, "
        "please exempt the listed hostnames or ensure the inspected certificate "
        "chains validate cleanly."
    )
    lines.append(
        "- Workday and SAP SuccessFactors hostnames are **data-center based**, "
        "not tenant-prefixed. Confirm with the customer's Workday / SAP account "
        "team which data center their tenant is hosted in before pruning the "
        "list to a subset."
    )
    lines.append("")

    content = "\n".join(lines) + "\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return out_path
