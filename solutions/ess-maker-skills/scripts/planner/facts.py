# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: non-Learn planning facts.

``planner_facts.json`` holds the few facts the planner needs that are **not**
discoverable on Microsoft Learn and are **not** a business-scenario catalogue.
Per the PM spec (FR-1/FR-3), the business scenarios themselves come from the
maker's own description grounded in Microsoft Learn — they are never enumerated
here. This module only exposes:

  * :func:`scenario_dependency_edges` — dependency edges between two scenarios
    (e.g. ``hr-ticketing requires hr-knowledge``), applied only when the maker
    puts both scenarios in scope. Each edge carries an explicit ``source``.
  * :func:`role_lexicon` / :func:`output_lexicon` — a small recognition
    vocabulary used to *spot* roles/outputs when reading Learn pages. The
    lexicon does not define the roles/outputs; those are read off the page.

Pure local-file IO; no network. Best-effort: a missing or corrupt file yields
empty results so a read never fails.
"""

from __future__ import annotations

import json
import os
from typing import Any

FACTS_PATH = os.path.join(os.path.dirname(__file__), "planner_facts.json")


def load_facts(path: str | os.PathLike[str] = FACTS_PATH) -> dict[str, Any]:
    """Load the facts JSON best-effort; ``{}`` if missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def scenario_dependency_edges(
    path: str | os.PathLike[str] = FACTS_PATH,
) -> list[dict[str, str]]:
    """The known scenario-dependency edges.

    Each edge is ``{scenario, dependsOn, kind, rationale, source}``. These are
    *not* a scenario list — they only take effect when the maker independently
    puts both ``scenario`` and ``dependsOn`` in scope.
    """
    edges: list[dict[str, str]] = []
    for dep in load_facts(path).get("scenarioDependencies", []) or []:
        if not isinstance(dep, dict):
            continue
        scenario = dep.get("scenario", "")
        depends_on = dep.get("dependsOn", "")
        if not scenario or not depends_on:
            continue
        edges.append(
            {
                "scenario": scenario,
                "dependsOn": depends_on,
                "kind": dep.get("kind", "requires"),
                "rationale": dep.get("rationale", ""),
                "source": dep.get("source", ""),
            }
        )
    return edges


def _lexicon(name: str, path: str | os.PathLike[str] = FACTS_PATH) -> list[str]:
    recognition = load_facts(path).get("recognition", {})
    if not isinstance(recognition, dict):
        return []
    values = recognition.get(name, [])
    return [v for v in values if isinstance(v, str)] if isinstance(values, list) else []


def role_lexicon(path: str | os.PathLike[str] = FACTS_PATH) -> list[str]:
    """Role phrases used to recognise a role while reading a Learn page."""
    return _lexicon("roles", path)


def output_lexicon(path: str | os.PathLike[str] = FACTS_PATH) -> list[str]:
    """Output/artifact nouns used to recognise an output while reading a page."""
    return _lexicon("outputs", path)
