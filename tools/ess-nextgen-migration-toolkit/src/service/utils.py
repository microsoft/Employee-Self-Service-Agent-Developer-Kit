"""Shared helper functions for the ESS Migration Toolkit."""

from __future__ import annotations

from service.constants import ESS_SOLUTION_BY_VERTICAL


def resolve_ess_solution(agent_schemaname: str) -> str | None:
    """Return the ESS base solution unique name for an agent schemaname.

    The vertical is the trailing ``hr``/``it`` suffix of the agent schemaname
    (e.g. ``msdyn_copilotforemployeeselfservicehr`` -> ``hr``).
    """
    schema = agent_schemaname.lower()
    for vertical, solution in ESS_SOLUTION_BY_VERTICAL.items():
        if schema.endswith(vertical):
            return solution
    return None
