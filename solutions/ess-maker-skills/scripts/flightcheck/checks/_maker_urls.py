# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared deep-link builders for the Power Platform maker portals.

Multiple FlightCheck checks emit remediation strings that point the user
at the place in the maker portal where a problem can be fixed. Several
of these strings used to be hand-written per check, which meant they
drifted (different hosts, different paths, inconsistent encoding). This
module is the single source of truth so every remediation links to the
same URL shape for the same operator action.

Consumers:
  * ENV-004 (``checks/environment._check_connections_and_refs``):
    re-bind orphan/unbound connection references and clean up unbound
    connections.
  * WD-CONN-* (``checks/workday``): repair unhealthy Workday connections
    by reopening the connector dialog from the connections list.

Host choice rationale:
  * ``make.powerautomate.com/environments/{env}/connections`` is used
    for the connections list because the PowerAutomate maker has
    rendered the env-scoped connections list more reliably than
    ``make.powerapps.com`` across the multiple Power Platform admin
    center information-architecture churns observed in 2024-2026.
  * ``make.powerapps.com/environments/{env}/solutions`` is the only
    surface that exposes the solution-scoped Connection References
    pane where a maker re-binds a reference to a different connection.
"""

from __future__ import annotations


def maker_connections_url(env_id: str) -> str:
    """Direct link to the maker connections list for ``env_id``.

    Use for remediations that ask the operator to open a connector
    dialog (test, edit credentials, delete unused connection). The
    target page is the same regardless of which connector the
    connection wraps, so callers do not need to pass connector kind.
    """
    return f"https://make.powerautomate.com/environments/{env_id}/connections"


def maker_solutions_url(env_id: str) -> str:
    """Direct link to the maker solutions list for ``env_id``.

    Use as a fallback when the operator must browse multiple solutions
    (e.g. broken refs spread across several solutions) or when the
    containing solution is not known.
    """
    return f"https://make.powerapps.com/environments/{env_id}/solutions"


def maker_solution_url(env_id: str, solution_id: str) -> str:
    """Direct link to a specific solution's detail page in the Power
    Apps maker for ``env_id``.

    Prefer this over :func:`maker_solutions_url` whenever the caller
    knows which solution holds the broken object — landing on the
    solutions LIST forces the operator to guess which solution to open
    (often half a dozen first-party + ISV solutions are present). The
    solution detail page exposes the **Objects \u2192 Connection
    references** pane directly.

    The URL format is documented at the Power Platform ALM level:
    ``make.powerapps.com/environments/{env}/solutions/{solution_guid}``.
    """
    return (
        f"https://make.powerapps.com/environments/{env_id}/solutions/{solution_id}"
    )
