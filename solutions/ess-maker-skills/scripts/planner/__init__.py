# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner (Step 1).

The ``/planner`` skill authors a local, structured **Plan** for an ESS rollout:
it researches Microsoft Learn to ground what ESS supports, interviews the
sponsor, emits atomic Tasks (each assigned by a Learn-grounded role, then to a
person), and captures what each Task produces onto the Plan.

Public surface:

  * :mod:`planner.plan_model` — the Plan document (schema, atomic IO,
    validation, summary render, Flow-2 grouping).
  * :mod:`planner.roles` — the absent-safe roles-source seam (``RoleDirectory``
    over the ``RoleSource`` protocol).
  * :mod:`planner.capture` — observe-mode detectors that read what a Task
    produced from local kit state (the generic ``/setup`` config.json capture —
    environment, agent, and any other id+name a skill recorded).
  * :mod:`planner.research` — the Table-of-Contents-first Learn research
    selection logic (parse ``toc.json`` -> relevance-select hrefs to fetch).

Everything is local-first and pure/local-IO — no WeveNova, tenant inventory,
or roles source is required for the Plan to work.
"""

from __future__ import annotations

from .plan_model import Plan, Limits, SCHEMA_VERSION

__all__ = ["Plan", "Limits", "SCHEMA_VERSION"]
