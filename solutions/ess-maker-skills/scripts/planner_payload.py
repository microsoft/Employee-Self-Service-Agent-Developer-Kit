# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Conservative admission budget for a shared Planner record, not its HTTP body."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PLAN_STORAGE_LIMIT_BYTES = 25_600
# Client policy, not an exact backend serializer: reserve space for record fields
# and per-entry provenance that the service adds after receiving the request.
PLAN_METADATA_HEADROOM_BYTES = 1_024
CONTEXT_METADATA_HEADROOM_BYTES = 256
PLAN_METADATA_FIELDS = ("configuringAgentName", "ownedById", "acceptanceCriteria", "context")


def json_utf8_size(value: Any) -> int:
    return len(json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8"))


def plan_metadata(plan: dict[str, Any], *, from_readback: bool = False) -> dict[str, Any]:
    """Project create/read/patch shapes onto fields stored in the plan record.

    Inline tasks are separate records. Readbacks may use PascalCase.
    """
    names = {name.casefold(): name for name in PLAN_METADATA_FIELDS}
    result: dict[str, Any] = {}
    for key, value in plan.items():
        if not isinstance(key, str):
            raise ValueError("Plan metadata field names must be strings.")
        name = names.get(key.casefold())
        if name is not None:
            if name in result:
                raise ValueError(f"plan metadata duplicates field {name}")
            result[name] = value
    if from_readback and isinstance(result.get("context"), list):
        entries = []
        for entry in result["context"]:
            if not isinstance(entry, dict):
                raise ValueError("Current plan contains malformed context entries.")
            # Provenance is accounted for by the allowance, not counted twice.
            fields = {}
            for key, value in entry.items():
                if not isinstance(key, str):
                    raise ValueError("Context field names must be strings.")
                name = key.casefold()
                if name in ("key", "value") or (
                    name in ("group", "description") and value not in (None, "")
                ):
                    if name in fields:
                        raise ValueError(f"Context duplicates field {name}.")
                    fields[name] = value
            entries.append(fields)
        result["context"] = entries
    return result


@dataclass(frozen=True)
class PlanPayloadSize:
    payload_bytes: int
    context_entries: int

    @property
    def headroom_bytes(self) -> int:
        return PLAN_METADATA_HEADROOM_BYTES + self.context_entries * CONTEXT_METADATA_HEADROOM_BYTES

    @property
    def estimated_bytes(self) -> int:
        return self.payload_bytes + self.headroom_bytes


class PlanPayloadTooLarge(ValueError):
    def __init__(self, size: PlanPayloadSize):
        self.size = size
        super().__init__(
            f"PlanPayloadTooLarge: plan metadata uses {size.payload_bytes:,} UTF-8 bytes "
            f"plus {size.headroom_bytes:,} bytes of client headroom for server-added "
            f"metadata ({size.context_entries} context entries). Estimated record size "
            f"{size.estimated_bytes:,} exceeds the {PLAN_STORAGE_LIMIT_BYTES:,}-byte "
            "ESS limit. Shorten/deduplicate context values and descriptions or compact "
            "generated workstream metadata; preserve requirements and keep detailed "
            "supporting material in the local review artifact. Do not retry unchanged."
        )


def measure_plan_payload(plan: dict[str, Any]) -> PlanPayloadSize:
    metadata = plan_metadata(plan)
    context = metadata.get("context")
    if context is not None and not isinstance(context, list):
        raise ValueError("plan.context must be an array or null")
    try:
        size = json_utf8_size(metadata)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("Plan metadata must be valid UTF-8 JSON.") from exc
    return PlanPayloadSize(size, len(context) if context is not None else 0)


def ensure_plan_payload_fits(plan: dict[str, Any]) -> PlanPayloadSize:
    size = measure_plan_payload(plan)
    if size.estimated_bytes > PLAN_STORAGE_LIMIT_BYTES:
        raise PlanPayloadTooLarge(size)
    return size
