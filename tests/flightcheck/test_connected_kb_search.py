# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure-logic tests for connected knowledge-base search normalization."""

from __future__ import annotations

import pytest

from flightcheck.connected_kb_search import (
    ConnectionClassification,
    ServiceNowIdentifier,
    classify_graph_connection,
    extract_servicenow_identifier,
    normalize_external_item_hits,
)
from tests.mocks import graph


SYS_ID = "0123456789abcdef0123456789abcdef"
OTHER_SYS_ID = "fedcba9876543210fedcba9876543210"


def test_normalize_search_hits_preserves_ranked_metadata() -> None:
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                hit_id="opaque-hit",
                rank=1,
                summary="Leave policy summary",
                resource={
                    "id": "external-item",
                    "properties": {
                        "title": "Parental leave",
                        "sys_id": SYS_ID.upper(),
                        "url": (
                            "https://example.service-now.com/kb"
                            f"?id=kb_article&sys_id={SYS_ID}"
                        ),
                        "category": "Benefits",
                    },
                },
            )
        ]
    )

    hits = normalize_external_item_hits(payload)

    assert len(hits) == 1
    assert hits[0].rank == 1
    assert hits[0].hit_id == "opaque-hit"
    assert hits[0].title == "Parental leave"
    assert hits[0].summary == "Leave policy summary"
    assert hits[0].source_url.endswith(f"sys_id={SYS_ID}")
    assert hits[0].properties["category"] == "Benefits"
    assert hits[0].service_now_identifier == ServiceNowIdentifier(
        kind="sys_id",
        value=SYS_ID,
    )
    assert hits[0].skip_reason is None


@pytest.mark.parametrize(
    "resource",
    [
        {"SYS_ID": SYS_ID.upper()},
        {"properties": {"sysId": SYS_ID.upper()}},
    ],
)
def test_extracts_sys_id_from_recognized_root_or_property_alias(
    resource: dict[str, object],
) -> None:
    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "sys_id", SYS_ID
    )


def test_extracts_and_normalizes_valid_article_number() -> None:
    resource = {"properties": {"articleNumber": " kb0012345 "}}

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "number", "KB0012345"
    )


def test_prefers_explicit_sys_id_over_article_number() -> None:
    resource = {
        "number": "KB0012345",
        "properties": {"sys_id": SYS_ID},
    }

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "sys_id", SYS_ID
    )


@pytest.mark.parametrize(
    "url",
    [
        f"https://example.service-now.com/kb_view.do?sys_id={SYS_ID.upper()}",
        f"https://example.service-now.com/kb_view.do?SYSPARM_SYS_ID={SYS_ID}",
        f"https://example.servicenow.com/api/now/table/kb_knowledge/{SYS_ID}",
        f"https://example.service-now.com/kb/{SYS_ID.upper()}/details",
    ],
)
def test_extracts_sys_id_from_supported_servicenow_url_forms(url: str) -> None:
    resource = {"properties": {"sourceUrl": url}}

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "sys_id", SYS_ID
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.servicenow.com/kb_view.do?sysparm_article=kb0012345",
        "https://example.servicenow.com/kb_view.do?ARTICLE_NUMBER=kb0012345",
        "https://example.service-now.com/kb/KB0012345",
    ],
)
def test_extracts_article_number_from_supported_servicenow_url_forms(
    url: str,
) -> None:
    resource = {"webUrl": url}

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "number", "KB0012345"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.service-now.com/kb?q=KB0012345",
        (
            "https://example.service-now.com/nav?"
            "target=https%3A%2F%2Fexample.service-now.com%2Fkb_view.do"
            "%3Fsysparm_article%3DKB0012345"
        ),
        "https://example.service-now.com/kb#KB0012345",
        (
            "https://example.service-now.com/now/nav/ui/classic/params/"
            f"target/kb_knowledge.do%3Fsys_id%3D{SYS_ID}"
        ),
    ],
)
def test_rejects_identifiers_from_untrusted_servicenow_url_locations(
    url: str,
) -> None:
    assert extract_servicenow_identifier({"url": url}) is None


@pytest.mark.parametrize(
    "resource",
    [
        {"sys_id": "not-a-sys-id"},
        {"sys_id": SYS_ID[:-1]},
        {"sys_id": f"{SYS_ID}0"},
        {"sys_id": "g" * 32},
        {"properties": {"sysId": 123}},
    ],
)
def test_rejects_malformed_sys_id(resource: dict[str, object]) -> None:
    assert extract_servicenow_identifier(resource) is None


def test_invalid_alias_before_valid_alias_accepts_valid_candidate() -> None:
    resource = {
        "sys_id": "invalid",
        "sysId": SYS_ID,
    }

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "sys_id", SYS_ID
    )


def test_duplicate_equivalent_alias_values_are_accepted() -> None:
    resource = {
        "SYS_ID": SYS_ID.upper(),
        "properties": {"sysId": f" {SYS_ID} "},
    }

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "sys_id", SYS_ID
    )


def test_conflicting_root_and_property_sys_ids_fail_closed() -> None:
    resource = {
        "sys_id": SYS_ID,
        "number": "KB0012345",
        "properties": {"sysId": "fedcba9876543210fedcba9876543210"},
    }

    assert extract_servicenow_identifier(resource) is None


def test_conflicting_direct_and_url_sys_ids_fail_closed() -> None:
    resource = {
        "sys_id": SYS_ID,
        "sourceUrl": (
            "https://example.service-now.com/kb_view.do"
            f"?sys_id={OTHER_SYS_ID}"
        ),
    }

    assert extract_servicenow_identifier(resource) is None


def test_equivalent_normalized_direct_and_url_sys_ids_are_accepted() -> None:
    resource = {
        "SYS_ID": SYS_ID.upper(),
        "sourceUrl": (
            "https://example.service-now.com/kb_view.do"
            f"?sys_id={SYS_ID}"
        ),
    }

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "sys_id", SYS_ID
    )


def test_invalid_servicenow_url_does_not_conflict_with_direct_sys_id() -> None:
    resource = {
        "sys_id": SYS_ID,
        "sourceUrl": f"ftp://example.service-now.com/kb/{OTHER_SYS_ID}",
    }

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "sys_id", SYS_ID
    )


def test_conflicting_article_numbers_fail_closed() -> None:
    resource = {
        "number": "KB0012345",
        "properties": {"articleNumber": "KB0076543"},
        "url": f"https://example.service-now.com/kb_view.do?sys_id={SYS_ID}",
    }

    assert extract_servicenow_identifier(resource) is None


def test_conflicting_direct_and_url_article_numbers_fail_closed() -> None:
    resource = {
        "number": "KB0012345",
        "webUrl": (
            "https://example.servicenow.com/kb_view.do"
            "?sysparm_article=KB0076543"
        ),
    }

    assert extract_servicenow_identifier(resource) is None


def test_equivalent_normalized_direct_and_url_article_numbers_are_accepted() -> None:
    resource = {
        "article_number": " kb0012345 ",
        "webUrl": (
            "https://example.servicenow.com/kb_view.do"
            "?sysparm_article=KB0012345"
        ),
    }

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "number", "KB0012345"
    )


def test_consistent_direct_and_url_identifiers_preserve_sys_id_priority() -> None:
    resource = {
        "sysId": SYS_ID,
        "number": "KB0012345",
        "properties": {
            "sourceUrl": (
                "https://example.service-now.com/kb_view.do"
                f"?sys_id={SYS_ID}&sysparm_article=KB0012345"
            )
        },
    }

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "sys_id", SYS_ID
    )


def test_article_aliases_ignore_invalid_and_accept_equivalent_values() -> None:
    resource = {
        "number": "invalid",
        "article_number": "kb0012345",
        "properties": {"articleNumber": " KB0012345 "},
    }

    assert extract_servicenow_identifier(resource) == ServiceNowIdentifier(
        "number", "KB0012345"
    )


def test_does_not_derive_identifier_from_opaque_hit_id_title_or_summary() -> None:
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                hit_id=SYS_ID,
                summary="Read KB0012345 for details",
                resource={
                    "properties": {
                        "title": "KB0012345",
                        "url": "https://example.invalid/articles/KB0012345",
                    }
                },
            )
        ]
    )

    hit = normalize_external_item_hits(payload)[0]

    assert hit.service_now_identifier is None
    assert hit.skip_reason == "No verified ServiceNow identifier found."


def test_deduplicates_same_identifier_and_host_preserving_first_ranked_hit() -> None:
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                hit_id="first",
                rank=1,
                resource={
                    "properties": {
                        "title": "First",
                        "sys_id": SYS_ID,
                        "url": (
                            "https://example.service-now.com/kb_view.do"
                            f"?sys_id={SYS_ID}"
                        ),
                    }
                },
            ),
            graph.search_hit(
                hit_id="duplicate",
                rank=2,
                resource={
                    "properties": {
                        "title": "Duplicate",
                        "sysId": SYS_ID.upper(),
                        "sourceUrl": (
                            "https://EXAMPLE.SERVICE-NOW.COM/kb_view.do"
                            f"?sys_id={SYS_ID}"
                        ),
                    }
                },
            ),
            graph.search_hit(
                hit_id="distinct",
                rank=3,
                resource={
                    "properties": {
                        "title": "Distinct",
                        "number": "KB0012345",
                    }
                },
            ),
        ]
    )

    hits = normalize_external_item_hits(payload)

    assert [hit.hit_id for hit in hits] == ["first", "distinct"]
    assert [hit.rank for hit in hits] == [1, 3]


@pytest.mark.parametrize(
    "second_url",
    [
        f"https://other.service-now.com/kb_view.do?sys_id={SYS_ID}",
        None,
        "not-a-valid-url",
    ],
)
def test_preserves_same_identifier_with_untrusted_host_evidence(
    second_url: str | None,
) -> None:
    first_url = f"https://example.service-now.com/kb_view.do?sys_id={SYS_ID}"
    second_properties: dict[str, object] = {
        "title": "Second",
        "sys_id": SYS_ID,
    }
    if second_url is not None:
        second_properties["url"] = second_url
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                hit_id="first",
                rank=1,
                resource={
                    "properties": {
                        "title": "First",
                        "sys_id": SYS_ID,
                        "url": first_url,
                    }
                },
            ),
            graph.search_hit(
                hit_id="second",
                rank=2,
                resource={"properties": second_properties},
            ),
        ]
    )

    hits = normalize_external_item_hits(payload)

    assert [hit.hit_id for hit in hits] == ["first", "second"]


def test_blank_url_alias_uses_valid_source_url_for_identifier_and_output() -> None:
    source_url = f"https://example.service-now.com/kb_view.do?sys_id={SYS_ID}"
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                hit_id="blank-url",
                resource={
                    "url": "  ",
                    "properties": {
                        "title": "Article",
                        "sourceUrl": source_url,
                    }
                },
            )
        ]
    )

    hit = normalize_external_item_hits(payload)[0]

    assert hit.source_url == source_url
    assert hit.service_now_identifier == ServiceNowIdentifier("sys_id", SYS_ID)


def test_preserves_same_identifier_with_ambiguous_host_evidence() -> None:
    first_url = f"https://example.service-now.com/kb_view.do?sys_id={SYS_ID}"
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                hit_id="first",
                resource={
                    "properties": {
                        "sys_id": SYS_ID,
                        "url": first_url,
                    }
                },
            ),
            graph.search_hit(
                hit_id="ambiguous",
                resource={
                    "properties": {
                        "sys_id": SYS_ID,
                        "url": first_url,
                        "sourceUrl": (
                            "https://other.service-now.com/kb_view.do"
                            f"?sys_id={SYS_ID}"
                        ),
                    }
                },
            ),
        ]
    )

    hits = normalize_external_item_hits(payload)

    assert [hit.hit_id for hit in hits] == ["first", "ambiguous"]


def test_conflicted_hit_is_not_deduplicated_by_inconsistent_source_host() -> None:
    first_url = f"https://example.service-now.com/kb_view.do?sys_id={SYS_ID}"
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                hit_id="first",
                rank=1,
                resource={
                    "properties": {
                        "sys_id": SYS_ID,
                        "url": first_url,
                    }
                },
            ),
            graph.search_hit(
                hit_id="conflicted",
                rank=2,
                resource={
                    "properties": {
                        "sys_id": SYS_ID,
                        "url": (
                            "https://example.service-now.com/kb_view.do"
                            f"?sys_id={OTHER_SYS_ID}"
                        ),
                    }
                },
            ),
        ]
    )

    hits = normalize_external_item_hits(payload)

    assert [hit.hit_id for hit in hits] == ["first", "conflicted"]
    assert hits[1].service_now_identifier is None
    assert hits[1].skip_reason == "No verified ServiceNow identifier found."


def test_null_url_alias_uses_valid_root_source_url() -> None:
    source_url = "https://example.servicenow.com/kb/KB0012345"
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                hit_id="null-url",
                resource={
                    "url": None,
                    "sourceUrl": source_url,
                    "properties": {"title": "Article"},
                },
            )
        ]
    )

    hit = normalize_external_item_hits(payload)[0]

    assert hit.source_url == source_url
    assert hit.service_now_identifier == ServiceNowIdentifier(
        "number", "KB0012345"
    )


def test_blank_root_title_uses_non_empty_property_title() -> None:
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                resource={
                    "title": "",
                    "properties": {
                        "title": "Property title",
                        "sys_id": SYS_ID,
                    },
                }
            )
        ]
    )

    assert normalize_external_item_hits(payload)[0].title == "Property title"


def test_missing_identifier_remains_with_stable_skip_reason() -> None:
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                hit_id="opaque",
                resource={"properties": {"title": "Unmapped article"}},
            )
        ]
    )

    hit = normalize_external_item_hits(payload)[0]

    assert hit.service_now_identifier is None
    assert hit.skip_reason == "No verified ServiceNow identifier found."


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"value": None},
        {"value": {}},
        {"value": [None, {"hitsContainers": None}]},
        {"value": [{"hitsContainers": [{}, {"hits": "not-a-list"}]}]},
    ],
)
def test_malformed_or_missing_response_containers_return_no_hits(
    payload: object,
) -> None:
    assert normalize_external_item_hits(payload) == []


def test_malformed_hit_rows_are_ignored_without_guessing() -> None:
    payload = {
        "value": [
            {
                "hitsContainers": [
                    {
                        "hits": [
                            None,
                            "not-a-hit",
                            {"hitId": "opaque", "rank": "first", "resource": None},
                        ]
                    }
                ]
            }
        ]
    }

    hits = normalize_external_item_hits(payload)

    assert len(hits) == 1
    assert hits[0].rank == 0
    assert hits[0].hit_id == "opaque"
    assert hits[0].service_now_identifier is None


@pytest.mark.parametrize(
    "connector_id",
    [
        "/providers/Microsoft.PowerApps/apis/shared_service-now",
        " /PROVIDERS/MICROSOFT.POWERAPPS/APIS/SHARED_SERVICE-NOW ",
    ],
)
def test_classifies_verified_servicenow_connector_metadata(
    connector_id: str,
) -> None:
    classification = classify_graph_connection(
        graph.external_connection(
            connector_id=connector_id,
            name="HR knowledge",
            description="Employee articles",
        )
    )

    assert classification == ConnectionClassification(
        kind="servicenow",
        evidence=(f"connectorId={connector_id.strip()}",),
    )


def test_guessed_servicenow_gallery_id_is_only_ambiguous() -> None:
    classification = classify_graph_connection(
        graph.external_connection(
            connector_id="serviceNowKnowledge",
            name="HR knowledge",
            description="Employee articles",
        )
    )

    assert classification == ConnectionClassification(
        kind="ambiguous",
        evidence=("connectorId=serviceNowKnowledge",),
    )


@pytest.mark.parametrize(
    "connector_id",
    [
        "servicenow",
        "custom-service-now",
        "shared_service-now-preview",
        "custom_service_now",
        "custom service now",
    ],
)
def test_servicenow_connector_id_text_variants_are_ambiguous(
    connector_id: str,
) -> None:
    classification = classify_graph_connection(
        graph.external_connection(
            connector_id=connector_id,
            name="HR knowledge",
            description="Employee articles",
        )
    )

    assert classification == ConnectionClassification(
        kind="ambiguous",
        evidence=(f"connectorId={connector_id}",),
    )


def test_classifies_clear_explicit_non_servicenow_connector_metadata() -> None:
    classification = classify_graph_connection(
        graph.external_connection(
            connector_id="salesforce",
            name="CRM knowledge",
            description="Customer articles",
        )
    )

    assert classification == ConnectionClassification(
        kind="other",
        evidence=("connectorId=salesforce",),
    )


@pytest.mark.parametrize(
    ("name", "description", "expected_evidence"),
    [
        ("ServiceNow HR knowledge", "Employee articles", ("name mentions ServiceNow",)),
        (
            "Service_Now HR knowledge",
            "Employee articles",
            ("name mentions ServiceNow",),
        ),
        (
            "HR knowledge",
            "Synced from Service-Now",
            ("description mentions ServiceNow",),
        ),
    ],
)
def test_name_or_description_hints_alone_are_ambiguous(
    name: str,
    description: str,
    expected_evidence: tuple[str, ...],
) -> None:
    classification = classify_graph_connection(
        graph.external_connection(
            connector_id=None,
            name=name,
            description=description,
        )
    )

    assert classification == ConnectionClassification(
        kind="ambiguous",
        evidence=expected_evidence,
    )


def test_connection_with_no_classification_evidence_is_ambiguous() -> None:
    assert classify_graph_connection({}) == ConnectionClassification(
        kind="ambiguous",
        evidence=(),
    )
