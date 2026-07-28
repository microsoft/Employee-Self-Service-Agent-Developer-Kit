# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Drift guard for the FlightCheck single-checkpoint registry.

Pure-logic, no network (see ``tests/AGENTS.md`` — pure-logic helpers are
exempt from the cassette rule). Statically scans every check module's source
for the checkpoint IDs it emits and asserts that the registry covers every
**setup-owned** ID. This catches an added or renamed setup checkpoint that
nobody registered, so ``--list-checkpoints`` / ``--checkpoint`` never silently
drift from what the setup category functions actually emit.

It is deliberately **scoped, not** a global ``registry ⊇ all-emitted``
assertion. Resolution is the registry's OWN resolution (exact entry first,
then longest-prefix family). For each emitted ID:

* resolves            -> pass
* does NOT resolve AND its prefix is in ``OWNED_PREFIXES`` -> FAIL
  (a setup checkpoint nobody registered)
* does NOT resolve AND outside the allow-list -> ignore
  (another integration's checkpoint — ``SN-*``, ``EXT-*``, ``SAP-*``, the
  pre-existing ``ENV-003`` / ``ENV-004`` rows, etc. — validated via ``--scope``)

We never blanket-strip a trailing ``-\\d+`` (that would fabricate bogus
families and mis-bucket fixed IDs like ``WD-CONN-012`` or ``WD-REST-001``).
The runner's synthetic ``{CAT}-ERR`` sentinels are not emitted by check
modules, so they never appear here; we skip them defensively anyway.
"""

from __future__ import annotations

import glob
import os
import re

import flightcheck.checks as _checks_pkg
from flightcheck import registry
from flightcheck.registry import OWNED_PREFIXES


# checkpoint_id= / cid = / cp_id = "LITERAL-ID" (literal or f-string with no
# interpolation in the captured span). Requires at least one hyphen group so we
# only match hyphenated upper-case checkpoint identifiers, never arbitrary
# strings.
_LITERAL = re.compile(
    r'(?:checkpoint_id|cid|cp_id)\s*=\s*(?:f)?"([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)"'
)
# checkpoint_id= / cid = / cp_id = f"PREFIX-{...}" — capture the static prefix
# (including its trailing hyphen) of a dynamically-numbered family.
_FPREFIX = re.compile(
    r'(?:checkpoint_id|cid|cp_id)\s*=\s*f"([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-)\{'
)
# checkpoint_prefix="WD-CONN" — the generic connection enumerator
# (connections.py) builds "{checkpoint_prefix}-001" + per-connection rows; the
# concrete prefix lives at the call site.
_CPREFIX = re.compile(r'checkpoint_prefix\s*=\s*"([A-Z][A-Z0-9-]*)"')


def _harvest_emitted_ids() -> set[str]:
    """Scan every checks/*.py module and return the set of emitted checkpoint
    IDs / family prefixes (family prefixes keep their trailing hyphen)."""
    checks_dir = os.path.dirname(_checks_pkg.__file__)
    tokens: set[str] = set()
    for path in glob.glob(os.path.join(checks_dir, "*.py")):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        tokens.update(_LITERAL.findall(text))
        tokens.update(_FPREFIX.findall(text))
        tokens.update(_CPREFIX.findall(text))
    return tokens


def _probe(token: str) -> str:
    """Normalise a harvested token to a registry resolution probe: strip a
    trailing hyphen from a family prefix (``"WD-FLOW-"`` -> ``"WD-FLOW"``)."""
    return token[:-1] if token.endswith("-") else token


def _is_owned(probe: str) -> bool:
    """True if the probe falls under a setup-owned prefix, using a hyphen
    boundary so ``ENV-001`` does not swallow ``ENV-0010`` and ``WD-ENV`` does
    not match ``WD-ENVX``."""
    return any(
        probe == prefix or probe.startswith(prefix + "-")
        for prefix in OWNED_PREFIXES
    )


class TestRegistryDrift:
    def test_harvest_finds_known_ids(self):
        # Sanity: the scan must actually find the obvious setup IDs, otherwise
        # a broken regex would make the drift guard vacuously pass.
        tokens = _harvest_emitted_ids()
        assert "WD-PKG-001" in tokens
        assert "ENV-001" in tokens
        assert "WD-FLOW-" in tokens  # f-string family prefix
        assert "WD-CONN" in tokens   # checkpoint_prefix kwarg

    def test_no_owned_setup_checkpoint_is_unregistered(self):
        failures = []
        for token in sorted(_harvest_emitted_ids()):
            if token.endswith("-ERR"):
                continue  # runner error sentinel, never a real checkpoint
            probe = _probe(token)
            if registry.resolve(probe) is not None:
                continue  # registered (exact or family) — good
            if _is_owned(probe):
                failures.append(token)
        assert not failures, (
            "Setup-owned checkpoint(s) are emitted but not registered in "
            "flightcheck/registry.py (add an exact entry or family): "
            f"{failures}. If a checkpoint genuinely belongs to another "
            "integration, it must not use an owned prefix."
        )

    def test_non_owned_ids_are_ignored_not_failed(self):
        # IDs from other integrations must NOT be flagged even though they don't
        # resolve in the setup registry — they are validated via --scope.
        for foreign in ("SN-CONN-003", "EXT-002-ACL", "SAP-001",
                        "ENV-004-OR-001", "ENV-009", "AUTH-005"):
            assert registry.resolve(_probe(foreign)) is None
            assert not _is_owned(_probe(foreign)), (
                f"{foreign} should be outside the owned allow-list"
            )

    def test_fixed_ids_not_mis_bucketed_by_numeric_strip(self):
        # Guard the "never blanket-strip -\d+" rule: these fixed IDs must
        # resolve to their own identity (exact or correct family), never to a
        # fabricated family invented by truncating the numeric suffix.
        assert registry.resolve("WD-CONN-012").key == "WD-CONN-012"  # exact
        assert registry.resolve("ENV-001").key == "ENV-001"          # exact
        # TOPIC-TRIGGER-001 / TOPIC-INTEGRATION-002 resolve to their registered
        # skill-6 families — the correct family, not one fabricated by stripping
        # the numeric suffix.
        assert registry.resolve("TOPIC-TRIGGER-001").key == "TOPIC-TRIGGER"
        assert registry.resolve("TOPIC-INTEGRATION-002").key == "TOPIC-INTEGRATION"
        assert _is_owned("TOPIC-TRIGGER-001") is True
        # A numeric-suffixed ID whose prefix is neither an exact entry nor a
        # registered family must still return None (no fabricated family).
        assert registry.resolve("ZZZ-001") is None
