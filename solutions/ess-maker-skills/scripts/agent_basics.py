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
    _validate_changeset_identity,
)

# A local resource budget, not an asserted AgentBuilder service limit.
MAX_IMAGE_BYTES = 1024 * 1024
PREVIEW_DIRECTORY = Path(".local/agent-basics-preview")
WRITE_STOP_FILE = Path(".local/agent-basics-writes.disabled")
WRITE_PENDING_FILE = Path(".local/agent-basics-write.pending")
_REVIEW_ID = re.compile(r"[0-9a-f]{64}")
_SERVER_FIELDS = {"version", "auditInfo"}
_PREVIEW_FILE = re.compile(r"[0-9a-f]{64}-(color|outline)\.png")


class AgentBasicsError(RuntimeError):
    """A branding request cannot safely continue."""


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


def _png(data: bytes, *, size: int | None = None, outline: bool = False) -> bytes:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise AgentBasicsError(
            "ADK requires a nonempty PNG within its 1 MiB local preview budget. "
            "This is not an AgentBuilder service limit."
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or image.n_frames != 1:
                    raise AgentBasicsError(
                        "Supply a single-frame PNG, not a converted file."
                    )
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
                image.load()
                rgba = image.convert("RGBA")
                pixels = rgba.tobytes()
                if outline:
                    values = list(
                        zip(pixels[::4], pixels[1::4], pixels[2::4], pixels[3::4])
                    )
                    if not any(alpha == 0 for _, _, _, alpha in values) or any(
                        (red, green, blue) != (255, 255, 255)
                        for red, green, blue, alpha in values
                        if alpha
                    ):
                        raise AgentBasicsError(
                            "The 32x32 outline PNG must have a transparent "
                            "background and a nonempty white outline."
                        )
                    if not any(alpha for _, _, _, alpha in values):
                        raise AgentBasicsError(
                            "The outline PNG cannot be entirely transparent."
                        )
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


def _image_file(path: str, *, size: int, outline: bool = False) -> tuple[str, bytes]:
    source = Path(path).expanduser().resolve()
    try:
        with source.open("rb") as stream:
            data = stream.read(MAX_IMAGE_BYTES + 1)
    except OSError as exc:
        raise AgentBasicsError("The selected local PNG cannot be read.") from exc
    _png(data, size=size, outline=outline)
    return str(source), data


def _decode(value: Any) -> bytes:
    if value is None:
        return b""
    if not isinstance(value, str) or len(value) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise AgentBasicsError(
            "The saved icon is unreadable or exceeds the preview budget."
        )
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AgentBasicsError("The saved icon is not valid base64.") from exc


def _teams(bot: dict[str, Any]) -> dict[str, Any]:
    application = bot.get("teamsAppInformation")
    if application is None:
        return {}
    if not isinstance(application, dict):
        raise AgentBasicsError("The saved application icon settings are unreadable.")
    teams = application.get("teams")
    if teams is None:
        return {}
    if not isinstance(teams, dict):
        raise AgentBasicsError("The saved application icon settings are unreadable.")
    return teams


def _logo(bot: dict[str, Any]) -> tuple[bytes, bytes]:
    if "iconBase64" not in bot:
        raise AgentBasicsError(
            "The current logo was not returned; logo editing is unavailable."
        )
    color = _decode(bot["iconBase64"])
    outline = _decode(_teams(bot).get("outlineIcon", ""))
    if color:
        _png(color)
    if outline:
        _png(outline, size=32)
    return color, outline


def _retained_logo_issue(bot: dict[str, Any]) -> str | None:
    if "iconBase64" not in bot:
        return "The current color icon was not returned by the service."
    if bot["iconBase64"] is None:
        return None
    try:
        _png(_decode(bot.get("iconBase64")), size=192)
        outline = _teams(bot).get("outlineIcon")
        if not isinstance(outline, str) or not outline:
            return "The existing outline is missing."
    except AgentBasicsError:
        return (
            "The existing color icon or application metadata could not be "
            "confirmed as safe from service-side icon processing."
        )
    return None


def read_state(
    client: AgentBuilderClient,
    target: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    agent_id = target["agent_id"]
    card = client.get_agent(agent_id)
    if not isinstance(card, dict):
        raise AgentBasicsError("The live agent identity is unreadable.")
    enrolled, realm = _confirm_direct_native_authoring_identity(agent_id, card)
    if enrolled:
        configuration = client.get_dev_configuration(agent_id)
        if not isinstance(configuration, dict):
            raise AgentBasicsError("The live Dev configuration is unreadable.")
        schema, _, realm = _confirm_dev(agent_id, card, configuration)
        if schema.casefold() != target["schema_name"].casefold():
            raise AgentBasicsError("Dev configuration and selected schema disagree.")
    changeset = client.fetch_components(agent_id)
    if not isinstance(changeset, dict):
        raise AgentBasicsError("The live authoring state is unreadable.")
    schema = _validate_changeset_identity(
        changeset,
        agent_id,
        expected_schema_name=target["schema_name"],
    )
    product = resolve_product_setup(agent_schema_name=schema)
    if not product:
        raise AgentBasicsError(
            "This schema is not a supported ESS product. No write is allowed."
        )
    bot = changeset["bot"]
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
        "product": product["productKey"],
        "qualityGate": realm if enrolled else "unenrolled authoring",
    }


def prepare(
    client: AgentBuilderClient,
    target: dict[str, str],
    *,
    name: str | None = None,
    logo: str | None = None,
    outline: str | None = None,
) -> dict[str, Any]:
    source: dict[str, str] = {}
    desired: dict[str, Any] = {}
    if name is not None:
        desired["displayName"] = validate_name(name)
    supplied: dict[str, bytes] = {}
    if logo:
        source["color"], color = _image_file(logo, size=192)
        supplied["color"] = color
    if outline:
        source["outline"], outline_data = _image_file(outline, size=32, outline=True)
        supplied["outline"] = outline_data
    state, resolved_target = read_state(client, target)
    bot = state["bot"]
    readable_name = isinstance(bot.get("displayName"), str)
    logo_error = None
    try:
        current_logo = _logo(bot)
    except AgentBasicsError as exc:
        current_logo = None
        logo_error = str(exc)
    if "displayName" in desired and not readable_name:
        raise AgentBasicsError(
            "The current name is unreadable; name editing is unavailable."
        )
    if supplied and current_logo is None:
        raise AgentBasicsError(logo_error)
    if supplied:
        assets = []
        for label, current, size in zip(("color", "outline"), current_logo, (192, 32)):
            data = supplied.get(label, current)
            try:
                _png(data, size=size, outline=label == "outline")
            except AgentBasicsError as exc:
                raise AgentBasicsError(
                    f"Supply a valid {label} PNG; the existing asset cannot "
                    "be retained for this logo change."
                ) from exc
            assets.append(base64.b64encode(data).decode("ascii"))
        desired["logo"] = tuple(assets)
    changes = {}
    if "displayName" in desired and desired["displayName"] != bot["displayName"]:
        changes["name"] = desired["displayName"]
    if "logo" in desired:
        desired_logo = tuple(_decode(value) for value in desired["logo"])
        if tuple(_png(value) if value else b"" for value in desired_logo) != tuple(
            _png(value) if value else b"" for value in current_logo
        ):
            changes["logo"] = desired["logo"]
    icon_processing_risk = (
        _retained_logo_issue(bot)
        if "name" in changes and "logo" not in changes
        else None
    )
    review_id = _digest(
        {
            "target": resolved_target,
            "state": state,
            "desired": desired,
            "sources": source,
            "serviceIconProcessingRisk": icon_processing_risk,
        }
    )
    return {
        "reviewId": review_id,
        "target": resolved_target,
        "state": state,
        "desired": desired,
        "changes": changes,
        "sources": source,
        "currentLogo": current_logo,
        "logoError": logo_error,
        "serviceIconProcessingRisk": icon_processing_risk,
    }


def review_output(plan: dict[str, Any], root: Path) -> dict[str, Any]:
    bot = plan["state"]["bot"]
    current: dict[str, Any] = {
        "name": bot.get("displayName")
        if isinstance(bot.get("displayName"), str)
        else None,
        "logo": "unavailable" if plan["currentLogo"] is None else "confirmed",
        "logoIssue": plan["logoError"],
    }
    if plan["currentLogo"]:
        directory = root / PREVIEW_DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        for label, data in zip(("color", "outline"), plan["currentLogo"]):
            if data:
                path = directory / f"{plan['reviewId']}-{label}.png"
                path.write_bytes(data)
                current[f"{label}Preview"] = str(path.resolve())
    return {
        "status": "review" if plan["changes"] else "no_change",
        "reviewId": plan["reviewId"],
        "target": plan["target"],
        "current": current,
        "proposed": {
            "name": plan["desired"].get("displayName"),
            "logoSources": plan["sources"],
        },
        "changedProperties": list(plan["changes"]),
        "serviceIconProcessingRisk": plan["serviceIconProcessingRisk"],
        "serviceIconProcessingWarning": (
            "The existing save API may resize or re-encode the color icon and "
            "clear outlineIcon and colorIcon, even though ADK sends the existing "
            "logo fields unchanged. Approve this possible side effect separately "
            "before saving. No replacement images are required. Read-back will "
            "verify the rename and report any logo changes."
            if plan["serviceIconProcessingRisk"]
            else None
        ),
        "retained": (
            "Unrequested fields are sent unchanged, but existing-logo preservation "
            "cannot be guaranteed; review serviceIconProcessingWarning. "
            "Instructions, schema, product and workspace identity must be retained."
            if plan["serviceIconProcessingRisk"]
            else "All unrequested properties, instructions, schema, product and workspace identity."
        ),
        "localArtifacts": "No agent files or setup display labels changed.",
        "publication": "Not performed; approval and employee visibility are unverified.",
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
        if "logo" in changes:
            item.pop("iconBase64", None)
            teams = _teams(item)
            teams.pop("outlineIcon", None)
            application = item.get("teamsAppInformation")
            if isinstance(application, dict):
                if application.get("teams") in ({}, None):
                    application.pop("teams", None)
                if not application:
                    item.pop("teamsAppInformation")
            elif application is None:
                item.pop("teamsAppInformation", None)
    return (
        previous == current
        and before["botComponentChanges"] == after["botComponentChanges"]
    )


def _changed_logo_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    previous_teams, current_teams = _teams(before), _teams(after)
    missing = object()
    return [
        path
        for path, previous, current in (
            ("iconBase64", before, after),
            (
                "teamsAppInformation.teams.outlineIcon",
                previous_teams,
                current_teams,
            ),
            ("teamsAppInformation.teams.colorIcon", previous_teams, current_teams),
        )
        if previous.get(path.rsplit(".", 1)[-1], missing)
        != current.get(path.rsplit(".", 1)[-1], missing)
    ]


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
    accept_service_icon_processing: bool = False,
) -> dict[str, Any]:
    """Save a freshly prepared plan; the CLI always prepares again after approval."""
    reviewed_target = {
        key: value
        for key, value in plan["target"].items()
        if key not in {"product", "qualityGate"}
    }
    if approval != plan["reviewId"] or current_target != reviewed_target:
        return {
            "status": "review_again",
            "reason": "Target, proposal or reviewed state changed; no write.",
        }
    changes = plan["changes"]
    if not changes:
        return {"status": "no_change", "properties": {}, "writeAttempted": False}
    _require_writes_enabled(root)
    bot = copy.deepcopy(plan["state"]["bot"])
    icon_processing_risk = (
        _retained_logo_issue(bot)
        if "name" in changes and "logo" not in changes
        else None
    )
    if icon_processing_risk != plan["serviceIconProcessingRisk"]:
        return {
            "status": "review_again",
            "reason": "The reviewed icon-processing risk changed; no write.",
        }
    if icon_processing_risk and not accept_service_icon_processing:
        return {
            "status": "review_again",
            "reason": "Explicit approval of possible service-side icon processing is required; no write.",
            "serviceIconProcessingRisk": icon_processing_risk,
        }
    if "name" in changes:
        bot["displayName"] = changes["name"]
    if "logo" in changes:
        bot["iconBase64"] = changes["logo"][0]
        if bot.get("teamsAppInformation") is None:
            bot["teamsAppInformation"] = {}
        application = bot["teamsAppInformation"]
        if application.get("teams") is None:
            application["teams"] = {}
        application["teams"]["outlineIcon"] = changes["logo"][1]

    # BotEntity.version is enforced by CreateBotEntityTransaction, independently
    # of component changeToken. Never strip it or retry this PUT automatically.
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
            "reason": "Protected metadata save conflicted; refresh and review again.",
            "httpStatus": status_code,
            "requestId": request_id,
            "writesDisabled": _writes_disabled(root),
            "writeStopIssue": write_stop_issue,
        }
    results = {field: "unverified" for field in changes}
    try:
        after, _ = read_state(client, current_target)
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
    if "name" in changes:
        if later_revision and observed.get("displayName") == changes["name"]:
            results["name"] = "saved"
        elif status_code is not None and 400 <= status_code < 500:
            results["name"] = "failed"
    if "logo" in changes:
        try:
            actual_logo = _logo(observed)
            expected_logo = tuple(_decode(value) for value in changes["logo"])
            same = tuple(
                _png(value) if value else b"" for value in actual_logo
            ) == tuple(_png(value) for value in expected_logo)
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
    logo_preservation = "not_applicable"
    changed_logo_fields = None
    if "logo" not in changes:
        try:
            changed_logo_fields = _changed_logo_fields(plan["state"]["bot"], observed)
            logo_preservation = "changed" if changed_logo_fields else "confirmed"
        except AgentBasicsError:
            logo_preservation = "unverified"
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
        "logoPreservation": logo_preservation,
        "changedLogoFields": changed_logo_fields,
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
    parser.add_argument("--logo", help="Local 192x192 color PNG, at most 1 MiB.")
    parser.add_argument(
        "--outline", help="Local 32x32 white/transparent PNG, at most 1 MiB."
    )
    parser.add_argument(
        "--approval", help="Exact reviewId explicitly approved by the maker."
    )
    parser.add_argument(
        "--accept-service-icon-processing",
        action="store_true",
        help="For save only, confirm separate maker approval of the reviewed icon-processing risk.",
    )
    parser.add_argument("--account")
    parser.add_argument("--select-account", action="store_true")
    args = parser.parse_args(argv)
    root = Path.cwd()
    if args.accept_service_icon_processing and args.action != "save":
        parser.error("--accept-service-icon-processing is only valid for save")
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
        token = authenticate(
            target["tenant_id"],
            target["ring"],
            account_hint=args.account,
            force_account_selection=args.select_account,
        )
        client = AgentBuilderClient(
            target["host"],
            token,
            ring=target["ring"],
            tenant_id=target["tenant_id"],
            api_version=target["api_version"],
        )
        plan = prepare(
            client, target, name=args.name, logo=args.logo, outline=args.outline
        )
        if args.action == "save":
            result = save(
                client,
                plan,
                args.approval,
                current_target=selected_target(root),
                root=root,
                accept_service_icon_processing=args.accept_service_icon_processing,
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
    print(prefix + json.dumps(result, ensure_ascii=True))
    return (
        0
        if result["status"] in ("review", "saved", "no_change", "writes_resumed")
        and not result.get("cleanupIssue")
        and not result.get("writeStopIssue")
        else 2
    )


if __name__ == "__main__":
    sys.exit(main())
