# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the ADK Copilot Studio analytics pointer (ADO PR 5465946).

These tests cover the pure-logic module only. They do not exercise the
Copilot Studio partner API — the whole point of the feature flag
this module ships behind is that no real API call is attempted until
the deep-link contract is confirmed.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path


# --- resolve_pointer_url -------------------------------------------------


def test_resolve_pointer_url_returns_stub_when_flag_off(monkeypatch):
    """With the feature flag OFF (the default) the resolver MUST NOT build a
    URL, even when both ids are present. This is the safety property that
    keeps the placeholder URL from ever leaking to real makers before the
    Copilot Studio partner contract is locked."""
    import analytics_pointer

    monkeypatch.delenv("ADK_ANALYTICS_POINTER", raising=False)

    url, reason = analytics_pointer.resolve_pointer_url(
        env_id="env-guid", agent_id="bot-guid",
    )

    assert url == ""
    assert reason == analytics_pointer.REASON_FLAG_OFF


def test_resolve_pointer_url_returns_full_url_when_flag_on(monkeypatch):
    """Flag on + both ids present → resolver returns a URL containing both
    ids. We assert on presence, not exact shape, so a future partner-
    contract change to the path can update the module constant without
    invalidating this test."""
    import analytics_pointer

    monkeypatch.setenv("ADK_ANALYTICS_POINTER", "on")

    url, reason = analytics_pointer.resolve_pointer_url(
        env_id="env-guid-42", agent_id="bot-guid-99",
    )

    assert reason == ""
    assert url.startswith("https://copilotstudio.microsoft.com/")
    assert "env-guid-42" in url
    assert "bot-guid-99" in url


def test_resolve_pointer_url_missing_env_id(monkeypatch):
    import analytics_pointer

    monkeypatch.setenv("ADK_ANALYTICS_POINTER", "on")

    url, reason = analytics_pointer.resolve_pointer_url(
        env_id="", agent_id="bot-guid",
    )

    assert url == ""
    assert reason == analytics_pointer.REASON_MISSING_ASSOCIATION


def test_resolve_pointer_url_missing_agent_id(monkeypatch):
    import analytics_pointer

    monkeypatch.setenv("ADK_ANALYTICS_POINTER", "on")

    url, reason = analytics_pointer.resolve_pointer_url(
        env_id="env-guid", agent_id="",
    )

    assert url == ""
    assert reason == analytics_pointer.REASON_MISSING_ASSOCIATION


def test_resolve_pointer_url_flag_off_beats_missing_ids(monkeypatch):
    """When the flag is off, the resolver should short-circuit to
    ``feature_flag_off`` BEFORE checking ids. This ordering matters for
    telemetry: even a well-linked workspace must not emit
    ``missing_association`` when the real reason we're not showing a URL
    is that the feature is off."""
    import analytics_pointer

    monkeypatch.delenv("ADK_ANALYTICS_POINTER", raising=False)

    url, reason = analytics_pointer.resolve_pointer_url(env_id="", agent_id="")

    assert url == ""
    assert reason == analytics_pointer.REASON_FLAG_OFF


# --- read_association ----------------------------------------------------


def _write_config(path: Path, cfg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg), encoding="utf-8")


def test_read_association_returns_none_when_file_missing(tmp_path: Path):
    import analytics_pointer

    result = analytics_pointer.read_association(path=tmp_path / "does-not-exist.json")
    assert result is None


def test_read_association_returns_none_when_agent_missing(tmp_path: Path):
    """Half-set-up workspace (env known, no agent linked) → None. That maps
    to the FR7 repair path."""
    import analytics_pointer

    cfg_path = tmp_path / ".local" / "config.json"
    _write_config(cfg_path, {
        "environmentId": "env-guid",
        "makerAad": "maker-oid",
        "agent": {},
    })

    assert analytics_pointer.read_association(path=cfg_path) is None


def test_read_association_returns_triplet_when_present(tmp_path: Path):
    import analytics_pointer

    cfg_path = tmp_path / ".local" / "config.json"
    _write_config(cfg_path, {
        "environmentId": "env-guid",
        "makerAad": "maker-oid",
        "agent": {"botId": "bot-guid"},
    })

    result = analytics_pointer.read_association(path=cfg_path)
    assert result == ("maker-oid", "env-guid", "bot-guid")


def test_read_association_accepts_env_id_on_agent(tmp_path: Path):
    """Some setups nest ``environmentId`` under ``agent``. That should also
    resolve — mirrors drive_topic.py's fallback."""
    import analytics_pointer

    cfg_path = tmp_path / ".local" / "config.json"
    _write_config(cfg_path, {
        "makerAad": "maker-oid",
        "agent": {"botId": "bot-guid", "environmentId": "env-nested"},
    })

    result = analytics_pointer.read_association(path=cfg_path)
    assert result == ("maker-oid", "env-nested", "bot-guid")


# --- render_pointer_line -------------------------------------------------


def test_render_pointer_line_url_plain():
    import analytics_pointer

    line = analytics_pointer.render_pointer_line(
        "https://example.com/analytics", "", reminder_framing=False,
    )
    assert "https://example.com/analytics" in line
    # Plain framing is the /analytics slash-command wording — must NOT sound
    # like a reminder ("run /analytics anytime").
    assert "anytime" not in line.lower()


def test_render_pointer_line_url_reminder_framing():
    import analytics_pointer

    line = analytics_pointer.render_pointer_line(
        "https://example.com/analytics", "", reminder_framing=True,
    )
    assert "https://example.com/analytics" in line
    # Reminder framing is the post-install footer wording — should mention
    # the slash command so the maker knows how to jump back.
    assert "/analytics" in line


def test_render_pointer_line_flag_off_mentions_flag():
    import analytics_pointer

    line = analytics_pointer.render_pointer_line(
        "", analytics_pointer.REASON_FLAG_OFF, reminder_framing=False,
    )
    assert "not yet enabled" in line.lower() or "feature flag" in line.lower()


def test_render_pointer_line_missing_association_points_at_setup():
    import analytics_pointer

    line = analytics_pointer.render_pointer_line(
        "", analytics_pointer.REASON_MISSING_ASSOCIATION, reminder_framing=False,
    )
    assert "/setup" in line


def test_render_pointer_line_reminder_vs_plain_differ():
    """The framing switch is the whole point of the ``reminder_framing`` flag
    — assert the two branches actually produce different copy for the same
    input state."""
    import analytics_pointer

    plain = analytics_pointer.render_pointer_line(
        "", analytics_pointer.REASON_MISSING_ASSOCIATION, reminder_framing=False,
    )
    reminder = analytics_pointer.render_pointer_line(
        "", analytics_pointer.REASON_MISSING_ASSOCIATION, reminder_framing=True,
    )
    assert plain != reminder


# --- LocalFileReminderStore ---------------------------------------------


def test_local_file_reminder_store_roundtrip(tmp_path: Path):
    import analytics_pointer

    store = analytics_pointer.LocalFileReminderStore(
        path=tmp_path / "reminder.json",
    )

    # Empty store: nothing is completed.
    assert store.is_completed("m", "e", "a") is False

    # Marking completes exactly the (m, e, a) triplet and no other.
    store.mark_completed("m", "e", "a", "post_deploy_install")

    assert store.is_completed("m", "e", "a") is True
    assert store.is_completed("m", "e", "different-agent") is False
    assert store.is_completed("other-maker", "e", "a") is False


def test_local_file_reminder_store_persists_across_instances(tmp_path: Path):
    """The store's file is the source of truth — a fresh instance pointing at
    the same path must see previously marked triplets. This is what makes
    the post-install reminder actually one-time."""
    import analytics_pointer

    p = tmp_path / "reminder.json"
    analytics_pointer.LocalFileReminderStore(path=p).mark_completed(
        "m", "e", "a", "post_deploy_install",
    )

    fresh = analytics_pointer.LocalFileReminderStore(path=p)
    assert fresh.is_completed("m", "e", "a") is True


def test_local_file_reminder_store_ignores_empty_ids(tmp_path: Path):
    """Marking with empty ids is a defensive no-op — otherwise the store
    would grow a garbage entry keyed by ``"||"`` for every unresolved
    installer run."""
    import analytics_pointer

    store = analytics_pointer.LocalFileReminderStore(
        path=tmp_path / "reminder.json",
    )
    store.mark_completed("", "", "", "post_deploy_install")

    assert store.is_completed("", "", "") is False
    # And the file either wasn't created or is an empty dict.
    if (tmp_path / "reminder.json").exists():
        data = json.loads((tmp_path / "reminder.json").read_text(encoding="utf-8"))
        assert not data.get("completed")


# --- get_reminder_store --------------------------------------------------


def test_get_reminder_store_defaults_to_local(monkeypatch):
    import analytics_pointer

    monkeypatch.delenv("ADK_ANALYTICS_STORE", raising=False)
    store = analytics_pointer.get_reminder_store()
    assert isinstance(store, analytics_pointer.LocalFileReminderStore)


def test_get_reminder_store_unknown_value_falls_back_to_local(monkeypatch):
    """A typo in ADK_ANALYTICS_STORE must NOT crash a skill — fall back to
    local silently."""
    import analytics_pointer

    monkeypatch.setenv("ADK_ANALYTICS_STORE", "not-a-real-backend")
    store = analytics_pointer.get_reminder_store()
    assert isinstance(store, analytics_pointer.LocalFileReminderStore)


def test_get_reminder_store_dataverse_still_returns_local_today(monkeypatch):
    """``dataverse`` is the reserved future value. Until the ESS Dataverse
    solution ships the ``adk_makerreminder`` table this falls back to the
    local store rather than erroring — same fail-open reasoning as the
    unknown-value case."""
    import analytics_pointer

    monkeypatch.setenv("ADK_ANALYTICS_STORE", "dataverse")
    store = analytics_pointer.get_reminder_store()
    assert isinstance(store, analytics_pointer.LocalFileReminderStore)


# --- CLI -----------------------------------------------------------------


def test_cli_status_when_flag_off_and_no_config(monkeypatch, tmp_path: Path):
    """--status must return JSON even when nothing is set up. This is what
    the /analytics prompt branches on."""
    import analytics_pointer

    monkeypatch.delenv("ADK_ANALYTICS_POINTER", raising=False)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = analytics_pointer.main(
            ["--config", str(tmp_path / "missing.json"), "--status"],
        )
    assert rc == 0

    payload = json.loads(buf.getvalue())
    assert payload["flag"] == "off"
    assert payload["association"] is None
    assert payload["reason"] == analytics_pointer.REASON_MISSING_ASSOCIATION


def test_cli_show_prints_url_when_resolved(monkeypatch, tmp_path: Path):
    import analytics_pointer

    monkeypatch.setenv("ADK_ANALYTICS_POINTER", "on")
    cfg_path = tmp_path / ".local" / "config.json"
    _write_config(cfg_path, {
        "environmentId": "env-guid-cli",
        "makerAad": "maker-cli",
        "agent": {"botId": "bot-guid-cli"},
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = analytics_pointer.main(["--config", str(cfg_path), "--show"])
    assert rc == 0

    out = buf.getvalue()
    assert "env-guid-cli" in out
    assert "bot-guid-cli" in out
