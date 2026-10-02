# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Warning policy and module isolation regressions for the MCP test loader."""

from __future__ import annotations

import sys
import warnings
from types import ModuleType
from uuid import uuid4

import pytest
from pydantic_settings.exceptions import IncompleteFieldDefinitionWarning

from tests.mcp._mcp_modules import load_mcp_modules


@pytest.fixture
def temporary_module(tmp_path):
    name = f"mcp_warning_test_{uuid4().hex}"
    alias_prefix = f"mcp_warning_alias_{uuid4().hex}"
    assert name not in sys.modules
    assert f"{alias_prefix}.{name}" not in sys.modules
    try:
        yield tmp_path, name, alias_prefix
    finally:
        sys.modules.pop(f"{alias_prefix}.{name}", None)
        sys.modules.pop(name, None)


@pytest.mark.parametrize("plain_binding_exists", [False, True])
@pytest.mark.parametrize("policy", ["always", "error"])
@pytest.mark.parametrize(
    "category", [IncompleteFieldDefinitionWarning, UserWarning, RuntimeWarning]
)
def test_loader_preserves_unrelated_warning_policy_and_module_bindings(
    temporary_module, plain_binding_exists, policy, category,
) -> None:
    directory, name, alias_prefix = temporary_module
    alias = f"{alias_prefix}.{name}"
    previous = ModuleType(name)
    if plain_binding_exists:
        sys.modules[name] = previous
    (directory / f"{name}.py").write_text(
        "import warnings\n"
        "from pydantic_settings.exceptions import IncompleteFieldDefinitionWarning\n"
        f"warnings.warn('module execution warning', {category.__name__})\n"
        "executed = True\n",
        encoding="utf-8",
    )
    suppressed = category is IncompleteFieldDefinitionWarning
    raises = policy == "error" and not suppressed

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter(policy)
        caller_filters = warnings.filters
        original_filters = caller_filters[:]

        if raises:
            with pytest.raises(category, match="module execution warning"):
                load_mcp_modules(directory, [name], alias_prefix)
            assert alias not in sys.modules
        else:
            loaded = load_mcp_modules(directory, [name], alias_prefix)
            assert loaded[name].executed is True
            assert sys.modules[alias] is loaded[name]
            assert load_mcp_modules(directory, [name], alias_prefix)[name] is loaded[name]

        assert warnings.filters is caller_filters
        assert warnings.filters == original_filters
        if plain_binding_exists:
            assert sys.modules[name] is previous
        else:
            assert name not in sys.modules
        if suppressed or raises:
            assert recorded == []
        else:
            assert len(recorded) == 1
            assert recorded[0].category is category
            assert str(recorded[0].message) == "module execution warning"

        # The targeted exception must also stay scoped to module execution.
        if policy == "error":
            with pytest.raises(IncompleteFieldDefinitionWarning):
                warnings.warn("caller warning", IncompleteFieldDefinitionWarning)
        else:
            warnings.warn("caller warning", IncompleteFieldDefinitionWarning)
            assert recorded[-1].category is IncompleteFieldDefinitionWarning
