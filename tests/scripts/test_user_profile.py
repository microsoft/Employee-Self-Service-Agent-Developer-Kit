# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

import user_profile


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "solutions" / "ess-maker-skills" / "scripts"
_PROCESS_MAIN = """
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import user_profile
raise SystemExit(user_profile.main(json.loads(sys.argv[2]), path=Path(sys.argv[3])))
"""


def _profile_path(tmp_path: Path) -> Path:
    return tmp_path / ".local" / "user-profile.json"


def _initialize(path: Path) -> user_profile.StoredProfile:
    return user_profile.initialize_profile(path).profile


def _version(profile: user_profile.StoredProfile) -> user_profile.ProfileVersion:
    return profile.version


def _start_process(arguments: list[str], path: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            _PROCESS_MAIN,
            str(_SCRIPTS),
            json.dumps(arguments),
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_missing_profile_resolves_defaults_without_creating_state(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)

    result = user_profile.resolve_profile(path)

    assert result.profile_exists is False
    assert result.version == user_profile.ProfileVersion(None, 0)
    assert result.effective_profile == user_profile.default_effective_profile()
    assert result.onboarding_status is user_profile.OnboardingStatus.NOT_STARTED
    assert result.pending_proposals == ()
    assert not path.parent.exists()


def test_initialize_writes_canonical_profile_and_is_idempotent(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)

    created = user_profile.initialize_profile(path)
    repeated = user_profile.initialize_profile(path)

    assert created.changed is True
    assert created.committed is True
    assert created.profile.revision == 1
    assert uuid.UUID(created.profile.generation).version == 4
    assert repeated.changed is False
    assert repeated.profile == created.profile
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert (path.parent / "user-profile.lock").exists()


def test_simultaneous_initializers_preserve_one_generation(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    processes = [_start_process(["initialize"], path) for _ in range(4)]

    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        results.append(json.loads(stdout))

    generations = {
        result["profile"]["generation"]
        for result in results
    }
    assert len(generations) == 1
    assert sum(result["changed"] for result in results) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("responseFormat", "table_first"),
        ("detailLevel", "detailed"),
        ("toneOfVoice", "empathetic"),
        ("confirmationFrequency", "frequent"),
        ("maximumResponseLength", {"value": 50, "unit": "words"}),
        ("maximumResponseLength", {"value": 5000, "unit": "words"}),
        ("maximumResponseLength", {"value": None, "unit": "words"}),
        ("proactiveSuggestions", "on"),
    ],
)
def test_set_accepts_documented_values(
    tmp_path: Path, field: str, value: object
) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)

    result = user_profile.set_preferences(
        path, {field: value}, expected_version=_version(profile)
    )

    assert result.changed is True
    assert result.profile.revision == 2
    assert result.profile.preferences[field].source is user_profile.PreferenceSource.EXPLICIT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("responseFormat", "TABLE"),
        ("detailLevel", "verbose"),
        ("toneOfVoice", "casual"),
        ("confirmationFrequency", "never"),
        ("maximumResponseLength", {"value": 49, "unit": "words"}),
        ("maximumResponseLength", {"value": 5001, "unit": "words"}),
        ("maximumResponseLength", {"value": True, "unit": "words"}),
        ("proactiveSuggestions", "always"),
    ],
)
def test_invalid_set_does_not_partially_write(
    tmp_path: Path, field: str, value: object
) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)
    before = path.read_bytes()

    with pytest.raises(user_profile.UserProfileArgumentError):
        user_profile.set_preferences(
            path,
            {"detailLevel": "concise", field: value},
            expected_version=_version(profile),
        )

    assert path.read_bytes() == before


def test_partial_update_preserves_other_preferences_and_noop_revision(
    tmp_path: Path,
) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)

    changed = user_profile.set_preferences(
        path,
        {"detailLevel": "concise"},
        expected_version=profile.version,
    )
    repeated = user_profile.set_preferences(
        path,
        {"detailLevel": "concise"},
        expected_version=changed.profile.version,
    )

    assert changed.profile.preferences["responseFormat"] == profile.preferences["responseFormat"]
    assert repeated.changed is False
    assert repeated.profile.revision == 2


def test_default_source_uses_current_default_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _profile_path(tmp_path)
    _initialize(path)
    before = path.read_bytes()
    monkeypatch.setitem(
        user_profile.DEFAULT_VALUES,
        "detailLevel",
        user_profile.DetailLevel.DETAILED,
    )

    resolved = user_profile.resolve_profile(path)

    assert resolved.effective_profile.detail_level is user_profile.DetailLevel.DETAILED
    assert path.read_bytes() == before


def test_explicit_value_remains_pinned_when_default_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)
    changed = user_profile.set_preferences(
        path,
        {"detailLevel": "concise"},
        expected_version=profile.version,
    )
    monkeypatch.setitem(
        user_profile.DEFAULT_VALUES,
        "detailLevel",
        user_profile.DetailLevel.DETAILED,
    )

    resolved = user_profile.resolve_profile(path)

    assert resolved.version == changed.profile.version
    assert resolved.effective_profile.detail_level is user_profile.DetailLevel.CONCISE


def test_proposal_does_not_apply_until_accepted(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)
    proposed = user_profile.propose_preference(
        path,
        "detailLevel",
        "concise",
        3,
        0.86,
        expected_version=profile.version,
    )

    before_accept = user_profile.resolve_profile(path)
    accepted = user_profile.accept_proposal(
        path,
        "detailLevel",
        expected_version=proposed.profile.version,
    )
    after_accept = user_profile.resolve_profile(path)

    assert before_accept.effective_profile.detail_level is user_profile.DetailLevel.BALANCED
    assert len(before_accept.pending_proposals) == 1
    assert accepted.profile.preferences["detailLevel"].source is user_profile.PreferenceSource.LEARNED
    assert after_accept.effective_profile.detail_level is user_profile.DetailLevel.CONCISE
    assert after_accept.pending_proposals == ()


def test_reject_preserves_active_value_and_terminal_decision(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)
    proposed = user_profile.propose_preference(
        path,
        "responseFormat",
        "bullets",
        2,
        0.75,
        expected_version=profile.version,
    )

    rejected = user_profile.reject_proposal(
        path,
        "responseFormat",
        expected_version=proposed.profile.version,
    )

    assert rejected.profile.preferences["responseFormat"] == profile.preferences["responseFormat"]
    assert rejected.profile.proposals["responseFormat"].status is user_profile.ProposalStatus.REJECTED
    with pytest.raises(user_profile.UserProfileProposalError) as error:
        user_profile.reject_proposal(
            path,
            "responseFormat",
            expected_version=rejected.profile.version,
        )
    assert error.value.status == "proposal_not_pending"


def test_same_proposal_is_noop_and_metadata_update_preserves_created_at(
    tmp_path: Path,
) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)
    first = user_profile.propose_preference(
        path,
        "detailLevel",
        "concise",
        2,
        0.7,
        expected_version=profile.version,
    )
    repeated = user_profile.propose_preference(
        path,
        "detailLevel",
        "concise",
        2,
        0.7,
        expected_version=first.profile.version,
    )
    updated = user_profile.propose_preference(
        path,
        "detailLevel",
        "concise",
        3,
        0.8,
        expected_version=repeated.profile.version,
    )

    assert repeated.changed is False
    assert updated.profile.proposals["detailLevel"].created_at == first.profile.proposals["detailLevel"].created_at
    assert updated.profile.proposals["detailLevel"].observation_count == 3


def test_explicit_set_removes_terminal_proposal(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)
    proposal = user_profile.propose_preference(
        path,
        "detailLevel",
        "concise",
        2,
        0.7,
        expected_version=profile.version,
    )
    rejected = user_profile.reject_proposal(
        path,
        "detailLevel",
        expected_version=proposal.profile.version,
    )

    changed = user_profile.set_preferences(
        path,
        {"detailLevel": "balanced"},
        expected_version=rejected.profile.version,
    )

    assert "detailLevel" not in changed.profile.proposals
    assert changed.profile.preferences["detailLevel"].source is user_profile.PreferenceSource.EXPLICIT


def test_stale_version_conflicts_even_for_noop(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)
    changed = user_profile.set_preferences(
        path,
        {"detailLevel": "concise"},
        expected_version=profile.version,
    )
    before = path.read_bytes()

    with pytest.raises(user_profile.UserProfileConflictError) as error:
        user_profile.set_preferences(
            path,
            {"detailLevel": "concise"},
            expected_version=profile.version,
        )

    assert error.value.actual_version == changed.profile.version
    assert path.read_bytes() == before


def test_simultaneous_writers_yield_one_commit_and_one_conflict(
    tmp_path: Path,
) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)
    version = profile.version.token()
    first = _start_process(
        [
            "set",
            "--values-json",
            '{"detailLevel":"concise"}',
            "--expected-version",
            version,
        ],
        path,
    )
    second = _start_process(
        [
            "set",
            "--values-json",
            '{"detailLevel":"detailed"}',
            "--expected-version",
            version,
        ],
        path,
    )

    outputs = []
    for process in (first, second):
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode in {0, 4}, stderr
        outputs.append(json.loads(stdout))

    assert sorted(output["status"] for output in outputs) == [
        "ok",
        "profile_conflict",
    ]
    assert user_profile.load_profile(path).revision == 2


def test_onboarding_transition_and_noop(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)

    completed = user_profile.set_onboarding_status(
        path,
        user_profile.OnboardingStatus.COMPLETED,
        expected_version=profile.version,
    )
    repeated = user_profile.set_onboarding_status(
        path,
        user_profile.OnboardingStatus.COMPLETED,
        expected_version=completed.profile.version,
    )

    assert completed.profile.onboarding.updated_at.endswith("Z")
    assert repeated.changed is False

    restarted = user_profile.set_onboarding_status(
        path,
        user_profile.OnboardingStatus.NOT_STARTED,
        expected_version=repeated.profile.version,
    )
    assert restarted.profile.onboarding.updated_at is not None


def test_reset_requires_confirmation_and_preserves_generation(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    profile = _initialize(path)
    changed = user_profile.set_preferences(
        path,
        {"detailLevel": "concise"},
        expected_version=profile.version,
    )

    with pytest.raises(user_profile.UserProfileConfirmationError):
        user_profile.reset_profile(
            path, expected_version=changed.profile.version
        )
    reset = user_profile.reset_profile(
        path,
        expected_version=changed.profile.version,
        confirmed=True,
    )

    assert reset.profile.generation == profile.generation
    assert reset.profile.revision == 3
    assert reset.profile == user_profile.default_profile(
        generation=profile.generation, revision=3
    )


def test_recovery_preserves_exact_bytes_and_rotates_generation(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    path.parent.mkdir(parents=True)
    damaged = b'{"schemaVersion":1,"broken":true}\n'
    path.write_bytes(damaged)
    digest = hashlib.sha256(damaged).hexdigest()

    recovered = user_profile.recover_profile(
        path,
        expected_content_hash=digest,
        confirmed=True,
    )

    assert recovered.backup_path is not None
    assert recovered.backup_path.read_bytes() == damaged
    assert recovered.profile.revision == 1
    assert user_profile.load_profile(path) == recovered.profile


def test_recovery_rejects_changed_or_valid_state(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    _initialize(path)
    valid_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(user_profile.UserProfileProposalError) as valid_error:
        user_profile.recover_profile(
            path,
            expected_content_hash=valid_hash,
            confirmed=True,
        )
    assert valid_error.value.status == "recovery_not_required"

    path.write_text("{", encoding="utf-8")
    with pytest.raises(user_profile.UserProfileConflictError):
        user_profile.recover_profile(
            path,
            expected_content_hash=valid_hash,
            confirmed=True,
        )

    assert path.read_text(encoding="utf-8") == "{"


def test_strict_json_rejects_duplicate_unknown_and_non_finite_fields(
    tmp_path: Path,
) -> None:
    path = _profile_path(tmp_path)
    path.parent.mkdir(parents=True)
    invalid_documents = [
        b'{"schemaVersion":1,"schemaVersion":1}',
        json.dumps(
            {
                **user_profile.default_profile(
                    generation=str(uuid.uuid4()), revision=1
                ).to_document(),
                "extra": True,
            }
        ).encode(),
        b'{"schemaVersion":1,"confidence":NaN}',
    ]

    for raw in invalid_documents:
        path.write_bytes(raw)
        with pytest.raises(user_profile.UserProfileValidationError):
            user_profile.load_profile(path)


@pytest.mark.parametrize("version", [0, 2])
def test_unknown_schema_versions_are_unsupported_before_shape_validation(
    tmp_path: Path, version: int
) -> None:
    path = _profile_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schemaVersion": version, "unknown": True}))

    with pytest.raises(user_profile.UserProfileSchemaVersionError) as error:
        user_profile.load_profile(path)

    assert error.value.content_hash == hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(user_profile.UserProfileSchemaVersionError):
        user_profile.validate_profile(
            {"schemaVersion": version, "unknown": True}
        )


def test_service_rejects_invalid_expected_version_before_reading(
    tmp_path: Path,
) -> None:
    path = _profile_path(tmp_path)

    with pytest.raises(user_profile.UserProfileArgumentError):
        user_profile.set_preferences(
            path,
            {"detailLevel": "concise"},
            expected_version=user_profile.ProfileVersion(None, 1),
        )

    assert not path.parent.exists()


def test_cli_success_and_error_envelopes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _profile_path(tmp_path)

    assert user_profile.main(["resolve"], path=path) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["status"] == "ok"
    assert resolved["version"] == "none:0"

    assert user_profile.main(["get"], path=path) == 3
    missing = json.loads(capsys.readouterr().out)
    assert missing["status"] == "profile_not_found"
    assert missing["committed"] is False
    assert "effectiveProfile" not in missing


def test_cli_stdin_round_trip_and_conflict_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _profile_path(tmp_path)
    assert user_profile.main(["initialize"], path=path) == 0
    initialized = json.loads(capsys.readouterr().out)
    version = initialized["version"]

    assert user_profile.main(
        [
            "set",
            "--values-stdin",
            "--expected-version",
            version,
        ],
        path=path,
        stdin_text='{"maximumResponseLength":{"value":400,"unit":"words"}}',
    ) == 0
    changed = json.loads(capsys.readouterr().out)
    assert changed["profile"]["preferences"]["maximumResponseLength"]["value"] == 400

    assert user_profile.main(
        [
            "set",
            "--values-json",
            '{"detailLevel":"balanced"}',
            "--expected-version",
            version,
        ],
        path=path,
    ) == 4
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["status"] == "profile_conflict"
    assert conflict["expectedVersion"] == version
    assert conflict["actualVersion"] == changed["version"]
