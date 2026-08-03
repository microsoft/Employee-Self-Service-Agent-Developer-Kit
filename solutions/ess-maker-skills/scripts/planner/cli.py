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
    python scripts/planner/cli.py add-task --id T1 --title "..." --skill onboarding --role power-platform-admin --produces primaryEnvironment
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
from planner.capture import detect_environment, snapshot_config
from planner.plan_model import (
    ARTIFACT_KINDS,
    PLAN_PATH,
    SCENARIO_GROUP,
    Plan,
    action_external,
    action_kit_skill,
    action_manual,
    action_portal,
    new_task,
    plan_artifact,
    principal_person,
    principal_pool,
)


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _load(args: argparse.Namespace) -> Plan:
    return Plan.load_or_new(args.plan)


def _save(plan: Plan, args: argparse.Namespace) -> None:
    plan.save_all(args.plan)


def _build_action(args: argparse.Namespace) -> dict:
    if getattr(args, "skill", None):
        return action_kit_skill(args.skill)
    kind = getattr(args, "action_kind", None)
    ref = getattr(args, "ref", None)
    if kind == "portal":
        return action_portal(ref or "")
    if kind == "external":
        return action_external(ref)
    return action_manual(ref)


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
    if args.person:
        assigned = principal_person(args.person, role_id=args.role)
    elif args.role:
        assigned = principal_pool(args.role)
    plan.add_task(
        new_task(
            args.id,
            args.title,
            description=args.description or "",
            action=_build_action(args),
            assigned_to=assigned,
            produces=_csv(args.produces),
            consumes=_csv(args.consumes),
        )
    )
    _save(plan, args)
    print(f"Added task {args.id!r}: {args.title!r}")
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    plan = _load(args)
    plan.assign_task(args.task, role_id=args.role, person_oid=args.person)
    _save(plan, args)
    who = args.person or f"{args.role} (pool)"
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
    plan.set_task_state(args.task, args.state)
    _save(plan, args)
    print(f"Task {args.task!r} -> {args.state}")
    return 0


def cmd_capture_setup(args: argparse.Namespace) -> int:
    """Observe-mode capture for the /setup -> environmentId hand-off.

    Reads the current .local/config.json as the "after" snapshot; the "before"
    is empty (setup has just run). The skill confirms with the assignee before
    this is called, then shows the pinned artifact.
    """
    plan = _load(args)
    before = json.loads(args.before) if args.before else {}
    after = snapshot_config(args.config)
    artifact = detect_environment(before, after, task_id=args.task, key=args.key)
    if artifact is None:
        print("No environment change detected in config.json; nothing to pin.", file=sys.stderr)
        return 1
    plan.add_output(artifact)
    if args.complete:
        plan.set_task_state(args.task, "Completed")
    _save(plan, args)
    print(json.dumps(artifact, indent=2))
    return 0


def cmd_pin_output(args: argparse.Namespace) -> int:
    """Commit what a task produced onto the plan (ask-mode capture).

    Used when the output isn't observable from local kit state — e.g. a Workday
    connection or Entra app the assignee created — so the assignee tells us the
    values and we pin them. This is the generic counterpart to capture-setup.
    """
    plan = _load(args)
    attrs: dict = {}
    for kv in (args.attr or []):
        if "=" in kv:
            k, v = kv.split("=", 1)
            attrs[k.strip()] = v.strip()
    art = plan_artifact(
        args.key, args.kind, attrs,
        produced_by_task_id=args.task,
        inventory_ref=args.inventory_ref,
        source=args.source,
    )
    plan.add_output(art)
    if args.complete:
        plan.set_task_state(args.task, "Completed")
    _save(plan, args)
    print(json.dumps(art, indent=2))
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
    action = brief.get("action") or {}
    if action.get("kind") == "kitSkill":
        print(f"  Do it by running: /{action.get('skill')}")
    elif action.get("ref"):
        print(f"  How: {action.get('kind')} - {action['ref']}")
    print(f"  Role: {brief.get('role')}  |  State: {brief.get('state')}")
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
    plan = _load(args)
    plan.write_summary(os.path.join(os.path.dirname(args.plan) or ".", "summary.md"))
    print(plan.render_summary())
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
    parser.add_argument("--plan", default=PLAN_PATH, help="path to plan.json")
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

    p = sub.add_parser("add-task", help="add an atomic task")
    p.add_argument("--id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description")
    p.add_argument("--skill", help="kit skill that performs this task")
    p.add_argument("--action-kind", choices=["kitSkill", "manual", "portal", "external"])
    p.add_argument("--ref", help="doc/portal URL for a non-skill action")
    p.add_argument("--role", help="Learn-grounded role for this task")
    p.add_argument("--person", help="assign directly to a person (oid)")
    p.add_argument("--produces", help="comma-separated output keys")
    p.add_argument("--consumes", help="comma-separated consumed keys")
    p.set_defaults(func=cmd_add_task)

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

    p = sub.add_parser("capture-setup", help="observe /setup output and pin the environment")
    p.add_argument("--task", required=True)
    p.add_argument("--key", default="primaryEnvironment")
    p.add_argument("--config", default=os.path.join(".local", "config.json"))
    p.add_argument("--before", help="JSON snapshot taken before setup (optional)")
    p.add_argument("--complete", action="store_true", help="mark the task Completed")
    p.set_defaults(func=cmd_capture_setup)

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

    p = sub.add_parser("summary", help="render summary.md and print it")
    p.set_defaults(func=cmd_summary)

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
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
