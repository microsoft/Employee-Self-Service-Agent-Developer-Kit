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

The CLI can fetch and cache the selected pages through :func:`collect_research`,
returning their readable text and provenance together so the agent need not fetch
them again. The selection functions remain pure and independently testable.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .plan_model import write_json_atomic

# Verified live 2026-07-30. The skill seeds from the vendored README URL and
# follows redirects to whatever the current base is; this is only a default.
LEARN_SECTION_BASE = "https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service"
RESEARCH_MAX_AGE = timedelta(hours=24)

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

# Default recognition vocabulary for :func:`extract_signals`. The vendored facts
# file (``planner_facts.json``) is the source of truth at runtime; these are the
# offline fallback so the pure function stands alone and is testable. The lexicon
# only helps *spot* a role/output in prose — the actual value is read off the page.
DEFAULT_ROLE_LEXICON: tuple[str, ...] = (
    "Power Platform administrator",
    "Power Platform admin",
    "Global administrator",
    "Microsoft 365 administrator",
    "Teams administrator",
    "SharePoint administrator",
    "security administrator",
    "Entra administrator",
    "Environment Maker",
    "Cloud Application Administrator",
    "Application Administrator",
    "Network Administrator",
    "Workday administrator",
    "maker",
)
DEFAULT_OUTPUT_LEXICON: tuple[str, ...] = (
    "environment",
    "connection",
    "connector",
    "app registration",
    "Entra app",
    "knowledge source",
    "solution",
    "agent",
    "publish",
)

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


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


def strip_html(html: str) -> str:
    """Reduce an HTML page to readable text: drop script/style, tags, collapse
    whitespace. Deterministic and pure — no parser dependency."""
    without_blocks = _SCRIPT_STYLE_RE.sub(" ", html or "")
    without_tags = _TAG_RE.sub(" ", without_blocks)
    return _WS_RE.sub(" ", without_tags).strip()


def _unique(seq: list[str]) -> list[str]:
    out: list[str] = []
    for item in seq:
        if item not in out:
            out.append(item)
    return out


def extract_signals(
    text: str,
    *,
    roles: "tuple[str, ...] | list[str]" = DEFAULT_ROLE_LEXICON,
    outputs: "tuple[str, ...] | list[str]" = DEFAULT_OUTPUT_LEXICON,
) -> dict[str, list[str]]:
    """Pull role/output candidates out of page text using a recognition lexicon.

    Pure and deterministic: a phrase is a hit when it appears (case-insensitive)
    in the (HTML-stripped) text. Returns ``{"roles": [...], "outputs": [...]}``
    with the lexicon's surface forms, de-duplicated and in lexicon order. This is
    the deterministic half of "read the Learn page and note who does what and
    what it produces" — the agent still reasons over the result.
    """
    haystack = strip_html(text).lower()
    found_roles = _unique([r for r in roles if r and r.lower() in haystack])
    found_outputs = _unique([o for o in outputs if o and o.lower() in haystack])
    return {"roles": found_roles, "outputs": found_outputs}


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

    Used for selection previews and managed research. Raises on failure so the
    caller can report it and explicitly fall back to the vendored snapshot.
    """
    url = url or toc_url()
    req = urllib.request.Request(url, headers={"User-Agent": "ess-maker-kit-planner"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https Learn URL
        return json.loads(resp.read().decode("utf-8"))


def fetch_page_text(url: str, *, timeout: float = 10.0) -> str:
    """Best-effort fetch of a Learn page, reduced to readable text (network).

    Companion to :func:`fetch_toc` for the ``research --extract`` path: the CLI
    fetches each selected page and runs :func:`extract_signals` on the result.
    Raises on network failure so the collector can report incomplete grounding."""
    req = urllib.request.Request(url, headers={"User-Agent": "ess-maker-kit-planner"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — https Learn URL
        charset = resp.headers.get_content_charset() or "utf-8"
        return strip_html(resp.read().decode(charset, errors="replace"))


def _fresh(timestamp: Any, now: datetime) -> bool:
    if timestamp is None:
        return False
    if not isinstance(timestamp, str):
        raise ValueError("Invalid research-cache timestamp; repair the sidecar before retrying.")
    recorded = datetime.fromisoformat(timestamp)
    if recorded.tzinfo is None:
        raise ValueError("Research-cache timestamps must include a timezone.")
    return timedelta(0) <= now - recorded < RESEARCH_MAX_AGE


def collect_research(
    path: str | Path, *, tokens: list[str], base: str = LEARN_SECTION_BASE,
    budget: int = 18, toc: dict[str, Any] | None = None, refresh: bool = False,
) -> dict[str, Any]:
    """Fetch selected Learn text once; reuse fresh pages without changing the plan.

    The managed ``learnCache`` coexists with legacy grounding notes. Failed page
    refreshes retain old text but invalidate it for reuse until retrieval succeeds.
    """
    if budget < 1:
        raise ValueError("The research page budget must be positive.")
    path = Path(path)
    try:
        context = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        context = {}
    if isinstance(context, list):
        context = {"sources": context}
    if not isinstance(context, dict):
        raise ValueError("Research context must be an object or a legacy source list.")
    cache = context.get("learnCache", {})
    if "learnCache" in context and (
        not isinstance(cache, dict) or cache.get("schemaVersion") != 1
        or not isinstance(cache.get("pages"), dict)
    ):
        raise ValueError("Unsupported or invalid research cache; existing notes were not overwritten.")

    base = base.rstrip("/")
    now = datetime.now(timezone.utc)
    fetched_at = now.isoformat()
    toc_source = "file" if toc is not None else "live"
    if toc is None:
        if (
            not refresh and cache.get("base") == base
            and cache.get("tocSource") == "live"
            and _fresh(cache.get("tocFetchedAt"), now)
        ):
            toc = cache.get("toc")
            fetched_at = cache["tocFetchedAt"]
        else:
            toc = fetch_toc(toc_url(base))
    if not isinstance(toc, dict):
        raise ValueError("The Learn table of contents must be a JSON object.")
    nodes = flatten_toc(toc)
    if not nodes:
        raise ValueError("The Learn table of contents contains no pages; research is not grounded.")
    selected = [
        {"href": href, "url": page_url(href, base)}
        for href in select_hrefs(nodes, tokens, budget=budget)
    ]
    index = index_by_href(nodes)
    cached_pages = dict(cache.get("pages", {}))
    pages: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    reused = 0
    for item in selected:
        url, href = item["url"], item["href"]
        cached = cached_pages.get(url)
        if cached is not None and (
            not isinstance(cached, dict) or cached.get("url") != url
            or not isinstance(cached.get("text"), str)
        ):
            raise ValueError(f"Invalid cached Learn page: {url}; existing notes were not overwritten.")
        if cached and not refresh and not cached.get("stale") and _fresh(cached.get("fetchedAt"), now):
            pages.append(cached)
            reused += 1
            continue
        try:
            text = fetch_page_text(url)
            if not text.strip():
                raise ValueError("The Learn page has no readable text.")
        except (OSError, ValueError) as exc:
            errors.append({"url": url, "message": str(exc)})
            if cached:
                cached["stale"] = True
            continue
        page = {
            "href": href, "url": url, "title": index[href]["title"],
            "text": text, "fetchedAt": now.isoformat(),
        }
        cached_pages[url] = page
        pages.append(page)
    context["learnCache"] = {
        "schemaVersion": 1, "base": base, "toc": toc,
        "tocFetchedAt": fetched_at, "tocSource": toc_source,
        "pages": cached_pages, "selected": [page["url"] for page in pages],
    }
    write_json_atomic(path, context)
    return {
        "base": base, "tokens": tokens, "totalPages": len(nodes), "selected": selected,
        "pages": pages, "reusedPages": reused, "errors": errors, "cachePath": str(path),
    }
