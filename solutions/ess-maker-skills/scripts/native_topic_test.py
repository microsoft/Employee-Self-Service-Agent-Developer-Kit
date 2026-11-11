# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Inspect topics, prepare a browser, start a new conversation, capture, or activate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
import uuid

import requests

from agentbuilder import AgentBuilderClient, AgentBuilderError, canonical_json
from drive_surface import DriveResult, DriveSurface
from minimalbot_evaluation import ComponentEditError, MinimalBotEvaluationError
from reply_signal import ReplySignal, classify_reply_signal, looks_like_error
from setup_existing_da import _expanded_literal_activity, connect_selected_dev_workspace
from topic_authoring import _native_client


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected an object in the saved test evidence.")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _error_facts(error: BaseException) -> dict[str, Any]:
    result: dict[str, Any] = {"type": type(error).__name__, "message": str(error)}
    evidence = getattr(error, "evidence", None)
    if isinstance(evidence, dict):
        result["evidence"] = evidence
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


def _edge_executable() -> Path:
    if sys.platform == "win32":
        candidates = [
            Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            for name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")
            if (root := os.environ.get(name))
        ]
    elif sys.platform == "darwin":
        candidates = [
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
        ]
    else:
        executable = shutil.which("microsoft-edge") or shutil.which("microsoft-edge-stable")
        candidates = [Path(executable)] if executable else []
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Microsoft Edge is required to prepare a dedicated test browser.")


def _wait_for_browser(
    process: subprocess.Popen, profile: Path, timeout: int,
) -> tuple[str, dict[str, Any]]:
    descriptor = profile / "DevToolsActivePort"
    deadline = time.monotonic() + timeout
    last_error = None
    with requests.Session() as session:
        session.trust_env = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"The dedicated test browser exited with code {process.returncode}."
                )
            if descriptor.is_file():
                lines = descriptor.read_text(encoding="utf-8").splitlines()
                if len(lines) >= 2:
                    port = int(lines[0])
                    if not 1 <= port <= 65535 or not lines[1].startswith("/devtools/browser/"):
                        raise ValueError("The dedicated browser wrote an invalid debug descriptor.")
                    cdp = f"http://127.0.0.1:{port}"
                    try:
                        response = session.get(
                            cdp + "/json/version", timeout=2, allow_redirects=False,
                        )
                    except requests.ConnectionError as error:
                        last_error = error
                    else:
                        if response.status_code != 200:
                            raise RuntimeError(
                                f"Browser metadata returned HTTP {response.status_code}."
                            )
                        metadata = response.json()
                        if (
                            not isinstance(metadata, dict)
                            or metadata.get("webSocketDebuggerUrl")
                            != f"ws://127.0.0.1:{port}{lines[1]}"
                        ):
                            raise RuntimeError(
                                "Browser metadata does not match the dedicated debug descriptor."
                            )
                        return cdp, metadata
            time.sleep(0.1)
    raise TimeoutError("The dedicated test browser did not expose its endpoint in time.") from last_error


def _prepare_browser(
    args: argparse.Namespace, root: Path, target: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    from daga_chat_driver import validate_studio_url

    url = validate_studio_url(args.url, target)
    output = _new_output(root, args.output, "prepare-browser")
    result: dict[str, Any] = {
        "operation": "prepare-browser", "target": _identity(target),
        "outcome": "blocked", "url": url, "output": str(output),
        "humanReadinessConfirmed": False, "sendAttempted": False,
        "launchAttempted": False,
    }
    evidence_errors = []
    process = None

    def record(name: str) -> None:
        try:
            _write(output / name, result)
        except OSError as error:
            evidence_errors.append({"file": name, "error": _error_facts(error)})

    try:
        executable = _edge_executable()
        profile = Path(tempfile.mkdtemp(prefix="ess-topic-browser-"))
        result["profile"] = str(profile)
        arguments = [
            str(executable), "--inprivate", f"--user-data-dir={profile}",
            "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
            "--no-first-run", "--no-default-browser-check", url,
        ]
        result["launchArguments"] = arguments
        _write(output / "launch-intent.json", result)
        result["launchAttempted"] = True
        result["outcome"] = "incomplete"
        process = subprocess.Popen(
            arguments, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=(
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                if sys.platform == "win32" else 0
            ),
            start_new_session=sys.platform != "win32",
        )
        result["pid"] = process.pid
        result["outcome"] = "incomplete"
        record("browser-process.json")
        cdp, metadata = _wait_for_browser(process, profile, args.timeout)
        result["cdp"] = cdp
        result["browserMetadata"] = metadata
        result["outcome"] = "prepared"
    except (OSError, ValueError, RuntimeError, requests.RequestException) as error:
        result["error"] = _error_facts(error)
    if process is not None:
        result["processExitCode"] = process.poll()
        if result["processExitCode"] is not None and "error" not in result:
            result["outcome"] = "incomplete"
            result["error"] = _error_facts(RuntimeError(
                f"The dedicated test browser exited with code {result['processExitCode']}."
            ))
    if evidence_errors:
        result["evidenceWriteErrors"] = evidence_errors
        result["outcome"] = "incomplete" if result["launchAttempted"] else "blocked"
    record("result.json")
    if evidence_errors:
        result["evidenceWriteErrors"] = evidence_errors
        result["outcome"] = "incomplete" if result["launchAttempted"] else "blocked"
    return result, 0 if result["outcome"] == "prepared" else 2


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


def _inspection(component: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    dialog = component.get("dialog")
    if component.get("$kind") != "DialogComponent" or not isinstance(dialog, dict):
        raise ValueError("The selected component is not a saved native dialog topic.")
    begin = dialog.get("beginDialog")
    intent = begin.get("intent") if isinstance(begin, dict) else None
    triggers = intent.get("triggerQueries") if isinstance(intent, dict) else None
    response = None
    try:
        response, _ = literal_response(component)
        exact_mode = {"supported": True}
    except ValueError as exc:
        exact_mode = {"supported": False, "reason": str(exc)}
    return {
        "schemaVersion": 1, "operation": "inspect",
        "target": _identity(target), "component": component,
        "response": response, "triggers": triggers,
        "exactMode": exact_mode,
        "inspectionEvidence": {
            "source": "native-components", "componentHash": _hash(component),
            "triggerKind": begin.get("$kind") if isinstance(begin, dict) else None,
        },
    }


def _load_inspection(root: Path, path: Path) -> dict[str, Any]:
    inspection = _read(_evidence_path(root, path))
    if inspection.get("schemaVersion") != 1 or inspection.get("operation") != "inspect":
        raise ValueError("Use an inspection produced by this native-topic test tool.")
    if not isinstance(inspection.get("component"), dict):
        raise ValueError("The inspection contains no native topic component.")
    return inspection


def _selected(
    inspection: dict[str, Any], target: dict[str, Any], components: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    if inspection.get("target") != _identity(target):
        raise ValueError("The inspection or original run belongs to another native target.")
    component_id = str(uuid.UUID(inspection["component"]["id"]))
    component = components.get(component_id)
    if component is None or _topic_state(component) != _topic_state(inspection["component"]):
        raise ValueError("The selected native topic changed. Inspect it and approve its content again.")
    if component.get("$kind") != "DialogComponent" or not isinstance(component.get("dialog"), dict):
        raise ValueError("The selected component is not a saved native dialog topic.")
    return component_id, component


def _snapshot(components: dict[str, dict[str, Any]], component_id: str) -> dict[str, Any]:
    return {
        "component": components.get(component_id),
        "componentHashes": {key: _hash(value) for key, value in components.items()},
    }


def _topic_state(component: dict[str, Any] | None) -> dict[str, Any] | None:
    if component is None:
        return None
    return {
        key: component.get(key)
        for key in ("$kind", "id", "schemaName", "parentBotId", "dialog", "state", "status")
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
    selected_unchanged: bool | None,
    native_drift: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    signal = (
        classify_reply_signal(capture.reply_text, timed_out=capture.timed_out)
        if capture is not None else None
    )
    assessed = (
        capture is not None and not capture.timed_out
        and bool(capture.reply_text.strip()) and not capture.had_card
    )
    exact = capture.reply_text == expected if capture is not None and assessed else None
    return {
        "signal": signal.value if signal is not None else None,
        "errorShaped": looks_like_error(capture.reply_text) if capture is not None else None,
        "componentDrift": native_drift,
        "checks": {
            "savedResponse": {
                "requirementType": "requiredOutcome", "requirementId": "saved-response",
                "assessed": assessed, "met": exact, "operator": "exact",
            },
            "selectedTopicUnchanged": {
                "requirementType": "invariant", "requirementId": "selected-topic-unchanged",
                "assessed": selected_unchanged is not None, "met": selected_unchanged,
            },
        },
        "outcome": (
            "blocked" if capture is None
            else "passed" if exact is True and selected_unchanged is True
            else "incomplete" if selected_unchanged is None
            else "timeout" if capture.timed_out
            else "unsupported_reply" if capture.had_card
            else "failed" if assessed
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
    try:
        from daga_chat_driver import DagaChatDriver, PlaywrightError, validate_studio_url
    except ImportError as exc:
        raise RuntimeError(
            "Browser topic testing requires the optional Playwright runtime. "
            "Basic-only installations do not support browser testing."
        ) from exc

    if args.operation in {"run", "capture"}:
        inspection = _load_inspection(root, args.inspection)
        exact_mode = args.operation == "run"
        prompt = args.prompt
        cdp, url = args.cdp, args.url
        original = None
        original_baseline = None
        require_empty_conversation = args.require_empty_conversation
    else:
        original = _evidence_path(root, args.previous)
        execution = _read(original / "execution.json")
        if execution.get("schemaVersion") != 1 or execution.get("operation") not in {"run", "capture"}:
            raise ValueError("Observe the original run or capture, not a replacement send or observation.")
        exact_mode = execution["operation"] == "run"
        inspection = _load_inspection(root, original / "inspection.json")
        prompt = execution["prompt"]
        if execution["target"] != inspection["target"]:
            raise ValueError("The original execution and inspection target differ.")
        cdp, url = execution["cdp"], execution["url"]
        original_baseline = _read(original / "native-before.json")
        require_empty_conversation = execution.get("requireEmptyConversation", False)
    before = _components(client, target)
    component_id, component = _selected(inspection, target, before)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Supply one non-empty approved message.")
    expectation = None
    if exact_mode:
        expected, triggers = literal_response(component)
        expectation = {"operator": "exact", "text": expected}
        if prompt not in triggers:
            raise ValueError("This bounded exact test accepts only an explicitly saved trigger phrase.")
    if original is not None and (
        execution.get("expectation") != expectation
        or _topic_state(original_baseline["component"]) != _topic_state(component)
    ):
        raise ValueError("The original response or selected-topic boundary no longer matches.")
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
            "id": "selected-topic-unchanged",
            "description": "The selected topic's identity, dialog and active state remain unchanged.",
        }],
    } if exact_mode else {
        "mode": "capture", "prompt": prompt,
        "description": "Capture one approved turn; the session owns interpretation and grading.",
    })
    capture = None
    capture_facts = None
    errors = {}
    diagnostics = {}
    evidence_errors = []
    submission_may_have_occurred = False

    def record(name: str, value: dict[str, Any]) -> None:
        try:
            _write(output / name, value)
        except OSError as exc:
            evidence_errors.append({"file": name, "error": _error_facts(exc)})

    surface = DriveSurface(driver)
    try:
        surface.start()
        if original is None:
            boundary = driver.prepare()
            if require_empty_conversation:
                diagnostics["conversationBoundary"] = boundary
                if (
                    type(boundary.get("renderedTurnsBefore")) is not int
                    or boundary["renderedTurnsBefore"] != 0
                    or boundary.get("beforeTurnIndex") is not None
                    or boundary.get("beforeTurnElementId") is not None
                    or type(boundary.get("expectedTurnIndex")) is not int
                    or boundary["expectedTurnIndex"] != 0
                ):
                    raise RuntimeError(
                        "An empty conversation is required, but the boundary is "
                        "nonempty or unverified. No message was sent; no reset was attempted."
                    )
            _write(output / "execution.json", {
                "schemaVersion": 1, "operation": args.operation,
                "target": _identity(target), "prompt": prompt,
                "expectation": expectation,
                "cdp": cdp, "url": url, "boundary": boundary,
                "submissionMayHaveOccurred": True,
                "requireEmptyConversation": require_empty_conversation,
                "isolation": (
                    "Empty transcript verified before Send; runtime freshness is not "
                    "established by DOM alone."
                    if require_empty_conversation
                    else "Existing conversation; no reset or reload."
                ),
            })
            submission_may_have_occurred = True
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
                "expectation": expectation,
                "boundary": boundary, "submissionMayHaveOccurred": False,
                "requireEmptyConversation": require_empty_conversation,
            })
            capture = driver.observe(prompt, boundary, args.timeout)
        capture_facts = {
            "replyText": capture.reply_text, "timedOut": capture.timed_out,
            "partial": capture.timed_out and bool(capture.bubbles),
            "completionObserved": not capture.timed_out,
            "hadCard": capture.had_card, "bubbleCount": capture.bubble_count,
            "bubbles": [{"text": bubble.text, "hadCard": bubble.had_card} for bubble in capture.bubbles],
            "observation": driver.observation(),
        }
        record("capture.json", capture_facts)
        if not capture.timed_out:
            try:
                driver.screenshot(output / "current-turn.png")
            except (RuntimeError, PlaywrightError, OSError) as exc:
                diagnostics["screenshotError"] = _error_facts(exc)
    except (RuntimeError, PlaywrightError, requests.RequestException, OSError) as exc:
        errors["captureError"] = {
            **_error_facts(exc),
            "observation": driver.observation(),
        }
    finally:
        try:
            surface.close()
        except (RuntimeError, PlaywrightError, OSError) as exc:
            errors["cleanupError"] = _error_facts(exc)
    drift = None
    after = None
    selected_unchanged = None
    try:
        after = _snapshot(_components(client, target), component_id)
        comparison = original_baseline if original_baseline is not None else baseline
        drift = _drift(comparison["componentHashes"], after["componentHashes"])
        selected_unchanged = _topic_state(comparison["component"]) == _topic_state(after["component"])
        record("native-after.json", after)
    except (AgentBuilderError, requests.RequestException, ValueError) as exc:
        errors["nativeReadbackError"] = _error_facts(exc)
    assessment = assess(capture, expected, selected_unchanged, drift) if exact_mode else {
        "graded": False,
        "signal": (
            classify_reply_signal(capture.reply_text, timed_out=capture.timed_out).value
            if capture is not None else None
        ),
        "errorShaped": looks_like_error(capture.reply_text) if capture is not None else None,
        "selectedTopicUnchanged": selected_unchanged,
        "componentDrift": drift,
        "outcome": (
            "blocked" if capture is None
            else "incomplete" if selected_unchanged is not True
            else "timeout" if capture.timed_out
            else "captured"
        ),
    }
    result = {
        "schemaVersion": 1, "operation": args.operation,
        "mode": "exact" if exact_mode else "capture",
        "target": _identity(target), "componentId": component_id,
        "prompt": prompt, "evidenceDirectory": str(output),
        "observation": driver.observation(),
        "submissionMayHaveOccurred": submission_may_have_occurred,
        "requireEmptyConversation": require_empty_conversation,
        "capture": capture_facts,
        "nativeReadback": after,
        **({"originalRun": str(original)} if original is not None else {}),
        **assessment,
        "limitations": [
            "Current-turn correlation is not an exact-topic invocation trace.",
            "Completion is a quiet, non-generating DOM observation, not backend completion proof.",
            "The existing conversation was not reset; this is not independent discovery evidence.",
            "An empty transcript does not prove a new runtime conversation or saved-version execution.",
            "Cards are captured as rendered text/presence, not structured card payloads; "
            "card interactions, backend fault injection and workflow diagnostics are unsupported.",
            "No activation, publication, routing change or retry is performed by capture or observe.",
            "An uncertain send must be observed without replay; a timeout is not proof of failure.",
        ] + (["Reply equality is only the optional exact saved-response assertion."] if exact_mode else []),
    }
    if exact_mode:
        result["assessmentOutcome"] = result["outcome"]
    if diagnostics:
        result["diagnostics"] = diagnostics
    if errors:
        result["error"] = errors
        result["outcome"] = "incomplete" if capture is not None else "blocked"
    if evidence_errors:
        result["evidenceWriteErrors"] = evidence_errors
        result["outcome"] = "incomplete" if capture is not None else "blocked"
    record("result.json", result)
    if evidence_errors:
        result["evidenceWriteErrors"] = evidence_errors
        result["outcome"] = "incomplete" if capture is not None else "blocked"
    return result, 2 if errors or evidence_errors else 0 if result["outcome"] in {"passed", "captured"} else 1


def _activate(
    args: argparse.Namespace,
    root: Path,
    client: AgentBuilderClient,
    target: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    inspection = _load_inspection(root, args.inspection)
    before = _components(client, target)
    component_id, component = _selected(inspection, target, before)
    if not isinstance(component.get("schemaName"), str) or not component["schemaName"].strip():
        raise ValueError("Native activation requires the inspected topic's schema name.")
    output = _new_output(root, args.output, "activate")
    baseline = _snapshot(before, component_id)
    _write(output / "inspection.json", inspection)
    _write(output / "native-before.json", baseline)
    result: dict[str, Any] = {
        "schemaVersion": 1, "operation": "activate",
        "target": _identity(target), "componentId": component_id,
        "evidenceDirectory": str(output), "before": baseline,
        "requestedState": {"state": "Active", "status": "Active"},
        "writeAttempted": False, "writeAccepted": None, "verified": False,
        "nativeReadback": None, "stateMatchesRequest": None, "componentDrift": None,
        "published": False, "outcome": "preview",
    }
    errors = {}
    evidence_errors = []

    def record(name: str, value: dict[str, Any]) -> None:
        try:
            _write(output / name, value)
        except OSError as exc:
            evidence_errors.append({"file": name, "error": _error_facts(exc)})

    if args.yes:
        # Record intent before the single native operation. A missing result is
        # never permission to repeat a potentially committed write.
        _write(output / "execution.json", {
            "schemaVersion": 1, "operation": "activate",
            "target": _identity(target), "componentId": component_id,
            "requestedState": result["requestedState"], "writeMayHaveOccurred": True,
        })
        try:
            saved = _native_client(client, target).update_dialog_components([{
                "componentId": component["id"], "schemaName": component["schemaName"],
                "expectedComponent": component,
                "state": "Active", "status": "Active",
            }], _retry_on_conflict=False)
            result.update({
                "nativeResult": saved, "writeAttempted": saved["writeAttempted"],
                "writeAccepted": True if saved["writeAttempted"] else None,
                "verified": saved["verified"],
                "outcome": "activated" if saved["writeAttempted"] else "unchanged",
            })
        except ComponentEditError as exc:
            result.update({
                "writeAttempted": exc.evidence.get("writeAttempted", True),
                "writeAccepted": exc.evidence.get("writeAccepted"),
                "outcome": "incomplete",
            })
            errors["activationError"] = _error_facts(exc)
        except (MinimalBotEvaluationError, requests.RequestException, ValueError, OSError) as exc:
            # The native adapter wraps every attempted PUT in ComponentEditError;
            # these failures precede that boundary.
            result["outcome"] = "blocked"
            errors["activationError"] = _error_facts(exc)
        try:
            after = _snapshot(_components(client, target), component_id)
            desired = {**_topic_state(component), "state": "Active", "status": "Active"}
            result.update({
                "nativeReadback": after,
                "stateMatchesRequest": _topic_state(after["component"]) == desired,
                "componentDrift": _drift(baseline["componentHashes"], after["componentHashes"]),
            })
            record("native-after.json", after)
            if not result["stateMatchesRequest"]:
                raise ValueError("Native readback differs from the inspected topic with Active state.")
        except (AgentBuilderError, requests.RequestException, ValueError) as exc:
            errors["nativeReadbackError"] = _error_facts(exc)
    result["activationOutcome"] = result["outcome"]
    if errors:
        result["error"] = errors
        result["outcome"] = "incomplete" if result["writeAttempted"] else "blocked"
    if evidence_errors:
        result["evidenceWriteErrors"] = evidence_errors
        result["outcome"] = "incomplete" if result["verified"] or result["writeAttempted"] else "blocked"
    record("result.json", result)
    if evidence_errors:
        result["evidenceWriteErrors"] = evidence_errors
        result["outcome"] = "incomplete" if result["verified"] or result["writeAttempted"] else "blocked"
    return result, 2 if errors or evidence_errors else 0


def _new_conversation(args, target: dict[str, Any]) -> tuple[dict[str, Any], int]:
    from daga_chat_driver import DagaChatDriver, validate_studio_url

    url = validate_studio_url(args.url, target)
    driver = DagaChatDriver(cdp=args.cdp, expected_url=url)
    driver.start()
    try:
        driver.reset()
    finally:
        driver.close()
    return {
        "operation": "new-conversation", "target": _identity(target), "outcome": "clicked",
    }, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=(
        "list", "inspect", "prepare-browser", "new-conversation",
        "run", "capture", "observe", "activate",
    ))
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
    parser.add_argument(
        "--require-empty-conversation", action="store_true",
        help="Require a verified empty turn boundary before Send; never reset the conversation.",
    )
    parser.add_argument("--yes", action="store_true", help="Apply separately authorized topic activation.")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds.")
    required = {
        "inspect": ("component_id",),
        "prepare-browser": ("url",),
        "new-conversation": ("cdp", "url"),
        "run": ("inspection", "prompt", "cdp", "url", "output"),
        "capture": ("inspection", "prompt", "cdp", "url", "output"),
        "observe": ("previous",),
        "activate": ("inspection",),
    }
    for field in required.get(args.operation, ()):
        if getattr(args, field) is None:
            parser.error(f"--{field.replace('_', '-')} is required.")
    if args.yes and args.operation != "activate":
        parser.error("--yes is valid only for separately authorized activation.")
    if args.require_empty_conversation and args.operation not in {"run", "capture"}:
        parser.error("--require-empty-conversation is valid only for run or capture.")
    try:
        root = args.kit_root.resolve()
        client, target = connect_selected_dev_workspace(root, args.account)
        if args.operation == "prepare-browser":
            result, code = _prepare_browser(args, root, target)
        elif args.operation == "new-conversation":
            result, code = _new_conversation(args, target)
        elif args.operation in {"run", "capture", "observe"}:
            result, code = _exercise(args, root, client, target)
        elif args.operation == "activate":
            result, code = _activate(args, root, client, target)
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
                inspection = _inspection(component, target)
                output = _new_output(root, args.output, "inspect")
                _write(output / "inspection.json", inspection)
                result = {
                    "operation": "inspect", "target": _identity(target),
                    "componentId": component["id"], "displayName": component.get("displayName"),
                    "state": component.get("state"), "status": component.get("status"),
                    "response": inspection["response"], "triggers": inspection["triggers"],
                    "component": component,
                    "exactMode": inspection["exactMode"],
                    "inspectionEvidence": inspection["inspectionEvidence"],
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
