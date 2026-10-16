# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Local maker user-profile service and JSON command-line interface."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterator, Mapping, NoReturn
import uuid


SCHEMA_VERSION = 1
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_RETRY_SECONDS = 0.05
SOLUTION_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = SOLUTION_ROOT / ".local" / "user-profile.json"
DEFAULT_EXPERIENCE_PATH = (
    SOLUTION_ROOT / ".local" / "user-profile-experience.json"
)
PREFERENCE_FIELDS = (
    "responseFormat",
    "detailLevel",
    "toneOfVoice",
    "confirmationFrequency",
    "maximumResponseLength",
    "proactiveSuggestions",
)


class ResponseFormat(str, Enum):
    AUTO = "auto"
    PROSE = "prose"
    BULLETS = "bullets"
    STEPS = "steps"
    TABLE_FIRST = "table_first"


class DetailLevel(str, Enum):
    CONCISE = "concise"
    BALANCED = "balanced"
    DETAILED = "detailed"


class ToneOfVoice(str, Enum):
    DIRECT = "direct"
    FRIENDLY_PROFESSIONAL = "friendly_professional"
    FORMAL = "formal"
    EMPATHETIC = "empathetic"


class ConfirmationFrequency(str, Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    FREQUENT = "frequent"


class ProactiveSuggestions(str, Enum):
    OFF = "off"
    CONTEXTUAL = "contextual"
    ON = "on"


class PreferenceSource(str, Enum):
    DEFAULT = "default"
    EXPLICIT = "explicit"
    LEARNED = "learned"


class OnboardingStatus(str, Enum):
    NOT_STARTED = "not_started"
    DEFERRED = "deferred"
    COMPLETED = "completed"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class TaskOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class PromptOrigin(str, Enum):
    AUTOMATIC = "automatic"
    EXPLICIT = "explicit"


PREFERENCE_ENUMS: dict[str, type[Enum]] = {
    "responseFormat": ResponseFormat,
    "detailLevel": DetailLevel,
    "toneOfVoice": ToneOfVoice,
    "confirmationFrequency": ConfirmationFrequency,
    "proactiveSuggestions": ProactiveSuggestions,
}


@dataclass(frozen=True)
class EffectiveProfile:
    response_format: ResponseFormat
    detail_level: DetailLevel
    tone_of_voice: ToneOfVoice
    confirmation_frequency: ConfirmationFrequency
    maximum_response_length: int | None
    proactive_suggestions: ProactiveSuggestions


@dataclass(frozen=True)
class ProfileVersion:
    generation: str | None
    revision: int

    def token(self) -> str:
        if self.generation is None:
            return "none:0"
        return f"{self.generation}:{self.revision}"


@dataclass(frozen=True)
class OnboardingState:
    status: OnboardingStatus
    updated_at: str | None


@dataclass(frozen=True)
class StoredPreference:
    value: Enum | int | None
    source: PreferenceSource
    updated_at: str | None
    unit: str | None = None


@dataclass(frozen=True)
class PreferenceProposal:
    proposed_value: Enum | int | None
    observation_count: int
    confidence: float
    status: ProposalStatus
    created_at: str
    updated_at: str
    unit: str | None = None


@dataclass(frozen=True)
class StoredProfile:
    schema_version: int
    generation: str
    revision: int
    onboarding: OnboardingState
    preferences: Mapping[str, StoredPreference]
    proposals: Mapping[str, PreferenceProposal]

    @property
    def version(self) -> ProfileVersion:
        return ProfileVersion(self.generation, self.revision)

    def to_document(self) -> dict[str, Any]:
        preferences: dict[str, Any] = {}
        for field in PREFERENCE_FIELDS:
            preference = self.preferences[field]
            item: dict[str, Any] = {"value": _json_value(preference.value)}
            if field == "maximumResponseLength":
                item["unit"] = preference.unit
            item["source"] = preference.source.value
            item["updatedAt"] = preference.updated_at
            preferences[field] = item

        proposals: dict[str, Any] = {}
        for field in PREFERENCE_FIELDS:
            proposal = self.proposals.get(field)
            if proposal is None:
                continue
            proposed_value: Any = _json_value(proposal.proposed_value)
            if field == "maximumResponseLength":
                proposed_value = {
                    "value": proposed_value,
                    "unit": proposal.unit,
                }
            proposals[field] = {
                "proposedValue": proposed_value,
                "observationCount": proposal.observation_count,
                "confidence": proposal.confidence,
                "status": proposal.status.value,
                "createdAt": proposal.created_at,
                "updatedAt": proposal.updated_at,
            }

        return {
            "schemaVersion": self.schema_version,
            "generation": self.generation,
            "revision": self.revision,
            "onboarding": {
                "status": self.onboarding.status.value,
                "updatedAt": self.onboarding.updated_at,
            },
            "preferences": preferences,
            "proposals": proposals,
        }


@dataclass(frozen=True)
class EffectiveProfileResult:
    profile_exists: bool
    version: ProfileVersion
    onboarding_status: OnboardingStatus
    effective_profile: EffectiveProfile
    pending_proposals: tuple[tuple[str, PreferenceProposal], ...]
    profile: StoredProfile | None = None


@dataclass(frozen=True)
class MutationResult:
    changed: bool
    committed: bool
    profile: StoredProfile
    backup_path: Path | None = None
    warnings: tuple[ExperienceWarning, ...] = ()
    experience_version: ExperienceVersion | None = None
    profile_changed: bool | None = None
    experience_committed: bool | None = None


@dataclass(frozen=True)
class ExperienceVersion:
    generation: str | None
    revision: int

    def token(self) -> str:
        if self.generation is None:
            return "none:0"
        return f"{self.generation}:{self.revision}"


@dataclass(frozen=True)
class OnboardingPromptState:
    prompt_count: int
    last_prompt_run: int | None
    suppressed: bool
    last_prompted_at: str | None


@dataclass(frozen=True)
class ProposalPromptState:
    proposal_created_at: str
    prompt_count: int
    last_prompt_run: int | None
    snoozed_at_run: int | None
    suppressed: bool
    last_prompted_at: str | None


@dataclass(frozen=True)
class RequestReceipt:
    request_id: str
    begin_profile_version: str
    run_number: int
    onboarding_offer: str
    finished: bool
    proposal_field: str | None


@dataclass(frozen=True)
class PendingProfileChange:
    operation: str
    before_version: str | None
    before_content_hash: str | None
    after_version: str
    after_content_hash: str
    experience_effect: str


@dataclass(frozen=True)
class ExperienceWarning:
    status: str
    error: str
    path: str
    content_hash: str | None = None


@dataclass(frozen=True)
class ExperienceState:
    schema_version: int
    generation: str | None
    revision: int
    profile_generation: str | None
    eligible_run_count: int
    onboarding_prompt: OnboardingPromptState
    proposal_prompts: Mapping[str, ProposalPromptState]
    request_receipts: tuple[RequestReceipt, ...]
    pending_profile_change: PendingProfileChange | None

    @property
    def version(self) -> ExperienceVersion:
        if self.generation is None:
            return ExperienceVersion(None, 0)
        return ExperienceVersion(self.generation, self.revision)

    def to_document(self) -> dict[str, Any]:
        if self.generation is None or self.revision < 1:
            raise UserProfileExperienceValidationError(
                "Missing experience state cannot be serialized."
            )
        onboarding = self.onboarding_prompt
        pending_change = self.pending_profile_change
        return {
            "schemaVersion": self.schema_version,
            "generation": self.generation,
            "revision": self.revision,
            "profileGeneration": self.profile_generation,
            "eligibleRunCount": self.eligible_run_count,
            "onboardingPrompt": {
                "promptCount": onboarding.prompt_count,
                "lastPromptRun": onboarding.last_prompt_run,
                "suppressed": onboarding.suppressed,
                "lastPromptedAt": onboarding.last_prompted_at,
            },
            "proposalPrompts": {
                field: {
                    "proposalCreatedAt": prompt.proposal_created_at,
                    "promptCount": prompt.prompt_count,
                    "lastPromptRun": prompt.last_prompt_run,
                    "snoozedAtRun": prompt.snoozed_at_run,
                    "suppressed": prompt.suppressed,
                    "lastPromptedAt": prompt.last_prompted_at,
                }
                for field, prompt in self.proposal_prompts.items()
            },
            "requestReceipts": [
                {
                    "requestId": receipt.request_id,
                    "beginProfileVersion": receipt.begin_profile_version,
                    "runNumber": receipt.run_number,
                    "onboardingOffer": receipt.onboarding_offer,
                    "finished": receipt.finished,
                    "proposalField": receipt.proposal_field,
                }
                for receipt in self.request_receipts
            ],
            "pendingProfileChange": (
                None
                if pending_change is None
                else {
                    "operation": pending_change.operation,
                    "beforeVersion": pending_change.before_version,
                    "beforeContentHash": pending_change.before_content_hash,
                    "afterVersion": pending_change.after_version,
                    "afterContentHash": pending_change.after_content_hash,
                    "experienceEffect": pending_change.experience_effect,
                }
            ),
        }


@dataclass(frozen=True)
class ExperienceResolution:
    profile: EffectiveProfileResult
    state_exists: bool
    experience_version: ExperienceVersion | None
    cadence_available: bool
    warnings: tuple[ExperienceWarning, ...]


@dataclass(frozen=True)
class ExperienceMutationResult:
    profile_version: ProfileVersion
    experience: ExperienceState | None
    changed: bool
    committed: bool
    experience_committed: bool
    replayed: bool = False
    onboarding_offer: str = "none"
    proposal_field: str | None = None
    proposal: PreferenceProposal | None = None
    reviewed_version: ProfileVersion | None = None
    warnings: tuple[ExperienceWarning, ...] = ()
    backup_path: Path | None = None


@dataclass(frozen=True)
class CompositeMutationResult:
    profile: StoredProfile
    effective_profile: EffectiveProfile
    experience_version: ExperienceVersion | None
    changed: bool
    committed: bool
    profile_changed: bool
    experience_committed: bool
    warnings: tuple[ExperienceWarning, ...] = ()
    backup_path: Path | None = None


@dataclass(frozen=True)
class ProfilePresentation:
    persona_id: str
    persona_name: str
    labels: tuple[tuple[str, str, str], ...]
    summary: str
    example: str
    example_label: str = "Example response - no action performed"


class UserProfileError(Exception):
    status = "invalid_arguments"
    exit_code = 2

    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        content_hash: str | None = None,
        committed: bool = False,
        version: ProfileVersion | None = None,
        profile_changed: bool | None = None,
        experience_committed: bool | None = None,
        reconciliation_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.content_hash = content_hash
        self.committed = committed
        self.version = version
        self.profile_changed = profile_changed
        self.experience_committed = experience_committed
        self.reconciliation_required = reconciliation_required


class UserProfileArgumentError(UserProfileError):
    pass


class UserProfileNotFoundError(UserProfileError):
    status = "profile_not_found"
    exit_code = 3


class UserProfileValidationError(UserProfileError):
    status = "invalid_profile"
    exit_code = 3


class UserProfileSchemaVersionError(UserProfileError):
    status = "unsupported_schema"
    exit_code = 3


class UserProfileConflictError(UserProfileError):
    status = "profile_conflict"
    exit_code = 4

    def __init__(
        self,
        message: str,
        *,
        expected_version: ProfileVersion | None = None,
        actual_version: ProfileVersion | None = None,
        expected_content_hash: str | None = None,
        actual_content_hash: str | None = None,
        path: Path | None = None,
    ) -> None:
        super().__init__(message, path=path)
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.expected_content_hash = expected_content_hash
        self.actual_content_hash = actual_content_hash


class UserProfileReadError(UserProfileError):
    status = "read_failed"
    exit_code = 5


class UserProfilePersistenceError(UserProfileError):
    status = "persistence_failed"
    exit_code = 5


class UserProfileProposalError(UserProfileError):
    exit_code = 3

    def __init__(self, message: str, *, status: str) -> None:
        super().__init__(message)
        self.status = status


class UserProfileLockTimeoutError(UserProfileError):
    status = "lock_timeout"
    exit_code = 4


class UserProfileConfirmationError(UserProfileError):
    status = "confirmation_required"
    exit_code = 2


class UserProfileExperienceValidationError(UserProfileError):
    status = "invalid_experience_state"
    exit_code = 3


class UserProfileExperienceSchemaVersionError(UserProfileExperienceValidationError):
    status = "unsupported_experience_schema"


class UserProfileExperienceReconciliationError(UserProfileError):
    status = "experience_reconciliation_required"
    exit_code = 3


class UserProfileExperienceConflictError(UserProfileError):
    status = "experience_conflict"
    exit_code = 4

    def __init__(
        self,
        message: str,
        *,
        expected_version: ExperienceVersion | None = None,
        actual_version: ExperienceVersion | None = None,
        expected_content_hash: str | None = None,
        actual_content_hash: str | None = None,
        resource: str = "experience",
        path: Path | None = None,
    ) -> None:
        super().__init__(message, path=path)
        self.expected_experience_version = expected_version
        self.actual_experience_version = actual_version
        self.expected_content_hash = expected_content_hash
        self.actual_content_hash = actual_content_hash
        self.resource = resource


class UserProfileRequestExpiredError(UserProfileError):
    status = "request_expired"
    exit_code = 3


class UserProfileOnboardingNotRequiredError(UserProfileError):
    status = "onboarding_not_required"
    exit_code = 3


DEFAULT_VALUES: dict[str, Any] = {
    "responseFormat": ResponseFormat.AUTO,
    "detailLevel": DetailLevel.BALANCED,
    "toneOfVoice": ToneOfVoice.FRIENDLY_PROFESSIONAL,
    "confirmationFrequency": ConfirmationFrequency.STANDARD,
    "maximumResponseLength": None,
    "proactiveSuggestions": ProactiveSuggestions.CONTEXTUAL,
}


def _json_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _later_timestamp(previous: str | None, candidate: str) -> str:
    if previous is None:
        return candidate
    previous_dt = datetime.fromisoformat(previous[:-1] + "+00:00")
    candidate_dt = datetime.fromisoformat(candidate[:-1] + "+00:00")
    if candidate_dt <= previous_dt:
        candidate_dt = previous_dt + timedelta(microseconds=1)
    return candidate_dt.isoformat().replace("+00:00", "Z")


def _content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise UserProfileValidationError(
            f"Object '{field}' does not match the documented fields."
        )


def _require_object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise UserProfileValidationError(
            f"Field '{field}' must be a JSON object."
        )
    return value


def _require_integer(
    value: object,
    field: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise UserProfileValidationError(f"Field '{field}' must be an integer.")
    if minimum is not None and value < minimum:
        raise UserProfileValidationError(f"Field '{field}' is below its minimum.")
    if maximum is not None and value > maximum:
        raise UserProfileValidationError(f"Field '{field}' exceeds its maximum.")
    return value


def _require_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise UserProfileValidationError(
            f"Field '{field}' must be a UTC timestamp with a Z suffix."
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise UserProfileValidationError(
            f"Field '{field}' must be a valid UTC timestamp."
        ) from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise UserProfileValidationError(
            f"Field '{field}' must be a UTC timestamp."
        )
    return value


def _require_enum(value: object, enum_type: type[Enum], field: str) -> Enum:
    if not isinstance(value, str):
        raise UserProfileValidationError(
            f"Field '{field}' must be a documented string value."
        )
    try:
        return enum_type(value)
    except ValueError as exc:
        raise UserProfileValidationError(
            f"Field '{field}' has an unsupported value."
        ) from exc


def _validate_generation(value: object) -> str:
    if not isinstance(value, str):
        raise UserProfileValidationError(
            "Field 'generation' must be a UUID v4 string."
        )
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise UserProfileValidationError(
            "Field 'generation' must be a UUID v4 string."
        ) from exc
    if parsed.version != 4 or str(parsed) != value:
        raise UserProfileValidationError(
            "Field 'generation' must be a canonical UUID v4 string."
        )
    return value


def _validate_preference_value(field: str, value: object) -> tuple[Any, str | None]:
    if field not in PREFERENCE_FIELDS:
        raise UserProfileValidationError(
            "The preference name is not supported."
        )
    if field == "maximumResponseLength":
        item = _require_object(value, field)
        _require_exact_keys(item, {"value", "unit"}, field)
        if item["unit"] != "words":
            raise UserProfileValidationError(
                "Field 'maximumResponseLength.unit' has an unsupported value."
            )
        length = item["value"]
        if length is not None:
            length = _require_integer(
                length,
                "maximumResponseLength.value",
                minimum=50,
                maximum=5000,
            )
        return length, "words"
    return _require_enum(value, PREFERENCE_ENUMS[field], field), None


def _validate_stored_preference(
    field: str,
    value: object,
) -> StoredPreference:
    item = _require_object(value, f"preferences.{field}")
    expected = {"value", "source", "updatedAt"}
    if field == "maximumResponseLength":
        expected.add("unit")
    _require_exact_keys(item, expected, f"preferences.{field}")
    input_value: object = item["value"]
    if field == "maximumResponseLength":
        input_value = {"value": item["value"], "unit": item["unit"]}
    parsed_value, unit = _validate_preference_value(field, input_value)
    source = _require_enum(
        item["source"],
        PreferenceSource,
        f"preferences.{field}.source",
    )
    updated_at = item["updatedAt"]
    if source is PreferenceSource.DEFAULT:
        if updated_at is not None:
            raise UserProfileValidationError(
                f"Field 'preferences.{field}.updatedAt' must be null for a default."
            )
    else:
        updated_at = _require_timestamp(
            updated_at,
            f"preferences.{field}.updatedAt",
        )
    return StoredPreference(
        value=parsed_value,
        unit=unit,
        source=source,
        updated_at=updated_at,
    )


def _validate_proposal(field: str, value: object) -> PreferenceProposal:
    item = _require_object(value, f"proposals.{field}")
    _require_exact_keys(
        item,
        {
            "proposedValue",
            "observationCount",
            "confidence",
            "status",
            "createdAt",
            "updatedAt",
        },
        f"proposals.{field}",
    )
    proposed_value, unit = _validate_preference_value(
        field, item["proposedValue"]
    )
    observation_count = _require_integer(
        item["observationCount"],
        f"proposals.{field}.observationCount",
        minimum=1,
    )
    confidence = item["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or confidence < 0.0
        or confidence > 1.0
    ):
        raise UserProfileValidationError(
            f"Field 'proposals.{field}.confidence' must be a finite number "
            "from 0.0 through 1.0."
        )
    status = _require_enum(
        item["status"],
        ProposalStatus,
        f"proposals.{field}.status",
    )
    created_at = _require_timestamp(
        item["createdAt"], f"proposals.{field}.createdAt"
    )
    updated_at = _require_timestamp(
        item["updatedAt"], f"proposals.{field}.updatedAt"
    )
    created = datetime.fromisoformat(created_at[:-1] + "+00:00")
    updated = datetime.fromisoformat(updated_at[:-1] + "+00:00")
    if updated < created:
        raise UserProfileValidationError(
            f"Field 'proposals.{field}.updatedAt' precedes createdAt."
        )
    return PreferenceProposal(
        proposed_value=proposed_value,
        unit=unit,
        observation_count=observation_count,
        confidence=float(confidence),
        status=status,
        created_at=created_at,
        updated_at=updated_at,
    )


def default_effective_profile() -> EffectiveProfile:
    return EffectiveProfile(
        response_format=DEFAULT_VALUES["responseFormat"],
        detail_level=DEFAULT_VALUES["detailLevel"],
        tone_of_voice=DEFAULT_VALUES["toneOfVoice"],
        confirmation_frequency=DEFAULT_VALUES["confirmationFrequency"],
        maximum_response_length=DEFAULT_VALUES["maximumResponseLength"],
        proactive_suggestions=DEFAULT_VALUES["proactiveSuggestions"],
    )


def default_profile(*, generation: str, revision: int) -> StoredProfile:
    generation = _validate_generation(generation)
    revision = _require_integer(revision, "revision", minimum=1)
    preferences = {
        field: StoredPreference(
            value=value,
            unit="words" if field == "maximumResponseLength" else None,
            source=PreferenceSource.DEFAULT,
            updated_at=None,
        )
        for field, value in DEFAULT_VALUES.items()
    }
    return StoredProfile(
        schema_version=SCHEMA_VERSION,
        generation=generation,
        revision=revision,
        onboarding=OnboardingState(OnboardingStatus.NOT_STARTED, None),
        preferences=preferences,
        proposals={},
    )


def validate_profile(document: object) -> StoredProfile:
    root = _require_object(document, "profile")
    if "schemaVersion" not in root:
        raise UserProfileValidationError(
            "Required field 'schemaVersion' is missing."
        )
    schema_version = _require_integer(root["schemaVersion"], "schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise UserProfileSchemaVersionError(
            "The profile schema version is not supported."
        )
    _require_exact_keys(
        root,
        {
            "schemaVersion",
            "generation",
            "revision",
            "onboarding",
            "preferences",
            "proposals",
        },
        "profile",
    )
    generation = _validate_generation(root["generation"])
    revision = _require_integer(root["revision"], "revision", minimum=1)

    onboarding_document = _require_object(root["onboarding"], "onboarding")
    _require_exact_keys(
        onboarding_document, {"status", "updatedAt"}, "onboarding"
    )
    onboarding_status = _require_enum(
        onboarding_document["status"],
        OnboardingStatus,
        "onboarding.status",
    )
    onboarding_updated_at = onboarding_document["updatedAt"]
    if onboarding_updated_at is not None:
        onboarding_updated_at = _require_timestamp(
            onboarding_updated_at, "onboarding.updatedAt"
        )
    if onboarding_status is not OnboardingStatus.NOT_STARTED and onboarding_updated_at is None:
        raise UserProfileValidationError(
            "Field 'onboarding.updatedAt' is required after a status change."
        )

    preference_documents = _require_object(
        root["preferences"], "preferences"
    )
    _require_exact_keys(
        preference_documents, set(PREFERENCE_FIELDS), "preferences"
    )
    preferences = {
        field: _validate_stored_preference(
            field, preference_documents[field]
        )
        for field in PREFERENCE_FIELDS
    }

    proposal_documents = _require_object(root["proposals"], "proposals")
    unknown_proposals = set(proposal_documents) - set(PREFERENCE_FIELDS)
    if unknown_proposals:
        raise UserProfileValidationError(
            "The profile contains an unsupported proposal name."
        )
    proposals = {
        field: _validate_proposal(field, proposal_documents[field])
        for field in PREFERENCE_FIELDS
        if field in proposal_documents
    }

    return StoredProfile(
        schema_version=schema_version,
        generation=generation,
        revision=revision,
        onboarding=OnboardingState(
            onboarding_status, onboarding_updated_at
        ),
        preferences=preferences,
        proposals=proposals,
    )


def migrate_profile(document: object) -> StoredProfile:
    root = _require_object(document, "profile")
    if "schemaVersion" not in root:
        raise UserProfileValidationError(
            "Required field 'schemaVersion' is missing."
        )
    version = root["schemaVersion"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise UserProfileValidationError(
            "Field 'schemaVersion' must be an integer."
        )
    if version != SCHEMA_VERSION:
        raise UserProfileSchemaVersionError(
            "The profile schema version is not supported."
        )
    return validate_profile(root)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise UserProfileValidationError(
                "The profile contains a duplicate JSON field."
            )
        result[key] = value
    return result


def _reject_non_finite(_value: str) -> NoReturn:
    raise UserProfileValidationError(
        "The profile contains a non-finite JSON number."
    )


def _parse_json_bytes(raw: bytes) -> object:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UserProfileValidationError(
            "The profile is not valid UTF-8 JSON."
        ) from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except UserProfileValidationError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise UserProfileValidationError(
            "The profile contains malformed JSON."
        ) from exc


_EXPERIENCE_FIELDS = {
    "schemaVersion",
    "generation",
    "revision",
    "profileGeneration",
    "eligibleRunCount",
    "onboardingPrompt",
    "proposalPrompts",
    "requestReceipts",
    "pendingProfileChange",
}
_EXPERIENCE_OPERATIONS = {
    "initialize",
    "onboarding-complete",
    "profile-save",
    "onboarding-defer",
    "reset",
    "recover",
}


def _experience_timestamp(
    value: object,
    field: str,
) -> str:
    try:
        return _require_timestamp(value, field)
    except UserProfileValidationError as exc:
        raise UserProfileExperienceValidationError(str(exc)) from exc


def _experience_version(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise UserProfileExperienceValidationError(
            f"Field '{field}' must be a version token."
        )
    try:
        parsed = parse_profile_version(value)
    except UserProfileArgumentError as exc:
        raise UserProfileExperienceValidationError(
            f"Field '{field}' has an invalid version token."
        ) from exc
    return parsed.token()


def _valid_content_hash(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise UserProfileExperienceValidationError(
            f"Field '{field}' must be a lowercase SHA-256 digest."
        )
    return value


def validate_experience_state(document: object) -> ExperienceState:
    try:
        root = _require_object(document, "experience")
        if "schemaVersion" not in root:
            raise UserProfileExperienceValidationError(
                "Required field 'schemaVersion' is missing."
            )
        schema_version = _require_integer(
            root["schemaVersion"], "schemaVersion"
        )
        if schema_version != 1:
            raise UserProfileExperienceSchemaVersionError(
                "The experience schema version is not supported."
            )
        _require_exact_keys(root, _EXPERIENCE_FIELDS, "experience")
        generation = _validate_generation(root["generation"])
        revision = _require_integer(root["revision"], "revision", minimum=1)
        profile_generation_value = root["profileGeneration"]
        profile_generation = (
            None
            if profile_generation_value is None
            else _validate_generation(profile_generation_value)
        )
        eligible_run_count = _require_integer(
            root["eligibleRunCount"], "eligibleRunCount", minimum=0
        )

        onboarding_document = _require_object(
            root["onboardingPrompt"], "onboardingPrompt"
        )
        _require_exact_keys(
            onboarding_document,
            {"promptCount", "lastPromptRun", "suppressed", "lastPromptedAt"},
            "onboardingPrompt",
        )
        onboarding_count = _require_integer(
            onboarding_document["promptCount"],
            "onboardingPrompt.promptCount",
            minimum=0,
            maximum=2,
        )
        onboarding_last_run = onboarding_document["lastPromptRun"]
        onboarding_last_at = onboarding_document["lastPromptedAt"]
        if onboarding_count == 0:
            if onboarding_last_run is not None or onboarding_last_at is not None:
                raise UserProfileExperienceValidationError(
                    "An unclaimed onboarding prompt must have null claim markers."
                )
        else:
            onboarding_last_run = _require_integer(
                onboarding_last_run,
                "onboardingPrompt.lastPromptRun",
                minimum=1,
                maximum=eligible_run_count,
            )
            onboarding_last_at = _experience_timestamp(
                onboarding_last_at, "onboardingPrompt.lastPromptedAt"
            )
        onboarding_suppressed = onboarding_document["suppressed"]
        if not isinstance(onboarding_suppressed, bool):
            raise UserProfileExperienceValidationError(
                "Field 'onboardingPrompt.suppressed' must be a boolean."
            )
        onboarding_prompt = OnboardingPromptState(
            prompt_count=onboarding_count,
            last_prompt_run=onboarding_last_run,
            suppressed=onboarding_suppressed,
            last_prompted_at=onboarding_last_at,
        )

        proposal_documents = _require_object(
            root["proposalPrompts"], "proposalPrompts"
        )
        if set(proposal_documents) - set(PREFERENCE_FIELDS):
            raise UserProfileExperienceValidationError(
                "The experience state contains an unsupported preference."
            )
        proposal_prompts: dict[str, ProposalPromptState] = {}
        for field, value in proposal_documents.items():
            item = _require_object(value, f"proposalPrompts.{field}")
            _require_exact_keys(
                item,
                {
                    "proposalCreatedAt",
                    "promptCount",
                    "lastPromptRun",
                    "snoozedAtRun",
                    "suppressed",
                    "lastPromptedAt",
                },
                f"proposalPrompts.{field}",
            )
            count = _require_integer(
                item["promptCount"],
                f"proposalPrompts.{field}.promptCount",
                minimum=0,
                maximum=2,
            )
            last_run = item["lastPromptRun"]
            last_at = item["lastPromptedAt"]
            if count == 0:
                if last_run is not None or last_at is not None:
                    raise UserProfileExperienceValidationError(
                        "An unclaimed proposal prompt must have null claim markers."
                    )
            else:
                last_run = _require_integer(
                    last_run,
                    f"proposalPrompts.{field}.lastPromptRun",
                    minimum=1,
                    maximum=eligible_run_count,
                )
                last_at = _experience_timestamp(
                    last_at, f"proposalPrompts.{field}.lastPromptedAt"
                )
            snoozed_run = item["snoozedAtRun"]
            if snoozed_run is not None:
                snoozed_run = _require_integer(
                    snoozed_run,
                    f"proposalPrompts.{field}.snoozedAtRun",
                    minimum=0,
                    maximum=eligible_run_count,
                )
            suppressed = item["suppressed"]
            if not isinstance(suppressed, bool):
                raise UserProfileExperienceValidationError(
                    f"Field 'proposalPrompts.{field}.suppressed' must be a boolean."
                )
            proposal_prompts[field] = ProposalPromptState(
                proposal_created_at=_experience_timestamp(
                    item["proposalCreatedAt"],
                    f"proposalPrompts.{field}.proposalCreatedAt",
                ),
                prompt_count=count,
                last_prompt_run=last_run,
                snoozed_at_run=snoozed_run,
                suppressed=suppressed,
                last_prompted_at=last_at,
            )

        receipt_documents = root["requestReceipts"]
        if not isinstance(receipt_documents, list):
            raise UserProfileExperienceValidationError(
                "Field 'requestReceipts' must be an array."
            )
        if len(receipt_documents) > 64:
            raise UserProfileExperienceValidationError(
                "Experience state contains too many request receipts."
            )
        receipts: list[RequestReceipt] = []
        request_ids: set[str] = set()
        previous_run = 0
        for index, value in enumerate(receipt_documents):
            item = _require_object(value, f"requestReceipts[{index}]")
            _require_exact_keys(
                item,
                {
                    "requestId",
                    "beginProfileVersion",
                    "runNumber",
                    "onboardingOffer",
                    "finished",
                    "proposalField",
                },
                f"requestReceipts[{index}]",
            )
            request_id = _validate_generation(item["requestId"])
            if request_id in request_ids:
                raise UserProfileExperienceValidationError(
                    "Experience request receipts must have unique IDs."
                )
            request_ids.add(request_id)
            run_number = _require_integer(
                item["runNumber"],
                f"requestReceipts[{index}].runNumber",
                minimum=1,
                maximum=eligible_run_count,
            )
            if run_number <= previous_run:
                raise UserProfileExperienceValidationError(
                    "Experience request receipts must be in run order."
                )
            previous_run = run_number
            begin_version = _experience_version(
                item["beginProfileVersion"],
                f"requestReceipts[{index}].beginProfileVersion",
            )
            offer = item["onboardingOffer"]
            if not isinstance(offer, str) or offer not in {
                "none",
                "initial",
                "deferred_reoffer",
            }:
                raise UserProfileExperienceValidationError(
                    "An experience receipt has an unsupported onboarding offer."
                )
            finished = item["finished"]
            if not isinstance(finished, bool):
                raise UserProfileExperienceValidationError(
                    "Experience receipt 'finished' must be a boolean."
                )
            proposal_field = item["proposalField"]
            if proposal_field is not None and (
                not isinstance(proposal_field, str)
                or proposal_field not in PREFERENCE_FIELDS
            ):
                raise UserProfileExperienceValidationError(
                    "An experience receipt has an unsupported proposal field."
                )
            receipts.append(
                RequestReceipt(
                    request_id=request_id,
                    begin_profile_version=begin_version,
                    run_number=run_number,
                    onboarding_offer=offer,
                    finished=finished,
                    proposal_field=proposal_field,
                )
            )

        pending_document = root["pendingProfileChange"]
        pending_change = None
        if pending_document is not None:
            item = _require_object(
                pending_document, "pendingProfileChange"
            )
            _require_exact_keys(
                item,
                {
                    "operation",
                    "beforeVersion",
                    "beforeContentHash",
                    "afterVersion",
                    "afterContentHash",
                    "experienceEffect",
                },
                "pendingProfileChange",
            )
            operation = item["operation"]
            if (
                not isinstance(operation, str)
                or operation not in _EXPERIENCE_OPERATIONS
            ):
                raise UserProfileExperienceValidationError(
                    "The pending profile operation is unsupported."
                )
            before_version = item["beforeVersion"]
            before_hash = item["beforeContentHash"]
            if before_version is None:
                if before_hash is None:
                    raise UserProfileExperienceValidationError(
                        "A damaged profile intent requires its content hash."
                    )
            else:
                before_version = _experience_version(
                    before_version, "pendingProfileChange.beforeVersion"
                )
                if before_hash is None:
                    if before_version != "none:0":
                        raise UserProfileExperienceValidationError(
                            "A persisted profile intent requires its content hash."
                        )
                else:
                    if before_version == "none:0":
                        raise UserProfileExperienceValidationError(
                            "A missing profile intent cannot contain a content hash."
                        )
                    before_hash = _valid_content_hash(
                        before_hash,
                        "pendingProfileChange.beforeContentHash",
                    )
            after_version = _experience_version(
                item["afterVersion"], "pendingProfileChange.afterVersion"
            )
            if after_version == "none:0":
                raise UserProfileExperienceValidationError(
                    "A pending profile change requires a persisted after version."
                )
            after_hash = _valid_content_hash(
                item["afterContentHash"],
                "pendingProfileChange.afterContentHash",
            )
            effect = item["experienceEffect"]
            if not isinstance(effect, str) or effect not in {"bind", "reset"}:
                raise UserProfileExperienceValidationError(
                    "The pending experience effect is unsupported."
                )
            pending_change = PendingProfileChange(
                operation=operation,
                before_version=before_version,
                before_content_hash=before_hash,
                after_version=after_version,
                after_content_hash=after_hash,
                experience_effect=effect,
            )

        return ExperienceState(
            schema_version=1,
            generation=generation,
            revision=revision,
            profile_generation=profile_generation,
            eligible_run_count=eligible_run_count,
            onboarding_prompt=onboarding_prompt,
            proposal_prompts=proposal_prompts,
            request_receipts=tuple(receipts),
            pending_profile_change=pending_change,
        )
    except UserProfileExperienceValidationError:
        raise
    except UserProfileValidationError as exc:
        raise UserProfileExperienceValidationError(str(exc)) from exc


def load_experience_state(path: Path) -> ExperienceState:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise UserProfileNotFoundError(
            "The experience state does not exist.", path=path
        ) from exc
    except OSError as exc:
        raise UserProfileReadError(
            "The experience state could not be read.", path=path
        ) from exc
    try:
        document = _parse_json_bytes(raw)
        return validate_experience_state(document)
    except UserProfileValidationError as exc:
        invalid = UserProfileExperienceValidationError(
            "The experience state is invalid."
        )
        invalid.path = path
        invalid.content_hash = _content_hash(raw)
        raise invalid from exc
    except UserProfileExperienceValidationError as exc:
        exc.path = path
        exc.content_hash = _content_hash(raw)
        raise


def _empty_experience_state(
    *,
    generation: str | None = None,
    revision: int = 0,
    profile_generation: str | None = None,
    eligible_run_count: int = 0,
    onboarding_prompt: OnboardingPromptState | None = None,
    proposal_prompts: Mapping[str, ProposalPromptState] | None = None,
    request_receipts: tuple[RequestReceipt, ...] = (),
    pending_profile_change: PendingProfileChange | None = None,
) -> ExperienceState:
    return ExperienceState(
        schema_version=1,
        generation=generation,
        revision=revision,
        profile_generation=profile_generation,
        eligible_run_count=eligible_run_count,
        onboarding_prompt=(
            OnboardingPromptState(0, None, False, None)
            if onboarding_prompt is None
            else onboarding_prompt
        ),
        proposal_prompts={} if proposal_prompts is None else proposal_prompts,
        request_receipts=request_receipts,
        pending_profile_change=pending_profile_change,
    )


def _serialize_experience(state: ExperienceState) -> bytes:
    validated = validate_experience_state(state.to_document())
    return (
        json.dumps(
            validated.to_document(),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _persist_experience(path: Path, state: ExperienceState) -> None:
    _atomic_write_bytes(path, _serialize_experience(state))


def _read_raw(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise UserProfileNotFoundError(
            "The user profile does not exist.", path=path
        ) from exc
    except OSError as exc:
        raise UserProfileReadError(
            "The user profile could not be read.", path=path
        ) from exc


def _profile_from_raw(raw: bytes, path: Path) -> StoredProfile:
    digest = _content_hash(raw)
    try:
        return migrate_profile(_parse_json_bytes(raw))
    except (UserProfileValidationError, UserProfileSchemaVersionError) as exc:
        exc.path = path
        exc.content_hash = digest
        raise


def load_profile(path: Path) -> StoredProfile:
    path = Path(path)
    return _profile_from_raw(_read_raw(path), path)


def _resolve_effective(profile: StoredProfile) -> EffectiveProfile:
    values: dict[str, Any] = {}
    for field in PREFERENCE_FIELDS:
        preference = profile.preferences[field]
        values[field] = (
            DEFAULT_VALUES[field]
            if preference.source is PreferenceSource.DEFAULT
            else preference.value
        )
    return EffectiveProfile(
        response_format=values["responseFormat"],
        detail_level=values["detailLevel"],
        tone_of_voice=values["toneOfVoice"],
        confirmation_frequency=values["confirmationFrequency"],
        maximum_response_length=values["maximumResponseLength"],
        proactive_suggestions=values["proactiveSuggestions"],
    )


def resolve_profile(path: Path) -> EffectiveProfileResult:
    try:
        profile = load_profile(path)
    except UserProfileNotFoundError:
        return EffectiveProfileResult(
            profile_exists=False,
            version=ProfileVersion(None, 0),
            onboarding_status=OnboardingStatus.NOT_STARTED,
            effective_profile=default_effective_profile(),
            pending_proposals=(),
        )
    pending = tuple(
        (field, profile.proposals[field])
        for field in PREFERENCE_FIELDS
        if field in profile.proposals
        and profile.proposals[field].status is ProposalStatus.PENDING
    )
    return EffectiveProfileResult(
        profile_exists=True,
        version=profile.version,
        onboarding_status=profile.onboarding.status,
        effective_profile=_resolve_effective(profile),
        pending_proposals=pending,
        profile=profile,
    )


def _validate_profile_experience_paths(
    profile_path: Path,
    experience_path: Path,
) -> tuple[Path, Path]:
    profile_path = Path(profile_path)
    experience_path = Path(experience_path)
    if profile_path.parent.resolve() != experience_path.parent.resolve():
        raise UserProfileArgumentError(
            "Profile and experience files must share one lock directory."
        )
    return profile_path, experience_path


def _experience_path_for_profile(profile_path: Path) -> Path:
    return Path(profile_path).parent / "user-profile-experience.json"


def _read_optional_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise UserProfileReadError(
            "A local profile document could not be read.", path=path
        ) from exc


def _effective_result_from_raw(
    raw: bytes | None,
    path: Path,
) -> EffectiveProfileResult:
    if raw is None:
        return EffectiveProfileResult(
            profile_exists=False,
            version=ProfileVersion(None, 0),
            onboarding_status=OnboardingStatus.NOT_STARTED,
            effective_profile=default_effective_profile(),
            pending_proposals=(),
        )
    profile = _profile_from_raw(raw, path)
    pending = tuple(
        (field, profile.proposals[field])
        for field in PREFERENCE_FIELDS
        if field in profile.proposals
        and profile.proposals[field].status is ProposalStatus.PENDING
    )
    return EffectiveProfileResult(
        profile_exists=True,
        version=profile.version,
        onboarding_status=profile.onboarding.status,
        effective_profile=_resolve_effective(profile),
        pending_proposals=pending,
        profile=profile,
    )


def _experience_warning(
    status: str,
    message: str,
    path: Path,
    raw: bytes | None = None,
) -> ExperienceWarning:
    return ExperienceWarning(
        status=status,
        error=message,
        path=_display_path(path),
        content_hash=None if raw is None else _content_hash(raw),
    )


def _read_experience_for_resolution(
    path: Path,
) -> tuple[ExperienceState | None, ExperienceVersion | None, bytes | None, ExperienceWarning | None]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, ExperienceVersion(None, 0), None, None
    except OSError:
        return (
            None,
            None,
            None,
            _experience_warning(
                "read_failed",
                "The experience state could not be read.",
                path,
            ),
        )
    try:
        state = validate_experience_state(_parse_json_bytes(raw))
    except UserProfileExperienceSchemaVersionError:
        return (
            None,
            None,
            raw,
            _experience_warning(
                "unsupported_experience_schema",
                "The experience schema version is not supported.",
                path,
                raw,
            ),
        )
    except (UserProfileExperienceValidationError, UserProfileValidationError):
        return (
            None,
            None,
            raw,
            _experience_warning(
                "invalid_experience_state",
                "The experience state is invalid.",
                path,
                raw,
            ),
        )
    return state, state.version, raw, None


def _resolve_experience_locked(
    profile_path: Path,
    experience_path: Path,
) -> ExperienceResolution:
    profile_raw = _read_optional_bytes(profile_path)
    profile_result = _effective_result_from_raw(profile_raw, profile_path)
    state, version, raw, warning = _read_experience_for_resolution(
        experience_path
    )
    warnings: list[ExperienceWarning] = []
    cadence_available = True
    if warning is not None:
        warnings.append(warning)
        cadence_available = False
    if state is not None:
        if state.pending_profile_change is not None:
            warnings.append(
                _experience_warning(
                    "experience_reconciliation_required",
                    "A profile transition requires reconciliation.",
                    experience_path,
                    raw,
                )
            )
            cadence_available = False
        elif state.profile_generation != (
            None if profile_result.profile is None else profile_result.profile.generation
        ):
            warnings.append(
                _experience_warning(
                    "profile_generation_mismatch",
                    "Reminder history belongs to a different profile lifetime.",
                    experience_path,
                    raw,
                )
            )
            cadence_available = False
    return ExperienceResolution(
        profile=profile_result,
        state_exists=raw is not None or warning is not None,
        experience_version=version,
        cadence_available=cadence_available,
        warnings=tuple(warnings),
    )


def resolve_experience(
    profile_path: Path,
    experience_path: Path,
) -> ExperienceResolution:
    profile_path, experience_path = _validate_profile_experience_paths(
        profile_path, experience_path
    )
    if not profile_path.parent.exists():
        return ExperienceResolution(
            profile=EffectiveProfileResult(
                profile_exists=False,
                version=ProfileVersion(None, 0),
                onboarding_status=OnboardingStatus.NOT_STARTED,
                effective_profile=default_effective_profile(),
                pending_proposals=(),
            ),
            state_exists=False,
            experience_version=ExperienceVersion(None, 0),
            cadence_available=True,
            warnings=(),
        )
    with _transaction_lock(profile_path):
        return _resolve_experience_locked(profile_path, experience_path)


def _lock_path(path: Path) -> Path:
    return path.parent / "user-profile.lock"


@contextmanager
def _transaction_lock(
    path: Path,
    *,
    timeout: float = LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    lock_path = _lock_path(path)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        stream = lock_path.open("a+b")
    except OSError as exc:
        raise UserProfilePersistenceError(
            "The user profile lock could not be opened.", path=lock_path
        ) from exc
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
    except OSError as exc:
        stream.close()
        raise UserProfilePersistenceError(
            "The user profile lock could not be initialized.", path=lock_path
        ) from exc

    deadline = time.monotonic() + timeout
    locked = False
    try:
        while not locked:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(
                        stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                    )
                locked = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise UserProfileLockTimeoutError(
                        "The user profile transaction lock timed out.",
                        path=lock_path,
                    )
                time.sleep(LOCK_RETRY_SECONDS)
        yield
    finally:
        if locked:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        stream.close()


def _fsync(stream: Any) -> None:
    try:
        os.fsync(stream.fileno())
    except OSError as exc:
        unsupported = {
            errno.EINVAL,
            getattr(errno, "ENOTSUP", errno.EINVAL),
            getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        }
        if exc.errno not in unsupported:
            raise


def _atomic_write_bytes(path: Path, raw: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
    except OSError as exc:
        raise UserProfilePersistenceError(
            "The user profile temporary file could not be created.", path=path
        ) from exc
    temporary_path = Path(temporary_name)
    try:
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                _fsync(stream)
            os.replace(temporary_path, path)
        except OSError as exc:
            raise UserProfilePersistenceError(
                "The user profile could not be persisted.", path=path
            ) from exc
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _serialize_profile(profile: StoredProfile) -> bytes:
    return (
        json.dumps(
            profile.to_document(),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _persist_profile(path: Path, profile: StoredProfile) -> None:
    validated = validate_profile(profile.to_document())
    _atomic_write_bytes(path, _serialize_profile(validated))


def _experience_state_for_writer(
    path: Path,
    *,
    allow_unavailable: bool,
) -> tuple[ExperienceState | None, bytes | None, ExperienceWarning | None]:
    try:
        raw = _read_optional_bytes(path)
    except UserProfileReadError:
        if not allow_unavailable:
            raise
        return (
            None,
            None,
            _experience_warning(
                "read_failed",
                "The experience state could not be read.",
                path,
            ),
        )
    if raw is None:
        return None, None, None
    try:
        state = validate_experience_state(_parse_json_bytes(raw))
    except UserProfileExperienceSchemaVersionError:
        if not allow_unavailable:
            raise
        return (
            None,
            raw,
            _experience_warning(
                "unsupported_experience_schema",
                "The experience schema version is not supported.",
                path,
                raw,
            ),
        )
    except (UserProfileExperienceValidationError, UserProfileValidationError):
        if not allow_unavailable:
            raise UserProfileExperienceValidationError(
                "The experience state is invalid.",
                path=path,
                content_hash=_content_hash(raw),
            )
        return (
            None,
            raw,
            _experience_warning(
                "invalid_experience_state",
                "The experience state is invalid.",
                path,
                raw,
            ),
        )
    return state, raw, None


def _profile_version_from_raw(
    raw: bytes | None,
    path: Path,
) -> ProfileVersion | None:
    if raw is None:
        return ProfileVersion(None, 0)
    try:
        return _profile_from_raw(raw, path).version
    except (UserProfileValidationError, UserProfileSchemaVersionError):
        return None


def _pending_change_matches(
    raw: bytes | None,
    path: Path,
    *,
    expected_version: str | None,
    expected_hash: str | None,
) -> bool:
    actual_hash = None if raw is None else _content_hash(raw)
    if actual_hash != expected_hash:
        return False
    actual_version = _profile_version_from_raw(raw, path)
    if expected_version is None:
        return actual_version is None and raw is not None
    if actual_version is None:
        return False
    return actual_version.token() == expected_version


def _finalize_profile_change(
    state: ExperienceState,
    profile: StoredProfile,
    *,
    effect: str,
) -> ExperienceState:
    revision = state.revision + 1
    if effect == "bind":
        return replace(
            state,
            revision=revision,
            profile_generation=profile.generation,
            pending_profile_change=None,
        )
    return _empty_experience_state(
        generation=str(uuid.uuid4()),
        revision=revision,
        profile_generation=profile.generation,
    )


def _reconcile_pending_change_locked(
    profile_path: Path,
    experience_path: Path,
    state: ExperienceState,
) -> tuple[ExperienceState, bool]:
    pending = state.pending_profile_change
    if pending is None:
        return state, False
    raw = _read_optional_bytes(profile_path)
    if _pending_change_matches(
        raw,
        profile_path,
        expected_version=pending.after_version,
        expected_hash=pending.after_content_hash,
    ):
        if raw is None:
            raise UserProfileExperienceReconciliationError(
                "The committed profile image is unavailable.",
                path=experience_path,
            )
        profile = _profile_from_raw(raw, profile_path)
        finalized = _finalize_profile_change(
            state, profile, effect=pending.experience_effect
        )
        _persist_experience(experience_path, finalized)
        return finalized, True
    if _pending_change_matches(
        raw,
        profile_path,
        expected_version=pending.before_version,
        expected_hash=pending.before_content_hash,
    ):
        cleared = replace(
            state,
            revision=state.revision + 1,
            pending_profile_change=None,
        )
        _persist_experience(experience_path, cleared)
        return cleared, True
    raise UserProfileExperienceReconciliationError(
        "The profile matches neither side of its pending transition.",
        path=experience_path,
        content_hash=(
            None if raw is None else _content_hash(raw)
        ),
    )


def _prepare_profile_writer_locked(
    profile_path: Path,
    experience_path: Path,
) -> tuple[ExperienceState | None, ExperienceWarning | None]:
    state, _, warning = _experience_state_for_writer(
        experience_path, allow_unavailable=True
    )
    if state is None:
        return None, warning
    state, _ = _reconcile_pending_change_locked(
        profile_path, experience_path, state
    )
    return state, None


def _persist_profile_transition_locked(
    profile_path: Path,
    experience_path: Path,
    *,
    before_raw: bytes | None,
    profile: StoredProfile,
    operation: str,
    effect: str,
    experience_state: ExperienceState | None,
) -> tuple[ExperienceState | None, bool]:
    candidate_raw = _serialize_profile(profile)
    if experience_state is None:
        if before_raw != candidate_raw:
            _atomic_write_bytes(profile_path, candidate_raw)
        return None, before_raw != candidate_raw

    before_version = _profile_version_from_raw(before_raw, profile_path)
    intent = PendingProfileChange(
        operation=operation,
        before_version=(
            None if before_version is None else before_version.token()
        ),
        before_content_hash=(
            None if before_raw is None else _content_hash(before_raw)
        ),
        after_version=profile.version.token(),
        after_content_hash=_content_hash(candidate_raw),
        experience_effect=effect,
    )
    staged = replace(
        experience_state,
        revision=experience_state.revision + 1,
        pending_profile_change=intent,
    )
    _persist_experience(experience_path, staged)
    profile_changed = before_raw != candidate_raw
    try:
        if profile_changed:
            _atomic_write_bytes(profile_path, candidate_raw)
    except UserProfilePersistenceError as exc:
        exc.reconciliation_required = True
        raise
    try:
        finalized = _finalize_profile_change(
            staged, profile, effect=effect
        )
        _persist_experience(experience_path, finalized)
    except UserProfileError as exc:
        exc.committed = profile_changed
        exc.version = profile.version
        exc.profile_changed = profile_changed
        exc.experience_committed = False
        exc.reconciliation_required = True
        raise
    return finalized, profile_changed


def _require_expected_version(
    actual: StoredProfile,
    expected: ProfileVersion,
    path: Path,
) -> None:
    if actual.version != expected:
        raise UserProfileConflictError(
            "The user profile changed after it was read.",
            expected_version=expected,
            actual_version=actual.version,
            path=path,
        )


def _validate_expected_version_argument(
    expected: ProfileVersion,
) -> ProfileVersion:
    if not isinstance(expected, ProfileVersion):
        raise UserProfileArgumentError(
            "The expected version must be a profile version."
        )
    if expected.generation is None:
        if expected.revision == 0:
            return expected
        raise UserProfileArgumentError(
            "The expected version is invalid."
        )
    try:
        generation = _validate_generation(expected.generation)
        revision = _require_integer(
            expected.revision, "expectedVersion.revision", minimum=1
        )
    except UserProfileValidationError as exc:
        raise UserProfileArgumentError(
            "The expected version is invalid."
        ) from exc
    return ProfileVersion(generation, revision)


def _profile_with(
    profile: StoredProfile,
    *,
    revision: int | None = None,
    onboarding: OnboardingState | None = None,
    preferences: Mapping[str, StoredPreference] | None = None,
    proposals: Mapping[str, PreferenceProposal] | None = None,
) -> StoredProfile:
    return StoredProfile(
        schema_version=profile.schema_version,
        generation=profile.generation,
        revision=profile.revision if revision is None else revision,
        onboarding=profile.onboarding if onboarding is None else onboarding,
        preferences=profile.preferences if preferences is None else preferences,
        proposals=profile.proposals if proposals is None else proposals,
    )


def initialize_profile(path: Path) -> MutationResult:
    path = Path(path)
    experience_path = _experience_path_for_profile(path)
    with _transaction_lock(path):
        experience_state, warning = _prepare_profile_writer_locked(
            path, experience_path
        )
        try:
            profile = load_profile(path)
        except UserProfileNotFoundError:
            profile = default_profile(
                generation=str(uuid.uuid4()),
                revision=1,
            )
            if experience_state is None:
                _persist_profile(path, profile)
                final_state = None
            else:
                final_state, _ = _persist_profile_transition_locked(
                    path,
                    experience_path,
                    before_raw=None,
                    profile=profile,
                    operation="initialize",
                    effect=(
                        "bind"
                        if experience_state.profile_generation is None
                        else "reset"
                    ),
                    experience_state=experience_state,
                )
            return MutationResult(
                True,
                True,
                profile,
                warnings=() if warning is None else (warning,),
                experience_version=(
                    None if final_state is None else final_state.version
                ),
            )
        return MutationResult(
            False,
            False,
            profile,
            warnings=() if warning is None else (warning,),
            experience_version=(
                None
                if experience_state is None
                else experience_state.version
            ),
        )


def set_preferences(
    path: Path,
    updates: Mapping[str, object],
    *,
    expected_version: ProfileVersion,
) -> MutationResult:
    expected_version = _validate_expected_version_argument(expected_version)
    if not isinstance(updates, Mapping) or not updates:
        raise UserProfileArgumentError(
            "Preference updates must be a nonempty JSON object."
        )
    unknown = set(updates) - set(PREFERENCE_FIELDS)
    if unknown:
        raise UserProfileArgumentError(
            "A preference update contains an unsupported field."
        )
    parsed: dict[str, tuple[Any, str | None]] = {}
    try:
        for field, value in updates.items():
            parsed[field] = _validate_preference_value(field, value)
    except UserProfileValidationError as exc:
        raise UserProfileArgumentError(str(exc)) from exc

    path = Path(path)
    experience_path = _experience_path_for_profile(path)
    with _transaction_lock(path):
        experience_state, warning = _prepare_profile_writer_locked(
            path, experience_path
        )
        profile = load_profile(path)
        _require_expected_version(profile, expected_version, path)
        preferences = dict(profile.preferences)
        proposals = dict(profile.proposals)
        now = _utc_now()
        changed = False
        for field, (value, unit) in parsed.items():
            current = preferences[field]
            preference_changed = (
                current.value != value
                or current.unit != unit
                or current.source is not PreferenceSource.EXPLICIT
            )
            proposal_removed = field in proposals
            if preference_changed:
                preferences[field] = StoredPreference(
                    value=value,
                    unit=unit,
                    source=PreferenceSource.EXPLICIT,
                    updated_at=now,
                )
            if proposal_removed:
                del proposals[field]
            changed = changed or preference_changed or proposal_removed
        if not changed:
            return MutationResult(
                False,
                False,
                profile,
                warnings=() if warning is None else (warning,),
                experience_version=(
                    None
                    if experience_state is None
                    else experience_state.version
                ),
            )
        candidate = _profile_with(
            profile,
            revision=profile.revision + 1,
            preferences=preferences,
            proposals=proposals,
        )
        candidate = validate_profile(candidate.to_document())
        _persist_profile(path, candidate)
        return MutationResult(
            True,
            True,
            candidate,
            warnings=() if warning is None else (warning,),
            experience_version=(
                None
                if experience_state is None
                else experience_state.version
            ),
        )


def set_onboarding_status(
    path: Path,
    status: OnboardingStatus,
    *,
    expected_version: ProfileVersion,
) -> MutationResult:
    expected_version = _validate_expected_version_argument(expected_version)
    if not isinstance(status, OnboardingStatus):
        try:
            status = OnboardingStatus(status)
        except (ValueError, TypeError) as exc:
            raise UserProfileArgumentError(
                "The onboarding status is not supported."
            ) from exc
    path = Path(path)
    experience_path = _experience_path_for_profile(path)
    with _transaction_lock(path):
        experience_state, warning = _prepare_profile_writer_locked(
            path, experience_path
        )
        profile = load_profile(path)
        _require_expected_version(profile, expected_version, path)
        if profile.onboarding.status is status:
            return MutationResult(
                False,
                False,
                profile,
                warnings=() if warning is None else (warning,),
                experience_version=(
                    None
                    if experience_state is None
                    else experience_state.version
                ),
            )
        candidate = _profile_with(
            profile,
            revision=profile.revision + 1,
            onboarding=OnboardingState(status, _utc_now()),
        )
        candidate = validate_profile(candidate.to_document())
        _persist_profile(path, candidate)
        return MutationResult(
            True,
            True,
            candidate,
            warnings=() if warning is None else (warning,),
            experience_version=(
                None
                if experience_state is None
                else experience_state.version
            ),
        )


def propose_preference(
    path: Path,
    field: str,
    value: object,
    observation_count: int,
    confidence: float,
    *,
    expected_version: ProfileVersion,
) -> MutationResult:
    expected_version = _validate_expected_version_argument(expected_version)
    try:
        proposed_value, unit = _validate_preference_value(field, value)
        observation_count = _require_integer(
            observation_count, "observationCount", minimum=1
        )
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or confidence < 0.0
            or confidence > 1.0
        ):
            raise UserProfileValidationError(
                "Field 'confidence' must be a finite number from 0.0 through 1.0."
            )
    except UserProfileValidationError as exc:
        raise UserProfileArgumentError(str(exc)) from exc

    path = Path(path)
    experience_path = _experience_path_for_profile(path)
    with _transaction_lock(path):
        experience_state, warning = _prepare_profile_writer_locked(
            path, experience_path
        )
        profile = load_profile(path)
        _require_expected_version(profile, expected_version, path)
        proposals = dict(profile.proposals)
        current = proposals.get(field)
        normalized_confidence = float(confidence)
        if (
            current is not None
            and current.status is ProposalStatus.PENDING
            and current.proposed_value == proposed_value
            and current.unit == unit
            and current.observation_count == observation_count
            and current.confidence == normalized_confidence
        ):
            return MutationResult(
                False,
                False,
                profile,
                warnings=() if warning is None else (warning,),
                experience_version=(
                    None
                    if experience_state is None
                    else experience_state.version
                ),
            )
        now = _utc_now()
        preserve_created = (
            current is not None
            and current.status is ProposalStatus.PENDING
            and current.proposed_value == proposed_value
            and current.unit == unit
        )
        created_at = (
            current.created_at
            if preserve_created
            else _later_timestamp(
                None if current is None else current.created_at,
                now,
            )
        )
        updated_at = _later_timestamp(created_at, now)
        proposals[field] = PreferenceProposal(
            proposed_value=proposed_value,
            unit=unit,
            observation_count=observation_count,
            confidence=normalized_confidence,
            status=ProposalStatus.PENDING,
            created_at=created_at,
            updated_at=updated_at,
        )
        candidate = _profile_with(
            profile,
            revision=profile.revision + 1,
            proposals=proposals,
        )
        candidate = validate_profile(candidate.to_document())
        _persist_profile(path, candidate)
        return MutationResult(
            True,
            True,
            candidate,
            warnings=() if warning is None else (warning,),
            experience_version=(
                None
                if experience_state is None
                else experience_state.version
            ),
        )


def _decide_proposal(
    path: Path,
    field: str,
    *,
    expected_version: ProfileVersion,
    accept: bool,
) -> MutationResult:
    expected_version = _validate_expected_version_argument(expected_version)
    if field not in PREFERENCE_FIELDS:
        raise UserProfileArgumentError(
            "The proposal preference name is not supported."
        )
    path = Path(path)
    experience_path = _experience_path_for_profile(path)
    with _transaction_lock(path):
        experience_state, warning = _prepare_profile_writer_locked(
            path, experience_path
        )
        profile = load_profile(path)
        _require_expected_version(profile, expected_version, path)
        proposal = profile.proposals.get(field)
        if proposal is None:
            raise UserProfileProposalError(
                "The requested proposal does not exist.",
                status="proposal_not_found",
            )
        if proposal.status is not ProposalStatus.PENDING:
            raise UserProfileProposalError(
                "The requested proposal is not pending.",
                status="proposal_not_pending",
            )
        now = _utc_now()
        proposals = dict(profile.proposals)
        proposals[field] = PreferenceProposal(
            proposed_value=proposal.proposed_value,
            unit=proposal.unit,
            observation_count=proposal.observation_count,
            confidence=proposal.confidence,
            status=(
                ProposalStatus.ACCEPTED if accept else ProposalStatus.REJECTED
            ),
            created_at=proposal.created_at,
            updated_at=now,
        )
        preferences = dict(profile.preferences)
        if accept:
            preferences[field] = StoredPreference(
                value=proposal.proposed_value,
                unit=proposal.unit,
                source=PreferenceSource.LEARNED,
                updated_at=now,
            )
        candidate = _profile_with(
            profile,
            revision=profile.revision + 1,
            preferences=preferences,
            proposals=proposals,
        )
        candidate = validate_profile(candidate.to_document())
        _persist_profile(path, candidate)
        return MutationResult(
            True,
            True,
            candidate,
            warnings=() if warning is None else (warning,),
            experience_version=(
                None
                if experience_state is None
                else experience_state.version
            ),
        )


def accept_proposal(
    path: Path,
    field: str,
    *,
    expected_version: ProfileVersion,
) -> MutationResult:
    return _decide_proposal(
        path, field, expected_version=expected_version, accept=True
    )


def reject_proposal(
    path: Path,
    field: str,
    *,
    expected_version: ProfileVersion,
) -> MutationResult:
    return _decide_proposal(
        path, field, expected_version=expected_version, accept=False
    )


def reset_profile(
    path: Path,
    *,
    expected_version: ProfileVersion,
    confirmed: bool = False,
) -> MutationResult:
    if not confirmed:
        raise UserProfileConfirmationError(
            "Reset requires explicit confirmation."
        )
    expected_version = _validate_expected_version_argument(expected_version)
    path = Path(path)
    experience_path = _experience_path_for_profile(path)
    with _transaction_lock(path):
        experience_state, warning = _prepare_profile_writer_locked(
            path, experience_path
        )
        profile = load_profile(path)
        _require_expected_version(profile, expected_version, path)
        reset = default_profile(
            generation=profile.generation,
            revision=profile.revision,
        )
        if (
            profile.onboarding == reset.onboarding
            and profile.preferences == reset.preferences
            and not profile.proposals
        ):
            candidate = profile
            profile_changed = False
        else:
            candidate = default_profile(
                generation=profile.generation,
                revision=profile.revision + 1,
            )
            profile_changed = True
        before_raw = path.read_bytes()
        if experience_state is not None:
            final_state, _ = _persist_profile_transition_locked(
                path,
                experience_path,
                before_raw=before_raw,
                profile=candidate,
                operation="reset",
                effect="reset",
                experience_state=experience_state,
            )
        else:
            final_state = None
            if profile_changed:
                _persist_profile(path, candidate)
        experience_changed = experience_state is not None
        return MutationResult(
            profile_changed or experience_changed,
            profile_changed or experience_changed,
            candidate,
            warnings=() if warning is None else (warning,),
            experience_version=(
                None if final_state is None else final_state.version
            ),
            profile_changed=profile_changed,
            experience_committed=experience_changed,
        )


def _write_recovery_backup(
    path: Path,
    raw: bytes,
    *,
    prefix: str = "user-profile",
) -> Path:
    while True:
        backup_path = path.parent / f"{prefix}.recovery.{uuid.uuid4()}.bak"
        try:
            with backup_path.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                _fsync(stream)
            return backup_path
        except FileExistsError:
            continue
        except OSError as exc:
            try:
                backup_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise UserProfilePersistenceError(
                "The recovery backup could not be persisted.", path=backup_path
            ) from exc


def recover_profile(
    path: Path,
    *,
    expected_content_hash: str,
    confirmed: bool = False,
) -> MutationResult:
    if not confirmed:
        raise UserProfileConfirmationError(
            "Recovery reset requires explicit confirmation."
        )
    if (
        not isinstance(expected_content_hash, str)
        or len(expected_content_hash) != 64
        or any(character not in "0123456789abcdef" for character in expected_content_hash)
    ):
        raise UserProfileArgumentError(
            "The expected content hash must be a lowercase SHA-256 digest."
        )
    path = Path(path)
    experience_path = _experience_path_for_profile(path)
    with _transaction_lock(path):
        experience_state, warning = _prepare_profile_writer_locked(
            path, experience_path
        )
        raw = _read_raw(path)
        actual_hash = _content_hash(raw)
        if actual_hash != expected_content_hash:
            raise UserProfileConflictError(
                "The damaged profile changed after it was inspected.",
                expected_content_hash=expected_content_hash,
                actual_content_hash=actual_hash,
                path=path,
            )
        try:
            _profile_from_raw(raw, path)
        except (UserProfileValidationError, UserProfileSchemaVersionError):
            pass
        else:
            raise UserProfileProposalError(
                "The user profile is valid; recovery is not required.",
                status="recovery_not_required",
            )
        backup_path = _write_recovery_backup(path, raw)
        candidate = default_profile(
            generation=str(uuid.uuid4()),
            revision=1,
        )
        try:
            if experience_state is not None:
                final_state, _ = _persist_profile_transition_locked(
                    path,
                    experience_path,
                    before_raw=raw,
                    profile=candidate,
                    operation="recover",
                    effect="reset",
                    experience_state=experience_state,
                )
            else:
                _persist_profile(path, candidate)
                final_state = None
        except UserProfilePersistenceError:
            raise
        return MutationResult(
            True,
            True,
            candidate,
            backup_path,
            warnings=() if warning is None else (warning,),
            experience_version=(
                None if final_state is None else final_state.version
            ),
            profile_changed=True,
            experience_committed=experience_state is not None,
        )


def _validate_expected_experience_version_argument(
    expected: ExperienceVersion,
) -> ExperienceVersion:
    if not isinstance(expected, ExperienceVersion):
        raise UserProfileArgumentError(
            "The expected version must be an experience version."
        )
    if expected.generation is None:
        if expected.revision == 0:
            return expected
        raise UserProfileArgumentError(
            "The expected experience version is invalid."
        )
    try:
        generation = _validate_generation(expected.generation)
        revision = _require_integer(
            expected.revision, "expectedExperienceVersion.revision", minimum=1
        )
    except UserProfileValidationError as exc:
        raise UserProfileArgumentError(
            "The expected experience version is invalid."
        ) from exc
    return ExperienceVersion(generation, revision)


def parse_experience_version(token: str) -> ExperienceVersion:
    if token == "none:0":
        return ExperienceVersion(None, 0)
    profile_version = parse_profile_version(token)
    if profile_version.generation is None:
        raise UserProfileArgumentError(
            "The expected experience version token is invalid."
        )
    return ExperienceVersion(
        profile_version.generation, profile_version.revision
    )


def _require_experience_version(
    actual: ExperienceVersion,
    expected: ExperienceVersion,
    path: Path,
) -> None:
    if actual != expected:
        raise UserProfileExperienceConflictError(
            "The experience state changed after it was read.",
            expected_version=expected,
            actual_version=actual,
            path=path,
        )


def _canonical_request_id(value: object) -> str:
    try:
        return _validate_generation(value)
    except UserProfileValidationError as exc:
        raise UserProfileArgumentError(
            "The request ID must be a canonical UUID v4."
        ) from exc


def _profile_snapshot_under_lock(
    profile_path: Path,
) -> tuple[bytes | None, EffectiveProfileResult]:
    raw = _read_optional_bytes(profile_path)
    return raw, _effective_result_from_raw(raw, profile_path)


def _fresh_experience_lifetime(
    state: ExperienceState | None,
    profile: EffectiveProfileResult,
) -> ExperienceState:
    current_generation = (
        None if profile.profile is None else profile.profile.generation
    )
    if state is None:
        return _empty_experience_state(
            generation=str(uuid.uuid4()),
            revision=0,
            profile_generation=current_generation,
        )
    if state.profile_generation != current_generation:
        return _empty_experience_state(
            generation=str(uuid.uuid4()),
            revision=0,
            profile_generation=current_generation,
        )
    return state


def _prune_proposal_prompts(
    state: ExperienceState,
    profile: EffectiveProfileResult,
) -> Mapping[str, ProposalPromptState]:
    pending = {
        field: proposal.created_at
        for field, proposal in profile.pending_proposals
    }
    return {
        field: prompt
        for field, prompt in state.proposal_prompts.items()
        if pending.get(field) == prompt.proposal_created_at
    }


def _load_experience_for_mutation_locked(
    profile_path: Path,
    experience_path: Path,
    expected_profile_version: ProfileVersion | None,
    expected_experience_version: ExperienceVersion,
) -> tuple[EffectiveProfileResult, ExperienceState, bool]:
    _, profile = _profile_snapshot_under_lock(profile_path)
    if (
        expected_profile_version is not None
        and profile.version != expected_profile_version
    ):
        raise UserProfileConflictError(
            "The user profile changed after it was read.",
            expected_version=expected_profile_version,
            actual_version=profile.version,
            path=profile_path,
        )
    state, raw, warning = _experience_state_for_writer(
        experience_path, allow_unavailable=False
    )
    if warning is not None:
        raise UserProfileExperienceValidationError(
            warning.error,
            path=experience_path,
            content_hash=warning.content_hash,
        )
    if state is not None:
        state, _ = _reconcile_pending_change_locked(
            profile_path, experience_path, state
        )
    actual_version = (
        ExperienceVersion(None, 0) if state is None else state.version
    )
    _require_experience_version(
        actual_version, expected_experience_version, experience_path
    )
    state = _fresh_experience_lifetime(state, profile)
    return profile, state, raw is not None


def _persist_experience_mutation(
    path: Path,
    state: ExperienceState,
) -> ExperienceState:
    if state.generation is None:
        state = replace(state, generation=str(uuid.uuid4()))
    if state.revision < 1:
        state = replace(state, revision=1)
    _persist_experience(path, state)
    return state


def _experience_result(
    profile: EffectiveProfileResult,
    state: ExperienceState | None,
    *,
    changed: bool,
    committed: bool,
    experience_committed: bool,
    replayed: bool = False,
    onboarding_offer: str = "none",
    proposal_field: str | None = None,
    proposal: PreferenceProposal | None = None,
    reviewed_version: ProfileVersion | None = None,
) -> ExperienceMutationResult:
    return ExperienceMutationResult(
        profile_version=profile.version,
        experience=state,
        changed=changed,
        committed=committed,
        experience_committed=experience_committed,
        replayed=replayed,
        onboarding_offer=onboarding_offer,
        proposal_field=proposal_field,
        proposal=proposal,
        reviewed_version=reviewed_version,
    )


def begin_profile_request(
    profile_path: Path,
    experience_path: Path,
    request_id: str,
    *,
    expected_profile_version: ProfileVersion,
    expected_experience_version: ExperienceVersion,
) -> ExperienceMutationResult:
    request_id = _canonical_request_id(request_id)
    expected_profile_version = _validate_expected_version_argument(
        expected_profile_version
    )
    expected_experience_version = _validate_expected_experience_version_argument(
        expected_experience_version
    )
    profile_path, experience_path = _validate_profile_experience_paths(
        profile_path, experience_path
    )
    with _transaction_lock(profile_path):
        profile_raw, profile = _profile_snapshot_under_lock(profile_path)
        state, _, warning = _experience_state_for_writer(
            experience_path, allow_unavailable=False
        )
        if warning is not None:
            raise UserProfileExperienceValidationError(
                warning.error,
                path=experience_path,
                content_hash=warning.content_hash,
            )
        receipt = None
        if state is not None:
            receipt = next(
                (
                    item
                    for item in state.request_receipts
                    if item.request_id == request_id
                ),
                None,
            )
        if receipt is not None:
            if (
                receipt.begin_profile_version
                != expected_profile_version.token()
                or profile.version != expected_profile_version
            ):
                raise UserProfileConflictError(
                    "The user profile changed after this request began.",
                    expected_version=expected_profile_version,
                    actual_version=profile.version,
                    path=profile_path,
                )
            return _experience_result(
                profile,
                state,
                changed=False,
                committed=False,
                experience_committed=False,
                replayed=True,
            )
        if profile.version != expected_profile_version:
            raise UserProfileConflictError(
                "The user profile changed after it was read.",
                expected_version=expected_profile_version,
                actual_version=profile.version,
                path=profile_path,
            )
        if state is not None:
            state, _ = _reconcile_pending_change_locked(
                profile_path, experience_path, state
            )
        actual_experience_version = (
            ExperienceVersion(None, 0)
            if state is None
            else state.version
        )
        _require_experience_version(
            actual_experience_version,
            expected_experience_version,
            experience_path,
        )
        state = _fresh_experience_lifetime(state, profile)
        next_run = state.eligible_run_count + 1
        onboarding = state.onboarding_prompt
        offer = "none"
        if (
            profile.onboarding_status is not OnboardingStatus.COMPLETED
            and not onboarding.suppressed
        ):
            if onboarding.prompt_count == 0:
                offer = "initial"
            elif (
                onboarding.prompt_count == 1
                and onboarding.last_prompt_run is not None
                and next_run - onboarding.last_prompt_run >= 3
            ):
                offer = "deferred_reoffer"
        now = _utc_now()
        if offer != "none":
            onboarding = OnboardingPromptState(
                prompt_count=onboarding.prompt_count + 1,
                last_prompt_run=next_run,
                suppressed=onboarding.suppressed,
                last_prompted_at=now,
            )
        new_receipt = RequestReceipt(
            request_id=request_id,
            begin_profile_version=expected_profile_version.token(),
            run_number=next_run,
            onboarding_offer=offer,
            finished=False,
            proposal_field=None,
        )
        candidate = replace(
            state,
            generation=state.generation or str(uuid.uuid4()),
            revision=state.revision + 1,
            eligible_run_count=next_run,
            onboarding_prompt=onboarding,
            proposal_prompts=_prune_proposal_prompts(state, profile),
            request_receipts=(state.request_receipts + (new_receipt,))[-64:],
        )
        candidate = _persist_experience_mutation(
            experience_path, candidate
        )
        return _experience_result(
            profile,
            candidate,
            changed=True,
            committed=True,
            experience_committed=True,
            onboarding_offer=offer,
        )


def finish_profile_request(
    profile_path: Path,
    experience_path: Path,
    request_id: str,
    *,
    expected_profile_version: ProfileVersion,
    expected_experience_version: ExperienceVersion,
    outcome: TaskOutcome,
    allows_extra_content: bool,
    optional_suggestion_used: bool,
) -> ExperienceMutationResult:
    request_id = _canonical_request_id(request_id)
    expected_profile_version = _validate_expected_version_argument(
        expected_profile_version
    )
    expected_experience_version = _validate_expected_experience_version_argument(
        expected_experience_version
    )
    if not isinstance(outcome, TaskOutcome):
        try:
            outcome = TaskOutcome(outcome)
        except (TypeError, ValueError) as exc:
            raise UserProfileArgumentError(
                "The task outcome is not supported."
            ) from exc
    if not isinstance(allows_extra_content, bool) or not isinstance(
        optional_suggestion_used, bool
    ):
        raise UserProfileArgumentError(
            "Suggestion eligibility flags must be booleans."
        )
    profile_path, experience_path = _validate_profile_experience_paths(
        profile_path, experience_path
    )
    with _transaction_lock(profile_path):
        _, profile = _profile_snapshot_under_lock(profile_path)
        state, _, warning = _experience_state_for_writer(
            experience_path, allow_unavailable=False
        )
        if warning is not None:
            raise UserProfileExperienceValidationError(
                warning.error,
                path=experience_path,
                content_hash=warning.content_hash,
            )
        if state is not None:
            state, _ = _reconcile_pending_change_locked(
                profile_path, experience_path, state
            )
        if profile.version != expected_profile_version:
            raise UserProfileConflictError(
                "The user profile changed after it was read.",
                expected_version=expected_profile_version,
                actual_version=profile.version,
                path=profile_path,
            )
        if state is None:
            raise UserProfileRequestExpiredError(
                "The request receipt is no longer available.",
                path=experience_path,
            )
        receipt_index = next(
            (
                index
                for index, item in enumerate(state.request_receipts)
                if item.request_id == request_id
            ),
            None,
        )
        if receipt_index is None:
            raise UserProfileRequestExpiredError(
                "The request receipt is no longer available.",
                path=experience_path,
            )
        receipt = state.request_receipts[receipt_index]
        if receipt.finished:
            return _experience_result(
                profile,
                state,
                changed=False,
                committed=False,
                experience_committed=False,
                replayed=True,
            )
        _require_experience_version(
            state.version, expected_experience_version, experience_path
        )
        proposal_field: str | None = None
        selected_proposal: PreferenceProposal | None = None
        proposal_prompts = dict(state.proposal_prompts)
        if (
            outcome is TaskOutcome.COMPLETED
            and allows_extra_content
            and not optional_suggestion_used
            and profile.effective_profile.proactive_suggestions
            is not ProactiveSuggestions.OFF
        ):
            for field, proposal in profile.pending_proposals:
                prompt = proposal_prompts.get(field)
                if prompt is not None and (
                    prompt.proposal_created_at != proposal.created_at
                    or prompt.suppressed
                    or prompt.prompt_count >= 2
                ):
                    continue
                baseline = None
                if prompt is not None:
                    values = [
                        value
                        for value in (
                            prompt.last_prompt_run,
                            prompt.snoozed_at_run,
                        )
                        if value is not None
                    ]
                    baseline = max(values) if values else None
                if (
                    baseline is not None
                    and state.eligible_run_count - baseline < 3
                ):
                    continue
                proposal_field = field
                selected_proposal = proposal
                prompt_count = 1 if prompt is None else prompt.prompt_count + 1
                proposal_prompts[field] = ProposalPromptState(
                    proposal_created_at=proposal.created_at,
                    prompt_count=prompt_count,
                    last_prompt_run=state.eligible_run_count,
                    snoozed_at_run=None,
                    suppressed=False,
                    last_prompted_at=_utc_now(),
                )
                break
        receipts = list(state.request_receipts)
        receipts[receipt_index] = replace(
            receipt,
            finished=True,
            proposal_field=proposal_field,
        )
        candidate = replace(
            state,
            revision=state.revision + 1,
            proposal_prompts=proposal_prompts,
            request_receipts=tuple(receipts),
        )
        candidate = _persist_experience_mutation(
            experience_path, candidate
        )
        return _experience_result(
            profile,
            candidate,
            changed=True,
            committed=True,
            experience_committed=True,
            proposal_field=proposal_field,
            proposal=selected_proposal,
            reviewed_version=profile.version if selected_proposal else None,
        )


def _parse_profile_updates(
    updates: Mapping[str, object],
    *,
    allow_empty: bool,
) -> dict[str, tuple[Any, str | None]]:
    if not isinstance(updates, Mapping) or (
        not allow_empty and not updates
    ):
        raise UserProfileArgumentError(
            "Preference updates must be a nonempty JSON object."
        )
    if set(updates) - set(PREFERENCE_FIELDS):
        raise UserProfileArgumentError(
            "A preference update contains an unsupported field."
        )
    parsed: dict[str, tuple[Any, str | None]] = {}
    try:
        for field, value in updates.items():
            parsed[field] = _validate_preference_value(field, value)
    except UserProfileValidationError as exc:
        raise UserProfileArgumentError(str(exc)) from exc
    return parsed


def _profile_after_confirmed_save(
    profile: StoredProfile | None,
    parsed_updates: Mapping[str, tuple[Any, str | None]],
) -> tuple[StoredProfile, bool]:
    now = _utc_now()
    if profile is None:
        current = default_profile(generation=str(uuid.uuid4()), revision=1)
        preferences = dict(current.preferences)
        proposals: Mapping[str, PreferenceProposal] = {}
        for field, (value, unit) in parsed_updates.items():
            preferences[field] = StoredPreference(
                value=value,
                unit=unit,
                source=PreferenceSource.EXPLICIT,
                updated_at=now,
            )
        candidate = _profile_with(
            current,
            onboarding=OnboardingState(OnboardingStatus.COMPLETED, now),
            preferences=preferences,
            proposals=proposals,
        )
        return validate_profile(candidate.to_document()), True

    preferences = dict(profile.preferences)
    proposals = dict(profile.proposals)
    changed = profile.onboarding.status is not OnboardingStatus.COMPLETED
    for field, (value, unit) in parsed_updates.items():
        current = preferences[field]
        if (
            current.value != value
            or current.unit != unit
            or current.source is not PreferenceSource.EXPLICIT
        ):
            preferences[field] = StoredPreference(
                value=value,
                unit=unit,
                source=PreferenceSource.EXPLICIT,
                updated_at=now,
            )
            changed = True
        if field in proposals:
            del proposals[field]
            changed = True
    if not changed:
        return profile, False
    onboarding = profile.onboarding
    if onboarding.status is not OnboardingStatus.COMPLETED:
        onboarding = OnboardingState(OnboardingStatus.COMPLETED, now)
    candidate = _profile_with(
        profile,
        revision=profile.revision + 1,
        onboarding=onboarding,
        preferences=preferences,
        proposals=proposals,
    )
    return validate_profile(candidate.to_document()), True


def complete_onboarding(
    profile_path: Path,
    experience_path: Path,
    updates: Mapping[str, object],
    *,
    expected_profile_version: ProfileVersion,
    confirmed: bool = False,
) -> CompositeMutationResult:
    if not confirmed:
        raise UserProfileConfirmationError(
            "Saving profile preferences requires explicit confirmation."
        )
    expected_profile_version = _validate_expected_version_argument(
        expected_profile_version
    )
    parsed_updates = _parse_profile_updates(updates, allow_empty=True)
    profile_path, experience_path = _validate_profile_experience_paths(
        profile_path, experience_path
    )
    with _transaction_lock(profile_path):
        experience_state, warning = _prepare_profile_writer_locked(
            profile_path, experience_path
        )
        before_raw = _read_optional_bytes(profile_path)
        current_result = _effective_result_from_raw(
            before_raw, profile_path
        )
        if current_result.version != expected_profile_version:
            raise UserProfileConflictError(
                "The user profile changed after it was reviewed.",
                expected_version=expected_profile_version,
                actual_version=current_result.version,
                path=profile_path,
            )
        candidate, changed = _profile_after_confirmed_save(
            current_result.profile, parsed_updates
        )
        final_state = experience_state
        if changed:
            if current_result.profile is None and experience_state is not None:
                effect = (
                    "bind"
                    if experience_state.profile_generation is None
                    else "reset"
                )
                final_state, _ = _persist_profile_transition_locked(
                    profile_path,
                    experience_path,
                    before_raw=before_raw,
                    profile=candidate,
                    operation="onboarding-complete",
                    effect=effect,
                    experience_state=experience_state,
                )
            else:
                _persist_profile(profile_path, candidate)
        effective = _resolve_effective(candidate)
        return CompositeMutationResult(
            profile=candidate,
            effective_profile=effective,
            experience_version=(
                None if final_state is None else final_state.version
            ),
            changed=changed,
            committed=changed,
            profile_changed=changed,
            experience_committed=(
                final_state is not experience_state
                or (changed and current_result.profile is None and experience_state is not None)
            ),
            warnings=() if warning is None else (warning,),
        )


def defer_onboarding(
    profile_path: Path,
    experience_path: Path,
    request_id: str,
    *,
    expected_profile_version: ProfileVersion,
) -> CompositeMutationResult:
    request_id = _canonical_request_id(request_id)
    expected_profile_version = _validate_expected_version_argument(
        expected_profile_version
    )
    profile_path, experience_path = _validate_profile_experience_paths(
        profile_path, experience_path
    )
    with _transaction_lock(profile_path):
        state, _, warning = _experience_state_for_writer(
            experience_path, allow_unavailable=False
        )
        if warning is not None or state is None:
            raise UserProfileExperienceValidationError(
                "A retained invitation receipt is required to defer onboarding.",
                path=experience_path,
                content_hash=None if warning is None else warning.content_hash,
            )
        state, _ = _reconcile_pending_change_locked(
            profile_path, experience_path, state
        )
        before_raw, current_result = _profile_snapshot_under_lock(
            profile_path
        )
        if current_result.version != expected_profile_version:
            raise UserProfileConflictError(
                "The user profile changed after it was read.",
                expected_version=expected_profile_version,
                actual_version=current_result.version,
                path=profile_path,
            )
        current_generation = (
            None
            if current_result.profile is None
            else current_result.profile.generation
        )
        if state.profile_generation != current_generation:
            raise UserProfileRequestExpiredError(
                "The invitation receipt belongs to a different profile lifetime.",
                path=experience_path,
            )
        if not any(
            receipt.request_id == request_id
            for receipt in state.request_receipts
        ):
            raise UserProfileRequestExpiredError(
                "The invitation receipt is no longer available.",
                path=experience_path,
            )
        if current_result.onboarding_status is OnboardingStatus.COMPLETED:
            raise UserProfileOnboardingNotRequiredError(
                "Onboarding is already completed.",
                path=profile_path,
            )
        if (
            current_result.profile is not None
            and current_result.onboarding_status is OnboardingStatus.DEFERRED
        ):
            return CompositeMutationResult(
                profile=current_result.profile,
                effective_profile=current_result.effective_profile,
                experience_version=state.version,
                changed=False,
                committed=False,
                profile_changed=False,
                experience_committed=False,
            )
        now = _utc_now()
        if current_result.profile is None:
            current = default_profile(
                generation=str(uuid.uuid4()), revision=1
            )
            candidate = validate_profile(
                _profile_with(
                    current,
                    onboarding=OnboardingState(
                        OnboardingStatus.DEFERRED, now
                    ),
                ).to_document()
            )
            effect = (
                "bind" if state.profile_generation is None else "reset"
            )
            final_state, _ = _persist_profile_transition_locked(
                profile_path,
                experience_path,
                before_raw=before_raw,
                profile=candidate,
                operation="onboarding-defer",
                effect=effect,
                experience_state=state,
            )
        else:
            candidate = validate_profile(
                _profile_with(
                    current_result.profile,
                    revision=current_result.profile.revision + 1,
                    onboarding=OnboardingState(
                        OnboardingStatus.DEFERRED, now
                    ),
                ).to_document()
            )
            _persist_profile(profile_path, candidate)
            final_state = state
        return CompositeMutationResult(
            profile=candidate,
            effective_profile=_resolve_effective(candidate),
            experience_version=final_state.version,
            changed=True,
            committed=True,
            profile_changed=True,
            experience_committed=final_state is not state,
        )


def suppress_onboarding_offer(
    profile_path: Path,
    experience_path: Path,
    *,
    expected_profile_version: ProfileVersion,
    expected_experience_version: ExperienceVersion,
    confirmed: bool = False,
) -> ExperienceMutationResult:
    if not confirmed:
        raise UserProfileConfirmationError(
            "Suppressing future onboarding invitations requires confirmation."
        )
    expected_profile_version = _validate_expected_version_argument(
        expected_profile_version
    )
    expected_experience_version = _validate_expected_experience_version_argument(
        expected_experience_version
    )
    profile_path, experience_path = _validate_profile_experience_paths(
        profile_path, experience_path
    )
    with _transaction_lock(profile_path):
        profile, state, _ = _load_experience_for_mutation_locked(
            profile_path,
            experience_path,
            expected_profile_version,
            expected_experience_version,
        )
        onboarding = state.onboarding_prompt
        if onboarding.suppressed:
            return _experience_result(
                profile,
                state if state.generation is not None else None,
                changed=False,
                committed=False,
                experience_committed=False,
            )
        candidate = replace(
            state,
            revision=state.revision + 1,
            onboarding_prompt=replace(onboarding, suppressed=True),
        )
        candidate = _persist_experience_mutation(
            experience_path, candidate
        )
        return _experience_result(
            profile,
            candidate,
            changed=True,
            committed=True,
            experience_committed=True,
        )


def reconcile_experience_state(
    profile_path: Path,
    experience_path: Path,
    *,
    expected_experience_version: ExperienceVersion,
) -> ExperienceMutationResult:
    expected_experience_version = _validate_expected_experience_version_argument(
        expected_experience_version
    )
    profile_path, experience_path = _validate_profile_experience_paths(
        profile_path, experience_path
    )
    with _transaction_lock(profile_path):
        _, profile = _profile_snapshot_under_lock(profile_path)
        state, _, warning = _experience_state_for_writer(
            experience_path, allow_unavailable=False
        )
        if warning is not None:
            raise UserProfileExperienceValidationError(
                warning.error,
                path=experience_path,
                content_hash=warning.content_hash,
            )
        actual = ExperienceVersion(None, 0) if state is None else state.version
        _require_experience_version(
            actual, expected_experience_version, experience_path
        )
        if state is None or state.pending_profile_change is None:
            return _experience_result(
                profile,
                state,
                changed=False,
                committed=False,
                experience_committed=False,
            )
        reconciled, changed = _reconcile_pending_change_locked(
            profile_path, experience_path, state
        )
        return _experience_result(
            profile,
            reconciled,
            changed=changed,
            committed=changed,
            experience_committed=changed,
        )


def reset_experience_state(
    profile_path: Path,
    experience_path: Path,
    *,
    expected_profile_version: ProfileVersion,
    expected_experience_version: ExperienceVersion,
    confirmed: bool = False,
) -> ExperienceMutationResult:
    if not confirmed:
        raise UserProfileConfirmationError(
            "Resetting reminder history requires explicit confirmation."
        )
    expected_profile_version = _validate_expected_version_argument(
        expected_profile_version
    )
    expected_experience_version = _validate_expected_experience_version_argument(
        expected_experience_version
    )
    profile_path, experience_path = _validate_profile_experience_paths(
        profile_path, experience_path
    )
    if not profile_path.parent.exists():
        profile = _effective_result_from_raw(None, profile_path)
        if profile.version != expected_profile_version:
            raise UserProfileConflictError(
                "The user profile changed after it was read.",
                expected_version=expected_profile_version,
                actual_version=profile.version,
                path=profile_path,
            )
        _require_experience_version(
            ExperienceVersion(None, 0),
            expected_experience_version,
            experience_path,
        )
        return _experience_result(
            profile,
            None,
            changed=False,
            committed=False,
            experience_committed=False,
        )
    with _transaction_lock(profile_path):
        _, profile = _profile_snapshot_under_lock(profile_path)
        if profile.version != expected_profile_version:
            raise UserProfileConflictError(
                "The user profile changed after it was read.",
                expected_version=expected_profile_version,
                actual_version=profile.version,
                path=profile_path,
            )
        state, _, warning = _experience_state_for_writer(
            experience_path, allow_unavailable=False
        )
        if warning is not None:
            raise UserProfileExperienceValidationError(
                warning.error,
                path=experience_path,
                content_hash=warning.content_hash,
            )
        actual = ExperienceVersion(None, 0) if state is None else state.version
        _require_experience_version(
            actual, expected_experience_version, experience_path
        )
        if state is None:
            return _experience_result(
                profile,
                None,
                changed=False,
                committed=False,
                experience_committed=False,
            )
        if state.pending_profile_change is not None:
            reconciled, _ = _reconcile_pending_change_locked(
                profile_path, experience_path, state
            )
            raise UserProfileExperienceConflictError(
                "Reminder history changed during reconciliation.",
                expected_version=expected_experience_version,
                actual_version=reconciled.version,
                path=experience_path,
            )
        current_generation = (
            None if profile.profile is None else profile.profile.generation
        )
        reset = _empty_experience_state(
            generation=str(uuid.uuid4()),
            revision=1,
            profile_generation=current_generation,
        )
        _persist_experience(experience_path, reset)
        return _experience_result(
            profile,
            reset,
            changed=True,
            committed=True,
            experience_committed=True,
        )


def recover_experience_state(
    profile_path: Path,
    experience_path: Path,
    *,
    expected_content_hash: str,
    expected_profile_version: ProfileVersion | None = None,
    expected_profile_content_hash: str | None = None,
    confirmed: bool = False,
) -> ExperienceMutationResult:
    if not confirmed:
        raise UserProfileConfirmationError(
            "Repairing reminder history requires explicit confirmation."
        )
    if (expected_profile_version is None) == (
        expected_profile_content_hash is None
    ):
        raise UserProfileArgumentError(
            "Provide exactly one expected profile version or content hash."
        )
    expected_content_hash = _valid_content_hash(
        expected_content_hash, "expectedContentHash"
    )
    if expected_profile_version is not None:
        expected_profile_version = _validate_expected_version_argument(
            expected_profile_version
        )
    if expected_profile_content_hash is not None:
        expected_profile_content_hash = _valid_content_hash(
            expected_profile_content_hash,
            "expectedProfileContentHash",
        )
    profile_path, experience_path = _validate_profile_experience_paths(
        profile_path, experience_path
    )
    with _transaction_lock(profile_path):
        experience_raw = _read_optional_bytes(experience_path)
        if experience_raw is None:
            raise UserProfileProposalError(
                "Reminder history does not need repair.",
                status="recovery_not_required",
            )
        actual_hash = _content_hash(experience_raw)
        if actual_hash != expected_content_hash:
            raise UserProfileExperienceConflictError(
                "Reminder history changed after it was inspected.",
                expected_content_hash=expected_content_hash,
                actual_content_hash=actual_hash,
                path=experience_path,
            )
        profile_raw = _read_optional_bytes(profile_path)
        profile: EffectiveProfileResult
        profile_error: UserProfileError | None = None
        try:
            profile = _effective_result_from_raw(profile_raw, profile_path)
        except (UserProfileValidationError, UserProfileSchemaVersionError) as exc:
            profile_error = exc
            profile = _effective_result_from_raw(None, profile_path)
        if expected_profile_content_hash is not None:
            if profile_error is None or profile_raw is None:
                raise UserProfileArgumentError(
                    "A profile content hash is only valid for damaged profile state."
                )
            actual_profile_hash = _content_hash(profile_raw)
            if actual_profile_hash != expected_profile_content_hash:
                raise UserProfileExperienceConflictError(
                    "The profile changed after it was inspected.",
                    expected_content_hash=expected_profile_content_hash,
                    actual_content_hash=actual_profile_hash,
                    resource="profile",
                    path=profile_path,
                )
        else:
            assert expected_profile_version is not None
            if profile_error is not None:
                raise profile_error
            if profile.version != expected_profile_version:
                raise UserProfileConflictError(
                    "The user profile changed after it was read.",
                    expected_version=expected_profile_version,
                    actual_version=profile.version,
                    path=profile_path,
                )
        try:
            state = validate_experience_state(
                _parse_json_bytes(experience_raw)
            )
        except UserProfileExperienceSchemaVersionError:
            state = None
        except (UserProfileExperienceValidationError, UserProfileValidationError):
            state = None
        if state is not None and state.pending_profile_change is not None:
            pending = state.pending_profile_change
            if _pending_change_matches(
                profile_raw,
                profile_path,
                expected_version=pending.after_version,
                expected_hash=pending.after_content_hash,
            ) or _pending_change_matches(
                profile_raw,
                profile_path,
                expected_version=pending.before_version,
                expected_hash=pending.before_content_hash,
            ):
                reconciled, _ = _reconcile_pending_change_locked(
                    profile_path, experience_path, state
                )
                return _experience_result(
                    profile,
                    reconciled,
                    changed=True,
                    committed=True,
                    experience_committed=True,
                )
        elif state is not None:
            raise UserProfileProposalError(
                "Reminder history is valid; repair is not required.",
                status="recovery_not_required",
            )

        backup_path = _write_recovery_backup(
            experience_path,
            experience_raw,
            prefix="user-profile-experience",
        )
        pending_proposals = (
            {}
            if profile_error is not None or profile.profile is None
            else {
                field: ProposalPromptState(
                    proposal_created_at=proposal.created_at,
                    prompt_count=0,
                    last_prompt_run=None,
                    snoozed_at_run=None,
                    suppressed=True,
                    last_prompted_at=None,
                )
                for field, proposal in profile.pending_proposals
            }
        )
        repaired = _empty_experience_state(
            generation=str(uuid.uuid4()),
            revision=1,
            profile_generation=(
                None if profile_error is not None else (
                    None if profile.profile is None else profile.profile.generation
                )
            ),
            onboarding_prompt=OnboardingPromptState(0, None, True, None),
            proposal_prompts=pending_proposals,
        )
        _persist_experience(experience_path, repaired)
        result = _experience_result(
            profile,
            repaired,
            changed=True,
            committed=True,
            experience_committed=True,
        )
        return replace(result, backup_path=backup_path)


def describe_profile(effective: EffectiveProfile) -> ProfilePresentation:
    if effective.tone_of_voice is ToneOfVoice.EMPATHETIC or (
        effective.confirmation_frequency is ConfirmationFrequency.FREQUENT
    ):
        persona_id, persona_name = "supportive_learner", "Supportive Learner"
    elif (
        effective.detail_level is DetailLevel.DETAILED
        or effective.response_format is ResponseFormat.TABLE_FIRST
    ):
        persona_id, persona_name = "curious_architect", "Curious Architect"
    elif (
        effective.detail_level is DetailLevel.CONCISE
        and effective.confirmation_frequency is ConfirmationFrequency.MINIMAL
    ):
        persona_id, persona_name = "focused_navigator", "Focused Navigator"
    elif (
        effective.response_format is ResponseFormat.STEPS
        or effective.tone_of_voice is ToneOfVoice.FORMAL
    ):
        persona_id, persona_name = "methodical_planner", "Methodical Planner"
    elif (
        effective.tone_of_voice is ToneOfVoice.FRIENDLY_PROFESSIONAL
        or effective.response_format
        in {ResponseFormat.BULLETS, ResponseFormat.PROSE}
    ):
        persona_id, persona_name = "collaborative_builder", "Collaborative Builder"
    else:
        persona_id, persona_name = "adaptive_explorer", "Adaptive Explorer"

    value_labels = {
        "responseFormat": {
            ResponseFormat.AUTO: "Use the clearest format",
            ResponseFormat.PROSE: "Plain-language paragraphs",
            ResponseFormat.BULLETS: "Crisp bullet points",
            ResponseFormat.STEPS: "Numbered steps",
            ResponseFormat.TABLE_FIRST: "Comparable information in tables",
        },
        "detailLevel": {
            DetailLevel.CONCISE: "Concise",
            DetailLevel.BALANCED: "Balanced",
            DetailLevel.DETAILED: "Detailed",
        },
        "toneOfVoice": {
            ToneOfVoice.DIRECT: "Direct",
            ToneOfVoice.FRIENDLY_PROFESSIONAL: "Friendly and professional",
            ToneOfVoice.FORMAL: "Formal",
            ToneOfVoice.EMPATHETIC: "Empathetic",
        },
        "confirmationFrequency": {
            ConfirmationFrequency.MINIMAL: "Only when truly stuck",
            ConfirmationFrequency.STANDARD: "When genuinely unclear",
            ConfirmationFrequency.FREQUENT: "Before significant choices",
        },
        "proactiveSuggestions": {
            ProactiveSuggestions.OFF: "Off",
            ProactiveSuggestions.CONTEXTUAL: "One useful in-task tip",
            ProactiveSuggestions.ON: "One adjacent next step",
        },
    }
    response_format = value_labels["responseFormat"][effective.response_format]
    detail = value_labels["detailLevel"][effective.detail_level]
    tone = value_labels["toneOfVoice"][effective.tone_of_voice]
    check_ins = value_labels["confirmationFrequency"][
        effective.confirmation_frequency
    ]
    maximum = (
        "No preferred maximum"
        if effective.maximum_response_length is None
        else f"About {effective.maximum_response_length} words"
    )
    tips = value_labels["proactiveSuggestions"][
        effective.proactive_suggestions
    ]
    labels = (
        ("responseFormat", "How replies are shaped", response_format),
        ("detailLevel", "How much detail", detail),
        ("maximumResponseLength", "Preferred maximum length", maximum),
        ("toneOfVoice", "Voice", tone),
        ("confirmationFrequency", "Check-ins", check_ins),
        ("proactiveSuggestions", "Optional tips", tips),
    )
    summary = (
        f"Prefers {response_format.lower()}, {detail.lower()} detail, a "
        f"{tone.lower()} voice, {check_ins.lower()}, {maximum.lower()}, "
        f"and optional tips {tips.lower()}."
    )
    facts = (
        "Files saved locally.",
        "Review is required.",
        "No live deployment occurred.",
    )
    if effective.response_format is ResponseFormat.TABLE_FIRST:
        example = (
            "| Check | Result |\n|---|---|\n"
            f"| Local save | {facts[0]} |\n"
            f"| Review | {facts[1]} |\n"
            f"| Deployment | {facts[2]} |"
        )
    elif effective.response_format is ResponseFormat.STEPS:
        example = "\n".join(
            f"{index}. {fact}" for index, fact in enumerate(facts, start=1)
        )
    elif effective.response_format is ResponseFormat.BULLETS:
        example = "\n".join(f"- {fact}" for fact in facts)
    else:
        example = " ".join(facts)
    return ProfilePresentation(
        persona_id=persona_id,
        persona_name=persona_name,
        labels=labels,
        summary=summary,
        example=example,
    )


def preview_profile(values: Mapping[str, object]) -> ProfilePresentation:
    parsed = _parse_profile_updates(values, allow_empty=False)
    if set(parsed) != set(PREFERENCE_FIELDS):
        raise UserProfileArgumentError(
            "Preview requires all six preference fields."
        )
    return describe_profile(
        EffectiveProfile(
            response_format=parsed["responseFormat"][0],
            detail_level=parsed["detailLevel"][0],
            tone_of_voice=parsed["toneOfVoice"][0],
            confirmation_frequency=parsed["confirmationFrequency"][0],
            maximum_response_length=parsed["maximumResponseLength"][0],
            proactive_suggestions=parsed["proactiveSuggestions"][0],
        )
    )


def snooze_proposal_prompt(
    profile_path: Path,
    experience_path: Path,
    field: str,
    proposal_created_at: str,
    *,
    expected_profile_version: ProfileVersion,
    expected_experience_version: ExperienceVersion,
    origin: PromptOrigin,
) -> ExperienceMutationResult:
    if field not in PREFERENCE_FIELDS:
        raise UserProfileArgumentError(
            "The proposal preference name is not supported."
        )
    proposal_created_at = _experience_timestamp(
        proposal_created_at, "proposalCreatedAt"
    )
    expected_profile_version = _validate_expected_version_argument(
        expected_profile_version
    )
    expected_experience_version = _validate_expected_experience_version_argument(
        expected_experience_version
    )
    if not isinstance(origin, PromptOrigin):
        try:
            origin = PromptOrigin(origin)
        except (TypeError, ValueError) as exc:
            raise UserProfileArgumentError(
                "The proposal prompt origin is not supported."
            ) from exc
    profile_path, experience_path = _validate_profile_experience_paths(
        profile_path, experience_path
    )
    with _transaction_lock(profile_path):
        profile, state, _ = _load_experience_for_mutation_locked(
            profile_path,
            experience_path,
            expected_profile_version,
            expected_experience_version,
        )
        proposal = dict(profile.pending_proposals).get(field)
        if proposal is None or proposal.created_at != proposal_created_at:
            raise UserProfileProposalError(
                "The reviewed proposal is no longer pending.",
                status="proposal_not_found",
            )
        current = state.proposal_prompts.get(field)
        if current is not None and (
            current.proposal_created_at != proposal_created_at
        ):
            current = None
        if origin is PromptOrigin.AUTOMATIC:
            if current is None or current.prompt_count == 0:
                raise UserProfileProposalError(
                    "The proposal has no matching automatic presentation claim.",
                    status="proposal_prompt_not_claimed",
                )
            matching_receipt = any(
                receipt.proposal_field == field
                and receipt.run_number == current.last_prompt_run
                for receipt in state.request_receipts
            )
            if not matching_receipt:
                raise UserProfileProposalError(
                    "The automatic proposal claim is no longer available.",
                    status="proposal_prompt_not_claimed",
                )
            if current.prompt_count < 2 or current.suppressed:
                return _experience_result(
                    profile,
                    state if state.generation is not None else None,
                    changed=False,
                    committed=False,
                    experience_committed=False,
                )
            candidate = replace(
                state,
                revision=state.revision + 1,
                proposal_prompts={
                    **state.proposal_prompts,
                    field: replace(current, suppressed=True),
                },
            )
        else:
            baseline = state.eligible_run_count
            if (
                current is not None
                and current.snoozed_at_run == baseline
            ):
                return _experience_result(
                    profile,
                    state if state.generation is not None else None,
                    changed=False,
                    committed=False,
                    experience_committed=False,
                )
            proposal_prompts = dict(state.proposal_prompts)
            proposal_prompts[field] = ProposalPromptState(
                proposal_created_at=proposal_created_at,
                prompt_count=0 if current is None else current.prompt_count,
                last_prompt_run=None if current is None else current.last_prompt_run,
                snoozed_at_run=baseline,
                suppressed=False,
                last_prompted_at=None if current is None else current.last_prompted_at,
            )
            candidate = replace(
                state,
                revision=state.revision + 1,
                proposal_prompts=proposal_prompts,
            )
        candidate = _persist_experience_mutation(
            experience_path, candidate
        )
        return _experience_result(
            profile,
            candidate,
            changed=True,
            committed=True,
            experience_committed=True,
        )


def parse_profile_version(token: str) -> ProfileVersion:
    if token == "none:0":
        return ProfileVersion(None, 0)
    if not isinstance(token, str) or token.count(":") != 1:
        raise UserProfileArgumentError(
            "The expected version token is invalid."
        )
    generation, revision_text = token.split(":", 1)
    try:
        parsed_generation = _validate_generation(generation)
    except UserProfileValidationError as exc:
        raise UserProfileArgumentError(
            "The expected version token is invalid."
        ) from exc
    if not revision_text.isdigit():
        raise UserProfileArgumentError(
            "The expected version token is invalid."
        )
    revision = int(revision_text)
    if revision < 1:
        raise UserProfileArgumentError(
            "The expected version token is invalid."
        )
    return ProfileVersion(parsed_generation, revision)


def _effective_profile_document(profile: EffectiveProfile) -> dict[str, Any]:
    return {
        "responseFormat": profile.response_format.value,
        "detailLevel": profile.detail_level.value,
        "toneOfVoice": profile.tone_of_voice.value,
        "confirmationFrequency": profile.confirmation_frequency.value,
        "maximumResponseLength": {
            "value": profile.maximum_response_length,
            "unit": "words",
        },
        "proactiveSuggestions": profile.proactive_suggestions.value,
    }


def _pending_proposal_documents(
    proposals: tuple[tuple[str, PreferenceProposal], ...],
) -> list[dict[str, Any]]:
    result = []
    for field, proposal in proposals:
        proposed_value: Any = _json_value(proposal.proposed_value)
        if field == "maximumResponseLength":
            proposed_value = {
                "value": proposed_value,
                "unit": proposal.unit,
            }
        result.append(
            {
                "field": field,
                "proposedValue": proposed_value,
                "observationCount": proposal.observation_count,
                "confidence": proposal.confidence,
                "status": proposal.status.value,
                "createdAt": proposal.created_at,
                "updatedAt": proposal.updated_at,
            }
        )
    return result


def _proposal_document(
    field: str,
    proposal: PreferenceProposal,
) -> dict[str, Any]:
    proposed_value: Any = _json_value(proposal.proposed_value)
    if field == "maximumResponseLength":
        proposed_value = {"value": proposed_value, "unit": proposal.unit}
    return {
        "field": field,
        "proposedValue": proposed_value,
        "observationCount": proposal.observation_count,
        "confidence": proposal.confidence,
        "status": proposal.status.value,
        "createdAt": proposal.created_at,
        "updatedAt": proposal.updated_at,
    }


def _experience_mutation_document(
    operation: str,
    result: ExperienceMutationResult,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "status": "ok",
        "operation": operation,
        "experienceSchemaVersion": 1,
        "profileVersion": result.profile_version.token(),
        "experienceStateExists": result.experience is not None,
        "experienceVersion": (
            "none:0"
            if result.experience is None
            else result.experience.version.token()
        ),
        "changed": result.changed,
        "committed": result.committed,
        "experienceCommitted": result.experience_committed,
        "profileChanged": False,
        "replayed": result.replayed,
        "onboardingOffer": result.onboarding_offer,
        "proposalField": result.proposal_field,
        "warnings": [_warning_document(item) for item in result.warnings],
    }
    if result.proposal is not None and result.proposal_field is not None:
        document["proposal"] = _proposal_document(
            result.proposal_field, result.proposal
        )
    if result.reviewed_version is not None:
        document["reviewedVersion"] = result.reviewed_version.token()
    if result.backup_path is not None:
        document["backupPath"] = str(result.backup_path)
    return document


def _composite_mutation_document(
    operation: str,
    result: CompositeMutationResult,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "status": "ok",
        "operation": operation,
        **_state_fields(result.profile),
        "experienceSchemaVersion": 1,
        "experienceStateExists": result.experience_version is not None,
        "experienceVersion": (
            None
            if result.experience_version is None and result.warnings
            else (
                "none:0"
                if result.experience_version is None
                else result.experience_version.token()
            )
        ),
        "changed": result.changed,
        "committed": result.committed,
        "profileChanged": result.profile_changed,
        "experienceCommitted": result.experience_committed,
        "profile": result.profile.to_document(),
        "effectiveProfile": _effective_profile_document(
            result.effective_profile
        ),
        "warnings": [_warning_document(item) for item in result.warnings],
    }
    if result.backup_path is not None:
        document["backupPath"] = str(result.backup_path)
    return document


def _presentation_document(
    operation: str,
    presentation: ProfilePresentation,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "operation": operation,
        "personaId": presentation.persona_id,
        "personaName": presentation.persona_name,
        "labels": [
            {"field": field, "label": label, "value": value}
            for field, label, value in presentation.labels
        ],
        "summary": presentation.summary,
        "example": presentation.example,
        "exampleLabel": presentation.example_label,
    }


def _state_fields(profile: StoredProfile) -> dict[str, Any]:
    return {
        "profileExists": True,
        "schemaVersion": SCHEMA_VERSION,
        "version": profile.version.token(),
    }


def _mutation_document(
    operation: str,
    result: MutationResult,
) -> dict[str, Any]:
    document = {
        "status": "ok",
        "operation": operation,
        **_state_fields(result.profile),
        "changed": result.changed,
        "committed": result.committed,
        "profileChanged": (
            result.changed
            if result.profile_changed is None
            else result.profile_changed
        ),
        "experienceCommitted": (
            False
            if result.experience_committed is None
            else result.experience_committed
        ),
        "profile": result.profile.to_document(),
    }
    if result.experience_version is not None:
        document["experienceVersion"] = result.experience_version.token()
    if result.warnings:
        document["warnings"] = [_warning_document(item) for item in result.warnings]
    if result.backup_path is not None:
        document["backupPath"] = str(result.backup_path)
    return document


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UserProfileArgumentError("The command arguments are invalid.")


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        description="Manage the local ESS Maker Kit user profile."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("defaults")
    subparsers.add_parser("resolve")
    subparsers.add_parser("get")
    subparsers.add_parser("validate")
    subparsers.add_parser("initialize")

    set_parser = subparsers.add_parser("set")
    set_input = set_parser.add_mutually_exclusive_group(required=True)
    set_input.add_argument("--values-json")
    set_input.add_argument("--values-stdin", action="store_true")
    set_parser.add_argument("--expected-version", required=True)

    onboarding_parser = subparsers.add_parser("onboarding")
    onboarding_parser.add_argument(
        "--status",
        required=True,
        choices=[status.value for status in OnboardingStatus],
    )
    onboarding_parser.add_argument("--expected-version", required=True)

    propose_parser = subparsers.add_parser("propose")
    propose_parser.add_argument("--field", required=True)
    propose_input = propose_parser.add_mutually_exclusive_group(required=True)
    propose_input.add_argument("--value-json")
    propose_input.add_argument("--value-stdin", action="store_true")
    propose_parser.add_argument("--observation-count", type=int, required=True)
    propose_parser.add_argument("--confidence", type=float, required=True)
    propose_parser.add_argument("--expected-version", required=True)

    for operation in ("accept", "reject"):
        proposal_parser = subparsers.add_parser(operation)
        proposal_parser.add_argument("--field", required=True)
        proposal_parser.add_argument("--expected-version", required=True)

    reset_parser = subparsers.add_parser("reset")
    reset_parser.add_argument("--expected-version")
    reset_parser.add_argument("--recover", action="store_true")
    reset_parser.add_argument("--expected-content-hash")
    reset_parser.add_argument("--yes", action="store_true")

    for operation in ("onboarding-complete", "profile-save"):
        save_parser = subparsers.add_parser(operation)
        save_input = save_parser.add_mutually_exclusive_group(required=True)
        save_input.add_argument("--values-json")
        save_input.add_argument("--values-stdin", action="store_true")
        save_parser.add_argument("--expected-version", required=True)
        save_parser.add_argument("--yes", action="store_true")

    defer_parser = subparsers.add_parser("onboarding-defer")
    defer_parser.add_argument("--request-id", required=True)
    defer_parser.add_argument("--expected-version", required=True)

    suppress_parser = subparsers.add_parser("onboarding-suppress")
    suppress_parser.add_argument("--expected-version", required=True)
    suppress_parser.add_argument(
        "--expected-experience-version", required=True
    )
    suppress_parser.add_argument("--yes", action="store_true")

    snooze_parser = subparsers.add_parser("proposal-snooze")
    snooze_parser.add_argument("--field", required=True)
    snooze_parser.add_argument("--proposal-created-at", required=True)
    snooze_parser.add_argument("--expected-version", required=True)
    snooze_parser.add_argument(
        "--expected-experience-version", required=True
    )
    snooze_parser.add_argument(
        "--origin",
        choices=[origin.value for origin in PromptOrigin],
        required=True,
    )

    preview_parser = subparsers.add_parser("preview")
    preview_input = preview_parser.add_mutually_exclusive_group(required=True)
    preview_input.add_argument("--values-json")
    preview_input.add_argument("--values-stdin", action="store_true")

    experience_parser = subparsers.add_parser("experience")
    experience_subparsers = experience_parser.add_subparsers(
        dest="experience_operation",
        required=True,
    )
    experience_subparsers.add_parser("resolve")
    begin_parser = experience_subparsers.add_parser("begin")
    begin_parser.add_argument("--request-id", required=True)
    begin_parser.add_argument("--expected-version", required=True)
    begin_parser.add_argument(
        "--expected-experience-version", required=True
    )
    finish_parser = experience_subparsers.add_parser("finish")
    finish_parser.add_argument("--request-id", required=True)
    finish_parser.add_argument("--expected-version", required=True)
    finish_parser.add_argument(
        "--expected-experience-version", required=True
    )
    finish_parser.add_argument(
        "--outcome",
        choices=[outcome.value for outcome in TaskOutcome],
        required=True,
    )
    finish_parser.add_argument(
        "--allows-extra-content", action="store_true"
    )
    finish_parser.add_argument(
        "--optional-suggestion-used", action="store_true"
    )
    reconcile_parser = experience_subparsers.add_parser("reconcile")
    reconcile_parser.add_argument(
        "--expected-experience-version", required=True
    )
    experience_reset = experience_subparsers.add_parser("reset")
    experience_reset.add_argument("--expected-version", required=True)
    experience_reset.add_argument(
        "--expected-experience-version", required=True
    )
    experience_reset.add_argument("--yes", action="store_true")
    experience_recover = experience_subparsers.add_parser("recover")
    experience_recover.add_argument("--expected-content-hash", required=True)
    profile_precondition = experience_recover.add_mutually_exclusive_group(
        required=True
    )
    profile_precondition.add_argument("--expected-version")
    profile_precondition.add_argument("--expected-profile-content-hash")
    experience_recover.add_argument("--yes", action="store_true")
    return parser


def _parse_cli_json(text: str, *, object_required: bool) -> object:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (UserProfileValidationError, json.JSONDecodeError, ValueError) as exc:
        raise UserProfileArgumentError(
            "The JSON command input is invalid."
        ) from exc
    if object_required and not isinstance(value, dict):
        raise UserProfileArgumentError(
            "The JSON command input must be an object."
        )
    return value


def _command_document(
    args: argparse.Namespace,
    path: Path,
    stdin_text: str | None,
) -> dict[str, Any]:
    operation = args.operation
    experience_path = _experience_path_for_profile(path)
    if operation == "experience":
        suboperation = args.experience_operation
        command = f"experience {suboperation}"
        if suboperation == "resolve":
            result = resolve_experience(path, experience_path)
            profile = result.profile
            return {
                "status": "ok",
                "operation": command,
                "schemaVersion": SCHEMA_VERSION,
                "experienceSchemaVersion": 1,
                "profileExists": profile.profile_exists,
                "version": profile.version.token(),
                "effectiveProfile": _effective_profile_document(
                    profile.effective_profile
                ),
                "profile": (
                    None
                    if profile.profile is None
                    else profile.profile.to_document()
                ),
                "onboardingStatus": profile.onboarding_status.value,
                "pendingProposals": _pending_proposal_documents(
                    profile.pending_proposals
                ),
                "experienceStateExists": result.state_exists,
                "experienceVersion": (
                    None
                    if result.experience_version is None
                    else result.experience_version.token()
                ),
                "cadenceAvailable": result.cadence_available,
                "warnings": [
                    _warning_document(item) for item in result.warnings
                ],
            }
        if suboperation == "begin":
            result = begin_profile_request(
                path,
                experience_path,
                args.request_id,
                expected_profile_version=parse_profile_version(
                    args.expected_version
                ),
                expected_experience_version=parse_experience_version(
                    args.expected_experience_version
                ),
            )
            return _experience_mutation_document(command, result)
        if suboperation == "finish":
            result = finish_profile_request(
                path,
                experience_path,
                args.request_id,
                expected_profile_version=parse_profile_version(
                    args.expected_version
                ),
                expected_experience_version=parse_experience_version(
                    args.expected_experience_version
                ),
                outcome=TaskOutcome(args.outcome),
                allows_extra_content=args.allows_extra_content,
                optional_suggestion_used=args.optional_suggestion_used,
            )
            return _experience_mutation_document(command, result)
        if suboperation == "reconcile":
            result = reconcile_experience_state(
                path,
                experience_path,
                expected_experience_version=parse_experience_version(
                    args.expected_experience_version
                ),
            )
            return _experience_mutation_document(command, result)
        if suboperation == "reset":
            result = reset_experience_state(
                path,
                experience_path,
                expected_profile_version=parse_profile_version(
                    args.expected_version
                ),
                expected_experience_version=parse_experience_version(
                    args.expected_experience_version
                ),
                confirmed=args.yes,
            )
            return _experience_mutation_document(command, result)
        if suboperation == "recover":
            result = recover_experience_state(
                path,
                experience_path,
                expected_content_hash=args.expected_content_hash,
                expected_profile_version=(
                    None
                    if args.expected_version is None
                    else parse_profile_version(args.expected_version)
                ),
                expected_profile_content_hash=(
                    args.expected_profile_content_hash
                ),
                confirmed=args.yes,
            )
            return _experience_mutation_document(command, result)
    if operation == "onboarding-complete" or operation == "profile-save":
        raw = stdin_text if args.values_stdin else args.values_json
        assert raw is not None
        updates = _parse_cli_json(raw, object_required=True)
        parsed_updates = _parse_profile_updates(
            updates,
            allow_empty=operation == "onboarding-complete",
        )
        normalized_updates = {
            field: (
                {"value": value[0], "unit": value[1]}
                if field == "maximumResponseLength"
                else _json_value(value[0])
            )
            for field, value in parsed_updates.items()
        }
        result = complete_onboarding(
            path,
            experience_path,
            normalized_updates,
            expected_profile_version=parse_profile_version(
                args.expected_version
            ),
            confirmed=args.yes,
        )
        return _composite_mutation_document(operation, result)
    if operation == "onboarding-defer":
        result = defer_onboarding(
            path,
            experience_path,
            args.request_id,
            expected_profile_version=parse_profile_version(
                args.expected_version
            ),
        )
        return _composite_mutation_document(operation, result)
    if operation == "onboarding-suppress":
        result = suppress_onboarding_offer(
            path,
            experience_path,
            expected_profile_version=parse_profile_version(
                args.expected_version
            ),
            expected_experience_version=parse_experience_version(
                args.expected_experience_version
            ),
            confirmed=args.yes,
        )
        return _experience_mutation_document(operation, result)
    if operation == "proposal-snooze":
        result = snooze_proposal_prompt(
            path,
            experience_path,
            args.field,
            args.proposal_created_at,
            expected_profile_version=parse_profile_version(
                args.expected_version
            ),
            expected_experience_version=parse_experience_version(
                args.expected_experience_version
            ),
            origin=PromptOrigin(args.origin),
        )
        return _experience_mutation_document(operation, result)
    if operation == "preview":
        raw = stdin_text if args.values_stdin else args.values_json
        assert raw is not None
        values = _parse_cli_json(raw, object_required=True)
        return _presentation_document(
            operation, preview_profile(values)
        )
    if operation == "defaults":
        return {
            "status": "ok",
            "operation": "defaults",
            "schemaVersion": SCHEMA_VERSION,
            "effectiveProfile": _effective_profile_document(
                default_effective_profile()
            ),
        }
    if operation == "resolve":
        result = resolve_profile(path)
        return {
            "status": "ok",
            "operation": "resolve",
            "profileExists": result.profile_exists,
            "schemaVersion": SCHEMA_VERSION,
            "version": result.version.token(),
            "onboardingStatus": result.onboarding_status.value,
            "effectiveProfile": _effective_profile_document(
                result.effective_profile
            ),
            "pendingProposals": _pending_proposal_documents(
                result.pending_proposals
            ),
        }
    if operation == "get":
        profile = load_profile(path)
        return {
            "status": "ok",
            "operation": "get",
            **_state_fields(profile),
            "profile": profile.to_document(),
        }
    if operation == "validate":
        profile = load_profile(path)
        return {
            "status": "ok",
            "operation": "validate",
            **_state_fields(profile),
        }
    if operation == "initialize":
        return _mutation_document(operation, initialize_profile(path))

    if operation == "set":
        raw = stdin_text if args.values_stdin else args.values_json
        assert raw is not None
        updates = _parse_cli_json(raw, object_required=True)
        return _mutation_document(
            operation,
            set_preferences(
                path,
                updates,
                expected_version=parse_profile_version(
                    args.expected_version
                ),
            ),
        )
    if operation == "onboarding":
        return _mutation_document(
            operation,
            set_onboarding_status(
                path,
                OnboardingStatus(args.status),
                expected_version=parse_profile_version(
                    args.expected_version
                ),
            ),
        )
    if operation == "propose":
        raw = stdin_text if args.value_stdin else args.value_json
        assert raw is not None
        value = _parse_cli_json(raw, object_required=False)
        return _mutation_document(
            operation,
            propose_preference(
                path,
                args.field,
                value,
                args.observation_count,
                args.confidence,
                expected_version=parse_profile_version(
                    args.expected_version
                ),
            ),
        )
    if operation in {"accept", "reject"}:
        function = accept_proposal if operation == "accept" else reject_proposal
        return _mutation_document(
            operation,
            function(
                path,
                args.field,
                expected_version=parse_profile_version(
                    args.expected_version
                ),
            ),
        )
    if operation == "reset":
        if args.recover:
            if args.expected_version or not args.expected_content_hash:
                raise UserProfileArgumentError(
                    "Recovery reset arguments are invalid."
                )
            result = recover_profile(
                path,
                expected_content_hash=args.expected_content_hash,
                confirmed=args.yes,
            )
        else:
            if args.expected_content_hash or not args.expected_version:
                raise UserProfileArgumentError(
                    "Normal reset arguments are invalid."
                )
            result = reset_profile(
                path,
                expected_version=parse_profile_version(
                    args.expected_version
                ),
                confirmed=args.yes,
            )
        return _mutation_document(operation, result)
    raise UserProfileArgumentError("The requested operation is not supported.")


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(SOLUTION_ROOT))
    except ValueError:
        return str(path)


def _warning_document(warning: ExperienceWarning) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": warning.status,
        "error": warning.error,
        "path": warning.path,
    }
    if warning.content_hash is not None:
        result["contentHash"] = warning.content_hash
    return result


def _error_document(
    operation: str | None,
    error: UserProfileError,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "status": error.status,
        "operation": operation,
        "error": str(error),
        "committed": error.committed,
    }
    if error.path is not None:
        document["path"] = _display_path(error.path)
    if error.content_hash is not None:
        document["contentHash"] = error.content_hash
    if error.version is not None:
        document["version"] = error.version.token()
    if error.profile_changed is not None:
        document["profileChanged"] = error.profile_changed
    if error.experience_committed is not None:
        document["experienceCommitted"] = error.experience_committed
    if error.reconciliation_required:
        document["reconciliationRequired"] = True
    if isinstance(error, UserProfileConflictError):
        if error.expected_version is not None:
            document["expectedVersion"] = error.expected_version.token()
        if error.actual_version is not None:
            document["actualVersion"] = error.actual_version.token()
        if error.expected_content_hash is not None:
            document["expectedContentHash"] = error.expected_content_hash
        if error.actual_content_hash is not None:
            document["actualContentHash"] = error.actual_content_hash
    if isinstance(error, UserProfileExperienceConflictError):
        document["resource"] = error.resource
        if error.expected_experience_version is not None:
            document["expectedExperienceVersion"] = (
                error.expected_experience_version.token()
            )
        if error.actual_experience_version is not None:
            document["actualExperienceVersion"] = (
                error.actual_experience_version.token()
            )
        if error.expected_content_hash is not None:
            document["expectedContentHash"] = error.expected_content_hash
        if error.actual_content_hash is not None:
            document["actualContentHash"] = error.actual_content_hash
    return document


def main(
    argv: list[str] | None = None,
    *,
    path: Path | None = None,
    stdin_text: str | None = None,
) -> int:
    if argv is None:
        import sys

        arguments = sys.argv[1:]
    else:
        arguments = list(argv)
    operation: str | None = None
    if arguments:
        operation = arguments[0] if arguments[0] in {
            "defaults",
            "resolve",
            "get",
            "validate",
            "initialize",
            "set",
            "onboarding",
            "propose",
            "accept",
            "reject",
            "reset",
        } else None
    try:
        args = build_parser().parse_args(arguments)
        operation = args.operation
        if args.operation == "experience":
            operation = f"experience {args.experience_operation}"
        needs_stdin = (
            getattr(args, "values_stdin", False)
            or getattr(args, "value_stdin", False)
        )
        if needs_stdin and stdin_text is None:
            import sys

            stdin_text = sys.stdin.read()
        document = _command_document(
            args,
            DEFAULT_PROFILE_PATH if path is None else Path(path),
            stdin_text,
        )
        exit_code = 0
    except UserProfileError as exc:
        document = _error_document(operation, exc)
        exit_code = exc.exit_code
    print(
        json.dumps(
            document,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
