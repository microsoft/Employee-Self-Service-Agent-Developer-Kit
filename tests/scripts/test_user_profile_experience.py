# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

import user_profile


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    local = tmp_path / ".local"
    return local / "user-profile.json", local / "user-profile-experience.json"


def _resolve(profile_path: Path, experience_path: Path) -> user_profile.ExperienceResolution:
    return user_profile.resolve_experience(profile_path, experience_path)


def _begin(
    profile_path: Path,
    experience_path: Path,
    *,
    request_id: str | None = None,
    resolution: user_profile.ExperienceResolution | None = None,
) -> user_profile.ExperienceMutationResult:
    current = resolution or _resolve(profile_path, experience_path)
    assert current.experience_version is not None
    return user_profile.begin_profile_request(
        profile_path,
        experience_path,
        request_id or str(uuid.uuid4()),
        expected_profile_version=current.profile.version,
        expected_experience_version=current.experience_version,
    )


def _finish(
    profile_path: Path,
    experience_path: Path,
    request_id: str,
    begin: user_profile.ExperienceMutationResult,
    profile_version: user_profile.ProfileVersion,
    *,
    outcome: user_profile.TaskOutcome = user_profile.TaskOutcome.COMPLETED,
    allows_extra_content: bool = False,
    optional_suggestion_used: bool = False,
) -> user_profile.ExperienceMutationResult:
    assert begin.experience is not None
    return user_profile.finish_profile_request(
        profile_path,
        experience_path,
        request_id,
        expected_profile_version=profile_version,
        expected_experience_version=begin.experience.version,
        outcome=outcome,
        allows_extra_content=allows_extra_content,
        optional_suggestion_used=optional_suggestion_used,
    )


def test_combined_resolution_has_no_write_for_missing_parent(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)

    result = _resolve(profile_path, experience_path)

    assert result.profile.version == user_profile.ProfileVersion(None, 0)
    assert result.experience_version == user_profile.ExperienceVersion(None, 0)
    assert result.cadence_available is True
    assert result.state_exists is False
    assert not profile_path.parent.exists()


def test_begin_claims_initial_invitation_once_and_only_writes_experience(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    initial = _resolve(profile_path, experience_path)
    request_id = str(uuid.uuid4())

    claimed = _begin(
        profile_path,
        experience_path,
        request_id=request_id,
        resolution=initial,
    )
    replay = user_profile.begin_profile_request(
        profile_path,
        experience_path,
        request_id,
        expected_profile_version=initial.profile.version,
        expected_experience_version=initial.experience_version,
    )

    assert claimed.onboarding_offer == "initial"
    assert claimed.experience is not None
    assert claimed.experience.eligible_run_count == 1
    assert replay.replayed is True
    assert replay.changed is False
    assert replay.onboarding_offer == "none"
    assert not profile_path.exists()
    assert experience_path.exists()


def test_abandoned_invitation_is_reoffered_after_three_later_runs(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    first = _begin(profile_path, experience_path)
    assert first.onboarding_offer == "initial"

    for expected_offer in ("none", "none", "deferred_reoffer"):
        later = _begin(profile_path, experience_path)
        assert later.onboarding_offer == expected_offer
        assert later.experience is not None
        assert later.experience.eligible_run_count in {2, 3, 4}


def test_completed_empty_onboarding_binds_history_and_preserves_defaults(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    first = _begin(profile_path, experience_path)
    assert first.experience is not None

    saved = user_profile.complete_onboarding(
        profile_path,
        experience_path,
        {},
        expected_profile_version=user_profile.ProfileVersion(None, 0),
        confirmed=True,
    )

    assert saved.profile.revision == 1
    assert saved.profile.onboarding.status is user_profile.OnboardingStatus.COMPLETED
    assert all(
        item.source is user_profile.PreferenceSource.DEFAULT
        for item in saved.profile.preferences.values()
    )
    assert saved.experience_committed is True
    state = user_profile.load_experience_state(experience_path)
    assert state.profile_generation == saved.profile.generation
    assert state.eligible_run_count == 1
    assert state.request_receipts[0].onboarding_offer == "initial"


def test_deferral_creates_default_profile_and_preserves_claim(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    begin = _begin(profile_path, experience_path)
    assert begin.experience is not None
    receipt = begin.experience.request_receipts[0]

    deferred = user_profile.defer_onboarding(
        profile_path,
        experience_path,
        receipt.request_id,
        expected_profile_version=user_profile.ProfileVersion(None, 0),
    )

    assert deferred.profile.onboarding.status is user_profile.OnboardingStatus.DEFERRED
    assert deferred.profile.revision == 1
    assert deferred.experience_committed is True
    state = user_profile.load_experience_state(experience_path)
    assert state.eligible_run_count == 1
    assert state.onboarding_prompt.prompt_count == 1


def test_deferred_profile_preserves_existing_preferences_and_proposals(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    profile = user_profile.initialize_profile(profile_path).profile
    proposed = user_profile.propose_preference(
        profile_path,
        "detailLevel",
        "concise",
        2,
        0.7,
        expected_version=profile.version,
    ).profile
    begin = _begin(profile_path, experience_path)
    assert begin.experience is not None
    receipt = begin.experience.request_receipts[0]

    deferred = user_profile.defer_onboarding(
        profile_path,
        experience_path,
        receipt.request_id,
        expected_profile_version=proposed.version,
    )

    assert deferred.profile.preferences == proposed.preferences
    assert deferred.profile.proposals == proposed.proposals
    assert deferred.profile.revision == proposed.revision + 1


def test_concurrent_initial_claims_have_one_winner(tmp_path: Path) -> None:
    profile_path, experience_path = _paths(tmp_path)
    snapshot = _resolve(profile_path, experience_path)
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import user_profile
raise SystemExit(user_profile.main([
    "experience", "begin",
    "--request-id", sys.argv[4],
    "--expected-version", sys.argv[5],
    "--expected-experience-version", sys.argv[6],
], path=Path(sys.argv[2]))
)
"""
    scripts = Path(user_profile.__file__).resolve().parent
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(scripts),
                str(profile_path),
                str(experience_path),
                request_id,
                snapshot.profile.version.token(),
                snapshot.experience_version.token(),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for request_id in ids
    ]
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        results.append((process.returncode, stdout, stderr))

    assert sorted(code for code, _, _ in results) == [0, 4]
    success = next(stdout for code, stdout, _ in results if code == 0)
    assert json.loads(success)["onboardingOffer"] == "initial"
    assert user_profile.load_experience_state(experience_path).eligible_run_count == 1


def test_finish_claims_pending_proposal_only_after_allowed_completion(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    profile = user_profile.initialize_profile(profile_path).profile
    proposed = user_profile.propose_preference(
        profile_path,
        "detailLevel",
        "concise",
        4,
        0.8,
        expected_version=profile.version,
    ).profile
    begin = _begin(profile_path, experience_path)
    assert begin.experience is not None
    request_id = begin.experience.request_receipts[-1].request_id

    finished = _finish(
        profile_path,
        experience_path,
        request_id,
        begin,
        proposed.version,
        allows_extra_content=True,
    )

    assert finished.proposal_field == "detailLevel"
    assert finished.proposal == proposed.proposals["detailLevel"]
    assert finished.reviewed_version == proposed.version
    assert finished.experience is not None
    assert finished.experience.proposal_prompts["detailLevel"].prompt_count == 1


def test_proposal_reappears_after_three_later_runs_and_suppresses_after_second_snooze(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    profile = user_profile.initialize_profile(profile_path).profile
    proposal_result = user_profile.propose_preference(
        profile_path,
        "detailLevel",
        "concise",
        4,
        0.8,
        expected_version=profile.version,
    )
    profile = proposal_result.profile
    first = _begin(profile_path, experience_path)
    first_id = first.experience.request_receipts[-1].request_id
    claimed = _finish(
        profile_path,
        experience_path,
        first_id,
        first,
        profile.version,
        allows_extra_content=True,
    )
    assert claimed.proposal_field == "detailLevel"
    snoozed = user_profile.snooze_proposal_prompt(
        profile_path,
        experience_path,
        "detailLevel",
        profile.proposals["detailLevel"].created_at,
        expected_profile_version=profile.version,
        expected_experience_version=claimed.experience.version,
        origin=user_profile.PromptOrigin.AUTOMATIC,
    )
    assert snoozed.changed is False

    for index in range(3):
        begin = _begin(profile_path, experience_path)
        request_id = begin.experience.request_receipts[-1].request_id
        finished = _finish(
            profile_path,
            experience_path,
            request_id,
            begin,
            profile.version,
            allows_extra_content=index == 2,
        )
    assert finished.proposal_field == "detailLevel"
    suppressed = user_profile.snooze_proposal_prompt(
        profile_path,
        experience_path,
        "detailLevel",
        profile.proposals["detailLevel"].created_at,
        expected_profile_version=profile.version,
        expected_experience_version=finished.experience.version,
        origin=user_profile.PromptOrigin.AUTOMATIC,
    )
    assert suppressed.changed is True
    assert suppressed.experience.proposal_prompts["detailLevel"].suppressed is True


def test_explicit_proposal_snooze_at_run_zero_sets_baseline_without_claim(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    profile = user_profile.initialize_profile(profile_path).profile
    profile = user_profile.propose_preference(
        profile_path,
        "responseFormat",
        "bullets",
        2,
        0.6,
        expected_version=profile.version,
    ).profile
    resolved = _resolve(profile_path, experience_path)

    snoozed = user_profile.snooze_proposal_prompt(
        profile_path,
        experience_path,
        "responseFormat",
        profile.proposals["responseFormat"].created_at,
        expected_profile_version=profile.version,
        expected_experience_version=resolved.experience_version,
        origin=user_profile.PromptOrigin.EXPLICIT,
    )

    prompt = snoozed.experience.proposal_prompts["responseFormat"]
    assert prompt.prompt_count == 0
    assert prompt.last_prompt_run is None
    assert prompt.snoozed_at_run == 0


def test_cross_file_failure_reports_commit_and_reconciles_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    _begin(profile_path, experience_path)
    original_persist = user_profile._persist_experience
    calls = 0

    def fail_finalization(path: Path, state: user_profile.ExperienceState) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise user_profile.UserProfilePersistenceError(
                "Simulated finalization failure.", path=path
            )
        original_persist(path, state)

    monkeypatch.setattr(user_profile, "_persist_experience", fail_finalization)
    with pytest.raises(user_profile.UserProfilePersistenceError) as error:
        user_profile.complete_onboarding(
            profile_path,
            experience_path,
            {"detailLevel": "detailed"},
            expected_profile_version=user_profile.ProfileVersion(None, 0),
            confirmed=True,
        )

    assert error.value.committed is True
    assert error.value.reconciliation_required is True
    committed_profile = user_profile.load_profile(profile_path)
    intent_state = user_profile.load_experience_state(experience_path)
    assert intent_state.pending_profile_change is not None
    monkeypatch.setattr(user_profile, "_persist_experience", original_persist)
    reconciled = user_profile.reconcile_experience_state(
        profile_path,
        experience_path,
        expected_experience_version=intent_state.version,
    )

    assert reconciled.changed is True
    assert reconciled.experience.pending_profile_change is None
    assert user_profile.load_profile(profile_path) == committed_profile


def test_unmatched_pending_intent_blocks_writers_without_profile_replay(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    begin = _begin(profile_path, experience_path)
    state = begin.experience
    intent = user_profile.PendingProfileChange(
        operation="recover",
        before_version=None,
        before_content_hash="a" * 64,
        after_version=f"{uuid.uuid4()}:1",
        after_content_hash="b" * 64,
        experience_effect="reset",
    )
    pending = replace(
        state,
        revision=state.revision + 1,
        pending_profile_change=intent,
    )
    user_profile._persist_experience(experience_path, pending)
    with pytest.raises(user_profile.UserProfileExperienceReconciliationError):
        user_profile.complete_onboarding(
            profile_path,
            experience_path,
            {"detailLevel": "detailed"},
            expected_profile_version=user_profile.ProfileVersion(None, 0),
            confirmed=True,
        )
    assert not profile_path.exists()


def test_reset_rotates_experience_generation_when_profile_is_already_default(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    profile = user_profile.initialize_profile(profile_path).profile
    _begin(profile_path, experience_path)
    current = user_profile.load_experience_state(experience_path)

    reset = user_profile.reset_profile(
        profile_path,
        expected_version=profile.version,
        confirmed=True,
    )

    assert reset.changed is True
    assert reset.profile_changed is False
    assert reset.experience_committed is True
    new_state = user_profile.load_experience_state(experience_path)
    assert new_state.generation != current.generation
    assert new_state.eligible_run_count == 0
    assert new_state.onboarding_prompt.suppressed is False


def test_experience_repair_backs_up_exact_bytes_and_suppresses_prompts(
    tmp_path: Path,
) -> None:
    profile_path, experience_path = _paths(tmp_path)
    profile = user_profile.initialize_profile(profile_path).profile
    experience_path.parent.mkdir(parents=True, exist_ok=True)
    damaged = b'{"schemaVersion":1,"bad":true}\n'
    experience_path.write_bytes(damaged)
    resolved = _resolve(profile_path, experience_path)
    assert resolved.experience_version is None

    repaired = user_profile.recover_experience_state(
        profile_path,
        experience_path,
        expected_content_hash=hashlib.sha256(damaged).hexdigest(),
        expected_profile_version=profile.version,
        confirmed=True,
    )

    assert repaired.backup_path is not None
    assert repaired.backup_path.read_bytes() == damaged
    assert repaired.experience.onboarding_prompt.suppressed is True
    assert repaired.experience.profile_generation == profile.generation


def test_preview_is_deterministic_and_disk_free(tmp_path: Path) -> None:
    profile_path, experience_path = _paths(tmp_path)
    values = {
        "responseFormat": "table_first",
        "detailLevel": "detailed",
        "toneOfVoice": "formal",
        "confirmationFrequency": "standard",
        "maximumResponseLength": {"value": 800, "unit": "words"},
        "proactiveSuggestions": "contextual",
    }

    first = user_profile.preview_profile(values)
    second = user_profile.preview_profile(values)

    assert first == second
    assert first.persona_name == "Curious Architect"
    assert first.example_label == "Example response - no action performed"
    assert "Review is required." in first.example
    assert "No live deployment occurred." in first.example
    assert not profile_path.parent.exists()
    assert not experience_path.exists()


def test_experience_cli_json_envelopes_and_stdin_save(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile_path, experience_path = _paths(tmp_path)

    assert user_profile.main(
        ["experience", "resolve"], path=profile_path
    ) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["experienceVersion"] == "none:0"
    assert resolved["profile"] is None

    request_id = str(uuid.uuid4())
    assert user_profile.main(
        [
            "experience",
            "begin",
            "--request-id",
            request_id,
            "--expected-version",
            "none:0",
            "--expected-experience-version",
            "none:0",
        ],
        path=profile_path,
    ) == 0
    begun = json.loads(capsys.readouterr().out)
    assert begun["onboardingOffer"] == "initial"
    assert begun["experienceStateExists"] is True

    assert user_profile.main(
        [
            "onboarding-complete",
            "--values-stdin",
            "--expected-version",
            "none:0",
            "--yes",
        ],
        path=profile_path,
        stdin_text="{}",
    ) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["profile"]["onboarding"]["status"] == "completed"
    assert saved["profileChanged"] is True
    assert saved["experienceCommitted"] is True

    assert experience_path.exists()
