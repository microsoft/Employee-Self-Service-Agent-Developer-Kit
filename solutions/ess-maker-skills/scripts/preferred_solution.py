# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Discover, select, and persist an unmanaged preferred solution."""

from __future__ import annotations

import argparse
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import uuid

from auth import (
    AuthExpiredError,
    authenticate,
    clear_token_cache,
    dataverse_get,
    execute_action,
    query_all,
)
from setup_state import persist_alm_solution


LIST_MARKER = "UNMANAGED_SOLUTIONS_JSON:"
SELECTION_MARKER = "PREFERRED_SOLUTION_JSON:"
ELIGIBLE_SOLUTION_FILTER = (
    "ismanaged eq false and isvisible eq true "
    "and uniquename ne 'Default' and uniquename ne 'Active' "
    "and solutiontype eq 0 and _parentsolutionid_value eq null"
)
ELIGIBLE_SOLUTION_SELECT = (
    "solutionid,uniquename,friendlyname,version,_publisherid_value"
)
PUBLISHER_SELECT = "uniquename,friendlyname,customizationprefix"


def _normalized_guid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class SolutionCandidate:
    solution_id: str
    unique_name: str
    display_name: str
    version: str
    publisher_name: str
    publisher_prefix: str
    publisher_is_default: bool
    is_preferred: bool

    def to_dict(self) -> dict:
        return {
            "solutionId": self.solution_id,
            "uniqueName": self.unique_name,
            "displayName": self.display_name,
            "version": self.version,
            "publisherName": self.publisher_name,
            "publisherPrefix": self.publisher_prefix,
            "publisherIsDefault": self.publisher_is_default,
            "isPreferred": self.is_preferred,
        }


class PreferredSolutionGateway(ABC):
    """Dataverse boundary used by the preferred-solution workflow."""

    @abstractmethod
    def list_unmanaged_solutions(self) -> list[dict]:
        """Return eligible customer-owned unmanaged solutions."""

    @abstractmethod
    def get_preferred_solution_id(self) -> str | None:
        """Return the current maker's preferred solution ID."""

    @abstractmethod
    def get_publisher(self, publisher_id: str) -> dict:
        """Return publisher metadata."""

    @abstractmethod
    def set_preferred_solution(self, solution_id: str) -> None:
        """Set the current maker's preferred solution."""


class DataversePreferredSolutionGateway(PreferredSolutionGateway):
    """Dataverse implementation of the preferred-solution boundary."""

    def __init__(self, env_url: str, token: str) -> None:
        self._env_url = env_url.rstrip("/")
        self._token = token

    def list_unmanaged_solutions(self) -> list[dict]:
        return query_all(
            self._env_url,
            self._token,
            "solutions",
            ELIGIBLE_SOLUTION_SELECT,
            ELIGIBLE_SOLUTION_FILTER,
        )

    def get_preferred_solution_id(self) -> str | None:
        preferred = dataverse_get(
            self._env_url,
            self._token,
            "GetPreferredSolution()",
        )
        return (preferred or {}).get("solutionid")

    def get_publisher(self, publisher_id: str) -> dict:
        return dataverse_get(
            self._env_url,
            self._token,
            f"publishers({publisher_id})",
            params={"$select": PUBLISHER_SELECT},
        )

    def set_preferred_solution(self, solution_id: str) -> None:
        execute_action(
            self._env_url,
            self._token,
            "SetPreferredSolution",
            {"SolutionId": solution_id},
        )


class PreferredSolutionService:
    """Application service for preferred-solution discovery and selection."""

    def __init__(self, gateway: PreferredSolutionGateway) -> None:
        self._gateway = gateway

    def list_candidates(self) -> list[SolutionCandidate]:
        preferred_id = _normalized_guid(
            self._gateway.get_preferred_solution_id()
        )
        candidates = []
        for solution in self._gateway.list_unmanaged_solutions():
            publisher_id = solution.get("_publisherid_value")
            if not publisher_id:
                raise RuntimeError(
                    f"Solution '{solution.get('uniquename', '<unknown>')}' "
                    "does not expose a publisher."
                )
            publisher = self._gateway.get_publisher(publisher_id) or {}
            publisher_prefix = publisher.get("customizationprefix")
            if not publisher_prefix:
                raise RuntimeError(
                    f"Publisher metadata is incomplete for solution "
                    f"'{solution.get('uniquename', '<unknown>')}'."
                )
            solution_id = solution.get("solutionid")
            unique_name = solution.get("uniquename")
            version = solution.get("version")
            if not all((solution_id, unique_name, version)):
                raise RuntimeError(
                    "Dataverse returned incomplete unmanaged solution metadata."
                )
            publisher_name = (
                publisher.get("friendlyname")
                or publisher.get("uniquename")
                or publisher_prefix
            )
            candidates.append(SolutionCandidate(
                solution_id=solution_id,
                unique_name=unique_name,
                display_name=solution.get("friendlyname") or unique_name,
                version=version,
                publisher_name=publisher_name,
                publisher_prefix=publisher_prefix,
                publisher_is_default=str(
                    publisher.get("uniquename") or ""
                ).casefold().startswith("defaultpublisher"),
                is_preferred=(
                    _normalized_guid(solution_id) == preferred_id
                ),
            ))
        return sorted(
            candidates,
            key=lambda candidate: (
                not candidate.is_preferred,
                candidate.display_name.casefold(),
            ),
        )

    def configure(self, solution_id: str) -> tuple[SolutionCandidate, bool]:
        candidates = self.list_candidates()
        selected = next(
            (
                candidate
                for candidate in candidates
                if _normalized_guid(candidate.solution_id)
                == _normalized_guid(solution_id)
            ),
            None,
        )
        if selected is None:
            raise ValueError(
                "The selected solution is not an eligible unmanaged solution."
            )

        already_preferred = selected.is_preferred
        if not already_preferred:
            self._gateway.set_preferred_solution(selected.solution_id)

        verified_id = _normalized_guid(
            self._gateway.get_preferred_solution_id()
        )
        if verified_id != _normalized_guid(selected.solution_id):
            raise RuntimeError(
                "Dataverse did not retain the selected preferred solution."
            )

        return selected, already_preferred


def _service(env_url: str) -> PreferredSolutionService:
    token = authenticate(env_url.rstrip("/"))
    gateway = DataversePreferredSolutionGateway(env_url, token)
    return PreferredSolutionService(gateway)


def _execute_command(args: argparse.Namespace) -> tuple[str, dict]:
    service = _service(args.url)
    if args.command == "list":
        candidates = service.list_candidates()
        return LIST_MARKER, {
            "solutions": [candidate.to_dict() for candidate in candidates],
            "preferredSolutionId": next(
                (
                    candidate.solution_id
                    for candidate in candidates
                    if candidate.is_preferred
                ),
                None,
            ),
        }

    selected, already_preferred = service.configure(args.solution_id)
    persist_alm_solution(
        solution_id=selected.solution_id,
        solution_name=selected.unique_name,
        publisher_prefix=selected.publisher_prefix,
        version=selected.version,
        state_path=Path(args.state),
    )
    return SELECTION_MARKER, {
        **selected.to_dict(),
        "isPreferred": True,
        "wasAlreadyPreferred": already_preferred,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--state",
        default=".local/setup/config.json",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    select = commands.add_parser("select")
    select.add_argument("--solution-id", required=True)
    args = parser.parse_args()

    try:
        try:
            marker, result = _execute_command(args)
        except AuthExpiredError:
            clear_token_cache(args.url)
            print(
                "Dataverse rejected the cached session. Refreshing sign-in..."
            )
            marker, result = _execute_command(args)
        print(f"{marker}{json.dumps(result)}")
        return 0
    except (AuthExpiredError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
