"""The eight per-kind crawlers, in crawl order (spec §4).

Tenant-root kinds are enumerated once per tenant and are crawled **first**; the
discovered ``Environment`` list then drives the env-scoped loops (spec §4 "Crawl order").
Each entry maps a kind to its platform surface (§6.2) -- surfaces flagged ``[verify Q-A]``
are the *expected* sources pending confirmation against the live APIs.
"""

from __future__ import annotations

from ..models import Kind
from .base import Crawler

# Tenant-root crawlers, enumerated once per tenant (spec §4 rows 1,2,3,5).
TENANT_ROOT_CRAWLERS: list[Crawler] = [
    # Power Platform / BAP -- environment list.
    Crawler(Kind.ENVIRONMENT, tenant_root=lambda p, n: p.list_environments(n)),
    # Entra ID / Microsoft Graph -- app registrations. [verify Q-A]
    Crawler(Kind.ENTRA_APP, tenant_root=lambda p, n: p.list_entra_apps(n)),
    # Power Platform connector catalog (BAP).
    Crawler(Kind.CONNECTOR, tenant_root=lambda p, n: p.list_connectors(n)),
    # Microsoft Graph -- sites. [verify Q-A]
    Crawler(Kind.SHAREPOINT_SITE, tenant_root=lambda p, n: p.list_sharepoint_sites(n)),
]

# Env-scoped crawlers, enumerated inside each environment (spec §4 rows 4,6,7,8).
ENV_SCOPED_CRAWLERS: list[Crawler] = [
    # Dataverse -- connection / connectionreference.
    Crawler(Kind.CONNECTION, env_scoped=lambda p, e, n: p.list_connections(e, n)),
    # Copilot Studio -- bot knowledge sources. [verify Q-A]
    Crawler(
        Kind.KNOWLEDGE_SOURCE, env_scoped=lambda p, e, n: p.list_knowledge_sources(e, n)
    ),
    # Dataverse -- installed solutions.
    Crawler(Kind.EXTENSION_PACK, env_scoped=lambda p, e, n: p.list_extension_packs(e, n)),
    # Dataverse -- template/action config.
    Crawler(
        Kind.SCENARIO_TEMPLATE, env_scoped=lambda p, e, n: p.list_scenario_templates(e, n)
    ),
]


def all_crawlers() -> list[Crawler]:
    return [*TENANT_ROOT_CRAWLERS, *ENV_SCOPED_CRAWLERS]
