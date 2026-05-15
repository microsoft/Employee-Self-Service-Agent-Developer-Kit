# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Sanity tests for the mock-validation policy.

Verifies that:

1. Every module in tests/mocks/ declares MOCK_STATUS.
2. The MOCK_STATUS values are all in the allowed set.
3. Validated modules cite a real cassette file that exists on disk.
4. Validatable modules cite a public schema source URL.
5. require_validated_mock() correctly accepts the three usable tiers
   and rejects placeholder / undeclared.

These are the rails that prevent agents from sneaking placeholder mocks
into integration tests.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

import tests.mocks
from tests.conftest import require_validated_mock

ALLOWED_STATUS = {"validated", "validatable", "documented", "placeholder"}
USABLE_IN_FLIGHTCHECK = {"validated", "validatable", "documented"}

REPO_ROOT = Path(__file__).resolve().parents[1]


def _all_mock_modules() -> list:
    """Discover every Python module under tests.mocks."""
    return [
        importlib.import_module(f"tests.mocks.{m.name}")
        for m in pkgutil.iter_modules(tests.mocks.__path__)
        if not m.name.startswith("_")
    ]


class TestMockModuleConvention:
    @pytest.mark.parametrize("mod", _all_mock_modules(), ids=lambda m: m.__name__)
    def test_declares_mock_status(self, mod) -> None:
        assert hasattr(mod, "MOCK_STATUS"), (
            f"{mod.__name__} is missing MOCK_STATUS — every mock module "
            "must declare its validation state. See tests/mocks/README.md."
        )

    @pytest.mark.parametrize("mod", _all_mock_modules(), ids=lambda m: m.__name__)
    def test_mock_status_value_is_valid(self, mod) -> None:
        assert mod.MOCK_STATUS in ALLOWED_STATUS, (
            f"{mod.__name__} declares MOCK_STATUS={mod.MOCK_STATUS!r} but "
            f"only {sorted(ALLOWED_STATUS)} are allowed."
        )

    @pytest.mark.parametrize("mod", _all_mock_modules(), ids=lambda m: m.__name__)
    def test_validated_modules_cite_existing_cassette(self, mod) -> None:
        if mod.MOCK_STATUS != "validated":
            pytest.skip("only validated modules require a cassette citation")
        cassette = getattr(mod, "MOCK_CASSETTE", None)
        assert cassette, (
            f"{mod.__name__} is MOCK_STATUS='validated' but does not set "
            "MOCK_CASSETTE pointing at the backing cassette."
        )
        path = REPO_ROOT / cassette
        assert path.exists(), (
            f"{mod.__name__} cites cassette {cassette!r} but the file "
            f"does not exist at {path}. Either add the cassette or "
            "re-tier the module."
        )

    @pytest.mark.parametrize("mod", _all_mock_modules(), ids=lambda m: m.__name__)
    def test_validatable_modules_cite_schema_source(self, mod) -> None:
        if mod.MOCK_STATUS != "validatable":
            pytest.skip("only validatable modules require MOCK_SCHEMA_SOURCE")
        source = getattr(mod, "MOCK_SCHEMA_SOURCE", None)
        assert source, (
            f"{mod.__name__} is MOCK_STATUS='validatable' but does not "
            "set MOCK_SCHEMA_SOURCE pointing at the public schema URL "
            "(e.g. https://graph.microsoft.com/v1.0/$metadata)."
        )
        assert source.startswith("https://"), (
            f"{mod.__name__} MOCK_SCHEMA_SOURCE={source!r} should be an "
            "https:// URL to a publicly-fetchable schema."
        )


class TestRequireValidatedMock:
    def test_accepts_validated(self) -> None:
        from tests.mocks import pp_admin as pp
        # pp_admin is MOCK_STATUS='validated' (cassette-backed)
        require_validated_mock(pp)

    def test_accepts_validatable(self) -> None:
        from tests.mocks import graph as g
        # graph is MOCK_STATUS='validatable' (Graph CSDL-backed)
        require_validated_mock(g)

    def test_accepts_documented(self) -> None:
        from tests.mocks import dataverse as dv
        # dataverse is MOCK_STATUS='documented' (MS Learn doc-backed)
        require_validated_mock(dv)

    def test_rejects_placeholder(self) -> None:
        from tests.mocks import workday as wd

        with pytest.raises(pytest.fail.Exception) as exc_info:
            require_validated_mock(wd)
        assert "PLACEHOLDER" in str(exc_info.value)
        assert "tests/AGENTS.md" in str(exc_info.value)

    def test_rejects_module_without_mock_status(self, tmp_path) -> None:
        # Build a fake module on the fly that has no MOCK_STATUS.
        import types

        fake = types.ModuleType("fake_mock_no_status")
        with pytest.raises(pytest.fail.Exception) as exc_info:
            require_validated_mock(fake)
        assert "does not declare MOCK_STATUS" in str(exc_info.value)
