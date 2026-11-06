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
import multiprocessing
import os
import time
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from PIL import Image, PngImagePlugin

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
QUALITY_IDS = {
    "dev": AGENT_ID,
    "test": "00000000-0000-4000-8000-000000004444",
    "prod": "00000000-0000-4000-8000-000000005555",
}


def png(size: int, *, outline: bool = False, color="blue", format="PNG") -> bytes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0) if outline else color)
    if outline:
        image.putpixel((size // 2, size // 2), (255, 255, 255, 255))
    stream = io.BytesIO()
    image.save(stream, format=format)
    return stream.getvalue()


def animated_png(*, second_color="blue", duration=100, loop=0) -> bytes:
    stream = io.BytesIO()
    Image.new("RGBA", (192, 192), "red").save(
        stream,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGBA", (192, 192), second_color)],
        duration=duration,
        loop=loop,
    )
    return stream.getvalue()


def encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class Client:
    def __init__(self, agent_id=AGENT_ID, *, realm=0, schema=SCHEMA):
        self.agent_id = agent_id
        self.state = {
            "bot": {
                "$kind": "BotEntity",
                "version": 4,
                "cdsBotId": agent_id,
                "schemaName": schema,
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
                    "$kind": "BotComponentUpdate",
                    "component": {
                        "$kind": "GptComponent",
                        "id": "00000000-0000-4000-8000-000000006666",
                        "schemaName": f"{schema}.gpt.default",
                        "displayName": "Employee Support",
                        "instructions": "Preserve these too",
                        "description": "Preserve description",
                        "metadata": {"instructions": "Preserve GPT instructions"},
                    },
                    "operation": "unchanged",
                },
            ],
            "changeToken": "current-component-token",
        }
        self.card = {"botId": agent_id, "realm": realm}
        self.configuration = {
            "cdsBotId": agent_id,
            "schemaName": schema,
            "grsRepositoryId": "stable-family",
            "realm": realm,
        }
        self.status = 200
        self.writes = []
        self.fail_reads = False
        self.fail_after_write = False
        self.timeout = False
        self.apply = True
        self.mutate = None
        self.host = TARGET["host"]
        self.api_version = TARGET["api_version"]
        self.headers = {"Accept": "application/json"}
        self.session = SimpleNamespace(request=self.update_components)
        self.component_writes = []

    def get_agent(self, agent_id):
        assert agent_id == self.agent_id
        if self.fail_reads:
            raise AgentBuilderHTTPError("read", 403, request_id="read-request")
        return copy.deepcopy(self.card)

    def get_dev_configuration(self, agent_id):
        assert agent_id == self.agent_id
        return copy.deepcopy(self.configuration)

    def fetch_components(self, agent_id):
        assert agent_id == self.agent_id
        return copy.deepcopy(self.state)

    def update_bot_entity(self, agent_id, bot):
        return self._update(agent_id, bot)

    def update_components(self, method, url, **kwargs):
        assert method == "PUT"
        assert url == f"{self.host}/copilotstudio/minimalBots/api/{self.agent_id}/components"
        assert kwargs["params"] == {"api-version": basics.NATIVE_ALM_API_VERSION}
        assert kwargs["allow_redirects"] is False
        body = kwargs["json"]
        assert len(body["botComponentChanges"]) == 1
        update = body["botComponentChanges"][0]
        assert update["$kind"] == "BotComponentUpdate"
        self.component_writes.append(copy.deepcopy(body))
        return self._update(
            self.agent_id, body["bot"], update["component"], body["changeToken"]
        )

    def _update(self, agent_id, bot, component=None, change_token=None):
        assert agent_id == self.agent_id
        self.writes.append(copy.deepcopy(bot))
        if self.apply and self.status == 200:
            # Mirrors CreateBotEntityTransaction's version precondition/increment.
            if bot["version"] != self.state["bot"]["version"] or (
                change_token is not None and change_token != self.state["changeToken"]
            ):
                self.status = 409
            else:
                self.state["bot"] = copy.deepcopy(bot)
                self.state["bot"]["version"] += 1
                if component is not None:
                    assert component["id"] == self.state["botComponentChanges"][0]["component"]["id"]
                    self.state["botComponentChanges"][0]["component"] = copy.deepcopy(component)
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


class QualityClient:
    def __init__(self):
        self.gates = {
            gate: Client(
                QUALITY_IDS[gate],
                realm=realm,
                schema=SCHEMA if gate == "dev" else f"{SCHEMA}_{gate}",
            )
            for gate, realm in basics.QUALITY_GATES.items()
        }
        self.agents = {agent.agent_id: agent for agent in self.gates.values()}
        for agent in self.gates.values():
            agent.configuration.update(
                values={
                    "botName": agent.state["bot"]["displayName"],
                    "region": "retained",
                    "optional": None,
                },
                flows={"workflow": "retained"},
                connections={"connector": {"connectionId": "retained"}},
            )
        self.host = TARGET["host"]
        self.api_version = TARGET["api_version"]
        self.headers = {"Accept": "application/json"}
        self.session = SimpleNamespace(request=self.request)
        self.configuration_requests = []
        self.realms = {
            "routeRealm": 0,
            "siblingRealms": [
                {"botId": QUALITY_IDS[gate], "realm": realm}
                for gate, realm in basics.QUALITY_GATES.items()
            ],
        }

    def get_realms(self, agent_id):
        assert agent_id == AGENT_ID
        return copy.deepcopy(self.realms)

    def get_agent(self, agent_id):
        return self.agents[agent_id].get_agent(agent_id)

    def get_dev_configuration(self, agent_id):
        return self.agents[agent_id].get_dev_configuration(agent_id)

    def get_realm_configuration(self, agent_id, realm):
        assert self.agents[agent_id].card["realm"] == realm
        agent = self.agents[agent_id]
        configuration = copy.deepcopy(agent.configuration)
        if (
            isinstance(configuration.get("values"), dict)
            and agent.state["bot"]["displayName"]
            == agent.state["botComponentChanges"][0]["component"]["displayName"]
        ):
            # Read-config strips the now-redundant independent name binding.
            configuration["values"].pop("gptDisplayName", None)
        return configuration

    def fetch_components(self, agent_id):
        return self.agents[agent_id].fetch_components(agent_id)

    def update_bot_entity(self, agent_id, bot):
        assert agent_id == AGENT_ID, "Promoted realms cannot use the metadata PUT."
        return self.agents[agent_id].update_bot_entity(agent_id, bot)

    def request(self, method, url, **kwargs):
        if method == "PUT":
            return self.gates["dev"].update_components(method, url, **kwargs)
        return self.configure(method, url, **kwargs)

    def configure(self, method, url, **kwargs):
        self.configuration_requests.append((method, url, copy.deepcopy(kwargs)))
        assert method == "POST"
        assert kwargs["allow_redirects"] is False
        assert kwargs["params"] == {"api-version": self.api_version}
        assert kwargs["timeout"] == basics.SAVE_TIMEOUT_SECONDS
        body = kwargs["json"]
        assert set(body) == {"realm", "values"}
        gate = body["realm"].casefold()
        assert gate in {"test", "prod"}
        agent = self.gates[gate]
        assert url == f"{self.host}/copilotstudio/minimalBots/alm/{agent.agent_id}/configure"
        bot = copy.deepcopy(agent.state["bot"])
        bot["displayName"] = body["values"]["botName"]
        component = copy.deepcopy(agent.state["botComponentChanges"][0]["component"])
        component["displayName"] = body["values"].get("gptDisplayName", body["values"]["botName"])
        if agent.apply and agent.status == 200:
            agent.configuration["values"] = copy.deepcopy(body["values"])
        return agent._update(agent.agent_id, bot, component)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def logos(tmp_path):
    color = tmp_path / "color.png"
    color.write_bytes(png(192, color="red"))
    return {"logo": str(color)}


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
    ],
    ids=["not-png", "dimensions", "bmp", "truncated"],
)
def test_color_png_content_validation(data):
    with pytest.raises(basics.AgentBasicsError):
        basics._png(data, size=192)


def test_valid_png_over_one_mib_is_saved_without_conversion(client, tmp_path):
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Description", "x" * (1024 * 1024))
    stream = io.BytesIO()
    Image.new("RGBA", (192, 192), "red").save(
        stream, format="PNG", pnginfo=metadata
    )
    data = stream.getvalue()
    assert len(data) > 1024 * 1024
    source = tmp_path / "large.png"
    source.write_bytes(data)

    plan = basics.prepare(client, TARGET, logo=str(source))
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )

    assert result["status"] == "saved"
    assert client.writes[0]["iconBase64"] == encoded(data)
    assert not basics.prepare(client, TARGET, logo=str(source))["changes"]


def test_animated_png_is_saved_without_conversion(client, tmp_path):
    data = animated_png()
    source = tmp_path / "animated.png"
    source.write_bytes(data)
    plan = basics.prepare(client, TARGET, logo=str(source))

    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )

    assert result["status"] == "saved"
    assert client.writes[0]["iconBase64"] == encoded(data)
    assert not basics.prepare(client, TARGET, logo=str(source))["changes"]


@pytest.mark.parametrize(
    "change",
    [{"second_color": "green"}, {"duration": 200}, {"loop": 1}],
    ids=["later-frame", "timing", "loop"],
)
def test_animation_changes_are_compared_and_verified(client, tmp_path, change):
    original = encoded(animated_png())
    client.state["bot"]["iconBase64"] = original
    source = tmp_path / "animated.png"
    source.write_bytes(animated_png(**change))
    plan = basics.prepare(client, TARGET, logo=str(source))
    assert list(plan["changes"]) == ["logo"]

    def discard_animation_change(state):
        state["bot"]["iconBase64"] = original

    client.mutate = discard_animation_change
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )

    assert result["properties"]["logo"] == "unverified"
    assert result["writesDisabled"] is True


def test_corrupt_later_png_frame_is_rejected():
    data = animated_png()
    offset = data.index(b"fdAT")
    length = int.from_bytes(data[offset - 4:offset], "big")
    payload = data[offset + 4:offset + 8] + b"invalid compressed frame"
    chunk = b"fdAT" + payload
    corrupted = (
        data[:offset - 4]
        + len(payload).to_bytes(4, "big")
        + chunk
        + zlib.crc32(chunk).to_bytes(4, "big")
        + data[offset + length + 8:]
    )
    with pytest.raises(basics.AgentBasicsError, match="fully decoded"):
        basics._png(corrupted, size=192)


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
    assert plan["state"] == before
    expected_components = copy.deepcopy(before["botComponentChanges"])
    if "name" in kwargs:
        expected_components[0]["component"]["displayName"] = kwargs["name"]
    assert client.state["botComponentChanges"] == expected_components
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


@pytest.mark.parametrize(
    "field", ["instructions", "components", "accent_color", "application_metadata"]
)
@pytest.mark.parametrize("operation", ["name", "logo"])
def test_unrequested_mutation_is_not_reported_complete(
    client, logos, field, tmp_path, operation
):
    def mutate(state):
        if field == "instructions":
            state["bot"]["configuration"]["instructions"] = "Unexpected"
        elif field == "components":
            state["botComponentChanges"] = []
        elif field == "accent_color":
            state["bot"]["teamsAppInformation"]["teams"]["accentColor"] = "#00ff00"
        else:
            state["bot"]["teamsAppInformation"]["other"] = "Unexpected"

    client.mutate = mutate
    proposal = {"name": "New Name"} if operation == "name" else logos
    plan = basics.prepare(client, TARGET, **proposal)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    missing_chat = operation == "name" and field == "components"
    assert result["properties"][operation] == ("unverified" if missing_chat else "saved")
    assert result["preservation"] == "unverified"
    assert result["status"] == ("unverified" if missing_chat else "unfinished")
    assert result["writesDisabled"] is True
    assert basics._writes_disabled(tmp_path)


@pytest.mark.parametrize(
    "state",
    [
        "small_color",
        "missing_outline",
        "missing_color",
        "invalid_color",
        "invalid_outline",
        "no_teams",
        "malformed_teams",
    ],
)
def test_name_only_does_not_inspect_or_request_images(
    client, state, tmp_path, monkeypatch
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
    elif state == "invalid_outline":
        bot["teamsAppInformation"]["teams"]["outlineIcon"] = "invalid"
    elif state == "no_teams":
        bot["teamsAppInformation"] = None
    else:
        bot["teamsAppInformation"]["teams"] = "malformed"

    def unexpected_logo_read(*args):
        pytest.fail("A rename must not inspect images")

    monkeypatch.setattr(basics, "_logo", unexpected_logo_read)
    before = copy.deepcopy(client.state)
    plan = basics.prepare(client, TARGET, name="People Support")
    review = basics.review_output(plan, tmp_path)
    assert review["status"] == "review"
    assert review["changedProperties"] == ["name"]
    assert review["current"] == {"name": "Employee Support"}
    assert review["proposed"] == {"name": "People Support", "logoSources": {}}
    assert "serviceIconProcessingRisk" not in review
    assert "serviceIconProcessingWarning" not in review
    assert review["proposed"]["logoSources"] == {}
    assert not (tmp_path / basics.PREVIEW_DIRECTORY).exists()
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert result["properties"] == {"name": "saved"}
    expected = copy.deepcopy(before["bot"])
    expected["displayName"] = "People Support"
    assert client.writes == [expected]
    assert not basics._writes_disabled(tmp_path)
    assert not basics.prepare(client, TARGET, name="People Support")["changes"]


@pytest.mark.parametrize("application", ["existing", None, {"teams": None}])
@pytest.mark.parametrize("normalizes", [False, True])
def test_rename_sends_existing_logo_and_ignores_service_image_normalization(
    client, tmp_path, normalizes, application
):
    client.state["bot"]["iconBase64"] = encoded(png(128))
    if application != "existing":
        client.state["bot"]["teamsAppInformation"] = application
    before = copy.deepcopy(client.state)

    def normalize(state):
        state["bot"]["iconBase64"] = encoded(png(192))
        application = state["bot"].setdefault("teamsAppInformation", {})
        if application is None:
            application = state["bot"]["teamsAppInformation"] = {}
        teams = application.get("teams")
        if teams is None:
            teams = application["teams"] = {}
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
    )
    assert len(client.writes) == 1
    written = copy.deepcopy(client.writes[0])
    assert written.pop("displayName") == "ESS HR Nov-3"
    expected = copy.deepcopy(before["bot"])
    expected.pop("displayName")
    assert written == expected
    assert result["properties"] == {"name": "saved"}
    assert client.state["bot"]["displayName"] == "ESS HR Nov-3"
    assert result["status"] == "saved"
    assert result["preservation"] == "confirmed"
    assert "logoPreservation" not in result
    assert "changedLogoFields" not in result
    assert result["writesDisabled"] is False
    assert not basics._writes_disabled(tmp_path)
    assert client.state["bot"]["configuration"] == before["bot"]["configuration"]
    expected_components = copy.deepcopy(before["botComponentChanges"])
    expected_components[0]["component"]["displayName"] = "ESS HR Nov-3"
    assert client.state["botComponentChanges"] == expected_components


def test_rename_with_missing_outline_still_requires_name_approval(client, tmp_path):
    client.state["bot"]["teamsAppInformation"]["teams"]["outlineIcon"] = ""
    plan = basics.prepare(client, TARGET, name="ESS HR Nov-3")
    result = basics.save(
        client,
        plan,
        "not approved",
        current_target=TARGET,
        root=tmp_path,
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


@pytest.mark.parametrize("outline", ["", None, "invalid", "missing"])
def test_source_logo_upload_does_not_require_a_stored_outline(
    client, logos, tmp_path, outline
):
    teams = client.state["bot"]["teamsAppInformation"]["teams"]
    if outline == "missing":
        del teams["outlineIcon"]
    else:
        teams["outlineIcon"] = outline
    before = copy.deepcopy(client.state["bot"])
    plan = basics.prepare(client, TARGET, **logos)
    review = basics.review_output(plan, tmp_path)
    assert review["current"]["logo"] == "confirmed"
    assert Path(review["current"]["colorPreview"]).read_bytes() == png(192)
    assert set(plan["sources"]) == {"color"}
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert result["properties"] == {"logo": "saved"}
    assert client.state["bot"]["displayName"] == before["displayName"]
    assert client.writes[0]["teamsAppInformation"] == before["teamsAppInformation"]
    assert client.writes[0]["iconBase64"] == encoded(Path(logos["logo"]).read_bytes())


@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize(
    "application",
    [None, {"teams": None}, {"teams": {"outlineIcon": "", "colorIcon": "legacy"}}],
)
def test_logo_readback_accepts_reencoding_and_platform_derived_fields(
    client, logos, tmp_path, combined, application
):
    client.state["bot"]["teamsAppInformation"] = copy.deepcopy(application)
    before = copy.deepcopy(client.state)
    source = Path(logos["logo"]).read_bytes()

    def normalize(state):
        stream = io.BytesIO()
        with Image.open(io.BytesIO(source)) as image:
            image.save(stream, format="PNG", compress_level=0)
        state["bot"]["iconBase64"] = encoded(stream.getvalue())
        application = state["bot"].get("teamsAppInformation")
        if application is None:
            application = state["bot"]["teamsAppInformation"] = {}
        teams = application.get("teams")
        if teams is None:
            teams = application["teams"] = {}
        teams.update(outlineIcon="", colorIcon="")

    client.mutate = normalize
    kwargs = {**logos, **({"name": "People Support"} if combined else {})}
    plan = basics.prepare(client, TARGET, **kwargs)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    expected = copy.deepcopy(before["bot"])
    expected["iconBase64"] = encoded(source)
    if combined:
        expected["displayName"] = "People Support"
    assert client.writes == [expected]
    assert client.state["bot"]["iconBase64"] != encoded(source)
    assert result["status"] == "saved"
    assert result["properties"] == (
        {"name": "saved", "logo": "saved"} if combined else {"logo": "saved"}
    )
    assert result["preservation"] == "confirmed"
    assert result["writesDisabled"] is False
    assert not basics._writes_disabled(tmp_path)
    assert client.state["bot"]["configuration"] == before["bot"]["configuration"]
    expected_components = copy.deepcopy(before["botComponentChanges"])
    if combined:
        expected_components[0]["component"]["displayName"] = "People Support"
    assert client.state["botComponentChanges"] == expected_components


def test_logo_only_does_not_confirm_unrequested_name_change(client, logos, tmp_path):
    client.mutate = lambda state: state["bot"].update(displayName="Unexpected rename")
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["properties"] == {"logo": "saved"}
    assert result["preservation"] == "unverified"
    assert result["status"] == "unfinished"
    assert result["writesDisabled"] is True


@pytest.mark.parametrize(
    "observed",
    [None, "invalid", encoded(png(191, color="red")), encoded(png(192, color="green"))],
    ids=["absent", "unreadable", "wrong-dimensions", "wrong-pixels"],
)
def test_logo_readback_does_not_confirm_a_mismatched_source(
    client, logos, tmp_path, observed
):
    client.mutate = lambda state: state["bot"].update(iconBase64=observed)
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["properties"] == {"logo": "unverified"}
    assert result["status"] == "unfinished"
    assert result["writesDisabled"] is True
    assert len(client.writes) == 1


def test_identical_source_pixels_are_a_noop_despite_png_encoding(
    client, logos, tmp_path
):
    with Image.open(io.BytesIO(png(192))) as image:
        image.save(logos["logo"], format="PNG", compress_level=0)
    assert (
        encoded(Path(logos["logo"]).read_bytes()) != client.state["bot"]["iconBase64"]
    )
    plan = basics.prepare(client, TARGET, **logos)
    assert not plan["changes"]
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "no_change"
    assert result["writeAttempted"] is False
    assert not client.writes


def test_confirmed_absent_source_can_receive_first_logo(client, logos, tmp_path):
    client.state["bot"]["iconBase64"] = None
    plan = basics.prepare(client, TARGET, **logos)
    review = basics.review_output(plan, tmp_path)
    assert review["current"]["logo"] == "none"
    assert "colorPreview" not in review["current"]
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert result["properties"] == {"logo": "saved"}


@pytest.mark.parametrize("source", ["missing", "invalid_base64", "invalid_png"])
def test_unreadable_source_blocks_logo_edit_but_not_rename(
    client, logos, tmp_path, source
):
    if source == "missing":
        del client.state["bot"]["iconBase64"]
    else:
        client.state["bot"]["iconBase64"] = (
            "invalid" if source == "invalid_base64" else encoded(b"not an image")
        )
    with pytest.raises(basics.AgentBasicsError):
        basics.prepare(client, TARGET, **logos)
    assert not client.writes
    name_plan = basics.prepare(client, TARGET, name="New Name")
    assert name_plan["currentLogo"] is None
    assert name_plan["logoError"] is None
    result = basics.save(
        client, name_plan, name_plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"


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
def test_source_logo_preserves_nullable_application_state(
    client, logos, application, tmp_path
):
    client.state["bot"]["teamsAppInformation"] = application
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert client.writes[0]["teamsAppInformation"] == application


def test_malformed_postsave_application_keeps_property_results(client, logos, tmp_path):
    client.mutate = lambda state: state["bot"].update(teamsAppInformation="malformed")
    plan = basics.prepare(client, TARGET, name="New Name", **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["properties"] == {"name": "saved", "logo": "saved"}
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
                "steps": {
                    step: {"state": "done"}
                    for step in (
                        "SETUP-01",
                        "SETUP-02.1",
                        "SETUP-02.2",
                        "SETUP-03",
                        "SETUP-04",
                        "SETUP-05",
                        "SETUP-06",
                        "SETUP-07",
                    )
                },
                "connect_ready": True,
            }
        },
    }
    (tmp_path / ".local" / "setup").mkdir(parents=True)
    (tmp_path / ".local" / "config.json").write_text(json.dumps(config))
    (tmp_path / ".local" / "setup" / "config.json").write_text(json.dumps(state))
    return tmp_path


def test_canonical_target_after_completed_setup(workspace):
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


def test_configured_account_disagreement_blocks_before_signin(workspace):
    path = workspace / ".local" / "config.json"
    config = json.loads(path.read_text())
    config["account"] = "other@example.test"
    path.write_text(json.dumps(config))
    path = workspace / ".local" / "setup" / "config.json"
    state = json.loads(path.read_text())
    state["environment"]["account"] = "maker@example.test"
    path.write_text(json.dumps(state))

    with pytest.raises(basics.AgentBasicsError, match="different Microsoft accounts"):
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


@pytest.mark.parametrize("quality_gate", ["dev", "test", "prod"])
def test_cli_name_changes_are_independent_per_quality_gate(
    cli, monkeypatch, capsys, quality_gate
):
    family = QualityClient()
    before = {gate: copy.deepcopy(agent.state) for gate, agent in family.gates.items()}
    monkeypatch.setattr(basics, "AgentBuilderClient", lambda *args, **kwargs: family)
    options = ["--name", f"Support {quality_gate}", "--quality-gate", quality_gate]

    assert basics.main(["preview", *options]) == 0
    preview = result_json(capsys)
    assert preview["target"]["agent_id"] == QUALITY_IDS[quality_gate]
    assert preview["target"]["qualityGate"] == quality_gate
    assert preview["changedProperties"] == ["name"]
    assert basics.main(["save", *options, "--approval", preview["reviewId"]]) == 0
    assert result_json(capsys)["status"] == "saved"

    for gate, agent in family.gates.items():
        expected = before[gate]
        if gate == quality_gate:
            expected["bot"]["displayName"] = f"Support {quality_gate}"
            expected["botComponentChanges"][0]["component"]["displayName"] = f"Support {quality_gate}"
            expected["bot"]["version"] += 1
        assert agent.state == expected
        assert len(agent.writes) == (1 if gate == quality_gate else 0)
    if quality_gate == "dev":
        assert family.configuration_requests == []
    else:
        assert len(family.configuration_requests) == 1
        assert family.configuration_requests[0][2]["json"]["values"] == {
            "botName": f"Support {quality_gate}",
            "region": "retained",
            "optional": None,
        }


def test_each_quality_gate_keeps_its_own_name(tmp_path):
    family = QualityClient()
    names = {"dev": "Support Development", "test": "Support Validation", "prod": "Support"}
    for gate, name in names.items():
        plan = basics.prepare(family, TARGET, name=name, quality_gate=gate)
        result = basics.save(
            family, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
        )
        assert result["status"] == "saved"
    assert {
        gate: agent.state["bot"]["displayName"] for gate, agent in family.gates.items()
    } == names


@pytest.mark.parametrize("quality_gate", ["dev", "test", "prod"])
def test_rename_repairs_chat_when_agent_name_already_matches(tmp_path, quality_gate):
    family = QualityClient()
    agent = family.gates[quality_gate]
    name = "People Support"
    agent.state["bot"]["displayName"] = name
    agent.configuration["values"].update(
        botName=name, gptDisplayName="Employee Support"
    )
    before = copy.deepcopy(agent.state)
    plan = basics.prepare(family, TARGET, name=name, quality_gate=quality_gate)
    assert plan["changes"] == {"name": name}
    review = basics.review_output(plan, tmp_path)
    assert review["current"] == {"name": name}
    assert review["proposed"] == {"name": name, "logoSources": {}}
    assert "GPT" not in review["concurrencyProtection"]
    assert not any(other.writes for other in family.gates.values())
    result = basics.save(
        family, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    expected = copy.deepcopy(before["botComponentChanges"][0]["component"])
    expected["displayName"] = name
    assert agent.state["botComponentChanges"][0]["component"] == expected
    assert agent.state["bot"]["displayName"] == name
    assert agent.state["bot"]["iconBase64"] == before["bot"]["iconBase64"]
    assert not basics._writes_disabled(tmp_path)
    if quality_gate == "dev":
        payload = agent.component_writes[0]
        assert payload["changeToken"] == before["changeToken"]
        assert payload["bot"]["version"] == before["bot"]["version"]
        assert payload["botComponentChanges"] == [
            {"$kind": "BotComponentUpdate", "component": expected}
        ]
    else:
        values = family.configuration_requests[0][2]["json"]["values"]
        assert values["botName"] == values["gptDisplayName"] == name
        assert "gptDisplayName" not in family.get_realm_configuration(
            agent.agent_id, basics.QUALITY_GATES[quality_gate]
        )["values"]
    assert not basics.prepare(
        family, TARGET, name=name, quality_gate=quality_gate
    )["changes"]
    assert all(
        not other.writes for gate, other in family.gates.items() if gate != quality_gate
    )


def test_rename_keeps_already_correct_chat_name_without_component_write(client, tmp_path):
    client.state["botComponentChanges"][0]["component"]["displayName"] = "People Support"
    client.state.pop("changeToken")
    plan = basics.prepare(client, TARGET, name="People Support")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert not client.component_writes


@pytest.mark.parametrize(
    "fault", ["missing", "ambiguous", "name", "id", "schema"]
)
def test_rename_requires_verified_chat_component(client, fault):
    component = client.state["botComponentChanges"][0]["component"]
    if fault == "missing":
        client.state["botComponentChanges"] = []
    elif fault == "ambiguous":
        client.state["botComponentChanges"].append(
            copy.deepcopy(client.state["botComponentChanges"][0])
        )
    elif fault == "name":
        component["displayName"] = None
    elif fault == "id":
        component["id"] = "not-a-guid"
    else:
        component["schemaName"] = ""
    with pytest.raises((basics.AgentBasicsError, ExistingDASetupError)):
        basics.prepare(client, TARGET, name="People Support")
    assert not client.writes


@pytest.mark.parametrize("token", [None, "", " ", {}, True])
def test_chat_rename_requires_component_concurrency_token(client, token):
    client.state["changeToken"] = token
    with pytest.raises(basics.AgentBasicsError, match="component change token"):
        basics.prepare(client, TARGET, name="People Support")
    assert not client.writes


def test_chat_component_write_conflict_requires_new_review(client, tmp_path):
    plan = basics.prepare(client, TARGET, name="People Support")
    client.state["changeToken"] = "concurrently-edited-components"
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "review_again"
    assert len(client.component_writes) == 1
    assert client.state["bot"]["displayName"] == "Employee Support"
    assert not basics._writes_disabled(tmp_path)


@pytest.mark.parametrize("binding", [None, "Unrelated chat"])
def test_promoted_rename_blocks_missing_or_inconsistent_chat_binding(tmp_path, binding):
    family = QualityClient()
    agent = family.gates["test"]
    agent.state["botComponentChanges"][0]["component"]["displayName"] = "Stale chat"
    if binding is not None:
        agent.configuration["values"]["gptDisplayName"] = binding
    with pytest.raises(basics.AgentBasicsError, match="ALM name binding disagree"):
        basics.prepare(family, TARGET, name="People Support", quality_gate="test")
    assert not agent.writes
    assert not family.configuration_requests


@pytest.mark.parametrize("unchanged", ["agent", "chat"])
def test_rename_cannot_report_saved_when_only_one_name_matches(client, tmp_path, unchanged):
    old_name = client.state["bot"]["displayName"]

    def partial(state):
        target = (
            state["bot"] if unchanged == "agent"
            else state["botComponentChanges"][0]["component"]
        )
        target["displayName"] = old_name

    client.mutate = partial
    plan = basics.prepare(client, TARGET, name="People Support")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["properties"]["name"] == "unverified"
    assert result["status"] == "unfinished"
    assert result["writesDisabled"] is True


@pytest.mark.parametrize("field", ["instructions", "description", "schemaName", "id"])
def test_chat_rename_preserves_every_unrequested_gpt_field(client, tmp_path, field):
    def mutate(state):
        component = state["botComponentChanges"][0]["component"]
        if field == "instructions":
            component["metadata"]["instructions"] = "Unexpected instructions"
        elif field == "id":
            component["id"] = "00000000-0000-4000-8000-000000007777"
        else:
            component[field] = "Unexpected value"

    client.mutate = mutate
    plan = basics.prepare(client, TARGET, name="People Support")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["properties"]["name"] == "saved"
    assert result["preservation"] == "unverified"
    assert result["status"] == "unfinished"
    assert result["writesDisabled"] is True


def test_chat_rename_accepts_server_owned_gpt_revision_fields(client, tmp_path):
    client.state["botComponentChanges"][0]["component"]["version"] = 2
    client.mutate = lambda state: state["botComponentChanges"][0]["component"].update(
        version=3, auditInfo={"modified": "server"}
    )
    plan = basics.prepare(client, TARGET, name="People Support")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert result["preservation"] == "confirmed"


@pytest.mark.parametrize("quality_gate", ["dev", "test", "prod"])
@pytest.mark.parametrize("mutation", ["none", "description", "id", "added", "removed"])
def test_configure_component_revisions_do_not_hide_content_changes(
    tmp_path, quality_gate, mutation
):
    family = QualityClient()
    agent = family.gates[quality_gate]
    agent.state["botComponentChanges"][0]["component"]["version"] = 2
    agent.state["botComponentChanges"].append({
        "$kind": "BotComponentUpdate",
        "component": {
            "$kind": "DialogComponent",
            "id": "00000000-0000-4000-8000-000000008888",
            "schemaName": f"{SCHEMA}.RetainedTopic",
            "displayName": "Retained topic",
            "description": "Retained topic content",
            "version": 4,
            "auditInfo": {"modified": "before"},
        },
    })

    def materialize(state):
        # Configure emits updates for every component, not only the name.
        for change in state["botComponentChanges"]:
            component = change["component"]
            component["version"] += 1
            component["auditInfo"] = {"modified": "server"}
        other = state["botComponentChanges"][1]["component"]
        if mutation == "description":
            other["description"] = "Unexpected content"
        elif mutation == "id":
            other["id"] = "00000000-0000-4000-8000-000000009999"
        elif mutation == "added":
            added = copy.deepcopy(state["botComponentChanges"][1])
            added["component"]["id"] = "00000000-0000-4000-8000-000000009999"
            added["component"]["schemaName"] = f"{SCHEMA}.UnexpectedTopic"
            state["botComponentChanges"].append(added)
        elif mutation == "removed":
            state["botComponentChanges"].pop()

    agent.mutate = materialize
    plan = basics.prepare(family, TARGET, name="People Support", quality_gate=quality_gate)
    result = basics.save(
        family, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    preserved = quality_gate != "dev" and mutation == "none"
    assert result["properties"]["name"] == "saved"
    assert result["preservation"] == ("confirmed" if preserved else "unverified")
    assert result["status"] == ("saved" if preserved else "unfinished")
    assert result["writesDisabled"] is not preserved
    assert basics._writes_disabled(tmp_path) is not preserved


def test_logo_only_never_changes_or_requires_a_readable_chat_name(client, logos, tmp_path):
    client.state["botComponentChanges"][0]["component"]["displayName"] = None
    before = copy.deepcopy(client.state["botComponentChanges"])
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert client.state["botComponentChanges"] == before
    assert not client.component_writes


@pytest.mark.parametrize("quality_gate", ["test", "prod"])
def test_promoted_view_is_read_only(cli, monkeypatch, capsys, quality_gate):
    family = QualityClient()
    monkeypatch.setattr(basics, "AgentBuilderClient", lambda *args, **kwargs: family)
    assert basics.main(["view", "--quality-gate", quality_gate]) == 0
    result = result_json(capsys)
    assert result["target"]["agent_id"] == QUALITY_IDS[quality_gate]
    assert not family.configuration_requests
    assert not any(agent.writes for agent in family.gates.values())


@pytest.mark.parametrize("quality_gate", ["test", "prod"])
def test_unenrolled_source_cannot_guess_promoted_target(client, quality_gate):
    client.card.pop("realm")
    with pytest.raises(basics.AgentBasicsError, match="ALM-enrolled Dev source"):
        basics.prepare(client, TARGET, name="Support", quality_gate=quality_gate)
    assert not client.writes


@pytest.mark.parametrize("quality_gate", ["test", "prod"])
@pytest.mark.parametrize("combined", [False, True], ids=["logo-only", "name-and-logo"])
def test_non_dev_logo_requests_are_blocked_before_signin(
    cli, monkeypatch, logos, capsys, quality_gate, combined
):
    family = QualityClient()

    def unexpected_signin(*args, **kwargs):
        pytest.fail("A prohibited logo request must not authenticate.")

    monkeypatch.setattr(basics, "authenticate", unexpected_signin)
    options = ["--logo", logos["logo"], "--quality-gate", quality_gate]
    if combined:
        options += ["--name", "Gate Support"]
    with pytest.raises(SystemExit) as exc:
        basics.main(["preview", *options])
    assert exc.value.code == 2
    assert "Logo changes are Dev-only" in capsys.readouterr().err
    with pytest.raises(basics.AgentBasicsError, match="Logo changes are Dev-only"):
        basics.prepare(
            family,
            TARGET,
            logo=logos["logo"],
            name="Gate Support" if combined else None,
            quality_gate=quality_gate,
        )
    assert not any(agent.writes for agent in family.gates.values())


@pytest.mark.parametrize(
    "fault",
    ["missing", "ambiguous", "card-realm", "config-realm", "agent-id", "family", "schema"],
)
def test_promoted_name_target_requires_verified_quality_identity(fault):
    family = QualityClient()
    promoted = family.gates["test"]
    if fault == "missing":
        family.realms["siblingRealms"] = []
    elif fault == "ambiguous":
        family.realms["siblingRealms"].append(
            {"botId": QUALITY_IDS["test"], "realm": 1}
        )
    elif fault == "card-realm":
        promoted.card["realm"] = 2
    elif fault == "config-realm":
        promoted.configuration["realm"] = 2
    elif fault == "agent-id":
        promoted.configuration["cdsBotId"] = QUALITY_IDS["prod"]
    elif fault == "family":
        promoted.configuration["grsRepositoryId"] = "another-family"
    else:
        promoted.configuration["schemaName"] = "unrelated-agent"

    with pytest.raises((basics.AgentBasicsError, ExistingDASetupError)):
        basics.prepare(family, TARGET, name="Test Support", quality_gate="test")
    assert not any(agent.writes for agent in family.gates.values())


@pytest.mark.parametrize("change", ["quality-gate", "alm-family"])
def test_name_approval_cannot_cross_quality_gate_or_family(tmp_path, change):
    family = QualityClient()
    reviewed = basics.prepare(
        family, TARGET, name="Gate Support", quality_gate="test"
    )
    quality_gate = "test"
    if change == "quality-gate":
        quality_gate = "prod"
    else:
        for agent in family.gates.values():
            agent.configuration["grsRepositoryId"] = "another-family"
    current = basics.prepare(
        family, TARGET, name="Gate Support", quality_gate=quality_gate
    )
    result = basics.save(
        family, current, reviewed["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "review_again"
    assert not any(agent.writes for agent in family.gates.values())


def test_name_save_rechecks_quality_target_after_writing(tmp_path):
    family = QualityClient()
    plan = basics.prepare(
        family, TARGET, name="Test Support", quality_gate="test"
    )

    def move_family(state):
        for agent in family.gates.values():
            agent.configuration["grsRepositoryId"] = "another-family"

    family.gates["test"].mutate = move_family
    result = basics.save(
        family, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "unverified"
    assert result["writesDisabled"] is True
    assert len(family.gates["test"].writes) == 1
    assert not family.gates["dev"].writes
    assert not family.gates["prod"].writes


def test_name_only_plan_cannot_be_used_to_write_non_dev_logo(tmp_path, logos):
    family = QualityClient()
    plan = basics.prepare(
        family, TARGET, name="Test Support", quality_gate="test"
    )
    plan["changes"]["logo"] = encoded(Path(logos["logo"]).read_bytes())
    with pytest.raises(basics.AgentBasicsError, match="Logo changes are Dev-only"):
        basics.save(
            family, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
        )
    assert not any(agent.writes for agent in family.gates.values())


@pytest.mark.parametrize(
    "values",
    [None, [], {"botName": 5}, {"other": "name"}, {"botName": "Inconsistent name"}],
)
def test_promoted_name_requires_readable_config_bindings(values):
    family = QualityClient()
    family.gates["test"].configuration["values"] = values
    with pytest.raises(basics.AgentBasicsError):
        basics.prepare(family, TARGET, name="Test Support", quality_gate="test")
    assert not family.configuration_requests


def test_promoted_name_refreshes_config_before_writing(tmp_path):
    family = QualityClient()
    plan = basics.prepare(family, TARGET, name="Test Support", quality_gate="test")
    family.gates["test"].configuration["values"]["region"] = "concurrent edit"
    result = basics.save(
        family, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "review_again"
    assert result["writeAttempted"] is False
    assert not family.configuration_requests
    assert not basics._writes_disabled(tmp_path)


def test_promoted_name_config_readback_must_preserve_other_bindings(tmp_path):
    family = QualityClient()
    plan = basics.prepare(family, TARGET, name="Test Support", quality_gate="test")
    family.gates["test"].mutate = lambda state: family.gates["test"].configuration[
        "values"
    ].update(region="unexpected change")
    result = basics.save(
        family, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["properties"]["name"] == "saved"
    assert result["preservation"] == "unverified"
    assert result["writesDisabled"] is True
    assert len(family.configuration_requests) == 1


@pytest.mark.parametrize("status", [403, 409, 500])
def test_promoted_name_surfaces_config_denials_and_conflicts(tmp_path, status):
    family = QualityClient()
    family.gates["test"].status = status
    plan = basics.prepare(family, TARGET, name="Test Support", quality_gate="test")
    result = basics.save(
        family, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["httpStatus"] == status
    assert result["requestId"] == "save-request"
    assert result["status"] == ("review_again" if status == 409 else "unfinished")
    assert len(family.configuration_requests) == 1
    assert not family.gates["dev"].writes
    assert not family.gates["prod"].writes


@pytest.mark.parametrize(
    ("options", "expected_account", "force_selection"),
    [
        ([], "maker@example.test", False),
        (["--account", "other@example.test"], "other@example.test", False),
        (["--select-account"], None, True),
    ],
)
def test_preview_and_save_reuse_setup_account_unless_explicitly_switched(
    cli, monkeypatch, capsys, options, expected_account, force_selection
):
    path = cli / ".local" / "setup" / "config.json"
    state = json.loads(path.read_text())
    state["environment"]["account"] = "maker@example.test"
    path.write_text(json.dumps(state))
    observed = []

    def authenticate(*args, **kwargs):
        observed.append(kwargs)
        return "fake-token"

    monkeypatch.setattr(basics, "authenticate", authenticate)
    assert basics.main(["preview", "--name", "People Support", *options]) == 0
    review_id = result_json(capsys)["reviewId"]
    assert basics.main(
        ["save", "--name", "People Support", "--approval", review_id, *options]
    ) == 0
    assert result_json(capsys)["status"] == "saved"
    assert observed == [
        {
            "account_hint": expected_account,
            "force_account_selection": force_selection,
            "require_account_identity": bool(expected_account),
        }
    ] * 2


def _stalled_command(argv):
    time.sleep(30)


def test_preview_deadline_stops_the_worker(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(basics, "_command_worker", _stalled_command)
    monkeypatch.setattr(basics, "READ_TIMEOUT_SECONDS", 0.2)
    children_before = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()

    assert basics.run_cli(["preview", "--name", "People Support"]) == 2

    result = result_json(capsys)
    assert result["status"] == "blocked"
    assert result["errorType"] == "Timeout"
    assert result["writeAttempted"] is False
    assert "No save was attempted" in result["message"]
    assert time.monotonic() - started < 10
    assert {child.pid for child in multiprocessing.active_children()} == children_before
    assert not (tmp_path / basics.WRITE_PENDING_FILE).exists()


@pytest.mark.parametrize("cancelled", [False, True], ids=["timeout", "cancel"])
def test_interrupted_save_stops_worker_and_retains_recovery(
    monkeypatch, tmp_path, capsys, cancelled
):
    monkeypatch.chdir(tmp_path)
    basics.disable_writes(tmp_path, pending=True)
    elapsed = [0]
    monkeypatch.setattr(basics.time, "monotonic", lambda: elapsed[0])

    class Process:
        running = False
        terminated = False
        closed = False
        exitcode = None

        def start(self):
            self.running = True

        def is_alive(self):
            return self.running

        def join(self, timeout=None):
            if self.running:
                elapsed[0] += timeout
                if cancelled:
                    raise KeyboardInterrupt

        def terminate(self):
            self.terminated = True
            self.running = False

        def close(self):
            self.closed = True

    process = Process()
    monkeypatch.setattr(
        basics.multiprocessing,
        "get_context",
        lambda mode: SimpleNamespace(Process=lambda **kwargs: process),
    )
    assert basics.run_cli(["save", "--name", "People Support", "--logo", "logo.png"]) == 2

    result = result_json(capsys)
    assert process.terminated and process.closed
    assert result["status"] == "unverified"
    assert result["errorType"] == ("Cancelled" if cancelled else "Timeout")
    assert result["properties"] == {"name": "unverified", "logo": "unverified"}
    assert result["preservation"] == "unverified"
    assert result["writesDisabled"] is True
    assert "actual saved state" in result["message"]
    assert (tmp_path / basics.WRITE_PENDING_FILE).is_file()
    if not cancelled:
        assert elapsed[0] == basics.SAVE_TIMEOUT_SECONDS


def test_cli_reports_authentication_stage_before_waiting(cli, monkeypatch, capsys):
    def stalled_authentication(*args, **kwargs):
        progress = capsys.readouterr().err
        assert '"stage": "authenticating"' in progress
        assert "Complete sign-in" in progress
        raise requests.Timeout("private service response")

    monkeypatch.setattr(basics, "authenticate", stalled_authentication)
    assert basics.main(["preview", "--name", "People Support"]) == 2
    result = result_json(capsys)
    assert result["status"] == "blocked"
    assert "private service response" not in result["message"]


@pytest.mark.parametrize(
    ("action", "readiness"),
    [("view", False), ("preview", None), ("preview", "true"), ("save", False)],
)
def test_cli_blocks_incomplete_setup_before_service_access(
    cli, client, capsys, monkeypatch, action, readiness
):
    command = [action]
    if action != "view":
        command.extend(["--name", "People Support"])
    if action == "save":
        assert basics.main(["preview", "--name", "People Support"]) == 0
        command.extend(["--approval", result_json(capsys)["reviewId"]])

    path = cli / ".local" / "setup" / "config.json"
    state = json.loads(path.read_text())
    selected = state["agents"][AGENT_ID]
    other = copy.deepcopy(selected)
    other["agent"].update(id=TARGET["tenant_id"], workspace_slug="other")
    state["agents"][TARGET["tenant_id"]] = other
    selected["steps"]["SETUP-06"]["state"] = "pending"
    if readiness is None:
        selected.pop("connect_ready")
    else:
        selected["connect_ready"] = readiness
    path.write_text(json.dumps(state))
    config_path = cli / ".local" / "config.json"
    config = json.loads(config_path.read_text())
    config["setup"] = "complete"
    config_path.write_text(json.dumps(config))

    def unexpected_auth(*args, **kwargs):
        pytest.fail("Incomplete setup must stop before authentication.")

    monkeypatch.setattr(basics, "authenticate", unexpected_auth)
    assert basics.main(command) == 2
    result = result_json(capsys)
    assert result["status"] == "blocked"
    assert "Complete /setup" in result["message"]
    assert not client.writes


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


def test_cli_rename_saves_without_image_consent_or_new_logo(cli, client, capsys):
    client.state["bot"]["teamsAppInformation"]["teams"]["outlineIcon"] = ""
    before = copy.deepcopy(client.state["bot"])
    assert basics.main(["preview", "--name", "ESS HR Nov-3"]) == 0
    preview = result_json(capsys)
    assert preview["current"] == {"name": "Employee Support"}
    assert preview["proposed"] == {"name": "ESS HR Nov-3", "logoSources": {}}
    assert "serviceIconProcessingWarning" not in preview
    assert not client.writes
    command = ["save", "--name", "ESS HR Nov-3", "--approval", preview["reviewId"]]
    assert basics.main(command) == 0
    saved = result_json(capsys)
    assert saved["properties"] == {"name": "saved"}
    assert saved["status"] == "saved"
    assert "logoPreservation" not in saved
    assert len(client.writes) == 1
    assert client.writes[0]["iconBase64"] == before["iconBase64"]
    assert client.writes[0]["teamsAppInformation"] == before["teamsAppInformation"]


def test_cli_entity_revision_change_still_requires_fresh_rename_approval(
    cli, client, capsys
):
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
            ]
        )
        == 2
    )
    assert result_json(capsys)["status"] == "review_again"
    assert not client.writes


@pytest.mark.parametrize("operation", ["logo", "both"])
def test_cli_source_logo_save_without_outline_or_image_consent(
    cli, client, logos, capsys, operation
):
    teams = client.state["bot"]["teamsAppInformation"]["teams"]
    teams["outlineIcon"] = ""
    client.mutate = lambda state: state["bot"]["teamsAppInformation"]["teams"].update(
        outlineIcon="", colorIcon=""
    )
    source = Path(logos["logo"]).read_bytes()
    proposal = ["--logo", logos["logo"]]
    if operation == "both":
        proposal += ["--name", "People Support"]
    assert basics.main(["preview", *proposal]) == 0
    review = result_json(capsys)
    assert set(review["proposed"]["logoSources"]) == {"color"}
    assert Path(review["current"]["colorPreview"]).read_bytes() == png(192)
    assert not client.writes
    assert basics.main(["save", *proposal, "--approval", review["reviewId"]]) == 0
    saved = result_json(capsys)
    assert saved["status"] == "saved"
    assert saved["properties"]["logo"] == "saved"
    assert saved["writesDisabled"] is False
    assert saved["publication"] == "Not performed for this change."
    assert len(client.writes) == 1
    assert Path(logos["logo"]).read_bytes() == source
    assert not Path(review["current"]["colorPreview"]).exists()


@pytest.mark.parametrize(
    "proposal", [[], ["--name", "People Support"], ["--logo", "color.png"]]
)
def test_cli_unsupported_outline_blocks_entire_request_before_service_access(
    cli, client, capsys, monkeypatch, proposal
):
    def unexpected_auth(*args, **kwargs):
        pytest.fail("Unsupported outline requests must stop before service access")

    monkeypatch.setattr(basics, "authenticate", unexpected_auth)
    with pytest.raises(SystemExit) as exc:
        basics.main(["preview", *proposal, "--outline", "outline.png"])
    assert exc.value.code == 2
    assert (
        "Independent outline customization is not supported" in capsys.readouterr().err
    )
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
