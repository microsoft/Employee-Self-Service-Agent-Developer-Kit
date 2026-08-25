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

# Ensure scripts/ is on the path so ``import planner...`` resolves when this
# file is run directly (mirrors scripts/flightcheck/cli.py).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from planner import research
from planner.capture import detect_config_artifacts, snapshot_config
from planner.plan_model import (
    ARTIFACT_KINDS,
    PLAN_PATH,
    SCENARIO_GROUP,
    Plan,
    new_task,
    order_tasks_by_dependency,
    plan_artifact,
    principal_person,
    principal_pool,
)


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _canonical_role(role: str | None) -> str | None:
    """Normalise a role to its exact WeveNova wire id when the registry
    recognises it (so a display name / casing variant like ``Workday
    Administrator`` or ``environment maker`` becomes ``WorkdayAdmin`` /
    ``Environment Maker``). An unrecognised role is passed through verbatim — the
    absent-safe local store still accepts free-form roles."""
    if not role:
        return role
    from planner.roles import DEFAULT_REGISTRY

    hit = DEFAULT_REGISTRY.find(role)
    return hit.role if hit else role


def _store(args: argparse.Namespace):
    """Build the Plan store for this invocation (local file, or WeveNova MCP)."""
    from planner.plan_store import PlanStoreError, make_store

    backend = getattr(args, "store", None) or os.environ.get("PLANNER_STORE", "local")
    try:
        return make_store(
            backend=backend,
            plan_path=args.plan,
            mcp_server=getattr(args, "mcp_server", "weve-plan"),
            mcp_config=getattr(args, "mcp_config", os.path.join(".vscode", "mcp.json")),
            project_id=getattr(args, "project_id", None),
            plan_id=getattr(args, "plan_id", None),
        )
    except PlanStoreError as exc:
        raise SystemExit(f"plan store error: {exc}")


def _load(args: argparse.Namespace) -> Plan:
    from planner.plan_store import PlanStoreError

    store = _store(args)
    try:
        plan = store.load()
    except PlanStoreError as exc:
        raise SystemExit(f"cannot load the plan: {exc}")
    for warning in getattr(store, "warnings", []):
        print(f"warning: {warning}", file=sys.stderr)
    return plan


class PlanInvalidError(Exception):
    """Raised when a mutation would persist an invalid plan (blocks the write)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _save(plan: Plan, args: argparse.Namespace) -> None:
    """Validate, then persist through the active store — never persist a document
    that ``validate`` would reject (over-limit collections, invalid artifact
    kinds/states, orphan artifacts, ...). The store also (re)renders the ``.md``.
    Any non-fatal store notices are printed to stderr."""
    from planner.plan_store import PlanStoreError

    errors = plan.validate()
    if errors:
        raise PlanInvalidError(errors)
    try:
        for notice in _store(args).save(plan):
            print(f"note: {notice}", file=sys.stderr)
    except PlanStoreError as exc:
        raise SystemExit(f"cannot save the plan: {exc}")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_init(args: argparse.Namespace) -> int:
    backend = getattr(args, "store", None) or os.environ.get("PLANNER_STORE", "local")
    if backend == "mcp":
        # ``init`` is the one command allowed to create the *first* WeveNova plan
        # for a project that has none yet (a brand-new project, or one whose only
        # plan is archived so discovery finds none). An existing plan is reused
        # untouched — never recreated, since a blind reconcile would drop its
        # tasks. Binding the plan up front the way the other commands do can't do
        # this (it errors when no plan exists), so use the project-first
        # open-or-create seam.
        from planner.plan_store import PlanStoreError, open_or_create_mcp_plan

        try:
            store, created = open_or_create_mcp_plan(
                plan_path=args.plan,
                mcp_server=getattr(args, "mcp_server", "weve-plan"),
                mcp_config=getattr(args, "mcp_config", os.path.join(".vscode", "mcp.json")),
                project_id=getattr(args, "project_id", None),
                plan_id=getattr(args, "plan_id", None),
                objective=getattr(args, "objective", None),
            )
            plan = store.load()
        except PlanStoreError as exc:
            raise SystemExit(f"plan store error: {exc}")
        for warning in getattr(store, "warnings", []):
            print(f"warning: {warning}", file=sys.stderr)
        plan.write_summary(store.summary_path)
        if created:
            print(
                f"Created a new WeveNova project plan ({store.plan_id}); rendered the plan view."
            )
        else:
            print(
                f"Using the existing WeveNova project plan ({store.plan_id}, owned upstream); "
                "rendered the plan view."
            )
        return 0
    if os.path.exists(args.plan) and not args.force:
        print(f"A plan already exists at {args.plan}. Use --force to overwrite.", file=sys.stderr)
        return 1
    plan = Plan.new(objective=args.objective)
    _save(plan, args)
    print(f"Initialised plan at {args.plan}")
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
    if args.json:
        print(json.dumps(status, indent=2))
        return 0
    met = [e for e in status if e.get("met")]
    unmet = [e for e in status if not e.get("met")]
    if met:
        print("Met scenario dependencies:\n")
        for edge in met:
            print(f"  - {edge['scenario']} {edge['kind']} {edge['dependsOn']}  [met]")
        print()
    if not unmet:
        print("No unmet scenario dependencies.")
        return 0
    print("Unmet scenario dependencies (advise the sponsor to add the prerequisite first):\n")
    for edge in unmet:
        print(f"  - {edge['scenario']} {edge['kind']} {edge['dependsOn']}")
        if edge.get("rationale"):
            print(f"      why: {edge['rationale']}")
        if edge.get("source"):
            print(f"      source: {edge['source']}")
    return 0


def cmd_add_system(args: argparse.Namespace) -> int:
    plan = _load(args)
    plan.set_system(args.area, args.system, source=args.source)
    _save(plan, args)
    print(f"Set system for {args.area!r} = {args.system!r}")
    return 0


def cmd_add_task(args: argparse.Namespace) -> int:
    plan = _load(args)
    assigned: dict | None = None
    role = _canonical_role(args.role)
    if args.person:
        assigned = principal_person(args.person, role_id=role)
    elif role:
        assigned = principal_pool(role)
    plan.add_task(
        new_task(
            args.id,
            args.title,
            description=args.description or "",
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


def cmd_assign(args: argparse.Namespace) -> int:
    plan = _load(args)
    role = _canonical_role(args.role)
    plan.assign_task(args.task, role_id=role, person_oid=args.person)
    _save(plan, args)
    who = args.person or f"{role} (pool)"
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
    """
    plan = _load(args)
    task_id = args.task or plan.setup_task_id()
    if not task_id:
        print("No setup task found on the plan; pass --task <T#>.", file=sys.stderr)
        return 1
    if args.before_file:
        with open(args.before_file, "r", encoding="utf-8") as fh:
            before = json.load(fh)
    elif args.before:
        before = json.loads(args.before)
    else:
        before = {}
    after = snapshot_config(args.config)
    pinned = detect_config_artifacts(before, after, task_id=task_id, env_key=args.key)
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
    if args.complete:
        missing = plan.unresolved_produces(task_id)
        if missing:
            complete_ok = False
            print(
                f"Pinned; NOT completing {task_id} — unresolved produces {missing}. "
                "Pin the rest, then complete.",
                file=sys.stderr,
            )
        else:
            plan.set_task_state(task_id, "Completed")
    _save(plan, args)
    print(json.dumps(pinned, indent=2))
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
        missing = plan.unresolved_produces(args.task)
        if missing:
            complete_ok = False
            print(
                f"Pinned; NOT completing {args.task} — unresolved produces {missing}. "
                "Pin the rest, then complete.",
                file=sys.stderr,
            )
        else:
            plan.set_task_state(args.task, "Completed")
    _save(plan, args)
    print(json.dumps(art, indent=2))
    return 0 if complete_ok else 1


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
    brief = plan.task_brief(args.task)
    if args.json:
        print(json.dumps(brief, indent=2))
        return 0
    print(f"Task {brief['id']}: {brief['title']}")
    if brief.get("description"):
        print(f"  {brief['description']}")
    print(f"  Role: {brief.get('role')}  |  State: {brief.get('state')}")
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
        # Within each role, order producers ahead of the tasks that consume what
        # they produce; independent tasks keep their Learn order.
        ordered = order_tasks_by_dependency([it["task"] for it in items])
        rank = {id(t): i for i, t in enumerate(ordered)}
        items = sorted(items, key=lambda it: rank[id(it["task"])])
        print(f"[{role}]")
        for item in items:
            task = item["task"]
            tag = "assigned to you" if item["relation"] == "assigned" else "open to your role"
            print(f"    - {task['id']}  {task['title']}  ({tag})  [{task.get('state')}]")
        print()
    return 0


def cmd_research(args: argparse.Namespace) -> int:
    if args.toc:
        with open(args.toc, "r", encoding="utf-8") as fh:
            toc = json.load(fh)
    elif args.fetch:
        toc = research.fetch_toc(research.toc_url(args.base))
    else:
        print("Provide --toc FILE or --fetch.", file=sys.stderr)
        return 2
    nodes = research.flatten_toc(toc)
    tokens = research.intent_tokens(args.tokens or "")
    hrefs = research.select_hrefs(nodes, tokens, budget=args.budget)
    selected = [{"href": h, "url": research.page_url(h, args.base)} for h in hrefs]
    result = {
        "base": args.base,
        "tokens": tokens,
        "totalPages": len(nodes),
        "selected": selected,
    }
    if getattr(args, "extract", False):
        result["signals"] = _extract_signals_for(selected)
    print(json.dumps(result, indent=2))
    return 0


def _extract_signals_for(selected: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Fetch each selected page and pull role/output candidates off it, grounded
    to the page they came from. Network + best-effort: pages that fail to fetch
    are skipped, never fatal. The recognition vocabulary comes from the vendored
    facts file (falling back to the module defaults)."""
    from planner import facts

    roles = facts.role_lexicon() or list(research.DEFAULT_ROLE_LEXICON)
    outputs = facts.output_lexicon() or list(research.DEFAULT_OUTPUT_LEXICON)
    role_hits: dict[str, str] = {}
    output_hits: dict[str, str] = {}
    for item in selected:
        try:
            text = research.fetch_page_text(item["url"])
        except Exception:  # noqa: BLE001 — one bad page must not sink the crawl
            continue
        sig = research.extract_signals(text, roles=roles, outputs=outputs)
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
    never clobbers their edits before they can be reconciled (`edit.md`)."""
    plan = _load(args)
    print(plan.render_summary())
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    """Fetch the plan from the active store and (re)materialize the local
    ``ESS-scenario-plan.md`` view.

    This is how the planner **resumes a WeveNova-backed plan**: with ``--store
    mcp`` it reads the configured project plan (context, outputs, status) and its
    tasks from the ``weve-plan`` MCP server — the plan for the project/agent being
    configured — and writes the human view locally so the sponsor can read it.
    Unlike ``summary`` (read-only), ``pull`` deliberately writes the ``.md`` to
    reflect the freshly fetched upstream state; run it at the start of a resume,
    before any local edits exist to reconcile."""
    store = _store(args)
    from planner.plan_store import PlanStoreError

    try:
        plan = store.load()
    except PlanStoreError as exc:
        raise SystemExit(f"cannot fetch the plan: {exc}")
    for warning in getattr(store, "warnings", []):
        print(f"warning: {warning}", file=sys.stderr)
    plan.write_summary(store.summary_path)
    print(plan.render_summary())
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    """Push the **whole local plan** to WeveNova in one pass — the bulk
    counterpart to ``pull``. Reads ``plan.json`` once, opens (or creates) the
    project's WeveNova plan, and reconciles the entire plan up at once: every
    plan-level Context + AcceptanceCriteria entry travels in a **single**
    ``update_project_plan`` write (not one round-trip per field), alongside the
    tasks. Author locally — cheap file writes — then ``push`` once, instead of
    editing straight against ``--store mcp`` where each ``set-context`` is its own
    server round-trip (the wasteful ``W/"5"`` -> ``W/"6"`` etag churn).

    Guards: reusing a project's **existing** plan needs ``--force`` because the
    reconcile deletes upstream tasks absent locally (a blind push could drop a
    second maker's tasks — ``pull`` first to merge). Creating the project's first
    plan needs no flag."""
    from planner.plan_store import (
        LocalPlanStore,
        PlanStoreError,
        open_or_create_mcp_plan,
    )

    if not os.path.exists(args.plan):
        raise SystemExit(f"no local plan at {args.plan} to push — run `init` first.")
    local_plan = LocalPlanStore(args.plan).load()

    errors = local_plan.validate()
    if errors:
        raise PlanInvalidError(errors)

    try:
        store, created = open_or_create_mcp_plan(
            plan_path=args.plan,
            mcp_server=getattr(args, "mcp_server", "weve-plan"),
            mcp_config=getattr(args, "mcp_config", os.path.join(".vscode", "mcp.json")),
            mcp_cache=False,  # don't touch the local cache until we're past the guard
            project_id=getattr(args, "project_id", None),
            plan_id=getattr(args, "plan_id", None),
            objective=local_plan.output_value_or_context("objective"),
        )
    except PlanStoreError as exc:
        raise SystemExit(f"cannot open the WeveNova plan: {exc}")

    if not created and not args.force:
        raise SystemExit(
            f"a WeveNova plan ({store.plan_id}) already exists for this project. "
            "Pushing reconciles it to the local plan and DELETES upstream tasks not "
            "present locally — `pull` first to merge, or re-run with --force to "
            "overwrite it with the local plan."
        )

    # Past the guard: mirror the post-push WeveNova state back into plan.json.
    store.cache_path = args.plan
    try:
        notices = store.save(local_plan)
    except PlanStoreError as exc:
        raise SystemExit(f"cannot push the plan to WeveNova: {exc}")
    for notice in notices:
        print(f"note: {notice}", file=sys.stderr)

    n_ctx = len(local_plan.context)
    n_tasks = len(local_plan.tasks)
    verb = "Created and pushed" if created else "Pushed"
    print(
        f"{verb} the plan to WeveNova ({store.plan_id}): {n_ctx} context "
        f"entr{'y' if n_ctx == 1 else 'ies'} in one write, {n_tasks} task(s). "
        "Local plan.json now mirrors WeveNova."
    )
    return 0


def cmd_activate(args: argparse.Namespace) -> int:
    """Activate the bound WeveNova plan using the current owner's identity."""
    from planner.plan_store import McpPlanStore, PlanStoreError

    store = _store(args)
    if not isinstance(store, McpPlanStore):
        raise SystemExit("activate requires --store mcp (or PLANNER_STORE=mcp).")
    try:
        plan = store.activate()
    except PlanStoreError as exc:
        raise SystemExit(f"cannot activate the plan: {exc}")
    print(
        f"Plan {store.plan_id} is {plan.get('Status', plan.get('status', 'Active'))} "
        f"(ETag {plan.get('ETag', plan.get('etag', '?'))})."
    )
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


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planner", description="ESS Maker Kit planner CLI")
    parser.add_argument("--plan", default=PLAN_PATH, help="path to plan.json (local store) / where the .md view is written")
    parser.add_argument(
        "--store",
        choices=["local", "mcp"],
        default=os.environ.get("PLANNER_STORE", "local"),
        help="where the Plan is persisted: 'local' (plan.json, default) or 'mcp' (WeveNova project plan via the weve-plan MCP server). The ESS-scenario-plan.md view is rendered either way.",
    )
    parser.add_argument("--mcp-server", dest="mcp_server", default="weve-plan", help="MCP server name in .vscode/mcp.json (store=mcp)")
    parser.add_argument("--mcp-config", dest="mcp_config", default=os.path.join(".vscode", "mcp.json"), help="path to the MCP config (store=mcp)")
    parser.add_argument("--project-id", dest="project_id", default=None, help="WeveNova project id (store=mcp); else PLANNER_MCP_PROJECT_ID or discovery")
    parser.add_argument("--plan-id", dest="plan_id", default=None, help="WeveNova plan id (store=mcp); else PLANNER_MCP_PLAN_ID or discovery")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a new plan")
    p.add_argument("--objective")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("set-context", help="add or overwrite an intent context entry")
    p.add_argument("--key", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--group")
    p.add_argument("--description")
    p.add_argument("--source", default="User", choices=["User", "Agent", "Discovered"])
    p.set_defaults(func=cmd_set_context)

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
    p.add_argument("--system", required=True, help="system name, e.g. 'Workday' or 'ServiceNow ITSM'")
    p.add_argument("--source", default="User", choices=["User", "Agent", "Discovered"])
    p.set_defaults(func=cmd_add_system)

    p = sub.add_parser("add-task", help="add an atomic task (described by title + description)")
    p.add_argument("--id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", help="self-explanatory: what to do and how (incl. which command to run)")
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
    p.add_argument(
        "--state",
        required=True,
        choices=["NotStarted", "InProgress", "Completed", "Cancelled"],
    )
    p.set_defaults(func=cmd_set_state)

    p = sub.add_parser("capture-setup", help="observe /setup output and pin every id+name artifact in config.json")
    p.add_argument("--task", help="setup task id (default: auto-detect the plan's /setup task)")
    p.add_argument("--key", default="primaryEnvironment")
    p.add_argument("--config", default=os.path.join(".local", "config.json"))
    p.add_argument("--before", help="JSON snapshot taken before setup (optional)")
    p.add_argument("--before-file", dest="before_file", help="path to a JSON snapshot taken before the action (enables the generic id+name sweep)")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="detect and print artifacts without saving (preview for confirm-before-pin)")
    p.add_argument("--complete", action="store_true", help="mark the task Completed")
    p.set_defaults(func=cmd_capture_setup)

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
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_task_brief)

    p = sub.add_parser("mine", help="show tasks for a person, grouped by role (Flow 2)")
    p.add_argument("--person", required=True)
    p.add_argument("--roles", help="comma-separated roles the person holds")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_mine)

    p = sub.add_parser("research", help="preview Learn page selection from a TOC")
    p.add_argument("--tokens", help="intent tokens, e.g. 'workday servicenow'")
    p.add_argument("--toc", help="path to a local toc.json")
    p.add_argument("--fetch", action="store_true", help="fetch the live TOC (network)")
    p.add_argument("--extract", action="store_true",
                   help="also fetch each selected page and extract role/output candidates (network)")
    p.add_argument("--base", default=research.LEARN_SECTION_BASE)
    p.add_argument("--budget", type=int, default=18)
    p.set_defaults(func=cmd_research)

    p = sub.add_parser("summary", help="render the plan's Markdown view (ESS-scenario-plan.md) and print it")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("pull", help="fetch the plan from the active store (WeveNova MCP with --store mcp) and write the local .md view")
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("push", help="push the whole local plan.json to WeveNova in one pass (bulk counterpart to pull); --force overwrites an existing plan")
    p.add_argument("--force", action="store_true", help="reconcile over an existing WeveNova plan (deletes upstream tasks absent locally)")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser(
        "activate",
        help="activate the bound WeveNova plan as its resource owner before task execution",
    )
    p.set_defaults(func=cmd_activate)

    p = sub.add_parser("validate", help="validate the plan")
    p.set_defaults(func=cmd_validate)

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


if __name__ == "__main__":
    raise SystemExit(main())
