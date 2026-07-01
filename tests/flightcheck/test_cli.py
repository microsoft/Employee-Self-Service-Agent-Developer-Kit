# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for solutions/ess-maker-skills/scripts/flightcheck/cli.py helpers.

Currently covers ``open_report_in_browser``, the post-run hook that
launches the HTML report in the default browser. The helper is a small
pure-side-effect function (file existence check + ``webbrowser.open``);
tests stub out ``webbrowser.open`` so no browser tab opens during the run.

The motivation for testing this at all is that the first implementation
built the ``file://`` URI with f-string concatenation, which produced
malformed URIs on Windows for any path containing spaces (e.g.
``C:\\Users\\foo\\OneDrive - Microsoft Corporation\\...``). The helper
now goes through ``pathlib.Path.as_uri()`` to produce RFC 8089 compliant
URIs. These tests pin that behavior so it doesn't regress.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from flightcheck import cli


class TestOpenReportInBrowser:
    """Tests for cli.open_report_in_browser."""

    def test_returns_false_when_report_missing(self, tmp_path: Path) -> None:
        # FlightCheck can abort before save_results (e.g. fatal config
        # error). The helper must no-op cleanly in that case rather
        # than 404'ing a browser tab.
        with patch("flightcheck.cli.webbrowser.open") as mock_open:
            result = cli.open_report_in_browser(str(tmp_path))
        assert result is False
        mock_open.assert_not_called()

    def test_returns_true_when_webbrowser_open_succeeds(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "report.html").write_text("<html></html>")
        with patch(
            "flightcheck.cli.webbrowser.open", return_value=True
        ) as mock_open:
            result = cli.open_report_in_browser(str(tmp_path))
        assert result is True
        mock_open.assert_called_once()

    def test_returns_false_when_webbrowser_open_reports_failure(
        self, tmp_path: Path
    ) -> None:
        # ``webbrowser.open`` returns False when it could not locate a
        # browser (e.g. SSH session with no DISPLAY). The helper must
        # propagate that so callers can decide what to do — and it must
        # NOT raise, because FlightCheck's exit code reflects check
        # results, not browser-launch success.
        (tmp_path / "report.html").write_text("<html></html>")
        with patch("flightcheck.cli.webbrowser.open", return_value=False):
            result = cli.open_report_in_browser(str(tmp_path))
        assert result is False

    def test_passes_well_formed_file_uri(self, tmp_path: Path) -> None:
        # All file URIs must start with ``file:///`` (three slashes —
        # empty host segment) per RFC 8089. The pre-fix f-string
        # produced ``file://C:\path...`` on Windows; ``Path.as_uri()``
        # produces ``file:///C:/path/...``.
        (tmp_path / "report.html").write_text("<html></html>")
        with patch("flightcheck.cli.webbrowser.open") as mock_open:
            cli.open_report_in_browser(str(tmp_path))

        uri = mock_open.call_args[0][0]
        assert uri.startswith("file:///")
        assert uri.endswith("/report.html")
        assert "\\" not in uri  # forward slashes only

    def test_handles_paths_with_spaces(self, tmp_path: Path) -> None:
        # The original bug: ``f"file://{abs_path}"`` produces an
        # unescaped URI for paths with spaces (e.g. Windows OneDrive
        # paths). ``Path.as_uri()`` percent-encodes them as ``%20``.
        spaced = tmp_path / "my output dir"
        spaced.mkdir()
        (spaced / "report.html").write_text("<html></html>")

        with patch("flightcheck.cli.webbrowser.open") as mock_open:
            cli.open_report_in_browser(str(spaced))

        uri = mock_open.call_args[0][0]
        assert "%20" in uri
        assert " " not in uri  # raw space would be malformed

    def test_resolves_relative_output_dir(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # CLI's default ``--output`` is ``workspace/flightcheck`` (relative).
        # The helper must resolve it to an absolute path so the resulting
        # ``file:///`` URI points at the right place even after a later
        # ``os.chdir``.
        monkeypatch.chdir(tmp_path)
        rel_out = Path("workspace/flightcheck")
        rel_out.mkdir(parents=True)
        (rel_out / "report.html").write_text("<html></html>")

        with patch("flightcheck.cli.webbrowser.open") as mock_open:
            cli.open_report_in_browser(str(rel_out))

        uri = mock_open.call_args[0][0]
        # tmp_path is absolute; the resolved URI must contain it (modulo
        # platform-specific drive-letter encoding).
        assert "workspace/flightcheck/report.html" in uri


class _FakeRunner:
    def __init__(self, scope: str) -> None:
        self.scope = scope
        self.registered = []
        self.config = None
        self.env_url = None
        self.dv_token = None
        self.env_id = None
        self.graph = None
        self.pp_admin = None
        self.pva = None

    def register(self, category, fn):
        self.registered.append((category, fn))

    def run(self):
        return SimpleNamespace(
            failed=0,
            results=[],
            overall="READY",
            warnings=0,
            errors=0,
            manual=0,
            not_configured=0,
            skipped=0,
            passed=0,
            total=0,
            duration_secs=0,
        )


class TestInfrastructureScopeAuthGating:
    def test_infrastructure_scope_runs_without_dataverse_endpoint(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        local_dir = tmp_path / ".local"
        local_dir.mkdir()
        (local_dir / "config.json").write_text('{"agents":[]}', encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cli, "FlightCheckRunner", _FakeRunner)
        monkeypatch.setattr(cli, "_print_prioritized_summary", lambda _result: None)
        monkeypatch.setattr(cli, "save_results", lambda _result, _output: None)
        monkeypatch.setattr(
            cli,
            "GraphClient",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Graph auth should be skipped")),
        )
        monkeypatch.setattr(
            cli,
            "PPAdminClient",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PP auth should be skipped")),
        )
        monkeypatch.setattr(
            cli,
            "PVAClient",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PVA auth should be skipped")),
        )
        monkeypatch.setattr("sys.argv", ["cli.py", "--scope", "infrastructure", "--no-open"])

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 0

    def test_non_infrastructure_scope_requires_dataverse_endpoint(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        local_dir = tmp_path / ".local"
        local_dir.mkdir()
        (local_dir / "config.json").write_text('{"agents":[]}', encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["cli.py", "--scope", "environment", "--no-open"])

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 1


class TestMakeStdioUnicodeSafe:
    """Tests for cli._make_stdio_unicode_safe.

    The terminal summary prints check ``result`` / ``remediation`` text that
    legitimately contains bullets (U+2022), arrows, and em dashes. On a
    default Windows console stdout is cp1252, so those characters raise
    ``UnicodeEncodeError`` mid-print. Because the summary runs BEFORE
    ``save_results`` / ``open_report_in_browser`` in ``main``, that crash also
    loses the HTML report and never opens the browser. This helper forces
    UTF-8 with ``errors="replace"`` so the run can't die on encoding.
    """

    class _FakeStream:
        def __init__(self, reconfigure_exc: Exception | None = None) -> None:
            self.calls: list[dict] = []
            self._exc = reconfigure_exc

        def reconfigure(self, **kwargs) -> None:
            self.calls.append(kwargs)
            if self._exc is not None:
                raise self._exc

    def test_reconfigures_stdout_and_stderr_to_utf8_replace(
        self, monkeypatch
    ) -> None:
        out, err = self._FakeStream(), self._FakeStream()
        monkeypatch.setattr("sys.stdout", out)
        monkeypatch.setattr("sys.stderr", err)

        cli._make_stdio_unicode_safe()

        for stream in (out, err):
            assert stream.calls == [{"encoding": "utf-8", "errors": "replace"}]

    def test_swallows_reconfigure_errors(self, monkeypatch) -> None:
        # Some environments raise when reconfiguring a redirected stream;
        # the helper must never let that abort FlightCheck.
        out = self._FakeStream(reconfigure_exc=OSError("cannot reconfigure"))
        err = self._FakeStream(reconfigure_exc=ValueError("bad stream"))
        monkeypatch.setattr("sys.stdout", out)
        monkeypatch.setattr("sys.stderr", err)

        cli._make_stdio_unicode_safe()  # must not raise

        assert out.calls and err.calls

    def test_no_op_when_stream_lacks_reconfigure(self, monkeypatch) -> None:
        # Wrapped/older streams (e.g. some pytest capture objects) may not
        # expose ``reconfigure``; the helper must skip them silently.
        monkeypatch.setattr("sys.stdout", object())
        monkeypatch.setattr("sys.stderr", object())

        cli._make_stdio_unicode_safe()  # must not raise
