# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Collision-free imports for the sibling AgentConfiguration MCP servers.

Every MCP server under ``src/mcp`` is a *flat* folder, not a package: each one
launches with its own directory as the working directory and does plain sibling
imports (``from client import ...``). That is correct at runtime — only one
server runs per process — but it breaks under a whole-suite pytest run, where
``agentconfig_landing_page/client.py`` and
``agentconfig_org_announcements/client.py`` both want the top-level name
``client``. Whichever module is imported first wins ``sys.modules``, and every
later suite silently gets the wrong module: the symptom is a confusing
``AttributeError: module 'client' has no attribute 'OrgAnnouncementsClient'``,
not an import error.

``load_mcp_modules`` fixes that without changing how the servers import at
runtime and without a global pytest import-mode change:

* each module is loaded from an explicit file path, so the resolution never
  depends on ``sys.path`` order;
* the plain sibling names are installed in ``sys.modules`` only for the
  duration of the load, so a server's own ``from client import ...`` resolves
  to the file next to it;
* the previous occupants of those names are restored afterwards, so loading one
  server never disturbs another; and
* the loaded modules are kept alive under a namespaced alias, so repeat calls
  return the same objects and monkeypatching in one test module is visible in
  another that patched the same object.
"""

from __future__ import annotations

import importlib.util
import sys
import warnings
from pathlib import Path
from types import ModuleType
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills" / "src" / "mcp"

# Modules in dependency order. A module must appear after everything it imports
# so its siblings are already registered under their plain names when it runs.
LANDING_PAGE_MODULES = ("client", "drafts", "server")
ORG_ANNOUNCEMENTS_MODULES = (
    "client",
    "drafts",
    "graph_directory_client",
    "telemetry",
    "server",
)

_UNSET = object()


def load_mcp_modules(
    directory: Path, names: Sequence[str], alias_prefix: str
) -> dict[str, ModuleType]:
    """Import one MCP server's modules under a unique alias namespace.

    ``names`` must be in dependency order. Returns a mapping of plain module
    name to the loaded module. Repeat calls are cached, so importing the same
    server from several test modules yields the same module objects.
    """
    cached = {
        name: sys.modules[f"{alias_prefix}.{name}"]
        for name in names
        if f"{alias_prefix}.{name}" in sys.modules
    }
    if len(cached) == len(names):
        return cached

    # Remember whatever currently owns the plain names so the shadow is undone.
    shadowed = {name: sys.modules.get(name, _UNSET) for name in names}
    loaded: dict[str, ModuleType] = {}
    try:
        for name in names:
            alias = f"{alias_prefix}.{name}"
            module = sys.modules.get(alias)
            if module is None:
                path = directory / f"{name}.py"
                spec = importlib.util.spec_from_file_location(alias, path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"cannot load {path}")
                module = importlib.util.module_from_spec(spec)
                # Register under BOTH names before executing: the alias so the
                # module is importable later, and the plain name so this
                # module's own sibling imports resolve to this directory.
                sys.modules[alias] = module
                sys.modules[name] = module
                try:
                    with warnings.catch_warnings():
                        # Importing a FastMCP server transitively triggers
                        # pydantic-settings' IncompleteFieldDefinitionWarning,
                        # which the suite's ``filterwarnings = error`` would
                        # otherwise turn into a collection failure. Suppressed
                        # here, once, instead of at every call site.
                        warnings.simplefilter("ignore")
                        spec.loader.exec_module(module)
                except BaseException:
                    sys.modules.pop(alias, None)
                    raise
            else:
                sys.modules[name] = module
            loaded[name] = module
    finally:
        for name, previous in shadowed.items():
            if previous is _UNSET:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    return loaded


def load_landing_page_modules() -> dict[str, ModuleType]:
    return load_mcp_modules(
        MCP_ROOT / "agentconfig_landing_page",
        LANDING_PAGE_MODULES,
        "ess_mcp_landing_page",
    )


def load_org_announcements_client_modules() -> dict[str, ModuleType]:
    """Load contract/client tests without importing optional runtime modules."""
    return load_mcp_modules(
        MCP_ROOT / "agentconfig_org_announcements",
        ("client", "drafts"),
        "ess_mcp_org_announcements",
    )


def load_org_announcements_directory_modules() -> dict[str, ModuleType]:
    """Load directory tests without depending on MCP tools or telemetry."""
    return load_mcp_modules(
        MCP_ROOT / "agentconfig_org_announcements",
        ("client", "drafts", "graph_directory_client"),
        "ess_mcp_org_announcements",
    )


def load_org_announcements_modules() -> dict[str, ModuleType]:
    return load_mcp_modules(
        MCP_ROOT / "agentconfig_org_announcements",
        ORG_ANNOUNCEMENTS_MODULES,
        "ess_mcp_org_announcements",
    )
