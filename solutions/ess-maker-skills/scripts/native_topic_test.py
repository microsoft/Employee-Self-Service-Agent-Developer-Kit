# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Inspect and browser-test a saved native fixed-response topic without mutations."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import uuid

import requests

from agentbuilder import AgentBuilderClient, AgentBuilderError, canonical_json
from drive_surface import DriveResult, DriveSurface
from reply_signal import ReplySignal, classify_reply_signal, looks_like_error
from setup_existing_da import _expanded_literal_activity, connect_selected_dev_workspace


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected an object in the saved test evidence.")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _error_facts(error: BaseException) -> dict[str, Any]:
    result: dict[str, Any] = {"type": type(error).__name__, "message": str(error)}
    cause = error.__cause__ or (
        error.__context__ if not error.__suppress_context__ else None
    )
    if cause is not None:
        result["cause"] = _error_facts(cause)
    return result


def _evidence_path(root: Path, value: Path) -> Path:
    path = (value if value.is_absolute() else root / value).resolve()
    base = (root / ".local" / "topic-tests").resolve()
    if not base.is_relative_to(root) or path == base or not path.is_relative_to(base):
        raise ValueError("Keep test evidence inside this workspace's .local/topic-tests folder.")
    return path


def _new_output(root: Path, value: Path | None, operation: str) -> Path:
    if value is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        value = Path(".local") / "topic-tests" / f"{operation}-{stamp}-{uuid.uuid4().hex[:8]}"
    output = _evidence_path(root, value)
    output.mkdir(parents=True, exist_ok=False)
    return output


def _identity(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "environment": {
            key: target["environment"][key]
            for key in ("id", "tenantId", "ring", "powerPlatformApiEndpoint", "apiVersion")
        },
        "agent": {
            key: target["agent"][key]
            for key in ("id", "schemaName", "realm")
        },
    }


def _components(client: AgentBuilderClient, target: dict[str, Any]) -> dict[str, dict[str, Any]]:
    changes = client.fetch_components(target["agent"]["id"]).get("botComponentChanges")
    if not isinstance(changes, list):
        raise ValueError("Native read did not return component changes.")
    result = {}
    for change in changes:
        component = change.get("component") if isinstance(change, dict) else None
        if not isinstance(component, dict):
            raise ValueError("Native read returned an unsupported component change.")
        if not isinstance(component.get("id"), str):
            raise ValueError("Native read returned a component without a supported identity.")
        component_id = str(uuid.UUID(component["id"]))
        if component_id in result:
            raise ValueError("Native read returned duplicate component identities.")
        result[component_id] = component
    return result


def literal_response(component: dict[str, Any]) -> tuple[str, list[str]]:
    """Accept only a literal SendActivity followed by EndDialog."""
    dialog = component.get("dialog") or {}
    if not isinstance(dialog, dict):
        raise ValueError("Unsupported native dialog shape.")
    begin = dialog.get("beginDialog") or {}
    if not isinstance(begin, dict):
        raise ValueError("Unsupported native trigger shape.")
    actions = begin.get("actions") or []
    if (
        component.get("$kind") != "DialogComponent"
        or dialog.get("$kind") != "AdaptiveDialog"
        or set(dialog) - {"$kind", "modelDescription", "beginDialog"}
        or begin.get("$kind") != "OnRecognizedIntent"
        or set(begin) - {"$kind", "id", "intent", "actions"}
        or not isinstance(actions, list)
        or any(not isinstance(action, dict) for action in actions)
        or [action.get("$kind") for action in actions] != ["SendActivity", "EndDialog"]
        or set(actions[0]) - {"$kind", "id", "activity"}
        or set(actions[1]) - {"$kind", "id"}
    ):
        raise ValueError(
            "Unsupported topic: only a native response-only dialog is supported. "
            "No browser message was sent."
        )
    intent = begin.get("intent") or {}
    if not isinstance(intent, dict):
        raise ValueError("Unsupported native intent shape.")
    triggers = intent.get("triggerQueries")
    response = _expanded_literal_activity(actions[0].get("activity"))
    if (
        intent.get("$kind") != "Intent"
        or set(intent) - {"$kind", "triggerQueries"}
        or not isinstance(triggers, list) or not triggers
        or any(not isinstance(text, str) or not text.strip() for text in triggers)
        or response is None
    ):
        raise ValueError("Unsupported dynamic content, cards or trigger configuration.")
    if not response.strip():
        raise ValueError("The saved topic has no non-empty literal response.")
    return response, triggers


def _snapshot(components: dict[str, dict[str, Any]], component_id: str) -> dict[str, Any]:
    return {
        "component": components.get(component_id),
        "componentHashes": {key: _hash(value) for key, value in components.items()},
    }


def _drift(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": sorted(key for key in before.keys() & after.keys() if before[key] != after[key]),
    }


def assess(
    capture: DriveResult | None,
    expected: str,
    native_drift: dict[str, list[str]] | None,
) -> dict[str, Any]:
    signal = (
        classify_reply_signal(capture.reply_text, timed_out=capture.timed_out)
        if capture is not None else None
    )
    assessed = capture is not None and signal is ReplySignal.OK and not capture.had_card
    exact = capture.reply_text == expected if capture is not None and assessed else None
    unchanged = not any(native_drift.values()) if native_drift is not None else None
    return {
        "signal": signal.value if signal is not None else None,
        "errorShaped": looks_like_error(capture.reply_text) if capture is not None else None,
        "checks": {
            "savedResponse": {
                "requirementType": "requiredOutcome", "requirementId": "saved-response",
                "assessed": assessed, "met": exact, "operator": "exact",
            },
            "nativeComponentsUnchanged": {
                "requirementType": "invariant", "requirementId": "native-components-unchanged",
                "assessed": unchanged is not None, "met": unchanged, "drift": native_drift,
            },
        },
        "outcome": (
            "blocked" if capture is None
            else "passed" if exact is True and unchanged is True
            else "incomplete" if unchanged is None
            else "unsupported_reply" if capture.had_card and signal is ReplySignal.OK
            else signal.value if signal is not None and signal is not ReplySignal.OK
            else "failed"
        ),
    }


def _exercise(
    args: argparse.Namespace,
    root: Path,
    client: AgentBuilderClient,
    target: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    from daga_chat_driver import DagaChatDriver, PlaywrightError, validate_studio_url

    if args.operation == "run":
        inspection = _read(_evidence_path(root, args.inspection))
        if inspection.get("schemaVersion") != 1 or inspection.get("operation") != "inspect":
            raise ValueError("Use an inspection produced by this native-topic test tool.")
        component_id = str(uuid.UUID(inspection["component"]["id"]))
        prompt = args.prompt
        expected_target = inspection["target"]
        expected_component = inspection["component"]
        cdp, url = args.cdp, args.url
        original = None
    else:
        original = _evidence_path(root, args.previous)
        execution = _read(original / "execution.json")
        if execution.get("schemaVersion") != 1 or execution.get("operation") != "run":
            raise ValueError("Observe the original run, not a replacement send or observation.")
        inspection = _read(original / "inspection.json")
        component_id = str(uuid.UUID(inspection["component"]["id"]))
        prompt = execution["prompt"]
        expected_target = execution["target"]
        expected_component = inspection["component"]
        cdp, url = execution["cdp"], execution["url"]
    if expected_target != _identity(target):
        raise ValueError("The inspection or original run belongs to another native target.")
    before = _components(client, target)
    component = before.get(component_id)
    if component is None or component != expected_component:
        raise ValueError("The selected native topic changed. Inspect it and approve its content again.")
    expected, triggers = literal_response(component)
    if prompt not in triggers:
        raise ValueError("This bounded test accepts only an explicitly saved trigger phrase.")
    if component.get("state") != "Active" or component.get("status") != "Active":
        raise ValueError("The selected topic is inactive; testing does not activate or publish it.")
    url = validate_studio_url(url, target)
    driver = DagaChatDriver(cdp=cdp, expected_url=url)
    output = _new_output(root, args.output, args.operation)
    _write(output / "inspection.json", inspection)
    baseline = _snapshot(before, component_id)
    _write(output / "native-before.json", baseline)
    _write(output / "case.json", {
        "testCaseId": "native-fixed-response",
        "description": "The selected native fixed-response topic returns its approved saved response.",
        "requiredOutcomes": [{
            "id": "saved-response",
            "description": "The approved saved trigger returns the approved saved literal response.",
        }],
        "invariants": [{
            "id": "native-components-unchanged",
            "description": "Testing leaves the selected native agent's components unchanged.",
        }],
    })
    capture = None
    error = None
    surface = DriveSurface(driver)
    try:
        surface.start()
        if args.operation == "run":
            boundary = driver.prepare()
            _write(output / "execution.json", {
                "schemaVersion": 1, "operation": "run",
                "target": _identity(target), "prompt": prompt,
                "expectation": {"operator": "exact", "text": expected},
                "cdp": cdp, "url": url, "boundary": boundary,
                "submissionMayHaveOccurred": True,
                "isolation": "Existing conversation; no reset or reload.",
            })
            capture = surface.drive(prompt, timeout_s=args.timeout)
        else:
            boundary = dict(execution["boundary"])
            capture_path = original / "capture.json"
            if capture_path.exists():
                boundary["expectedResponseId"] = _read(capture_path)["observation"].get("responseId")
            elif (original / "result.json").exists():
                boundary["expectedResponseId"] = (
                    _read(original / "result.json").get("observation", {}).get("responseId")
                )
            _write(output / "execution.json", {
                "schemaVersion": 1, "operation": "observe",
                "originalRun": str(original), "target": _identity(target),
                "prompt": prompt, "cdp": cdp, "url": url,
                "expectation": {"operator": "exact", "text": expected},
                "boundary": boundary, "submissionMayHaveOccurred": False,
            })
            capture = driver.observe(prompt, boundary, args.timeout)
        _write(output / "capture.json", {
            "replyText": capture.reply_text, "timedOut": capture.timed_out,
            "bubbles": [{"text": bubble.text, "hadCard": bubble.had_card} for bubble in capture.bubbles],
            "observation": driver.observation(),
        })
        if not capture.timed_out:
            driver.screenshot(output / "current-turn.png")
    except (RuntimeError, PlaywrightError, requests.RequestException, OSError) as exc:
        error = {
            **_error_facts(exc),
            "observation": driver.observation(),
        }
    finally:
        try:
            surface.close()
        except (RuntimeError, PlaywrightError) as exc:
            error = {
                **({"captureError": error} if error else {}),
                "cleanupError": _error_facts(exc),
            }
    drift = None
    try:
        after = _snapshot(_components(client, target), component_id)
        _write(output / "native-after.json", after)
        before_hashes = (
            _read(original / "native-before.json")["componentHashes"]
            if original is not None else baseline["componentHashes"]
        )
        drift = _drift(before_hashes, after["componentHashes"])
    except (AgentBuilderError, requests.RequestException, ValueError) as exc:
        error = {
            **({"captureError": error} if error else {}),
            "nativeReadbackError": _error_facts(exc),
        }
    result = {
        "schemaVersion": 1, "operation": args.operation,
        "target": _identity(target), "componentId": component_id,
        "prompt": prompt, "evidenceDirectory": str(output),
        "observation": driver.observation(),
        **({"originalRun": str(original)} if original is not None else {}),
        **assess(capture, expected, drift),
        "limitations": [
            "Reply equality is not an exact-topic invocation trace.",
            "The existing conversation was not reset; this is not independent discovery evidence.",
            "Cards, workflow diagnostics, backend faults and automatic publication are unsupported.",
        ],
    }
    if error is not None:
        result["error"] = error
        result["outcome"] = "incomplete" if capture is not None else "blocked"
    _write(output / "result.json", result)
    return result, 0 if result["outcome"] == "passed" else 2 if error else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("list", "inspect", "run", "observe"))
    parser.add_argument("--kit-root", type=Path, default=Path.cwd())
    parser.add_argument("--account")
    parser.add_argument("--component-id")
    parser.add_argument("--inspection", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--prompt")
    parser.add_argument("--cdp")
    parser.add_argument("--url")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds.")
    required = {
        "inspect": ("component_id",),
        "run": ("inspection", "prompt", "cdp", "url", "output"),
        "observe": ("previous",),
    }
    for field in required.get(args.operation, ()):
        if getattr(args, field) is None:
            parser.error(f"--{field.replace('_', '-')} is required.")
    try:
        root = args.kit_root.resolve()
        client, target = connect_selected_dev_workspace(root, args.account)
        if args.operation in {"run", "observe"}:
            result, code = _exercise(args, root, client, target)
        else:
            components = _components(client, target)
            if args.operation == "list":
                result = {
                    "operation": "list", "target": _identity(target),
                    "topics": [
                        {key: component.get(key) for key in (
                            "id", "schemaName", "displayName", "state", "status",
                        )}
                        for component in components.values()
                        if component.get("$kind") == "DialogComponent"
                    ],
                }
            else:
                component = components.get(str(uuid.UUID(args.component_id)))
                if component is None:
                    raise ValueError("The selected native topic was not found.")
                response, triggers = literal_response(component)
                output = _new_output(root, args.output, "inspect")
                inspection = {
                    "schemaVersion": 1, "operation": "inspect",
                    "target": _identity(target), "component": component,
                    "response": response, "triggers": triggers,
                }
                _write(output / "inspection.json", inspection)
                result = {
                    "operation": "inspect", "target": _identity(target),
                    "componentId": component["id"], "displayName": component.get("displayName"),
                    "state": component.get("state"), "status": component.get("status"),
                    "response": response, "triggers": triggers,
                    "inspection": str(output / "inspection.json"),
                }
            code = 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (AgentBuilderError, requests.RequestException, ValueError, RuntimeError, OSError, ImportError) as error:
        print(json.dumps({
            "outcome": "blocked", "error": _error_facts(error),
        }, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
