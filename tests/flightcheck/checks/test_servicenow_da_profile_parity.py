# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Parity and isolation tests for the shared ServiceNow DA check profiles.

The golden fixture was captured from the implementation that rewrote HRSD
output into ITSM output after the fact. The profile-driven implementation must
produce byte-identical CheckResult rows for both profiles.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import connect_servicenow_da as snow
from flightcheck.checks import servicenow_da_hrsd as shared
from flightcheck.checks.servicenow_da_hrsd import (
    run_servicenow_da_hrsd_checks,
)
from flightcheck.checks.servicenow_da_itsm import (
    run_servicenow_da_itsm_checks,
)
from tests.flightcheck.checks.test_servicenow_da_hrsd import (
    AGENT_ID,
    AGENT_SLUG as HR_SLUG,
    APP_CLIENT_ID,
    CONNECTION_ID,
    ENVIRONMENT_ID,
    _components as _hr_components,
    _connection,
    _runner as _hr_runner,
    _write_state as _write_hr_state,
)
from tests.flightcheck.checks.test_servicenow_da_itsm import (
    IT_SLUG,
    _itsm_components,
    _runner as _it_runner,
    _write_it_state,
)


GOLDEN_PATH = Path(__file__).parent / "golden" / (
    "servicenow_da_profile_results.json"
)
WRITE_GOLDEN_ENV = "SN_PARITY_WRITE_GOLDEN"
SUFFIXES = (
    "PKG",
    "ADMIN-PREFLIGHT",
    "PLUGIN",
    "ENTRA-SETUP",
    "OIDC",
    "CREDENTIAL",
    "AGENT-CONNECTION",
    "TOPICS",
    "PORTAL",
    "TEST",
)
RETIRED_CHECKPOINT = "-PUBLISH-"
PLAN_SHA = "d" * 64
TARGET_SHA = "e" * 64


class _ThrottledError(RuntimeError):
    status_code = 429


def _profile_fixture(key: str) -> dict[str, Any]:
    if key == "hrsd":
        return {
            "prefix": "SN-DA-HRSD",
            "slug": HR_SLUG,
            "schema": snow.HR_SCHEMA_NAME,
            "provider": snow.HRSD_PROFILE.provider_key,
            "prompt": snow.HRSD_PROFILE.test_prompt_category,
            "components": _hr_components,
            "runner": _hr_runner,
            "write_state": _write_hr_state,
            "run": run_servicenow_da_hrsd_checks,
            "other_schema": snow.IT_SCHEMA_NAME,
        }
    return {
        "prefix": "SN-DA-ITSM",
        "slug": IT_SLUG,
        "schema": snow.IT_SCHEMA_NAME,
        "provider": snow.ITSM_PROFILE.provider_key,
        "prompt": snow.ITSM_PROFILE.test_prompt_category,
        "components": _itsm_components,
        "runner": _it_runner,
        "write_state": _write_it_state,
        "run": run_servicenow_da_itsm_checks,
        "other_schema": snow.HR_SCHEMA_NAME,
    }


def _row(result: Any) -> dict[str, Any]:
    value = asdict(result)
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _row_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(row, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _state_file(root: Path, fixture: dict[str, Any]) -> Path:
    return (
        root
        / ".local"
        / "connect"
        / fixture["provider"]
        / "agents"
        / fixture["slug"]
        / "lifecycle.json"
    )


def _edit_state(
    root: Path,
    fixture: dict[str, Any],
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    path = _state_file(root, fixture)
    state = json.loads(path.read_text(encoding="utf-8"))
    mutate(state)
    path.write_text(json.dumps(state), encoding="utf-8")


def _swap_text(components: dict[str, Any], old: str, new: str) -> dict:
    return json.loads(json.dumps(components).replace(old, new))


def _inactive_topic(components: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(components)
    component = value["botComponentChanges"][0]["component"]
    component["state"] = "Inactive"
    component["status"] = "Inactive"
    return value


def _no_topics(components: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(components)
    value["botComponentChanges"] = []
    return value


def _no_connection_refs(components: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(components)
    value["connectionReferenceChanges"] = []
    return value


def _wrong_portal_instance(components: dict[str, Any]) -> dict[str, Any]:
    return _swap_text(
        components,
        "dev123.service-now.com",
        "other456.service-now.com",
    )


def _connections_runner(runner: Any, connections: list[dict]) -> None:
    runner.connectivity = SimpleNamespace(
        list_connector_connections=lambda _environment_id, _connector: (
            connections
        )
    )


def _raise(error: BaseException) -> Callable[..., Any]:
    def raiser(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return raiser


def _disconnected(runner: Any) -> None:
    connection = _connection()
    connection["properties"]["statuses"] = [
        {"target": "token", "status": "Disconnected"}
    ]
    _connections_runner(runner, [connection])


def _wrong_resource(runner: Any) -> None:
    connection = _connection()
    connection["properties"]["connectionParametersSet"]["values"][
        "token:ResourceUri"
    ]["value"] = "00000000-0000-4000-8000-000000009998"
    _connections_runner(runner, [connection])


def _connectivity_error(runner: Any) -> None:
    runner.connectivity = SimpleNamespace(
        list_connector_connections=_raise(
            RuntimeError("inventory 403 denied")
        )
    )


def _components_error(runner: Any) -> None:
    runner.agentbuilder = SimpleNamespace(
        fetch_components=_raise(RuntimeError("components unavailable"))
    )


def _components_throttled(runner: Any) -> None:
    runner.agentbuilder = SimpleNamespace(
        fetch_components=_raise(_ThrottledError("slow down"))
    )


def _target_context(fixture: dict[str, Any], *, current: bool) -> dict:
    key = "hrsd" if fixture["prefix"].endswith("HRSD") else "itsm"
    target = {
        "agentId": AGENT_ID,
        "schemaName": f"{fixture['schema']}_test",
        "environmentId": ENVIRONMENT_ID,
    }
    context: dict[str, Any] = {
        "realm": "test",
        "profile": key,
        "sourceAgentSlug": fixture["slug"],
        "target": target,
        "expectedInstanceName": "dev123",
        "expectedApplicationClientId": APP_CLIENT_ID,
        "connectionId": CONNECTION_ID,
        "targetConfigurationSha256": TARGET_SHA,
    }
    if current:
        context["validation"] = {
            "runtimePlan": {
                "planSha256": PLAN_SHA,
                "connectionId": CONNECTION_ID,
            },
            "runtimeApproval": {
                "decision": "approved",
                "planSha256": PLAN_SHA,
            },
            "agentBinding": {
                "status": "completed",
                "targetConfigurationSha256": TARGET_SHA,
                "targetAgentId": AGENT_ID,
                "targetEnvironmentId": ENVIRONMENT_ID,
                "planSha256": PLAN_SHA,
                "connectionId": CONNECTION_ID,
            },
            "functionalTest": {
                "status": "completed",
                "result": "pass",
                "failureCategory": None,
                "promptCategory": fixture["prompt"],
                "binding": {
                    "provider": fixture["provider"],
                    "profile": key,
                    "targetAgentId": AGENT_ID,
                    "targetEnvironmentId": ENVIRONMENT_ID,
                    "targetConfigurationSha256": TARGET_SHA,
                    "planSha256": PLAN_SHA,
                    "connectionId": CONNECTION_ID,
                },
            },
        }
    return context


# (name, components mutator, state mutator, runner mutator, all targets?)
_SCENARIOS: tuple[tuple[str, Any, Any, Any, bool], ...] = (
    ("full_healthy", None, None, None, True),
    ("inactive_topic", _inactive_topic, None, None, False),
    ("no_topics", _no_topics, None, None, True),
    ("no_connection_refs", _no_connection_refs, None, None, True),
    ("wrong_portal_instance", _wrong_portal_instance, None, None, False),
    (
        "entra_missing",
        None,
        lambda s: s["adminSetup"]["phaseHandoffs"]["entra-registration"][
            "evidence"
        ].pop("clientId"),
        None,
        False,
    ),
    (
        "oidc_missing",
        None,
        lambda s: s["adminSetup"]["phaseHandoffs"].pop("servicenow-oidc"),
        None,
        False,
    ),
    (
        "preflight_missing",
        None,
        lambda s: s["adminSetup"]["preflight"].pop("instanceName"),
        None,
        False,
    ),
    (
        "plugin_missing",
        None,
        lambda s: s["adminSetup"]["phaseHandoffs"].pop(
            "plugin-prerequisites", None
        ),
        None,
        False,
    ),
    (
        "test_failed",
        None,
        lambda s: s["evidence"]["test"].update({"result": "fail"}),
        None,
        False,
    ),
    (
        "stale_agent_binding",
        None,
        lambda s: s["evidence"]["agentConnection"]["binding"].update(
            {"bindingIdentitySha256": "0" * 64}
        ),
        None,
        False,
    ),
    (
        "credential_evidence_missing",
        None,
        lambda s: s["evidence"].pop("credential"),
        None,
        False,
    ),
    (
        "publish_missing",
        None,
        lambda s: s["evidence"].pop("publish"),
        None,
        False,
    ),
    ("credential_disconnected", None, None, _disconnected, False),
    ("credential_wrong_resource", None, None, _wrong_resource, False),
    ("connectivity_error", None, None, _connectivity_error, False),
    ("components_error", None, None, _components_error, False),
    ("components_throttled", None, None, _components_throttled, False),
    (
        "wrong_schema",
        None,
        None,
        lambda r: r.config["agents"][0].update({"schemaName": "other"}),
        False,
    ),
    (
        "no_agent_id",
        None,
        None,
        lambda r: r.config["agents"][0].pop("botId"),
        False,
    ),
)


def _scenario_runner(
    fixture: dict[str, Any],
    components: dict[str, Any],
    target: str | None,
) -> Any:
    runner = fixture["runner"](components)
    runner.checkpoint_target = target
    return runner


def collect_results(
    profile_key: str,
    base: Path,
    chdir: Callable[[Path], None],
) -> dict[str, list[dict[str, Any]]]:
    """Run every parity scenario for one profile and return CheckResult rows."""
    fixture = _profile_fixture(profile_key)
    run = fixture["run"]
    collected: dict[str, list[dict[str, Any]]] = {}
    counter = 0

    def fresh(with_state: bool, components: dict) -> Path:
        nonlocal counter
        counter += 1
        root = base / f"{profile_key}-{counter}"
        root.mkdir(parents=True)
        if with_state:
            fixture["write_state"](root, components)
        chdir(root)
        return root

    def record(name: str, results: list) -> None:
        collected[name] = [_row(result) for result in results]

    bare = SimpleNamespace(config={}, checkpoint_target=None)
    base.mkdir(parents=True, exist_ok=True)
    chdir(base)
    record("bare", run(bare))

    base_components = fixture["components"]()
    targets: list[str | None] = [None] + [
        f"{fixture['prefix']}-{suffix}-001" for suffix in SUFFIXES
    ]
    for name, components_edit, state_edit, runner_edit, all_targets in (
        _SCENARIOS
    ):
        components = (
            components_edit(base_components)
            if components_edit
            else copy.deepcopy(base_components)
        )
        for target in targets if all_targets else [None]:
            root = fresh(True, base_components)
            if state_edit is not None:
                _edit_state(root, fixture, state_edit)
            runner = _scenario_runner(fixture, components, target)
            if runner_edit is not None:
                runner_edit(runner)
            record(f"{name}:{target or 'all'}", run(runner))

    for target in targets:
        fresh(False, base_components)
        record(
            f"no_state:{target or 'all'}",
            run(_scenario_runner(fixture, base_components, target)),
        )

    for current in (False, True):
        for target in targets:
            fresh(True, base_components)
            runner = _scenario_runner(fixture, base_components, target)
            runner.servicenow_target_context = _target_context(
                fixture,
                current=current,
            )
            record(
                f"target_context_{'current' if current else 'stale'}:"
                f"{target or 'all'}",
                run(runner),
            )
    return collected


def _golden_document(
    collected: dict[str, dict[str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    scenarios: dict[str, dict[str, list[str]]] = {}
    for profile_key, results in collected.items():
        scenarios[profile_key] = {}
        for name, items in results.items():
            hashes = []
            for row in items:
                digest = _row_hash(row)
                rows[digest] = row
                hashes.append(digest)
            scenarios[profile_key][name] = hashes
    return {"rows": rows, "scenarios": scenarios}


def _collect_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    return {
        key: collect_results(key, tmp_path / key, monkeypatch.chdir)
        for key in ("hrsd", "itsm")
    }


def test_write_golden_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not os.environ.get(WRITE_GOLDEN_ENV):
        pytest.skip(f"Set {WRITE_GOLDEN_ENV}=1 to regenerate the golden.")
    document = _golden_document(_collect_all(tmp_path, monkeypatch))
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(
        json.dumps(document, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("profile_key", ["hrsd", "itsm"])
def test_profile_results_match_pre_refactor_golden(
    profile_key: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    collected = collect_results(profile_key, tmp_path, monkeypatch.chdir)
    # The PUBLISH checkpoint was retired after the golden was captured. Its
    # rows and PUBLISH-targeted scenarios are the only permitted difference.
    expected = {
        name: [
            digest
            for digest in digests
            if RETIRED_CHECKPOINT
            not in golden["rows"][digest]["checkpoint_id"]
        ]
        for name, digests in golden["scenarios"][profile_key].items()
        if not name.endswith("-PUBLISH-001")
    }
    assert set(collected) == set(expected)
    for name, rows in collected.items():
        assert [_row_hash(row) for row in rows] == expected[name], name
        for row in rows:
            assert golden["rows"][_row_hash(row)] == row


_RETIRED_GLOBALS = (
    "HR_SCHEMA_NAME",
    "PROVIDER_KEY",
    "_CATEGORY",
    "_ENTRA_PREFIX",
    "_TEST_PROMPT_CATEGORY",
)


def _module_snapshot() -> dict[str, Any]:
    return {
        name: copy.deepcopy(value)
        for name, value in vars(shared).items()
        if not name.startswith("__")
        and name != "annotations"
        and not callable(value)
        and not isinstance(value, type(shared))
    }


def _prepare(profile_key: str, root: Path, target: str | None = None) -> Any:
    fixture = _profile_fixture(profile_key)
    components = fixture["components"]()
    root.mkdir(parents=True, exist_ok=True)
    fixture["write_state"](root, components)
    return fixture, _scenario_runner(fixture, components, target)


def test_it_run_does_not_mutate_module_globals_or_runner_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    it_target = "SN-DA-ITSM-TOPICS-001"
    fixture, runner = _prepare("itsm", tmp_path, it_target)
    before = _module_snapshot()
    observed: list[tuple[dict[str, Any], Any]] = []
    original_load = shared._load_state

    def watching_load(*args: Any, **kwargs: Any) -> Any:
        observed.append((_module_snapshot(), runner.checkpoint_target))
        return original_load(*args, **kwargs)

    monkeypatch.setattr(shared, "_load_state", watching_load)
    results = fixture["run"](runner)

    assert observed
    assert all(
        snapshot == before and target == it_target
        for snapshot, target in observed
    )
    assert _module_snapshot() == before
    assert runner.checkpoint_target == it_target
    assert [result.checkpoint_id for result in results] == [it_target]
    for name in _RETIRED_GLOBALS:
        assert not hasattr(shared, name)


def test_hr_results_identical_after_it_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    def hr_rows(name: str) -> list[dict[str, Any]]:
        fixture, runner = _prepare("hrsd", tmp_path / name)
        monkeypatch.chdir(tmp_path / name)
        return [_row(result) for result in fixture["run"](runner)]

    def it_rows() -> list[dict[str, Any]]:
        fixture, runner = _prepare("itsm", tmp_path / "it")
        monkeypatch.chdir(tmp_path / "it")
        return [_row(result) for result in fixture["run"](runner)]

    first = hr_rows("hr1")
    middle = it_rows()
    second = hr_rows("hr2")

    assert first == second
    assert all(row["checkpoint_id"].startswith("SN-DA-HRSD") for row in first)
    assert all(
        row["checkpoint_id"].startswith("SN-DA-ITSM") for row in middle
    )
    assert "SN-DA-ITSM-PLUGIN-001" not in {
        row["checkpoint_id"] for row in middle
    }


def test_it_output_does_not_rewrite_foreign_hr_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    fixture, runner = _prepare("itsm", tmp_path)
    foreign = "upstream said HR case HRSD agent unavailable"
    runner.agentbuilder = SimpleNamespace(
        fetch_components=_raise(RuntimeError(foreign))
    )
    text = json.dumps([_row(result) for result in fixture["run"](runner)])

    assert foreign in text
