# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure controller/transport tests, not evidence of native API qualification."""

from copy import deepcopy




import pytest



from topic_actions_catalog import (
    load_catalog, parse_catalog,
)

from topic_actions_discovery import DiscoveryError, DiscoveryTarget


TARGET = DiscoveryTarget(
    "00000000-0000-0000-0000-000000001111",
    "00000000-0000-0000-0000-000000002222",
    "00000000-0000-0000-0000-000000003333",
)

def catalog_document():
    return {
        "schemaVersion": 1, "authorityStatus": "owner_approved",
        "source": {
            "kind": "ess_package_mapping", "repositoryUrl": "synthetic-source",
            "revision": "r1", "approvalReference": "synthetic-only",
        },
        "packages": [{
            "key": "package", "packageId": "synthetic-package", "packageVersion": "1",
            "agentSchemaNames": ["synthetic.hr"], "sourcePath": "synthetic-path",
            "sourceRevision": "r1", "setCoverage": "complete",
            "requiredTopicCoverage": "complete",
            "requiredTopicSource": {"sourcePath": "synthetic-required", "sourceRevision": "r1"},
            "topics": [
                {"schemaName": f"synthetic.hr.topic.{name}", "classification": "isv_topic", "required": False}
                for name in ("a", "shared", "b", "unrelated")
            ],
        }],
        "sets": [{
            "key": key, "name": key, "integration": {"key": "synthetic", "name": "Synthetic"},
            "sourceVariants": [{
                "packageKey": "package", "membershipStatus": "owner_approved",
                "membershipComplete": True,
                "memberSchemaNames": [f"synthetic.hr.topic.{name}" for name in names],
            }],
        } for key, names in (("alpha", ("a", "shared")), ("beta", ("b", "shared")))],
    }

@pytest.mark.parametrize(("change", "reason"), [
    (lambda doc: doc["packages"].append(deepcopy(doc["packages"][0])), "duplicate_package"),
    (lambda doc: doc["sets"].append(deepcopy(doc["sets"][0])), "duplicate_set"),
    (lambda doc: doc["sets"][0]["sourceVariants"].append(deepcopy(doc["sets"][0]["sourceVariants"][0])), "duplicate_variant"),
    (lambda doc: doc["sets"][0]["sourceVariants"][0].update(packageKey="missing"), "dangling_package"),
    (lambda doc: doc["sets"][0]["sourceVariants"][0]["memberSchemaNames"].append("missing"), "dangling_member"),
    (lambda doc: doc["packages"][0]["topics"][0].update(classification="required_system", required=False), "contradictory_classification"),
    (lambda doc: doc["packages"][0]["topics"][0].update(required=True), "contradictory_classification"),
    (lambda doc: doc["packages"][0]["topics"][0].update(classification="required_system", required=True), "ineligible_member"),
    (lambda doc: doc["packages"][0]["topics"][0].update(classification="other_non_isv"), "ineligible_member"),
    (lambda doc: doc["packages"][0].update(requiredTopicSource=None), "invalid_required_coverage"),
    (lambda doc: doc["packages"][0]["topics"][0].update(required=None), "invalid_required_coverage"),
    (lambda doc: doc.update(schemaVersion=2), "invalid_catalog"),
])
def test_catalog_semantics_reject_unsafe_definitions(change, reason):
    document = catalog_document()
    change(document)
    with pytest.raises(DiscoveryError) as error:
        parse_catalog(document)
    assert error.value.reason == reason

def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schemaVersion": 1, "schemaVersion": 1}', encoding="utf-8")
    with pytest.raises(DiscoveryError) as error:
        load_catalog(path)
    assert error.value.reason == "ambiguous_catalog"
