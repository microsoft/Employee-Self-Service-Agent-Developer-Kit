# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner CLI.

The deterministic surface the ``/planner`` skill calls to read and mutate the
local Plan (``workspace/plan/plan.json``) and to preview Learn research. The
skill drives the conversation, grounding, and confirmations; this CLI owns the
structured, crash-safe writes and the pure selection math.

Usage (run from the kit root):

    python scripts/planner/cli.py init [--objective "..."]
    python scripts/planner/cli.py set-context --key market --value DE --group market
    python scripts/planner/cli.py add-task --id T1 --title "..." --role power-platform-admin --produces primaryEnvironment
    python scripts/planner/cli.py assign --task T1 --role power-platform-admin --person <oid>
    python scripts/planner/cli.py set-state --task T1 --state Completed
    python scripts/planner/cli.py capture-setup --task T1
    python scripts/planner/cli.py mine --person <oid> --roles integration-owner,eval-author
    python scripts/planner/cli.py research --tokens "workday servicenow ticketing" --toc toc.json
    python scripts/planner/cli.py summary
    python scripts/planner/cli.py validate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from typing import Any

# Ensure scripts/ is on the path so ``import planner...`` resolves when this
# file is run directly (mirrors scripts/flightcheck/cli.py).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from planner import research, review, setup_tasks
from planner.capture import (
    INVENTORY_MIRROR_PATH,
    detect_config_artifacts,
    read_config,
    snapshot_config,
    summarize_discovery,
)
from planner.plan_model import (
    ARTIFACT_KINDS,
    CONFIGURING_AGENT_CHOICES,
    PLAN_PATH,
    PRIMARY_ENVIRONMENT_KEY,
    RESEARCH_PATH,
    SCENARIO_GROUP,
    SUMMARY_FILENAME,
    Plan,
    new_task,
    plan_artifact,
    principal_person,
    principal_pool,
    read_research_context,
)
from planner.sync import (
    extract_json_payload,
    hydrate_from_remote,
    pending_sync_payload,
    preserve_local_pending,
    stamp_remote_ids,
    to_remote_plan_body,
)


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _load(args: argparse.Namespace) -> Plan:
    return Plan.load_or_new(args.plan)


class PlanInvalidError(Exception):
    """Raised when a mutation would persist an invalid plan (blocks the write)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _save(plan: Plan, args: argparse.Namespace) -> None:
    """Validate, then atomically persist — never overwrite the authoritative
    plan with a document that ``validate`` would reject (over-limit collections,
    invalid artifact kinds/states, orphan artifacts, ...)."""
    errors = plan.validate()
    if errors:
        raise PlanInvalidError(errors)
    plan.save_all(args.plan)


def _emit_sync_progress(plan: Plan, task_ids: list[str]) -> None:
    """Tell the agent a local completion should now be synced to the shared plan.

    The CLI is network-free (src/skills/planner/sync.md), so it marks the task
    ``pendingSync`` and prints — to **stderr**, so stdout stays the clean artifact
    JSON the skill parses — a note to sync it **in the same flow, without waiting to
    be asked**. The agent runs ``pending-sync`` for the exact
    ``complete_project_plan_task`` arguments, syncs, then ``import-remote-plan`` (or
    ``mark-synced``) to confirm. If the shared plan can't be reached the task stays
    saved locally and syncs automatically on the next connection — the skill lets
    the sponsor know plainly."""
    if not task_ids:
        return
    if not plan.data.get("projectId") or not plan.data.get("planId"):
        print(
            "Progress saved locally. This plan has not been shared; keep the "
            "completion and outputs for the first explicit share.",
            file=sys.stderr,
        )
        return
    ids = ", ".join(task_ids)
    print(
        "Syncing progress to the shared plan — " + ids + " is complete locally and "
        "will now be saved to the shared plan (flagged pendingSync until confirmed). "
        "In this same flow, without waiting to be asked:\n"
        "  1. run `pending-sync` for the completion operation and arguments "
        "(projectId, planId, taskId, outputs, etag),\n"
        "  2. check the Active plan, task state, dependencies and ETag; apply its operation,\n"
        "  3. on success, re-hydrate with `import-remote-plan` to confirm state AND outputs.\n"
        "If the shared plan can't be reached: the completion stays saved locally and "
        "syncs automatically on the next successful connection — let the sponsor know "
        "plainly that it is saved locally and not yet on the shared plan.",
        file=sys.stderr,
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_init(args: argparse.Namespace) -> int:
    if os.path.exists(args.plan) and not args.force:
        print(f"A plan already exists at {args.plan}. Use --force to overwrite.", file=sys.stderr)
        return 1
    plan = Plan.new(objective=args.objective)
    _save(plan, args)
    print(f"Initialised plan at {args.plan}")
    return 0


def _print_gaps(gaps: dict) -> None:
    """Human-readable rendering of :meth:`Plan.missing_slots` — the questions the
    skill still needs to ask. Printed to stdout so the skill can read it back."""
    required = gaps.get("required") or []
    recommended = gaps.get("recommended") or []
    pending = gaps.get("pending") or []
    if not required and not recommended and not pending:
        print("Nothing missing — the plan has the objective, scenarios, and a system for each.")
        return
    if required:
        print("Still needed (blocks building the plan) — ask the maker:")
        for gap in required:
            print(f"  - [{gap['slot']}] {gap['prompt']}")
    if recommended:
        if required:
            print()
        print("Nice to confirm (improves the plan, not blocking):")
        for gap in recommended:
            print(f"  - [{gap['slot']}] {gap['prompt']}")
    if pending:
        print("\nPending decisions (saved for later; do not block planning):")
        for gap in pending:
            print(f"  - [{gap['slot']}] {gap['prompt']}")


def cmd_ingest_upload(args: argparse.Namespace) -> int:
    """Build a plan from a maker-authored **uploaded** plan in one atomic write.

    The skill parses the attached plan document — whatever shape the maker wrote
    it in — into the normalized payload (see ``Plan.ingest_upload``) and hands it
    here so the structured write stays atomic and validated. After ingesting, it
    prints what was captured and the remaining gaps (``missing_slots``) so the
    skill knows exactly which questions to ask instead of re-interviewing from
    scratch. Refuses to clobber an existing plan unless ``--force`` (an edit to a
    plan that already exists is the reconcile path, src/skills/planner/edit.md).
    """
    if os.path.exists(args.plan) and not args.force:
        print(
            f"A plan already exists at {args.plan}. Use --force to replace it from "
            "the upload, or reconcile an edit into the existing plan instead.",
            file=sys.stderr,
        )
        return 1
    try:
        payload = json.loads(_read_input(args.input))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read the uploaded plan payload: {exc}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print("The uploaded plan payload must be a JSON object.", file=sys.stderr)
        return 1
    plan = Plan.new()
    try:
        counts = plan.ingest_upload(payload)
    except (ValueError, KeyError) as exc:
        print(f"Could not ingest the uploaded plan: {exc}", file=sys.stderr)
        return 1
    _save(plan, args)
    gaps = plan.missing_slots()
    if args.json:
        print(json.dumps({"ingested": counts, "gaps": gaps}, indent=2))
        return 0
    captured = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
    print(f"Ingested the uploaded plan into {args.plan}.")
    if captured:
        print(f"Captured: {captured}")
    print()
    _print_gaps(gaps)
    return 0


def cmd_gaps(args: argparse.Namespace) -> int:
    """Show the intent slots the plan still lacks (``missing_slots``) — the
    questions to ask. Read-only; re-run after filling a slot to see fewer gaps."""
    plan = _load(args)
    gaps = plan.missing_slots()
    if args.json:
        print(json.dumps(gaps, indent=2))
        return 0
    _print_gaps(gaps)
    return 0


def cmd_set_context(args: argparse.Namespace) -> int:
    plan = _load(args)
    plan.set_context(
        args.key,
        args.value,
        group=args.group,
        description=args.description,
        source=args.source,
    )
    _save(plan, args)
    print(f"Set context {args.key!r} = {args.value!r}")
    return 0


def cmd_add_scenario(args: argparse.Namespace) -> int:
    plan = _load(args)
    plan.set_context(
        args.id, args.label, group=SCENARIO_GROUP,
        description="Scenario in scope", source=args.source,
    )
    _save(plan, args)
    print(f"Registered scenario {args.id!r}")
    return 0


def cmd_add_scenario_dependency(args: argparse.Namespace) -> int:
    plan = _load(args)
    plan.add_scenario_dependency(
        args.scenario, args.depends_on,
        kind=args.kind, rationale=args.rationale or "", source=args.source,
    )
    _save(plan, args)
    print(f"{args.scenario} {args.kind} {args.depends_on}")
    return 0


def cmd_check_deps(args: argparse.Namespace) -> int:
    plan = _load(args)
    status = plan.scenario_dependency_status()
    gaps = plan.task_consume_gaps()
    if args.json:
        print(json.dumps(
            {"scenarioDependencies": status, "taskGraphGaps": gaps}, indent=2
        ))
        return 1 if gaps else 0
    met = [e for e in status if e.get("met")]
    unmet = [e for e in status if not e.get("met")]
    if met:
        print("Met scenario dependencies:\n")
        for edge in met:
            print(f"  - {edge['scenario']} {edge['kind']} {edge['dependsOn']}  [met]")
        print()
    if unmet:
        print("Unmet scenario dependencies (advise the sponsor to add the prerequisite first):\n")
        for edge in unmet:
            print(f"  - {edge['scenario']} {edge['kind']} {edge['dependsOn']}")
            if edge.get("rationale"):
                print(f"      why: {edge['rationale']}")
            if edge.get("source"):
                print(f"      source: {edge['source']}")
        print()
    else:
        print("No unmet scenario dependencies.\n")
    if gaps:
        print("Task-graph gaps (a task consumes something nothing on the plan produces):\n")
        for gap in gaps:
            print(f"  - {gap['task']} ({gap['title']}) needs '{gap['missing']}' — no task produces it")
        print("\nRe-add the producer, or remove/repoint the consumer, then re-check.")
        return 1
    print("Task graph is coherent: every consumed output has a producer.")
    return 0


def cmd_add_system(args: argparse.Namespace) -> int:
    plan = _load(args)
    system = "; ".join(dict.fromkeys(args.system or []))
    plan.set_system(args.area, system, source=args.source, pending=args.pending)
    _save(plan, args)
    print(f"Recorded system decision for {args.area!r}: {system or 'Pending — not known yet'}")
    return 0


def cmd_add_task(args: argparse.Namespace) -> int:
    plan = _load(args)
    assigned: dict | None = None
    if args.person:
        assigned = principal_person(args.person, role_id=args.role)
    elif args.role:
        assigned = principal_pool(args.role)
    plan.add_task(
        new_task(
            args.id,
            args.title,
            description=args.description or "",
            stream=args.stream or "",
            assigned_to=assigned,
            produces=_csv(args.produces),
            consumes=_csv(args.consumes),
        )
    )
    _save(plan, args)
    print(f"Added task {args.id!r}: {args.title!r}")
    return 0


def cmd_update_task(args: argparse.Namespace) -> int:
    plan = _load(args)
    plan.update_task(
        args.id,
        title=args.title,
        description=args.description,
        produces=_csv(args.produces) if args.produces is not None else None,
        consumes=_csv(args.consumes) if args.consumes is not None else None,
    )
    _save(plan, args)
    print(f"Updated task {args.id!r}")
    return 0


def cmd_remove_task(args: argparse.Namespace) -> int:
    plan = _load(args)
    plan.remove_task(args.id)
    _save(plan, args)
    print(f"Removed task {args.id!r}")
    return 0


def cmd_remove_context(args: argparse.Namespace) -> int:
    plan = _load(args)
    try:
        plan.remove_context(args.key)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _save(plan, args)
    print(f"Removed context {args.key!r}")
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    plan = _load(args)
    plan.assign_task(args.task, role_id=args.role, person_oid=args.person)
    _save(plan, args)
    who = args.person or f"the {args.role} role"
    print(f"Assigned {args.task!r} to {who}")
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    plan = _load(args)
    plan.claim_task(args.task, args.person)
    _save(plan, args)
    print(f"{args.person} claimed {args.task!r}")
    return 0


def cmd_set_state(args: argparse.Namespace) -> int:
    plan = _load(args)
    try:
        plan.set_task_state(args.task, args.state)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _save(plan, args)
    if args.state == "Completed" and plan.task(args.task).get("pendingSync"):
        _emit_sync_progress(plan, [args.task])
    print(f"Task {args.task!r} -> {args.state}")
    return 0


def cmd_capture_setup(args: argparse.Namespace) -> int:
    """Observe-mode capture for the ``/setup`` (and any config-writing skill)
    hand-off — pins **every** id + name artifact ``config.json`` recorded: the
    environment, the cloned agent, and any other object a skill wrote (a
    connection, an app, an unknown shape), not just one value.

    Reads the current .local/config.json as the "after" snapshot; the "before"
    is empty (setup has just run). The skill confirms with the assignee before
    this is called, then shows the pinned artifact(s).

    With ``--complete``, one run can close **more than one** task: beyond the
    named/auto-detected task, every other plan task whose declared ``produces``
    the run fully satisfied is also marked Completed (e.g. a single ``/setup``
    run closes both the environment task and the base-agent task when the plan
    splits them).
    """
    plan = _load(args)
    task_id = args.task or plan.setup_task_id()
    if not task_id:
        print("No setup task found on the plan; pass --task <T#>.", file=sys.stderr)
        return 1
    env_key = args.key or plan.setup_environment_key(task_id) or PRIMARY_ENVIRONMENT_KEY
    if args.before_file:
        with open(args.before_file, "r", encoding="utf-8") as fh:
            before = json.load(fh)
    elif args.before:
        before = json.loads(args.before)
    else:
        before = {}
    after = snapshot_config(args.config)
    pinned = detect_config_artifacts(before, after, task_id=task_id, env_key=env_key)
    if not pinned:
        print("No new id/name artifacts detected in config.json; nothing to pin.", file=sys.stderr)
        return 1
    if args.dry_run:
        print(json.dumps(pinned, indent=2))
        print(
            f"[dry-run] detected {len(pinned)} artifact(s); nothing saved. "
            "Confirm with the assignee, then re-run without --dry-run to pin.",
            file=sys.stderr,
        )
        return 0
    for artifact in pinned:
        plan.add_output(artifact)
    complete_ok = True
    also_completed: list[str] = []
    if args.complete:
        complete_ok = _complete_captured_task(plan, task_id)
        # One skill run can satisfy several plan tasks — e.g. /setup both records
        # the environment (primaryEnvironment) AND clones the agent (essAgent). If
        # the plan splits those into separate tasks, close every OTHER task this
        # run fully produced too, so running the skill completes all the tasks it
        # covers, not just the one that triggered the capture.
        pinned_keys = {a["key"] for a in pinned}
        pinned_by_key = {a["key"]: a for a in pinned}
        for t in plan.tasks:
            tid = t["id"]
            if tid == task_id or t.get("state") == "Completed":
                continue
            produces = t.get("produces") or []
            # Close a split task only when THIS run produced EVERY one of its
            # declared outputs — not when an earlier run already satisfied the
            # rest (unresolved_produces counts all-time active outputs, so an
            # `any(...)` test would complete a task on partial credit). And
            # re-attribute each such output to the task that actually owns it:
            # detect_config_artifacts stamped them all with the setup task_id, so
            # without this a split base-agent task is Completed while its artifact
            # belongs to the setup task — and removing that setup task later
            # cascade-deletes the artifact, leaving the completed task unresolved.
            if produces and all(k in pinned_keys for k in produces):
                if plan.blocking_inputs(tid, require_shared_confirmation=False):
                    print(f"Not completing {tid}: waiting on {plan.blocking_reason(tid)}.", file=sys.stderr)
                    complete_ok = False
                    continue
                for key in produces:
                    pinned_by_key[key]["producedByTaskId"] = tid
                if _complete_captured_task(plan, tid):
                    also_completed.append(tid)
                else:
                    complete_ok = False
        if also_completed:
            print(
                "Also completed (produced by this run): " + ", ".join(also_completed),
                file=sys.stderr,
            )
    _save(plan, args)
    completed = [tid for tid in [task_id, *also_completed] if plan.task(tid).get("pendingSync")]
    _emit_sync_progress(plan, completed)
    print(json.dumps(pinned, indent=2))
    return 0 if complete_ok else 1


def cmd_capture_discover(args: argparse.Namespace) -> int:
    """Observe-mode capture for the ``/discover`` hand-off — pin the tenant
    inventory summary a crawl produced onto the plan so the discover task can close
    and downstream tasks read it off the plan.

    The tenant inventory is the one backbone output ``capture-setup`` cannot see:
    ``/discover`` writes the full picture to the durable mirror
    (``.local/inventory.json``) and only leaves two string pointers in
    ``config.json``, which the generic id+name sweep skips. This reads the run's
    ``results.json`` instead and shapes one ``Custom`` ``tenantInventory`` artifact.
    ``--task`` is optional — omitted, it auto-detects the plan's discover task (the
    task that produces ``tenantInventory``).
    """
    plan = _load(args)
    task_id = args.task or plan.discover_task_id()
    if not task_id:
        print(
            "No discover task found on the plan (no task produces 'tenantInventory'); "
            "pass --task <T#>, or skip if this plan isn't tracking discovery.",
            file=sys.stderr,
        )
        return 1
    try:
        with open(args.results, "r", encoding="utf-8") as fh:
            results = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"Could not read discovery results at {args.results!r}: {exc}. "
            "Run /discover first — it writes workspace/discover/results.json.",
            file=sys.stderr,
        )
        return 1
    config = read_config(args.config)
    updated_at = config.get("inventoryUpdatedAt")
    # ``/discover --inventory-out`` records where it actually mirrored the inventory
    # in ``config.json`` (``inventoryPath``). Honour that so a custom mirror path is
    # not silently overwritten by the parser default; an explicit --inventory-path
    # still wins, and the mirror default is the last-resort fallback.
    inventory_path = args.inventory_path or config.get("inventoryPath") or INVENTORY_MIRROR_PATH
    artifact = summarize_discovery(
        results,
        task_id=task_id,
        key=args.key,
        inventory_path=inventory_path,
        results_path=args.results,
        updated_at=updated_at,
    )
    if artifact is None:
        print(
            "Discovery run aborted — nothing was recorded, so there is nothing to "
            "pin. Re-run /discover, then capture again.",
            file=sys.stderr,
        )
        return 1
    if args.dry_run:
        print(json.dumps(artifact, indent=2))
        print(
            f"[dry-run] detected the {artifact['key']} artifact; nothing saved. "
            "Confirm with the assignee, then re-run without --dry-run to pin.",
            file=sys.stderr,
        )
        return 0
    plan.add_output(artifact)
    complete_ok = True
    if args.complete:
        complete_ok = _complete_captured_task(plan, task_id)
    _save(plan, args)
    if args.complete and complete_ok:
        _emit_sync_progress(plan, [task_id])
    print(json.dumps(artifact, indent=2))
    return 0 if complete_ok else 1


def cmd_pin_output(args: argparse.Namespace) -> int:
    """Commit what a task produced onto the plan (ask-mode capture).

    Used when the output isn't observable from local kit state — e.g. a Workday
    connection or Entra app the assignee created — so the assignee tells us the
    values and we pin them. This is the generic counterpart to capture-setup.
    """
    plan = _load(args)
    attrs: dict = {}
    for kv in (args.attr or []):
        key, sep, val = kv.partition("=")
        if not sep or not key.strip():
            print(f"Invalid --attr {kv!r}; expected a non-empty key=value pair.", file=sys.stderr)
            return 1
        attrs[key.strip()] = val.strip()
    art = plan_artifact(
        args.key, args.kind, attrs,
        produced_by_task_id=args.task,
        inventory_ref=args.inventory_ref,
        source=args.source,
    )
    plan.add_output(art)
    complete_ok = True
    if args.complete:
        complete_ok = _complete_captured_task(plan, args.task)
    _save(plan, args)
    if args.complete and complete_ok:
        _emit_sync_progress(plan, [args.task])
    print(json.dumps(art, indent=2))
    return 0 if complete_ok else 1


def _complete_captured_task(plan: Plan, task_id: str) -> bool:
    try:
        plan.set_task_state(task_id, "Completed")
    except ValueError as exc:
        print(f"Outputs retained; NOT completing {task_id}: {exc}", file=sys.stderr)
        return False
    return True


def cmd_snapshot_config(args: argparse.Namespace) -> int:
    """Print the current config.json snapshot as JSON. Capture this **before** a
    skill runs and pass it to ``capture-setup --before-file`` so the generic
    id+name sweep only pins what actually changed (pre-existing config isn't
    mis-attributed as produced by the task)."""
    print(json.dumps(snapshot_config(args.config), indent=2))
    return 0


def cmd_task_brief(args: argparse.Namespace) -> int:
    """Brief a task's assignee: how to do it, their role, the resolved values it
    consumes (e.g. the env id from setup), and the keys to capture when done."""
    plan = _load(args)
    brief = plan.task_brief(args.task, workspace_config=read_config(args.config))
    if args.json:
        print(json.dumps(brief, indent=2))
        return 0
    print(f"Task {brief['id']}: {brief['title']}")
    if brief.get("description"):
        print(f"  {brief['description']}")
    print(f"  Role: {brief.get('role')}  |  State: {brief.get('state')}")
    if brief.get("blockingReason"):
        print(f"  Not ready to start — waiting on {brief['blockingReason']}")
    if brief.get("firstRunSetup"):
        print(
            "  First-run setup: this plan needs its Power Platform environment "
            "stood up. You can set it up manually in Copilot Studio, or run /setup "
            "to decide or create it — running /setup is the recommended path."
        )
    nudge = brief.get("kitSetup")
    if nudge:
        env = nudge.get("environmentId") or nudge.get("environmentUrl") or "the plan's environment"
        print(f"  First connect your kit: run /setup and choose environment {env}.")
    consumes = brief.get("consumes") or {}
    if consumes:
        print("  Use these values produced by earlier tasks:")
        for key, attrs in consumes.items():
            if attrs:
                vals = ", ".join(f"{ak}={av}" for ak, av in attrs.items())
                print(f"    - {key}: {vals}")
            else:
                print(f"    - {key}: (not produced yet - blocked)")
    if brief.get("produces"):
        print("  When done, capture these outputs: " + ", ".join(brief["produces"]))
    return 0


def cmd_mine(args: argparse.Namespace) -> int:
    plan = _load(args)
    grouped = plan.tasks_for_person(args.person, _csv(args.roles))
    if args.json:
        print(json.dumps(grouped, indent=2))
        return 0
    if not grouped:
        print("No tasks are waiting on you right now.")
        return 0
    print(f"You hold {len(grouped)} role(s) with tasks:\n")
    for role, items in grouped.items():
        print(f"[{role}]")
        for item in items:
            task = item["task"]
            tag = "assigned to you" if item["relation"] == "assigned" else "open to your role"
            waiting = item.get("waitingOn") or []
            blocked = f"  [blocked by {', '.join(waiting)}]" if waiting else ""
            print(f"    - {task['id']}  {task['title']}  ({tag})  [{task.get('state')}]{blocked}")
        print()
    return 0


def cmd_research(args: argparse.Namespace) -> int:
    if not args.toc and not args.fetch:
        print("Provide --toc FILE or --fetch.", file=sys.stderr)
        return 2
    if args.refresh and not args.extract:
        print("--refresh requires --extract; preview mode does not use a research cache.", file=sys.stderr)
        return 2
    toc = None
    if args.toc:
        with open(args.toc, "r", encoding="utf-8") as fh:
            toc = json.load(fh)
    tokens = research.intent_tokens(args.tokens or "")
    if args.extract:
        path = os.path.join(os.path.dirname(args.plan) or ".", os.path.basename(RESEARCH_PATH))
        result = research.collect_research(
            path, tokens=tokens, base=args.base, budget=args.budget,
            toc=toc, refresh=args.refresh,
        )
        result["signals"] = _extract_signals_for(result["pages"])
        print(json.dumps(result, indent=2))
        for error in result["errors"]:
            print(f"Learn research incomplete for {error['url']}: {error['message']}", file=sys.stderr)
        return 1 if result["errors"] else 0
    if toc is None:
        toc = research.fetch_toc(research.toc_url(args.base))
    nodes = research.flatten_toc(toc)
    hrefs = research.select_hrefs(nodes, tokens, budget=args.budget)
    selected = [{"href": h, "url": research.page_url(h, args.base)} for h in hrefs]
    result = {
        "base": args.base,
        "tokens": tokens,
        "totalPages": len(nodes),
        "selected": selected,
    }
    print(json.dumps(result, indent=2))
    return 0


def cmd_setup_tasks(args: argparse.Namespace) -> int:
    """Emit the grounded, attestable-mapped Tasks a system's setup checklist
    decomposes into (Phase 3, model.md). Read-only and plan-free — it never
    touches the plan; the skill runs it, reviews the rows, then feeds them to
    ``add-task``. Default output is JSON; ``--commands`` prints copy-paste
    ``add-task`` lines."""
    try:
        tasks = setup_tasks.system_setup_tasks(
            args.system, skip_foundation=args.skip_foundation
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.commands:
        for task in tasks:
            print(task.add_task_command())
    else:
        print(json.dumps([task.as_dict() for task in tasks], indent=2))
    return 0


def _extract_signals_for(pages: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """Extract candidates from the already-fetched text, without another request."""
    from planner import facts

    roles = facts.role_lexicon() or list(research.DEFAULT_ROLE_LEXICON)
    outputs = facts.output_lexicon() or list(research.DEFAULT_OUTPUT_LEXICON)
    role_hits: dict[str, str] = {}
    output_hits: dict[str, str] = {}
    for item in pages:
        sig = research.extract_signals(item["text"], roles=roles, outputs=outputs)
        for role in sig["roles"]:
            role_hits.setdefault(role, item["href"])
        for out in sig["outputs"]:
            output_hits.setdefault(out, item["href"])
    return {
        "roles": [{"value": k, "href": v} for k, v in role_hits.items()],
        "outputs": [{"value": k, "href": v} for k, v in output_hits.items()],
    }


def cmd_summary(args: argparse.Namespace) -> int:
    """Render and print the plan's Markdown view. **Read-only** — it does NOT
    rewrite ``ESS-scenario-plan.md`` (mutating commands already regenerate it via
    ``save_all``), so running ``summary`` after a Plan editor revises that file
    never clobbers their edits before they can be reconciled (`edit.md`). The
    printed view is enriched from the Learn-research sidecar (best-effort) so it
    matches the file the mutating commands write."""
    plan = _load(args)
    directory = os.path.dirname(os.fspath(args.plan)) or "."
    print(plan.render_summary(research=read_research_context(directory)))
    # Assistant-facing hints on stderr (never part of the sponsor-facing Markdown,
    # which is stdout/file only). The plan Markdown is written by THIS CLI — a
    # subprocess — so the VS Code chat window never surfaces it on its own; it
    # appears only if the agent renders a clickable Markdown link to it in its
    # reply. Hand the agent that exact line so it can't be skipped, and forward-
    # slash the path (VS Code doesn't resolve backslash links). See Bug 7952898.
    if plan.tasks:
        artifact_path = os.path.join(directory, SUMMARY_FILENAME)
        link = artifact_path.replace(os.sep, "/")
        print(
            f"artifact: the maker's plan is saved at {artifact_path}. Surface it in "
            "chat as a downloadable file BEFORE the plan body — render this markdown "
            "line verbatim (do not just print the path in prose):\n"
            f"    \U0001F4C4 [ESS-scenario-plan.md]({link}) — download or edit your plan",
            file=sys.stderr,
        )
        checklist = plan.render_task_checklist()
        if checklist:
            print(
                "readback: use this dependency-ordered checklist for the initial plan "
                "or an explicit full-plan request. After an edit, summarize the changes "
                "and blockers instead of repeating every unchanged task:\n"
                + textwrap.indent(checklist, "    "),
                file=sys.stderr,
            )
    if plan.tasks and not plan.data.get("planId"):
        print(
            "reminder: this draft is saved in this workspace. Share only when the "
            "maker asks; do not publish or activate automatically.",
            file=sys.stderr,
        )
    return 0


def cmd_setup_status(args: argparse.Namespace) -> int:
    """**Read-only** snapshot of the plan's setup state, printed as JSON — the
    pinned environment (if any), the setup task's declared environment key, and
    whether that task is still open. Never mutates or saves the plan (mirrors
    :func:`cmd_summary`).

    Serves two callers that must not parse ``plan.json`` themselves:

    * the ``/setup`` skill's cross-persona **environment-reuse offer** — once the
      admin's setup task has pinned ``primaryEnvironment``, every other maker's
      First-Run ``/setup`` can offer that same environment instead of asking them
      to pick one. ``/setup`` stays plan-*unaware*: it only reads this status and
      never writes the plan.
    * the ``/planner`` reconcile **guard** — on resume / "what am I assigned?",
      the planner folds a finished FRE setup into the plan via
      ``capture-setup --complete`` ONLY while ``setupTaskOpen`` is true, so the
      reconcile is idempotent and a completed setup task is never re-pinned on
      every resume.

    Safe no-op shape when there is no plan or no setup task (``hasPlan`` /
    ``setupTaskOpen`` false, ``environment`` null) so a standalone caller gets a
    well-formed status rather than an error. Always exits 0 — the absence of a
    plan is a valid answer to a query, not a failure."""
    plan = _load(args) if os.path.exists(args.plan) else None
    setup_tid = plan.setup_task_id() if plan else None
    setup_task = plan.task(setup_tid) if (plan and setup_tid) else None
    setup_state = setup_task.get("state") if setup_task else None
    env = plan.output(args.key) if plan else None
    if plan and env is None and args.key == "primaryEnvironment":
        env = plan.output("provisionedEnvironment")
    env_attrs = (env.get("attributes") or {}) if env else {}
    # An Environment artifact may carry only an environmentId and no org URL
    # (e.g. a plan synced from the planner service). The /setup reuse path feeds
    # this value straight into ENV_URL, so advertise the environment as reusable
    # only when a non-empty URL is actually present — otherwise the offer would
    # build requests against an empty endpoint.
    env_url = (env_attrs.get("environmentUrl") or "").strip()
    status = {
        "hasPlan": plan is not None,
        "setupTaskId": setup_tid,
        "setupEnvironmentKey": plan.setup_environment_key(setup_tid) if (plan and setup_tid) else None,
        "setupTaskState": setup_state,
        # Reconcile guard: fold a finished FRE setup into the plan only while the
        # setup task is still open; once Completed, skip so repeated resumes never
        # re-pin the environment (churn-free idempotency).
        "setupTaskOpen": bool(setup_tid) and setup_state != "Completed",
        "firstRunSetupTaskId": next(
            (task["id"] for task in plan.ordered_tasks() if plan.first_run_setup_pending(task["id"])),
            None,
        ) if plan else None,
        "environmentPinned": bool(env_url),
        "agentPinned": bool(plan and (plan.output("essAgent") or plan.output("deployedEssAgent"))),
        "environment": {
            "environmentId": env_attrs.get("environmentId", ""),
            "environmentUrl": env_url,
            "displayName": env_attrs.get("displayName") or env_attrs.get("name", ""),
        } if env else None,
    }
    print(json.dumps(status, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    plan = _load(args)
    errors = plan.validate()
    if not errors:
        print("Plan is valid.")
        return 0
    print("Plan has problems:", file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    return 1


def cmd_export_review(args: argparse.Namespace) -> int:
    review.export_review(_load(args), args.output)
    print(f"Saved spreadsheet review copy: {args.output}")
    return 0


def cmd_review_changes(args: argparse.Namespace) -> int:
    print(json.dumps(review.review_changes(_load(args), args.input), indent=2))
    return 0


# --------------------------------------------------------------------------- #
# Sync seam — the local plan mirrors the planner service. The CLI never talks to
# the network: these commands only translate between the local document and the
# JSON the skill shuttles to/from the planner tools (see planner.sync).
# --------------------------------------------------------------------------- #

def _read_input(source: str | None) -> str:
    """Read a JSON payload from a file path, or stdin when ``source`` is ``-``."""
    if source in (None, "-"):
        return sys.stdin.read()
    with open(source, "r", encoding="utf-8") as fh:
        return fh.read()


def cmd_set_agent_name(args: argparse.Namespace) -> int:
    """Name the ESS agent this plan configures — required before it can be pushed."""
    plan = _load(args)
    try:
        plan.set_configuring_agent_name(args.name)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _save(plan, args)
    print(f"Set configuring agent name to {args.name}")
    return 0


def cmd_export_remote_plan(args: argparse.Namespace) -> int:
    """Print the single create body for pushing this plan (as one object)."""
    plan = _load(args)
    try:
        body = to_remote_plan_body(plan, configuring_agent_name=args.agent_name)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(body, indent=2, ensure_ascii=False))
    return 0


def cmd_import_remote_plan(args: argparse.Namespace) -> int:
    """Rebuild the local cache from a pushed plan's entities.

    Accepts either the two raw tool-result dumps (``--plan-file`` +
    ``--tasks-file``) or a single ``{"plan": <plan>, "tasks": [...]}`` payload / a
    bare plan entity (``--input``). A large tool result is saved as the payload
    followed by a trailing ``{"result": ...}`` envelope, so every source is read
    through :func:`extract_json_payload` (first JSON document wins).
    ``--created-plan-file`` associates an unshared draft with its successful
    create response; normal resume never infers that association from titles.
    The service is the source of truth, so this does **not** gate the write on local validation —
    it only surfaces any validation notes as non-blocking warnings.
    """
    try:
        if args.plan_file:
            plan_entity = extract_json_payload(_read_input(args.plan_file))
            tasks = (
                extract_json_payload(_read_input(args.tasks_file))
                if args.tasks_file
                else None
            )
        else:
            if args.tasks_file:
                print(
                    "--tasks-file requires --plan-file (it names the plan's tasks dump).",
                    file=sys.stderr,
                )
                return 1
            payload = extract_json_payload(_read_input(args.input))
            if isinstance(payload, dict) and "plan" in payload:
                plan_entity = payload.get("plan")
                tasks = payload.get("tasks")
            else:
                # Allow passing the plan entity directly (tasks embedded via expansion).
                plan_entity = payload
                tasks = None
        created_plan = (
            extract_json_payload(_read_input(args.created_plan_file))
            if args.created_plan_file else None
        )
        if args.created_plan_file and not isinstance(created_plan, dict):
            raise ValueError("the successful create response must be a service Plan object")
    except (OSError, ValueError) as exc:
        print(f"Could not read plan payload: {exc}", file=sys.stderr)
        return 1

    try:
        data = hydrate_from_remote(plan_entity, tasks)
        if not data.get("planId") or any(not task.get("id") for task in data["tasks"]):
            raise ValueError("A shared plan ID and task IDs are required; refusing to replace the local plan.")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # The pull rebuilds the cache wholesale from the service, which would revert a
    # completion that was saved locally but never pushed (pendingSync). Carry those
    # forward so an unpushed local completion is never clobbered by the service's
    # stale state; they stay flagged and the agent re-pushes them.
    local_data = None
    if os.path.exists(args.plan):
        try:
            local_data = Plan.load(args.plan).data
        except (OSError, ValueError) as exc:
            print(f"Local plan could not be read; refusing to overwrite it: {exc}", file=sys.stderr)
            return 1
    try:
        data = preserve_local_pending(data, local_data, created_plan=created_plan)
    except ValueError as exc:
        print(f"Local changes kept; cannot replace this plan: {exc}", file=sys.stderr)
        return 1
    preserved = [t.get("id", "") for t in data.get("tasks", []) if t.get("pendingSync")]

    plan = Plan(data)
    plan.save_all(args.plan)
    print(
        f"Imported plan {data.get('planId') or '(no id)'} "
        f"with {len(data.get('tasks', []))} task(s)"
    )
    if preserved:
        print(
            "Preserved unpushed local completion(s): " + ", ".join(preserved)
            + " — still pendingSync; sync them to the shared plan with "
            "complete_project_plan_task (run `pending-sync` for the arguments).",
            file=sys.stderr,
        )
    partial = [task["id"] for task in plan.tasks if task.get("pendingOutputs")]
    if partial:
        print(
            "Partial outputs retained locally, not yet shared: " + ", ".join(partial)
            + ". Finish the task or approve a genuine milestone split; do not fake completion.",
            file=sys.stderr,
        )
    warnings = plan.validate()
    if warnings:
        print("Note — local validation flagged (not blocking the import):", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)
    return 0


def cmd_stamp_remote(args: argparse.Namespace) -> int:
    """Record the service ids/ETag a locally-authored plan now mirrors."""
    plan = _load(args)
    stamp_remote_ids(
        plan,
        project_id=args.project_id,
        plan_id=args.plan_id,
        plan_etag=args.etag,
    )
    _save(plan, args)
    print(f"Stamped remote identity: project={args.project_id} plan={args.plan_id}")
    return 0


def cmd_pending_sync(args: argparse.Namespace) -> int:
    """Print the push backlog: tasks completed locally but not yet confirmed on the
    shared planner, with the exact ``complete_project_plan_task`` arguments.

    **Read-only.** The agent runs this after a capture ``--complete`` (or on
    ``/planner`` entry) to push each pending completion — ``tasks`` is empty when
    nothing is outstanding. Each entry carries the service ``taskId``, the ETag to
    guard the PATCH, and the produced ``outputs`` already in the tool's shape."""
    plan = _load(args)
    print(json.dumps(pending_sync_payload(plan), indent=2))
    return 0


def cmd_mark_synced(args: argparse.Namespace) -> int:
    """Clear the pending-sync flag on a task (or ``--all``) once its completion is
    confirmed on the shared planner.

    Use after a successful ``complete_project_plan_task`` push when a full
    ``import-remote-plan`` re-hydrate isn't being run (the re-hydrate clears the
    flag on its own). An unknown ``--task`` id fails loudly."""
    plan = _load(args)
    if args.all:
        cleared = [t["id"] for t in plan.pending_sync_tasks()]
        for tid in cleared:
            plan.clear_task_pending_sync(tid)
    else:
        if not args.task:
            print("mark-synced requires --task <id> or --all.", file=sys.stderr)
            return 1
        try:
            plan.clear_task_pending_sync(args.task)
        except KeyError:
            print(f"No such task: {args.task!r}.", file=sys.stderr)
            return 1
        cleared = [args.task]
    _save(plan, args)
    if cleared:
        print("Cleared pendingSync: " + ", ".join(cleared))
    else:
        print("No pending-sync tasks to clear.")
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planner", description="ESS Maker Kit planner CLI")
    parser.add_argument("--plan", default=PLAN_PATH, help="path to plan.json")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a new plan")
    p.add_argument("--objective")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("ingest-upload",
                       help="build a plan from a maker-authored uploaded plan (normalized JSON payload)")
    p.add_argument("--input", default="-",
                   help="path to the normalized plan JSON, or '-' for stdin (default)")
    p.add_argument("--force", action="store_true",
                   help="replace an existing plan with the upload")
    p.add_argument("--json", action="store_true",
                   help="print {ingested, gaps} as JSON instead of prose")
    p.set_defaults(func=cmd_ingest_upload)

    p = sub.add_parser("gaps",
                       help="list the intent slots the plan still lacks (questions the skill should ask)")
    p.add_argument("--json", action="store_true",
                   help="print {required, recommended} as JSON instead of prose")
    p.set_defaults(func=cmd_gaps)

    p = sub.add_parser("set-context", help="add or overwrite an intent context entry")
    p.add_argument("--key", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--group")
    p.add_argument("--description")
    p.add_argument("--source", default="User", choices=["User", "Agent", "Discovered"])
    p.set_defaults(func=cmd_set_context)

    p = sub.add_parser(
        "remove-context",
        help="remove a context entry by key (move a scenario/system/dependency out of scope)",
    )
    p.add_argument("--key", required=True,
                   help="scenario id, 'system.<area>', or a 'A -> B' dependency key")
    p.set_defaults(func=cmd_remove_context)

    p = sub.add_parser("add-scenario", help="register a scenario in scope")
    p.add_argument("--id", required=True, help="scenario id, e.g. hr-ticketing")
    p.add_argument("--label", required=True, help="human-readable scenario label")
    p.add_argument("--source", default="User", choices=["User", "Agent", "Discovered"])
    p.set_defaults(func=cmd_add_scenario)

    p = sub.add_parser("add-scenario-dependency", help="record that scenario A depends on scenario B")
    p.add_argument("--scenario", required=True, help="the dependent scenario id")
    p.add_argument("--depends-on", required=True, dest="depends_on", help="the prerequisite scenario id")
    p.add_argument("--kind", default="requires", choices=["requires", "recommends"])
    p.add_argument("--rationale", help="why — cite the PM spec / Learn source")
    p.add_argument("--source", default="Agent", choices=["User", "Agent", "Discovered"])
    p.set_defaults(func=cmd_add_scenario_dependency)

    p = sub.add_parser("check-deps", help="show met and unmet scenario dependencies")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check_deps)

    p = sub.add_parser("add-system", help="record the target system for one scenario/area (scoped key)")
    p.add_argument("--area", required=True, help="scenario id or area slug, e.g. hr-knowledge")
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument("--system", action="append", help="system name; repeat for multiple systems in this area")
    choice.add_argument("--pending", action="store_true", help="record that this system is not known yet; keep planning")
    p.add_argument("--source", default="User", choices=["User", "Agent", "Discovered"])
    p.set_defaults(func=cmd_add_system)

    p = sub.add_parser("add-task", help="add an atomic task (described by title + description)")
    p.add_argument("--id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", help="self-explanatory: what to do and how (incl. which command to run)")
    p.add_argument("--stream", help="workstream/theme label to group this task under in the plan view (e.g. 'Workday', 'Setup', 'Authoring')")
    p.add_argument("--role", help="Learn-grounded role for this task")
    p.add_argument("--person", help="assign directly to a person (oid)")
    p.add_argument("--produces", help="comma-separated output keys")
    p.add_argument("--consumes", help="comma-separated consumed keys")
    p.set_defaults(func=cmd_add_task)

    p = sub.add_parser("update-task", help="update an existing task's content (title/description/produces/consumes)")
    p.add_argument("--id", required=True)
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--produces", help="comma-separated output keys (replaces; empty string clears)")
    p.add_argument("--consumes", help="comma-separated consumed keys (replaces; empty string clears)")
    p.set_defaults(func=cmd_update_task)

    p = sub.add_parser("remove-task", help="remove a task (reconciling a deletion from the plan's Markdown view)")
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_remove_task)

    p = sub.add_parser("assign", help="assign a task to a role and/or person (Flow 1)")
    p.add_argument("--task", required=True)
    p.add_argument("--role")
    p.add_argument("--person")
    p.set_defaults(func=cmd_assign)

    p = sub.add_parser("claim", help="a person claims a pooled task")
    p.add_argument("--task", required=True)
    p.add_argument("--person", required=True)
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("set-state", help="set a task's state")
    p.add_argument("--task", required=True)
    p.add_argument("--state", required=True, choices=["NotStarted", "InProgress", "Completed", "Blocked"])
    p.set_defaults(func=cmd_set_state)

    p = sub.add_parser("capture-setup", help="observe /setup output and pin every id+name artifact in config.json")
    p.add_argument("--task", help="setup task id (default: auto-detect the plan's /setup task)")
    p.add_argument(
        "--key",
        help="environment output key (default: the task's declared setup environment key, otherwise primaryEnvironment)",
    )
    p.add_argument("--config", default=os.path.join(".local", "config.json"))
    p.add_argument("--before", help="JSON snapshot taken before setup (optional)")
    p.add_argument("--before-file", dest="before_file", help="path to a JSON snapshot taken before the action (enables the generic id+name sweep)")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="detect and print artifacts without saving (preview for confirm-before-pin)")
    p.add_argument("--complete", action="store_true", help="mark the task Completed")
    p.set_defaults(func=cmd_capture_setup)

    p = sub.add_parser(
        "setup-status",
        help="read-only JSON: the plan's pinned environment, setup output key + whether the /setup task is still "
             "open (drives the /setup env-reuse offer and the planner reconcile guard)",
    )
    p.add_argument("--key", default="primaryEnvironment",
                   help="environment ledger key to report (default: primaryEnvironment)")
    p.set_defaults(func=cmd_setup_status)

    p = sub.add_parser("capture-discover", help="observe /discover output and pin the tenant inventory summary onto the plan")
    p.add_argument("--task", help="discover task id (default: auto-detect the plan's /discover task)")
    p.add_argument("--key", default="tenantInventory")
    p.add_argument("--results", default=os.path.join("workspace", "discover", "results.json"),
                   help="the /discover results JSON to summarize")
    p.add_argument("--inventory-path", dest="inventory_path", default=None,
                   help="pointer to the durable local inventory mirror recorded on the artifact "
                        "(default: the inventoryPath in config.json, else .local/inventory.json)")
    p.add_argument("--config", default=os.path.join(".local", "config.json"),
                   help="config.json to read inventoryUpdatedAt from")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="detect and print the artifact without saving (preview for confirm-before-pin)")
    p.add_argument("--complete", action="store_true", help="mark the discover task Completed")
    p.set_defaults(func=cmd_capture_discover)

    p = sub.add_parser("snapshot-config", help="print the config.json snapshot (capture before an action for capture-setup --before-file)")
    p.add_argument("--config", default=os.path.join(".local", "config.json"))
    p.set_defaults(func=cmd_snapshot_config)

    p = sub.add_parser("pin-output", help="commit what a task produced onto the plan (ask-mode capture)")
    p.add_argument("--task", required=True)
    p.add_argument("--key", required=True, help="ledger key, e.g. workdayConnection")
    p.add_argument("--kind", required=True, choices=list(ARTIFACT_KINDS))
    p.add_argument("--attr", action="append", help="attribute key=value (repeatable)")
    p.add_argument("--inventory-ref", dest="inventory_ref")
    p.add_argument("--source", default="User", choices=["User", "Agent", "Discovered"])
    p.add_argument("--complete", action="store_true", help="mark the task Completed")
    p.set_defaults(func=cmd_pin_output)

    p = sub.add_parser("task-brief", help="brief an assignee: how, role, consumed values, outputs to capture")
    p.add_argument("--task", required=True)
    p.add_argument("--config", default=os.path.join(".local", "config.json"),
                   help="workspace setup config used to avoid repeating an already-complete binding")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_task_brief)

    p = sub.add_parser("mine", help="show tasks for a person, grouped by role (Flow 2)")
    p.add_argument("--person", required=True)
    p.add_argument("--roles", help="comma-separated roles the person holds")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_mine)

    p = sub.add_parser("research", help="preview or cache intent-scoped Learn research")
    p.add_argument("--tokens", help="intent tokens, e.g. 'workday servicenow'")
    p.add_argument("--toc", help="path to a local toc.json")
    p.add_argument("--fetch", action="store_true", help="fetch the live TOC (network)")
    p.add_argument("--extract", action="store_true",
                   help="return readable pages and candidates, reusing cached research for up to 24 hours")
    p.add_argument("--refresh", action="store_true",
                   help="with --extract, bypass cached TOC/pages and fetch current Learn content")
    p.add_argument("--base", default=research.LEARN_SECTION_BASE)
    p.add_argument("--budget", type=int, default=18)
    p.set_defaults(func=cmd_research)

    p = sub.add_parser(
        "setup-tasks",
        help="decompose a system's setup checklist into grounded, attestable tasks",
    )
    p.add_argument("--system", default="workday",
                   help="setup system whose checklist to decompose (default: workday)")
    p.add_argument("--skip-foundation", action="store_true",
                   help="drop the shared foundation groups (Power Platform environment + "
                        "ESS base agent) already produced by the backbone 'Set up the "
                        "environment' (/setup) task")
    p.add_argument("--commands", action="store_true",
                   help="print copy-paste add-task command lines instead of JSON")
    p.set_defaults(func=cmd_setup_tasks)

    p = sub.add_parser("summary", help="render the plan's Markdown view (ESS-scenario-plan.md) and print it")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("validate", help="validate the plan")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("set-agent-name",
                       help="name the ESS agent this plan configures (required before a sync push)")
    p.add_argument("--name", required=True, choices=list(CONFIGURING_AGENT_CHOICES))
    p.set_defaults(func=cmd_set_agent_name)

    p = sub.add_parser("export-remote-plan",
                       help="print the single create body for pushing this plan (JSON)")
    p.add_argument("--agent-name", dest="agent_name", choices=list(CONFIGURING_AGENT_CHOICES),
                   help="override the plan's configuringAgentName for this export")
    p.set_defaults(func=cmd_export_remote_plan)

    p = sub.add_parser("import-remote-plan",
                       help="rebuild the local cache from a pushed plan's entities (JSON)")
    p.add_argument("--input", default="-",
                   help="path to a {plan, tasks} JSON file, or '-' for stdin (default)")
    p.add_argument("--plan-file", dest="plan_file",
                   help="path to the raw get_project_plan tool-result dump; the CLI "
                        "extracts the payload past any trailing {\"result\": ...} "
                        "envelope (pair with --tasks-file)")
    p.add_argument("--tasks-file", dest="tasks_file",
                   help="path to the raw list_project_plan_tasks tool-result dump "
                        "(used with --plan-file)")
    p.add_argument("--created-plan-file", dest="created_plan_file",
                   help="successful create_project_plan response for this local draft's "
                        "first share; its identity must match the imported plan")
    p.set_defaults(func=cmd_import_remote_plan)

    p = sub.add_parser("stamp-remote",
                       help="record the service ids/ETag this local plan mirrors")
    p.add_argument("--project-id", dest="project_id", required=True)
    p.add_argument("--plan-id", dest="plan_id", required=True)
    p.add_argument("--etag", help="plan ETag for optimistic concurrency (optional)")
    p.set_defaults(func=cmd_stamp_remote)

    p = sub.add_parser(
        "pending-sync",
        help="list completions saved locally but not yet on the shared plan, with "
             "the complete_project_plan_task arguments to sync each (read-only)",
    )
    p.set_defaults(func=cmd_pending_sync)

    p = sub.add_parser(
        "mark-synced",
        help="clear the pendingSync flag on a task once its completion is confirmed "
             "on the shared plan",
    )
    p.add_argument("--task", help="task id to clear (or use --all)")
    p.add_argument("--all", action="store_true", help="clear every pending-sync task")
    p.set_defaults(func=cmd_mark_synced)

    p = sub.add_parser("export-review", help="write a new CSV review copy for Excel or other spreadsheets")
    p.add_argument("--output", required=True, help="new review CSV path (existing reviews are not overwritten)")
    p.set_defaults(func=cmd_export_review)

    p = sub.add_parser("review-changes", help="preview CSV review proposals; never apply them automatically")
    p.add_argument("--input", required=True, help="edited review CSV path")
    p.set_defaults(func=cmd_review_changes)

    return parser


def _configure_io() -> None:
    """Best-effort UTF-8 stdout/stderr so summaries (em-dashes, etc.) print on
    Windows consoles without crashing on cp1252."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_io()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PlanInvalidError as exc:
        print("Refusing to save — the plan would be invalid:", file=sys.stderr)
        for err in exc.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    except (ValueError, KeyError, OSError) as exc:
        print(f"Could not update the plan: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
