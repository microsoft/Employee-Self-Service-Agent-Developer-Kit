# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_SKILLS = (
    _ROOT / "solutions" / "ess-maker-skills" / "src" / "skills" / "user-profile"
)


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


def test_onboarding_uses_five_questions_for_all_six_independent_settings() -> None:
    onboarding = _normalized(_PROFILE_SKILLS / "onboarding.md")

    assert "five questions take about a minute" in onboarding
    assert "### 1. Response format" in onboarding
    assert "### 2. Detail and maximum length" in onboarding
    assert "### 3. Voice" in onboarding
    assert "### 4. Check-ins" in onboarding
    assert "### 5. Optional tips" in onboarding
    assert "The two fields are independent" in onboarding
    assert "skipping length preserves the entry value/source" in onboarding
    assert "length can be answered even if detail is skipped" in onboarding


def test_quiz_keeps_drafts_local_and_requires_confirmed_save() -> None:
    onboarding = _normalized(_PROFILE_SKILLS / "onboarding.md")

    assert "Keep answers in conversation context only" in onboarding
    assert "free text that must be mapped and confirmed before entering the draft" in onboarding
    assert "Only confirmed values enter the draft" in onboarding
    assert "Only confirmed values enter the draft" in onboarding
    assert "On save, send only answered fields to onboarding-complete" in onboarding
    assert "{} is valid when every question was skipped" in onboarding
    assert "On conflict, resolve again and require a new review" in onboarding


def test_invitation_privacy_and_continuation_contracts_are_preserved() -> None:
    onboarding = _normalized(_PROFILE_SKILLS / "onboarding.md")

    assert "never blocks the original skill" in onboarding
    assert "successful onboardingOffer from experience begin" in onboarding
    assert "local reminder history records that an invitation was offered but does not store quiz answers" in onboarding
    assert "no name, email, UPN, employee ID, or transcript is saved or sent to Copilot Studio" in onboarding
    assert "continue with the resolved current profile" in onboarding
    assert "resume the original request using one fresh experience resolve snapshot" in onboarding
    assert "Never invent resumption after conversation context is lost" in onboarding


def test_onboarding_preview_is_deterministic_and_not_a_claim_of_task_execution() -> None:
    onboarding = _normalized(_PROFILE_SKILLS / "onboarding.md")

    assert "preview --values-stdin" in onboarding
    assert "Example response - no action performed" in onboarding
    assert "The example is fictional and must not be represented as an actual task result" in onboarding
    assert "Show the returned persona" in onboarding
    assert "The example is fictional" in onboarding
