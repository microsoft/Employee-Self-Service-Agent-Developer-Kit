# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Graph audience discovery, eligibility, and metadata hydration."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from portalocker.exceptions import LockException


REPO_ROOT = Path(__file__).parents[3]
ORG_ANNOUNCEMENTS_DIR = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_org_announcements"
)
# Sibling MCP servers share the top-level names ``client``/``server``, so the
# modules are loaded through the shared isolated importer rather than by a plain
# ``import`` off ``sys.path``. See tests/mcp/_mcp_modules.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _mcp_modules import load_org_announcements_directory_modules  # noqa: E402

_ORG_MODULES = load_org_announcements_directory_modules()

graph = _ORG_MODULES["graph_directory_client"]
TENANT_ID = "00000000-0000-0000-0000-000000001111"
OTHER_TENANT_ID = "00000000-0000-0000-0000-000000002222"
OBJECT_ID = "00000000-0000-0000-0000-000000003333"
OTHER_OBJECT_ID = "00000000-0000-0000-0000-000000004444"


def _token(
    label: str = "test-token", tenant_id: str = TENANT_ID,
    object_id: str | None = OBJECT_ID,
) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": tenant_id, "nonce": label, "oid": object_id}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


def _make_client(handler) -> graph.GraphDirectoryClient:
    return graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(handler),
        access_token=_token(),
    )


def _group(
    group_id: str,
    *,
    display_name: str | None = None,
    mail: str | None = None,
    mail_enabled: bool = False,
    security_enabled: bool = True,
    group_types: list[str] | None = None,
) -> dict:
    return {
        "id": group_id,
        "displayName": display_name if display_name is not None else f"Group {group_id}",
        "mail": mail,
        "mailEnabled": mail_enabled,
        "securityEnabled": security_enabled,
        "groupTypes": group_types if group_types is not None else [],
    }


# --------------------------------------------------------------------------
# Eligibility predicate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("group", "eligible", "reason"),
    [
        (
            _group("sg", mail_enabled=False, security_enabled=True),
            True,
            "non-dynamic security group",
        ),
        (
            _group("mesg", mail="m@contoso.com", mail_enabled=True, security_enabled=True),
            True,
            "mail-enabled security group",
        ),
        (
            _group("dl", mail="dl@contoso.com", mail_enabled=True, security_enabled=False),
            True,
            "classic distribution group",
        ),
        (
            _group(
                "m365",
                mail="m365@contoso.com",
                mail_enabled=True,
                security_enabled=False,
                group_types=["Unified"],
            ),
            False,
            "Microsoft 365 / Unified group",
        ),
        (
            _group(
                "m365-sec",
                mail_enabled=True,
                security_enabled=True,
                group_types=["Unified"],
            ),
            False,
            "Unified group with security enabled",
        ),
        (
            _group("dyn", security_enabled=True, group_types=["DynamicMembership"]),
            False,
            "dynamic-membership security group",
        ),
        (
            _group(
                "dyn-unified",
                mail_enabled=True,
                security_enabled=False,
                group_types=["Unified", "DynamicMembership"],
            ),
            False,
            "dynamic Microsoft 365 group",
        ),
        (
            _group("neither", mail_enabled=False, security_enabled=False),
            False,
            "neither mail- nor security-enabled",
        ),
        ({"id": "", "groupTypes": []}, False, "empty id"),
        ({"displayName": "no id", "groupTypes": []}, False, "missing id"),
        ({"id": "no-types"}, False, "missing groupTypes"),
        ("not-a-dict", False, "non-object"),
    ],
)
def test_eligibility_predicate(group, eligible, reason) -> None:
    assert graph.is_eligible_group(group) is eligible, reason


def test_eligibility_ignores_group_type_casing() -> None:
    assert graph.is_eligible_group(_group("a", group_types=["unified"])) is False
    assert (
        graph.is_eligible_group(_group("b", group_types=["dynamicmembership"])) is False
    )


# --------------------------------------------------------------------------
# Query escaping
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("Finance", "Finance"),
        ('say "hi"', 'say \\"hi\\"'),
        ("back\\slash", "back\\\\slash"),
        ('mix"and\\match', 'mix\\"and\\\\match'),
        ("  padded  ", "padded"),
    ],
)
def test_search_values_are_escaped_for_the_search_phrase(raw, escaped) -> None:
    assert graph.escape_search_value(raw) == escaped


@pytest.mark.parametrize("bad", ["", "   ", "with\nnewline", "with\x00null", "x" * 300])
def test_invalid_search_values_are_rejected(bad) -> None:
    with pytest.raises(ValueError):
        graph.escape_search_value(bad)


def test_search_sends_the_escaped_phrase_and_eventual_consistency() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"value": [_group("a")]})

    client = _make_client(handler)

    async def run() -> None:
        await client.search_groups('Finance "West"')
        await client.aclose()

    asyncio.run(run())

    params = parse_qs(urlsplit(str(captured[0].url)).query)
    assert len(captured) == 1
    assert params["$search"] == [
        '"displayName:Finance \\"West\\"" OR "mail:Finance \\"West\\""'
    ]
    assert params["$count"] == ["true"]
    assert params["$top"] == [str(graph.GRAPH_PAGE_SIZE)]
    assert captured[0].headers["ConsistencyLevel"] == "eventual"


# --------------------------------------------------------------------------
# Paging, bounding, dedupe, ordering
# --------------------------------------------------------------------------


def test_search_stops_after_twenty_eligible_results() -> None:
    pages: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pages.append(request)
        return httpx.Response(
            200,
            json={
                "value": [_group(f"p{len(pages)}-{index}") for index in range(30)],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/groups?$skiptoken=x",
            },
        )

    client = _make_client(handler)

    async def run() -> dict:
        result = await client.search_groups("finance")
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert len(result["groups"]) == graph.MAX_ELIGIBLE_RESULTS
    assert result["exhausted"] is False
    assert len(pages) == 1


def test_search_stops_at_the_three_page_cap_without_claiming_exhaustion() -> None:
    pages: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pages.append(request)
        # Only ineligible groups, so the eligible budget is never filled.
        return httpx.Response(
            200,
            json={
                "value": [
                    _group(f"m365-{len(pages)}", group_types=["Unified"])
                ],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/groups?$skiptoken=x",
            },
        )

    client = _make_client(handler)

    async def run() -> dict:
        result = await client.search_groups("finance")
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert len(pages) == graph.MAX_SEARCH_PAGES
    assert result["groups"] == []
    assert result["exhausted"] is False
    assert result["pagesExamined"] == graph.MAX_SEARCH_PAGES


def test_search_reports_exhaustion_when_the_result_set_ends() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [_group("a")]})

    client = _make_client(handler)

    async def run() -> dict:
        result = await client.search_groups("finance")
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result["exhausted"] is True
    assert [group["id"] for group in result["groups"]] == ["a"]


def test_search_follows_next_link_without_duplicating_query_options() -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if len(urls) == 1:
            return httpx.Response(
                200,
                json={
                    "value": [_group("a")],
                    "@odata.nextLink": (
                        "https://graph.microsoft.com/v1.0/groups?$skiptoken=abc"
                    ),
                },
            )
        return httpx.Response(200, json={"value": [_group("b")]})

    client = _make_client(handler)

    async def run() -> dict:
        result = await client.search_groups("finance")
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert urls[1] == "https://graph.microsoft.com/v1.0/groups?$skiptoken=abc"
    assert [group["id"] for group in result["groups"]] == ["a", "b"]


def test_search_dedupes_by_id_and_preserves_first_seen_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    _group("b", display_name="Beta"),
                    _group("a", display_name="Alpha"),
                    _group("b", display_name="Beta duplicate"),
                    _group("c", display_name="Gamma"),
                ]
            },
        )

    client = _make_client(handler)

    async def run() -> dict:
        result = await client.search_groups("finance")
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert [group["id"] for group in result["groups"]] == ["b", "a", "c"]
    assert result["groups"][0]["displayName"] == "Beta"


def test_search_results_carry_only_the_contract_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        **_group("a", display_name="Alpha", mail="a@contoso.com",
                                 mail_enabled=True),
                        "onPremisesSyncEnabled": True,
                        "description": "internal",
                    }
                ]
            },
        )

    client = _make_client(handler)

    async def run() -> dict:
        result = await client.search_groups("alpha")
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result["groups"] == [
        {
            "id": "a",
            "displayName": "Alpha",
            "mail": "a@contoso.com",
            "isValid": True,
        }
    ]


# --------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "AuthenticationRequired", False),
        (403, "AuthorizationDenied", False),
        (429, "SearchUnavailable", True),
        (503, "SearchUnavailable", True),
        (400, "SearchUnavailable", False),
    ],
)
def test_graph_http_failures_map_to_discriminated_codes(
    status, code, retryable
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": "x"}})

    client = _make_client(handler)

    async def run() -> None:
        with pytest.raises(graph.GraphDirectoryError) as caught:
            await client.search_groups("finance")
        assert caught.value.code == code
        assert caught.value.retryable is retryable
        await client.aclose()

    asyncio.run(run())


def test_graph_transport_failure_is_a_retryable_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    client = _make_client(handler)

    async def run() -> None:
        with pytest.raises(graph.GraphDirectoryError) as caught:
            await client.search_groups("finance")
        assert caught.value.code == "NetworkError"
        assert caught.value.retryable is True
        await client.aclose()

    asyncio.run(run())


def test_malformed_graph_payloads_are_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": "not-a-list"})

    client = _make_client(handler)

    async def run() -> None:
        with pytest.raises(graph.GraphDirectoryError) as caught:
            await client.search_groups("finance")
        assert caught.value.code == "SearchUnavailable"
        await client.aclose()

    asyncio.run(run())


# --------------------------------------------------------------------------
# Metadata hydration
# --------------------------------------------------------------------------


def test_resolve_groups_dedupes_only_the_lookup_batch() -> None:
    filters: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = parse_qs(urlsplit(str(request.url)).query)
        filters.append(params["$filter"][0])
        return httpx.Response(200, json={"value": [_group("g1"), _group("g2")]})

    client = _make_client(handler)

    async def run() -> dict:
        result = await client.resolve_groups(["g1", "g2", "g1", "g2", "g1"])
        await client.aclose()
        return result

    resolved = asyncio.run(run())

    assert filters == ["id eq 'g1' or id eq 'g2'"]
    assert set(resolved) == {"g1", "g2"}


def test_resolve_groups_skips_ids_that_would_break_the_filter() -> None:
    filters: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = parse_qs(urlsplit(str(request.url)).query)
        filters.append(params["$filter"][0])
        return httpx.Response(200, json={"value": [_group("g1")]})

    client = _make_client(handler)

    async def run() -> dict:
        result = await client.resolve_groups(["g1", "bad' or id eq 'x"])
        await client.aclose()
        return result

    resolved = asyncio.run(run())

    assert filters == ["id eq 'g1'"]
    assert set(resolved) == {"g1"}


def test_resolve_groups_excludes_ineligible_categories() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    _group("sg"),
                    _group("m365", group_types=["Unified"], mail_enabled=True),
                ]
            },
        )

    client = _make_client(handler)

    async def run() -> dict:
        result = await client.resolve_groups(["sg", "m365"])
        await client.aclose()
        return result

    resolved = asyncio.run(run())

    assert set(resolved) == {"sg"}


def test_hydration_preserves_order_multiplicity_and_invalid_ids() -> None:
    resolved = {
        "g1": {
            "id": "g1",
            "displayName": "Group One",
            "mail": "one@contoso.com",
            "isValid": True,
        }
    }

    metadata = graph.build_audience_metadata(["g1", "missing", "g1"], resolved)

    assert [group["id"] for group in metadata] == ["g1", "missing", "g1"]
    assert metadata[1]["isValid"] is False
    assert metadata[0]["isValid"] is True
    assert metadata[2]["displayName"] == "Group One"


def test_hydration_never_renders_a_raw_group_id_as_a_display_name() -> None:
    metadata = graph.build_audience_metadata(["11111111-2222-3333"], {})

    assert metadata[0]["id"] == "11111111-2222-3333"
    assert metadata[0]["displayName"] != "11111111-2222-3333"
    assert metadata[0]["displayName"]
    assert metadata[0]["mail"] is None


def test_hydration_of_an_empty_audience_is_empty() -> None:
    assert graph.build_audience_metadata([], {}) == []


# --------------------------------------------------------------------------
# Display-name fallback
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("display_name", "mail", "expected"),
    [
        ("Finance", "fin@contoso.com", "Finance"),
        ("Finance", None, "Finance"),
        ("  Finance  ", None, "Finance"),
        ("", "fin@contoso.com", "fin@contoso.com"),
        ("   ", "fin@contoso.com", "fin@contoso.com"),
        (None, "fin@contoso.com", "fin@contoso.com"),
        ("", "", graph.UNNAMED_GROUP_LABEL),
        (None, None, graph.UNNAMED_GROUP_LABEL),
        ("   ", "   ", graph.UNNAMED_GROUP_LABEL),
    ],
)
def test_display_name_falls_back_to_mail_then_a_neutral_label(
    display_name, mail, expected
) -> None:
    """A raw directory ID is never shown as a name.

    It is meaningless to the maker and it puts a tenant group identifier into
    the widget's visible surface.
    """
    group_id = "11111111-2222-3333-4444-555555555555"
    # Built inline rather than through ``_group``, which substitutes a default
    # display name for ``None`` and would hide the fallback under test.
    projected = graph.to_audience_group(
        {
            "id": group_id,
            "displayName": display_name,
            "mail": mail,
            "mailEnabled": False,
            "securityEnabled": True,
            "groupTypes": [],
        }
    )

    assert projected["displayName"] == expected
    assert projected["displayName"] != projected["id"]


def test_search_never_returns_a_raw_id_as_a_display_name() -> None:
    group_id = "11111111-2222-3333-4444-555555555555"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"value": [_group(group_id, display_name="", mail=None)]}
        )

    client = _make_client(handler)

    async def run() -> dict:
        result = await client.search_groups("anything")
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result["groups"][0]["displayName"] == graph.UNNAMED_GROUP_LABEL
    assert result["groups"][0]["mail"] is None


def test_hydration_never_returns_a_raw_id_as_a_display_name() -> None:
    group_id = "11111111-2222-3333-4444-555555555555"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": group_id,
                        "displayName": None,
                        "mail": "  ",
                        "mailEnabled": False,
                        "securityEnabled": True,
                        "groupTypes": [],
                    }
                ]
            },
        )

    client = _make_client(handler)

    async def run() -> dict:
        resolved = await client.resolve_groups([group_id])
        await client.aclose()
        return resolved

    resolved = asyncio.run(run())

    assert resolved[group_id]["displayName"] == graph.UNNAMED_GROUP_LABEL


# --------------------------------------------------------------------------
# Token cache location and acquisition behavior
# --------------------------------------------------------------------------


def test_the_graph_cache_is_the_shared_solution_root_cache() -> None:
    """One Graph cache for the whole ADK, not a per-server third cache."""
    expected = (
        REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / ".local"
        / ".token_cache.bin"
    )

    assert Path(graph.GRAPH_TOKEN_CACHE_PATH) == expected


def test_the_graph_cache_path_is_independent_of_the_working_directory(
    tmp_path,
) -> None:
    """The MCP server launches with cwd set to its own folder.

    A cwd-relative cache path would mint a private third cache there and force a
    second interactive sign-in for a maker who already signed in via /setup.
    Checked by importing the module fresh in a subprocess whose cwd is somewhere
    else entirely — reloading in-process would only re-run the same already
    imported module and would disturb state other tests share.
    """
    probe = (
        "import sys; sys.path.insert(0, %r);"
        "import graph_directory_client as g;"
        "print(g.GRAPH_TOKEN_CACHE_PATH)" % str(ORG_ANNOUNCEMENTS_DIR)
    )
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    from_foreign_cwd = Path(result.stdout.strip())

    assert from_foreign_cwd == Path(graph.GRAPH_TOKEN_CACHE_PATH)
    assert from_foreign_cwd.is_absolute()
    assert tmp_path not in from_foreign_cwd.parents


def test_constructing_the_client_acquires_no_token(monkeypatch) -> None:
    """Auth must be lazy: __init__ runs on the event loop."""
    calls: list[int] = []

    def _never(tenant_id, object_id) -> str:
        calls.append(1)
        raise AssertionError("token acquired during construction")

    monkeypatch.setattr(graph, "acquire_graph_token", _never)

    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"value": []})
        )
    )

    assert calls == []
    assert client._token == ""


def test_the_token_is_acquired_off_the_event_loop_on_first_use(monkeypatch) -> None:
    """A blocking MSAL sign-in must never run inside the running loop."""
    threads: list[int] = []

    def _acquire(tenant_id, object_id) -> str:
        assert tenant_id == TENANT_ID
        assert object_id == OBJECT_ID
        threads.append(threading.get_ident())
        return _token("lazy-token")

    monkeypatch.setattr(graph, "acquire_graph_token", _acquire)

    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"value": []})
        )
    )

    async def run() -> int:
        loop_thread = threading.get_ident()
        await client.search_groups("anything")
        await client.aclose()
        return loop_thread

    loop_thread = asyncio.run(run())

    assert len(threads) == 1
    assert threads[0] != loop_thread, "sign-in ran on the event loop thread"


def test_concurrent_first_calls_share_one_sign_in(monkeypatch) -> None:
    """Two racing tool calls must not open two browser prompts."""
    calls: list[int] = []

    def _acquire(tenant_id, object_id) -> str:
        assert tenant_id == TENANT_ID
        calls.append(1)
        return _token("lazy-token")

    monkeypatch.setattr(graph, "acquire_graph_token", _acquire)

    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"value": []})
        )
    )

    async def run() -> None:
        await asyncio.gather(
            client.search_groups("a"),
            client.search_groups("b"),
            client.resolve_groups(["11111111-2222-3333-4444-555555555555"]),
        )
        await client.aclose()

    asyncio.run(run())

    assert calls == [1]


def test_token_acquisition_writes_nothing_to_stdout_or_stderr(
    monkeypatch, tmp_path
) -> None:
    """stdout is the MCP JSON-RPC transport; a device code would corrupt it."""
    interactive_calls: list[tuple] = []

    class _FakeApp:
        def __init__(self, *args, **kwargs) -> None:
            self.token_cache = kwargs["token_cache"]

        def get_accounts(self):
            return []

        def acquire_token_silent(self, *args, **kwargs):
            return None

        def acquire_token_interactive(self, *args, **kwargs):
            interactive_calls.append((args, kwargs))
            return {"access_token": _token("interactive-token")}

        def initiate_device_flow(self, *args, **kwargs):
            raise AssertionError("device flow must not be used by an MCP server")

    class _FakeCache:
        has_state_changed = False

        def search(self, credential_type):
            return iter([])

        def deserialize(self, data: str) -> None:
            pass

        def serialize(self) -> str:
            return ""

    import msal

    monkeypatch.setattr(msal, "PublicClientApplication", _FakeApp)
    monkeypatch.setattr(graph, "create_token_cache", lambda path: _FakeCache())
    monkeypatch.delenv("GRAPH_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(graph, "GRAPH_TOKEN_CACHE_PATH", str(tmp_path / "cache.bin"))

    captured_out, captured_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(
        captured_err
    ):
        token = graph.acquire_graph_token(TENANT_ID, OBJECT_ID)

    assert token == _token("interactive-token")
    assert captured_out.getvalue() == ""
    assert captured_err.getvalue() == ""
    assert len(interactive_calls) == 1


def test_a_silent_token_is_preferred_over_an_interactive_prompt(
    monkeypatch, tmp_path
) -> None:
    """A maker who already signed in for /setup is not prompted again."""

    class _FakeApp:
        def __init__(self, *args, **kwargs) -> None:
            self.token_cache = kwargs["token_cache"]

        def get_accounts(self):
            return [{"home_account_id": "maker-home"}]

        def acquire_token_silent(self, *args, **kwargs):
            return {"access_token": _token("silent-token")}

        def acquire_token_interactive(self, *args, **kwargs):
            raise AssertionError("interactive prompt on a warm cache")

    class _FakeCache:
        has_state_changed = False

        def search(self, credential_type):
            return iter([{
                "home_account_id": "maker-home",
                "local_account_id": OBJECT_ID,
                "realm": TENANT_ID,
            }])

        def deserialize(self, data: str) -> None:
            pass

        def serialize(self) -> str:
            return ""

    import msal

    monkeypatch.setattr(msal, "PublicClientApplication", _FakeApp)
    monkeypatch.setattr(graph, "create_token_cache", lambda path: _FakeCache())
    monkeypatch.delenv("GRAPH_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(graph, "GRAPH_TOKEN_CACHE_PATH", str(tmp_path / "cache.bin"))

    assert graph.acquire_graph_token(TENANT_ID, OBJECT_ID) == _token("silent-token")


@pytest.mark.parametrize(
    ("provider_error", "expected_code"),
    [
        ("access_denied", "access_denied"),
        ("interaction_required", "interaction_required"),
        ("consent_required", "consent_required"),
        ("private_account_identifier", "unknown_error"),
        ("access_denied\nprivate account details", "unknown_error"),
        (_token("private-token"), "unknown_error"),
        ("x" * 1024, "unknown_error"),
        (["access_denied"], "unknown_error"),
        ({"account": "private"}, "unknown_error"),
        (None, "unknown_error"),
    ],
)
def test_failed_sign_in_logs_only_allowlisted_msal_codes(
    monkeypatch, tmp_path, caplog, provider_error, expected_code
) -> None:
    """Provider diagnostics must not become a channel for private response data."""

    class _FakeApp:
        def __init__(self, *args, **kwargs) -> None:
            self.token_cache = kwargs["token_cache"]

        def get_accounts(self):
            return []

        def acquire_token_silent(self, *args, **kwargs):
            return None

        def acquire_token_interactive(self, *args, **kwargs):
            return {
                "error": provider_error,
                "error_description": "Tenant contoso-secret blocked this app.",
                "claims": "PRIVATE_CLAIMS",
                "id_token": "PRIVATE_ID_TOKEN",
                "account": {"username": "private@contoso.test"},
            }

    class _FakeCache:
        has_state_changed = False

        def search(self, credential_type):
            return iter([])

        def deserialize(self, data: str) -> None:
            pass

        def serialize(self) -> str:
            return ""

    import msal

    monkeypatch.setattr(msal, "PublicClientApplication", _FakeApp)
    monkeypatch.setattr(graph, "create_token_cache", lambda path: _FakeCache())
    monkeypatch.delenv("GRAPH_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(graph, "GRAPH_TOKEN_CACHE_PATH", str(tmp_path / "cache.bin"))
    caplog.set_level("WARNING", logger="ess-org-announcements.graph")

    with pytest.raises(graph.GraphAuthenticationError) as caught:
        graph.acquire_graph_token(TENANT_ID, OBJECT_ID)

    assert str(caught.value) == (
        "Microsoft Graph sign-in failed. Sign in with the authoring account."
    )
    assert caught.value.code == "AuthenticationRequired"
    assert caught.value.retryable is False
    diagnostics = [
        record.getMessage() for record in caplog.records
        if record.name == "ess-org-announcements.graph"
    ]
    assert diagnostics == [f"Microsoft Graph sign-in failed ({expected_code})."]
    for private in ("contoso-secret", "PRIVATE_CLAIMS", "PRIVATE_ID_TOKEN", "private@contoso.test"):
        assert private not in caplog.text
        assert private not in str(caught.value)


# --------------------------------------------------------------------------
# Bounded TTL group-metadata cache
# --------------------------------------------------------------------------

GROUP_A = "11111111-1111-1111-1111-111111111111"
GROUP_B = "22222222-2222-2222-2222-222222222222"


def _counting_client(counter: list[int], groups: list[dict], **kwargs):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        return httpx.Response(200, json={"value": groups})

    return graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(handler),
        access_token=_token(),
        **kwargs,
    )


def test_resolved_group_metadata_is_served_from_cache_on_repeat_lookups() -> None:
    """Every mutation refreshes the manager; re-querying each time is waste."""
    requests: list[int] = []
    client = _counting_client(requests, [_group(GROUP_A)])

    async def run() -> tuple[dict, dict]:
        first = await client.resolve_groups([GROUP_A])
        second = await client.resolve_groups([GROUP_A])
        await client.aclose()
        return first, second

    first, second = asyncio.run(run())

    assert len(requests) == 1, "the second lookup hit Graph again"
    assert first == second
    assert first[GROUP_A]["displayName"] == f"Group {GROUP_A}"


def test_only_uncached_ids_are_sent_to_graph() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"value": [_group(GROUP_A), _group(GROUP_B)]})

    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(handler),
        access_token=_token(),
    )

    async def run() -> None:
        await client.resolve_groups([GROUP_A, GROUP_B])
        await client.resolve_groups([GROUP_A, GROUP_B])
        await client.aclose()

    asyncio.run(run())

    assert len(requests) == 1


def test_cached_group_metadata_expires(monkeypatch) -> None:
    requests: list[int] = []
    cache = graph._GroupMetadataCache(ttl_seconds=60.0)
    client = _counting_client(requests, [_group(GROUP_A)], metadata_cache=cache)

    clock = [1000.0]
    monkeypatch.setattr(cache, "_now", lambda: clock[0])

    async def run() -> None:
        await client.resolve_groups([GROUP_A])
        clock[0] += 59.0
        await client.resolve_groups([GROUP_A])  # still fresh
        clock[0] += 2.0
        await client.resolve_groups([GROUP_A])  # expired
        await client.aclose()

    asyncio.run(run())

    assert len(requests) == 2


def test_a_graph_failure_does_not_poison_the_metadata_cache() -> None:
    """A transient outage must not make later lookups return stale nothing."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": {"code": "serviceUnavailable"}})
        return httpx.Response(200, json={"value": [_group(GROUP_A)]})

    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(handler),
        access_token=_token(),
    )

    async def run() -> dict:
        with pytest.raises(graph.GraphDirectoryError):
            await client.resolve_groups([GROUP_A])
        resolved = await client.resolve_groups([GROUP_A])
        await client.aclose()
        return resolved

    resolved = asyncio.run(run())

    assert len(attempts) == 2
    assert resolved[GROUP_A]["id"] == GROUP_A


def test_an_unresolved_id_is_not_negatively_cached() -> None:
    """A newly created or newly eligible group must not stay invalid."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(200, json={"value": []})
        return httpx.Response(200, json={"value": [_group(GROUP_A)]})

    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(handler),
        access_token=_token(),
    )

    async def run() -> tuple[dict, dict]:
        first = await client.resolve_groups([GROUP_A])
        second = await client.resolve_groups([GROUP_A])
        await client.aclose()
        return first, second

    first, second = asyncio.run(run())

    assert first == {}
    assert second[GROUP_A]["id"] == GROUP_A
    assert len(attempts) == 2


def test_the_metadata_cache_is_bounded() -> None:
    cache = graph._GroupMetadataCache(ttl_seconds=600.0, max_entries=3)
    for index in range(5):
        cache.put(f"g{index}", {"id": f"g{index}", "displayName": f"G{index}"})

    # Oldest entries were evicted; the newest survive.
    assert cache.get("g0") is None
    assert cache.get("g1") is None
    assert cache.get("g4")["id"] == "g4"


def test_cached_metadata_preserves_order_and_multiplicity() -> None:
    """Caching must not reshape an individual audience list."""
    requests: list[int] = []
    client = _counting_client(requests, [_group(GROUP_A), _group(GROUP_B)])

    async def run() -> list[dict]:
        await client.resolve_groups([GROUP_A, GROUP_B])
        resolved = await client.resolve_groups([GROUP_B, GROUP_A, GROUP_B])
        await client.aclose()
        return graph.build_audience_metadata([GROUP_B, GROUP_A, GROUP_B], resolved)

    metadata = asyncio.run(run())

    assert [group["id"] for group in metadata] == [GROUP_B, GROUP_A, GROUP_B]
    assert len(requests) == 1


# --------------------------------------------------------------------------
# 401 recovery: expired token must not poison the process-global client
# --------------------------------------------------------------------------


def _client_with_responses(responses, monkeypatch, tokens=None):
    """Build a client whose Graph calls return ``responses`` in order.

    ``tokens`` is the sequence ``acquire_graph_token`` hands out, so a test can
    tell a reacquired token from the original one.
    """
    issued = list(tokens or ["token-2", "token-3", "token-4"])
    acquisitions: list[str] = []

    def _acquire(tenant_id, object_id) -> str:
        assert tenant_id == TENANT_ID
        token = issued.pop(0)
        acquisitions.append(token)
        return _token(token)

    monkeypatch.setattr(graph, "acquire_graph_token", _acquire)

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = responses[min(len(seen) - 1, len(responses) - 1)]
        return httpx.Response(status, json=body)

    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(handler),
        access_token=_token("token-1"),
    )
    return client, seen, acquisitions


def test_a_graph_401_invalidates_the_cached_token_and_client(monkeypatch) -> None:
    """An expired token must not survive to poison every later lookup.

    The MCP server holds ONE process-global Graph client, so without
    invalidation a single 401 would fail every audience lookup until the maker
    restarted the whole MCP host.
    """
    client, _, _ = _client_with_responses(
        [(401, {"error": {"code": "InvalidAuthenticationToken"}})], monkeypatch
    )

    async def run() -> None:
        await client._ensure_client()
        assert client._token == _token("token-1")
        assert client._client is not None

        with pytest.raises(graph.GraphDirectoryError) as caught:
            await client.search_groups("finance")

        assert caught.value.code == "AuthenticationRequired"
        assert caught.value.http_status == 401
        # Both the credential and the client that baked it into its headers
        # are gone.
        assert client._token == ""
        assert client._client is None
        await client.aclose()

    asyncio.run(run())


def test_the_call_after_a_401_reacquires_and_succeeds(monkeypatch) -> None:
    """Recovery happens on the next call, with no MCP restart."""
    client, seen, acquisitions = _client_with_responses(
        [
            (401, {"error": {"code": "InvalidAuthenticationToken"}}),
            (200, {"value": [_group(GROUP_A)]}),
        ],
        monkeypatch,
    )

    async def run() -> dict:
        with pytest.raises(graph.GraphDirectoryError):
            await client.search_groups("finance")
        resolved = await client.resolve_groups([GROUP_A])
        await client.aclose()
        return resolved

    resolved = asyncio.run(run())

    assert resolved[GROUP_A]["id"] == GROUP_A
    # Exactly one reacquisition, and the retry carried the NEW credential.
    assert acquisitions == ["token-2"]
    assert seen[0].headers["Authorization"] == f"Bearer {_token('token-1')}"
    assert seen[1].headers["Authorization"] == f"Bearer {_token('token-2')}"


def test_a_401_does_not_replay_the_failed_request(monkeypatch) -> None:
    """No automatic replay: reacquisition can open a browser mid-call.

    These are idempotent GETs so a replay would be *safe*, but blocking an
    in-flight tool call on a surprise interactive sign-in is worse than
    returning an actionable AuthenticationRequired the maker can act on.
    """
    client, seen, acquisitions = _client_with_responses(
        [(401, {"error": {"code": "InvalidAuthenticationToken"}})], monkeypatch
    )

    async def run() -> None:
        with pytest.raises(graph.GraphDirectoryError):
            await client.search_groups("finance")
        await client.aclose()

    asyncio.run(run())

    assert len(seen) == 1, "the failed request was replayed"
    assert acquisitions == [], "a sign-in was triggered inside the failing call"


def test_a_403_does_not_invalidate_the_token(monkeypatch) -> None:
    """403 is a consent/Conditional Access problem, not an expired token.

    Clearing the credential would force a pointless re-sign-in that cannot fix
    the underlying authorization gap.
    """
    client, _, acquisitions = _client_with_responses(
        [(403, {"error": {"code": "Authorization_RequestDenied"}})], monkeypatch
    )

    async def run() -> None:
        with pytest.raises(graph.GraphDirectoryError) as caught:
            await client.search_groups("finance")
        assert caught.value.code == "AuthorizationDenied"
        assert client._token == _token("token-1")
        assert client._client is not None
        await client.aclose()

    asyncio.run(run())

    assert acquisitions == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_failures_do_not_invalidate_the_token(monkeypatch, status) -> None:
    client, _, acquisitions = _client_with_responses(
        [(status, {"error": {"code": "transient"}})], monkeypatch
    )

    async def run() -> None:
        with pytest.raises(graph.GraphDirectoryError):
            await client.search_groups("finance")
        assert client._token == _token("token-1")
        await client.aclose()

    asyncio.run(run())

    assert acquisitions == []


def test_a_late_401_does_not_wipe_a_concurrently_refreshed_token(
    monkeypatch,
) -> None:
    """Invalidation is a compare-and-swap, not a blind clear.

    A 401 for an old credential can land after another caller has already
    completed a fresh acquisition. Wiping that fresh token would discard a good
    credential and force an unnecessary second sign-in.
    """
    monkeypatch.setattr(
        graph,
        "acquire_graph_token",
        lambda tenant_id, object_id: (_ for _ in ()).throw(AssertionError("must not reacquire")),
    )
    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"value": []})
        ),
        access_token=_token("fresh-token"),
    )

    async def run() -> None:
        # A 401 arrives for a credential that is no longer current.
        await client._invalidate_credentials(_token("stale-token"))
        assert client._token == _token("fresh-token")
        await client.aclose()

    asyncio.run(run())


def test_concurrent_callers_share_one_reacquisition_after_a_401(
    monkeypatch,
) -> None:
    """Two tool calls recovering at once must not open two browser prompts."""
    acquisitions: list[int] = []

    def _acquire(tenant_id, object_id) -> str:
        assert tenant_id == TENANT_ID
        acquisitions.append(1)
        return _token("token-2")

    monkeypatch.setattr(graph, "acquire_graph_token", _acquire)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": []})

    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(handler),
        access_token=_token("token-1"),
    )

    async def run() -> None:
        await client._invalidate_credentials(_token("token-1"))
        assert client._token == ""
        await asyncio.gather(
            client.search_groups("a"),
            client.search_groups("b"),
            client.resolve_groups([GROUP_A]),
        )
        await client.aclose()

    asyncio.run(run())

    assert acquisitions == [1], "concurrent recovery raced more than one sign-in"


def test_invalidation_closes_the_client_it_drops(monkeypatch) -> None:
    """A live client keeps sending the dead bearer from its default headers."""
    monkeypatch.setattr(
        graph, "acquire_graph_token", lambda tenant_id, object_id: _token("token-2")
    )
    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"value": []})
        ),
        access_token=_token("token-1"),
    )

    async def run() -> None:
        await client._ensure_client()
        dropped = client._client
        await client._invalidate_credentials(_token("token-1"))
        assert dropped.is_closed
        assert client._client is None
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("source", ["environment", "silent", "interactive"])
@pytest.mark.parametrize("token_tenant", [TENANT_ID, OTHER_TENANT_ID])
@pytest.mark.parametrize("token_object", [OBJECT_ID, OTHER_OBJECT_ID, None])
def test_graph_acquisition_is_bound_to_authoring_tenant_and_account(
    monkeypatch, source, token_tenant, token_object
) -> None:
    import msal

    token = _token(source, token_tenant, token_object)
    calls = {}
    class Cache:
        def search(self, credential_type):
            return iter([{
                "home_account_id": "cached-account",
                "local_account_id": OBJECT_ID,
                "realm": TENANT_ID,
            }])

    cache = Cache()

    def cache_factory(path):
        calls["cache_path"] = path
        return cache

    class FakeApp:
        def __init__(self, client_id, *, authority, token_cache):
            calls["app"] = (client_id, authority, token_cache)
            self.token_cache = token_cache

        def get_accounts(self):
            return [{"home_account_id": "cached-account"}]

        def acquire_token_silent(self, scopes, account):
            calls["scopes"] = scopes
            return {"access_token": token} if source == "silent" else None

        def acquire_token_interactive(self, scopes, **kwargs):
            calls["interactive"] = (scopes, kwargs)
            return {"access_token": token}

    monkeypatch.setattr(graph, "create_token_cache", cache_factory)
    monkeypatch.setattr(msal, "PublicClientApplication", FakeApp)
    if source == "environment":
        monkeypatch.setenv("GRAPH_ACCESS_TOKEN", token)

    if token_tenant == TENANT_ID and token_object == OBJECT_ID:
        assert graph.acquire_graph_token(TENANT_ID, OBJECT_ID) == token
    else:
        with pytest.raises(graph.GraphAuthenticationError, match="current authoring tenant"):
            graph.acquire_graph_token(TENANT_ID, OBJECT_ID)
    if source == "environment":
        assert calls == {}
    else:
        assert calls["cache_path"] == graph.GRAPH_TOKEN_CACHE_PATH
        assert calls["app"] == (
            "14d82eec-204b-4c2f-b7e8-296a70dab67e",
            f"https://login.microsoftonline.com/{TENANT_ID}",
            cache,
        )
        assert calls["scopes"] == ["https://graph.microsoft.com/Directory.Read.All"]
        if source == "interactive":
            assert calls["interactive"] == (
                ["https://graph.microsoft.com/Directory.Read.All"],
                {"prompt": "select_account"},
            )
        else:
            assert "interactive" not in calls


def test_a_wrong_tenant_token_cannot_construct_a_directory_client() -> None:
    with pytest.raises(graph.GraphAuthenticationError):
        graph.GraphDirectoryClient(
            tenant_id=TENANT_ID,
            object_id=OBJECT_ID,
            access_token=_token("wrong", OTHER_TENANT_ID),
        )


def test_wrong_lazy_token_is_rejected_before_directory_io_or_cache_hit(monkeypatch) -> None:
    cache = graph._GroupMetadataCache()
    cache.put(GROUP_A, graph.to_audience_group(_group(GROUP_A)))
    requests = []
    monkeypatch.setattr(
        graph, "acquire_graph_token", lambda tenant_id, object_id: _token("wrong", OTHER_TENANT_ID)
    )
    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        metadata_cache=cache,
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json={"value": []})
        ),
    )

    async def run():
        with pytest.raises(graph.GraphAuthenticationError):
            await client.resolve_groups([GROUP_A])
        assert client._client is None
        await client.aclose()

    asyncio.run(run())
    assert requests == []


def test_tenant_is_not_mutable_on_an_existing_client() -> None:
    client = _make_client(lambda request: httpx.Response(200, json={"value": []}))
    assert client.tenant_id == TENANT_ID
    with pytest.raises(AttributeError):
        client.tenant_id = OTHER_TENANT_ID


def test_credential_reset_replaces_metadata_and_forces_fresh_resolution(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(graph, "acquire_graph_token", lambda tenant_id, object_id: _token("new"))

    def handler(request):
        seen.append(request)
        label = "old" if len(seen) == 1 else "new"
        return httpx.Response(200, json={"value": [_group(GROUP_A, display_name=label)]})

    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        access_token=_token("old"),
        transport=httpx.MockTransport(handler),
    )

    async def run():
        assert (await client.resolve_groups([GROUP_A]))[GROUP_A]["displayName"] == "old"
        previous_cache = client._metadata_cache
        await client._invalidate_credentials(_token("old"))
        assert client._metadata_cache is not previous_cache
        assert previous_cache.get(GROUP_A) is None
        assert (await client.resolve_groups([GROUP_A]))[GROUP_A]["displayName"] == "new"
        assert len(seen) == 2
        await client.aclose()

    asyncio.run(run())


def test_late_resolution_cannot_populate_the_replacement_cache(monkeypatch) -> None:
    monkeypatch.setattr(graph, "acquire_graph_token", lambda tenant_id, object_id: _token("new"))

    async def run():
        started = asyncio.Event()
        release = asyncio.Event()
        seen = []

        async def handler(request):
            seen.append(request)
            if request.headers["Authorization"] == f"Bearer {_token('old')}":
                started.set()
                await release.wait()
                label = "old"
            else:
                label = "new"
            return httpx.Response(200, json={"value": [_group(GROUP_A, display_name=label)]})

        client = graph.GraphDirectoryClient(
            tenant_id=TENANT_ID,
            object_id=OBJECT_ID,
            access_token=_token("old"),
            transport=httpx.MockTransport(handler),
        )
        old_request = asyncio.create_task(client.resolve_groups([GROUP_A]))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            await client._invalidate_credentials(_token("old"))
            fresh = await client.resolve_groups([GROUP_A])
            release.set()
            old = await asyncio.wait_for(old_request, timeout=5)
            assert old[GROUP_A]["displayName"] == "old"
            assert fresh[GROUP_A]["displayName"] == "new"
            assert (await client.resolve_groups([GROUP_A]))[GROUP_A]["displayName"] == "new"
            assert len(seen) == 2
        finally:
            release.set()
            await asyncio.gather(old_request, return_exceptions=True)
            await client.aclose()

    asyncio.run(run())


def test_paging_does_not_adopt_replacement_credentials_mid_request(monkeypatch) -> None:
    acquisitions = []
    seen = []

    def acquire(tenant_id, object_id):
        acquisitions.append(tenant_id)
        return _token("new")

    monkeypatch.setattr(graph, "acquire_graph_token", acquire)

    async def run():
        async def handler(request):
            seen.append(request)
            await client._invalidate_credentials(_token("old"))
            return httpx.Response(200, json={
                "value": [],
                "@odata.nextLink": f"{graph.GRAPH_BASE_URL}/groups?$skiptoken=next",
            })

        client = graph.GraphDirectoryClient(
            tenant_id=TENANT_ID,
            object_id=OBJECT_ID,
            access_token=_token("old"),
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(graph.GraphAuthenticationError, match="reset"):
            await client.search_groups("finance")
        await client.aclose()

    asyncio.run(run())
    assert len(seen) == 1
    assert acquisitions == []


@pytest.mark.parametrize("error_type", [LockException, PermissionError])
def test_cache_acquisition_errors_are_safe_domain_errors_with_private_causes(
    monkeypatch, error_type, caplog
) -> None:
    detail = "/private/graph-cache PRIVATE_CREDENTIAL_DETAIL"
    original = error_type(detail)

    def acquire(tenant_id, object_id):
        assert tenant_id == TENANT_ID
        raise original

    monkeypatch.setattr(graph, "acquire_graph_token", acquire)
    client = graph.GraphDirectoryClient(tenant_id=TENANT_ID, object_id=OBJECT_ID)

    async def run():
        with pytest.raises(graph.GraphAuthenticationError) as caught:
            await client._access_token()
        assert caught.value.__cause__ is original
        assert caught.value.code == "AuthenticationRequired"
        assert caught.value.retryable is False
        for fragment in detail.split():
            assert fragment not in str(caught.value)
        assert client._token == ""
        assert client._client is None
        assert not client._token_lock.locked()
        await client.aclose()

    asyncio.run(run())
    for fragment in detail.split():
        assert fragment not in caplog.text


def test_unrelated_graph_acquisition_errors_are_not_blanket_caught(monkeypatch) -> None:
    original = RuntimeError("unexpected implementation failure")

    def acquire(tenant_id, object_id):
        raise original

    monkeypatch.setattr(graph, "acquire_graph_token", acquire)
    client = graph.GraphDirectoryClient(tenant_id=TENANT_ID, object_id=OBJECT_ID)

    async def run():
        with pytest.raises(RuntimeError) as caught:
            await client._access_token()
        assert caught.value is original
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("query", "escaped"),
    [
        ("finance@contoso.com", "finance@contoso.com"),
        ('Finance "West"', 'Finance \\"West\\"'),
        ('Back\\slash " OR "displayName:all', 'Back\\\\slash \\" OR \\"displayName:all'),
    ],
)
def test_one_combined_query_keeps_email_matches_and_filters_ineligible_groups(query, escaped):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"value": [
            _group("email-match", display_name="Budget", mail="finance@contoso.com"),
            _group("unified", group_types=["Unified"], mail_enabled=True),
            _group("name-match", display_name="Finance"),
            _group("dynamic", group_types=["DynamicMembership"]),
            _group("email-match", display_name="duplicate"),
        ]})

    client = _make_client(handler)

    async def run():
        try:
            return await client.search_groups(query)
        finally:
            await client.aclose()

    result = asyncio.run(run())
    assert [group["id"] for group in result["groups"]] == ["email-match", "name-match"]
    assert result["exhausted"] is True
    assert result["pagesExamined"] == 1
    assert len(requests) == 1
    params = requests[0].url.params
    assert params["$search"] == f'"displayName:{escaped}" OR "mail:{escaped}"'
    assert params["$select"] == "id,displayName,mail,mailEnabled,securityEnabled,groupTypes"
    assert params["$top"] == "50"
    assert requests[0].headers["ConsistencyLevel"] == "eventual"


def test_graph_silent_acquisition_uses_matching_account_not_first_account(monkeypatch):
    from types import SimpleNamespace
    import msal

    wrong = {"home_account_id": "wrong", "realm": TENANT_ID, "local_account_id": OTHER_OBJECT_ID}
    right = {"home_account_id": "right", "realm": TENANT_ID, "local_account_id": OBJECT_ID}
    cache = SimpleNamespace(search=lambda credential_type: iter([wrong, right]))
    calls = []

    class App:
        token_cache = cache

        def get_accounts(self):
            return [wrong, right]

        def acquire_token_silent(self, scopes, account):
            calls.append((scopes, account))
            return {"access_token": _token()}

        def acquire_token_interactive(self, *args, **kwargs):
            pytest.fail("matching cached account must not prompt")

    monkeypatch.setattr(graph, "create_token_cache", lambda path: cache)
    monkeypatch.setattr(msal, "PublicClientApplication", lambda *args, **kwargs: App())
    assert graph.acquire_graph_token(TENANT_ID, OBJECT_ID) == _token()
    assert calls == [(graph.GRAPH_SCOPES, right)]


@pytest.mark.parametrize("token", ["opaque-graph-token", _token(object_id=None)])
def test_graph_credentials_without_account_context_are_rejected(monkeypatch, token):
    monkeypatch.setenv("GRAPH_ACCESS_TOKEN", token)
    with pytest.raises(graph.GraphAuthenticationError, match="tid and oid"):
        graph.acquire_graph_token(TENANT_ID, OBJECT_ID)


def test_missing_authoring_account_never_attempts_independent_graph_sign_in():
    # The autouse fixture rejects any unmocked MSAL/network call.
    with pytest.raises(graph.GraphAuthenticationError, match="authoring account cannot be identified"):
        graph.acquire_graph_token(TENANT_ID, None)


def test_same_tenant_wrong_account_cannot_use_cached_metadata(monkeypatch):
    cache = graph._GroupMetadataCache()
    cache.put(GROUP_A, graph.to_audience_group(_group(GROUP_A)))
    monkeypatch.setattr(
        graph, "acquire_graph_token",
        lambda tenant_id, object_id: _token(object_id=OTHER_OBJECT_ID),
    )
    client = graph.GraphDirectoryClient(
        tenant_id=TENANT_ID, object_id=OBJECT_ID, metadata_cache=cache,
    )
    with pytest.raises(graph.GraphAuthenticationError):
        asyncio.run(client.resolve_groups([GROUP_A]))
    assert client._client is None
