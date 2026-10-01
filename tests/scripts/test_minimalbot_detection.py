# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure-logic tests for the MinimalBot (Dataverse-free) transport.

Covers detection (``is_minimalbot`` / ``_is_native_da``), ring derivation
(``ring_for_config`` and the per-ring helpers), the ring-aware environment host,
``environmentId`` precedence, the ring-derived client wiring, the ring-aware
Copilot Studio origin/deep-link helpers in ``evaluation_runs``, and the
flag-safety rejections in ``push._minimalbot_push``.

None of these touch the network — they exercise the kit's pure-logic helpers,
which ``tests/AGENTS.md`` exempts from the cassette rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import minimalbot_evaluation as mbe
import evaluation_runs
import push


ENV_ID = "214d162d-0479-e7b3-b118-3ba749943035"
BOT_ID = "fc27c063-49bb-4241-9546-8239e385a267"

TEST_ENDPOINT = "https://abc123.environment.api.test.powerplatform.com"
PREPROD_ENDPOINT = "https://abc123.environment.api.preprod.powerplatform.com"
PROD_ENDPOINT = "https://abc123.environment.api.powerplatform.com"


# -- is_minimalbot / _is_native_da ------------------------------------------


def test_is_minimalbot_true_for_top_level_releaseline_da():
    config = {
        "releaseLine": "da",
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID},
    }
    assert mbe.is_minimalbot(config) is True


def test_is_minimalbot_true_for_agent_releaseline_da():
    config = {
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID, "releaseLine": "DA"},
    }
    assert mbe.is_minimalbot(config) is True


def test_is_minimalbot_true_for_power_platform_endpoint_marker():
    config = {
        "powerPlatformApiEndpoint": TEST_ENDPOINT,
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID},
    }
    assert mbe.is_minimalbot(config) is True


def test_is_minimalbot_false_when_dataverse_endpoint_present():
    # A classic agent that also happens to carry a DA marker must NOT be
    # misrouted to the Dataverse-free plane while it has a Dataverse endpoint.
    config = {
        "releaseLine": "da",
        "dataverseEndpoint": "https://contoso.crm.dynamics.com",
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID},
    }
    assert mbe.is_minimalbot(config) is False


def test_is_minimalbot_false_without_environment_id():
    config = {
        "releaseLine": "da",
        "agent": {"botId": BOT_ID},
    }
    assert mbe.is_minimalbot(config) is False


def test_is_minimalbot_false_without_explicit_marker():
    # No dataverseEndpoint AND no DA marker: a half-configured classic agent is
    # not silently treated as a MinimalBot (the core regression this fixes).
    config = {
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID},
    }
    assert mbe.is_minimalbot(config) is False


def test_is_minimalbot_false_for_non_dict():
    assert mbe.is_minimalbot(None) is False  # type: ignore[arg-type]


# -- ring_for_config and per-ring helpers -----------------------------------


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        (TEST_ENDPOINT, "test"),
        (PREPROD_ENDPOINT, "preprod"),
        (PROD_ENDPOINT, "prod"),
    ],
)
def test_ring_for_config_derives_ring_from_endpoint(endpoint, expected):
    assert mbe.ring_for_config({"powerPlatformApiEndpoint": endpoint}) == expected


def test_ring_for_config_defaults_to_prod_when_absent():
    assert mbe.ring_for_config({"environmentId": ENV_ID}) == "prod"


def test_ring_for_config_defaults_to_prod_on_unrecognised_endpoint():
    assert mbe.ring_for_config({"powerPlatformApiEndpoint": "https://x.example"}) == "prod"


def test_api_base_and_scope_per_ring():
    assert mbe._api_base_for_ring("prod") == "https://api.powerplatform.com"
    assert mbe._api_base_for_ring("test") == "https://api.test.powerplatform.com"
    assert mbe._scope_for_ring("test") == "https://api.test.powerplatform.com/.default"


def test_agent_backend_is_cosmos_only_on_test_ring():
    assert mbe._agent_backend_for_ring("test") == "cosmos"
    assert mbe._agent_backend_for_ring("prod") is None
    assert mbe._agent_backend_for_ring("preprod") is None


# -- _environment_host (ring-aware) -----------------------------------------


def test_environment_host_is_ring_specific():
    prod_host = mbe._environment_host(ENV_ID, "prod")
    test_host = mbe._environment_host(ENV_ID, "test")
    assert prod_host.startswith("https://")
    assert prod_host.endswith(".environment.api.powerplatform.com")
    assert test_host.endswith(".environment.api.test.powerplatform.com")
    # The split index differs between rings, so the hosts must not collide.
    assert prod_host != test_host


def test_environment_host_round_trips_through_ring_detection():
    # The host we build for a ring must itself resolve back to that ring.
    from agentbuilder import ring_from_environment_host

    for ring in ("prod", "preprod", "test"):
        host = mbe._environment_host(ENV_ID, ring)
        assert ring_from_environment_host(host) == ring


# -- environmentId precedence -----------------------------------------------


def test_environment_id_prefers_agent_over_top_level():
    config = {
        "environmentId": "top-level-stale",
        "agent": {"environmentId": "agent-specific"},
    }
    assert mbe._environment_id(config) == "agent-specific"


def test_environment_id_falls_back_to_top_level():
    config = {"environmentId": "top-level", "agent": {"botId": BOT_ID}}
    assert mbe._environment_id(config) == "top-level"


# -- client wiring derives from ring ----------------------------------------


def test_client_defaults_to_test_ring():
    client = mbe.MinimalBotEvaluationClient(ENV_ID, BOT_ID, "tenant-1")
    assert client.ring == "test"
    assert client.api_base == "https://api.test.powerplatform.com"
    assert client.scope == "https://api.test.powerplatform.com/.default"
    assert client.agent_backend == "cosmos"
    assert client.host.endswith(".environment.api.test.powerplatform.com")


def test_from_config_derives_prod_ring_and_no_cosmos_backend():
    config = {
        "powerPlatformApiEndpoint": PROD_ENDPOINT,
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID, "releaseLine": "da"},
    }
    client = mbe.MinimalBotEvaluationClient.from_config(config)
    assert client.ring == "prod"
    assert client.api_base == "https://api.powerplatform.com"
    assert client.scope == "https://api.powerplatform.com/.default"
    assert client.agent_backend is None
    assert client.host.endswith(".environment.api.powerplatform.com")


# -- evaluation_runs ring-aware Studio helpers ------------------------------


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        (PROD_ENDPOINT, "https://copilotstudio.microsoft.com"),
        (PREPROD_ENDPOINT, "https://copilotstudio.preprod.microsoft.com"),
        (TEST_ENDPOINT, "https://copilotstudio.test.microsoft.com"),
    ],
)
def test_studio_origin_for_config_is_ring_aware(endpoint, expected):
    assert evaluation_runs._studio_origin_for_config(
        {"powerPlatformApiEndpoint": endpoint}) == expected


def test_studio_origin_falls_back_to_prod_when_endpoint_absent():
    assert (
        evaluation_runs._studio_origin_for_config({})
        == "https://copilotstudio.microsoft.com"
    )


def test_agent_studio_url_deep_link_appends_agent_backend():
    url = evaluation_runs._agent_studio_url(
        "https://copilotstudio.test.microsoft.com",
        ENV_ID,
        BOT_ID,
        test_set_id="set-1",
        run_id="run-1",
        agent_backend="cosmos",
    )
    assert url == (
        "https://copilotstudio.test.microsoft.com"
        f"/environments/{ENV_ID}/copilots/{BOT_ID}"
        "/evaluation/runsDetails/set-1/run-1?agentBackend=cosmos"
    )


def test_agent_studio_url_deep_link_without_backend_has_no_query():
    url = evaluation_runs._agent_studio_url(
        "https://copilotstudio.microsoft.com",
        ENV_ID,
        BOT_ID,
        test_set_id="set-1",
        run_id="run-1",
    )
    assert url is not None
    assert "?agentBackend=" not in url


def test_agent_studio_url_falls_back_to_overview_without_run_ids():
    url = evaluation_runs._agent_studio_url(
        "https://copilotstudio.microsoft.com", ENV_ID, BOT_ID)
    assert url == (
        f"https://copilotstudio.microsoft.com/environments/{ENV_ID}"
        f"/bots/{BOT_ID}/overview"
    )


def test_agent_studio_url_returns_none_when_ids_missing():
    assert evaluation_runs._agent_studio_url("origin", "", BOT_ID) is None
    assert evaluation_runs._agent_studio_url("", ENV_ID, BOT_ID) is None


# -- push._minimalbot_push flag safety (#3) ---------------------------------


def _minimalbot_config(folder: str) -> dict[str, Any]:
    return {
        "powerPlatformApiEndpoint": TEST_ENDPOINT,
        "environmentId": ENV_ID,
        "agent": {
            "botId": BOT_ID,
            "folder": folder,
            "releaseLine": "da",
            "schemaName": "contoso",
        },
    }


def test_minimalbot_push_rejects_force_delete(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        push._minimalbot_push(
            _minimalbot_config(str(tmp_path)),
            dry_run=False,
            force_delete=True,
            repair_mode=False,
            only_globs=None,
        )
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--force-delete is not supported" in out
    assert "No request was made" in out


def test_minimalbot_push_rejects_repair(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        push._minimalbot_push(
            _minimalbot_config(str(tmp_path)),
            dry_run=False,
            force_delete=False,
            repair_mode=True,
            only_globs=None,
        )
    assert exc.value.code == 1
    assert "--repair" in capsys.readouterr().out


def test_warn_minimalbot_non_eval_changes_flags_topic_edits(tmp_path, capsys):
    agent_dir = tmp_path / "agent"
    baseline_dir = agent_dir / ".baseline"
    (baseline_dir / "topics").mkdir(parents=True)
    # A new topic (botcomponent) not under evaluations/ must be surfaced.
    (agent_dir / "topics").mkdir(parents=True)
    (agent_dir / "topics" / "greet.mcs.yml").write_text("kind: Topic\n", encoding="utf-8")

    push._warn_minimalbot_non_eval_changes(str(agent_dir))
    out = capsys.readouterr().out
    assert "will NOT be pushed" in out
    assert "topics/greet.mcs.yml" in out


def test_warn_minimalbot_non_eval_changes_silent_for_eval_only(tmp_path, capsys):
    agent_dir = tmp_path / "agent"
    baseline_dir = agent_dir / ".baseline"
    baseline_dir.mkdir(parents=True)
    eval_dir = agent_dir / "evaluations" / "set-a"
    eval_dir.mkdir(parents=True)
    (eval_dir / "set.mcs.yml").write_text("kind: EvaluationSet\n", encoding="utf-8")

    push._warn_minimalbot_non_eval_changes(str(agent_dir))
    assert "will NOT be pushed" not in capsys.readouterr().out


# -- MinimalBot push scoping / gate / kind-safety regressions ----------------


def _write_eval_set(root, name, *, kind="EvaluationData", cases=("case1",)):
    """Create evaluations/<name>/ with one EvaluationSet parent + child files."""
    folder = root / "evaluations" / name
    folder.mkdir(parents=True)
    (folder / f"{name}.mcs.yml").write_text(
        f"kind: EvaluationSet\ndisplayName: {name}\n"
        "graders:\n  - kind: CompareMeaningGrader\n", encoding="utf-8")
    for case in cases:
        (folder / f"{case}.mcs.yml").write_text(
            f"kind: {kind}\nrows:\n  - input: q\n    expectedOutput: a\n",
            encoding="utf-8",
        )
    return folder


def _mb_client():
    return mbe.MinimalBotEvaluationClient(ENV_ID, BOT_ID, "tenant-1")


def test_scoped_minimalbot_push_only_touches_matching_set(tmp_path):
    # F-1: a scoped push must NOT silently expand to every set. With two sets
    # on disk and a glob that matches only one, the plan carries just that set.
    _write_eval_set(tmp_path, "compensation")
    _write_eval_set(tmp_path, "benefits")

    plan = _mb_client().push_agent_evaluations(
        str(tmp_path),
        dry_run=True,
        only_globs=["evaluations/compensation/*"],
    )
    assert [s["folder"] for s in plan["sets"]] == ["compensation"]


def test_scoped_minimalbot_push_raises_when_nothing_matches(tmp_path):
    # F-1: an unmatched scope must fail loudly, never fall back to a broad push.
    _write_eval_set(tmp_path, "compensation")

    with pytest.raises(mbe.MinimalBotEvaluationError) as exc:
        _mb_client().push_agent_evaluations(
            str(tmp_path),
            dry_run=True,
            only_globs=["evaluations/does-not-exist/*"],
        )
    assert "No evaluation sets matched" in str(exc.value)


def test_minimalbot_push_rejects_multiturn_case(tmp_path):
    # F-4: a MultiTurnEvaluationCase child must not be silently dropped — the
    # push fails rather than deploying a set that differs from local source.
    _write_eval_set(tmp_path, "compensation", kind="MultiTurnEvaluationCase")

    with pytest.raises(mbe.MinimalBotEvaluationError) as exc:
        _mb_client().push_agent_evaluations(str(tmp_path), dry_run=True)
    msg = str(exc.value)
    assert "multi-turn" in msg
    assert "only single-response EvaluationData" in msg


class _RecordingClient:
    """Fake MinimalBot client capturing the push/auth ordering for the gate."""

    def __init__(self):
        self.signed_in_username = "tester@example.com"
        self.authenticated = False
        self.real_push = False
        self.topic_updates = []

    def authenticate(self, preferred_username=None):
        self.authenticated = True
        self.preferred_username = preferred_username

    def push_agent_evaluations(
        self, agent_dir, *, dry_run=False, only_globs=None, plan=None,
    ):
        if dry_run:
            return {"dryRun": True, "sets": [
                {"folder": "compensation", "displayName": "compensation",
                 "testSetId": "plan-id", "cases": "1"}], "componentCount": 2}
        self.real_push = True
        assert plan["sets"][0]["testSetId"] == "plan-id"
        return {"dryRun": False, "status": "pushed", "sets": [
            {"folder": "compensation", "displayName": "compensation",
             "testSetId": "plan-id", "cases": "1"}],
            "componentCount": 2, "verifiedComponents": 2}

    def update_dialog_components(self, updates):
        self.topic_updates = updates
        return {
            "updatedComponents": len(updates),
            "verifiedComponents": len(updates),
        }


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr(
        push.MinimalBotEvaluationClient, "from_config",
        classmethod(lambda cls, config: fake),
    )


def test_minimalbot_push_prompts_before_mutating(tmp_path, monkeypatch, capsys):
    # F-2: the script-level confirmation gate must run BEFORE any mutation.
    # Answering "no" cancels without authenticating or pushing for real.
    _write_eval_set(tmp_path, "compensation")
    fake = _RecordingClient()
    _patch_client(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "no")

    push._minimalbot_push(_minimalbot_config(str(tmp_path)), auto_yes=False)

    out = capsys.readouterr().out
    assert "Push cancelled." in out
    assert fake.authenticated is False
    assert fake.real_push is False


def test_minimalbot_push_yes_flag_bypasses_prompt(tmp_path, monkeypatch, capsys):
    # F-2: --yes preserves its bypass semantics for the MinimalBot transport.
    _write_eval_set(tmp_path, "compensation")
    fake = _RecordingClient()
    _patch_client(monkeypatch, fake)

    def _no_input(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("input() must not be called when --yes is set")

    monkeypatch.setattr("builtins.input", _no_input)

    push._minimalbot_push(_minimalbot_config(str(tmp_path)), auto_yes=True)

    out = capsys.readouterr().out
    assert fake.authenticated is True
    assert fake.real_push is True
    assert "Pushed 1 evaluation set(s)" in out


def test_minimalbot_dry_run_never_mutates(tmp_path, monkeypatch, capsys):
    # F-2: a dry run must remain non-mutating and must not prompt.
    _write_eval_set(tmp_path, "compensation")
    fake = _RecordingClient()
    _patch_client(monkeypatch, fake)

    def _no_input(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("dry run must not prompt")

    monkeypatch.setattr("builtins.input", _no_input)

    push._minimalbot_push(_minimalbot_config(str(tmp_path)), dry_run=True)

    out = capsys.readouterr().out
    assert "Dry run — no changes pushed" in out
    assert fake.authenticated is False
    assert fake.real_push is False


def _write_existing_topic_change(root):
    baseline = root / ".baseline" / "topics"
    working = root / "topics"
    baseline.mkdir(parents=True)
    working.mkdir(parents=True)
    baseline_body = "kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRedirect\n"
    working_body = (
        f"{baseline_body}"
        "  actions:\n"
        "    - kind: BeginDialog\n"
        "      dialog: contoso.topic.WorkdaySystemGetUserContextV2\n"
    )
    baseline.joinpath("Setusercontext.mcs.yml").write_text(
        baseline_body,
        encoding="utf-8",
    )
    working.joinpath("Setusercontext.mcs.yml").write_text(
        working_body,
        encoding="utf-8",
    )
    root.joinpath(".component-map.json").write_text(
        json.dumps(
            {
                "topics/Setusercontext.mcs.yml": {
                    "componentKind": "DialogComponent",
                    "componentId": "setup-topic",
                    "schemaName": "contoso.topic.Setusercontext",
                    "displayName": "[Admin] - User Context - Setup",
                }
            }
        ),
        encoding="utf-8",
    )


def _fake_topic_conversion(items):
    return [
        {
            "key": item["key"],
            "success": True,
            "elementType": "AdaptiveDialog",
            "objectModel": {
                "$kind": "AdaptiveDialog",
                "source": item["yaml"],
            },
        }
        for item in items
    ]


def _write_workday_topics(root, *, changed=False):
    baseline = root / ".baseline" / "topics"
    working = root / "topics"
    baseline.mkdir(parents=True)
    working.mkdir(parents=True)
    component_map = {}
    for index in (1, 2):
        path = f"topics/workday-{index}.mcs.yml"
        baseline_body = f"kind: AdaptiveDialog\nvalue: before-{index}\n"
        working_body = (
            f"kind: AdaptiveDialog\nvalue: after-{index}\n"
            if changed and index == 1
            else baseline_body
        )
        baseline.joinpath(f"workday-{index}.mcs.yml").write_text(
            baseline_body,
            encoding="utf-8",
        )
        working.joinpath(f"workday-{index}.mcs.yml").write_text(
            working_body,
            encoding="utf-8",
        )
        component_map[path] = {
            "componentKind": "DialogComponent",
            "componentId": f"workday-{index}",
            "schemaName": f"contoso.topic.WorkdayTopic{index}",
            "displayName": f"Workday Topic {index}",
        }
    root.joinpath(".component-map.json").write_text(
        json.dumps(component_map),
        encoding="utf-8",
    )
    return sorted(component_map)


def test_scoped_minimalbot_topic_dry_run_is_non_mutating(
    tmp_path, monkeypatch, capsys
):
    _write_existing_topic_change(tmp_path)
    fake = _RecordingClient()
    _patch_client(monkeypatch, fake)
    monkeypatch.setattr(push, "yaml_to_object_models", _fake_topic_conversion)

    push._minimalbot_push(
        _minimalbot_config(str(tmp_path)),
        dry_run=True,
        only_globs=["topics/Setusercontext.mcs.yml"],
    )

    out = capsys.readouterr().out
    assert "Would update 1 existing topic" in out
    assert fake.authenticated is False
    assert fake.topic_updates == []


def test_scoped_minimalbot_topic_push_pins_account_and_updates_baseline(
    tmp_path, monkeypatch
):
    _write_existing_topic_change(tmp_path)
    fake = _RecordingClient()
    _patch_client(monkeypatch, fake)
    monkeypatch.setattr(push, "yaml_to_object_models", _fake_topic_conversion)

    push._minimalbot_push(
        _minimalbot_config(str(tmp_path)),
        auto_yes=True,
        only_globs=["topics/Setusercontext.mcs.yml"],
        preferred_username="maker@contoso.com",
    )

    assert fake.authenticated is True
    assert fake.preferred_username == "maker@contoso.com"
    assert fake.topic_updates[0]["componentId"] == "setup-topic"
    assert (
        tmp_path / ".baseline" / "topics" / "Setusercontext.mcs.yml"
    ).read_text(encoding="utf-8") == (
        tmp_path / "topics" / "Setusercontext.mcs.yml"
    ).read_text(encoding="utf-8")


def test_scoped_minimalbot_topic_activation_does_not_require_content_diff(
    tmp_path,
):
    paths = _write_workday_topics(tmp_path)

    plan = push._minimalbot_topic_update_plan(
        str(tmp_path),
        paths,
        activate_topics=True,
        agent_schema="contoso",
    )

    assert len(plan) == 2
    assert all(entry["state"] == "Active" for entry in plan)
    assert all(entry["status"] == "Active" for entry in plan)
    assert all("requireCleanDiagnostics" not in entry for entry in plan)
    assert all("dialog" not in entry for entry in plan)


def test_minimalbot_activation_rejects_non_workday_topic(tmp_path):
    _write_existing_topic_change(tmp_path)

    with pytest.raises(
        mbe.MinimalBotEvaluationError,
        match="No mapped Workday dialog topics",
    ):
        push._minimalbot_topic_update_plan(
            str(tmp_path),
            ["topics/Setusercontext.mcs.yml"],
            activate_topics=True,
            agent_schema="contoso",
        )


def test_workday_topic_resolution_enforces_reviewed_ess_hr_count(tmp_path):
    _write_workday_topics(tmp_path)
    component_map_path = tmp_path / ".component-map.json"
    component_map = json.loads(component_map_path.read_text(encoding="utf-8"))
    reviewed = (
        "EmployeeUpdatePhoneNumber",
        "GetReferenceData",
    )
    for entry, suffix in zip(component_map.values(), reviewed, strict=True):
        entry["schemaName"] = (
            "gptagent_copilotforemployeeselfservicehr.topic."
            + suffix
        )
    component_map_path.write_text(
        json.dumps(component_map),
        encoding="utf-8",
    )

    with pytest.raises(
        mbe.MinimalBotEvaluationError,
        match="reviewed 23-topic",
    ):
        mbe.resolve_workday_dialogs(
            tmp_path,
            "gptagent_copilotforemployeeselfservicehr",
        )


def test_workday_topic_resolution_uses_exact_reviewed_hr_inventory(tmp_path):
    schema = "gptagent_copilotforemployeeselfservicehr"
    expected_topics = frozenset(
        json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "fixtures"
                / "workday_hr_reviewed_topics.json"
            ).read_text(encoding="utf-8")
        )
    )
    assert mbe._REVIEWED_WORKDAY_TOPIC_SUFFIXES[schema] == expected_topics
    component_map = {}
    for index, suffix in enumerate(
        sorted(expected_topics),
        start=1,
    ):
        path = f"topics/workday-{index}.mcs.yml"
        tmp_path.joinpath(path).parent.mkdir(parents=True, exist_ok=True)
        tmp_path.joinpath(path).write_text(
            "kind: AdaptiveDialog\n",
            encoding="utf-8",
        )
        component_map[path] = {
            "componentKind": "DialogComponent",
            "componentId": f"workday-{index}",
            "schemaName": f"{schema}.topic.{suffix}",
            "displayName": f"Workday {suffix}",
        }
    handoff_path = "topics/employee-handoff.mcs.yml"
    tmp_path.joinpath(handoff_path).write_text(
        "kind: AdaptiveDialog\n",
        encoding="utf-8",
    )
    component_map[handoff_path] = {
        "componentKind": "DialogComponent",
        "componentId": "employee-handoff",
        "schemaName": f"{schema}.topic.WorkdayEmployeeScenariosHandoff",
        "displayName": "Workday Employee Scenarios Handoff",
    }
    tmp_path.joinpath(".component-map.json").write_text(
        json.dumps(component_map),
        encoding="utf-8",
    )

    resolved = mbe.resolve_workday_dialogs(tmp_path, schema)

    assert len(resolved) == 23
    schemas = {entry["schemaName"] for entry in resolved}
    assert f"{schema}.topic.EmployeeUpdatePhoneNumber" in schemas
    assert f"{schema}.topic.GetReferenceData" in schemas
    assert f"{schema}.topic.WorkdayEmployeeScenariosHandoff" not in schemas


def test_minimalbot_activation_rejects_local_topic_content_changes(
    tmp_path,
    monkeypatch,
):
    paths = _write_workday_topics(tmp_path, changed=True)
    baseline_workflow = tmp_path / ".baseline" / "workflows" / "flow.json"
    working_workflow = tmp_path / "workflows" / "flow.json"
    baseline_workflow.parent.mkdir(parents=True)
    working_workflow.parent.mkdir(parents=True)
    baseline_workflow.write_text('{"state":"before"}', encoding="utf-8")
    working_workflow.write_text('{"state":"unpushed"}', encoding="utf-8")
    fake = _RecordingClient()
    _patch_client(monkeypatch, fake)
    monkeypatch.setattr(push, "yaml_to_object_models", _fake_topic_conversion)

    with pytest.raises(
        SystemExit,
    ):
        push._minimalbot_push(
            _minimalbot_config(str(tmp_path)),
            auto_yes=True,
            only_globs=["*"],
            activate_topics=True,
            preferred_username="maker@contoso.com",
        )

    assert paths
    assert fake.topic_updates == []
    assert baseline_workflow.read_text(encoding="utf-8") == (
        '{"state":"before"}'
    )


def test_minimalbot_dialog_update_uses_update_envelope_and_verifies(
    monkeypatch,
):
    client = _mb_client()
    client._token = "token"
    before_component = {
        "$kind": "DialogComponent",
        "id": "setup-topic",
        "schemaName": "contoso.topic.Setusercontext",
        "dialog": {"$kind": "AdaptiveDialog", "state": "before"},
    }
    desired_dialog = {"$kind": "AdaptiveDialog", "state": "after"}
    after_component = {
        **before_component,
        "dialog": {
            **desired_dialog,
            "diagnostics": [{"$kind": "Informational"}],
        },
    }
    reads = iter(
        (
            {
                "changeToken": "token-1",
                "botComponentChanges": [
                    {
                        "$kind": "BotComponentInsert",
                        "component": before_component,
                    }
                ],
            },
            {
                "changeToken": "token-2",
                "botComponentChanges": [
                    {
                        "$kind": "BotComponentInsert",
                        "component": after_component,
                    }
                ],
            },
        )
    )
    monkeypatch.setattr(client, "read_components", lambda: next(reads))
    captured = {}

    def request(method, url, *, body, operation):
        captured.update(
            method=method,
            url=url,
            body=body,
            operation=operation,
        )
        return SimpleNamespace(status_code=200), {}

    monkeypatch.setattr(client, "_request", request)

    result = client.update_dialog_components(
        [
            {
                "componentId": "setup-topic",
                "schemaName": "contoso.topic.Setusercontext",
                "expectedDialog": before_component["dialog"],
                "dialog": desired_dialog,
            }
        ]
    )

    assert result["verifiedComponents"] == 1
    assert captured["method"] == "PUT"
    assert captured["body"]["changeToken"] == "token-1"
    assert captured["body"]["botComponentChanges"][0]["$kind"] == (
        "BotComponentUpdate"
    )


def test_minimalbot_dialog_activation_preserves_content(monkeypatch):
    client = _mb_client()
    client._token = "token"
    dialog = {"$kind": "AdaptiveDialog"}
    before_component = {
        "$kind": "DialogComponent",
        "id": "setup-topic",
        "schemaName": "contoso.topic.Setusercontext",
        "state": "Inactive",
        "status": "Inactive",
        "dialog": dialog,
    }
    after_component = {
        **before_component,
        "state": "Active",
        "status": "Active",
    }
    reads = iter(
        (
            {
                "changeToken": "token-1",
                "botComponentChanges": [
                    {
                        "$kind": "BotComponentInsert",
                        "component": before_component,
                    }
                ],
            },
            {
                "changeToken": "token-2",
                "botComponentChanges": [
                    {
                        "$kind": "BotComponentInsert",
                        "component": after_component,
                    }
                ],
            },
        )
    )
    monkeypatch.setattr(client, "read_components", lambda: next(reads))
    captured = {}

    def request(_method, _url, *, body, operation):
        captured["body"] = body
        captured["operation"] = operation
        return SimpleNamespace(status_code=200), {}

    monkeypatch.setattr(client, "_request", request)

    result = client.update_dialog_components(
        [
            {
                "componentId": "setup-topic",
                "schemaName": "contoso.topic.Setusercontext",
                "state": "Active",
                "status": "Active",
            }
        ]
    )

    updated = captured["body"]["botComponentChanges"][0]["component"]
    assert result["verifiedComponents"] == 1
    assert updated["dialog"] == dialog
    assert updated["state"] == "Active"
    assert updated["status"] == "Active"


def test_minimalbot_activation_rejects_blocking_diagnostics(monkeypatch):
    client = _mb_client()
    client._token = "token"
    component = {
        "$kind": "DialogComponent",
        "id": "workday-topic",
        "schemaName": "contoso.topic.WorkdayTopic",
        "state": "Active",
        "status": "Active",
        "dialog": {
            "$kind": "AdaptiveDialog",
            "diagnostics": [
                {
                    "$kind": "InvalidReferenceError",
                    "errorCode": "NotFound",
                    "errorMessage": "CloudFlow not found",
                }
            ],
        },
    }
    monkeypatch.setattr(
        client,
        "read_components",
        lambda: {
            "changeToken": "token-1",
            "botComponentChanges": [
                {
                    "$kind": "BotComponentInsert",
                    "component": component,
                }
            ],
        },
    )

    with pytest.raises(
        mbe.MinimalBotEvaluationError,
        match="blocking diagnostics",
    ):
        client.verify_dialog_components(
            [
                {
                    "componentId": "workday-topic",
                    "schemaName": "contoso.topic.WorkdayTopic",
                    "state": "Active",
                    "status": "Active",
                    "requireCleanDiagnostics": True,
                }
            ]
        )


@pytest.mark.parametrize(
    "components",
    [
        [],
        [
            {
                "$kind": "DialogComponent",
                "id": "workday-topic",
                "schemaName": "contoso.topic.WorkdayTopic",
            },
            {
                "$kind": "DialogComponent",
                "id": "workday-topic",
                "schemaName": "contoso.topic.WorkdayTopic",
            },
        ],
    ],
)
def test_minimalbot_verification_rejects_missing_or_duplicate_ids(
    monkeypatch,
    components,
):
    client = _mb_client()
    client._token = "token"
    monkeypatch.setattr(
        client,
        "read_components",
        lambda: {
            "changeToken": "token-1",
            "botComponentChanges": [
                {"$kind": "BotComponentInsert", "component": component}
                for component in components
            ],
        },
    )

    with pytest.raises(
        mbe.MinimalBotEvaluationError,
        match="missing or duplicate component ID",
    ):
        client.verify_dialog_components(
            [
                {
                    "componentId": "workday-topic",
                    "schemaName": "contoso.topic.WorkdayTopic",
                }
            ]
        )


@pytest.mark.parametrize(
    "component",
    [
        {
            "$kind": "UnexpectedComponent",
            "id": "workday-topic",
            "schemaName": "contoso.topic.WorkdayTopic",
        },
        {
            "$kind": "DialogComponent",
            "id": "workday-topic",
            "schemaName": "contoso.topic.OtherTopic",
        },
    ],
)
def test_minimalbot_verification_rejects_kind_or_schema_drift(
    monkeypatch,
    component,
):
    client = _mb_client()
    client._token = "token"
    monkeypatch.setattr(
        client,
        "read_components",
        lambda: {
            "changeToken": "token-1",
            "botComponentChanges": [
                {
                    "$kind": "BotComponentInsert",
                    "component": component,
                }
            ],
        },
    )

    with pytest.raises(
        mbe.MinimalBotEvaluationError,
        match="verification failed",
    ):
        client.verify_dialog_components(
            [
                {
                    "componentId": "workday-topic",
                    "schemaName": "contoso.topic.WorkdayTopic",
                }
            ]
        )


def test_minimalbot_activation_reports_diagnostics_without_rejecting(
    monkeypatch,
):
    client = _mb_client()
    client._token = "token"
    component = {
        "$kind": "DialogComponent",
        "id": "workday-topic",
        "schemaName": "contoso.topic.WorkdayTopic",
        "state": "Active",
        "status": "Active",
        "dialog": {
            "$kind": "AdaptiveDialog",
            "diagnostics": [
                {
                    "$kind": "InvalidReferenceError",
                    "errorCode": "NotFound",
                    "errorMessage": "CloudFlow not found",
                }
            ],
        },
    }
    monkeypatch.setattr(
        client,
        "read_components",
        lambda: {
            "changeToken": "token-1",
            "botComponentChanges": [
                {
                    "$kind": "BotComponentInsert",
                    "component": component,
                }
            ],
        },
    )

    result = client.verify_dialog_components(
        [
            {
                "componentId": "workday-topic",
                "schemaName": "contoso.topic.WorkdayTopic",
                "state": "Active",
                "status": "Active",
            }
        ]
    )

    assert result["verifiedComponents"] == 1
    assert result["activeComponents"] == 1
    assert result["blockingDiagnostics"] == [
        {
            "path": "$.dialog.diagnostics[0]",
            "kind": "InvalidReferenceError",
            "errorCode": "NotFound",
            "message": "CloudFlow not found",
            "referenceType": "",
            "referenceId": "",
            "componentId": "workday-topic",
            "schemaName": "contoso.topic.WorkdayTopic",
        }
    ]
