# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.research — TOC crawl selection (pure logic, no network).

The fixture below mirrors the shape of the real ESS Learn ``toc.json``
(verified 2026-07-30): nested ``items`` with ``href`` + ``toc_title`` and
grouping headers that carry ``children`` but no ``href``.
"""

from __future__ import annotations

import pytest

from planner import research

TOC = {
    "items": [
        {"href": "overview", "toc_title": "Overview"},
        {
            "toc_title": "Deploy the Employee Self-Service agent",
            "children": [
                {"href": "prerequisites", "toc_title": "Prerequisites"},
                {"href": "install", "toc_title": "Install Employee Self-Service agent"},
            ],
        },
        {
            "toc_title": "Integrate external systems",
            "children": [
                {"href": "securely-integrating-with-external-systems", "toc_title": "Securely integrating"},
                {
                    "toc_title": "Workday",
                    "children": [
                        {"href": "workday-simplified-setup", "toc_title": "Simplified Workday setup"},
                        {"href": "workday-extensibility", "toc_title": "Extensibility"},
                    ],
                },
                {
                    "href": "servicenow",
                    "toc_title": "Integrating ServiceNow",
                    "children": [
                        {"href": "servicenow-hrsd-itsm", "toc_title": "ServiceNow HRSD and ITSM"},
                    ],
                },
                {"href": "sapsuccessfactors", "toc_title": "SAP SuccessFactors"},
            ],
        },
        {"href": "commands-reference", "toc_title": "Commands reference"},
    ]
}


def test_flatten_captures_depth_section_children():
    nodes = research.flatten_toc(TOC)
    index = research.index_by_href(nodes)

    # A pure grouping header ("Integrate external systems") is not a fetchable page.
    assert "Integrate external systems" not in index

    overview = index["overview"]
    assert overview["depth"] == 0
    assert overview["section"] == "Overview"

    workday_setup = index["workday-simplified-setup"]
    assert workday_setup["depth"] == 2
    assert workday_setup["section"] == "Integrate external systems"
    assert workday_setup["parent"] == "Workday"

    servicenow = index["servicenow"]
    assert servicenow["children"] == ["servicenow-hrsd-itsm"]


def test_intent_tokens_drops_short_and_stopwords():
    tokens = research.intent_tokens("Connect to Workday and ServiceNow HR")
    assert "workday" in tokens
    assert "servicenow" in tokens
    assert "to" not in tokens      # stopword
    assert "hr" not in tokens      # too short (< 3)
    assert "and" not in tokens


def test_relevance_score_counts_token_hits():
    nodes = research.flatten_toc(TOC)
    index = research.index_by_href(nodes)
    score = research.relevance_score(index["servicenow-hrsd-itsm"], ["servicenow", "workday"])
    assert score == 1  # matches "servicenow" only


def test_select_includes_backbone_and_relevant_skips_irrelevant():
    nodes = research.flatten_toc(TOC)
    tokens = research.intent_tokens("workday servicenow")
    selected = research.select_hrefs(nodes, tokens, budget=18)

    # Always-include backbone present.
    for backbone in ("overview", "prerequisites", "install", "commands-reference"):
        assert backbone in selected
    # Intent-relevant subtrees present.
    assert "workday-simplified-setup" in selected
    assert "servicenow" in selected
    # SAP is not intent-relevant and not backbone -> excluded.
    assert "sapsuccessfactors" not in selected


def test_select_respects_budget():
    nodes = research.flatten_toc(TOC)
    tokens = research.intent_tokens("workday servicenow")
    selected = research.select_hrefs(nodes, tokens, budget=3)
    assert len(selected) == 3


def test_classify_relationships():
    nodes = research.flatten_toc(TOC)
    index = research.index_by_href(nodes)
    assert research.classify("servicenow", "servicenow-hrsd-itsm", index) == "child"
    assert research.classify("servicenow-hrsd-itsm", "servicenow", index) == "parent"
    assert research.classify("prerequisites", "install", index) == "sibling"
    assert research.classify("overview", "servicenow", index) == "related"
    assert research.classify("overview", "does-not-exist", index) == "unknown"


def test_toc_and_page_urls():
    base = "https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service"
    assert research.toc_url(base) == base + "/toc.json"
    assert research.page_url("workday", base) == base + "/workday"


def test_strip_html_removes_tags_and_scripts():
    html = "<html><head><style>.x{color:red}</style></head><body><h1>Set up</h1>"
    html += "<script>var a=1;</script><p>Create an <b>environment</b>.</p></body></html>"
    text = research.strip_html(html)
    # Text content survives (tags become spaces, so punctuation may separate);
    # scripts/styles are gone entirely and no angle brackets remain.
    assert "Set up" in text and "Create an" in text and "environment" in text
    assert "color:red" not in text and "var a=1" not in text and "<" not in text


def test_extract_signals_finds_roles_and_outputs():
    text = (
        "<p>The <b>Power Platform administrator</b> creates the environment and "
        "publishes the agent. A maker adds a knowledge source.</p>"
    )
    sig = research.extract_signals(text)
    assert "Power Platform administrator" in sig["roles"]
    assert "maker" in sig["roles"]
    assert "environment" in sig["outputs"]
    assert "knowledge source" in sig["outputs"]
    assert "publish" in sig["outputs"]


def test_extract_signals_dedupes_and_honours_custom_lexicon():
    text = "environment environment ENVIRONMENT"
    sig = research.extract_signals(text, roles=(), outputs=("environment",))
    assert sig["roles"] == []
    assert sig["outputs"] == ["environment"]  # de-duped, case-insensitive


@pytest.mark.live
def test_fetch_toc_live():
    """Opt-in (``--run-live``): the real ESS TOC parses and has known pages."""
    toc = research.fetch_toc()
    nodes = research.flatten_toc(toc)
    hrefs = {n["href"] for n in nodes}
    assert "overview" in hrefs
    assert "servicenow" in hrefs
