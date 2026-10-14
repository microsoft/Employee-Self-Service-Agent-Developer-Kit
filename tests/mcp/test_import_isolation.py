# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Guards for collision-free imports of the sibling MCP servers.

The sibling servers under ``src/mcp`` are flat folders that both define
top-level ``client``/``server`` modules. Under a whole-suite run the first one
imported wins ``sys.modules`` and every later suite silently gets the wrong
module — the failure surfaces as an ``AttributeError`` on a name that does
exist, in a different file, which is very hard to read as an import problem.

These tests pin the isolation itself so it cannot regress into that state.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _mcp_modules import (  # noqa: E402
    load_landing_page_modules,
    load_org_announcements_modules,
)


def test_both_servers_load_with_their_own_client_module() -> None:
    landing = load_landing_page_modules()
    org = load_org_announcements_modules()

    assert landing["client"] is not org["client"]
    assert hasattr(landing["client"], "AgentConfigClient")
    assert hasattr(org["client"], "OrgAnnouncementsClient")
    # Each server bound the client that sits next to it, not its sibling's.
    assert not hasattr(landing["client"], "OrgAnnouncementsClient")
    assert not hasattr(org["client"], "AgentConfigClient")


def test_each_server_binds_the_client_from_its_own_directory() -> None:
    """``server.py`` does a plain ``from client import ...`` at runtime."""
    landing = load_landing_page_modules()
    org = load_org_announcements_modules()

    assert Path(landing["server"].__file__).parent == Path(
        landing["client"].__file__
    ).parent
    assert Path(org["server"].__file__).parent == Path(org["client"].__file__).parent
    assert (
        Path(landing["server"].__file__).parent
        != Path(org["server"].__file__).parent
    )


def test_loading_is_idempotent_and_returns_the_same_modules() -> None:
    """Monkeypatching in one test module must be visible in another."""
    first = load_org_announcements_modules()
    second = load_org_announcements_modules()

    for name, module in first.items():
        assert second[name] is module


def test_loading_leaves_no_plain_sibling_name_behind() -> None:
    """The plain names are shadowed only for the duration of the load."""
    before = {
        name: sys.modules.get(name)
        for name in ("client", "server", "drafts", "graph_directory_client")
    }

    load_landing_page_modules()
    load_org_announcements_modules()

    for name, previous in before.items():
        assert sys.modules.get(name) is previous, name


def test_the_whole_mcp_tree_collects_in_either_order() -> None:
    """Import-order independence, proven by compiling every suite together.

    A plain ``import client`` anywhere in these suites reintroduces the
    collision, so this asserts the source shape rather than re-running pytest
    (which the harness cannot nest).
    """
    suites = sorted((REPO_ROOT / "tests" / "mcp").rglob("test_*.py"))
    assert suites, "no MCP test modules found"

    for suite in suites:
        source = suite.read_text(encoding="utf-8")
        for forbidden in (
            "\nimport client",
            "\nimport server",
            "\nimport drafts",
            "\nimport graph_directory_client",
            "\nfrom client import",
            "\nfrom server import",
            "\nfrom graph_directory_client import",
        ):
            assert forbidden not in source, (
                f"{suite.relative_to(REPO_ROOT)} imports a top-level MCP module "
                f"directly ({forbidden.strip()}); use _mcp_modules instead"
            )


def test_the_suites_run_clean_in_a_single_interpreter() -> None:
    """Both servers imported into one process must stay distinct.

    Reproduces the real whole-suite condition in a subprocess so a regression
    that only appears when both are loaded is caught here.
    """
    probe = (
        "import sys; sys.path.insert(0, %r);"
        "from _mcp_modules import load_landing_page_modules, "
        "load_org_announcements_modules;"
        "a = load_landing_page_modules(); b = load_org_announcements_modules();"
        "assert a['client'] is not b['client'];"
        "assert hasattr(b['client'], 'OrgAnnouncementsClient');"
        "assert hasattr(a['client'], 'AgentConfigClient');"
        "print('ok')" % str(REPO_ROOT / "tests" / "mcp")
    )
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
