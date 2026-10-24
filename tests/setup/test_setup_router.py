# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural guards for DA-only Workday Connect ownership and routing."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_CONNECT = _SOLUTION / "src" / "skills" / "connect"
_CONNECT_STEP1 = _SOLUTION / "src" / "skills" / "connect" / "step1.md"
_CONNECT_SKILL = _SOLUTION / "src" / "skills" / "connect" / "SKILL.md"
_SERVICENOW_MESSAGE = (
    "Guided ServiceNow setup is not yet available in ADK. You can configure the "
    "ServiceNow connection manually in Copilot Studio or contact admin."
)
_OLD_PROMPT = _SOLUTION / ".github" / "prompts" / "setup-workday.prompt.md"
_WORKDAY_PROVIDER_DIR = _SOLUTION / "src" / "skills" / "connect" / "workday"


def test_connect_workday_routes_only_da_to_controller() -> None:
    registration = json.loads(
        (_WORKDAY_PROVIDER_DIR / "integration.json").read_text(encoding="utf-8")
    )
    entry = (_WORKDAY_PROVIDER_DIR / registration["entryDoc"]).read_text(
        encoding="utf-8"
    )

    assert registration["availability"] == "available"
    assert "src/skills/connect/workday/SKILL.md" in entry
    assert "--checkpoint WD-PKG-001" not in entry
    assert "WD-DA-PKG-001" in entry
    assert "main-ca" in entry
    assert "Stop without running package checks" in entry
    assert "ESS IT Agent isn't supported" in entry
    assert "This branch supports DA agents only" in entry


def test_direct_workday_requests_automatically_prepare_missing_setup_at_entry() -> None:
    instructions = " ".join(
        (_SOLUTION / ".github" / "copilot-instructions.md").read_text(encoding="utf-8").split()
    )
    prompt = " ".join(
        (_SOLUTION / ".github" / "prompts" / "connect.prompt.md").read_text(encoding="utf-8").split()
    )
    alias = " ".join(
        (_SOLUTION / ".github" / "prompts" / "connect-workday.prompt.md").read_text(encoding="utf-8").split()
    )
    entry = " ".join(
        (_WORKDAY_PROVIDER_DIR / "entry.md").read_text(encoding="utf-8").split()
    )

    assert "or explicitly asked to **connect Workday**" in instructions
    assert "proceed with `src/skills/connect/SKILL.md` even when setup is missing" in instructions
    assert "Do not show the setup-required Message block" in instructions
    assert "Missing setup does not stop integration selection" in prompt
    assert "type `/setup` to set up your environment" not in prompt
    assert "apply provider availability before following that provider's entry point" in prompt
    assert "with `workday` supplied as the selected integration" in alias
    assert "I'll prepare your agent workspace first, then continue connecting Workday." in entry
    assert "Immediately read `src/skills/foundation-setup/SKILL.md`" in entry
    assert "in the same invocation" in entry
    assert "If they are already satisfied, skip Setup entirely even when `connect_ready` is false" in entry
    assert "product boundaries below before invoking Setup" in entry
    assert "Do not create Workday state" in entry
    assert "If setup is blocked, cancelled, or exited" in entry
    assert "reread both local configuration files and reapply" in entry
    assert "without showing the integration menu again" in entry
    assert "instead of entering an automatic Setup loop" in entry
    assert "Run `/setup` or select the intended agent first" not in entry
    assert "Do not invoke Setup between Workday phases or after Workday completion" in entry


def test_integration_preparation_returns_at_verified_workspace_boundary() -> None:
    foundation_dir = _SOLUTION / "src" / "skills" / "foundation-setup"
    foundation = " ".join(
        (foundation_dir / "SKILL.md").read_text(encoding="utf-8").split()
    ).split("## Prepare the workspace for an integration", 1)[1].split("## Start", 1)[0]

    assert "`steps.SETUP-07.state: \"done\"`" in foundation
    assert "canonical workspace evidence" in foundation
    assert "schema_version: 4" in foundation
    assert "Preserve the recorded workspace Dev identity" in foundation
    assert "even when `connect_ready` is false" in foundation
    assert "without asking the maker to select that option" in foundation
    assert "Reuse a retained verified maker rather than repeating account selection" in foundation
    assert "use the normal setup questions and authorization controls" in foundation
    assert "Return to the caller's entry point in this same invocation" in foundation
    assert "takes precedence over the usual post-attachment readiness-check" in foundation
    assert "Do not wait for `connect_ready: true`" in foundation
    assert "blocked, cancelled, or exited" in foundation
    assert "Ordinary standalone `/setup` still runs its full readiness and completion behavior" in foundation
    assert "Resume after an integration completes" not in foundation
    for guide in ("da-existing-dev.md", "da-mos-starter.md", "da-prod-to-dev.md", "da-alm-import.md"):
        text = " ".join((foundation_dir / guide).read_text(encoding="utf-8").split())
        assert "integration's entry-only preparation request" in text, guide
        assert "parent skill" in text, guide
        assert "return to the retained caller" in text.casefold(), guide


def test_connect_route_precedes_setup_probe_and_terminal_welcome() -> None:
    instructions = (_SOLUTION / ".github" / "copilot-instructions.md").read_text(
        encoding="utf-8"
    )
    routes, gate = instructions.split("### Setup gate for all other requests", 1)
    normalized_routes = " ".join(routes.split())
    normalized_gate = " ".join(gate.split())

    assert "Route Before Checking Setup" in routes
    assert "Use both the user's message and the invoked command prompt" in normalized_routes
    assert "do not first probe setup metadata" in normalized_routes
    assert "proceed with `src/skills/connect/SKILL.md` even when setup is missing" in normalized_routes
    assert "For `/connect workday`, retain `workday` as the selected integration" in normalized_routes
    assert "**STOP.**" not in routes
    assert "Hey! Welcome to the ESS Maker Kit." not in routes
    assert "Only when no setup-independent route above matches" in normalized_gate
    assert "try to read `.local/setup/config.json`" in normalized_gate
    assert "**STOP.**" in gate
    assert "Hey! Welcome to the ESS Maker Kit." in gate
    assert "YOUR VERY FIRST ACTION on every new conversation" not in instructions


def test_clean_workspace_handoff_handles_missing_metadata_at_each_entry() -> None:
    prompt = " ".join(
        (_SOLUTION / ".github" / "prompts" / "connect.prompt.md").read_text(encoding="utf-8").split()
    )
    alias = " ".join(
        (_SOLUTION / ".github" / "prompts" / "connect-workday.prompt.md").read_text(encoding="utf-8").split()
    )
    entry = " ".join((_WORKDAY_PROVIDER_DIR / "entry.md").read_text(encoding="utf-8").split())
    foundation = " ".join(
        (_SOLUTION / "src" / "skills" / "foundation-setup" / "SKILL.md").read_text(encoding="utf-8").split()
    ).split("## Prepare the workspace for an integration", 1)[1].split("## Start", 1)[0]

    assert "Read that router before probing `.local` metadata" in prompt
    assert "Route before probing `.local` metadata" in alias
    assert "check whether canonical `.local/setup/config.json` exists before reading it" in entry
    assert "`Path does not exist` read result is expected unprepared state" in entry
    assert "Do not treat access-denied or malformed-file errors as absence" in entry
    assert "already-known unsupported-product boundary" in entry
    assert "If `.local` or either file is absent" in foundation
    assert "continue normal Setup target resolution in this invocation" in foundation
    assert "recreate deleted metadata by guessing old state" in foundation
    assert "Unreadable or malformed files still require supported state recovery" in foundation


def test_guided_servicenow_requests_stop_before_provider_actions() -> None:
    registration = json.loads(
        (_CONNECT / "servicenow" / "integration.json").read_text(encoding="utf-8")
    )
    assert registration["availability"] == "unavailable"
    assert registration["unavailableMessage"] == _SERVICENOW_MESSAGE
    assert "snow" in registration["aliases"]
    assert "entryDoc" not in registration and "statusDoc" not in registration
    skill = " ".join(_CONNECT_SKILL.read_text(encoding="utf-8").split())
    assert "repair requests, follow-ups, and saved-state resume" in skill
    route = _CONNECT_STEP1.read_text(encoding="utf-8")
    dispatch = route.split("## 1.3", 1)[1]
    assert dispatch.index("STOP before provider") < dispatch.index(
        "emit_capability.py"
    )
    assert "state, credentials, telemetry, MCP, or retained steps" in dispatch
    assert "Do not load `entryDoc`" in dispatch


def test_connect_menus_and_callers_use_the_guided_boundary() -> None:
    route = _CONNECT_STEP1.read_text(encoding="utf-8")
    assert "menu from `available` registrations only" in route
    assert "go directly to 1.3 without asking" in route
    assert "including unavailable ones" in route
    assert "before any\nearlier conversation selection" in route
    instructions = (_SOLUTION / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    triggers = instructions.split("**Trigger phrases for connect:**", 1)[1].split(
        "**Trigger phrases for troubleshooting:**", 1
    )[0]
    assert "servicenow" not in triggers.casefold()
    assert "Wait for the user and try again" in route
    assert "Never fall back to a provider automatically" in route


def test_generic_connect_guidance_has_no_provider_specific_content() -> None:
    registrations = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in _CONNECT.glob("*/integration.json")
    ]
    assert registrations
    for guide in _CONNECT.glob("*.md"):
        text = guide.read_text(encoding="utf-8")
        for registration in registrations:
            assert not re.search(
                rf"\b{re.escape(registration['id'])}\b", text, re.IGNORECASE
            ), guide
        for provider_detail in (".local/connect/", "gptagent_", "WD-DA-PKG", "main-ca"):
            assert provider_detail not in text, guide


def test_provider_registrations_have_unambiguous_names_and_safe_documents() -> None:
    registrations = sorted(_CONNECT.glob("*/integration.json"))
    assert registrations
    owners: dict[str, str] = {}
    for path in registrations:
        registration = json.loads(path.read_text(encoding="utf-8"))
        provider_id = registration["id"]
        assert re.fullmatch(r"[a-z][a-z0-9-]*", provider_id)
        assert provider_id == path.parent.name
        assert isinstance(registration["description"], str)
        assert registration["description"].strip()
        assert isinstance(registration["aliases"], list)
        for name in (
            provider_id, registration["displayName"], *registration["aliases"]
        ):
            assert isinstance(name, str) and name.strip()
            assert owners.setdefault(name.casefold(), provider_id) == provider_id
        assert registration["availability"] in {"available", "unavailable"}
        if registration["availability"] == "unavailable":
            assert registration["unavailableMessage"].strip()
            continue
        assert "entryDoc" in registration
        for field in ("entryDoc", "statusDoc"):
            if field not in registration:
                continue
            relative = PurePosixPath(registration[field])
            assert not relative.is_absolute() and ".." not in relative.parts
            document = (path.parent / Path(*relative.parts)).resolve()
            assert document.is_relative_to(path.parent.resolve())
            assert document.is_file()


def test_flightcheck_and_docs_keep_servicenow_setup_manual() -> None:
    text = (_SOLUTION / "src" / "skills" / "flightcheck" / "SKILL.md").read_text(encoding="utf-8")
    fixes = text.split("### 3c", 1)[1].split("### 3d", 1)[0]
    assert "Missing Workday connection" in fixes and "Missing Workday/ServiceNow" not in fixes
    readme = (_SOLUTION / "README.md").read_text(encoding="utf-8")
    assert _SERVICENOW_MESSAGE in " ".join(readme.split())
    assert "/connect servicenow" not in readme


def test_retired_setup_is_removed_without_removing_foundation() -> None:
    skills = _SOLUTION / "src" / "skills"
    assert not (skills / "setup").exists()
    assert (skills / "foundation-setup" / "SKILL.md").is_file()
    prompt = (_SOLUTION / ".github" / "prompts" / "setup.prompt.md").read_text(
        encoding="utf-8"
    )
    assert "src/skills/foundation-setup/SKILL.md" in prompt


def test_active_skill_guides_do_not_reference_retired_setup() -> None:
    for guide in (_SOLUTION / "src" / "skills").rglob("*.md"):
        assert "src/skills/setup/" not in guide.read_text(encoding="utf-8"), guide


def test_retired_workday_entry_points_remain_absent() -> None:
    assert not _OLD_PROMPT.exists()
    assert (_WORKDAY_PROVIDER_DIR / "SKILL.md").is_file()
    assert not (_WORKDAY_PROVIDER_DIR / "contract.json").exists()
    assert not (_WORKDAY_PROVIDER_DIR / "cea").exists()
    assert not (_WORKDAY_PROVIDER_DIR / "da").exists()
    assert not list(_WORKDAY_PROVIDER_DIR.glob("step*.md"))
