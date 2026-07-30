# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: grounded Learn research (Table-of-Contents crawl).

The planner grounds every Plan by *researching Microsoft Learn* — a primary
planning activity, not a fallback. The cleanest way to walk the ESS docs is via
the section's Table of Contents (``toc.json``), which Learn publishes as the
authoritative parent/child/sibling tree. This module holds the deterministic
parts of that crawl:

  * :func:`flatten_toc` — turn a fetched ``toc.json`` into a flat node list.
  * :func:`relevance_score` / :func:`select_hrefs` — pick the subset of pages
    to actually read, scoped to the sponsor's intent and a page budget.
  * :func:`classify` — child / sibling / parent / related, from the TOC.

The agent does the HTTP fetching and reasoning; these functions do the
tree math so page selection is stable and testable. :func:`fetch_toc` is a
best-effort convenience for the CLI (network) — the pure functions above never
touch the network.

Note on URLs: the ESS Learn section has already moved once (an old path 301s to
the current one), which is exactly why research is done live. The constants
below were verified on 2026-07-30; the skill re-resolves the base by following
redirects, so a future move only changes the seed, not this logic. We never
fabricate a URL — only ``href``s that appear in a fetched TOC are crawlable.
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

# Verified live 2026-07-30. The skill seeds from the vendored README URL and
# follows redirects to whatever the current base is; this is only a default.
LEARN_SECTION_BASE = "https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service"

# Pages worth reading on almost any greenfield plan (capability surface +
# prerequisites + the ADK command reference). These are hrefs in the ESS TOC.
ALWAYS_INCLUDE: tuple[str, ...] = (
    "overview",
    "prerequisites",
    "deploy-overview-alm",
    "install",
    "commands-reference",
    "securely-integrating-with-external-systems",
)

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
_STOPWORDS = frozenset(
    {"the", "and", "for", "with", "from", "into", "to", "a", "an", "of", "in", "on", "our"}
)


def toc_url(base: str = LEARN_SECTION_BASE) -> str:
    """The ``toc.json`` URL for a section base."""
    return base.rstrip("/") + "/toc.json"


def page_url(href: str, base: str = LEARN_SECTION_BASE) -> str:
    """The page URL for a TOC ``href`` under a section base."""
    return base.rstrip("/") + "/" + href.lstrip("/")


def flatten_toc(toc: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a ``toc.json`` tree into nodes.

    Each node is ``{"href", "title", "depth", "parent", "section", "children"}``
    where ``section`` is the top-level (depth-0) section the node lives under and
    ``children`` is the list of direct child hrefs. Nodes without an ``href``
    (pure grouping headers like "Integrate external systems") are not emitted as
    fetchable pages but still define the ``section`` of their descendants.
    """
    nodes: list[dict[str, Any]] = []

    def walk(items: list[dict[str, Any]], depth: int, parent_title: str, section: str) -> None:
        for item in items:
            title = item.get("toc_title", "")
            href = item.get("href")
            children = item.get("children") or []
            child_hrefs = [c.get("href") for c in children if c.get("href")]
            cur_section = section or title
            if href:
                nodes.append(
                    {
                        "href": href,
                        "title": title,
                        "depth": depth,
                        "parent": parent_title,
                        "section": cur_section,
                        "children": child_hrefs,
                    }
                )
            if children:
                walk(children, depth + 1, title or parent_title, cur_section)

    walk(toc.get("items", []), 0, "", "")
    return nodes


def index_by_href(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {n["href"]: n for n in nodes}


def intent_tokens(*strings: str) -> list[str]:
    """Normalise free-text intent (systems, scenarios, market) into match tokens."""
    tokens: list[str] = []
    for s in strings:
        for word in _TOKEN_SPLIT.split((s or "").lower()):
            if len(word) >= 3 and word not in _STOPWORDS and word not in tokens:
                tokens.append(word)
    return tokens


def relevance_score(node: dict[str, Any], tokens: list[str]) -> int:
    """How many intent tokens appear in a node's href / title / section."""
    haystack = f"{node.get('href', '')} {node.get('title', '')} {node.get('section', '')}".lower()
    return sum(1 for t in tokens if t in haystack)


def select_hrefs(
    nodes: list[dict[str, Any]],
    tokens: list[str],
    *,
    always_include: tuple[str, ...] = ALWAYS_INCLUDE,
    budget: int = 18,
) -> list[str]:
    """Pick which pages to fetch: the always-include backbone plus the most
    intent-relevant pages, breadth-first and capped at ``budget``.

    Relevance-guided selection keeps the crawl bounded and deterministic — a
    ~59-page section collapses to the handful that matter for *this* plan.
    """
    index = index_by_href(nodes)
    selected: list[str] = []
    seen: set[str] = set()

    for href in always_include:
        if href in index and href not in seen:
            selected.append(href)
            seen.add(href)

    scored: list[tuple[int, int, str]] = []
    for node in nodes:
        href = node["href"]
        if href in seen:
            continue
        score = relevance_score(node, tokens)
        if score > 0:
            # breadth-first (shallow first), then most-relevant, then stable href
            scored.append((node.get("depth", 0), -score, href))
    scored.sort()
    for _, _, href in scored:
        if href not in seen:
            selected.append(href)
            seen.add(href)

    return selected[:budget]


def classify(a_href: str, b_href: str, index: dict[str, dict[str, Any]]) -> str:
    """Relationship of ``b`` to ``a`` in the TOC: child / parent / sibling /
    related / unknown. Drives how the crawl expands from a fetched page."""
    a = index.get(a_href)
    b = index.get(b_href)
    if not a or not b:
        return "unknown"
    if b_href in a.get("children", []):
        return "child"
    if a_href in b.get("children", []):
        return "parent"
    if a.get("parent") == b.get("parent") and a.get("depth") == b.get("depth"):
        return "sibling"
    return "related"


def fetch_toc(url: str = "", *, timeout: float = 10.0) -> dict[str, Any]:
    """Best-effort fetch + parse of a ``toc.json`` (network).

    Convenience for the CLI so a maker can preview page selection offline of the
    chat agent. The pure functions above are what the skill relies on; this is
    the one function here that touches the network, and it raises on failure so
    the caller can fall back to the vendored snapshot.
    """
    url = url or toc_url()
    req = urllib.request.Request(url, headers={"User-Agent": "ess-maker-kit-planner"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https Learn URL
        return json.loads(resp.read().decode("utf-8"))
