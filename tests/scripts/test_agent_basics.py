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
import zipfile
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
    def __init__(self, agent_id=AGENT_ID, *, realm=None, schema=SCHEMA):
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
        self.card = {"botId": agent_id}
        if realm is not None:
            self.card["realm"] = realm
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
        self.session = SimpleNamespace(request=self.request)
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

    def request(self, method, url, **kwargs):
        assert method == "PUT"
        assert url == (
            f"{self.host}/copilotstudio/minimalBots/api/{self.agent_id}/components"
        )
        assert kwargs["params"] == {"api-version": basics.NATIVE_ALM_API_VERSION}
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == basics.SAVE_TIMEOUT_SECONDS
        payload = copy.deepcopy(kwargs["json"])
        self.component_writes.append(payload)
        if payload["changeToken"] != self.state["changeToken"]:
            self.status = 409
        return self._update(
            self.agent_id, payload["bot"], components=payload["botComponentChanges"]
        )

    def _update(self, agent_id, bot, *, components=None):
        assert agent_id == self.agent_id
        self.writes.append(copy.deepcopy(bot))
        if self.apply and self.status == 200:
            # Mirrors CreateBotEntityTransaction's version precondition/increment.
            if bot["version"] != self.state["bot"]["version"]:
                self.status = 409
            else:
                self.state["bot"] = copy.deepcopy(bot)
                self.state["bot"]["version"] += 1
                if components is not None:
                    assert len(components) == 1
                    component = components[0]["component"]
                    assert component["$kind"] == "GptComponent"
                    current = self.state["botComponentChanges"][0]
                    assert current["component"]["id"] == component["id"]
                    current["component"] = copy.deepcopy(component)
                    self.state["changeToken"] = "next-component-token"
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
        assert url == (
            f"{self.host}/copilotstudio/minimalBots/api/{AGENT_ID}/components"
        ), "Only native Dev authoring is permitted, never promoted Configure writes."
        return self.gates["dev"].request(method, url, **kwargs)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def logos(tmp_path):
    color = tmp_path / "color.png"
    color.write_bytes(png(192, color="red"))
    return {"logo": str(color)}


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("", "Supply a nonblank"),
        (" ", "Supply a nonblank"),
        ("\ud800", "must be valid Unicode"),
        ("a" * 31, "must not exceed 30 characters"),
        ("a" * 100, "must not exceed 30 characters"),
        ("a" * 101, "must not exceed 30 characters"),
        ("\U0001f600" * 31, "must not exceed 30 characters"),
        (" " + "a" * 29 + " ", "must not exceed 30 characters"),
    ],
)
def test_unusable_name_inputs_are_rejected(value, reason):
    with pytest.raises(basics.AgentBasicsError, match=reason):
        basics.validate_name(value)


@pytest.mark.parametrize(
    "value",
    [
        "a" * 29,
        "a" * 30,
        "People & Support",
        "\U0001f600" * 30,
        "\u754c" * 30,
        "Support\u200dDesk",
        " padded ",
        "Dev",
        "Test",
        "Prod",
        "dev1",
    ],
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
def test_manifest_color_png_content_validation(data):
    with pytest.raises(basics.AgentBasicsError):
        basics._png(data, size=192)


@pytest.mark.parametrize(
    ("data", "observed"),
    [(png(64), "64x64"), (png(192, format="BMP"), "BMP")],
    ids=["wrong-dimensions", "wrong-format"],
)
def test_invalid_manifest_icon_explains_the_observed_problem(data, observed):
    with pytest.raises(basics.AgentBasicsError) as error:
        basics._png(data, size=192)

    assert observed in str(error.value)
    assert "192x192" in str(error.value) or "Supply a PNG" in str(error.value)


@pytest.mark.parametrize(
    ("size", "visible_bounds"),
    [
        ((32, 32), (0, 0, 192, 192)),
        ((256, 128), (0, 48, 192, 144)),
        ((128, 256), (48, 0, 144, 192)),
    ],
)
def test_logo_review_previews_share_a_canvas_without_distorting_source(
    tmp_path, client, size, visible_bounds
):
    source = tmp_path / "source.png"
    stream = io.BytesIO()
    Image.new("RGBA", size, "red").save(stream, format="PNG")
    data = stream.getvalue()
    source.write_bytes(data)

    plan = basics.prepare(client, TARGET, logo=str(source))
    review = basics.review_output(plan, tmp_path)
    proposed = (
        tmp_path / basics.PREVIEW_DIRECTORY / f"{review['reviewId']}-proposed-color.png"
    )
    with Image.open(review["current"]["colorPreview"]) as current:
        with Image.open(proposed) as preview:
            assert current.size == preview.size == (192, 192)
            assert preview.getchannel("A").getbbox() == visible_bounds
    details = review["proposed"]["logoDetails"]
    assert (details["width"], details["height"]) == size
    assert plan["desired"]["logo"] == encoded(data)
    assert source.read_bytes() == data
    assert not client.writes


@pytest.mark.parametrize(
    ("format", "size"),
    [
        ("PNG", (32, 32)),
        ("PNG", (198, 198)),
        ("PNG", (256, 128)),
        ("JPEG", (256, 128)),
        ("BMP", (64, 64)),
        ("GIF", (192, 192)),
        ("TIFF", (128, 256)),
        ("WEBP", (256, 256)),
    ],
)
@pytest.mark.parametrize("combined", [False, True])
def test_cli_e2e_authoring_defers_logo_dimensions_and_formats_to_service(
    cli, client, capsys, format, size, combined
):
    """The fake service echoes source bytes; this is not format certification."""
    stream = io.BytesIO()
    Image.new("RGB" if format == "JPEG" else "RGBA", size, "red").save(
        stream, format=format
    )
    source = stream.getvalue()
    path = cli / "logo with misleading extension.bin"
    path.write_bytes(source)
    proposal = ["--logo", str(path)]
    name = " Employee Support " + "\U0001f600" * 12
    if combined:
        proposal += ["--name", name]
    assert basics.main(["preview", *proposal]) == 0
    review = result_json(capsys)
    assert review["status"] == "review"
    details = review["proposed"]["logoDetails"]
    assert (details["width"], details["height"]) == size
    assert details["format"] == format
    assert "Proposed agent logo" in review["proposed"]["logoPreviewMarkdown"]
    assert not client.writes
    assert basics.main(["save", *proposal, "--approval", review["reviewId"]]) == 0
    saved = result_json(capsys)
    assert saved["status"] == "saved"
    assert client.writes[0]["iconBase64"] == encoded(source)
    if combined:
        assert saved["comparison"]["name"]["current"] == name
        assert client.writes[0]["displayName"] == name
    image = saved["comparison"]["logo"]["current"]
    with Image.open(image["preview"]) as preview:
        assert preview.format == "PNG"
        assert preview.size == (192, 192)
    assert path.read_bytes() == source
    assert basics.main(["cleanup", "--approval", saved["reviewId"]]) == 0
    assert result_json(capsys)["status"] == "cleaned"
    assert not Path(image["preview"]).exists()
    assert path.read_bytes() == source


@pytest.mark.parametrize("property", ["name", "logo"])
def test_cli_e2e_server_transformation_is_not_an_exact_match_or_automatic_retry(
    cli, client, logos, capsys, property
):
    if property == "logo":
        Path(logos["logo"]).write_bytes(png(198, color="red"))
        proposal = ["--logo", logos["logo"], "--name", "People Support"]
        client.mutate = lambda state: state["bot"].update(
            iconBase64=encoded(png(192, color="red"))
        )
    else:
        proposal = ["--name", "x" * 30]

        def shorten(state):
            state["bot"]["displayName"] = "x" * 29
            state["botComponentChanges"][0]["component"]["displayName"] = "x" * 29

        client.mutate = shorten
    assert basics.main(["preview", *proposal]) == 0
    review = result_json(capsys)
    assert basics.main(["save", *proposal, "--approval", review["reviewId"]]) == 2
    saved = result_json(capsys)
    assert saved["properties"][property] == "unverified"
    assert saved["writesDisabled"] is True
    assert property not in saved["comparison"]
    if property == "logo":
        assert saved["properties"]["name"] == "saved"
        image = saved["observedLogo"]
        assert Path(image["preview"]).read_bytes() == png(192, color="red")
        assert image["sourceComparison"] == "different"
        assert "does not mean the upload failed" in image["verification"]
        assert "not confirmed" in image["verification"]
        assert saved["completionPreviewRetained"] is True
    else:
        assert saved["observedName"]["value"] == "x" * 29
    assert basics.main(["save", *proposal, "--approval", review["reviewId"]]) == 2
    assert result_json(capsys)["writesDisabled"] is True
    assert len(client.writes) == 1


def test_matching_logo_with_unconfirmed_revision_is_not_presented_as_different(
    client, logos, tmp_path
):
    original_revision = client.state["bot"]["version"]
    client.mutate = lambda state: state["bot"].update(version=original_revision)
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["httpStatus"] == 200
    assert result["properties"] == {"logo": "unverified"}
    image = result["observedLogo"]
    assert image["sourceComparison"] == "matching"
    assert "matches the approved source" in image["verification"]
    assert "differs" not in image["verification"]
    assert "logo" not in result["comparison"]
    assert result["writesDisabled"] is True
    assert len(client.writes) == 1


@pytest.mark.parametrize("status", [200, 422])
def test_logo_comparison_does_not_replace_request_outcome(
    client, logos, tmp_path, status
):
    client.status = status
    client.mutate = lambda state: state["bot"].update(
        iconBase64=encoded(png(191, color="green"))
    )
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["httpStatus"] == status
    assert result["properties"] == {"logo": "unverified"}
    assert result["observedLogo"]["sourceComparison"] == "different"
    assert "not confirmed" in result["observedLogo"]["verification"]
    assert "logo" not in result["comparison"]
    assert result["writesDisabled"] is True
    assert len(client.writes) == 1


@pytest.mark.parametrize(
    "ring, origin",
    [
        ("prod", "https://copilotstudio.microsoft.com"),
        ("preprod", "https://copilotstudio.preprod.microsoft.com"),
        ("test", "https://copilotstudio.test.microsoft.com"),
    ],
)
def test_agent_studio_link_uses_verified_selected_environment_agent_and_ring(
    client, tmp_path, ring, origin
):
    plan = basics.prepare(client, {**TARGET, "ring": ring})
    expected = (
        f"{origin}/environments/{TARGET['environment_id']}/bots/{AGENT_ID}/overview"
    )
    assert plan["agentStudioUrl"] == expected
    assert basics.review_output(plan, tmp_path)["agentStudioUrl"] == expected


def test_agent_studio_link_does_not_guess_an_unknown_ring(client):
    with pytest.raises(basics.AgentBasicsError, match="verified Copilot Studio link"):
        basics.prepare(client, {**TARGET, "ring": "unknown"})
    assert not client.writes


def _save_processed_logo(cli, client, logos, capsys, *, combined=False):
    Path(logos["logo"]).write_bytes(png(198, color="red"))
    client.mutate = lambda state: state["bot"].update(
        iconBase64=encoded(png(192, color="red"))
    )
    arguments = ["--logo", logos["logo"]]
    if combined:
        arguments += ["--name", "People Support"]
    assert basics.main(["preview", *arguments]) == 0
    preview = result_json(capsys)
    assert basics.main(["save", *arguments, "--approval", preview["reviewId"]]) == 2
    saved = result_json(capsys)
    assert saved["logoConfirmation"]["status"] == "available"
    return saved


@pytest.mark.parametrize("decision", ["yes", "no"])
@pytest.mark.parametrize("combined", [False, True])
def test_cli_previous_logo_gets_one_confirmation_without_resume_or_repeat_upload(
    cli, client, logos, capsys, decision, combined
):
    _save_processed_logo(cli, client, logos, capsys, combined=combined)
    evidence = (cli / basics.WRITE_PENDING_FILE).read_text(encoding="utf-8")
    assert "Preserve exact instructions" not in evidence
    assert "Employee Support" not in evidence
    assert encoded(png(192, color="red")) not in evidence
    assert basics.main(["view"]) == 0
    view = result_json(capsys)
    confirmation = view["logoConfirmation"]
    assert confirmation["status"] == "confirmation_required"
    assert confirmation["requestedProperties"] == (
        ["name", "logo"] if combined else ["logo"]
    )
    setting = "name and logo" if combined else "logo"
    dialog = confirmation["dialog"]
    assert dialog["question"] == f"Did the {setting} update as intended?"
    assert dialog["description"] == (
        f"Open your DEV agent in Microsoft Copilot Studio and check the {setting}.\n"
        + view["agentStudioUrl"]
    )
    assert view["agentStudioUrl"].endswith(
        f"/environments/{TARGET['environment_id']}/bots/{AGENT_ID}/overview"
    )
    assert confirmation["reviewId"] != view["reviewId"]
    if not combined:
        assert "name" not in dialog["question"]
        assert "name" not in dialog["description"]
    assert (
        basics.main(
            [
                "confirm-logo",
                "--decision",
                decision,
                "--approval",
                confirmation["reviewId"],
            ]
        )
        == 0
    )
    resolved = result_json(capsys)
    assert resolved["status"] == (
        "logo_confirmed" if decision == "yes" else "logo_not_confirmed"
    )
    assert resolved["properties"] == {
        "logo": "confirmed_by_user" if decision == "yes" else "not_confirmed"
    }
    assert resolved["verificationMethod"] == "user_studio_confirmation"
    assert resolved["agentStudioUrl"] == view["agentStudioUrl"]
    assert resolved["writesDisabled"] is False
    assert resolved["writeAttempted"] is False
    assert len(client.writes) == 1
    assert client.state["bot"]["iconBase64"] == encoded(png(192, color="red"))
    if combined:
        assert client.state["bot"]["displayName"] == "People Support"
    assert basics.main(["view"]) == 0
    assert "logoConfirmation" not in result_json(capsys)

    client.mutate = None
    Path(logos["logo"]).write_bytes(png(192, color="green"))
    assert basics.main(["preview", "--logo", logos["logo"]]) == 0
    replacement = result_json(capsys)
    assert len(client.writes) == 1
    assert (
        basics.main(
            ["save", "--logo", logos["logo"], "--approval", replacement["reviewId"]]
        )
        == 0
    )
    assert result_json(capsys)["properties"] == {"logo": "saved"}
    assert len(client.writes) == 2
    assert client.writes[-1]["iconBase64"] == encoded(png(192, color="green"))


def test_cli_later_exact_logo_match_resolves_pause_without_user_confirmation(
    cli, client, logos, capsys
):
    _save_processed_logo(cli, client, logos, capsys)
    client.state["bot"].update(
        iconBase64=encoded(png(198, color="red")),
        version=client.state["bot"]["version"] + 1,
    )
    assert basics.main(["view"]) == 0
    result = result_json(capsys)
    assert result["logoConfirmation"]["status"] == "logo_verified"
    assert result["logoConfirmation"]["properties"] == {"logo": "saved"}
    assert result["logoConfirmation"]["verificationMethod"] == "api_exact_match"
    assert "dialog" not in result["logoConfirmation"]
    assert result["logoConfirmation"]["writeAttempted"] is False
    assert result["writesDisabled"] is False
    assert len(client.writes) == 1
    assert basics.main(["view"]) == 0
    assert "logoConfirmation" not in result_json(capsys)


def test_cli_verified_logo_save_never_offers_another_confirmation(
    cli, client, logos, capsys
):
    assert basics.main(["preview", "--logo", logos["logo"]]) == 0
    preview = result_json(capsys)
    assert (
        basics.main(
            ["save", "--logo", logos["logo"], "--approval", preview["reviewId"]]
        )
        == 0
    )
    saved = result_json(capsys)
    assert saved["status"] == "saved"
    assert "logoConfirmation" not in saved
    assert basics.main(["view"]) == 0
    assert "logoConfirmation" not in result_json(capsys)


def test_cli_previous_logo_answer_is_invalidated_by_a_changed_review(
    cli, client, logos, capsys
):
    _save_processed_logo(cli, client, logos, capsys)
    assert basics.main(["view"]) == 0
    confirmation = result_json(capsys)["logoConfirmation"]
    client.state["bot"].update(
        iconBase64=encoded(png(192, color="green")),
        version=client.state["bot"]["version"] + 1,
    )
    assert (
        basics.main(
            [
                "confirm-logo",
                "--decision",
                "yes",
                "--approval",
                confirmation["reviewId"],
            ]
        )
        == 2
    )
    result = result_json(capsys)
    assert result["status"] == "review_again"
    assert result["writesDisabled"] is True
    assert len(client.writes) == 1
    assert basics.main(["view"]) == 0
    refreshed = result_json(capsys)["logoConfirmation"]
    assert refreshed["status"] == "confirmation_required"
    assert refreshed["reviewId"] != confirmation["reviewId"]


@pytest.mark.parametrize(
    "issue",
    [
        "instructions",
        "selection",
        "unreadable",
        "hard-stop",
        "legacy",
        "malformed",
        "older",
    ],
)
def test_cli_logo_confirmation_cannot_clear_unrelated_or_unproven_pauses(
    cli, client, logos, capsys, monkeypatch, issue
):
    _save_processed_logo(cli, client, logos, capsys)
    assert basics.main(["view"]) == 0
    confirmation = result_json(capsys)["logoConfirmation"]
    if issue == "instructions":
        client.state["bot"]["configuration"]["instructions"] = "Unexpected"
    elif issue == "selection":
        selected = basics.selected_target(cli)
        monkeypatch.setattr(
            basics,
            "selected_target",
            lambda root: {**selected, "workspace_fingerprint": "another selection"},
        )
    elif issue == "unreadable":
        client.state["bot"]["iconBase64"] = "invalid"
    elif issue == "hard-stop":
        basics.disable_writes(cli)
    elif issue == "legacy":
        (cli / basics.WRITE_PENDING_FILE).write_text(
            "Agent Basics writes are stopped.", encoding="utf-8"
        )
    elif issue == "malformed":
        (cli / basics.WRITE_PENDING_FILE).write_text('{"kind":', encoding="utf-8")
    else:
        client.state["bot"]["version"] -= 1
    assert (
        basics.main(
            [
                "confirm-logo",
                "--decision",
                "yes",
                "--approval",
                confirmation["reviewId"],
            ]
        )
        == 2
    )
    result = result_json(capsys)
    assert result["status"] == "blocked"
    assert result["writesDisabled"] is True
    assert basics._writes_disabled(cli)
    assert len(client.writes) == 1


@pytest.mark.parametrize(
    "issue", ["rejection", "transport", "preservation", "revision"]
)
def test_logo_confirmation_is_not_offered_without_safe_completed_save_evidence(
    client, logos, tmp_path, issue
):
    def mutate(state):
        state["bot"]["iconBase64"] = encoded(png(191, color="green"))
        if issue == "preservation":
            state["bot"]["configuration"]["instructions"] = "Unexpected"
        if issue == "revision":
            state["bot"]["version"] -= 1

    client.mutate = mutate
    client.status = 422 if issue == "rejection" else 200
    client.timeout = issue == "transport"
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert "logoConfirmation" not in result
    assert result["writesDisabled"] is True
    assert basics._writes_disabled(tmp_path)
    assert len(client.writes) == 1


def test_confirmation_evidence_failure_keeps_pause_and_reports_reason(
    client, logos, tmp_path, monkeypatch
):
    client.mutate = lambda state: state["bot"].update(
        iconBase64=encoded(png(191, color="green"))
    )

    def unavailable(*args):
        raise PermissionError("locked")

    monkeypatch.setattr(basics, "_record_logo_confirmation", unavailable)
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert "logoConfirmation" not in result
    assert result["confirmationIssue"]
    assert result["writesDisabled"] is True
    assert len(client.writes) == 1


def test_cli_automatic_logo_verification_reports_a_local_release_failure(
    cli, client, logos, capsys, monkeypatch
):
    _save_processed_logo(cli, client, logos, capsys)
    client.state["bot"]["iconBase64"] = encoded(png(198, color="red"))
    unlink = Path.unlink

    def locked(path, *args, **kwargs):
        if path == cli / basics.WRITE_PENDING_FILE:
            raise PermissionError("locked")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    assert basics.main(["view"]) == 2
    result = result_json(capsys)
    assert result["logoConfirmation"]["status"] == "logo_verified"
    assert result["writeStopIssue"]
    assert result["writesDisabled"] is True
    assert len(client.writes) == 1


def test_automatic_logo_verification_cannot_clear_a_changed_workspace_selection(
    cli, client, logos, capsys, monkeypatch
):
    _save_processed_logo(cli, client, logos, capsys)
    client.state["bot"]["iconBase64"] = encoded(png(198, color="red"))
    selected = basics.selected_target(cli)
    selections = 0

    def changes_after_read(root):
        nonlocal selections
        selections += 1
        return (
            selected
            if selections == 1
            else {**selected, "workspace_fingerprint": "changed during view"}
        )

    monkeypatch.setattr(basics, "selected_target", changes_after_read)
    assert basics.main(["view"]) == 0
    result = result_json(capsys)
    assert result["logoConfirmation"]["status"] == "blocked"
    assert result["writesDisabled"] is True
    assert basics._writes_disabled(cli)
    assert len(client.writes) == 1


def test_failed_logo_recheck_does_not_offer_confirmation_of_an_earlier_read(
    client, logos, tmp_path, monkeypatch
):
    client.mutate = lambda state: state["bot"].update(
        iconBase64=encoded(png(191, color="green"))
    )
    plan = basics.prepare(client, TARGET, **logos)
    read_state = basics.read_state
    post_write_reads = 0

    def fails_on_recheck(*args, **kwargs):
        nonlocal post_write_reads
        if client.writes:
            post_write_reads += 1
            if post_write_reads == 2:
                raise AgentBuilderHTTPError("read", 403)
        return read_state(*args, **kwargs)

    monkeypatch.setattr(basics, "read_state", fails_on_recheck)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["readBackIssue"]["httpStatus"] == 403
    assert "observedLogo" in result
    assert "logoConfirmation" not in result
    assert result["writesDisabled"] is True
    assert len(client.writes) == 1


def test_later_logo_verification_does_not_discard_a_requested_replacement(
    cli, client, logos, capsys
):
    _save_processed_logo(cli, client, logos, capsys)
    assert basics.main(["view"]) == 0
    confirmation = result_json(capsys)["logoConfirmation"]
    client.state["bot"]["iconBase64"] = encoded(png(198, color="red"))
    assert (
        basics.main(
            ["confirm-logo", "--decision", "no", "--approval", confirmation["reviewId"]]
        )
        == 0
    )
    result = result_json(capsys)
    assert result["status"] == "logo_verified"
    assert result["replacementRequested"] is True
    assert "Offer a replacement" in result["nextAction"]
    assert result["writesDisabled"] is False
    assert len(client.writes) == 1


def test_logo_confirmation_is_retained_when_redisplaying_fails(
    cli, client, logos, capsys, monkeypatch
):
    _save_processed_logo(cli, client, logos, capsys)
    assert basics.main(["view"]) == 0
    confirmation = result_json(capsys)["logoConfirmation"]

    def unavailable(*args):
        raise PermissionError("preview storage locked")

    monkeypatch.setattr(basics, "review_output", unavailable)
    assert (
        basics.main(
            [
                "confirm-logo",
                "--decision",
                "yes",
                "--approval",
                confirmation["reviewId"],
            ]
        )
        == 0
    )
    result = result_json(capsys)
    assert result["status"] == "logo_confirmed"
    assert result["properties"] == {"logo": "confirmed_by_user"}
    assert result["presentationIssue"]
    assert result["writesDisabled"] is False
    assert result["writeAttempted"] is False
    assert len(client.writes) == 1


def test_name_only_view_discovers_prior_logo_confirmation_without_image_work(
    cli, client, logos, capsys, monkeypatch
):
    _save_processed_logo(cli, client, logos, capsys)

    def no_images(*args, **kwargs):
        raise AssertionError("A name-only read must not inspect previous logo images")

    monkeypatch.setattr(basics, "_image", no_images)
    monkeypatch.setattr(basics, "_preview_image", no_images)
    assert basics.main(["view", "--name-only"]) == 0
    result = result_json(capsys)
    assert result["logoConfirmation"]["status"] == "available"
    assert "logo" not in result["current"]
    assert result["writesDisabled"] is True
    assert len(client.writes) == 1


def test_existing_logo_confirmation_record_gets_a_studio_link_without_guessing_scope(
    cli, client, logos, capsys
):
    _save_processed_logo(cli, client, logos, capsys, combined=True)
    path = cli / basics.WRITE_PENDING_FILE
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("requestedProperties")
    path.write_text(json.dumps(record), encoding="utf-8")
    assert basics.main(["view"]) == 0
    result = result_json(capsys)
    confirmation = result["logoConfirmation"]
    assert confirmation["status"] == "confirmation_required"
    assert confirmation["requestedProperties"] == ["logo"]
    assert confirmation["dialog"]["question"] == "Did the logo update as intended?"
    assert result["agentStudioUrl"] in confirmation["dialog"]["description"]
    assert result["writesDisabled"] is True
    assert len(client.writes) == 1


@pytest.mark.parametrize("length", [31, 100, 101])
@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize("action", ["preview", "save"])
def test_cli_rejects_over_limit_names_before_reading_or_writing(
    cli, client, logos, capsys, monkeypatch, length, combined, action
):
    def unexpected(*args, **kwargs):
        pytest.fail("An over-limit proposal must be rejected before service reads")

    monkeypatch.setattr(basics, "read_state", unexpected)
    proposal = ["--name", "N" * length]
    if combined:
        proposal += ["--logo", logos["logo"]]
    if action == "save":
        proposal += ["--approval", "a" * 64]
    assert basics.main([action, *proposal]) == 2
    result = result_json(capsys)
    assert result["status"] == "blocked"
    assert result["message"] == (
        "Agent name must not exceed 30 characters. "
        f"You entered {length} characters. Enter a shorter name."
    )
    assert result["writesDisabled"] is False
    assert not client.writes
    assert not (cli / basics.WRITE_PENDING_FILE).exists()


def test_existing_over_limit_name_remains_viewable_and_allows_logo_only_edits(
    cli, client, logos, capsys
):
    name = "Existing " + "N" * 31
    client.state["bot"]["displayName"] = name
    client.state["botComponentChanges"][0]["component"]["displayName"] = name
    assert basics.main(["view", "--name-only"]) == 0
    assert result_json(capsys)["current"] == {"name": name}
    assert basics.main(["preview", "--logo", logos["logo"]]) == 0
    review = result_json(capsys)
    assert (
        basics.main(["save", "--logo", logos["logo"], "--approval", review["reviewId"]])
        == 0
    )
    assert result_json(capsys)["properties"] == {"logo": "saved"}
    assert client.state["bot"]["displayName"] == name
    assert client.state["botComponentChanges"][0]["component"]["displayName"] == name


def test_cli_e2e_name_at_limit_preserves_exact_text_without_image_work(
    cli, client, capsys, monkeypatch
):
    name = "  People Support " + "\U0001f600" * 11 + "  "
    client.state["bot"]["iconBase64"] = "unreadable image"

    def no_images(*args, **kwargs):
        raise AssertionError("A rename must not inspect or preview images")

    monkeypatch.setattr(basics, "_image", no_images)
    monkeypatch.setattr(basics, "_preview_image", no_images)
    assert basics.main(["preview", "--name", name]) == 0
    review = result_json(capsys)
    assert basics.main(["save", "--name", name, "--approval", review["reviewId"]]) == 0
    saved = result_json(capsys)
    assert saved["properties"] == {"name": "saved"}
    assert saved["comparison"]["name"]["current"] == name
    assert client.writes[0]["displayName"] == name
    assert "observedLogo" not in saved
    assert not (cli / basics.PREVIEW_DIRECTORY).exists()


@pytest.mark.parametrize("status", [413, 415, 422])
def test_service_validation_error_preserves_reason_without_inner_details(status):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(
        {
            "error": {
                "code": "InvalidImage",
                "message": "The provided image is not supported by this service.",
                "innererror": {"message": "private implementation detail"},
            }
        }
    ).encode()
    assert basics._service_error(response) == {
        "httpStatus": status,
        "code": "InvalidImage",
        "message": "The provided image is not supported by this service.",
    }


@pytest.mark.parametrize("content", [b"<html>Internal server error</html>", b"[]"])
def test_unstructured_service_errors_do_not_expose_raw_bodies(content):
    response = requests.Response()
    response.status_code = 400
    response._content = content
    assert basics._service_error(response) == {"httpStatus": 400}


@pytest.mark.parametrize("operation", ["name", "logo", "both"])
def test_cli_e2e_server_rejection_reports_safe_reason_and_preserves_settings(
    cli, client, logos, capsys, operation, monkeypatch
):
    before = copy.deepcopy(client.state)
    client.status = 400
    client.apply = False
    update = client._update

    def rejected(*args, **kwargs):
        response = update(*args, **kwargs)
        response._content = json.dumps(
            {
                "error": {
                    "code": "InvalidAuthoringValue",
                    "message": (
                        "The supplied value does not meet the service requirement. "
                        "Authorization: Bearer private-token "
                        "See https://service.example/?token=private "
                        "contact@example.com"
                    ),
                    "innererror": {"stack": "MUST NOT BE RETURNED"},
                }
            }
        ).encode()
        return response

    monkeypatch.setattr(client, "_update", rejected)
    proposal = _branding_arguments(operation, logos)
    assert basics.main(["preview", *proposal]) == 0
    review = result_json(capsys)
    assert basics.main(["save", *proposal, "--approval", review["reviewId"]]) == 2
    saved = result_json(capsys)
    assert set(saved["properties"].values()) == {"failed"}
    error = saved["serviceError"]
    assert error["code"] == "InvalidAuthoringValue"
    assert "does not meet the service requirement" in error["message"]
    rendered = json.dumps(error)
    assert "private-token" not in rendered
    assert "https://" not in rendered
    assert "contact@example.com" not in rendered
    assert "MUST NOT BE RETURNED" not in rendered
    assert saved["requestId"] == "save-request"
    assert saved["comparison"] == {}
    assert client.state == before
    assert len(client.writes) == 1


@pytest.mark.parametrize(
    ("icon", "stage", "value"),
    [
        (encoded(png(192)), "current_property_loaded", "confirmed"),
        (None, "current_property_loaded", "none"),
        ("not base64", "current_property_unavailable", None),
    ],
    ids=["loaded", "empty", "unreadable"],
)
def test_current_name_is_available_before_logo_inspection(
    client, monkeypatch, icon, stage, value
):
    client.state["bot"]["iconBase64"] = icon
    events = []
    monkeypatch.setattr(
        basics, "_progress", lambda stage, **details: events.append((stage, details))
    )
    inspect_logo = basics._logo

    def inspect_after_name(bot):
        assert (
            "current_property_loaded",
            {"property": "name", "value": "Employee Support"},
        ) in events
        assert events[-1] == ("reading_current_logo", {})
        return inspect_logo(bot)

    monkeypatch.setattr(basics, "_logo", inspect_after_name)
    basics.prepare(client, TARGET)

    assert events[-1][0] == stage
    assert events[-1][1]["property"] == "logo"
    if value is not None:
        assert events[-1][1]["value"] == value
    else:
        assert "reason" in events[-1][1]
    assert not client.writes


def test_valid_png_over_one_mib_is_saved_without_conversion(client, tmp_path):
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Description", "x" * (1024 * 1024))
    stream = io.BytesIO()
    Image.new("RGBA", (192, 192), "red").save(stream, format="PNG", pnginfo=metadata)
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
    length = int.from_bytes(data[offset - 4 : offset], "big")
    payload = data[offset + 4 : offset + 8] + b"invalid compressed frame"
    chunk = b"fdAT" + payload
    corrupted = (
        data[: offset - 4]
        + len(payload).to_bytes(4, "big")
        + chunk
        + zlib.crc32(chunk).to_bytes(4, "big")
        + data[offset + length + 8 :]
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
    if properties in ("name", "both"):
        expected_components[0]["component"]["displayName"] = kwargs["name"]
        assert len(client.component_writes) == 1
        assert client.component_writes[0]["changeToken"] == before["changeToken"]
    else:
        assert not client.component_writes
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


@pytest.mark.parametrize("component_update", [False, True])
def test_save_point_version_conflict_does_not_retry(client, tmp_path, component_update):
    if not component_update:
        client.state["botComponentChanges"][0]["component"]["displayName"] = "New Name"
    plan = basics.prepare(client, TARGET, name="New Name")
    original_update = client._update

    def race(agent_id, bot, **kwargs):
        client.state["bot"]["version"] += 1
        client.state["bot"]["displayName"] = "Concurrent rename"
        return original_update(agent_id, bot, **kwargs)

    client._update = race
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


@pytest.mark.parametrize("readback", ["unreadable", "changed", "unchanged_pixels"])
def test_rejected_logo_save_requires_readable_unchanged_state_to_prove_failure(
    client, logos, tmp_path, readback
):
    client.status = 403
    before = basics._decode(client.state["bot"]["iconBase64"])
    if readback == "unchanged_pixels":
        stream = io.BytesIO()
        with Image.open(io.BytesIO(before)) as image:
            image.save(stream, format="PNG", compress_level=0)
        value = encoded(stream.getvalue())
        assert value != encoded(before)
    else:
        value = (
            "invalid base64"
            if readback == "unreadable"
            else encoded(png(192, color="green"))
        )
    client.mutate = lambda state: state["bot"].update(iconBase64=value)
    plan = basics.prepare(client, TARGET, **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    proven_failed = readback == "unchanged_pixels"
    assert result["properties"] == {"logo": "failed" if proven_failed else "unverified"}
    assert result["writesDisabled"] is not proven_failed
    assert result["status"] != "saved"
    assert len(client.writes) == 1
    if readback == "unreadable":
        assert "logo" in result["readBackIssue"]["properties"]


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


def test_readback_denial_remains_unverified(client, tmp_path, monkeypatch):
    client.fail_after_write = True
    reads = []
    get_agent = client.get_agent

    def count_readback(agent_id):
        if client.writes:
            reads.append(agent_id)
        return get_agent(agent_id)

    monkeypatch.setattr(client, "get_agent", count_readback)
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
    assert reads == [AGENT_ID, AGENT_ID]
    assert "Establish actual Dev draft state" in result["nextAction"]
    assert "do not block recovery of this authoring operation" in result["nextAction"]


@pytest.mark.parametrize("first_read", ["unavailable", "stale", "partial"])
def test_uncertain_save_rechecks_read_only_before_completing(
    client, logos, tmp_path, monkeypatch, capsys, first_read
):
    before = copy.deepcopy(client.state)
    plan = basics.prepare(client, TARGET, name="New Name", **logos)
    fetch = client.fetch_components
    reads = []

    def readback(agent_id):
        state = fetch(agent_id)
        if client.writes:
            reads.append(agent_id)
            if len(reads) == 1:
                if first_read == "unavailable":
                    raise AgentBuilderHTTPError(
                        "read", 503, request_id="read-back-request"
                    )
                if first_read == "stale":
                    return copy.deepcopy(before)
                state["bot"]["iconBase64"] = before["bot"]["iconBase64"]
        return state

    monkeypatch.setattr(client, "fetch_components", readback)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )

    assert result["status"] == "saved"
    assert result["properties"] == {"name": "saved", "logo": "saved"}
    assert result["preservation"] == "confirmed"
    assert "readBackIssue" not in result
    assert reads == [AGENT_ID, AGENT_ID]
    assert len(client.writes) == len(client.component_writes) == 1
    assert not basics._writes_disabled(tmp_path)
    assert '"stage": "rechecking_saved_changes"' in capsys.readouterr().err


@pytest.mark.parametrize("second_read", ["unavailable", "stale", "changed_name"])
def test_inconclusive_recheck_stops_without_repeating_or_undoing_saves(
    client, logos, tmp_path, monkeypatch, second_read
):
    before = copy.deepcopy(client.state)
    plan = basics.prepare(client, TARGET, name="New Name", **logos)
    fetch = client.fetch_components
    reads = []

    def readback(agent_id):
        state = fetch(agent_id)
        if client.writes:
            reads.append(agent_id)
            if len(reads) == 1:
                state["bot"]["iconBase64"] = before["bot"]["iconBase64"]
            elif second_read == "unavailable":
                raise AgentBuilderHTTPError("read", 403, request_id="recheck-request")
            elif second_read == "stale":
                return copy.deepcopy(before)
            else:
                state["bot"].update(displayName="Concurrent name", version=6)
                state["botComponentChanges"][0]["component"]["displayName"] = (
                    "Concurrent name"
                )
        return state

    monkeypatch.setattr(client, "fetch_components", readback)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )

    assert result["status"] == "unverified"
    assert result["preservation"] == "unverified"
    assert reads == [AGENT_ID, AGENT_ID]
    assert len(client.writes) == len(client.component_writes) == 1
    assert result["writesDisabled"] is True
    assert basics._writes_disabled(tmp_path)
    if second_read == "changed_name":
        assert result["properties"] == {"name": "unverified", "logo": "saved"}
        assert result["readBackIssue"] == {
            "errorType": "StateChangedDuringRecheck",
            "previouslyVerifiedProperties": ["name"],
        }
    else:
        assert result["properties"] == {"name": "saved", "logo": "unverified"}
        if second_read == "unavailable":
            assert result["readBackIssue"]["httpStatus"] == 403
            assert result["readBackIssue"]["requestId"] == "recheck-request"
        else:
            assert "older revision" in result["readBackIssue"]["reason"]


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


@pytest.mark.parametrize("unapplied", ["name", "logo"])
def test_partial_success_retry_omits_confirmed_property(
    client, logos, tmp_path, unapplied
):
    original = copy.deepcopy(client.state)

    def restore_unapplied(state):
        if unapplied == "logo":
            state["bot"]["iconBase64"] = original["bot"]["iconBase64"]
        else:
            state["bot"]["displayName"] = original["bot"]["displayName"]
            state["botComponentChanges"][0]["component"]["displayName"] = original[
                "botComponentChanges"
            ][0]["component"]["displayName"]

    client.mutate = restore_unapplied
    plan = basics.prepare(client, TARGET, name="New Name", **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "unfinished"
    assert result["properties"] == {
        field: "unverified" if field == unapplied else "saved"
        for field in ("name", "logo")
    }
    recheck = basics.prepare(client, TARGET, name="New Name", **logos)
    assert set(recheck["changes"]) == {unapplied}
    assert len(client.writes) == 1


@pytest.mark.parametrize(
    "fault", ["component", "component_id", "chat_name", "bot_name"]
)
def test_unreadable_name_does_not_hide_independently_verified_logo(
    client, logos, tmp_path, fault
):
    def unreadable_name(state):
        if fault == "component":
            state["botComponentChanges"] = []
        elif fault == "component_id":
            state["botComponentChanges"][0]["component"]["id"] = "not-a-guid"
        elif fault == "chat_name":
            state["botComponentChanges"][0]["component"]["displayName"] = None
        else:
            del state["bot"]["displayName"]

    client.mutate = unreadable_name
    plan = basics.prepare(client, TARGET, name="New Name", **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "unverified"
    assert result["properties"] == {"name": "unverified", "logo": "saved"}
    assert "name" in result["readBackIssue"]["properties"]
    assert set(result["comparison"]) == {"logo"}
    assert result["writesDisabled"] is True
    assert len(client.writes) == 1


def test_unreadable_name_on_recheck_retains_earlier_confirmation(
    client, logos, tmp_path, monkeypatch
):
    original_logo = client.state["bot"]["iconBase64"]
    fetch = client.fetch_components
    reads = []

    def readback(agent_id):
        state = fetch(agent_id)
        if client.writes:
            reads.append(agent_id)
            if len(reads) == 1:
                state["bot"]["iconBase64"] = original_logo
            else:
                state["botComponentChanges"][0]["component"]["displayName"] = None
        return state

    monkeypatch.setattr(client, "fetch_components", readback)
    plan = basics.prepare(client, TARGET, name="New Name", **logos)
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "unverified"
    assert result["properties"] == {"name": "saved", "logo": "saved"}
    assert "name" in result["readBackIssue"]["properties"]
    assert result["writesDisabled"] is True
    assert reads == [AGENT_ID, AGENT_ID]
    assert len(client.writes) == 1


@pytest.mark.parametrize(
    "field", ["instructions", "components", "accent_color", "application_metadata"]
)
@pytest.mark.parametrize("operation", ["name", "logo"])
def test_unrequested_mutation_is_not_reported_complete(
    client, logos, field, tmp_path, operation, capsys
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
    unreadable_name = operation == "name" and field == "components"
    assert result["properties"][operation] == (
        "unverified" if unreadable_name else "saved"
    )
    assert result["preservation"] == "unverified"
    assert result["status"] == ("unverified" if unreadable_name else "unfinished")
    assert result["writesDisabled"] is True
    assert basics._writes_disabled(tmp_path)
    assert '"stage": "rechecking_saved_changes"' not in capsys.readouterr().err


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
    assert result["status"] == ("unverified" if observed == "invalid" else "unfinished")
    if observed == "invalid":
        assert "logo" in result["readBackIssue"]["properties"]
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
    client.card.pop("realm", None)
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
    ["card", "fetched_id", "schema", "version", "components"],
)
def test_identity_and_preservation_preconditions(client, mutation):
    if mutation == "card":
        client.card["botId"] = TARGET["tenant_id"]
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


@pytest.mark.parametrize("operation", ["name", "logo", "both"])
def test_unpublished_enrolled_dev_branding_does_not_require_published_config(
    client, logos, tmp_path, monkeypatch, operation
):
    def unpublished(*args):
        raise AgentBuilderHTTPError("Dev realm configuration", 404)

    monkeypatch.setattr(client, "get_dev_configuration", unpublished)
    client.card["realm"] = 0
    proposal = {}
    if operation in ("name", "both"):
        proposal["name"] = "People Support"
    if operation in ("logo", "both"):
        proposal.update(logos)
    plan = basics.prepare(client, TARGET, **proposal)
    assert plan["target"]["qualityGate"] == "dev"
    assert not client.writes
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert result["preservation"] == "confirmed"
    assert not result["writesDisabled"]
    assert len(client.writes) == 1


@pytest.mark.parametrize("quality_gate", ["test", "prod"])
@pytest.mark.parametrize("status", [403, 404])
def test_promoted_view_still_requires_readable_published_dev_config(
    monkeypatch, quality_gate, status
):
    family = QualityClient()

    def unavailable(*args):
        raise AgentBuilderHTTPError("Dev realm configuration", status)

    monkeypatch.setattr(family, "get_dev_configuration", unavailable)
    with pytest.raises(AgentBuilderHTTPError) as exc:
        basics.prepare(family, TARGET, quality_gate=quality_gate)
    assert exc.value.status_code == status
    assert not family.configuration_requests
    assert not any(agent.writes for agent in family.gates.values())


@pytest.mark.parametrize("quality_gate", ["test", "prod"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cdsBotId", TARGET["tenant_id"]),
        ("schemaName", "different"),
        ("grsRepositoryId", ""),
    ],
)
def test_promoted_view_still_validates_dev_configuration_identity(
    quality_gate, field, value
):
    family = QualityClient()
    family.gates["dev"].configuration[field] = value
    with pytest.raises((basics.AgentBasicsError, ExistingDASetupError)):
        basics.prepare(family, TARGET, quality_gate=quality_gate)
    assert not family.configuration_requests
    assert not any(agent.writes for agent in family.gates.values())


def test_previews_and_cleanup_never_change_maker_sources(client, logos, tmp_path):
    original_sources = {key: Path(path).read_bytes() for key, path in logos.items()}
    plan = basics.prepare(client, TARGET, **logos)
    review = basics.review_output(plan, tmp_path)
    assert "retained" not in review
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


def test_name_only_current_read_never_processes_images(
    cli, client, monkeypatch, capsys
):
    client.state["bot"]["iconBase64"] = "unreadable image"
    full_view = basics.prepare(client, TARGET)

    def unexpected(*args, **kwargs):
        pytest.fail("A name-only current-state read must not process images")

    monkeypatch.setattr(basics, "_logo", unexpected)
    monkeypatch.setattr(basics, "_png", unexpected)
    assert basics.main(["view", "--name-only"]) == 0
    result = result_json(capsys)
    assert result["current"] == {"name": "Employee Support"}
    assert result["editableProperties"] == ["name"]
    assert not client.writes
    assert not (cli / basics.PREVIEW_DIRECTORY).exists()
    assert result["reviewId"] != full_view["reviewId"]


@pytest.mark.parametrize(
    "action", ["preview", "save", "validate-package", "resume-writes"]
)
def test_name_only_read_option_cannot_change_write_or_recovery_scope(
    monkeypatch, capsys, action
):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid scope must fail before authentication")

    monkeypatch.setattr(basics, "authenticate", unexpected)
    with pytest.raises(SystemExit) as exc:
        basics.main([action, "--name-only"])
    assert exc.value.code == 2
    assert "--name-only is supported only by view" in capsys.readouterr().err


@pytest.mark.parametrize("quality_gate", ["test", "prod"])
@pytest.mark.parametrize("action", ["preview", "save"])
@pytest.mark.parametrize("operation", ["name", "logo", "both"])
def test_promoted_edits_stop_before_authentication_or_target_reads(
    cli, monkeypatch, capsys, quality_gate, action, operation, logos
):
    def unexpected(*args, **kwargs):
        raise AssertionError(
            "Unsupported edits must stop before authentication or reads"
        )

    monkeypatch.setattr(basics, "authenticate", unexpected)
    options = ["--quality-gate", quality_gate]
    if operation in ("name", "both"):
        options += ["--name", "New Name"]
    if operation in ("logo", "both"):
        options += ["--logo", logos["logo"]]
    with pytest.raises(SystemExit) as exc:
        basics.main([action, *options])
    assert exc.value.code == 2
    assert "names and logos in Dev only" in capsys.readouterr().err
    client = Client()
    monkeypatch.setattr(client, "get_agent", unexpected)
    with pytest.raises(basics.AgentBasicsError, match="target was not switched"):
        basics.prepare(client, TARGET, name="New Name", quality_gate=quality_gate)
    assert not client.writes


@pytest.mark.parametrize("realm", [None, 0])
def test_current_bot_name_still_updates_a_different_chat_name(realm, tmp_path):
    client = Client(realm=realm)
    client.state["botComponentChanges"][0]["component"]["displayName"] = "Distinct GPT"
    before = copy.deepcopy(client.state)
    plan = basics.prepare(client, TARGET, name=before["bot"]["displayName"])
    assert plan["changes"] == {"name": before["bot"]["displayName"]}
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert result["properties"] == {"name": "saved"}
    expected = copy.deepcopy(before["botComponentChanges"])
    expected[0]["component"]["displayName"] = before["bot"]["displayName"]
    assert client.state["botComponentChanges"] == expected
    assert len(client.component_writes) == 1


@pytest.mark.parametrize("operation", ["name", "logo", "both"])
def test_enrolled_native_dev_branding_leaves_test_and_prod_unchanged(
    tmp_path, logos, operation
):
    family = QualityClient()
    before = {
        gate: (copy.deepcopy(agent.state), copy.deepcopy(agent.configuration))
        for gate, agent in family.gates.items()
    }
    proposal = {
        **({"name": "dev1"} if operation in ("name", "both") else {}),
        **(logos if operation in ("logo", "both") else {}),
    }
    plan = basics.prepare(family, TARGET, **proposal)
    result = basics.save(
        family, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert result["releaseHandoff"]["status"] == "not_started"
    for gate in ("test", "prod"):
        agent = family.gates[gate]
        assert (agent.state, agent.configuration) == before[gate]
        assert not agent.writes
        assert not agent.component_writes
    assert len(family.gates["dev"].writes) == 1
    assert len(family.gates["dev"].component_writes) == (
        1 if operation in ("name", "both") else 0
    )
    assert family.gates["dev"].configuration == before["dev"][1]
    assert not basics._writes_disabled(tmp_path)
    assert not family.configuration_requests


@pytest.mark.parametrize(
    ("fault", "editable"),
    [
        ("none", ["name", "logo"]),
        ("empty-name", ["name", "logo"]),
        ("missing-name", ["logo"]),
        ("unreadable-logo", ["name"]),
        ("empty-logo", ["name", "logo"]),
        ("unreadable-both", []),
        ("missing-gpt", ["logo"]),
        ("invalid-gpt-id", ["logo"]),
    ],
)
def test_current_settings_offer_only_independently_editable_properties(
    client, tmp_path, fault, editable
):
    if fault in ("missing-name", "unreadable-both"):
        client.state["bot"].pop("displayName")
    if fault == "empty-name":
        client.state["bot"]["displayName"] = ""
    if fault in ("unreadable-logo", "unreadable-both"):
        client.state["bot"]["iconBase64"] = "invalid image"
    if fault == "empty-logo":
        client.state["bot"]["iconBase64"] = ""
    if fault == "missing-gpt":
        client.state["botComponentChanges"] = []
    if fault == "invalid-gpt-id":
        client.state["botComponentChanges"][0]["component"]["id"] = "invalid"
    plan = basics.prepare(client, TARGET)
    result = basics.review_output(plan, tmp_path)
    assert result["editableProperties"] == editable
    if fault == "empty-name":
        assert result["current"]["name"] == ""
        assert "nameIssue" not in result["current"]
    if fault == "empty-logo":
        assert result["current"]["logo"] == "none"
        assert result["current"]["logoIssue"] is None
    if fault == "unreadable-both":
        assert result["current"]["name"] is None
        assert result["current"]["logo"] == "unavailable"
        assert result["current"]["nameIssue"]
        assert result["current"]["logoIssue"]
        assert "colorPreview" not in result["current"]
        assert result["changedProperties"] == []
    if fault in ("missing-gpt", "invalid-gpt-id"):
        assert result["current"]["name"] == "Employee Support"
        assert "Name editing is unavailable" in result["current"]["nameIssue"]
    basics.cleanup(tmp_path, plan["reviewId"])
    assert not client.writes


def write_app_package(tmp_path, icons, assets, *, manifest=None):
    path = tmp_path / "generated-app.zip"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "manifest.json",
            json.dumps({"icons": icons}) if manifest is None else manifest,
        )
        for name, data in assets.items():
            package.writestr(name, data)
    return path


@pytest.fixture
def package_icons():
    return {"color": "assets/color.png", "outline": "assets/outline.png"}


@pytest.fixture
def package_assets(package_icons):
    return {
        package_icons["color"]: png(192),
        package_icons["outline"]: png(32, outline=True),
    }


@pytest.mark.parametrize("optional", [False, True])
def test_generated_package_validation_is_local_and_scoped(
    tmp_path, monkeypatch, capsys, package_icons, package_assets, optional
):
    if optional:
        package_icons["color32x32"] = "assets/small-color.png"
        package_assets["assets/small-color.png"] = png(32, outline=True)
    path = write_app_package(tmp_path, package_icons, package_assets)
    before = path.read_bytes()
    monkeypatch.chdir(tmp_path)

    def unexpected(*args, **kwargs):
        raise AssertionError("Package validation must not authenticate or read setup")

    monkeypatch.setattr(basics, "authenticate", unexpected)
    monkeypatch.setattr(basics, "selected_target", unexpected)
    assert basics.main(["validate-package", "--package", str(path)]) == 0
    result = result_json(capsys)
    assert result["status"] == "validated"
    assert result["scope"] == "provided_app_package_icons_only"
    assert result["targetAssociation"] == "unverified"
    assert result["employeeVisibility"] == "unverified"
    assert result["icons"] == sorted(package_icons)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "fault",
    [
        "missing-outline",
        "missing-color",
        "extra-icon",
        "missing-asset",
        "color-size",
        "outline-size",
        "not-png",
        "opaque-outline",
        "colored-outline",
        "optional-size",
        "opaque-optional",
        "malformed-manifest",
    ],
)
def test_generated_package_rejects_noncompliant_icons(
    tmp_path, package_icons, package_assets, fault
):
    if fault.startswith("missing-") and fault != "missing-asset":
        package_icons.pop(fault.removeprefix("missing-"))
    elif fault == "extra-icon":
        package_icons["unexpected"] = "assets/color.png"
    elif fault == "missing-asset":
        package_assets.pop(package_icons["outline"])
    elif fault == "color-size":
        package_assets[package_icons["color"]] = png(32)
    elif fault == "outline-size":
        package_assets[package_icons["outline"]] = png(192, outline=True)
    elif fault == "not-png":
        package_assets[package_icons["color"]] = png(192, format="BMP")
    elif fault == "opaque-outline":
        package_assets[package_icons["outline"]] = png(32, color="white")
    elif fault == "colored-outline":
        image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        image.putpixel((16, 16), (0, 0, 255, 255))
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        package_assets[package_icons["outline"]] = stream.getvalue()
    elif fault in ("optional-size", "opaque-optional"):
        package_icons["color32x32"] = "assets/small-color.png"
        package_assets["assets/small-color.png"] = png(
            192 if fault == "optional-size" else 32
        )
    path = write_app_package(
        tmp_path,
        package_icons,
        package_assets,
        manifest="not JSON" if fault == "malformed-manifest" else None,
    )
    with pytest.raises(basics.AgentBasicsError):
        basics.validate_package(path)


@pytest.mark.parametrize(
    "asset_path",
    [
        "",
        "/color.png",
        "../color.png",
        "assets/../color.png",
        "C:\\color.png",
        "https://example.test/color.png",
        "a" * 2049,
    ],
)
def test_generated_package_rejects_nonrelative_or_overlong_icon_paths(
    tmp_path, package_icons, package_assets, asset_path
):
    package_icons["color"] = asset_path
    path = write_app_package(tmp_path, package_icons, package_assets)
    with pytest.raises(basics.AgentBasicsError, match="package-relative path"):
        basics.validate_package(path)


@pytest.mark.parametrize("filename", ["a" * 2037, "\u754c" * 1018])
def test_generated_package_path_limit_counts_characters_not_bytes(
    tmp_path, package_icons, package_assets, filename
):
    asset_path = "assets/" + filename + ".png"
    package_assets[asset_path] = package_assets.pop(package_icons["color"])
    package_icons["color"] = asset_path
    path = write_app_package(tmp_path, package_icons, package_assets)
    assert basics.validate_package(path)["status"] == "validated"


def test_generated_package_missing_manifest_and_duplicate_asset_are_rejected(
    tmp_path, package_icons, package_assets
):
    path = tmp_path / "native-alm.zip"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("app.config.dev.json", "{}")
    with pytest.raises(basics.AgentBasicsError, match="manifest.json"):
        basics.validate_package(path)
    path = write_app_package(tmp_path, package_icons, package_assets)
    with zipfile.ZipFile(path, "a") as package:
        with pytest.warns(UserWarning, match="Duplicate name"):
            package.writestr(package_icons["color"], png(192, color="red"))
    with pytest.raises(basics.AgentBasicsError, match="duplicate file paths"):
        basics.validate_package(path)


def test_rename_keeps_already_correct_chat_name_without_component_write(
    client, tmp_path
):
    client.state["botComponentChanges"][0]["component"]["displayName"] = (
        "People Support"
    )
    client.state.pop("changeToken")
    plan = basics.prepare(client, TARGET, name="People Support")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "saved"
    assert not client.component_writes


@pytest.mark.parametrize("fault", ["missing", "ambiguous", "name", "id", "schema"])
def test_rename_requires_an_identifiable_readable_chat_component(client, fault):
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
    assert not client.component_writes


@pytest.mark.parametrize("token", [None, "", " ", {}, True])
def test_chat_rename_requires_a_real_component_token(client, token):
    client.state["changeToken"] = token
    with pytest.raises(basics.AgentBasicsError, match="component change token"):
        basics.prepare(client, TARGET, name="People Support")
    assert not client.writes
    assert not client.component_writes


def test_chat_component_write_conflict_requires_new_review(client, tmp_path):
    plan = basics.prepare(client, TARGET, name="People Support")
    client.state["changeToken"] = "concurrently-edited-components"
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "review_again"
    assert not client.component_writes
    assert not client.writes
    assert client.state["bot"]["displayName"] == "Employee Support"
    assert not basics._writes_disabled(tmp_path)


def test_component_token_race_after_refresh_requires_new_review(
    client, tmp_path, monkeypatch
):
    request = client.session.request

    def race(*args, **kwargs):
        client.state["changeToken"] = "changed-after-refresh"
        return request(*args, **kwargs)

    monkeypatch.setattr(client.session, "request", race)
    plan = basics.prepare(client, TARGET, name="People Support")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert result["status"] == "review_again"
    assert result["httpStatus"] == 409
    assert len(client.component_writes) == 1
    assert client.state["bot"]["displayName"] == "Employee Support"
    assert not basics._writes_disabled(tmp_path)


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


def test_chat_name_save_accepts_server_owned_gpt_revision_changes(client, tmp_path):
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
    assert result["writesDisabled"] is False


def test_rename_is_unverified_when_the_chat_name_is_not_saved(client, tmp_path):
    client.mutate = lambda state: state["botComponentChanges"][0]["component"].update(
        displayName="Employee Support"
    )
    plan = basics.prepare(client, TARGET, name="People Support")
    result = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert client.state["bot"]["displayName"] == "People Support"
    assert result["status"] == "unfinished"
    assert result["properties"]["name"] == "unverified"
    assert result["preservation"] == "confirmed"
    assert result["writesDisabled"] is True


def test_logo_only_never_changes_or_requires_a_readable_chat_name(
    client, logos, tmp_path
):
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
    assert result["editableProperties"] == []
    assert not family.configuration_requests
    assert not any(agent.writes for agent in family.gates.values())


@pytest.mark.parametrize("quality_gate", ["test", "prod"])
def test_unenrolled_source_cannot_guess_promoted_target(client, quality_gate):
    client.card.pop("realm", None)
    with pytest.raises(basics.AgentBasicsError, match="ALM-enrolled Dev source"):
        basics.prepare(client, TARGET, quality_gate=quality_gate)
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
    assert "names and logos in Dev only" in capsys.readouterr().err
    with pytest.raises(basics.AgentBasicsError, match="names and logos in Dev only"):
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
    [
        "missing",
        "ambiguous",
        "card-realm",
        "config-realm",
        "agent-id",
        "family",
        "schema",
    ],
)
def test_promoted_view_requires_verified_quality_identity(fault):
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
        basics.prepare(family, TARGET, quality_gate="test")
    assert not any(agent.writes for agent in family.gates.values())


@pytest.mark.parametrize("property_name", ["name", "logo"])
def test_read_only_plan_cannot_be_used_to_write_non_dev_properties(
    tmp_path, logos, property_name
):
    family = QualityClient()
    plan = basics.prepare(family, TARGET, quality_gate="test")
    plan["changes"][property_name] = (
        "Test Support"
        if property_name == "name"
        else encoded(Path(logos["logo"]).read_bytes())
    )
    with pytest.raises(basics.AgentBasicsError, match="names and logos in Dev only"):
        basics.save(
            family, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
        )
    assert not any(agent.writes for agent in family.gates.values())


@pytest.mark.parametrize(
    "values",
    [None, [], {"botName": 5}, {"other": "name"}, {"botName": "Inconsistent name"}],
)
def test_promoted_view_requires_readable_config_bindings(values):
    family = QualityClient()
    family.gates["test"].configuration["values"] = values
    with pytest.raises(basics.AgentBasicsError):
        basics.prepare(family, TARGET, quality_gate="test")
    assert not family.configuration_requests


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
    assert (
        basics.main(
            ["save", "--name", "People Support", "--approval", review_id, *options]
        )
        == 0
    )
    assert result_json(capsys)["status"] == "saved"
    assert (
        observed
        == [
            {
                "account_hint": expected_account,
                "force_account_selection": force_selection,
                "require_account_identity": bool(expected_account),
            }
        ]
        * 2
    )


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
    assert (
        basics.run_cli(["save", "--name", "People Support", "--logo", "logo.png"]) == 2
    )

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
    assert saved["completionPreviewRetained"] is True
    assert saved["reviewId"] == review["reviewId"]
    assert set(saved["comparison"]) == (
        {"name", "logo"} if operation == "both" else {"logo"}
    )
    comparison = saved["comparison"]["logo"]
    for column, expected in (("previous", png(192)), ("current", source)):
        image = comparison[column]
        assert Path(image["preview"]).read_bytes() == expected
        assert image["previewUri"] == Path(image["preview"]).as_uri()
        assert image["previewUri"] in image["previewMarkdown"]
    basics.cleanup(cli, saved["reviewId"])
    assert not Path(review["current"]["colorPreview"]).exists()
    assert all(not Path(value["preview"]).exists() for value in comparison.values())


def test_saved_name_comparison_does_not_inspect_or_copy_logo(client, tmp_path):
    client.state["bot"]["iconBase64"] = "unreadable-platform-logo"
    previous = client.state["bot"]["displayName"]
    plan = basics.prepare(client, TARGET, name="People Support")
    saved = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert saved["status"] == "saved"
    assert saved["comparison"] == {
        "name": {"previous": previous, "current": "People Support"}
    }
    assert "completionPreviewRetained" not in saved
    assert not (tmp_path / basics.PREVIEW_DIRECTORY).exists()


def test_saved_logo_display_failure_preserves_service_result(
    client, logos, tmp_path, monkeypatch
):
    plan = basics.prepare(client, TARGET, logo=logos["logo"])

    def unavailable_preview(*args):
        raise OSError("Preview directory is not writable")

    monkeypatch.setattr(basics, "_saved_comparison", unavailable_preview)
    saved = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert saved["status"] == "saved"
    assert saved["properties"] == {"logo": "saved"}
    assert "Preview directory is not writable" in saved["presentationIssue"]
    assert "completionPreviewRetained" not in saved
    assert len(client.writes) == 1


def test_saved_logo_comparison_labels_absent_previous_logo(client, logos, tmp_path):
    client.state["bot"]["iconBase64"] = None
    plan = basics.prepare(client, TARGET, logo=logos["logo"])
    saved = basics.save(
        client, plan, plan["reviewId"], current_target=TARGET, root=tmp_path
    )
    assert saved["status"] == "saved"
    assert saved["comparison"]["logo"]["previous"] == {"logo": "none"}
    image = saved["comparison"]["logo"]["current"]
    assert Path(image["preview"]).read_bytes() == Path(logos["logo"]).read_bytes()
    basics.cleanup(tmp_path, saved["reviewId"])
    assert not Path(image["preview"]).exists()


@pytest.mark.parametrize(
    "proposal", [[], ["--name", "People Support"], ["--logo", "color.png"]]
)
@pytest.mark.parametrize("kind", ["outline", "color32x32"])
def test_cli_independent_icons_block_entire_request_before_service_access(
    cli, client, capsys, monkeypatch, proposal, kind
):
    def unexpected_auth(*args, **kwargs):
        pytest.fail("Unsupported icon requests must stop before service access")

    monkeypatch.setattr(basics, "authenticate", unexpected_auth)
    with pytest.raises(SystemExit) as exc:
        basics.main(["preview", *proposal, f"--{kind}", "small.png"])
    assert exc.value.code == 2
    assert "publication regenerates color and outline" in capsys.readouterr().err
    assert not client.writes


@pytest.fixture
def manifest_icons(tmp_path):
    color = tmp_path / "manifest-color.png"
    color.write_bytes(png(192, color=(255, 0, 0, 100)))
    outline = tmp_path / "outline.png"
    image = Image.new("RGBA", (32, 32))
    image.putpixel((8, 8), (255, 255, 255, 128))
    image.save(outline)
    return {"color": str(color), "outline": str(outline)}


@pytest.mark.parametrize("operation", ["color", "both"])
def test_cli_color_uses_protected_source_logo_review(
    cli, client, manifest_icons, capsys, operation
):
    proposal = ["--color", manifest_icons["color"]]
    if operation == "both":
        proposal += ["--name", "People Support"]
    assert basics.main(["preview", *proposal]) == 0
    review = result_json(capsys)
    expected = {"logo": "saved"}
    if operation == "both":
        expected["name"] = "saved"
    assert set(review["changedProperties"]) == set(expected)
    assert set(review["proposed"]["logoSources"]) == {"color"}
    assert not client.writes
    assert basics.main(["save", *proposal, "--approval", review["reviewId"]]) == 0
    result = result_json(capsys)
    assert result["properties"] == expected
    assert len(client.writes) == 1
    assert client.state["bot"]["iconBase64"] == encoded(
        Path(manifest_icons["color"]).read_bytes()
    )


@pytest.mark.parametrize("kind", ["outline", "color32x32"])
def test_prepare_refuses_independent_icons_before_reading_service(client, kind):
    client.fail_reads = True
    with pytest.raises(basics.AgentBasicsError, match="requires platform support"):
        basics.prepare(client, TARGET, **{kind: "icon.png"})
    assert not client.writes


@pytest.mark.parametrize("quality_gate", ["test", "prod"])
def test_color_alias_is_dev_only_before_authentication(
    cli, client, monkeypatch, quality_gate
):
    def unexpected(*args, **kwargs):
        pytest.fail("Test/Prod color edits must stop before authentication")

    monkeypatch.setattr(basics, "authenticate", unexpected)
    with pytest.raises(SystemExit) as exc:
        basics.main(["preview", "--color", "color.png", "--quality-gate", quality_gate])
    assert exc.value.code == 2
    assert not client.writes


def test_color_and_logo_aliases_cannot_silently_replace_each_other(
    cli, client, logos, monkeypatch
):
    def unexpected(*args, **kwargs):
        pytest.fail("Conflicting aliases must stop before authentication")

    monkeypatch.setattr(basics, "authenticate", unexpected)
    with pytest.raises(SystemExit) as exc:
        basics.main(["preview", "--logo", logos["logo"], "--color", "other.png"])
    assert exc.value.code == 2
    with pytest.raises(basics.AgentBasicsError, match="use only one"):
        basics.prepare(client, TARGET, **logos, color="other.png")
    assert not client.writes


@pytest.mark.parametrize(
    ("kind", "data", "reason"),
    [
        ("color", png(32), "192x192"),
        ("outline", png(192, outline=True), "32x32"),
        ("outline", png(32, color="white"), "transparent background"),
        ("outline", png(32, color=(255, 0, 0, 0)), "white on"),
        ("color32x32", png(32, color="red"), "transparent background"),
        ("color32x32", png(192, outline=True), "32x32"),
    ],
)
def test_local_icon_validation_rejects_format_specific_errors(
    tmp_path, monkeypatch, capsys, kind, data, reason
):
    path = tmp_path / "icon.png"
    path.write_bytes(data)
    monkeypatch.chdir(tmp_path)
    assert basics.main(["validate-icons", f"--{kind}", str(path)]) == 2
    result = result_json(capsys)
    assert result["status"] == "blocked"
    assert reason in result["message"]


def test_all_documented_icon_types_can_be_validated_without_authentication(
    tmp_path, monkeypatch, capsys, manifest_icons
):
    small = tmp_path / "small.png"
    image = Image.new("RGBA", (32, 32))
    image.putpixel((8, 8), (255, 0, 0, 255))
    image.save(small)
    inputs = {**manifest_icons, "color32x32": str(small)}
    original = {kind: Path(path).read_bytes() for kind, path in inputs.items()}
    monkeypatch.chdir(tmp_path)

    def unexpected(*args, **kwargs):
        pytest.fail("Local icon validation must not authenticate or read setup")

    monkeypatch.setattr(basics, "authenticate", unexpected)
    monkeypatch.setattr(basics, "selected_target", unexpected)
    arguments = [arg for kind, path in inputs.items() for arg in (f"--{kind}", path)]
    assert basics.main(["validate-icons", *arguments]) == 0
    result = result_json(capsys)
    assert result["scope"] == "provided_local_icon_files_only"
    assert result["nativeSaveUnsupported"] == ["outline", "color32x32"]
    assert result["writeAttempted"] is False
    assert {kind: Path(path).read_bytes() for kind, path in inputs.items()} == original
    assert not (tmp_path / ".local").exists()


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
    assert "service denied access" in result["message"]
    assert "Recheck access and current values" in result["message"]
    assert "People Support" not in json.dumps(result)
    assert not client.writes


def test_current_name_logo_read_rechecks_after_denial_without_setup_fallback(
    cli, client, capsys
):
    client.fail_reads = True
    assert basics.main(["view"]) == 2
    denied = result_json(capsys)
    assert denied["httpStatus"] == 403
    assert "current" not in denied
    assert "Cached old label" not in json.dumps(denied)
    client.fail_reads = False
    client.state["bot"]["displayName"] = "Fresh live name"
    current_logo = png(192, color="green")
    client.state["bot"]["iconBase64"] = encoded(current_logo)
    assert basics.main(["view"]) == 0
    view = result_json(capsys)
    assert view["current"]["name"] == "Fresh live name"
    assert view["current"]["logo"] == "confirmed"
    assert view["current"]["logoIssue"] is None
    assert Path(view["current"]["colorPreview"]).read_bytes() == current_logo
    assert view["current"]["colorPreviewMarkdown"] == (
        f"![Current agent logo]({view['current']['colorPreviewUri']})"
    )
    assert not client.writes
    assert basics.main(["cleanup", "--approval", view["reviewId"]]) == 0
    result_json(capsys)


def test_logo_preview_returns_inline_file_uri_without_deleting_image(client, tmp_path):
    root = tmp_path / "preview with spaces #"
    plan = basics.prepare(client, TARGET)
    result = basics.review_output(plan, root)
    current = result["current"]
    path = Path(current["colorPreview"])
    assert current["colorPreviewUri"] == path.as_uri()
    assert "%20" in current["colorPreviewUri"]
    assert "%23" in current["colorPreviewUri"]
    assert current["colorPreviewMarkdown"] == (
        f"![Current agent logo]({current['colorPreviewUri']})"
    )
    assert path.read_bytes() == basics._decode(client.state["bot"]["iconBase64"])
    basics.cleanup(root, result["reviewId"])
    assert not path.exists()
    assert not client.writes


def _branding_arguments(operation, logos):
    return (["--name", "dev1"] if operation in ("name", "both") else []) + (
        ["--logo", logos["logo"]] if operation in ("logo", "both") else []
    )


@pytest.mark.parametrize(
    ("fault", "editable"),
    [
        ("none", ["name", "logo"]),
        ("empty-name", ["name", "logo"]),
        ("empty-logo", ["name", "logo"]),
        ("missing-name", ["logo"]),
        ("unreadable-logo", ["name"]),
        ("unreadable-both", []),
    ],
)
def test_cli_e2e_current_states_and_cancel_preserve_service_and_workspace(
    cli, client, capsys, fault, editable
):
    if fault in ("missing-name", "unreadable-both"):
        client.state["bot"].pop("displayName")
    if fault == "empty-name":
        client.state["bot"]["displayName"] = ""
    if fault == "empty-logo":
        client.state["bot"]["iconBase64"] = None
    if fault in ("unreadable-logo", "unreadable-both"):
        client.state["bot"]["iconBase64"] = "unreadable"
    before = copy.deepcopy(client.state)
    assert basics.main(["view"]) == 0
    view = result_json(capsys)
    assert view["editableProperties"] == editable
    assert view["changedProperties"] == []
    if fault == "empty-name":
        assert view["current"]["name"] == ""
    if fault == "empty-logo":
        assert view["current"]["logo"] == "none"
    assert basics.main(["cleanup", "--approval", view["reviewId"]]) == 0
    assert result_json(capsys)["status"] == "cleaned"
    assert client.state == before
    assert not client.writes
    directory = cli / basics.PREVIEW_DIRECTORY
    assert not directory.exists() or not list(directory.iterdir())


@pytest.mark.parametrize("operation", ["name", "logo", "both"])
def test_cli_e2e_cancel_discards_proposal_without_saving(
    cli, client, logos, capsys, operation
):
    before = copy.deepcopy(client.state)
    paths = [
        cli / ".local" / "config.json",
        cli / ".local" / "setup" / "config.json",
        Path(logos["logo"]),
    ]
    local_before = {path: path.read_bytes() for path in paths}
    assert basics.main(["preview", *_branding_arguments(operation, logos)]) == 0
    review = result_json(capsys)
    assert review["status"] == "review"
    assert basics.main(["cleanup", "--approval", review["reviewId"]]) == 0
    assert result_json(capsys)["status"] == "cleaned"
    assert client.state == before
    assert {path: path.read_bytes() for path in paths} == local_before
    assert not client.writes


@pytest.mark.parametrize("fault", ["name", "logo-corrupt", "logo-missing"])
@pytest.mark.parametrize("combined", [False, True])
def test_cli_e2e_invalid_input_never_saves_valid_half(
    cli, client, logos, capsys, fault, combined
):
    if fault == "name":
        proposal = ["--name", "   "]
        if combined:
            proposal += ["--logo", logos["logo"]]
    else:
        if fault == "logo-corrupt":
            Path(logos["logo"]).write_bytes(b"not an image")
        else:
            Path(logos["logo"]).unlink()
        proposal = ["--logo", logos["logo"]]
        if combined:
            proposal += ["--name", "dev1"]
    assert basics.main(["preview", *proposal]) == 2
    result = result_json(capsys)
    assert result["status"] == "blocked"
    assert not client.writes
    assert not basics._writes_disabled(cli)


@pytest.mark.parametrize("operation", ["name", "logo", "both"])
@pytest.mark.parametrize("gate", ["test", "prod"])
def test_cli_e2e_gate_switch_requires_dev_review_and_new_approval(
    cli, monkeypatch, logos, capsys, gate, operation
):
    family = QualityClient()
    monkeypatch.setattr(basics, "AgentBuilderClient", lambda *args, **kwargs: family)
    before = {
        quality: copy.deepcopy(agent.state) for quality, agent in family.gates.items()
    }
    arguments = _branding_arguments(operation, logos)
    assert basics.main(["view", "--quality-gate", gate]) == 0
    gate_view = result_json(capsys)
    assert gate_view["editableProperties"] == []
    with pytest.raises(SystemExit) as exc:
        basics.main(["preview", "--quality-gate", gate, *arguments])
    assert exc.value.code == 2
    capsys.readouterr()
    assert not any(agent.writes for agent in family.gates.values())
    assert basics.main(["preview", "--quality-gate", "dev", *arguments]) == 0
    dev_review = result_json(capsys)
    assert dev_review["target"]["qualityGate"] == "dev"
    assert basics.main(["save", *arguments, "--approval", gate_view["reviewId"]]) == 2
    assert result_json(capsys)["status"] == "review_again"
    assert not any(agent.writes for agent in family.gates.values())
    assert basics.main(["save", *arguments, "--approval", dev_review["reviewId"]]) == 0
    assert result_json(capsys)["status"] == "saved"
    assert len(family.gates["dev"].writes) == 1
    for quality in ("test", "prod"):
        assert family.gates[quality].state == before[quality]
        assert not family.gates[quality].writes
    for view in (gate_view, dev_review):
        assert basics.main(["cleanup", "--approval", view["reviewId"]]) == 0
        result_json(capsys)


@pytest.mark.parametrize("issue", ["legacy", "missing", "denied"])
def test_cli_e2e_target_failures_do_not_guess_supported_scope(
    cli, client, capsys, issue
):
    if issue == "legacy":
        path = cli / ".local" / "config.json"
        config = json.loads(path.read_text())
        config["releaseLine"] = "legacy"
        path.write_text(json.dumps(config))
    else:

        def unavailable(agent_id):
            raise AgentBuilderHTTPError("read", 404 if issue == "missing" else 403)

        client.get_agent = unavailable
    assert basics.main(["preview", "--name", "dev1"]) == 2
    result = result_json(capsys)
    assert result["status"] == "blocked"
    if issue == "legacy":
        assert "compatible kit" in result["message"]
    else:
        assert result["httpStatus"] == (404 if issue == "missing" else 403)
        assert "unsupported" not in result["message"]
    assert not client.writes


def test_cli_e2e_access_restored_requires_fresh_current_values(cli, client, capsys):
    client.fail_reads = True
    assert basics.main(["preview", "--name", "dev1"]) == 2
    denied = result_json(capsys)
    assert denied["httpStatus"] == 403
    assert not client.writes
    client.fail_reads = False
    client.state["bot"]["displayName"] = "Changed while access was denied"
    client.state["botComponentChanges"][0]["component"]["displayName"] = client.state[
        "bot"
    ]["displayName"]
    assert basics.main(["preview", "--name", "dev1"]) == 0
    review = result_json(capsys)
    assert review["current"]["name"] == "Changed while access was denied"
    assert not client.writes
    assert (
        basics.main(["save", "--name", "dev1", "--approval", review["reviewId"]]) == 0
    )
    assert result_json(capsys)["properties"] == {"name": "saved"}
    assert len(client.writes) == 1


def test_cli_e2e_conflict_invalidates_approval_before_successful_fresh_review(
    cli, client, capsys
):
    assert basics.main(["preview", "--name", "dev1"]) == 0
    original_review = result_json(capsys)
    update = client._update

    def race(agent_id, bot, **kwargs):
        client.state["bot"].update(version=5, displayName="Concurrent rename")
        client.state["botComponentChanges"][0]["component"]["displayName"] = (
            "Concurrent rename"
        )
        return update(agent_id, bot, **kwargs)

    client._update = race
    assert (
        basics.main(
            ["save", "--name", "dev1", "--approval", original_review["reviewId"]]
        )
        == 2
    )
    assert result_json(capsys)["status"] == "review_again"
    assert len(client.writes) == 1
    client._update = update
    client.status = 200
    assert basics.main(["preview", "--name", "dev1"]) == 0
    refreshed = result_json(capsys)
    assert refreshed["current"]["name"] == "Concurrent rename"
    assert (
        basics.main(
            ["save", "--name", "dev1", "--approval", original_review["reviewId"]]
        )
        == 2
    )
    assert result_json(capsys)["status"] == "review_again"
    assert len(client.writes) == 1
    assert (
        basics.main(["save", "--name", "dev1", "--approval", refreshed["reviewId"]])
        == 0
    )
    assert result_json(capsys)["properties"] == {"name": "saved"}
    assert len(client.writes) == 2


@pytest.mark.parametrize("status", [403, 413, 500])
def test_cli_e2e_rejected_save_is_not_completion_or_automatic_retry(
    cli, client, capsys, status
):
    assert basics.main(["preview", "--name", "dev1"]) == 0
    review = result_json(capsys)
    client.status = status
    assert (
        basics.main(["save", "--name", "dev1", "--approval", review["reviewId"]]) == 2
    )
    result = result_json(capsys)
    assert result["status"] != "saved"
    assert result["properties"] == {"name": "failed" if status < 500 else "unverified"}
    assert result["requestId"] == "save-request"
    assert len(client.writes) == 1


@pytest.mark.parametrize("recheck", ["confirmed", "inconclusive"])
def test_cli_e2e_uncertain_save_rechecks_without_resending(
    cli, client, capsys, monkeypatch, recheck
):
    fetch = client.fetch_components
    reads = []

    def readback(agent_id):
        if client.writes:
            reads.append(agent_id)
            if len(reads) == 1 or recheck == "inconclusive":
                raise AgentBuilderHTTPError("read", 503, request_id="readback-request")
        return fetch(agent_id)

    monkeypatch.setattr(client, "fetch_components", readback)
    assert basics.main(["preview", "--name", "dev1"]) == 0
    review = result_json(capsys)
    expected_exit = 0 if recheck == "confirmed" else 2
    assert (
        basics.main(["save", "--name", "dev1", "--approval", review["reviewId"]])
        == expected_exit
    )
    result = result_json(capsys)
    assert result["properties"] == {
        "name": "saved" if recheck == "confirmed" else "unverified"
    }
    assert reads == [AGENT_ID, AGENT_ID]
    assert len(client.writes) == 1
    if recheck == "inconclusive":
        assert result["writesDisabled"] is True
        assert (
            basics.main(["save", "--name", "dev1", "--approval", review["reviewId"]])
            == 2
        )
        assert result_json(capsys)["writesDisabled"] is True
        assert len(client.writes) == 1


@pytest.mark.parametrize("unapplied", ["name", "logo"])
def test_cli_e2e_partial_success_recovery_only_saves_remaining_property(
    cli, client, logos, capsys, unapplied
):
    before = copy.deepcopy(client.state)
    arguments = _branding_arguments("both", logos)

    def restore_unapplied(state):
        if unapplied == "logo":
            state["bot"]["iconBase64"] = before["bot"]["iconBase64"]
        else:
            state["bot"]["displayName"] = before["bot"]["displayName"]
            state["botComponentChanges"][0]["component"]["displayName"] = before[
                "botComponentChanges"
            ][0]["component"]["displayName"]

    client.mutate = restore_unapplied
    assert basics.main(["preview", *arguments]) == 0
    review = result_json(capsys)
    assert basics.main(["save", *arguments, "--approval", review["reviewId"]]) == 2
    partial = result_json(capsys)
    assert partial["properties"] == {
        field: "unverified" if field == unapplied else "saved"
        for field in ("name", "logo")
    }
    assert partial["writesDisabled"] is True
    assert len(client.writes) == 1
    client.mutate = None
    assert basics.main(["view"]) == 0
    recovery = result_json(capsys)
    assert basics.main(["resume-writes", "--approval", recovery["reviewId"]]) == 0
    assert result_json(capsys)["writeAttempted"] is False
    assert len(client.writes) == 1
    assert basics.main(["preview", *arguments]) == 0
    remaining = result_json(capsys)
    assert remaining["changedProperties"] == [unapplied]
    assert basics.main(["save", *arguments, "--approval", remaining["reviewId"]]) == 0
    assert result_json(capsys)["properties"] == {unapplied: "saved"}
    assert len(client.writes) == 2
    assert client.state["bot"]["displayName"] == "dev1"
    assert client.state["bot"]["iconBase64"] == encoded(
        Path(logos["logo"]).read_bytes()
    )
    assert client.state["bot"]["configuration"] == before["bot"]["configuration"]


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


@pytest.mark.parametrize("quality_gate", ["test", "prod"])
def test_promoted_recovery_requires_fresh_same_gate_review_without_service_write(
    cli, monkeypatch, capsys, quality_gate
):
    family = QualityClient()
    agent = family.gates[quality_gate]
    before = {gate: copy.deepcopy(value.state) for gate, value in family.gates.items()}
    monkeypatch.setattr(basics, "AgentBuilderClient", lambda *args, **kwargs: family)
    basics.disable_writes(cli, pending=True)
    options = ["--quality-gate", quality_gate]

    assert basics.main(["view", *options]) == 0
    recovery = result_json(capsys)
    assert recovery["writesDisabled"] is True
    assert recovery["target"]["qualityGate"] == quality_gate
    assert basics.main(["resume-writes", "--approval", recovery["reviewId"]]) == 2
    assert result_json(capsys)["status"] == "review_again"
    assert basics._writes_disabled(cli)

    agent.state["bot"]["version"] += 1
    assert (
        basics.main(["resume-writes", *options, "--approval", recovery["reviewId"]])
        == 2
    )
    assert result_json(capsys)["status"] == "review_again"
    assert basics._writes_disabled(cli)

    assert basics.main(["view", *options]) == 0
    recovery = result_json(capsys)
    assert (
        basics.main(["resume-writes", *options, "--approval", recovery["reviewId"]])
        == 0
    )
    resumed = result_json(capsys)
    assert resumed["status"] == "writes_resumed"
    assert resumed["writeAttempted"] is False
    assert not basics._writes_disabled(cli)
    assert family.configuration_requests == []
    for gate, value in family.gates.items():
        expected = before[gate]
        if gate == quality_gate:
            expected["bot"]["version"] += 1
        assert value.state == expected
        assert not value.writes


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
