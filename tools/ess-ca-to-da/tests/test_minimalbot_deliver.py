"""Tests for the live MinimalBot components delivery path (the prod-capable writer)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest

from essmig.minimalbot_deliver import (
    DEFAULT_RING,
    INSERT_KIND,
    DeliveryError,
    MinimalBotTarget,
    OnTargetComponent,
    deliver_minimalbot,
    environment_host,
    existing_component_ids,
    existing_components,
    overlay_edits,
    parse_agent_url,
    plan_bot_entity_update,
    plan_changes,
    ring_for_endpoint,
    scope_for_ring,
)

_BOT = "33333333-3333-3333-3333-333333333333"
_ENV = "22222222-2222-2222-2222-222222222222"
_TENANT = "11111111-1111-1111-1111-111111111111"


class _StaticToken:
    def __init__(self, token: str = "token-abc") -> None:
        self._token = token
        self.scopes_seen: list[object] = []

    def get_token(self, scopes: object = None) -> str:
        self.scopes_seen.append(scopes)
        return self._token


class _FailingToken:
    def get_token(self, scopes: object = None) -> str:
        raise RuntimeError("no account")


@dataclass
class _Result:
    schemaname: str
    outcome: str


def _target(**overrides: object) -> MinimalBotTarget:
    values: dict[str, object] = {
        "bot_id": _BOT,
        "environment_id": _ENV,
        "tenant_id": _TENANT,
    }
    values.update(overrides)
    return MinimalBotTarget(**values)  # type: ignore[arg-type]


def _agent() -> dict[str, object]:
    # The merged agent.yml: compact ALM form. "Edited" is a shipped topic the
    # customer tweaked (plain-text modelDescription edit); "BrandNew" has no
    # template counterpart; "Untouched" is a component the migration left alone.
    return {
        "kind": "BotDefinition",
        "components": [
            {
                "kind": "DialogComponent",
                "id": "aaaaaaaa-0000-0000-0000-000000000001",
                "schemaName": "agent.topic.Edited",
                "dialog": {
                    "modelDescription": "customer edited description",
                    "beginDialog": {"kind": "OnRedirect"},
                },
            },
            {
                "kind": "DialogComponent",
                "id": "aaaaaaaa-0000-0000-0000-000000000002",
                "schemaName": "agent.topic.BrandNew",
                "dialog": {"beginDialog": {"kind": "OnRedirect"}},
            },
            {
                "kind": "GlobalVariableComponent",
                "schemaName": "agent.var.Untouched",
            },
        ],
    }


def _live_edited() -> dict[str, object]:
    # The "Edited" topic as the components API returns it: expanded runtime form.
    return {
        "$kind": "DialogComponent",
        "id": "server-id-1",
        "version": 3,
        "schemaName": "agent.topic.Edited",
        "dialog": {
            "$kind": "AdaptiveDialog",
            "modelDescription": "template description",
            "beginDialog": {"$kind": "OnRedirect"},
        },
    }


def _existing() -> dict[str, OnTargetComponent]:
    return {
        "agent.topic.Edited": OnTargetComponent(
            id="server-id-1", version=3, body=_live_edited()
        )
    }


def _results() -> list[_Result]:
    return [
        _Result("agent.topic.Edited", "merged"),
        _Result("agent.topic.BrandNew", "carried-new"),
        _Result("agent.var.Untouched", "unchanged"),
    ]


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


# --- ring / host / scope ----------------------------------------------------


@pytest.mark.parametrize(
    ("endpoint", "ring"),
    [
        ("https://x.environment.api.powerplatform.com", "prod"),
        ("https://x.environment.api.preprod.powerplatform.com", "preprod"),
        ("https://x.environment.api.test.powerplatform.com", "test"),
        ("", "prod"),
        (None, "prod"),
        ("https://unknown.example.com", "prod"),
    ],
)
def test_ring_is_derived_and_defaults_to_prod(endpoint: str | None, ring: str) -> None:
    assert ring_for_endpoint(endpoint) == ring


def test_scope_is_the_rings_minimalbot_scope() -> None:
    assert scope_for_ring("prod") == (
        "https://api.powerplatform.com/CopilotStudio.MinimalBot.ReadWrite"
    )
    assert scope_for_ring("test") == (
        "https://api.test.powerplatform.com/CopilotStudio.MinimalBot.ReadWrite"
    )


def _resolve_primary(hostname: str, port: int) -> None:
    """A fake DNS resolver that only the ring's primary split resolves against."""
    # prod primary split is 30: first label is 30 hex chars, second is 2.
    first = hostname.split(".", 1)[0]
    if len(first) != 30:
        raise OSError("name does not resolve")


def test_environment_host_splits_the_guid_per_ring() -> None:
    host = environment_host(_ENV, "prod", resolver=_resolve_primary)
    assert host.startswith("https://")
    assert host.endswith(".environment.api.powerplatform.com")
    # The primary (30) split is used when it resolves.
    assert host == f"https://{_ENV.replace('-', '')[:30]}.{_ENV.replace('-', '')[30:]}"\
        ".environment.api.powerplatform.com"


def test_environment_host_falls_back_to_the_other_split_when_primary_misses() -> None:
    # Only the 31 split resolves — the deriver must try the second candidate.
    def resolve_secondary(hostname: str, port: int) -> None:
        if len(hostname.split(".", 1)[0]) != 31:
            raise OSError("name does not resolve")

    host = environment_host(_ENV, "prod", resolver=resolve_secondary)
    compact = _ENV.replace("-", "")
    assert host == f"https://{compact[:31]}.{compact[31:]}"\
        ".environment.api.powerplatform.com"


def test_environment_host_falls_back_to_primary_when_offline() -> None:
    def always_fail(hostname: str, port: int) -> None:
        raise OSError("offline")

    host = environment_host(_ENV, "prod", resolver=always_fail)
    compact = _ENV.replace("-", "")
    assert host == f"https://{compact[:30]}.{compact[30:]}"\
        ".environment.api.powerplatform.com"


# --- target -----------------------------------------------------------------


def test_components_url_follows_the_documented_path() -> None:
    target = _target()
    assert target.components_url == (
        f"{target.host}/copilotstudio/minimalBots/api/{_BOT}/components"
        f"?api-version={target.api_version}"
    )


def test_default_ring_is_prod() -> None:
    assert _target().ring == DEFAULT_RING == "prod"


@pytest.mark.parametrize(
    "overrides",
    [
        {"bot_id": "not-a-guid"},
        {"environment_id": "nope"},
        {"tenant_id": ""},
        {"ring": "staging"},
    ],
)
def test_a_malformed_target_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(DeliveryError):
        _target(**overrides)


# --- change-set construction ------------------------------------------------


def test_overlay_writes_a_plain_scalar_edit_without_mutating_live() -> None:
    live = {"$kind": "GptComponent", "gpt": {"instructions": "ship text", "name": "x"}}
    merged = {"kind": "GptComponent", "gpt": {"instructions": "customer text", "name": "x"}}
    patched, notes = overlay_edits(live, merged)
    assert patched["gpt"]["instructions"] == "customer text"
    assert patched["gpt"]["name"] == "x"
    assert notes == []
    # The source live component is never mutated in place.
    assert live["gpt"]["instructions"] == "ship text"


def test_overlay_aligns_list_items_by_property_name() -> None:
    live = {
        "dialog": {
            "inputs": [
                {"$kind": "AutomaticTaskInput", "propertyName": "State", "description": "old"},
                {"$kind": "AutomaticTaskInput", "propertyName": "Comment", "description": "c"},
            ]
        }
    }
    # Same items, reordered, with only State's description edited.
    merged = {
        "dialog": {
            "inputs": [
                {"kind": "AutomaticTaskInput", "propertyName": "Comment", "description": "c"},
                {"kind": "AutomaticTaskInput", "propertyName": "State", "description": "new"},
            ]
        }
    }
    patched, notes = overlay_edits(live, merged)
    by_name = {i["propertyName"]: i for i in patched["dialog"]["inputs"]}
    assert by_name["State"]["description"] == "new"
    assert by_name["Comment"]["description"] == "c"
    assert notes == []


def test_overlay_leaves_an_unchanged_expression_field_without_a_note() -> None:
    # A compact literal over a ValueExpression that carries the same literal is not
    # an edit — it must not be flagged.
    live = {"value": {"$kind": "ValueExpression", "literalValue": "UserContextLog"}}
    merged = {"value": "UserContextLog"}
    patched, notes = overlay_edits(live, merged)
    assert patched["value"] == {"$kind": "ValueExpression", "literalValue": "UserContextLog"}
    assert notes == []


def test_overlay_matches_a_variable_reference_expression() -> None:
    live = {"value": {"$kind": "ValueExpression", "variableReference": "System.User.FirstName"}}
    merged = {"value": "=System.User.FirstName"}
    _, notes = overlay_edits(live, merged)
    assert notes == []


def test_overlay_notes_an_edit_to_an_expression_field_it_cannot_compile() -> None:
    live = {"value": {"$kind": "ValueExpression", "literalValue": "UserContextLog"}}
    merged = {"value": "EditedValue"}
    patched, notes = overlay_edits(live, merged)
    # The live expression is preserved (we cannot compile the edit) and it is noted.
    assert patched["value"] == {"$kind": "ValueExpression", "literalValue": "UserContextLog"}
    assert notes and "expression field" in notes[0]


def test_overlay_silently_skips_a_package_only_field() -> None:
    # A field present in the package but absent on the live component is a
    # structural/template difference, not a customer text edit: left off, no note.
    live = {"dialog": {"beginDialog": {"$kind": "OnRedirect"}}}
    merged = {"dialog": {"beginDialog": {"kind": "OnRedirect"}, "extra": "new"}}
    patched, notes = overlay_edits(live, merged)
    assert "extra" not in patched["dialog"]
    assert notes == []


def test_overlay_resolves_a_config_pointer_before_writing_it() -> None:
    # The display name resolves from config.values at ALM import; the live path
    # bypasses import, so the pointer must be resolved here (not written literally).
    live = {"$kind": "GptComponent", "displayName": "Template Name"}
    merged = {"kind": "GptComponent", "displayName": '${config.values["gptDisplayName"]}'}
    patched, notes = overlay_edits(live, merged, {"gptDisplayName": "ESS CR Agent"})
    assert patched["displayName"] == "ESS CR Agent"
    assert notes == []


def test_overlay_leaves_an_unresolved_config_pointer_on_the_live_value() -> None:
    live = {"$kind": "GptComponent", "displayName": "Template Name"}
    merged = {"kind": "GptComponent", "displayName": '${config.values["missing"]}'}
    patched, notes = overlay_edits(live, merged, {})
    assert patched["displayName"] == "Template Name"
    assert notes and "config pointer" in notes[0]


def _template_line(*parts: object) -> dict[str, object]:
    """Build a TemplateLine from alternating text / variableReference tokens."""
    segments: list[dict[str, object]] = []
    for index, part in enumerate(parts):
        if index % 2 == 0:
            segments.append({"$kind": "TextSegment", "value": part})
        else:
            segments.append(
                {
                    "$kind": "ExpressionSegment",
                    "expression": {"$kind": "ValueExpression", "variableReference": part},
                }
            )
    return {"$kind": "TemplateLine", "segments": segments}


def test_overlay_applies_a_prose_edit_to_instructions_reusing_live_expressions() -> None:
    live = {
        "metadata": {
            "instructions": _template_line(
                "escalate to HR when needed. Name ", "System.User.Name", " end"
            )
        }
    }
    merged = {
        "metadata": {
            "instructions": (
                "escalate to Colleague Resources when needed. Name {System.User.Name} end"
            )
        }
    }
    patched, notes = overlay_edits(live, merged)
    segments = patched["metadata"]["instructions"]["segments"]
    assert segments[0]["value"] == "escalate to Colleague Resources when needed. Name "
    # The expression object is reused verbatim (never fabricated from the string).
    assert segments[1] == {
        "$kind": "ExpressionSegment",
        "expression": {"$kind": "ValueExpression", "variableReference": "System.User.Name"},
    }
    assert segments[2]["value"] == " end"
    assert notes == []


def test_overlay_instructions_rebuilds_with_fabricated_newer_tokens() -> None:
    # The target is an older template (one reference); the package has a newer one.
    # The customer's full prose is carried AND the newer reference is fabricated by
    # cloning the live segment's shape (proven accepted by the components API).
    live = {
        "metadata": {
            "instructions": _template_line("Core: HR. ", "System.User.Name", " tail ")
        }
    }
    merged = {
        "metadata": {
            "instructions": (
                "Core: Colleague Resources. {System.User.Name} tail {Global.CurrentDate}!"
            )
        }
    }
    patched, notes = overlay_edits(live, merged)
    segments = patched["metadata"]["instructions"]["segments"]
    assert segments[0]["value"] == "Core: Colleague Resources. "
    # The matching leading token reuses the live object; the newer token is
    # fabricated with the same shape; the full tail prose is carried.
    expr_tokens = [
        s["expression"]["variableReference"]
        for s in segments
        if s["$kind"] == "ExpressionSegment"
    ]
    assert expr_tokens == ["System.User.Name", "Global.CurrentDate"]
    assert segments[-1]["value"] == "!"
    assert notes == []
    # Round-trip: the rebuilt line reproduces the merged instructions exactly.
    flat = ""
    for seg in segments:
        if seg["$kind"] == "TextSegment":
            flat += seg["value"]
        else:
            flat += "{" + seg["expression"]["variableReference"] + "}"
    assert flat == merged["metadata"]["instructions"]


def test_plan_overlays_shipped_topics_live_and_defers_new_topics() -> None:
    changes, planned, deferred, notes = plan_changes(_agent(), _results(), _existing())

    # Only the shipped topic the customer edited is sent live, as an overlay.
    assert [p.schema_name for p in planned] == ["agent.topic.Edited"]
    assert [p.action for p in planned] == ["update"]
    # The brand-new topic has no live counterpart -> routed to the package import.
    assert [d.schema_name for d in deferred] == ["agent.topic.BrandNew"]
    assert [d.action for d in deferred] == ["package"]
    # The untouched component is never considered either way.
    touched = {p.schema_name for p in planned} | {d.schema_name for d in deferred}
    assert "agent.var.Untouched" not in touched
    assert notes == []  # the only edit (modelDescription) is a plain scalar

    change = changes[0]
    assert change["$kind"] == INSERT_KIND
    component = change["component"]
    # Addressed at the live component's id and CURRENT version (upsert).
    assert component["id"] == "server-id-1"
    assert component["version"] == 3
    assert component["extensionData"] == {"UseProvidedBotComponentId": True}
    # The body STARTED from the live (expanded) component, with the customer's
    # plain-text edit overlaid onto it — not the compact agent.yml entry.
    assert component["$kind"] == "DialogComponent"
    assert component["dialog"]["$kind"] == "AdaptiveDialog"
    assert component["dialog"]["modelDescription"] == "customer edited description"
    assert component["dialog"]["beginDialog"]["$kind"] == "OnRedirect"


def test_existing_component_ids_maps_schema_to_id() -> None:
    body = {
        "botComponentChanges": [
            {"component": {"schemaName": "a", "id": "id-a"}},
            {"component": {"schemaName": "b", "id": "id-b"}},
            {"notAComponent": True},
        ]
    }
    assert existing_component_ids(body) == {"a": "id-a", "b": "id-b"}


def test_existing_components_captures_id_version_and_body() -> None:
    body = {
        "botComponentChanges": [
            {"component": {"schemaName": "a", "id": "id-a", "version": 4}},
            {"component": {"schemaName": "b", "id": "id-b"}},  # missing version -> 1
            {"notAComponent": True},
        ]
    }
    got = existing_components(body)
    assert got == {
        "a": OnTargetComponent(
            id="id-a", version=4, body={"schemaName": "a", "id": "id-a", "version": 4}
        ),
        "b": OnTargetComponent(
            id="id-b", version=1, body={"schemaName": "b", "id": "id-b"}
        ),
    }


# --- delivery orchestration -------------------------------------------------


def _read_body() -> dict[str, object]:
    return {
        "changeToken": "tok-1",
        "botComponentChanges": [
            {
                "component": {
                    "schemaName": "agent.topic.Edited",
                    "id": "server-id-1",
                    "version": 3,
                    "$kind": "DialogComponent",
                    "dialog": {
                        "$kind": "AdaptiveDialog",
                        "modelDescription": "template description",
                        "beginDialog": {"$kind": "OnRedirect"},
                    },
                }
            }
        ],
    }


def test_dry_run_reads_classifies_and_writes_nothing() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        assert request.method == "POST"  # never a PUT in dry-run
        return httpx.Response(200, json=_read_body())

    result = deliver_minimalbot(
        _target(),
        _agent(),
        _results(),
        _StaticToken(),
        dry_run=True,
        client=_client(httpx.MockTransport(handler)),
    )

    assert result.ok and result.dry_run
    assert "PUT" not in calls
    # One shipped-topic overlay prepared; the brand-new topic is deferred to the package.
    assert result.updated == 1
    assert result.inserted == 0
    assert [d.schema_name for d in result.deferred] == ["agent.topic.BrandNew"]


def test_apply_puts_under_the_change_token_and_verifies() -> None:
    seen: dict[str, object] = {}
    reads = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            reads["n"] += 1
            if reads["n"] == 1:
                return httpx.Response(200, json=_read_body())
            # verification read: the overlaid shipped topic is present
            return httpx.Response(
                200,
                json={
                    "changeToken": "tok-2",
                    "botComponentChanges": [
                        {"component": {"schemaName": "agent.topic.Edited", "id": "server-id-1"}},
                    ],
                },
            )
        seen["token"] = request.url  # PUT
        import json as _json

        body = _json.loads(request.content)
        seen["changeToken"] = body["changeToken"]
        seen["count"] = len(body["botComponentChanges"])
        return httpx.Response(200, json={})

    result = deliver_minimalbot(
        _target(),
        _agent(),
        _results(),
        _StaticToken(),
        dry_run=False,
        client=_client(httpx.MockTransport(handler)),
    )

    assert result.ok and not result.dry_run
    assert seen["changeToken"] == "tok-1"
    # Only the shipped-topic overlay is PUT; the brand-new topic is deferred.
    assert seen["count"] == 1
    assert result.updated == 1 and result.inserted == 0
    assert [d.schema_name for d in result.deferred] == ["agent.topic.BrandNew"]


def test_apply_reports_verification_miss() -> None:
    reads = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            reads["n"] += 1
            if reads["n"] == 1:
                return httpx.Response(200, json=_read_body())
            # verification read: the overlaid component is now absent
            return httpx.Response(
                200, json={"changeToken": "tok-2", "botComponentChanges": []}
            )
        return httpx.Response(200, json={})

    result = deliver_minimalbot(
        _target(),
        _agent(),
        _results(),
        _StaticToken(),
        dry_run=False,
        client=_client(httpx.MockTransport(handler)),
    )

    assert not result.ok
    assert "verification" in result.detail


def test_a_rejected_write_is_captured_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_read_body())
        return httpx.Response(409, json={"error": {"message": "stale change token"}})

    result = deliver_minimalbot(
        _target(),
        _agent(),
        _results(),
        _StaticToken(),
        dry_run=False,
        client=_client(httpx.MockTransport(handler)),
    )

    assert not result.ok
    assert result.status == 409
    assert "stale change token" in result.detail


def test_nothing_to_deliver_when_no_customizations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_read_body())

    results = [_Result("agent.var.Untouched", "unchanged")]
    result = deliver_minimalbot(
        _target(),
        _agent(),
        results,
        _StaticToken(),
        dry_run=False,
        client=_client(httpx.MockTransport(handler)),
    )

    assert result.ok
    assert "nothing to deliver" in result.detail


def test_a_failing_token_is_captured_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_read_body())

    result = deliver_minimalbot(
        _target(),
        _agent(),
        _results(),
        _FailingToken(),
        dry_run=True,
        client=_client(httpx.MockTransport(handler)),
    )

    assert not result.ok
    assert result.deferred  # every customized topic routes to the package import


def test_the_ring_scope_is_requested_for_the_token() -> None:
    token = _StaticToken()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_read_body())

    deliver_minimalbot(
        _target(ring="test"),
        _agent(),
        _results(),
        token,
        dry_run=True,
        client=_client(httpx.MockTransport(handler)),
    )

    assert "https://api.test.powerplatform.com/CopilotStudio.MinimalBot.ReadWrite" \
        in token.scopes_seen


# --- botId / environment targeting from the Copilot Studio URL ---------------


_URL_ENV = "aff216bc-791e-ec17-b348-556f8374a207"
_URL_BOT = "a43d3c12-edee-473a-be89-249407e1b6ec"


def test_parse_agent_url_extracts_env_and_bot_from_a_copilots_url() -> None:
    url = (
        "https://copilotstudio.microsoft.com/environments/"
        f"{_URL_ENV}/copilots/{_URL_BOT}/details?agentBackend=cosmos"
    )
    assert parse_agent_url(url) == (_URL_ENV, _URL_BOT)


def test_parse_agent_url_accepts_a_bots_path_too() -> None:
    url = (
        "https://copilotstudio.microsoft.com/environments/"
        f"{_URL_ENV}/bots/{_URL_BOT}/overview"
    )
    assert parse_agent_url(url) == (_URL_ENV, _URL_BOT)


def test_parse_agent_url_rejects_a_url_without_both_guids() -> None:
    with pytest.raises(DeliveryError, match="could not find an environment id"):
        parse_agent_url("https://copilotstudio.microsoft.com/environments/foo/copilots/bar")


# --- bot-entity rename (main-panel name) ------------------------------------


def test_plan_bot_entity_update_renames_and_resolves_a_config_pointer() -> None:
    agent = {"entity": {"displayName": '${config.values["botName"]}'}}
    read_body = {"bot": {"displayName": "Old Name", "schemaName": "gpt_x"}}
    patched, new_name = plan_bot_entity_update(
        agent, read_body, {"botName": "ESS CR Agent"}
    )
    assert new_name == "ESS CR Agent"
    assert patched is not None
    assert patched["displayName"] == "ESS CR Agent"
    # Live entity is not mutated and other fields are carried verbatim.
    assert read_body["bot"]["displayName"] == "Old Name"
    assert patched["schemaName"] == "gpt_x"


def test_plan_bot_entity_update_is_a_noop_when_the_name_is_unchanged() -> None:
    agent = {"entity": {"displayName": "ESS CR Agent"}}
    read_body = {"bot": {"displayName": "ESS CR Agent"}}
    assert plan_bot_entity_update(agent, read_body, {}) == (None, None)


def test_plan_bot_entity_update_is_a_noop_on_an_unresolved_pointer() -> None:
    agent = {"entity": {"displayName": '${config.values["botName"]}'}}
    read_body = {"bot": {"displayName": "Old Name"}}
    assert plan_bot_entity_update(agent, read_body, {}) == (None, None)


def test_plan_bot_entity_update_is_a_noop_when_the_read_has_no_bot() -> None:
    agent = {"entity": {"displayName": "ESS CR Agent"}}
    assert plan_bot_entity_update(agent, {}, {}) == (None, None)


def test_apply_renames_the_bot_entity_via_the_put_body() -> None:
    seen: dict[str, object] = {}
    reads = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            reads["n"] += 1
            if reads["n"] == 1:
                body = _read_body()
                body["bot"] = {"displayName": "Old Name", "schemaName": "gpt_x"}
                return httpx.Response(200, json=body)
            return httpx.Response(
                200,
                json={
                    "changeToken": "tok-2",
                    "botComponentChanges": [
                        {"component": {"schemaName": "agent.topic.Edited", "id": "server-id-1"}},
                    ],
                },
            )
        import json as _json

        body = _json.loads(request.content)
        seen["bot"] = body.get("bot")
        return httpx.Response(200, json={})

    agent = _agent()
    agent["entity"] = {"displayName": '${config.values["botName"]}'}

    result = deliver_minimalbot(
        _target(),
        agent,
        _results(),
        _StaticToken(),
        dry_run=False,
        config_values={"botName": "ESS CR Agent"},
        client=_client(httpx.MockTransport(handler)),
    )

    assert result.ok and not result.dry_run
    assert result.renamed_to == "ESS CR Agent"
    assert isinstance(seen["bot"], dict)
    assert seen["bot"]["displayName"] == "ESS CR Agent"  # type: ignore[index]

