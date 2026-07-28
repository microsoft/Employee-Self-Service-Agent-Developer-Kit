# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for flightcheck.consent (runtime-reachability consent UX).

Covers the tri-state resolver, the safe-by-default Y/N reader, system-name
normalization, and the message builders (including the direct IP-ranges /
service-tags JSON link on the manual-verification path)."""

import io

import pytest

from flightcheck import consent


class TestSystemLabel:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Workday", "Workday"),
            ("workday", "Workday"),
            ("ServiceNow", "ServiceNow"),
            ("servicenow", "ServiceNow"),
            ("SuccessFactors", "SAP SuccessFactors"),
            ("SAPSuccessFactors", "SAP SuccessFactors"),
            ("Contoso HR", "Contoso HR"),   # unknown -> passthrough
        ],
    )
    def test_known_and_unknown(self, raw, expected):
        assert consent.system_label(raw) == expected

    def test_empty_defaults_to_generic(self):
        assert consent.system_label(None) == "your external system"
        assert consent.system_label("") == "your external system"


class TestResolveConsent:
    def test_flag_true_grants_without_prompt(self):
        d = consent.resolve_consent(True, endpoints_present=True, interactive=True)
        assert (d.enabled, d.declined, d.prompted) == (True, False, False)

    def test_flag_false_declines_without_prompt(self):
        d = consent.resolve_consent(False, endpoints_present=True, interactive=True)
        assert (d.enabled, d.declined, d.prompted) == (False, True, False)

    def test_none_no_endpoints_does_not_offer(self):
        called = []
        d = consent.resolve_consent(
            None,
            endpoints_present=False,
            interactive=True,
            prompt_fn=lambda: called.append(1) or True,
        )
        assert (d.enabled, d.declined, d.prompted) == (False, False, False)
        assert called == []  # never prompted

    def test_none_non_interactive_stays_read_only(self):
        d = consent.resolve_consent(None, endpoints_present=True, interactive=False)
        assert (d.enabled, d.declined, d.prompted) == (False, False, False)

    def test_none_interactive_yes(self):
        d = consent.resolve_consent(
            None, endpoints_present=True, interactive=True, prompt_fn=lambda: True
        )
        assert (d.enabled, d.declined, d.prompted) == (True, False, True)

    def test_none_interactive_no(self):
        d = consent.resolve_consent(
            None, endpoints_present=True, interactive=True, prompt_fn=lambda: False
        )
        assert (d.enabled, d.declined, d.prompted) == (False, True, True)


class TestAskYesNo:
    def _ask(self, typed: str, **kw):
        return consent.ask_yes_no(
            "Workday",
            stream_in=io.StringIO(typed),
            stream_out=io.StringIO(),
            **kw,
        )

    @pytest.mark.parametrize("typed", ["y\n", "Y\n", "yes\n", "  yes \n"])
    def test_yes(self, typed):
        assert self._ask(typed) is True

    @pytest.mark.parametrize("typed", ["n\n", "N\n", "no\n"])
    def test_no(self, typed):
        assert self._ask(typed) is False

    def test_eof_declines(self):
        assert self._ask("") is False

    def test_ambiguous_then_yes(self):
        assert self._ask("maybe\nyes\n") is True

    def test_all_ambiguous_declines(self):
        assert self._ask("a\nb\nc\nd\n", max_attempts=3) is False


class TestMessages:
    def test_offer_prompt_reassurances(self):
        msg = consent.build_offer_prompt("ServiceNow")
        assert "ServiceNow" in msg
        assert "no business data" in msg.lower()
        assert "deleted" in msg.lower()

    def test_skip_message(self):
        msg = consent.build_skip_message("Workday")
        assert "skipped" in msg.lower()
        assert "Workday" in msg

    def test_manual_fallback_has_both_links(self):
        msg = consent.build_manual_fallback("Workday")
        assert consent.OUTBOUND_IP_ARTICLE_URL in msg
        assert consent.SERVICE_TAGS_JSON_URL in msg
        # Markdown link syntax so the HTML report renders it clickable.
        assert "](http" in msg
        assert "Workday" in msg
