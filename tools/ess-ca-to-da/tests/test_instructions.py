from __future__ import annotations

import pytest

from essmig import llm
from essmig.instructions import keep_target_instructions, reconcile_instructions


def test_reconcile_passes_all_three_versions_and_strips_the_reply() -> None:
    seen: dict[str, str] = {}

    def fake_complete(system: str, user: str) -> str:
        seen["system"] = system
        seen["user"] = user
        return "  merged DA instructions  \n"

    result = reconcile_instructions(
        "CA base", "CA edited", "DA today", complete=fake_complete
    )

    assert result == "merged DA instructions"
    # All three versions must reach the model, or it cannot isolate the delta.
    assert "CA base" in seen["user"]
    assert "CA edited" in seen["user"]
    assert "DA today" in seen["user"]


def test_keep_target_instructions_is_an_offline_no_op() -> None:
    assert keep_target_instructions("base", "ours", "theirs") == "theirs"


def test_a_missing_gh_cli_raises_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_gh(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("gh")

    monkeypatch.setattr(llm.subprocess, "run", missing_gh)
    with pytest.raises(llm.LlmUnavailable, match="gh"):
        llm.gh_token()
