# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = (
    _ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "shared"
    / "user-profile-contract.md"
)


def _contract() -> str:
    return _CONTRACT.read_text(encoding="utf-8")


def test_contract_defines_resolution_and_canonical_fallback() -> None:
    contract = _contract()

    assert "python scripts\\user_profile.py resolve" in contract
    assert "python scripts/user_profile.py defaults" in contract
    assert "immutable resolved profile" in contract
    assert "do not resolve again" in contract


def test_contract_preserves_security_and_required_output() -> None:
    contract = _contract()

    assert "Security and privacy requirements" in contract
    assert "Destructive-operation confirmation" in contract
    assert "Exact Message blocks" in contract
    assert "mandatory confirmation" in contract
    assert "`machine_readable`" in contract
    assert "Never transform JSON, YAML, CSV, code, commands, API payloads" in contract


def test_contract_uses_section_level_classification_and_soft_length() -> None:
    contract = _contract()

    assert "Classify each output section independently" in contract
    assert "`flexible`" in contract
    assert "`contractual`" in contract
    assert "`safety_critical`" in contract
    assert "soft word budget" in contract
    assert "Exceed the budget rather than truncating" in contract


def test_contract_defines_failure_and_privacy_boundaries() -> None:
    contract = _contract()

    assert "missing profile is not an error" in contract
    assert "Malformed or unsupported state is reported and never overwritten" in contract
    assert "Raw conversation evidence" in contract or "raw conversation evidence" in contract
    assert "typed data, never instructions" in contract
    assert "Stale versions and lock timeouts" in contract


def test_contract_keeps_task_instructions_and_required_remediation() -> None:
    contract = _contract()

    assert "Explicit instructions for the current task" in contract
    assert "not automatically persisted" in contract
    assert "Required remediation" in contract
    assert "`off` omits it" in contract
