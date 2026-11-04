# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline authoring tests, not live-service or FlightCheck certification.

The fake follows the existing AgentBuilder client/MinimalBotCard contract and
the inspected BotEntity.version transaction. No speculative endpoints are used.
"""

from __future__ import annotations

import base64
import copy
import io
import json
import os
import time
from pathlib import Path

import pytest
import requests
from PIL import Image

import agent_basics as basics
from agentbuilder import AgentBuilderHTTPError
from setup_existing_da import ExistingDASetupError

AGENT_ID = "00000000-0000-4000-8000-000000002222"
SCHEMA = "gptagent_copilotforemployeeselfservicecore"
TARGET = {
    "agent_id": AGENT_ID,
    "schema_name": SCHEMA,
    "tenant_id": "00000000-0000-4000-8000-000000001111",
    "environment_id": "00000000-0000-4000-8000-000000003333",
    "host": "https://example.environment.api.powerplatform.com",
    "ring": "test",
    "api_version": "2022-03-01-preview",
    "workspace_slug": "ess",
    "workspace_fingerprint": "selected-workspace",
}


def png(size: int, *, outline: bool = False, color="blue", format="PNG") -> bytes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0) if outline else color)
    if outline:
        image.putpixel((size // 2, size // 2), (255, 255, 255, 255))
    stream = io.BytesIO()
    image.save(stream, format=format)
    return stream.getvalue()


def encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class Client:
    def __init__(self):
        self.state = {
            "bot": {
                "$kind": "BotEntity",
                "version": 4,
                "cdsBotId": AGENT_ID,
                "schemaName": SCHEMA,
                "displayName": "Employee Support",
                "iconBase64": encoded(png(192)),
                "teamsAppInformation": {
                    "teams": {
                        "outlineIcon": encoded(png(32, outline=True)),
                        "colorIcon": "retained",
                    },
                    "other": "retained",
                },
                "configuration": {"instructions": "Preserve exact instructions"},
                "futureField": {"preserve": [1, 2]},
            },
            "botComponentChanges": [
                {
                    "component": {"instructions": "Preserve these too"},
                    "operation": "unchanged",
                },
            ],
        }
        self.card = {"botId": AGENT_ID, "realm": 0}
        self.configuration = {
            "cdsBotId": AGENT_ID,
            "schemaName": SCHEMA,
            "grsRepositoryId": "stable-family",
            "realm": 0,
        }
        self.status = 200
        self.writes = []
        self.fail_reads = False
        self.fail_after_write = False
        self.timeout = False
        self.apply = True
        self.mutate = None

    def get_agent(self, agent_id):
        assert agent_id == AGENT_ID
        if self.fail_reads:
            raise AgentBuilderHTTPError("read", 403, request_id="read-request")
        return copy.deepcopy(self.card)

    def get_dev_configuration(self, agent_id):
        assert agent_id == AGENT_ID
        return copy.deepcopy(self.configuration)

    def fetch_components(self, agent_id):
        assert agent_id == AGENT_ID
        return copy.deepcopy(self.state)

    def update_bot_entity(self, agent_id, bot):
        assert agent_id == AGENT_ID
        self.writes.append(copy.deepcopy(bot))
        if self.apply and self.status == 200:
            # Mirrors CreateBotEntityTransaction's version precondition/increment.
            if bot["version"] != self.state["bot"]["version"]:
                self.status = 409
            else:
                self.state["bot"] = copy.deepcopy(bot)
                self.state["bot"]["version"] += 1
        if self.mutate:
            self.mutate(self.state)
        if self.fail_after_write:
            self.fail_reads = True
        if self.timeout:
            raise requests.Timeout("uncertain acknowledgment")
        response = requests.Response()
        response.status_code = self.status
        response.headers["x-ms-request-id"] = "save-request"
        return response


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def logos(tmp_path):
    color = tmp_path / "color.png"
    outline = tmp_path / "outline.png"
    color.write_bytes(png(192, color="red"))
    outline.write_bytes(png(32, outline=True))
    return {"logo": str(color), "outline": str(outline)}


@pytest.mark.parametrize(
    "value",
    ["", " ", "a" * 31, "\ud800", "\U0001f600" * 31],
)
def test_invalid_short_names(value):
    with pytest.raises(basics.AgentBasicsError):
        basics.validate_name(value)


@pytest.mark.parametrize(
    "value",
    ["a" * 30, "People & Support", "\U0001f600" * 30, "Support\u200dDesk", " padded "],
)
def test_valid_names_are_not_transformed(value):
    assert basics.validate_name(value) == value


@pytest.mark.parametrize(
    "data",
    [
        b"not a PNG",
        png(191),
        png(192, format="BMP"),
        png(192)[:-20],
        b"x" * (basics.MAX_IMAGE_BYTES + 1),
    ],
    ids=["not-png", "dimensions", "bmp", "truncated", "oversize"],
)
def test_color_png_content_validation(data):
    with pytest.raises(basics.AgentBasicsError):
        basics._png(data, size=192)


def test_animated_and_invalid_outline_pngs():
    stream = io.BytesIO()
    Image.new("RGBA", (192, 192), "red").save(
        stream,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGBA", (192, 192), "blue")],
    )
    with pytest.raises(basics.AgentBasicsError):
        basics._png(stream.getvalue(), size=192)
    for data in (png(32), png(32, color="white"), png(32, color=(0, 0, 0, 0))):
        with pytest.raises(basics.AgentBasicsError):
            basics._png(data, size=32, outline=True)
    assert basics._png(png(32, outline=True), size=32, outline=True)


@pytest.mark.parametrize("properties", ["name", "logo", "both"])
def test_save_preserves_full_entity_and_components(client, logos, properties, tmp_path):
    kwargs = {}
    if properties in ("name", "both"):
        kwargs["name"] = "People Support"
    if properties in ("logo", "both"):
        kwargs.update(logos)
    before = copy.deepcopy(client.state)
    plan = basics.prepare(client, TARGET, **kwargs)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert result["preservation"] == "confirmed"
    assert set(result["properties"].values()) == {"saved"}
    assert len(client.writes) == 1
    written = client.writes[0]
    assert written["version"] == 4
    assert written["configuration"] == before["bot"]["configuration"]
    assert written["futureField"] == before["bot"]["futureField"]
    assert written["teamsAppInformation"]["teams"]["colorIcon"] == "retained"
    assert client.state["botComponentChanges"] == before["botComponentChanges"]
    assert plan["state"] == before
    assert result["publication"] == "Not performed for this change."
    assert result["employeeVisibility"] == "Unverified for this change."


def test_noop_and_unapproved_changes_never_write(client, logos, tmp_path):
    Path(logos["logo"]).write_bytes(png(192))
    plan = basics.prepare(client, TARGET, name="Employee Support", **logos)
    assert not plan["changes"]
    assert (
        basics.save(
            client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
        )["status"]
        == "no_change"
    )
    plan = basics.prepare(client, TARGET, name="New Name")
    assert (
        basics.save(client, plan, "not approved", current_target=TARGET, root=tmp_path)[
            "status"
        ]
        == "review_again"
    )
    assert (
        basics.save(
            client,
            plan,
            plan["reviewId"],
            current_target={**TARGET, "agent_id": "different"},
            root=tmp_path,
        )["status"]
        == "review_again"
    )
    assert client.writes == []


def test_review_drift_invalidates_approval(client, logos, tmp_path):
    first = basics.prepare(client, TARGET, name="New Name", **logos)
    client.state["bot"]["configuration"]["instructions"] = "Concurrent instruction edit"
    refreshed = basics.prepare(client, TARGET, name="New Name", **logos)
    result = basics.save(
        client, refreshed, first["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "review_again"
    assert not client.writes
    Path(logos["logo"]).write_bytes(png(192, color="green"))
    changed_source = basics.prepare(client, TARGET, name="New Name", **logos)
    assert changed_source["reviewId"] != refreshed["reviewId"]


def test_save_point_version_conflict_does_not_retry(client, tmp_path):
    plan = basics.prepare(client, TARGET, name="New Name")
    client.state["bot"]["version"] += 1
    client.state["bot"]["displayName"] = "Concurrent rename"
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "review_again"
    assert result["httpStatus"] == 409
    assert len(client.writes) == 1
    assert client.state["bot"]["displayName"] == "Concurrent rename"
    assert not basics._writes_disabled(tmp_path)


@pytest.mark.parametrize("status", [403, 413, 500])
def test_rejected_saves_are_not_success_or_retried(client, status, tmp_path):
    client.status = status
    plan = basics.prepare(client, TARGET, name="New Name")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "unfinished"
    assert result["properties"]["name"] == ("failed" if status < 500 else "unverified")
    assert result["requestId"] == "save-request"
    assert len(client.writes) == 1


@pytest.mark.parametrize("applied", [True, False])
def test_timeout_readback_without_resending(client, applied, tmp_path):
    client.timeout = True
    client.apply = applied
    plan = basics.prepare(client, TARGET, name="New Name")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["properties"]["name"] == ("saved" if applied else "unverified")
    assert result["transportIssue"] is True
    assert len(client.writes) == 1
    assert basics._writes_disabled(tmp_path) is not applied


def test_readback_denial_remains_unverified(client, tmp_path):
    client.fail_after_write = True
    plan = basics.prepare(client, TARGET, name="New Name")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "unverified"
    assert result["properties"] == {"name": "unverified"}
    assert result["preservation"] == "unverified"
    assert result["readBackIssue"]["httpStatus"] == 403
    assert result["readBackIssue"]["requestId"] == "read-request"
    assert len(client.writes) == 1
    assert result["writesDisabled"] is True
    assert basics._writes_disabled(tmp_path)


def test_readback_without_newer_revision_cannot_confirm_save(client, tmp_path):
    client.mutate = lambda state: state["bot"].update(version=4)
    plan = basics.prepare(client, TARGET, name="New Name")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["properties"] == {"name": "unverified"}
    assert result["status"] == "unfinished"


def test_malformed_readback_remains_unverified(client, tmp_path):
    client.mutate = lambda state: setattr(client, "state", None)
    plan = basics.prepare(client, TARGET, name="New Name")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "unverified"
    assert result["readBackIssue"]["errorType"] == "AgentBasicsError"
    assert len(client.writes) == 1


def test_partial_success_retry_omits_confirmed_name(client, logos, tmp_path):
    original_logo = client.state["bot"]["iconBase64"]
    client.mutate = lambda state: state["bot"].update(iconBase64=original_logo)
    plan = basics.prepare(client, TARGET, name="New Name", **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "unfinished"
    assert result["properties"] == {"name": "saved", "logo": "unverified"}
    recheck = basics.prepare(client, TARGET, name="New Name", **logos)
    assert set(recheck["changes"]) == {"logo"}
    assert len(client.writes) == 1


@pytest.mark.parametrize("field", ["instructions", "components", "logo"])
def test_unrequested_mutation_is_not_reported_complete(client, field, tmp_path):
    def mutate(state):
        if field == "instructions":
            state["bot"]["configuration"]["instructions"] = "Unexpected"
        elif field == "components":
            state["botComponentChanges"] = []
        else:
            state["bot"]["iconBase64"] = encoded(png(192, color="green"))

    client.mutate = mutate
    plan = basics.prepare(client, TARGET, name="New Name")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["properties"]["name"] == "saved"
    assert result["preservation"] == "unverified"
    assert result["status"] == "unfinished"
    assert result["writesDisabled"] is True
    assert basics._writes_disabled(tmp_path)


@pytest.mark.parametrize(
    "state",
    ["small_color", "missing_outline", "missing_color", "invalid_color", "no_teams"],
)
def test_name_only_reviews_service_icon_processing_without_requiring_new_images(
    client, state, tmp_path
):
    bot = client.state["bot"]
    if state == "small_color":
        bot["iconBase64"] = encoded(png(128))
    elif state == "missing_outline":
        bot["teamsAppInformation"]["teams"]["outlineIcon"] = ""
    elif state == "missing_color":
        del bot["iconBase64"]
    elif state == "invalid_color":
        bot["iconBase64"] = "invalid"
    else:
        bot["teamsAppInformation"] = None
    before = copy.deepcopy(client.state)
    plan = basics.prepare(client, TARGET, name="People Support")
    review = basics.review_output(plan, tmp_path)
    assert review["status"] == "review"
    assert review["changedProperties"] == ["name"]
    assert review["serviceIconProcessingRisk"]
    assert "clear outlineIcon and colorIcon" in review["serviceIconProcessingWarning"]
    assert (
        "No replacement images are required" in review["serviceIconProcessingWarning"]
    )
    assert "cannot be guaranteed" in review["retained"]
    assert review["proposed"]["logoSources"] == {}
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "review_again"
    assert "Explicit approval" in result["reason"]
    assert client.state == before
    assert not client.writes
    assert not basics._writes_disabled(tmp_path)
    # Current-state review and keeping the existing name still require no write.
    assert not basics.prepare(client, TARGET)["changes"]
    assert not basics.prepare(client, TARGET, name=bot["displayName"])["changes"]


def test_changed_icon_risk_requires_fresh_review_even_with_risk_consent(
    client, tmp_path
):
    plan = basics.prepare(client, TARGET, name="People Support")
    plan["state"]["bot"]["teamsAppInformation"]["teams"]["outlineIcon"] = ""
    result = basics.save(
        client,
        plan,
        plan["reviewId"],
        current_target=TARGET,
        root=tmp_path,
        accept_service_icon_processing=True,
    )
    assert result["status"] == "review_again"
    assert "risk changed" in result["reason"]
    assert not client.writes
    assert not basics._writes_disabled(tmp_path)


@pytest.mark.parametrize("normalizes", [False, True])
def test_reviewed_risky_rename_uses_existing_logo_and_reports_actual_preservation(
    client, tmp_path, normalizes
):
    client.state["bot"]["iconBase64"] = encoded(png(128))
    before = copy.deepcopy(client.state)

    def normalize(state):
        state["bot"]["iconBase64"] = encoded(png(192))
        teams = state["bot"]["teamsAppInformation"]["teams"]
        teams["outlineIcon"] = ""
        teams["colorIcon"] = ""

    if normalizes:
        client.mutate = normalize
    plan = basics.prepare(client, TARGET, name="ESS HR Nov-3")
    result = basics.save(
        client,
        plan,
        plan["reviewId"],
        current_target=TARGET,
        root=tmp_path,
        accept_service_icon_processing=True,
    )
    assert len(client.writes) == 1
    written = copy.deepcopy(client.writes[0])
    assert written.pop("displayName") == "ESS HR Nov-3"
    expected = copy.deepcopy(before["bot"])
    expected.pop("displayName")
    assert written == expected
    assert result["properties"] == {"name": "saved"}
    assert client.state["bot"]["displayName"] == "ESS HR Nov-3"
    assert result["status"] == ("unfinished" if normalizes else "saved")
    assert result["preservation"] == ("unverified" if normalizes else "confirmed")
    assert result["logoPreservation"] == ("changed" if normalizes else "confirmed")
    assert result["changedLogoFields"] == (
        [
            "iconBase64",
            "teamsAppInformation.teams.outlineIcon",
            "teamsAppInformation.teams.colorIcon",
        ]
        if normalizes
        else []
    )
    assert basics._writes_disabled(tmp_path) is normalizes
    assert client.state["bot"]["configuration"] == before["bot"]["configuration"]
    assert client.state["botComponentChanges"] == before["botComponentChanges"]


def test_icon_risk_consent_cannot_replace_rename_approval(client, tmp_path):
    client.state["bot"]["teamsAppInformation"]["teams"]["outlineIcon"] = ""
    plan = basics.prepare(client, TARGET, name="ESS HR Nov-3")
    result = basics.save(
        client,
        plan,
        "not approved",
        current_target=TARGET,
        root=tmp_path,
        accept_service_icon_processing=True,
    )
    assert result["status"] == "review_again"
    assert not client.writes


def test_confirmed_null_icon_can_be_retained_by_name_only_save(client, tmp_path):
    client.state["bot"]["iconBase64"] = None
    before = copy.deepcopy(client.state["bot"]["teamsAppInformation"])
    plan = basics.prepare(client, TARGET, name="People Support")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert client.state["bot"]["iconBase64"] is None
    assert client.state["bot"]["teamsAppInformation"] == before


def test_explicit_combined_change_can_replace_readable_nonconforming_icons(
    client, logos, tmp_path
):
    client.state["bot"]["iconBase64"] = encoded(png(128))
    client.state["bot"]["teamsAppInformation"]["teams"]["outlineIcon"] = ""
    plan = basics.prepare(client, TARGET, name="People Support", **logos)
    assert set(plan["changes"]) == {"name", "logo"}
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert client.writes[0]["iconBase64"] == encoded(Path(logos["logo"]).read_bytes())


@pytest.mark.parametrize("asset", ["logo", "outline"])
def test_single_uploaded_asset_retains_other_valid_current_asset(
    client, logos, tmp_path, asset
):
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    image.putpixel((0, 0), (255, 255, 255, 255))
    image.save(logos["outline"])
    before = copy.deepcopy(client.state["bot"])
    plan = basics.prepare(client, TARGET, **{asset: logos[asset]})
    assert set(plan["sources"]) == {"color" if asset == "logo" else "outline"}
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    if asset == "logo":
        assert (
            client.state["bot"]["teamsAppInformation"] == before["teamsAppInformation"]
        )
    else:
        assert client.state["bot"]["iconBase64"] == before["iconBase64"]


@pytest.mark.parametrize("asset", ["logo", "outline"])
def test_single_asset_requires_a_valid_retained_counterpart(client, logos, asset):
    if asset == "logo":
        client.state["bot"]["teamsAppInformation"]["teams"]["outlineIcon"] = ""
        missing = "outline"
    else:
        client.state["bot"]["iconBase64"] = None
        missing = "color"
    with pytest.raises(basics.AgentBasicsError, match=f"Supply a valid {missing} PNG"):
        basics.prepare(client, TARGET, **{asset: logos[asset]})
    assert not client.writes


def test_unreadable_outline_allows_name_but_not_logo_edit(client, logos, tmp_path):
    client.state["bot"]["teamsAppInformation"]["teams"]["outlineIcon"] = "invalid"
    name_plan = basics.prepare(client, TARGET, name="New Name")
    assert name_plan["logoError"]
    with pytest.raises(basics.AgentBasicsError, match="base64"):
        basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, name_plan, name_plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert (
        client.state["bot"]["teamsAppInformation"]["teams"]["outlineIcon"] == "invalid"
    )


def test_unreadable_name_allows_logo_but_not_name_edit(client, logos, tmp_path):
    del client.state["bot"]["displayName"]
    with pytest.raises(basics.AgentBasicsError, match="name is unreadable"):
        basics.prepare(client, TARGET, name="New Name")
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert "displayName" not in client.state["bot"]


@pytest.mark.parametrize("application", [None, {}, {"teams": None}])
def test_first_outline_and_nullable_application_state(
    client, logos, application, tmp_path
):
    client.state["bot"]["teamsAppInformation"] = application
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"


def test_malformed_postsave_application_keeps_property_results(client, logos, tmp_path):
    client.mutate = lambda state: state["bot"].update(teamsAppInformation="malformed")
    plan = basics.prepare(client, TARGET, name="New Name", **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["properties"] == {"name": "saved", "logo": "unverified"}
    assert result["preservation"] == "unverified"


@pytest.mark.parametrize("realm", [1, 2])
def test_test_and_prod_cannot_be_edited(client, realm):
    client.card["realm"] = realm
    with pytest.raises(ExistingDASetupError):
        basics.prepare(client, TARGET, name="New Name")
    assert not client.writes


def test_unenrolled_native_authoring_and_registry_identity(client):
    client.card.pop("realm")
    plan = basics.prepare(client, TARGET, name="New Name")
    assert plan["target"]["qualityGate"] == "unenrolled authoring"
    assert plan["target"]["product"] == "employee-self-service-hub"
    client.state["bot"]["schemaName"] = "custom_schema"
    with pytest.raises(basics.AgentBasicsError, match="not a supported ESS"):
        basics.prepare(
            client, {**TARGET, "schema_name": "custom_schema"}, name="New Name"
        )


@pytest.mark.parametrize(
    "mutation",
    ["card", "dev_id", "dev_schema", "fetched_id", "schema", "version", "components"],
)
def test_identity_and_preservation_preconditions(client, mutation):
    if mutation == "card":
        client.card["botId"] = TARGET["tenant_id"]
    elif mutation == "dev_id":
        client.configuration["cdsBotId"] = TARGET["tenant_id"]
    elif mutation == "dev_schema":
        client.configuration["schemaName"] = "different"
    elif mutation == "fetched_id":
        client.state["bot"]["cdsBotId"] = TARGET["tenant_id"]
    elif mutation == "schema":
        client.state["bot"]["schemaName"] = "different"
    elif mutation == "version":
        client.state["bot"]["version"] = None
    else:
        client.state.pop("botComponentChanges")
    with pytest.raises((basics.AgentBasicsError, ExistingDASetupError)):
        basics.prepare(client, TARGET, name="New Name")
    assert not client.writes


def test_previews_and_cleanup_never_change_maker_sources(client, logos, tmp_path):
    original_sources = {key: Path(path).read_bytes() for key, path in logos.items()}
    plan = basics.prepare(client, TARGET, **logos)
    review = basics.review_output(plan, tmp_path)
    assert Path(review["current"]["colorPreview"]).read_bytes() == png(192)
    assert review["proposed"]["logoSources"]["color"] == str(
        Path(logos["logo"]).resolve()
    )
    directory = tmp_path / basics.PREVIEW_DIRECTORY
    unrelated = directory / "maker-owned.png"
    unrelated.write_bytes(b"keep")
    basics.cleanup(tmp_path, plan["reviewId"])
    assert not Path(review["current"]["colorPreview"]).exists()
    assert unrelated.exists()
    assert {
        key: Path(path).read_bytes() for key, path in logos.items()
    } == original_sources
    with pytest.raises(basics.AgentBasicsError):
        basics.cleanup(tmp_path, "..")
    assert not client.writes


def test_interrupted_preview_cleanup_only_removes_expired_adk_copies(tmp_path):
    directory = tmp_path / basics.PREVIEW_DIRECTORY
    directory.mkdir(parents=True)
    expired = directory / f"{'a' * 64}-color.png"
    fresh = directory / f"{'b' * 64}-outline.png"
    unrelated = directory / "maker.png"
    for path in (expired, fresh, unrelated):
        path.write_bytes(b"image")
    for path in (expired, unrelated):
        os.utime(path, (time.time() - 7200,) * 2)
    basics.cleanup_expired(tmp_path)
    assert not expired.exists()
    assert fresh.exists() and unrelated.exists()


@pytest.fixture
def workspace(tmp_path):
    folder = tmp_path / "workspace" / "agents" / "ess"
    folder.mkdir(parents=True)
    (folder / "agent.mcs.yml").write_text("kind: GptComponent\n")
    config = {
        "configVersion": basics.EXPECTED_CONFIG_VERSION,
        "releaseLine": "da",
        "activeAgent": "ess",
        "agent": {"botId": AGENT_ID, "schemaName": SCHEMA},
    }
    state = {
        "schema_version": 4,
        "environment": {
            "id": TARGET["environment_id"],
            "tenant_id": TARGET["tenant_id"],
            "power_platform_api_endpoint": TARGET["host"],
            "ring": TARGET["ring"],
            "api_version": TARGET["api_version"],
        },
        "agents": {
            AGENT_ID: {
                "agent": {
                    "id": AGENT_ID,
                    "schema_name": SCHEMA,
                    "workspace_slug": "ess",
                    "name": "Cached old label",
                },
                "workspace": {
                    "folder": str(folder.relative_to(tmp_path)),
                    "agent_path": "agent.mcs.yml",
                },
                "steps": {"SETUP-07": {"state": "done"}},
                "connect_ready": False,
            }
        },
    }
    (tmp_path / ".local" / "setup").mkdir(parents=True)
    (tmp_path / ".local" / "config.json").write_text(json.dumps(config))
    (tmp_path / ".local" / "setup" / "config.json").write_text(json.dumps(state))
    return tmp_path


def test_canonical_target_without_runtime_readiness(workspace):
    target = basics.selected_target(workspace)
    assert target["agent_id"] == AGENT_ID
    assert target["schema_name"] == SCHEMA
    assert "agent_name" not in target
    (workspace / "workspace" / "agents" / "ess" / "agent.mcs.yml").unlink()
    with pytest.raises(basics.AgentBasicsError, match="workspace is missing"):
        basics.selected_target(workspace)


def test_target_disagreement_and_legacy_no_write(workspace):
    path = workspace / ".local" / "config.json"
    config = json.loads(path.read_text())
    config["agent"]["botId"] = TARGET["tenant_id"]
    path.write_text(json.dumps(config))
    with pytest.raises(basics.AgentBasicsError, match="disagree"):
        basics.selected_target(workspace)
    config["releaseLine"] = "legacy"
    path.write_text(json.dumps(config))
    with pytest.raises(basics.AgentBasicsError, match="compatible kit"):
        basics.selected_target(workspace)


@pytest.fixture
def cli(monkeypatch, workspace, client):
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(basics, "authenticate", lambda *args, **kwargs: "fake-token")
    monkeypatch.setattr(basics, "AgentBuilderClient", lambda *args, **kwargs: client)
    return workspace


def result_json(capsys):
    output = capsys.readouterr().out
    return json.loads(output.split("_JSON:", 1)[1])


def test_cli_refreshes_after_approval_and_never_renames_local_files(
    cli, client, capsys, monkeypatch
):
    events = []
    monkeypatch.setattr(
        basics,
        "emit_capability_use",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    local_before = {
        path: path.read_bytes() for path in cli.rglob("*") if path.is_file()
    }
    assert basics.main(["preview", "--name", "People Support"]) == 0
    preview = result_json(capsys)
    client.state["bot"]["displayName"] = "Concurrent name"
    client.state["bot"]["version"] += 1
    assert (
        basics.main(
            ["save", "--name", "People Support", "--approval", preview["reviewId"]]
        )
        == 2
    )
    assert result_json(capsys)["status"] == "review_again"
    assert not client.writes
    assert basics.main(["preview", "--name", "People Support"]) == 0
    refreshed = result_json(capsys)
    assert (
        basics.main(
            ["save", "--name", "People Support", "--approval", refreshed["reviewId"]]
        )
        == 0
    )
    assert result_json(capsys)["status"] == "saved"
    assert all(path.read_bytes() == data for path, data in local_before.items())
    assert all(args == ("agent_basics",) and not kwargs for args, kwargs in events)
    assert not (
        cli / basics.PREVIEW_DIRECTORY / f"{refreshed['reviewId']}-color.png"
    ).exists()


def test_cli_risky_rename_requires_separate_consent_and_no_new_logo(
    cli, client, capsys
):
    client.state["bot"]["teamsAppInformation"]["teams"]["outlineIcon"] = ""
    before = copy.deepcopy(client.state["bot"])
    assert basics.main(["preview", "--name", "ESS HR Nov-3"]) == 0
    preview = result_json(capsys)
    assert preview["serviceIconProcessingWarning"]
    assert not client.writes
    command = ["save", "--name", "ESS HR Nov-3", "--approval", preview["reviewId"]]
    assert basics.main(command) == 2
    assert result_json(capsys)["status"] == "review_again"
    assert not client.writes
    assert basics.main(command + ["--accept-service-icon-processing"]) == 0
    saved = result_json(capsys)
    assert saved["properties"] == {"name": "saved"}
    assert saved["logoPreservation"] == "confirmed"
    assert len(client.writes) == 1
    assert client.writes[0]["iconBase64"] == before["iconBase64"]
    assert client.writes[0]["teamsAppInformation"] == before["teamsAppInformation"]


def test_cli_new_review_invalidates_icon_risk_consent(cli, client, capsys):
    client.state["bot"]["teamsAppInformation"]["teams"]["outlineIcon"] = ""
    assert basics.main(["preview", "--name", "ESS HR Nov-3"]) == 0
    preview = result_json(capsys)
    client.state["bot"]["iconBase64"] = encoded(png(128))
    client.state["bot"]["version"] += 1
    assert (
        basics.main(
            [
                "save",
                "--name",
                "ESS HR Nov-3",
                "--approval",
                preview["reviewId"],
                "--accept-service-icon-processing",
            ]
        )
        == 2
    )
    assert result_json(capsys)["status"] == "review_again"
    assert not client.writes


def test_cleanup_failure_does_not_mask_persisted_result(cli, capsys, monkeypatch):
    assert basics.main(["preview", "--name", "People Support"]) == 0
    preview = result_json(capsys)

    def locked(*args):
        raise PermissionError("locked")

    monkeypatch.setattr(basics, "cleanup", locked)
    assert (
        basics.main(
            ["save", "--name", "People Support", "--approval", preview["reviewId"]]
        )
        == 2
    )
    result = result_json(capsys)
    assert result["status"] == "saved"
    assert result["properties"] == {"name": "saved"}
    assert "cleanupIssue" in result


def test_access_denial_returns_sanitized_diagnostic(cli, client, capsys):
    client.fail_reads = True
    assert basics.main(["preview", "--name", "People Support"]) == 2
    result = result_json(capsys)
    assert result["httpStatus"] == 403
    assert result["requestId"] == "read-request"
    assert "People Support" not in json.dumps(result)
    assert not client.writes


def test_unsafe_cli_save_stops_writes_until_fresh_reviewed_recovery(
    cli, client, capsys
):
    assert basics.main(["preview", "--name", "People Support"]) == 0
    preview = result_json(capsys)
    client.mutate = lambda state: state["bot"]["configuration"].update(
        instructions="Unexpected service mutation"
    )
    assert (
        basics.main(
            ["save", "--name", "People Support", "--approval", preview["reviewId"]]
        )
        == 2
    )
    result = result_json(capsys)
    assert result["properties"] == {"name": "saved"}
    assert result["writesDisabled"] is True
    assert (
        basics.main(
            ["save", "--name", "Another Name", "--approval", preview["reviewId"]]
        )
        == 2
    )
    assert result_json(capsys)["writesDisabled"] is True
    assert len(client.writes) == 1
    assert basics.main(["view"]) == 0
    recovery = result_json(capsys)
    assert recovery["writesDisabled"] is True
    client.state["bot"]["version"] += 1
    assert basics.main(["resume-writes", "--approval", recovery["reviewId"]]) == 2
    assert result_json(capsys)["status"] == "review_again"
    assert basics._writes_disabled(cli)
    assert basics.main(["view"]) == 0
    recovery = result_json(capsys)
    assert basics.main(["resume-writes", "--approval", recovery["reviewId"]]) == 0
    assert result_json(capsys)["writeAttempted"] is False
    assert not basics._writes_disabled(cli)
    assert len(client.writes) == 1
    # Resumption neither restores instructions nor repeats the confirmed rename.
    assert client.state["bot"]["displayName"] == "People Support"
    assert (
        client.state["bot"]["configuration"]["instructions"]
        == "Unexpected service mutation"
    )


def test_explicit_disable_survives_safe_inflight_save_and_allows_readonly_review(
    cli, client, capsys
):
    assert basics.main(["preview", "--name", "People Support"]) == 0
    preview = result_json(capsys)
    client.mutate = lambda state: basics.disable_writes(cli)
    assert (
        basics.main(
            ["save", "--name", "People Support", "--approval", preview["reviewId"]]
        )
        == 0
    )
    saved = result_json(capsys)
    assert saved["status"] == "saved"
    assert saved["writesDisabled"] is True
    assert not (cli / basics.WRITE_PENDING_FILE).exists()
    assert basics.main(["disable-writes"]) == 0
    assert result_json(capsys)["writesDisabled"] is True
    assert basics.main(["view"]) == 0
    assert result_json(capsys)["writesDisabled"] is True
    assert len(client.writes) == 1


def test_cannot_create_pending_marker_means_no_service_write(
    cli, client, capsys, monkeypatch
):
    assert basics.main(["preview", "--name", "People Support"]) == 0
    preview = result_json(capsys)

    def unavailable(*args, **kwargs):
        raise PermissionError("local storage unavailable")

    monkeypatch.setattr(basics, "disable_writes", unavailable)
    assert (
        basics.main(
            ["save", "--name", "People Support", "--approval", preview["reviewId"]]
        )
        == 2
    )
    assert result_json(capsys)["status"] == "blocked"
    assert not client.writes


def test_failure_releasing_marker_preserves_actual_save_result(
    cli, client, capsys, monkeypatch
):
    assert basics.main(["preview", "--name", "People Support"]) == 0
    preview = result_json(capsys)
    original_unlink = Path.unlink

    def locked(path, *args, **kwargs):
        if path == cli / basics.WRITE_PENDING_FILE:
            raise PermissionError("locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    assert (
        basics.main(
            ["save", "--name", "People Support", "--approval", preview["reviewId"]]
        )
        == 2
    )
    result = result_json(capsys)
    assert result["status"] == "saved"
    assert result["properties"] == {"name": "saved"}
    assert result["writeStopIssue"]
    assert result["writesDisabled"] is True


def test_interrupted_save_blocks_new_writes_before_authentication(
    cli, client, capsys, monkeypatch
):
    basics.disable_writes(cli, pending=True)

    def unexpected_auth(*args, **kwargs):
        pytest.fail("A stopped save must not attempt authentication or a service call")

    monkeypatch.setattr(basics, "authenticate", unexpected_auth)
    assert (
        basics.main(["save", "--name", "People Support", "--approval", "a" * 64]) == 2
    )
    result = result_json(capsys)
    assert result["writesDisabled"] is True
    assert not client.writes


def test_preexisting_stop_is_not_cleared_by_noop_or_unapproved_save(client, tmp_path):
    basics.disable_writes(tmp_path)
    plan = basics.prepare(client, TARGET, name=client.state["bot"]["displayName"])
    assert (
        basics.save(
            client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
        )["status"]
        == "no_change"
    )
    plan = basics.prepare(client, TARGET, name="People Support")
    assert (
        basics.save(client, plan, "not approved", current_target=TARGET, root=tmp_path)[
            "status"
        ]
        == "review_again"
    )
    assert basics._writes_disabled(tmp_path)
    with pytest.raises(basics.AgentBasicsError, match="writes are disabled"):
        basics.save(
            client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
        )
    assert not client.writes
