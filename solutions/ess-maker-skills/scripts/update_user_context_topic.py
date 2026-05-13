# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Update User Context Setup Topic

PATCHes the `[Admin] - User Context - Setup` topic to redirect to
`WorkdaySystemGetUserContextV2`, enabling worker-ID resolution at runtime.

Usage:
    python scripts/update_user_context_topic.py \\
        --env-url https://orgxyz.crm.dynamics.com --persona hr

Exit codes: 0 success, 1 auth, 2 patch/discovery, 3 unexpected.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import requests
except ImportError:
    print("ERROR: requests required. Run: pip install -r scripts/requirements.txt", file=sys.stderr)
    sys.exit(3)

from auth import authenticate, query_all
from pp_helpers import VALID_PERSONAS


def topic_yaml_for_persona(persona):
    """Build the redirect YAML body for the given persona."""
    return (
        "kind: AdaptiveDialog\n"
        "beginDialog:\n"
        "  kind: OnRedirect\n"
        "  id: main\n"
        "  priority: 0\n"
        "  actions:\n"
        "    - kind: BeginDialog\n"
        "      id: QVk2yi\n"
        f"      dialog: msdyn_copilotforemployeeselfservice{persona}.topic.WorkdaySystemGetUserContextV2\n"
    )


def find_user_context_topic(env_url, token, persona):
    """Find the [Admin] - User Context - Setup topic for the persona's bot.

    Persona is validated against VALID_PERSONAS before OData interpolation.
    """
    if persona.lower() not in VALID_PERSONAS:
        raise ValueError(f"persona must be one of {sorted(VALID_PERSONAS)}, got {persona!r}")
    persona_prefix = f"msdyn_copilotforemployeeselfservice{persona.lower()}"

    # Topic body lives in `data`, NOT `content`. CPS reads `data`; `content`
    # is a metadata-only column. See push.py ~line 391 for precedent.
    rows = query_all(
        env_url,
        token,
        "botcomponents",
        "botcomponentid,name,schemaname,data,componenttype",
        f"startswith(schemaname,'{persona_prefix}') and componenttype eq 9",
    )

    # Match by name first, then schema name as fallback.
    name_signals = ["user context", "usercontext"]
    candidates = []
    for row in rows:
        name = (row.get("name") or "").lower()
        schemaname = (row.get("schemaname") or "").lower()
        if "setup" in name and any(sig in name for sig in name_signals):
            candidates.append(row)
        elif "setup" in schemaname and any(sig in schemaname for sig in name_signals):
            candidates.append(row)

    return candidates


def patch_topic_content(env_url, token, botcomponentid, new_content):
    """PATCH the topic's `data` field with new YAML.

    Uses `data` (not `content`) — CPS reads topic body from `data`.
    """
    url = f"{env_url.rstrip('/')}/api/data/v9.2/botcomponents({botcomponentid})"
    body = {"data": new_content}
    resp = requests.patch(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "If-Match": "*",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
        },
        json=body,
        timeout=30,
    )
    return resp


def main():
    parser = argparse.ArgumentParser(description="Update the User Context Setup topic with the WorkdaySystemGetUserContextV2 redirect")
    parser.add_argument("--env-url", required=True, help="Dataverse env URL")
    parser.add_argument("--persona", required=True, choices=["hr", "it"], help="ESS persona (hr or it)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be patched without actually patching")
    parser.add_argument("--force", action="store_true", help="Overwrite even if the topic has non-empty custom content")
    args = parser.parse_args()

    new_yaml = topic_yaml_for_persona(args.persona)

    # Auth via Dataverse Web API
    token = authenticate(args.env_url)

    # Discover the User Context Setup topic.
    candidates = find_user_context_topic(args.env_url, token, args.persona)

    if not candidates:
        print(
            f"ERROR: could not find a User Context Setup topic in the persona namespace "
            f"'msdyn_copilotforemployeeselfservice{args.persona}'. Verify the Workday ISV "
            f"is installed and the agent's bot components are visible.",
            file=sys.stderr,
        )
        sys.exit(2)

    if len(candidates) > 1:
        # Show all candidates and pick the one that looks most like the User Context Setup topic.
        print(f"Found {len(candidates)} candidate topics; picking the first. Candidates:", file=sys.stderr)
        for c in candidates:
            print(f"  - name='{c.get('name')}' schemaname='{c.get('schemaname')}'", file=sys.stderr)

    topic = candidates[0]
    botcomponentid = topic.get("botcomponentid")
    topic_name = topic.get("name")
    topic_schema = topic.get("schemaname")

    # Safety: refuse to overwrite non-trivial custom content without --force.
    existing_data = (topic.get("data") or "").strip()
    is_empty = not existing_data
    is_bare_scaffold = (
        existing_data
        and "OnRedirect" in existing_data
        and "BeginDialog" not in existing_data
        and ("actions" not in existing_data
             or "actions: []" in existing_data
             or "actions:\n" in existing_data)
    )
    is_already_correct = (
        existing_data
        and "WorkdaySystemGetUserContextV2" in existing_data
    )

    if not is_empty and not is_bare_scaffold and not is_already_correct:
        if not args.force:
            print(
                f"ERROR: topic '{topic_name}' already has custom content that does not "
                f"match the expected empty/scaffold state. Refusing to overwrite.\n"
                f"Current content (first 300 chars): {existing_data[:300]}\n\n"
                f"Use --force to overwrite, or --dry-run to inspect.",
                file=sys.stderr,
            )
            sys.exit(2)
        print(
            f"WARNING: topic has custom content but --force was specified. Overwriting.",
            file=sys.stderr,
        )

    if is_already_correct and not args.force:
        out = {
            "action": "already-correct",
            "topic": {
                "botcomponentid": botcomponentid,
                "name": topic_name,
                "schemaname": topic_schema,
            },
        }
        print(json.dumps(out, indent=2))
        sys.exit(0)

    if args.dry_run:
        out = {
            "action": "dry-run",
            "topic": {
                "botcomponentid": botcomponentid,
                "name": topic_name,
                "schemaname": topic_schema,
                "currentContent": (topic.get("data") or "")[:500],
            },
            "newContent": new_yaml,
        }
        print(json.dumps(out, indent=2))
        sys.exit(0)

    print(f"Patching topic '{topic_name}' (botcomponentid={botcomponentid})...", file=sys.stderr)

    resp = patch_topic_content(args.env_url, token, botcomponentid, new_yaml)

    if resp.status_code in (200, 204):
        out = {
            "action": "patched",
            "topic": {
                "botcomponentid": botcomponentid,
                "name": topic_name,
                "schemaname": topic_schema,
                "previousContent": existing_data[:500] if existing_data else None,
            },
            "newContent": new_yaml,
            "httpStatus": resp.status_code,
        }
        print(json.dumps(out, indent=2))
        sys.exit(0)
    elif resp.status_code == 401:
        print(f"ERROR: 401 auth rejected. Body: {resp.text[:300]}", file=sys.stderr)
        sys.exit(1)
    elif 400 <= resp.status_code < 500:
        print(f"ERROR: PATCH {resp.status_code}: {resp.text[:600]}", file=sys.stderr)
        sys.exit(2)
    else:
        print(f"ERROR: PATCH {resp.status_code}: {resp.text[:600]}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
