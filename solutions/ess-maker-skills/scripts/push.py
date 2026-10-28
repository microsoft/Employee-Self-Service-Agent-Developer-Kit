# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Inspect pending workspace changes and dispatch explicit native operations."""

import argparse
import json
import os
import sys

from auth import load_config
from alm_enrollment import _exception_chain
from minimalbot_evaluation import (
    MinimalBotEvaluationClient, MinimalBotEvaluationError, is_minimalbot,
)
from topic_authoring import (
    plan_workspace_topic_updates as _minimalbot_topic_update_plan,
    save_workspace_topic_updates,
)
from workspace_state import (
    classify_path, collect_files, compute_diff, inspect_pending_changes,
    _ensure_utf8_stdout as _ensure_utf8_stdout,
)


def _read_only_manifest(path):
    """Read a push scope manifest: one relative path/glob per line.

    Blank lines and lines starting with '#' are ignored. Backslashes are
    normalized to forward slashes so entries match the forward-slash
    relative paths compute_diff produces.
    """
    globs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                globs.append(line.replace("\\", "/"))
    return globs



def parse_only_globs(argv):
    """Collect --only GLOB / --only=GLOB (repeatable) and --only-from FILE.

    Returns a list of glob patterns. An empty list selects the local overview.
    """
    globs = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--only" and i + 1 < len(argv):
            globs.append(argv[i + 1].replace("\\", "/"))
            i += 2
            continue
        if arg.startswith("--only="):
            globs.append(arg.split("=", 1)[1].replace("\\", "/"))
            i += 1
            continue
        if arg == "--only-from" and i + 1 < len(argv):
            globs.extend(_read_only_manifest(argv[i + 1]))
            i += 2
            continue
        if arg.startswith("--only-from="):
            globs.extend(_read_only_manifest(arg.split("=", 1)[1]))
            i += 1
            continue
        i += 1
    return globs



def _warn_minimalbot_non_eval_changes(agent_dir):
    """Report pending non-evaluation changes the MinimalBot push cannot deploy.

    Evaluation deployment does not acknowledge topic, instruction or workflow
    changes. Report those separately without implying a Dataverse fallback.
    """
    baseline_dir = os.path.join(agent_dir, ".baseline")
    if not os.path.isdir(baseline_dir):
        return
    changed, new, deleted = compute_diff(
        collect_files(baseline_dir), collect_files(agent_dir))
    non_eval = sorted({
        f for f in (*changed, *new, *deleted)
        if classify_path(f)
        and not f.replace("\\", "/").startswith("evaluations/")
    })
    if not non_eval:
        return
    print(
        "WARNING: the following non-evaluation change(s) will NOT be pushed "
        "by this evaluation operation; use their owning authoring operations:"
    )
    for path in non_eval[:20]:
        print(f"  - {path}")
    if len(non_eval) > 20:
        print(f"  ... and {len(non_eval) - 20} more")



def _minimalbot_push(
    config,
    *,
    dry_run=False,
    force_delete=False,
    repair_mode=False,
    only_globs=None,
    auto_yes=False,
    preferred_username=None,
    activate_topics=False,
):
    """Push supported changes to a Dataverse-free MinimalBot agent.

    Uses the Power Platform MinimalBot components API on the agent's ring (see
    :mod:`minimalbot_evaluation`). Evaluation inserts and scoped updates to
    existing dialog topics are supported. Other component types still require
    a different authoring path.

    The operation is explicitly scoped by its caller. Confirmation precedes
    mutation; dry runs never authenticate or mutate remote state.
    """
    agent_dir = config["agent"]["folder"]
    if not os.path.exists(agent_dir):
        print(f"ERROR: Agent folder not found: {agent_dir}")
        sys.exit(1)

    if repair_mode:
        print(
            "ERROR: --repair applies to Dataverse flow registration and is not "
            "supported for Dataverse-free (MinimalBot) agents. No request was "
            "made."
        )
        sys.exit(1)
    if force_delete:
        print(
            "ERROR: --force-delete is not supported for Dataverse-free "
            "(MinimalBot) agents; evaluation components cannot be deleted "
            "through this path yet. No request was made."
        )
        sys.exit(1)
    if activate_topics and not only_globs:
        raise MinimalBotEvaluationError("Activation requires an explicit topic scope.")

    print("MinimalBot agent detected (Dataverse-free).")
    if only_globs:
        print(f"(Scoped push — {len(only_globs)} filter(s) active)")

    client = MinimalBotEvaluationClient.from_config(config)
    try:
        topic_updates = _minimalbot_topic_update_plan(
            agent_dir,
            only_globs,
            activate_topics=activate_topics,
            agent_schema=(config.get("agent") or {}).get("schemaName"),
        )
    except MinimalBotEvaluationError as exc:
        print(json.dumps({
            "error": str(exc), "errors": _exception_chain(exc),
            "evidence": getattr(exc, "evidence", {}),
        }), file=sys.stderr)
        raise SystemExit(1) from exc

    if topic_updates:
        print(f"\nWould update {len(topic_updates)} existing topic(s):")
        for entry in topic_updates:
            print(f"  • {entry['displayName']}  ({entry['path']})")
        if dry_run:
            print("\n(Dry run — no changes pushed)")
            return
        if not auto_yes:
            response = input(
                "\nPush these changes to Copilot Studio? (yes/no): "
            ).strip().lower()
            if response not in ("yes", "y"):
                print("Push cancelled.")
                return
        try:
            client.authenticate(preferred_username=preferred_username)
            result = save_workspace_topic_updates(client, agent_dir, topic_updates)
        except MinimalBotEvaluationError as exc:
            print(json.dumps({
                "error": str(exc), "errors": _exception_chain(exc),
                "evidence": getattr(exc, "evidence", {}),
            }), file=sys.stderr)
            raise SystemExit(1) from exc
        if client.signed_in_username:
            print(f"Signed in as: {client.signed_in_username}")
        if result.get("reconciledComponents"):
            print(
                "Preserved newer live content while applying the scoped "
                "topic change."
            )
        print(
            f"\n✅ Updated and verified "
            f"{result['verifiedComponents']} topic component(s)."
        )
        diagnostics = result.get("blockingDiagnostics") or []
        if diagnostics:
            print(
                "WARNING: The topic save was verified, but "
                f"{len(diagnostics)} dependency diagnostic(s) remain. "
                "Continue with Workday connection verification."
            )
        return result

    if only_globs and all(pattern.startswith("topics/") for pattern in only_globs):
        return {"status": "no_local_changes", "remoteVerified": False}

    _warn_minimalbot_non_eval_changes(agent_dir)

    # Build the plan offline first (no auth, no mutation) so the change set can
    # be shown and confirmed BEFORE any component insert. Honouring only_globs
    # prevents a selected action from deploying unrelated new evaluation sets.
    try:
        plan = client.push_agent_evaluations(
            agent_dir, dry_run=True, only_globs=only_globs)
    except MinimalBotEvaluationError as exc:
        print(json.dumps({
            "error": str(exc), "errors": _exception_chain(exc),
            "evidence": getattr(exc, "evidence", {}),
        }), file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"\nWould push {len(plan['sets'])} evaluation set(s), "
          f"{plan['componentCount']} component(s):")
    for entry in plan["sets"]:
        print(f"  • {entry['displayName']}  (cases: {entry['cases']})")
    if plan["componentCount"]:
        print("Native Push creates a new deployed copy; existing remote copies are retained.")
    if plan.get("reviewWarning"):
        print(plan["reviewWarning"])

    if dry_run:
        print("\n(Dry run — no changes pushed)")
        return {"status": "ready", "backend": "minimalbot", "plan": plan}

    # Dry runs return before authentication or mutation.
    if not auto_yes:
        response = input(
            "\nPush these changes to Copilot Studio? (yes/no): "
        ).strip().lower()
        if response not in ("yes", "y"):
            print("Push cancelled.")
            return {"status": "cancelled", "backend": "minimalbot"}

    print("Pushing evaluations via the Power Platform MinimalBot API...")
    try:
        client.authenticate()
        result = client.push_agent_evaluations(
            agent_dir, dry_run=False, only_globs=only_globs, plan=plan)
    except MinimalBotEvaluationError as exc:
        print(json.dumps({
            "error": str(exc), "errors": _exception_chain(exc),
            "evidence": getattr(exc, "evidence", {}),
        }), file=sys.stderr)
        raise SystemExit(1) from exc

    if client.signed_in_username:
        print(f"Signed in as: {client.signed_in_username}")
    print(f"\n✅ Pushed {len(result['sets'])} evaluation set(s), "
          f"{result['verifiedComponents']} component(s) verified:")
    for entry in result["sets"]:
        print(f"  • {entry['displayName']}")
        print(f"      testSetId: {entry['testSetId']}  (cases: {entry['cases']})")
    print("\nRun a set with:")
    print("  python scripts/evaluation_runs.py run --test-set-id <testSetId>")
    return {**result, "backend": "minimalbot"}


def main(argv=None, *, config=None):
    """Inspect local pending changes or invoke one explicitly scoped owner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--only-from", action="append", default=[])
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--preferred-username")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--force-delete", action="store_true")
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv)
    if args.repair or args.force_delete:
        parser.error(
            "Dataverse deployment, template-config CRUD and workflow "
            "deploy/register/repair operations are retired. No request was made."
        )
    config = load_config() if config is None else config
    scope = parse_only_globs(argv)
    if not scope:
        if args.activate:
            parser.error("--activate requires an explicit topic scope.")
        pending = inspect_pending_changes(config["agent"]["folder"])
        result = {
            "status": "pending" if any(pending.values()) else "no_local_changes",
            "scope": "local", "changes": pending, "remoteVerified": False,
        }
        print(json.dumps(result, indent=2))
        return result
    topic_scope = all(pattern.startswith("topics/") for pattern in scope)
    evaluation_scope = all(pattern.startswith("evaluations/") for pattern in scope)
    if not (topic_scope or evaluation_scope) or (args.activate and not topic_scope):
        parser.error(
            "Select topics or evaluations separately. Instructions use their "
            "separately approved operation; workflow/template-config writes are retired."
        )
    if not is_minimalbot(config):
        parser.error("Dataverse Push is retired. No remote request was made.")
    return _minimalbot_push(
        config, dry_run=args.dry_run, only_globs=scope, auto_yes=args.yes,
        preferred_username=args.preferred_username, activate_topics=args.activate,
    )


if __name__ == "__main__":
    _ensure_utf8_stdout()
    try:
        main()
    except (MinimalBotEvaluationError, OSError, ValueError) as exc:
        print(json.dumps({
            "errors": _exception_chain(exc), "evidence": getattr(exc, "evidence", {}),
        }), file=sys.stderr)
        raise SystemExit(1) from exc
