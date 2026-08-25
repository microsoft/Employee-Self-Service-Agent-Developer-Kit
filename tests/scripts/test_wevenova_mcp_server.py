# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Token-source resolution for the WeveNova MCP server.

The server has three ways to obtain a bearer token and the order matters: a developer
on an unpaired TDS machine must be able to supply a token minted elsewhere without the
server silently falling through to a PowerShell mint that cannot succeed. These pin
that precedence, and the header-paste tolerance that makes the token file usable in
practice (the value is normally copied straight out of an Authorization header).

No network, no PowerShell, no token: the mint path is only reached in the one case that
asserts it is *not* reached.
"""

from __future__ import annotations

import os
import sys
import warnings

import pytest

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
_SERVER_DIR = os.path.join(
    _REPO_ROOT, "solutions", "ess-maker-skills", "src", "mcp", "wevenova"
)
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

pytest.importorskip("mcp.server.fastmcp", reason="mcp<2 not installed")

# Constructing FastMCP emits a pydantic-settings warning about an unresolved forward
# reference in the SDK's own Settings model. The kit's pytest config promotes warnings
# to errors, which would fail collection over a third-party issue we do not control and
# which does not affect the running server. Suppressed only around this import.
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import server as wevenova_server  # noqa: E402

_TokenProvider = wevenova_server._TokenProvider


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    """Never inherit the developer's real token or point at their real token file."""
    monkeypatch.delenv("WEVENOVA_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WEVENOVA_VERIFY_TLS", raising=False)
    monkeypatch.delenv("WEVENOVA_BASE_URL", raising=False)
    monkeypatch.setenv("WEVENOVA_TOKEN_FILE", str(tmp_path / "absent.token"))


class TestTlsVerificationFollowsTheTarget:
    """Verify everywhere except this machine.

    The dev tunnel serves a self-signed certificate that httpx rejects, so requiring a
    flag for the one host where interception is impossible only trains people to pass
    ``--insecure`` everywhere. Loopback traffic never leaves the box; any other host is
    still fully checked.
    """

    def test_the_dev_tunnel_is_not_verified(self, monkeypatch):
        monkeypatch.setenv("WEVENOVA_BASE_URL", "https://localhost:444/weveb2")
        assert wevenova_server._verify_tls() is False

    def test_the_built_in_default_is_the_dev_tunnel(self):
        assert wevenova_server._verify_tls() is False

    @pytest.mark.parametrize("host", ["127.0.0.1:444", "[::1]:444"])
    def test_other_loopback_spellings_are_not_verified(self, monkeypatch, host):
        monkeypatch.setenv("WEVENOVA_BASE_URL", f"https://{host}/weveb2")
        assert wevenova_server._verify_tls() is False

    def test_a_real_host_is_verified(self, monkeypatch):
        monkeypatch.setenv(
            "WEVENOVA_BASE_URL", "https://substrate.office.com/weveb2"
        )
        assert wevenova_server._verify_tls() is True

    def test_a_lookalike_host_is_verified(self, monkeypatch):
        """'localhost.evil.test' is not loopback -- substring matching would be a hole."""
        monkeypatch.setenv("WEVENOVA_BASE_URL", "https://localhost.evil.test/weveb2")
        assert wevenova_server._verify_tls() is True

    @pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE"])
    def test_an_explicit_true_overrides_the_loopback_rule(self, monkeypatch, value):
        monkeypatch.setenv("WEVENOVA_BASE_URL", "https://localhost:444/weveb2")
        monkeypatch.setenv("WEVENOVA_VERIFY_TLS", value)
        assert wevenova_server._verify_tls() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "FALSE"])
    def test_an_explicit_false_overrides_a_real_host(self, monkeypatch, value):
        """--insecure-skip-tls-verify has to still work off-box."""
        monkeypatch.setenv("WEVENOVA_BASE_URL", "https://substrate.office.com/weveb2")
        monkeypatch.setenv("WEVENOVA_VERIFY_TLS", value)
        assert wevenova_server._verify_tls() is False


class TestTokenSourcePrecedence:
    def test_env_var_wins(self, monkeypatch, tmp_path):
        token_file = tmp_path / "t.token"
        token_file.write_text("from-file", encoding="utf-8")
        monkeypatch.setenv("WEVENOVA_TOKEN_FILE", str(token_file))
        monkeypatch.setenv("WEVENOVA_ACCESS_TOKEN", "from-env")
        assert _TokenProvider._mint() == "from-env"

    def test_token_file_is_used_before_shelling_out(self, monkeypatch, tmp_path):
        token_file = tmp_path / "t.token"
        token_file.write_text("from-file", encoding="utf-8")
        monkeypatch.setenv("WEVENOVA_TOKEN_FILE", str(token_file))

        def _explode(*_a, **_k):
            raise AssertionError("must not shell out when a token file exists")

        monkeypatch.setattr(wevenova_server.subprocess, "run", _explode)
        assert _TokenProvider._mint() == "from-file"

    def test_missing_token_file_falls_through_to_minting(self, monkeypatch):
        """An absent file must not be mistaken for an empty token."""
        monkeypatch.setattr(wevenova_server.os.path, "exists", lambda _p: False)
        with pytest.raises(wevenova_server.TokenMintError, match="not found"):
            _TokenProvider._mint()

    def test_default_token_file_lives_in_the_gitignored_local_dir(self):
        # Anywhere else and a real credential could be committed.
        assert wevenova_server.DEFAULT_TOKEN_FILE.replace("\\", "/").endswith(
            "solutions/ess-maker-skills/.local/.wevenova_token"
        )

    def test_accepts_the_dotless_filename(self, monkeypatch, tmp_path):
        """A dotfile is easy to miss in Explorer, so both spellings must resolve."""
        monkeypatch.delenv("WEVENOVA_TOKEN_FILE", raising=False)
        monkeypatch.setattr(wevenova_server, "_LOCAL_DIR", str(tmp_path))
        (tmp_path / "wevenova_token").write_text("dotless", encoding="utf-8")
        assert _TokenProvider._token_file() == str(tmp_path / "wevenova_token")
        assert _TokenProvider._mint() == "dotless"

    def test_prefers_the_dotfile_when_both_exist(self, monkeypatch, tmp_path):
        monkeypatch.delenv("WEVENOVA_TOKEN_FILE", raising=False)
        monkeypatch.setattr(wevenova_server, "_LOCAL_DIR", str(tmp_path))
        (tmp_path / ".wevenova_token").write_text("dotted", encoding="utf-8")
        (tmp_path / "wevenova_token").write_text("dotless", encoding="utf-8")
        assert _TokenProvider._mint() == "dotted"

    def test_explicit_override_beats_both_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wevenova_server, "_LOCAL_DIR", str(tmp_path))
        (tmp_path / "wevenova_token").write_text("default", encoding="utf-8")
        override = tmp_path / "elsewhere.token"
        override.write_text("override", encoding="utf-8")
        monkeypatch.setenv("WEVENOVA_TOKEN_FILE", str(override))
        assert _TokenProvider._mint() == "override"


class TestTokenFileParsing:
    def test_strips_a_pasted_bearer_prefix(self, tmp_path):
        path = tmp_path / "t.token"
        path.write_text("Bearer abc.def.ghi\n", encoding="utf-8")
        # Copied straight from an Authorization header; sending "Bearer Bearer x"
        # would fail as an opaque 401 with no hint at the real cause.
        assert _TokenProvider._read_token_file(str(path)) == "abc.def.ghi"

    def test_strips_surrounding_whitespace(self, tmp_path):
        path = tmp_path / "t.token"
        path.write_text("  abc.def.ghi  \n\n", encoding="utf-8")
        assert _TokenProvider._read_token_file(str(path)) == "abc.def.ghi"

    def test_tolerates_a_utf8_bom(self, tmp_path):
        path = tmp_path / "t.token"
        # Set-Content and Notepad both write a BOM by default on Windows.
        path.write_text("abc.def.ghi", encoding="utf-8-sig")
        assert _TokenProvider._read_token_file(str(path)) == "abc.def.ghi"

    def test_empty_file_is_not_a_token(self, tmp_path):
        path = tmp_path / "t.token"
        path.write_text("   \n", encoding="utf-8")
        assert _TokenProvider._read_token_file(str(path)) is None

    def test_absent_file_is_not_a_token(self, tmp_path):
        assert _TokenProvider._read_token_file(str(tmp_path / "nope")) is None


class TestServerInfoDoesNotLeak:
    def test_reports_the_file_as_the_source_without_the_token(
        self, monkeypatch, tmp_path
    ):
        path = tmp_path / "t.token"
        path.write_text("super-secret-token", encoding="utf-8")
        monkeypatch.setenv("WEVENOVA_TOKEN_FILE", str(path))

        info = wevenova_server.server_info()["data"]

        assert str(path) in info["tokenSource"]
        # The whole point of server_info is that it is safe to print and log.
        assert "super-secret-token" not in repr(info)

    def test_reports_the_env_var_as_the_source(self, monkeypatch):
        monkeypatch.setenv("WEVENOVA_ACCESS_TOKEN", "super-secret-token")
        info = wevenova_server.server_info()["data"]
        assert info["tokenSource"] == "WEVENOVA_ACCESS_TOKEN"
        assert "super-secret-token" not in repr(info)
