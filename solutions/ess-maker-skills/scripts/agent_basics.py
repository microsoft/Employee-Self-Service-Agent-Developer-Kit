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
from pathlib import Path
from typing import Any

import requests
from PIL import Image, UnidentifiedImageError

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
from da_product_registry import DAProductRegistryError, resolve_product_setup
from publish import _is_native_config, _native_context
from setup_existing_da import (
    ExistingDASetupError,
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
WRITE_STOP_FILE = Path(".local/agent-basics-writes.disabled")
WRITE_PENDING_FILE = Path(".local/agent-basics-write.pending")
_REVIEW_ID = re.compile(r"[0-9a-f]{64}")
_SERVER_FIELDS = {"version", "auditInfo"}
_PREVIEW_FILE = re.compile(r"[0-9a-f]{64}-(color|outline)\.png")


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


def validate_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 30:
        raise AgentBasicsError(
            "Supply a nonblank displayName of at most 30 Unicode characters, "
            "as required by the selected manifest profile. ADK does not trim "
            "or truncate it."
        )
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AgentBasicsError("The displayName must be valid Unicode.") from exc
    return value


def _png(data: bytes, *, size: int | None = None) -> bytes:
    if not data:
        raise AgentBasicsError("Supply a nonempty PNG.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG":
                    raise AgentBasicsError("Supply a PNG.")
                if size is not None and image.size != (size, size):
                    raise AgentBasicsError(
                        f"PNG dimensions must be exactly {size}x{size}."
                    )
                if image.width > 192 or image.height > 192:
                    raise AgentBasicsError(
                        "The current icon exceeds the supported preview dimensions."
                    )
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                if image.n_frames > 1:
                    fingerprint = hashlib.sha256()
                    fingerprint.update(
                        _digest(
                            {
                                "frames": image.n_frames,
                                "loop": image.info.get("loop"),
                                "defaultImage": image.info.get("default_image", False),
                            }
                        ).encode("ascii")
                    )
                    for index in range(image.n_frames):
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
            "The PNG cannot be fully decoded; no write is allowed."
        ) from exc


def _image_file(path: str, *, size: int) -> tuple[str, bytes]:
    source = Path(path).expanduser().resolve()
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise AgentBasicsError("The selected local PNG cannot be read.") from exc
    _png(data, size=size)
    return str(source), data


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
        _png(color)
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
        raise AgentBasicsError("Quality-gate discovery did not identify the Dev source.")
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
        raise AgentBasicsError("The discovered agent does not match the requested gate.")
    configuration = client.get_realm_configuration(agent_id, QUALITY_GATES[quality_gate])
    if not isinstance(configuration, dict):
        raise AgentBasicsError("The quality-gate configuration is unreadable.")
    if _realm_name(configuration.get("realm")) != quality_gate:
        raise AgentBasicsError("The configuration identifies a different quality gate.")
    configured_id = _normalize_guid(
        str(configuration.get("cdsBotId") or ""), "Configured quality-gate agent ID"
    )
    if configured_id.casefold() != agent_id.casefold():
        raise AgentBasicsError("The quality-gate configuration identifies another agent.")
    configured_family = str(configuration.get("grsRepositoryId") or "").strip()
    if configured_family.casefold() != family_id.casefold():
        raise AgentBasicsError("The quality-gate agent belongs to another ALM family.")
    schema = str(
        configuration.get("schemaName") or card.get("schemaName") or ""
    ).strip()
    source_schema = target["schema_name"].casefold()
    if schema.casefold() not in {source_schema, f"{source_schema}_{quality_gate}"}:
        raise AgentBasicsError("The quality-gate schema does not match the selected ESS agent.")
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
    if enrolled:
        _progress("checking_dev_target")
        configuration = client.get_dev_configuration(agent_id)
        if not isinstance(configuration, dict):
            raise AgentBasicsError("The live Dev configuration is unreadable.")
        schema, family_id, realm = _confirm_dev(agent_id, card, configuration)
        if schema.casefold() != target["schema_name"].casefold():
            raise AgentBasicsError("Dev configuration and selected schema disagree.")
    if quality_gate != "dev":
        if not enrolled:
            raise AgentBasicsError("Test and Prod require an ALM-enrolled Dev source.")
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
        **({"alm_family_id": family_id} if enrolled else {}),
        "product": product["productKey"],
        "qualityGate": realm if enrolled else "unenrolled authoring",
    }


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
        raise AgentBasicsError("The current chat name is unreadable; rename is unavailable.")
    configuration = state.get("_realmConfiguration")
    if configuration is not None:
        values = configuration["values"]
        binding = "gptDisplayName" if "gptDisplayName" in values else "botName"
        if values[binding] != component["displayName"]:
            raise AgentBasicsError(
                "The chat name and ALM name binding disagree; refresh before renaming."
            )
    return component


def prepare(
    client: AgentBuilderClient,
    target: dict[str, str],
    *,
    name: str | None = None,
    logo: str | None = None,
    quality_gate: str = "dev",
) -> dict[str, Any]:
    if logo is not None and quality_gate != "dev":
        raise AgentBasicsError(
            "Logo changes are Dev-only. Request a separate name-only change for Test or Prod."
        )
    source: dict[str, str] = {}
    desired: dict[str, Any] = {}
    if name is not None:
        desired["displayName"] = validate_name(name)
    supplied = None
    if logo is not None:
        source["color"], color = _image_file(logo, size=192)
        supplied = color
    state, resolved_target = read_state(client, target, quality_gate=quality_gate)
    bot = state["bot"]
    readable_name = isinstance(bot.get("displayName"), str)
    current_logo = None
    logo_error = None
    if name is None or supplied is not None:
        try:
            current_logo = _logo(bot)
        except AgentBasicsError as exc:
            logo_error = str(exc)
    if "displayName" in desired and not readable_name:
        raise AgentBasicsError(
            "The current name is unreadable; name editing is unavailable."
        )
    gpt = _gpt_component(state) if name is not None else None
    if (
        gpt is not None
        and quality_gate == "dev"
        and gpt["displayName"] != desired["displayName"]
        and (
            not isinstance(state.get("changeToken"), str)
            or not state["changeToken"].strip()
        )
    ):
        raise AgentBasicsError(
            "A component change token is required for a protected chat-name update."
        )
    if supplied is not None and current_logo is None:
        raise AgentBasicsError(logo_error)
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
        if _png(desired_logo) != (_png(current_logo) if current_logo else b""):
            changes["logo"] = desired["logo"]
    review_id = _digest(
        {
            "target": resolved_target,
            "state": state,
            "desired": desired,
            "sources": source,
        }
    )
    return {
        "reviewId": review_id,
        "selection": dict(target),
        "requestedQualityGate": quality_gate,
        "target": resolved_target,
        "state": state,
        "desired": desired,
        "changes": changes,
        "sources": source,
        "currentLogo": current_logo,
        "logoError": logo_error,
    }


def review_output(plan: dict[str, Any], root: Path) -> dict[str, Any]:
    bot = plan["state"]["bot"]
    current: dict[str, Any] = {
        "name": bot.get("displayName")
        if isinstance(bot.get("displayName"), str)
        else None,
    }
    if "displayName" in plan["desired"]:
        current["chatName"] = _gpt_component(plan["state"])["displayName"]
    if "displayName" not in plan["desired"] or plan["sources"]:
        current["logo"] = (
            "unavailable"
            if plan["currentLogo"] is None
            else "confirmed"
            if plan["currentLogo"]
            else "none"
        )
        current["logoIssue"] = plan["logoError"]
    if plan["currentLogo"]:
        directory = root / PREVIEW_DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{plan['reviewId']}-color.png"
        path.write_bytes(plan["currentLogo"])
        current["colorPreview"] = str(path.resolve())
    promoted = plan["requestedQualityGate"] != "dev"
    return {
        "status": "review" if plan["changes"] else "no_change",
        "reviewId": plan["reviewId"],
        "target": plan["target"],
        "current": current,
        "proposed": {
            "name": plan["desired"].get("displayName"),
            **(
                {"chatName": plan["desired"]["displayName"]}
                if "displayName" in plan["desired"]
                else {}
            ),
            "logoSources": plan["sources"],
        },
        "changedProperties": list(plan["changes"]),
        "retained": "Instructions, unrequested non-image settings, schema, product and workspace identity.",
        "localArtifacts": "No agent files or setup display labels changed.",
        "publication": "Not performed; approval and employee visibility are unverified.",
        "concurrencyProtection": (
            "ALM configuration is refreshed before writing and verified afterwards; "
            "the API does not accept a client revision precondition."
            if promoted
            else (
                "BotEntity.version protects the save; GPT name updates also "
                "use the fetched component changeToken."
            )
        ),
    }


def cleanup(root: Path, review_id: str) -> None:
    if not _REVIEW_ID.fullmatch(review_id):
        raise AgentBasicsError("Invalid review identifier.")
    for label in ("color", "outline"):
        (root / PREVIEW_DIRECTORY / f"{review_id}-{label}.png").unlink(missing_ok=True)


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


def _preserved(
    before: dict[str, Any], after: dict[str, Any], changes: dict[str, Any]
) -> bool:
    previous = copy.deepcopy(before["bot"])
    current = copy.deepcopy(after["bot"])
    for item in (previous, current):
        for field in _SERVER_FIELDS:
            item.pop(field, None)
        if "name" in changes:
            item.pop("displayName", None)
        if "name" in changes or "logo" in changes:
            # The platform owns source-icon normalization and derived icon fields.
            item.pop("iconBase64", None)
            application = item.get("teamsAppInformation")
            if isinstance(application, dict):
                teams = application.get("teams")
                if isinstance(teams, dict):
                    teams.pop("outlineIcon", None)
                    teams.pop("colorIcon", None)
                if application.get("teams") in ({}, None):
                    application.pop("teams", None)
                if not application:
                    item.pop("teamsAppInformation")
            elif application is None:
                item.pop("teamsAppInformation", None)
    previous_components = copy.deepcopy(before["botComponentChanges"])
    current_components = copy.deepcopy(after["botComponentChanges"])
    if "name" in changes:
        for state, components in (
            (before, previous_components),
            (after, current_components),
        ):
            gpt = _gpt_component({**state, "botComponentChanges": components})
            for field in ("displayName", *_SERVER_FIELDS):
                gpt.pop(field, None)
    previous_config = copy.deepcopy(before.get("_realmConfiguration"))
    current_config = copy.deepcopy(after.get("_realmConfiguration"))
    if previous_config is not None and current_config is not None and "name" in changes:
        previous_config["values"].pop("botName", None)
        current_config["values"].pop("botName", None)
        previous_config["values"].pop("gptDisplayName", None)
        current_config["values"].pop("gptDisplayName", None)
    return (
        previous == current
        and previous_components == current_components
        and previous_config == current_config
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


def save(
    client: AgentBuilderClient,
    plan: dict[str, Any],
    approval: str,
    *,
    current_target: dict[str, str],
    root: Path,
) -> dict[str, Any]:
    """Save a freshly prepared plan; the CLI always prepares again after approval."""
    if approval != plan["reviewId"] or current_target != plan["selection"]:
        return {
            "status": "review_again",
            "reason": "Target, proposal or reviewed state changed; no write.",
        }
    changes = plan["changes"]
    if not changes:
        return {"status": "no_change", "properties": {}, "writeAttempted": False}
    if "logo" in changes and plan["requestedQualityGate"] != "dev":
        raise AgentBasicsError("Logo changes are Dev-only; no write was attempted.")
    _require_writes_enabled(root)
    bot = copy.deepcopy(plan["state"]["bot"])
    gpt = None
    if "name" in changes:
        bot["displayName"] = changes["name"]
        gpt = _gpt_component(plan["state"])
    if "logo" in changes:
        bot["iconBase64"] = changes["logo"]

    promoted = plan["requestedQualityGate"] != "dev"
    if promoted:
        _progress("refreshing_quality_gate_configuration")
        refreshed, refreshed_target = read_state(
            client, current_target, quality_gate=plan["requestedQualityGate"]
        )
        if refreshed != plan["state"] or refreshed_target != plan["target"]:
            return {
                "status": "review_again",
                "reason": "Quality-gate configuration changed; refresh and review again.",
                "writeAttempted": False,
            }
    # Dev uses the fetched entity revision. Promoted realms require Configure,
    # whose full-replacement values map has no caller-supplied revision field.
    status_code = None
    request_id = None
    transport_issue = False
    try:
        disable_writes(root, pending=True)
    except FileExistsError as exc:
        raise AgentBasicsError(
            "Another save or validation stop disabled writes; no write was attempted."
        ) from exc
    try:
        _progress("saving_approved_changes")
        if promoted:
            values = copy.deepcopy(plan["state"]["_realmConfiguration"]["values"])
            values["botName"] = changes["name"]
            if "gptDisplayName" in values:
                values["gptDisplayName"] = changes["name"]
            response = client.session.request(
                "POST",
                f"{client.host}/copilotstudio/minimalBots/alm/{plan['target']['agent_id']}/configure",
                params={"api-version": client.api_version},
                headers={**client.headers, "Content-Type": "application/json"},
                json={
                    "realm": REALM_NAMES[QUALITY_GATES[plan["requestedQualityGate"]]],
                    "values": values,
                },
                timeout=SAVE_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        elif gpt is not None and gpt["displayName"] != changes["name"]:
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
    try:
        _progress("verifying_saved_changes")
        after, observed_target = read_state(
            client, current_target, quality_gate=plan["requestedQualityGate"]
        )
        if observed_target != plan["target"]:
            raise AgentBasicsError("The quality-gate target changed during save verification.")
        observed_gpt = _gpt_component(after) if "name" in changes else None
    except (
        AgentBuilderError,
        AgentBasicsError,
        ExistingDASetupError,
        DAProductRegistryError,
        requests.RequestException,
    ) as exc:
        issue: dict[str, Any] = {"errorType": type(exc).__name__}
        if isinstance(exc, AgentBuilderHTTPError):
            issue.update(httpStatus=exc.status_code, requestId=exc.request_id)
        return {
            "status": "unverified",
            "properties": results,
            "preservation": "unverified",
            "httpStatus": status_code,
            "requestId": request_id,
            "transportIssue": transport_issue,
            "writesDisabled": True,
            "readBackIssue": issue,
            "nextAction": "Writes remain disabled. Establish actual saved/publication state and complete reviewed recovery before considering a retry. No rollback or blind retry.",
        }
    observed = after["bot"]
    # A cached pre-save read does not prove that an uncertain write failed.
    # Confirm completion only from a later persisted entity revision.
    later_revision = observed["version"] > plan["state"]["bot"]["version"]
    if gpt is not None and observed_gpt is not None:
        if (
            later_revision
            and observed.get("displayName") == changes["name"]
            and observed_gpt["displayName"] == changes["name"]
        ):
            results["name"] = "saved"
        elif (
            status_code is not None
            and 400 <= status_code < 500
            and observed.get("displayName") == plan["state"]["bot"].get("displayName")
            and observed_gpt["displayName"] == gpt["displayName"]
        ):
            results["name"] = "failed"
    if "logo" in changes:
        try:
            actual_logo = _logo(observed)
            expected_logo = _decode(changes["logo"])
            same = (_png(actual_logo) if actual_logo else b"") == _png(expected_logo)
        except AgentBasicsError:
            same = False
        if later_revision and same:
            results["logo"] = "saved"
        elif status_code is not None and 400 <= status_code < 500:
            results["logo"] = "failed"
    try:
        preserved = _preserved(plan["state"], after, changes)
    except AgentBasicsError:
        preserved = False
    writes_disabled = not (
        preserved and all(value in {"saved", "failed"} for value in results.values())
    )
    write_stop_issue = None
    if not writes_disabled:
        write_stop_issue = _release_pending_write(root)
    writes_disabled = _writes_disabled(root)
    return {
        "status": "saved"
        if preserved and all(value == "saved" for value in results.values())
        else "unfinished",
        "target": plan["target"],
        "properties": results,
        "preservation": "confirmed" if preserved else "unverified",
        "httpStatus": status_code,
        "transportIssue": transport_issue,
        "requestId": request_id,
        "writesDisabled": writes_disabled,
        "writeStopIssue": write_stop_issue,
        "localArtifacts": "Unchanged; schema, folders and setup identity are not renamed.",
        "publication": "Not performed for this change.",
        "approval": "Unverified for this change.",
        "employeeVisibility": "Unverified for this change.",
        "nextAction": (
            "Writes remain disabled. Establish actual saved/publication state, "
            "resolve any preservation issue and complete reviewed recovery. "
            "Keep confirmed saves; no rollback or automatic retry."
            if writes_disabled
            else "Keep confirmed saves. Recheck failed properties and prepare a new "
            "review only for unapplied changes. No rollback or automatic retry."
        ),
    }


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
        ),
    )
    parser.add_argument("--name")
    parser.add_argument("--logo", help="Local 192x192 color PNG.")
    parser.add_argument(
        "--quality-gate",
        type=str.casefold,
        choices=tuple(QUALITY_GATES),
        default="dev",
        help="Gate to view or rename; logo changes are Dev-only. Default: dev.",
    )
    parser.add_argument(
        "--outline",
        help="Unsupported: the platform derives outlines from the --logo source.",
    )
    parser.add_argument(
        "--approval", help="Exact reviewId explicitly approved by the maker."
    )
    parser.add_argument("--account")
    parser.add_argument("--select-account", action="store_true")
    args = parser.parse_args(argv)
    root = Path.cwd()
    if args.logo is not None and args.quality_gate != "dev":
        parser.error(
            "Logo changes are Dev-only. Test and Prod accept name-only changes. "
            "No write was attempted."
        )
    if args.outline is not None:
        parser.error(
            "Independent outline customization is not supported. Use --logo "
            "for the source image; the platform derives its outline. "
            "No write was attempted."
        )
    if args.action == "cleanup" and not args.approval:
        parser.error("cleanup requires --approval REVIEW_ID")
    if args.action in ("view", "resume-writes", "disable-writes") and any(
        value is not None for value in (args.name, args.logo, args.outline)
    ):
        parser.error(f"{args.action} does not accept proposed changes")
    if args.action in ("save", "resume-writes") and not args.approval:
        parser.error(f"{args.action} requires the explicitly approved reviewId")
    plan = None
    result: dict[str, Any] = {}
    prefix = "AGENT_BASICS_RESULT_JSON:"
    try:
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
            quality_gate=args.quality_gate,
        )
        if args.action == "save":
            result = save(
                client,
                plan,
                args.approval,
                current_target=selected_target(root),
                root=root,
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
        if review_id and _REVIEW_ID.fullmatch(review_id):
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
        if result["status"] in ("review", "saved", "no_change", "writes_resumed")
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
            for field, option in (("name", "--name"), ("logo", "--logo"))
            if any(arg == option or arg.startswith(option + "=") for arg in arguments)
        }
    else:
        result["writeAttempted"] = False
    print("AGENT_BASICS_ERROR_JSON:" + json.dumps(result), flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(run_cli())
