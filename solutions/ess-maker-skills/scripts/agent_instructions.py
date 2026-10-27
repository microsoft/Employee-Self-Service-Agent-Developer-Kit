# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read, preview, and explicitly save native agent-instruction text edits.

Uses the selected canonical Dev agent and workspace-local authentication.
Read native instructions with `read --output <snapshot.json>`. Supply an update
request containing only {"edits": [{"segmentIndex": 0, "oldText": "...",
"newText": "..."}]}. Indices refer to the native instructions.segments array.
Each oldText must occur exactly once in its TextSegment; edits cannot overlap.
Expression segments and all other component fields are preserved.

Preview with `update --request <request.json> --expected <snapshot.json>
--output <preview.json>`. After separate approval, save with the same request,
`--expected <preview.json> --yes --output <result.json>`. A changed request,
target, or native GPT baseline requires another preview. Output files must be
new paths. This operation does not edit topics, activate, publish, or verify
conversational behavior. After an uncertain write, read native state before
the session decides whether another operation is appropriate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from agentbuilder import AgentBuilderError
from alm_enrollment import _exception_chain
from minimalbot_evaluation import (
    MinimalBotEvaluationClient,
    MinimalBotEvaluationError,
    build_agent_instruction_update,
)
from setup_existing_da import ExistingDASetupError
from topic_authoring import connect, read_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("operation", choices=("read", "update"))
    parser.add_argument("--kit-root", type=Path, default=Path.cwd())
    parser.add_argument("--account")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--yes", action="store_true", help="Save the separately approved preview."
    )
    args = parser.parse_args(argv)
    if args.operation == "read" and (args.yes or args.request or args.expected):
        parser.error("read does not accept --yes, --request, or --expected.")
    if args.operation == "update" and (args.request is None or args.expected is None):
        parser.error("update requires --request and --expected.")
    if args.output and args.output.exists():
        raise FileExistsError(
            f"Choose a new output path; this file exists: {args.output}"
        )
    request = read_json(args.request) if args.request else None
    expected = read_json(args.expected) if args.expected else None
    if request is not None and set(request) != {"edits"}:
        raise ValueError("An instruction request must contain only edits.")

    client, target = connect(args.kit_root.resolve(), args.account)
    native = MinimalBotEvaluationClient(
        target["environment"]["id"],
        target["agent"]["id"],
        target["environment"]["tenantId"],
        ring=target["environment"]["ring"],
        host=client.host,
        access_token=client.headers["Authorization"].split(" ", 1)[1],
        session=client.session,
    )
    current = native.read_agent_instructions()
    result: dict[str, Any] = {"target": target, "operation": args.operation, **current}
    if args.operation == "update":
        assert expected is not None and request is not None
        for section, fields in (
            ("environment", ("id", "tenantId", "ring", "powerPlatformApiEndpoint")),
            ("agent", ("id", "schemaName", "realm")),
        ):
            if any(
                expected["target"][section].get(field) != target[section].get(field)
                for field in fields
            ):
                raise ValueError(
                    "The expected instruction snapshot belongs to a different target."
                )
        if current["component"] != expected["component"]:
            raise ValueError(
                "Native instructions changed since the expected snapshot; preview again."
            )
        desired = build_agent_instruction_update(current["component"], request["edits"])
        if args.yes and (
            expected.get("operation") != "update"
            or expected.get("saved") is not False
            or expected.get("edits") != request["edits"]
            or expected.get("desiredComponent") != desired
        ):
            raise ValueError(
                "The instruction request differs from its approved preview; preview again."
            )
        result.update(
            {
                "edits": request["edits"],
                "desiredComponent": desired,
                "changed": desired != current["component"],
                "saved": False,
            }
        )
        if args.yes:
            update = native.update_agent_instructions(
                current["component"], request["edits"]
            )
            result.update(update)
            result["saved"] = update["updatedComponents"] != 0
    result["published"] = False
    result["conversationVerified"] = False
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    print(output, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        AgentBuilderError,
        ExistingDASetupError,
        MinimalBotEvaluationError,
        ValueError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "completed": False,
                    "errors": _exception_chain(exc),
                    **getattr(exc, "evidence", {}),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
