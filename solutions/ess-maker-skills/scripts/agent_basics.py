# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Review and author native ESS name/logo changes without publishing."""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import io
import json
import multiprocessing
import re
import sys
import time
import warnings
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

from adk_telemetry import emit_capability_use
from agentbuilder import (
    NATIVE_ALM_API_VERSION,
    REALM_NAMES,
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    authenticate,
)
from auth import EXPECTED_CONFIG_VERSION
from alm_enrollment import _redact_text
from da_product_registry import DAProductRegistryError, resolve_product_setup
from publish import _is_native_config, _native_context
from setup_existing_da import (
    ExistingDASetupError,
    STUDIO_RING_BY_HOST,
    _confirm_direct_native_authoring_identity,
    _confirm_dev,
    _normalize_guid,
    _realm_name,
    _validate_changeset_identity,
)

QUALITY_GATES = {name.casefold(): realm for realm, name in REALM_NAMES.items()}
READ_TIMEOUT_SECONDS = 120
SAVE_TIMEOUT_SECONDS = 180
PROGRESS_INTERVAL_SECONDS = 15
PREVIEW_DIRECTORY = Path(".local/agent-basics-preview")
LOGO_PREVIEW_SIZE = (192, 192)
WRITE_STOP_FILE = Path(".local/agent-basics-writes.disabled")
WRITE_PENDING_FILE = Path(".local/agent-basics-write.pending")
_REVIEW_ID = re.compile(r"[0-9a-f]{64}")
_SERVER_FIELDS = {"version", "auditInfo"}
_PREVIEW_LABELS = (
    "color",
    "outline",
    "previous-color",
    "saved-color",
    "proposed-color",
    "observed-color",
)
_PREVIEW_FILE = re.compile(r"[0-9a-f]{64}-(" + "|".join(_PREVIEW_LABELS) + r")\.png")
_INDEPENDENT_ICON_LIMITATION = (
    "Independent outline and color32x32 customization cannot be completed through "
    "the inspected native ESS platform: publication regenerates color and outline "
    "from iconBase64, and the package model has no color32x32 field. "
    "Use validate-icons for local validation only. Native customization requires "
    "platform support. No write was attempted, including other supplied changes."
)
_DEV_ONLY = (
    "Agent Basics authors names and logos in Dev only. No write was attempted. "
    "Select Dev through the existing setup target-selection flow and review "
    "a separate proposal; the target was not switched."
)


class AgentBasicsError(RuntimeError):
    """A branding request cannot safely continue."""


def _progress(stage: str, **details: Any) -> None:
    print(
        "AGENT_BASICS_PROGRESS_JSON:" + json.dumps({"stage": stage, **details}),
        file=sys.stderr,
        flush=True,
    )


def _digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise AgentBasicsError(
            "Selected workspace configuration is unavailable; resume /setup."
        ) from exc
    if not isinstance(value, dict):
        raise AgentBasicsError("Selected workspace configuration must be an object.")
    return value


def selected_target(root: Path) -> dict[str, str]:
    """Reuse the publisher's canonical selected-target resolution, not titleId."""
    config = _json_file(root / ".local/config.json")
    if config.get("configVersion") != EXPECTED_CONFIG_VERSION:
        raise AgentBasicsError("Workspace configuration needs /setup --refresh.")
    if not _is_native_config(config):
        raise AgentBasicsError(
            "The selected workspace has not established native DA authoring. "
            "Resume /setup to classify it; use the compatible kit only for a "
            "confirmed legacy family. No name or logo was written."
        )
    state = _json_file(root / ".local/setup/config.json")
    if state.get("schema_version") != 4:
        raise AgentBasicsError("Canonical native setup must be schema version 4.")
    context = _native_context(state, config)
    canonical_account = str(state["environment"].get("account") or "").strip()
    operational_account = str(config.get("account") or "").strip()
    if (
        canonical_account
        and operational_account
        and canonical_account.casefold() != operational_account.casefold()
    ):
        raise AgentBasicsError(
            "Canonical setup and workspace configuration identify different "
            "Microsoft accounts. Resume /setup; no write was attempted."
        )
    if canonical_account or operational_account:
        context["account"] = canonical_account or operational_account
    matches = [
        entry
        for entry in state["agents"].values()
        if isinstance(entry, dict)
        and isinstance(entry.get("agent"), dict)
        and entry["agent"].get("workspace_slug") == config["activeAgent"]
    ]
    if len(matches) != 1:
        raise AgentBasicsError("The selected canonical workspace is not unique.")
    selected = matches[0]
    if selected.get("connect_ready") is not True:
        raise AgentBasicsError(
            "Setup is incomplete for the selected agent. Complete /setup before "
            "viewing or changing its name or logo. No write was attempted."
        )
    agent = selected["agent"]
    local_agent = config.get("agent")
    workspace = selected.get("workspace")
    steps = selected.get("steps")
    if (
        not isinstance(local_agent, dict)
        or not isinstance(agent.get("schema_name"), str)
        or not agent["schema_name"]
        or local_agent.get("botId") != context["agent_id"]
        or local_agent.get("schemaName") != agent.get("schema_name")
        or not isinstance(workspace, dict)
        or not isinstance(workspace.get("agent_path"), str)
        or not isinstance(workspace.get("folder"), str)
        or not isinstance(steps, dict)
        or not isinstance(steps.get("SETUP-07"), dict)
        or steps["SETUP-07"].get("state") != "done"
    ):
        raise AgentBasicsError(
            "Selected local and canonical identities disagree or materialization "
            "is incomplete. Resume /setup; no write was attempted."
        )
    folder = (root / workspace["folder"]).resolve()
    agent_path = (folder / workspace["agent_path"]).resolve()
    if (
        not folder.is_relative_to(root.resolve())
        or not agent_path.is_relative_to(folder)
        or not folder.is_dir()
        or not agent_path.is_file()
    ):
        raise AgentBasicsError(
            "The selected materialized workspace is missing. Resume /setup."
        )
    context.update(
        schema_name=agent["schema_name"],
        workspace_slug=config["activeAgent"],
        workspace_fingerprint=_digest({"config": config, "canonical": selected}),
    )
    # Cached display labels must never become target identity or a current value.
    context.pop("agent_name")
    return context


def _agent_studio_url(target: dict[str, str]) -> str:
    hosts = [
        host
        for host, ring in STUDIO_RING_BY_HOST.items()
        if ring == target["ring"] and ".preview." not in host
    ]
    if (
        len(hosts) != 1
        or not target.get("environment_id")
        or not target.get("agent_id")
    ):
        raise AgentBasicsError(
            "The selected agent has no verified Copilot Studio link; check setup."
        )
    return (
        f"https://{hosts[0]}/environments/{quote(target['environment_id'], safe='')}"
        f"/bots/{quote(target['agent_id'], safe='')}/overview"
    )


def validate_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentBasicsError(
            "Supply a nonblank displayName so the intended name is clear. "
            "This is an ADK input check, not a platform length limit. "
            "ADK does not trim or truncate it."
        )
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AgentBasicsError("The displayName must be valid Unicode.") from exc
    if len(value) > 30:
        raise AgentBasicsError(
            "Agent name must not exceed 30 characters. "
            f"You entered {len(value)} characters. Enter a shorter name."
        )
    return value


def _image(data: bytes, *, size: int | None = None, png_only: bool = False) -> bytes:
    if not data:
        raise AgentBasicsError("Supply a nonempty image.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if png_only and image.format != "PNG":
                    raise AgentBasicsError(
                        f"Supply a PNG; the supplied file is {image.format}."
                    )
                if size is not None and image.size != (size, size):
                    raise AgentBasicsError(
                        f"PNG dimensions must be exactly {size}x{size}; "
                        f"the supplied image is {image.width}x{image.height}."
                    )
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                frames = getattr(image, "n_frames", 1)
                if frames > 1:
                    fingerprint = hashlib.sha256()
                    fingerprint.update(
                        _digest(
                            {
                                "frames": frames,
                                "loop": image.info.get("loop"),
                                "defaultImage": image.info.get("default_image", False),
                            }
                        ).encode("ascii")
                    )
                    for index in range(frames):
                        image.seek(index)
                        image.load()
                        fingerprint.update(
                            _digest(
                                {
                                    "size": image.size,
                                    "duration": image.info.get("duration"),
                                }
                            ).encode("ascii")
                        )
                        fingerprint.update(image.convert("RGBA").tobytes())
                    return fingerprint.digest()
                image.load()
                rgba = image.convert("RGBA")
                pixels = rgba.tobytes()
                return (
                    image.width.to_bytes(4, "big")
                    + image.height.to_bytes(4, "big")
                    + pixels
                )
    except (
        OSError,
        ValueError,
        SyntaxError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise AgentBasicsError(
            "The image cannot be fully decoded for a safe preview; no write is "
            "allowed. Provide a readable image. This is a local preview check, "
            "not a statement of the service's supported formats."
        ) from exc


def _png(data: bytes, *, size: int | None = None) -> bytes:
    return _image(data, size=size, png_only=True)


def _image_file(path: str, *, size: int | None = None) -> tuple[str, bytes]:
    source = Path(path).expanduser().resolve()
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise AgentBasicsError("The selected local image cannot be read.") from exc
    if size is None:
        _image(data)
    else:
        _png(data, size=size)
    return str(source), data


def _preview_image(data: bytes, root: Path, review_id: str, suffix: str) -> Path:
    directory = root / PREVIEW_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{review_id}-{suffix}.png"
    with Image.open(io.BytesIO(data)) as image:
        if image.format == "PNG" and image.size == LOGO_PREVIEW_SIZE:
            path.write_bytes(data)
        else:
            ImageOps.pad(
                image.convert("RGBA"),
                LOGO_PREVIEW_SIZE,
                method=Image.Resampling.LANCZOS,
                color=(0, 0, 0, 0),
            ).save(path, format="PNG")
    return path.resolve()


def _manifest_png(data: bytes, kind: str) -> bytes:
    pixels = _png(data, size=192 if kind == "color" else 32)
    if kind == "color":
        return pixels
    with Image.open(io.BytesIO(data)) as image:
        for frame in range(image.n_frames):
            image.seek(frame)
            rgba = image.convert("RGBA").tobytes()
            colors = list(zip(rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4]))
            if not any(alpha == 0 for _, _, _, alpha in colors):
                raise AgentBasicsError(
                    f"The {kind} icon needs a transparent background."
                )
            if kind == "outline":
                visible = [(r, g, b) for r, g, b, alpha in colors if alpha]
                if not visible or any(pixel != (255, 255, 255) for pixel in visible):
                    raise AgentBasicsError(
                        "The outline icon must be white on a transparent background."
                    )
    return pixels


def _icon_file(path: str, kind: str) -> tuple[str, bytes]:
    source, data = _image_file(path, size=192 if kind == "color" else 32)
    _manifest_png(data, kind)
    return source, data


def _decode(value: Any) -> bytes:
    if value is None:
        return b""
    if not isinstance(value, str):
        raise AgentBasicsError("The saved icon is unreadable.")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AgentBasicsError("The saved icon is not valid base64.") from exc


def _logo(bot: dict[str, Any]) -> bytes:
    if "iconBase64" not in bot:
        raise AgentBasicsError(
            "The current logo was not returned; logo editing is unavailable."
        )
    color = _decode(bot["iconBase64"])
    if color:
        _image(color)
    return color


def _promoted_target(
    client: AgentBuilderClient,
    target: dict[str, str],
    quality_gate: str,
    family_id: str,
) -> tuple[str, str, dict[str, Any]]:
    _progress("checking_quality_gate", qualityGate=quality_gate)
    realms = client.get_realms(target["agent_id"])
    if not isinstance(realms, dict) or _realm_name(realms.get("routeRealm")) != "dev":
        raise AgentBasicsError(
            "Quality-gate discovery did not identify the Dev source."
        )
    siblings = realms.get("siblingRealms")
    if not isinstance(siblings, list):
        raise AgentBasicsError("Quality-gate discovery did not return sibling agents.")
    matches = [
        sibling
        for sibling in siblings
        if isinstance(sibling, dict)
        and _realm_name(sibling.get("realm")) == quality_gate
    ]
    if len(matches) != 1:
        raise AgentBasicsError(
            f"The {quality_gate} quality-gate target is missing or ambiguous."
        )
    agent_id = _normalize_guid(
        str(matches[0].get("botId") or ""), "Quality-gate agent ID"
    )
    if agent_id.casefold() == target["agent_id"].casefold():
        raise AgentBasicsError("A promoted quality gate cannot use the Dev agent ID.")
    card = client.get_agent(agent_id)
    if not isinstance(card, dict):
        raise AgentBasicsError("The quality-gate agent identity is unreadable.")
    enrolled, realm = _confirm_direct_native_authoring_identity(agent_id, card)
    if not enrolled or realm != quality_gate:
        raise AgentBasicsError(
            "The discovered agent does not match the requested gate."
        )
    configuration = client.get_realm_configuration(
        agent_id, QUALITY_GATES[quality_gate]
    )
    if not isinstance(configuration, dict):
        raise AgentBasicsError("The quality-gate configuration is unreadable.")
    if _realm_name(configuration.get("realm")) != quality_gate:
        raise AgentBasicsError("The configuration identifies a different quality gate.")
    configured_id = _normalize_guid(
        str(configuration.get("cdsBotId") or ""), "Configured quality-gate agent ID"
    )
    if configured_id.casefold() != agent_id.casefold():
        raise AgentBasicsError(
            "The quality-gate configuration identifies another agent."
        )
    configured_family = str(configuration.get("grsRepositoryId") or "").strip()
    if configured_family.casefold() != family_id.casefold():
        raise AgentBasicsError("The quality-gate agent belongs to another ALM family.")
    schema = str(
        configuration.get("schemaName") or card.get("schemaName") or ""
    ).strip()
    source_schema = target["schema_name"].casefold()
    if schema.casefold() not in {source_schema, f"{source_schema}_{quality_gate}"}:
        raise AgentBasicsError(
            "The quality-gate schema does not match the selected ESS agent."
        )
    values = configuration.get("values")
    if not isinstance(values, dict) or not all(
        isinstance(key, str) and (value is None or isinstance(value, str))
        for key, value in values.items()
    ):
        raise AgentBasicsError("The quality-gate configuration values are unreadable.")
    if not isinstance(values.get("botName"), str):
        raise AgentBasicsError("The quality-gate botName binding is unavailable.")
    return agent_id, schema, configuration


def read_state(
    client: AgentBuilderClient,
    target: dict[str, str],
    *,
    quality_gate: str = "dev",
) -> tuple[dict[str, Any], dict[str, Any]]:
    if quality_gate not in QUALITY_GATES:
        raise AgentBasicsError("Select the dev, test, or prod quality gate.")
    agent_id = target["agent_id"]
    expected_schema = target["schema_name"]
    family_id = ""
    realm_configuration = None
    _progress("checking_agent")
    card = client.get_agent(agent_id)
    if not isinstance(card, dict):
        raise AgentBasicsError("The live agent identity is unreadable.")
    enrolled, realm = _confirm_direct_native_authoring_identity(agent_id, card)
    if enrolled and realm != "dev":
        raise ExistingDASetupError(
            "The selected setup target is not the Dev authoring agent."
        )
    if quality_gate != "dev":
        if not enrolled:
            raise AgentBasicsError("Test and Prod require an ALM-enrolled Dev source.")
        _progress("checking_dev_target")
        configuration = client.get_dev_configuration(agent_id)
        if not isinstance(configuration, dict):
            raise AgentBasicsError("The live Dev configuration is unreadable.")
        schema, family_id, realm = _confirm_dev(agent_id, card, configuration)
        if schema.casefold() != target["schema_name"].casefold():
            raise AgentBasicsError("Dev configuration and selected schema disagree.")
        agent_id, expected_schema, realm_configuration = _promoted_target(
            client, target, quality_gate, family_id
        )
        realm = quality_gate
    _progress("reading_current_settings")
    changeset = client.fetch_components(agent_id)
    if not isinstance(changeset, dict):
        raise AgentBasicsError("The live authoring state is unreadable.")
    schema = _validate_changeset_identity(
        changeset,
        agent_id,
        expected_schema_name=expected_schema,
    )
    product = resolve_product_setup(agent_schema_name=target["schema_name"])
    if not product:
        raise AgentBasicsError(
            "This schema is not a supported ESS product. No write is allowed."
        )
    bot = changeset["bot"]
    if realm_configuration is not None:
        if realm_configuration["values"]["botName"] != bot.get("displayName"):
            raise AgentBasicsError(
                "The quality-gate name and configuration changed during read; refresh."
            )
        changeset["_realmConfiguration"] = realm_configuration
    version = bot.get("version")
    if type(version) is not int or version < 1:
        raise AgentBasicsError(
            "A positive BotEntity.version is required for a protected save."
        )
    if not isinstance(changeset.get("botComponentChanges"), list):
        raise AgentBasicsError(
            "Component state is unavailable; instruction preservation cannot be checked."
        )
    return changeset, {
        **target,
        "agent_id": agent_id,
        "schema_name": schema,
        **({"alm_family_id": family_id} if family_id else {}),
        "product": product["productKey"],
        "qualityGate": realm if enrolled else "unenrolled authoring",
    }


def _require_dev_edit(quality_gate: str) -> None:
    if quality_gate != "dev":
        raise AgentBasicsError(_DEV_ONLY)


def _gpt_component(state: dict[str, Any]) -> dict[str, Any]:
    components = [
        change["component"]
        for change in state["botComponentChanges"]
        if isinstance(change, dict)
        and isinstance(change.get("component"), dict)
        and change["component"].get("$kind") == "GptComponent"
    ]
    if len(components) != 1:
        raise AgentBasicsError(
            "Exactly one GPT component is required to verify the chat name."
        )
    component = components[0]
    _normalize_guid(str(component.get("id") or ""), "GPT component ID")
    if (
        not isinstance(component.get("schemaName"), str)
        or not component["schemaName"].strip()
    ):
        raise AgentBasicsError("The GPT component schema is unreadable.")
    if not isinstance(component.get("displayName"), str):
        raise AgentBasicsError(
            "The current chat name is unreadable; rename is unavailable."
        )
    return component


def validate_package(path: Path) -> dict[str, Any]:
    """Inspect an existing app package without extracting or publishing it."""
    try:
        with zipfile.ZipFile(path) as package:
            if len(package.namelist()) != len(set(package.namelist())):
                raise AgentBasicsError("The app package contains duplicate file paths.")
            manifest = json.loads(package.read("manifest.json").decode("utf-8-sig"))
            icons = manifest.get("icons") if isinstance(manifest, dict) else None
            if (
                not isinstance(icons, dict)
                or not {"outline", "color"}.issubset(icons)
                or set(icons) - {"outline", "color", "color32x32"}
            ):
                raise AgentBasicsError(
                    "The app manifest must reference outline and color icons, "
                    "with only color32x32 optional."
                )
            for kind, asset_path in icons.items():
                if (
                    not isinstance(asset_path, str)
                    or not asset_path
                    or len(asset_path) > 2048
                    or "\\" in asset_path
                    or ":" in asset_path
                    or asset_path.startswith("/")
                    or any(part in ("", ".", "..") for part in asset_path.split("/"))
                ):
                    raise AgentBasicsError(
                        f"The {kind} icon needs a package-relative path of at most "
                        "2,048 characters without traversal."
                    )
                data = package.read(asset_path)
                _manifest_png(data, kind)
    except AgentBasicsError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, RuntimeError) as exc:
        raise AgentBasicsError(
            "The app package is unreadable, malformed, encrypted, or missing "
            "manifest.json or a referenced icon."
        ) from exc
    return {
        "status": "validated",
        "scope": "provided_app_package_icons_only",
        "icons": sorted(icons),
        "targetAssociation": "unverified",
        "publication": "Not performed.",
        "employeeVisibility": "unverified",
    }


def prepare(
    client: AgentBuilderClient,
    target: dict[str, str],
    *,
    name: str | None = None,
    logo: str | None = None,
    color: str | None = None,
    outline: str | None = None,
    color32x32: str | None = None,
    quality_gate: str = "dev",
    name_only: bool = False,
) -> dict[str, Any]:
    if outline is not None or color32x32 is not None:
        raise AgentBasicsError(_INDEPENDENT_ICON_LIMITATION)
    if color is not None:
        if logo is not None:
            raise AgentBasicsError(
                "--color and --logo name the same source; use only one."
            )
        logo = color
    if name_only and any(value is not None for value in (name, logo, color, outline)):
        raise AgentBasicsError("A name-only view cannot include proposed changes.")
    if any(value is not None for value in (name, logo, color, outline)):
        _require_dev_edit(quality_gate)
    source: dict[str, str] = {}
    desired: dict[str, Any] = {}
    if name is not None:
        desired["displayName"] = validate_name(name)
    supplied = None
    if logo is not None:
        _progress("validating_logo")
        source["color"], supplied = _image_file(logo)
    state, resolved_target = read_state(client, target, quality_gate=quality_gate)
    bot = state["bot"]
    readable_name = isinstance(bot.get("displayName"), str)
    if readable_name:
        _progress("current_property_loaded", property="name", value=bot["displayName"])
    else:
        _progress("current_property_unavailable", property="name")
    current_logo = None
    logo_error = None
    inspect_logo = not name_only and (name is None or supplied is not None)
    if inspect_logo:
        _progress("reading_current_logo")
        try:
            current_logo = _logo(bot)
        except AgentBasicsError as exc:
            logo_error = str(exc)
            _progress(
                "current_property_unavailable", property="logo", reason=logo_error
            )
        else:
            _progress(
                "current_property_loaded",
                property="logo",
                value="confirmed" if current_logo else "none",
            )
    if "displayName" in desired and not readable_name:
        raise AgentBasicsError(
            "The current name is unreadable; name editing is unavailable."
        )
    if supplied is not None and current_logo is None:
        raise AgentBasicsError(logo_error)
    gpt = _gpt_component(state) if name is not None else None
    if (
        gpt is not None
        and gpt["displayName"] != desired["displayName"]
        and (
            not isinstance(state.get("changeToken"), str)
            or not state["changeToken"].strip()
        )
    ):
        raise AgentBasicsError(
            "A component change token is required for a protected chat-name update."
        )
    if supplied is not None:
        desired["logo"] = base64.b64encode(supplied).decode("ascii")
    changes = {}
    if gpt is not None and (
        desired["displayName"] != bot["displayName"]
        or desired["displayName"] != gpt["displayName"]
    ):
        changes["name"] = desired["displayName"]
    if "logo" in desired:
        desired_logo = _decode(desired["logo"])
        if _image(desired_logo) != (_image(current_logo) if current_logo else b""):
            changes["logo"] = desired["logo"]
    agent_studio_url = _agent_studio_url(resolved_target)
    review_id = _digest(
        {
            "target": resolved_target,
            "state": state,
            "desired": desired,
            "sources": source,
            "nameOnly": name_only,
        }
    )
    return {
        "reviewId": review_id,
        "selection": dict(target),
        "requestedQualityGate": quality_gate,
        "target": resolved_target,
        "agentStudioUrl": agent_studio_url,
        "state": state,
        "desired": desired,
        "changes": changes,
        "sources": source,
        "currentLogo": current_logo,
        "logoInspected": inspect_logo,
        "logoError": logo_error,
    }


def review_output(plan: dict[str, Any], root: Path) -> dict[str, Any]:
    bot = plan["state"]["bot"]
    current: dict[str, Any] = {
        "name": bot.get("displayName")
        if isinstance(bot.get("displayName"), str)
        else None,
    }
    if current["name"] is None:
        current["nameIssue"] = (
            "The current name was not returned as readable text; "
            "name editing is unavailable."
        )
    if plan["logoInspected"]:
        current["logo"] = (
            "unavailable"
            if plan["currentLogo"] is None
            else "confirmed"
            if plan["currentLogo"]
            else "none"
        )
        current["logoIssue"] = plan["logoError"]
    if plan["currentLogo"]:
        path = _preview_image(plan["currentLogo"], root, plan["reviewId"], "color")
        current["colorPreview"] = str(path)
        current["colorPreviewUri"] = path.as_uri()
        current["colorPreviewMarkdown"] = (
            f"![Current agent logo]({current['colorPreviewUri']})"
        )
    promoted = plan["requestedQualityGate"] != "dev"
    readable = {
        "name": current["name"] is not None,
        **({"logo": current["logo"] != "unavailable"} if "logo" in current else {}),
    }
    if readable["name"] and not promoted:
        try:
            _gpt_component(plan["state"])
        except (AgentBasicsError, ExistingDASetupError) as exc:
            readable["name"] = False
            current["nameIssue"] = f"Name editing is unavailable: {exc}"
    proposed: dict[str, Any] = {
        "name": plan["desired"].get("displayName"),
        "logoSources": plan["sources"],
    }
    if "logo" in plan["desired"]:
        data = _decode(plan["desired"]["logo"])
        path = _preview_image(data, root, plan["reviewId"], "proposed-color")
        with Image.open(io.BytesIO(data)) as image:
            proposed["logoDetails"] = {
                "format": image.format,
                "width": image.width,
                "height": image.height,
                "frames": getattr(image, "n_frames", 1),
            }
        proposed["logoPreviewMarkdown"] = f"![Proposed agent logo]({path.as_uri()})"
        proposed["logoProcessing"] = (
            "Original file bytes will be submitted unchanged. The service may "
            "resize or otherwise process the image; read-back must be checked "
            "against this review. A static preview does not show all animation frames."
        )
    return {
        "status": "review" if plan["changes"] else "no_change",
        "reviewId": plan["reviewId"],
        "target": plan["target"],
        "agentStudioUrl": plan["agentStudioUrl"],
        "current": current,
        "proposed": proposed,
        "changedProperties": list(plan["changes"]),
        "editableProperties": [
            field for field, available in readable.items() if available and not promoted
        ],
        "localArtifacts": "No agent files or setup display labels changed.",
        "publication": "Not performed; approval and employee visibility are unverified.",
        "concurrencyProtection": (
            "Read-only; Agent Basics does not author Test/Prod."
            if promoted
            else "Revision checks protect the save."
        ),
        "authoringLimitations": [_DEV_ONLY] if promoted else [],
    }


def cleanup(root: Path, review_id: str) -> None:
    if not _REVIEW_ID.fullmatch(review_id):
        raise AgentBasicsError("Invalid review identifier.")
    for label in _PREVIEW_LABELS:
        (root / PREVIEW_DIRECTORY / f"{review_id}-{label}.png").unlink(missing_ok=True)


def _saved_comparison(
    plan: dict[str, Any], results: dict[str, str], root: Path
) -> dict[str, Any]:
    comparison: dict[str, Any] = {}
    if results.get("name") == "saved":
        comparison["name"] = {
            "previous": plan["state"]["bot"]["displayName"],
            "current": plan["changes"]["name"],
        }
    if results.get("logo") == "saved":
        comparison["logo"] = {}
        for column, label, data in (
            ("previous", "Previous agent logo", plan["currentLogo"]),
            ("current", "Saved DEV agent logo", _decode(plan["changes"]["logo"])),
        ):
            if not data:
                comparison["logo"][column] = {"logo": "none"}
                continue
            suffix = "previous-color" if column == "previous" else "saved-color"
            path = _preview_image(data, root, plan["reviewId"], suffix)
            uri = path.as_uri()
            comparison["logo"][column] = {
                "logo": "confirmed",
                "preview": str(path.resolve()),
                "previewUri": uri,
                "previewMarkdown": f"![{label}]({uri})",
            }
    return comparison


def cleanup_expired(root: Path) -> None:
    """Bound retention after interrupted sessions; only delete our named copies."""
    directory = root / PREVIEW_DIRECTORY
    if directory.exists():
        for path in directory.iterdir():
            if (
                _PREVIEW_FILE.fullmatch(path.name)
                and path.is_file()
                and path.stat().st_mtime < time.time() - 3600
            ):
                path.unlink()


def _preservation_snapshot(
    state: dict[str, Any], changes: dict[str, Any]
) -> dict[str, Any]:
    bot = copy.deepcopy(state["bot"])
    for field in _SERVER_FIELDS:
        bot.pop(field, None)
    if "name" in changes:
        bot.pop("displayName", None)
    if "name" in changes or "logo" in changes:
        # The platform owns source-icon normalization and derived icon fields.
        bot.pop("iconBase64", None)
        application = bot.get("teamsAppInformation")
        if isinstance(application, dict):
            teams = application.get("teams")
            if isinstance(teams, dict):
                teams.pop("outlineIcon", None)
                teams.pop("colorIcon", None)
            if application.get("teams") in ({}, None):
                application.pop("teams", None)
            if not application:
                bot.pop("teamsAppInformation")
        elif application is None:
            bot.pop("teamsAppInformation", None)
    components = copy.deepcopy(state["botComponentChanges"])
    if "name" in changes:
        gpt = _gpt_component({**state, "botComponentChanges": components})
        for field in ("displayName", *_SERVER_FIELDS):
            gpt.pop(field, None)
    return {
        "bot": bot,
        "botComponentChanges": components,
        "_realmConfiguration": state.get("_realmConfiguration"),
    }


def _preserved(
    before: dict[str, Any], after: dict[str, Any], changes: dict[str, Any]
) -> bool:
    return _preservation_snapshot(before, changes) == _preservation_snapshot(
        after, changes
    )


def disable_writes(root: Path, *, pending: bool = False) -> None:
    path = root / (WRITE_PENDING_FILE if pending else WRITE_STOP_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    # One marker, no branding, instructions, target snapshots or history.
    with path.open("x", encoding="utf-8") as stream:
        stream.write(
            "Agent Basics writes are stopped. Establish actual saved and "
            "publication state, resolve the issue with the engineering owner, "
            "then explicitly review resumption. This does not roll back a save.\n"
        )


def _writes_disabled(root: Path) -> bool:
    return any((root / path).exists() for path in (WRITE_STOP_FILE, WRITE_PENDING_FILE))


def _require_writes_enabled(root: Path) -> None:
    if _writes_disabled(root):
        raise AgentBasicsError(
            "Agent Basics writes are disabled in this workspace. Use view "
            "to establish actual state and follow the reviewed recovery flow. "
            "Do not delete the marker or retry the save to bypass recovery."
        )


def _release_pending_write(root: Path) -> str | None:
    try:
        (root / WRITE_PENDING_FILE).unlink()
    except OSError:
        return (
            "ADK could not release the local write stop. The service outcome "
            "is unchanged; complete reviewed recovery before further writes."
        )
    return None


def _record_logo_confirmation(
    root: Path, plan: dict[str, Any], observed: dict[str, Any]
) -> dict[str, Any]:
    record = {
        "kind": "logo_confirmation",
        "workspace": _digest(str(root.resolve())),
        "selection": _digest(plan["selection"]),
        "target": _digest(plan["target"]),
        "baseline": _digest(_preservation_snapshot(observed, {"logo": True})),
        "approvedLogo": hashlib.sha256(
            _image(_decode(plan["changes"]["logo"]))
        ).hexdigest(),
        "minimumRevision": observed["bot"]["version"],
        "requestedProperties": [
            *(["name"] if "displayName" in plan["desired"] else []),
            "logo",
        ],
    }
    # Store only fingerprints after a completed, preservation-checked request.
    with (root / WRITE_PENDING_FILE).open("r+", encoding="utf-8") as stream:
        stream.seek(0)
        json.dump(record, stream)
        stream.truncate()
    return record


def logo_confirmation_review(plan: dict[str, Any], root: Path) -> dict[str, Any] | None:
    path = root / WRITE_PENDING_FILE
    if (
        (root / WRITE_STOP_FILE).exists()
        or not path.exists()
        or plan["requestedQualityGate"] != "dev"
        or plan["desired"]
    ):
        return None
    text = path.read_text(encoding="utf-8")
    if not text.lstrip().startswith("{"):
        # Legacy/interrupted markers do not establish logo-only uncertainty.
        return None
    try:
        record = json.loads(text)
    except ValueError as exc:
        raise AgentBasicsError(
            "The previous logo confirmation evidence is unreadable; saves remain paused."
        ) from exc
    if (
        not isinstance(record, dict)
        or record.get("kind") != "logo_confirmation"
        or not all(
            isinstance(record.get(key), str) and _REVIEW_ID.fullmatch(record[key])
            for key in ("workspace", "selection", "target", "baseline", "approvedLogo")
        )
        or type(record.get("minimumRevision")) is not int
    ):
        raise AgentBasicsError(
            "The previous logo confirmation evidence is invalid; saves remain paused."
        )
    requested = record.get("requestedProperties", ["logo"])
    if requested not in (["logo"], ["name", "logo"]):
        raise AgentBasicsError(
            "The saved confirmation scope is invalid; saves remain paused."
        )
    if (
        record["workspace"] != _digest(str(root.resolve()))
        or record["selection"] != _digest(plan["selection"])
        or record["target"] != _digest(plan["target"])
        or record["baseline"]
        != _digest(_preservation_snapshot(plan["state"], {"logo": True}))
        or plan["state"]["bot"]["version"] < record["minimumRevision"]
    ):
        return {
            "status": "blocked",
            "reason": "The target, preserved settings or readable logo could not be confirmed; keep saves paused.",
        }
    if not plan["logoInspected"]:
        return {
            "status": "available",
            "requestedProperties": requested,
            "writeAttempted": False,
        }
    if not plan["currentLogo"]:
        return {
            "status": "blocked",
            "reason": "The previous logo could not be read; keep saves paused.",
        }
    matches = (
        hashlib.sha256(_image(plan["currentLogo"])).hexdigest()
        == record["approvedLogo"]
    )
    review: dict[str, Any] = {
        "status": "verified" if matches else "confirmation_required",
        "reviewId": _digest(
            {
                "view": plan["reviewId"],
                "pending": record,
                "confirmationMode": "copilot_studio",
                "agentStudioUrl": plan["agentStudioUrl"],
                "requestedProperties": requested,
            }
        ),
        "requestedProperties": requested,
        "writeAttempted": False,
    }
    if not matches:
        setting = "name and logo" if "name" in requested else "logo"
        review["dialog"] = {
            "title": "Confirm update",
            "question": f"Did the {setting} update as intended?",
            "description": (
                "Open your DEV agent in Microsoft Copilot Studio "
                f"and check the {setting}.\n{plan['agentStudioUrl']}"
            ),
            "choices": {
                "yes": "Yes, updated as intended",
                "no": "No, it needs correction",
                "cancel": "Cancel",
            },
        }
    return review


def confirm_logo(
    plan: dict[str, Any],
    root: Path,
    *,
    approval: str | None = None,
    decision: str | None = None,
) -> dict[str, Any]:
    review = logo_confirmation_review(plan, root)
    if not review or review["status"] not in ("verified", "confirmation_required"):
        raise AgentBasicsError(
            "This pause cannot be resolved by logo confirmation; no write was attempted."
        )
    verified = review["status"] == "verified"
    if not verified and (
        approval != review["reviewId"] or decision not in ("yes", "no")
    ):
        return {
            "status": "review_again",
            "reason": "The logo confirmation changed; show a fresh current-logo review.",
            "writesDisabled": _writes_disabled(root),
            "writeAttempted": False,
        }
    write_stop_issue = _release_pending_write(root)
    return {
        "status": "logo_verified"
        if verified
        else "logo_confirmed"
        if decision == "yes"
        else "logo_not_confirmed",
        "properties": {
            "logo": "saved"
            if verified
            else "confirmed_by_user"
            if decision == "yes"
            else "not_confirmed"
        },
        "verificationMethod": "api_exact_match"
        if verified
        else "user_studio_confirmation",
        "target": plan["target"],
        "agentStudioUrl": plan["agentStudioUrl"],
        "requestedProperties": review["requestedProperties"],
        "writesDisabled": _writes_disabled(root),
        "writeStopIssue": write_stop_issue,
        "writeAttempted": False,
        "publication": "Not performed.",
        "replacementRequested": decision == "no",
        "nextAction": (
            "Ask which requested setting needs correction, then use the normal preview and save-approval flow; do not retry automatically."
            if "name" in review["requestedProperties"]
            else "Offer a replacement through the normal preview and save-approval flow; do not retry automatically."
        )
        if decision == "no"
        else "Keep the confirmed logo; do not repeat the previous upload.",
    }


def _verified_properties(
    plan: dict[str, Any], after: dict[str, Any], status_code: int | None
) -> tuple[dict[str, str], bool, dict[str, dict[str, str]]]:
    changes = plan["changes"]
    results = {field: "unverified" for field in changes}
    property_issues: dict[str, dict[str, str]] = {}
    observed = after["bot"]
    # A cached pre-save read does not prove that an uncertain write failed.
    later_revision = observed["version"] > plan["state"]["bot"]["version"]
    if "name" in changes:
        gpt = _gpt_component(plan["state"])
        try:
            observed_gpt = _gpt_component(after)
            if not isinstance(observed.get("displayName"), str):
                raise AgentBasicsError("The saved display name is unreadable.")
        except (AgentBasicsError, ExistingDASetupError) as exc:
            property_issues["name"] = {
                "errorType": type(exc).__name__,
                "reason": str(exc),
            }
        else:
            if (
                later_revision
                and observed["displayName"] == changes["name"]
                and observed_gpt["displayName"] == changes["name"]
            ):
                results["name"] = "saved"
            elif (
                status_code is not None
                and 400 <= status_code < 500
                and observed["displayName"] == plan["state"]["bot"]["displayName"]
                and observed_gpt["displayName"] == gpt["displayName"]
            ):
                results["name"] = "failed"
    if "logo" in changes:
        try:
            actual_logo = _logo(observed)
            actual_pixels = _image(actual_logo) if actual_logo else b""
            original_logo = plan["currentLogo"]
            original_pixels = _image(original_logo) if original_logo else b""
            expected_pixels = _image(_decode(changes["logo"]))
        except AgentBasicsError as exc:
            property_issues["logo"] = {
                "errorType": type(exc).__name__,
                "reason": str(exc),
            }
        else:
            if later_revision and actual_pixels == expected_pixels:
                results["logo"] = "saved"
            elif (
                status_code is not None
                and 400 <= status_code < 500
                and actual_pixels == original_pixels
            ):
                results["logo"] = "failed"
    try:
        preserved = _preserved(plan["state"], after, changes)
    except (AgentBasicsError, ExistingDASetupError):
        preserved = False
    return results, preserved, property_issues


def _service_error(response: requests.Response) -> dict[str, Any]:
    result: dict[str, Any] = {"httpStatus": response.status_code}
    try:
        body = response.json()
    except ValueError:
        return result
    if not isinstance(body, dict):
        return result
    error = body.get("error") or body.get("Error") or body
    if not isinstance(error, dict):
        return result
    code = error.get("code") or error.get("Code")
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", code):
        result["code"] = code
    # Only structured validation messages, never response bodies or inner errors.
    message = error.get("message") or error.get("Message")
    if response.status_code in (400, 413, 415, 422) and isinstance(message, str):
        message = _redact_text(message)
        message = re.sub(r"https?://\S+|[\w.+-]+@[\w.-]+", "[REDACTED]", message)
        message = re.sub(r"[A-Za-z]:\\[^\r\n;]+", "[REDACTED]", message)
        message = re.sub(r"[A-Za-z0-9+/=_-]{80,}", "[REDACTED]", message)
        message = " ".join(message.split())[:1000]
        if message and "<" not in message and ">" not in message:
            result["message"] = message
    return result


def save(
    client: AgentBuilderClient,
    plan: dict[str, Any],
    approval: str,
    *,
    current_target: dict[str, str],
    root: Path,
) -> dict[str, Any]:
    """Save a freshly prepared plan; the CLI always prepares again after approval."""
    _require_dev_edit(plan["requestedQualityGate"])
    if approval != plan["reviewId"] or current_target != plan["selection"]:
        return {
            "status": "review_again",
            "reason": "Target, proposal or reviewed state changed; no write.",
        }
    changes = plan["changes"]
    if not changes:
        return {"status": "no_change", "properties": {}, "writeAttempted": False}
    _require_writes_enabled(root)
    _progress("refreshing_reviewed_state")
    refreshed, refreshed_target = read_state(client, current_target)
    if refreshed != plan["state"] or refreshed_target != plan["target"]:
        return {
            "status": "review_again",
            "reason": "Reviewed state changed; refresh and review again.",
            "writeAttempted": False,
        }
    bot = copy.deepcopy(plan["state"]["bot"])
    gpt = None
    if "name" in changes:
        bot["displayName"] = changes["name"]
        gpt = _gpt_component(plan["state"])
    if "logo" in changes:
        bot["iconBase64"] = changes["logo"]

    status_code = None
    request_id = None
    transport_issue = False
    service_error = None
    try:
        disable_writes(root, pending=True)
    except FileExistsError as exc:
        raise AgentBasicsError(
            "Another save or validation stop disabled writes; no write was attempted."
        ) from exc
    try:
        _progress("saving_approved_changes", properties=list(changes))
        if gpt is not None and gpt["displayName"] != changes["name"]:
            updated_gpt = copy.deepcopy(gpt)
            updated_gpt["displayName"] = changes["name"]
            response = client.session.request(
                "PUT",
                f"{client.host}/copilotstudio/minimalBots/api/{plan['target']['agent_id']}/components",
                params={"api-version": NATIVE_ALM_API_VERSION},
                headers={**client.headers, "Content-Type": "application/json"},
                json={
                    "bot": bot,
                    "changeToken": plan["state"]["changeToken"],
                    "botComponentChanges": [
                        {"$kind": "BotComponentUpdate", "component": updated_gpt}
                    ],
                },
                timeout=SAVE_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        else:
            response = client.update_bot_entity(plan["target"]["agent_id"], bot)
        status_code = response.status_code
        if status_code >= 400:
            service_error = _service_error(response)
        request_id = next(
            (
                response.headers.get(key)
                for key in ("x-ms-service-request-id", "x-ms-request-id", "request-id")
                if response.headers.get(key)
            ),
            None,
        )
    except requests.RequestException:
        transport_issue = True
    if status_code in (409, 412):
        write_stop_issue = _release_pending_write(root)
        return {
            "status": "review_again",
            "reason": "Save conflicted; refresh and review again.",
            "httpStatus": status_code,
            "requestId": request_id,
            "writesDisabled": _writes_disabled(root),
            "writeStopIssue": write_stop_issue,
        }
    results = {field: "unverified" for field in changes}
    preserved = False
    read_back_issue: dict[str, Any] | None = None
    last_revision: int | None = None
    observed_state = None
    for attempt in range(2):
        _progress(
            "rechecking_saved_changes" if attempt else "verifying_saved_changes",
            properties=list(changes),
        )
        try:
            after, observed_target = read_state(
                client, current_target, quality_gate=plan["requestedQualityGate"]
            )
            if observed_target != plan["target"]:
                raise AgentBasicsError(
                    "The quality-gate target changed during save verification."
                )
            if last_revision is not None and after["bot"]["version"] < last_revision:
                raise AgentBasicsError(
                    "Save recheck returned an older revision than the first read."
                )
            checked_results, preserved, property_issues = _verified_properties(
                plan, after, status_code
            )
            observed_state = after
        except (
            AgentBuilderError,
            AgentBasicsError,
            ExistingDASetupError,
            DAProductRegistryError,
            requests.RequestException,
        ) as exc:
            preserved = False
            read_back_issue = {"errorType": type(exc).__name__}
            if isinstance(exc, AgentBasicsError):
                read_back_issue["reason"] = str(exc)
            if isinstance(exc, AgentBuilderHTTPError):
                read_back_issue.update(
                    httpStatus=exc.status_code, requestId=exc.request_id
                )
            if not attempt and isinstance(
                exc, (AgentBuilderError, requests.RequestException)
            ):
                continue
            break
        read_back_issue = (
            {"errorType": "PropertyReadBackError", "properties": property_issues}
            if property_issues
            else None
        )
        for field in property_issues:
            if results[field] == "saved":
                checked_results[field] = "saved"
        changed_after_verification = [
            field
            for field, value in results.items()
            if value == "saved" and checked_results[field] != "saved"
        ]
        results = checked_results
        if changed_after_verification:
            preserved = False
            read_back_issue = {
                "errorType": "StateChangedDuringRecheck",
                "previouslyVerifiedProperties": changed_after_verification,
            }
            break
        if not preserved or "unverified" not in results.values():
            break
        last_revision = after["bot"]["version"]
    writes_disabled = not (
        preserved and all(value in {"saved", "failed"} for value in results.values())
    )
    write_stop_issue = None
    if not writes_disabled:
        write_stop_issue = _release_pending_write(root)
    writes_disabled = _writes_disabled(root)
    result = {
        "status": "unverified"
        if read_back_issue
        else "saved"
        if preserved and all(value == "saved" for value in results.values())
        else "unfinished",
        "target": plan["target"],
        "agentStudioUrl": plan["agentStudioUrl"],
        "properties": results,
        "preservation": "confirmed" if preserved else "unverified",
        "httpStatus": status_code,
        "transportIssue": transport_issue,
        "requestId": request_id,
        "writesDisabled": writes_disabled,
        "writeStopIssue": write_stop_issue,
        **({"serviceError": service_error} if service_error else {}),
        **({"readBackIssue": read_back_issue} if read_back_issue else {}),
        "localArtifacts": "Unchanged; schema, folders and setup identity are not renamed.",
        "publication": "Not performed for this change.",
        "approval": "Unverified for this change.",
        "employeeVisibility": "Unverified for this change.",
        "packageIcons": "Not checked; validate the applicable service-generated app package separately.",
        "releaseHandoff": {
            "workflow": "Manage ESS releases from ADK",
            "status": "not_started",
            "almFamilyId": plan["target"].get("alm_family_id") or "unverified",
            "publicationRequired": "unverified",
            "destination": "unverified",
            "requiredRole": "unverified",
        },
        "nextAction": (
            "Writes remain disabled. Establish actual Dev draft state, "
            "resolve any preservation issue and complete reviewed recovery. "
            "Keep confirmed saves; no rollback or automatic retry. "
            "Publication and employee visibility are separate and do not "
            "block recovery of this authoring operation."
            if writes_disabled
            else "Dev draft saved and verified. Publication and employee visibility "
            "are separate; no publication, promotion or deployment was performed."
            if all(value == "saved" for value in results.values())
            else "Keep confirmed saves. Recheck failed properties and prepare a new "
            "review only for unapplied changes. No rollback or automatic retry."
        ),
    }
    comparison_results = results
    if read_back_issue:
        comparison_results = (
            {
                field: value
                for field, value in results.items()
                if field not in read_back_issue["properties"]
            }
            if "properties" in read_back_issue
            else {}
        )
    if results.get("name") == "unverified" and observed_state:
        observed_name = observed_state["bot"].get("displayName")
        if isinstance(observed_name, str):
            result["observedName"] = {
                "value": observed_name,
                "verification": (
                    "Latest readable display name, not confirmed as matching the "
                    "approved rename. Do not truncate locally or repeat the write."
                ),
            }
    try:
        result["comparison"] = _saved_comparison(plan, comparison_results, root)
        if "logo" in changes and results["logo"] == "unverified" and observed_state:
            observed_logo = _logo(observed_state["bot"])
            if observed_logo:
                source_matches = _image(observed_logo) == _image(
                    _decode(changes["logo"])
                )
                path = _preview_image(
                    observed_logo, root, plan["reviewId"], "observed-color"
                )
                result["observedLogo"] = {
                    "previewMarkdown": f"![Read-back agent logo]({path.as_uri()})",
                    "preview": str(path),
                    "revision": observed_state["bot"]["version"],
                    "sourceComparison": "matching" if source_matches else "different",
                    "verification": (
                        "A DEV logo was read back for review. Its decoded image matches "
                        "the approved source, but save verification is not complete. "
                        "Do not repeat the write."
                        if source_matches
                        else "A DEV logo was read back for review. Its decoded image "
                        "differs from the original upload. Image processing can explain "
                        "a difference, but the cause is not confirmed. This difference "
                        "alone does not mean the upload failed. Do not repeat the write."
                    ),
                }
    except (OSError, AgentBasicsError) as exc:
        result["presentationIssue"] = (
            f"Could not prepare the saved-logo comparison images: {exc}. "
            "The reported service outcome is unchanged."
        )
    if result.get("comparison", {}).get("logo") or result.get("observedLogo"):
        result["reviewId"] = plan["reviewId"]
        result["completionPreviewRetained"] = True
    if (
        results.get("logo") == "unverified"
        and all(value == "saved" for field, value in results.items() if field != "logo")
        and preserved
        and read_back_issue is None
        and status_code in (200, 201, 204)
        and not transport_issue
        and observed_state
        and observed_state["bot"]["version"] > plan["state"]["bot"]["version"]
        and result.get("observedLogo")
        and not (root / WRITE_STOP_FILE).exists()
    ):
        try:
            record = _record_logo_confirmation(root, plan, observed_state)
        except OSError:
            result["confirmationIssue"] = (
                "ADK could not retain safe logo-confirmation evidence; saves remain paused."
            )
        else:
            result["logoConfirmation"] = {
                "status": "available",
                "requestedProperties": record["requestedProperties"],
            }
            result["nextAction"] = (
                "Finish verification now in this update flow. If verified, ask nothing; "
                "otherwise use the returned confirmation dialog to ask the maker to "
                "check the requested settings in Copilot Studio using agentStudioUrl. "
                "Do not show read-back-image confirmation or a maintainer/resume dialog."
            )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "view",
            "preview",
            "save",
            "cleanup",
            "disable-writes",
            "resume-writes",
            "confirm-logo",
            "validate-package",
            "validate-icons",
        ),
    )
    parser.add_argument("--name")
    parser.add_argument(
        "--logo",
        help="Readable local source image; the service validates authoring input.",
    )
    parser.add_argument(
        "--color",
        help="Same source-logo edit as --logo; validate-icons requires a 192x192 PNG.",
    )
    parser.add_argument(
        "--color32x32",
        help="Local transparent 32x32 color PNG; validate-icons only, not native saving.",
    )
    parser.add_argument(
        "--name-only",
        action="store_true",
        help="View only the current name, without inspecting or previewing images.",
    )
    parser.add_argument("--package", help="Existing service-generated app-package ZIP.")
    parser.add_argument(
        "--quality-gate",
        type=str.casefold,
        choices=tuple(QUALITY_GATES),
        default="dev",
        help="Gate to view. All edits are Dev-only. Default: dev.",
    )
    parser.add_argument(
        "--outline",
        help="Local white-on-transparent 32x32 PNG; validate-icons only, not native saving.",
    )
    parser.add_argument(
        "--approval", help="Exact reviewId explicitly approved by the maker."
    )
    parser.add_argument(
        "--decision",
        choices=("yes", "no"),
        help="Submitted visual answer about the previous logo; confirm-logo only.",
    )
    parser.add_argument("--account")
    parser.add_argument("--select-account", action="store_true")
    args = parser.parse_args(argv)
    root = Path.cwd()
    if args.action != "validate-icons" and (
        args.outline is not None or args.color32x32 is not None
    ):
        parser.error(_INDEPENDENT_ICON_LIMITATION)
    if args.color is not None and args.logo is not None:
        parser.error("--color and --logo name the same source; use only one")
    if (
        args.action in ("preview", "save", "confirm-logo")
        and args.quality_gate != "dev"
    ):
        parser.error(_DEV_ONLY)
    if (args.action == "confirm-logo") != (args.decision is not None):
        parser.error(
            "confirm-logo requires --decision yes|no; other actions do not accept it"
        )
    if args.name_only and args.action != "view":
        parser.error("--name-only is supported only by view")
    if args.action == "validate-package":
        if not args.package:
            parser.error("validate-package requires --package PATH")
        if any(
            value is not None
            for value in (
                args.name,
                args.logo,
                args.color,
                args.outline,
                args.color32x32,
                args.approval,
                args.account,
            )
        ) or (args.select_account or args.quality_gate != "dev"):
            parser.error("validate-package accepts only --package PATH")
    elif args.package is not None:
        parser.error("--package is only supported by validate-package")
    if args.action == "validate-icons":
        if not any(
            value is not None for value in (args.color, args.outline, args.color32x32)
        ):
            parser.error("validate-icons requires --color, --outline or --color32x32")
        if any(
            value is not None
            for value in (args.name, args.logo, args.approval, args.account)
        ) or (args.select_account or args.name_only or args.quality_gate != "dev"):
            parser.error(
                "validate-icons accepts only --color, --outline and --color32x32"
            )
    if args.action == "cleanup" and not args.approval:
        parser.error("cleanup requires --approval REVIEW_ID")
    if args.action in (
        "view",
        "resume-writes",
        "disable-writes",
        "confirm-logo",
    ) and any(
        value is not None for value in (args.name, args.logo, args.color, args.outline)
    ):
        parser.error(f"{args.action} does not accept proposed changes")
    if args.action in ("save", "resume-writes", "confirm-logo") and not args.approval:
        parser.error(f"{args.action} requires the explicitly approved reviewId")
    plan = None
    result: dict[str, Any] = {}
    prefix = "AGENT_BASICS_RESULT_JSON:"
    try:
        if args.action == "validate-icons":
            sources = {}
            for kind, path in (
                ("color", args.color),
                ("outline", args.outline),
                ("color32x32", args.color32x32),
            ):
                if path is not None:
                    sources[kind], _ = _icon_file(path, kind)
            print(
                prefix
                + json.dumps(
                    {
                        "status": "validated",
                        "scope": "provided_local_icon_files_only",
                        "sources": sources,
                        "writeAttempted": False,
                        "publication": "Not performed.",
                        "nativeSaveUnsupported": [
                            kind
                            for kind in ("outline", "color32x32")
                            if kind in sources
                        ],
                    }
                )
            )
            return 0
        if args.action == "validate-package":
            result = validate_package(Path(args.package))
            print(prefix + json.dumps(result))
            return 0
        cleanup_expired(root)
        if args.action == "cleanup":
            cleanup(root, args.approval)
            print(prefix + json.dumps({"status": "cleaned"}))
            return 0
        if args.action == "disable-writes":
            if not (root / WRITE_STOP_FILE).exists():
                disable_writes(root)
            print(
                prefix
                + json.dumps({"status": "writes_disabled", "writesDisabled": True})
            )
            return 0
        if args.action == "save":
            _require_writes_enabled(root)
        target = selected_target(root)
        account_hint = args.account or (
            None if args.select_account else target.get("account")
        )
        _progress("authenticating", message="Complete sign-in if a browser opens.")
        token = authenticate(
            target["tenant_id"],
            target["ring"],
            account_hint=account_hint,
            force_account_selection=args.select_account,
            require_account_identity=bool(account_hint),
        )
        client = AgentBuilderClient(
            target["host"],
            token,
            ring=target["ring"],
            tenant_id=target["tenant_id"],
            api_version=target["api_version"],
        )
        plan = prepare(
            client,
            target,
            name=args.name,
            logo=args.logo,
            color=args.color,
            quality_gate=args.quality_gate,
            name_only=args.name_only,
        )
        if args.action == "save":
            result = save(
                client,
                plan,
                args.approval,
                current_target=selected_target(root),
                root=root,
            )
        elif args.action == "confirm-logo":
            if selected_target(root) != target:
                raise AgentBasicsError(
                    "The selected target changed; saves remain paused."
                )
            result = confirm_logo(
                plan, root, approval=args.approval, decision=args.decision
            )
            if result["status"] != "review_again":
                try:
                    view = review_output(plan, root)
                except OSError:
                    result["presentationIssue"] = (
                        "Could not redisplay the confirmed DEV logo. "
                        "The reported confirmation outcome is unchanged."
                    )
                else:
                    result.update(
                        current=view["current"],
                        reviewId=plan["reviewId"],
                        completionPreviewRetained=True,
                    )
        elif args.action == "resume-writes":
            if args.approval != plan["reviewId"] or selected_target(root) != target:
                result = {
                    "status": "review_again",
                    "reason": "Recovery state changed; writes remain disabled.",
                }
            else:
                (root / WRITE_STOP_FILE).unlink(missing_ok=True)
                (root / WRITE_PENDING_FILE).unlink(missing_ok=True)
                result = {
                    "status": "writes_resumed",
                    "writesDisabled": False,
                    "writeAttempted": False,
                    "nextAction": "Prepare a fresh proposal and obtain approval before any corrective or remaining write.",
                }
        else:
            result = review_output(plan, root)
            if args.action == "view":
                confirmation = logo_confirmation_review(plan, root)
                if confirmation:
                    if selected_target(root) != target:
                        confirmation = {
                            "status": "blocked",
                            "reason": "The selected target changed; saves remain paused.",
                        }
                    result["logoConfirmation"] = (
                        confirm_logo(plan, root)
                        if confirmation["status"] == "verified"
                        else confirmation
                    )
                    if result["logoConfirmation"].get("writeStopIssue"):
                        result["writeStopIssue"] = result["logoConfirmation"][
                            "writeStopIssue"
                        ]
            result["writesDisabled"] = _writes_disabled(root)
        emit_capability_use("agent_basics")
    except (
        AgentBasicsError,
        AgentBuilderError,
        ExistingDASetupError,
        DAProductRegistryError,
        requests.RequestException,
        OSError,
    ) as exc:
        # Service exception messages can contain response bodies and branding.
        result = {
            "status": "blocked",
            "errorType": type(exc).__name__,
            "message": str(exc)
            if isinstance(exc, AgentBasicsError)
            else "Target verification or service access failed. Check the selected environment, maker access and connection; no completion is claimed.",
        }
        if isinstance(exc, AgentBuilderHTTPError):
            result.update(httpStatus=exc.status_code, requestId=exc.request_id)
            if exc.response is not None:
                result["serviceError"] = _service_error(exc.response)
            if exc.status_code == 403:
                result["message"] = (
                    "The service denied access to the selected agent. Confirm the "
                    "selected account and use the verified agent/environment "
                    "access path. Recheck access and current values before a "
                    "fresh review; no completion is claimed."
                )
        result["writesDisabled"] = _writes_disabled(root)
        prefix = "AGENT_BASICS_ERROR_JSON:"
    finally:
        review_id = (
            args.approval
            if args.action in ("save", "resume-writes")
            else (
                plan["reviewId"] if plan and result.get("status") == "blocked" else None
            )
        )
        if (
            review_id
            and _REVIEW_ID.fullmatch(review_id)
            and not result.get("completionPreviewRetained")
        ):
            try:
                cleanup(root, review_id)
            except OSError:
                result["cleanupIssue"] = (
                    "ADK could not remove this review's temporary icon copies. "
                    "Run cleanup again; the reported service outcome is unchanged."
                )
    print(prefix + json.dumps(result, ensure_ascii=True), flush=True)
    return (
        0
        if result["status"]
        in (
            "review",
            "saved",
            "no_change",
            "writes_resumed",
            "logo_verified",
            "logo_confirmed",
            "logo_not_confirmed",
        )
        and not result.get("cleanupIssue")
        and not result.get("writeStopIssue")
        else 2
    )


def _command_worker(argv: list[str]) -> None:
    sys.exit(main(argv))


def run_cli(argv: list[str] | None = None) -> int:
    """Bound the entire command, including authentication and HTTP retry waits."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    action = arguments[0] if arguments else ""
    timeout = SAVE_TIMEOUT_SECONDS if action == "save" else READ_TIMEOUT_SECONDS
    process = multiprocessing.get_context("spawn").Process(
        target=_command_worker, args=(arguments,)
    )
    started = time.monotonic()
    reason = "Timeout"
    try:
        process.start()
        while process.is_alive():
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                break
            process.join(timeout=min(PROGRESS_INTERVAL_SECONDS, remaining))
            if process.is_alive() and time.monotonic() - started < timeout:
                _progress("waiting", elapsedSeconds=int(time.monotonic() - started))
        if not process.is_alive():
            return process.exitcode
    except KeyboardInterrupt:
        reason = "Cancelled"
    finally:
        # A timed-out worker must not continue reading or saving after reporting.
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
        process.close()
    uncertain = action == "save"
    result = {
        "status": "unverified" if uncertain else "blocked",
        "errorType": reason,
        "elapsedSeconds": int(time.monotonic() - started),
        "message": (
            "The command was stopped. The save outcome is unverified; read the "
            "actual saved state and complete reviewed recovery before retrying."
            if uncertain
            else "The command was stopped before completion. No save was attempted. "
            "Check sign-in and the connection before preparing a fresh preview."
        ),
        "writesDisabled": _writes_disabled(Path.cwd()),
    }
    if uncertain:
        result["preservation"] = "unverified"
        result["properties"] = {
            field: "unverified"
            for field, option in (
                ("name", "--name"),
                ("logo", "--logo"),
                ("logo", "--color"),
            )
            if any(arg == option or arg.startswith(option + "=") for arg in arguments)
        }
    else:
        result["writeAttempted"] = False
    print("AGENT_BASICS_ERROR_JSON:" + json.dumps(result), flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(run_cli())
