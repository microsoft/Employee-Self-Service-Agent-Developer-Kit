# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Optional OOTB Workday topics installer.

Deterministically copies selected ready-made Workday sample topics from the
vendored ``src/examples/ess-samples/Workday`` tree into the agent's working
``topics/`` folder, ready for ``push.py`` to publish.

WHY THIS SCRIPT EXISTS
----------------------
The optional installer (setup skill 5b) used to let the assistant hand-copy
and name files from a prose playbook. Free-form name derivation produced
mangled slugs such as ``w-or-kd-ay-ge-tu-se-rp-ro-fi-le.mcs.yml`` (letters
chopped into 2-char groups). push.py builds a topic's Dataverse schema name
and display name from its filename, so a mangled filename corrupts the
topic's identity. This script removes the assistant from the naming loop:
filenames follow the kit's topic convention (PascalCase, alphanumeric — see
``src/skills/topics/create/SKILL.md``), which also yields clean schema names.

TOPICS ONLY - NOT TEMPLATE CONFIGS
----------------------------------
A Workday topic (the adaptive-dialog conversation logic) calls a Workday
"scenario template" (``msdyn_employeeselfservicetemplateconfigs``) to talk to
Workday. Those scenario templates are *managed* components delivered by the
Workday extension pack installed in setup skill 5 (their meta.json carries
``"ismanaged": true``). They cannot be created per-agent — attempting to do
so returns HTTP 400 (duplicate). The sample folders ship the template XML
purely as reference. Therefore this installer copies **only** the topic YAML
and relies on the extension pack for the scenario templates it references.

SUBSTITUTIONS
-------------
Each sample ``topic.yaml`` is rewritten before being written out:
  1. Schema prefix: sample cross-topic references
     ``msdyn_copilotforemployeeselfservicehr.topic.X`` are re-pointed at the
     target agent's own schema name (a no-op when they already match).
  2. ``<TENANT_NAME>`` placeholder -> the configured Workday tenant.

This module performs pure local file operations (no network / auth), so it is
fully unit-testable. The caller runs ``push.py --only-from <manifest>``
afterwards to publish exactly the topics written here.
"""

import argparse
import json
import os
import re
import sys

# The fixed schema prefix used throughout the vendored HR sample topics.
# Cross-topic dialog references look like "<SAMPLE_SCHEMA>.topic.<Name>".
SAMPLE_SCHEMA = "msdyn_copilotforemployeeselfservicehr"

# Category folder -> friendly key.
CATEGORY_DIRS = {
    "EmployeeScenarios": "employee",
    "ManagerScenarios": "manager",
}

DEFAULT_MANIFEST = os.path.join(".local", "setup", "ootb-push-manifest.txt")


def solution_root():
    """Absolute path to the ess-maker-skills solution root (scripts/..)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def samples_dir(root=None):
    """Absolute path to the vendored Workday samples tree."""
    root = root or solution_root()
    return os.path.join(root, "src", "examples", "ess-samples", "Workday")


def topic_basename(folder_name):
    """Convert a sample folder name to a clean PascalCase topic base name.

    Strips every non-alphanumeric character (hyphens, spaces), matching the
    kit's topic naming convention. Examples:
      WorkdayGetUserProfile           -> WorkdayGetUserProfile
      WorkdayManagersdirect-CompanyCode -> WorkdayManagersdirectCompanyCode
    """
    return re.sub(r"[^0-9A-Za-z]", "", folder_name)


def rewrite_topic(content, schema_name, tenant):
    """Apply the two required substitutions to a sample topic's YAML text."""
    out = content.replace(
        SAMPLE_SCHEMA + ".topic.", schema_name + ".topic."
    )
    if tenant:
        out = out.replace("<TENANT_NAME>", tenant)
    return out


def discover(root=None):
    """Discover installable sample scenarios.

    Returns a list of dicts sorted by (category, folder), each:
      {category, folder, basename, topic_src}
    Only folders that contain a ``topic.yaml`` are included.
    """
    base = samples_dir(root)
    found = []
    for dirname, category in sorted(CATEGORY_DIRS.items()):
        cat_dir = os.path.join(base, dirname)
        if not os.path.isdir(cat_dir):
            continue
        for folder in sorted(os.listdir(cat_dir)):
            folder_path = os.path.join(cat_dir, folder)
            topic_src = os.path.join(folder_path, "topic.yaml")
            if not os.path.isfile(topic_src):
                continue
            found.append({
                "category": category,
                "folder": folder,
                "basename": topic_basename(folder),
                "topic_src": topic_src,
            })
    return found


def _norm(name):
    """Loose key for matching a user-supplied scenario name."""
    return re.sub(r"[^0-9a-z]", "", name.lower())


def select(scenarios, categories=None, names=None):
    """Filter discovered scenarios by category and/or explicit name list.

    categories: iterable of {'employee','manager'} (None = no category filter).
    names: iterable of scenario identifiers matched loosely against both the
           folder name and the PascalCase basename (None = no name filter).
    When both are None, returns everything.
    """
    cats = set(categories) if categories else None
    wanted = {_norm(n) for n in names} if names else None
    out = []
    for s in scenarios:
        if cats is not None and s["category"] not in cats:
            continue
        if wanted is not None and not (
            _norm(s["folder"]) in wanted or _norm(s["basename"]) in wanted
        ):
            continue
        out.append(s)
    return out


def _already_installed(basename, agent_dir):
    """True if a topic with this base name already exists (working/baseline)."""
    fname = basename + ".mcs.yml"
    return (
        os.path.isfile(os.path.join(agent_dir, "topics", fname))
        or os.path.isfile(os.path.join(agent_dir, ".baseline", "topics", fname))
    )


def plan(selected, agent_dir):
    """Compute per-scenario actions without touching disk.

    Returns a list of dicts: {folder, basename, dest_rel, status} where
    status is 'write' (new topic) or 'skip-exists' (already installed).
    """
    actions = []
    for s in selected:
        basename = s["basename"]
        dest_rel = "topics/" + basename + ".mcs.yml"
        status = "skip-exists" if _already_installed(basename, agent_dir) \
            else "write"
        actions.append({
            "folder": s["folder"],
            "category": s["category"],
            "basename": basename,
            "topic_src": s["topic_src"],
            "dest_rel": dest_rel,
            "status": status,
        })
    return actions


def install(selected, agent_dir, schema_name, tenant, dry_run=False):
    """Write selected topics into the agent's working tree.

    Returns {written: [rel...], skipped: [{basename, reason}...]}.
    Skips scenarios whose target topic already exists (idempotent).
    """
    written = []
    skipped = []
    for action in plan(selected, agent_dir):
        if action["status"] == "skip-exists":
            skipped.append({
                "basename": action["basename"],
                "reason": "already installed",
            })
            continue

        dest_rel = action["dest_rel"]
        dest_abs = os.path.join(agent_dir, *dest_rel.split("/"))
        if not dry_run:
            with open(action["topic_src"], "r", encoding="utf-8") as f:
                content = f.read()
            content = rewrite_topic(content, schema_name, tenant)
            os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
            with open(dest_abs, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        written.append(dest_rel)
    return {"written": written, "skipped": skipped}


def write_manifest(manifest_path, rel_paths):
    """Write a push scope manifest (one topic relative path per line)."""
    os.makedirs(os.path.dirname(os.path.abspath(manifest_path)), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="") as f:
        f.write("# OOTB Workday topics to push (scoped). Generated file.\n")
        for rel in rel_paths:
            f.write(rel + "\n")


def _resolve_config(args):
    """Resolve (agent_dir, schema_name, tenant) from flags or config files."""
    agent_dir = args.agent_dir
    schema_name = args.schema_name
    tenant = args.tenant

    if not agent_dir or not schema_name:
        # Lazy import so the pure functions stay import-safe under test.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from auth import load_config
        cfg = load_config()
        agent_dir = agent_dir or cfg["agent"]["folder"]
        schema_name = schema_name or cfg["agent"]["schemaName"]

    if tenant is None:
        wd_path = os.path.join(
            ".local", "connect", "workday", "config.json")
        if os.path.isfile(wd_path):
            try:
                with open(wd_path, "r", encoding="utf-8") as f:
                    tenant = json.load(f).get("tenant")
            except (OSError, json.JSONDecodeError):
                tenant = None
    return agent_dir, schema_name, tenant


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="Install ready-made Workday sample topics (topics only).")
    parser.add_argument("--list", action="store_true",
                        help="List available scenarios and exit.")
    parser.add_argument("--all", action="store_true",
                        help="Install all employee + manager scenarios.")
    parser.add_argument("--employee", action="store_true",
                        help="Install all employee scenarios.")
    parser.add_argument("--manager", action="store_true",
                        help="Install all manager scenarios.")
    parser.add_argument("--scenarios", default=None,
                        help="Comma-separated scenario names to install.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be written without writing.")
    parser.add_argument("--manifest-out", default=DEFAULT_MANIFEST,
                        help="Where to write the push scope manifest.")
    parser.add_argument("--agent-dir", default=None,
                        help="Override agent folder (default: from config).")
    parser.add_argument("--schema-name", default=None,
                        help="Override agent schema name (default: from config).")
    parser.add_argument("--tenant", default=None,
                        help="Override Workday tenant (default: from config).")
    parser.add_argument("--samples-root", default=None,
                        help="Override the solution root that holds src/examples.")
    parser.add_argument("--json", action="store_true",
                        help="Emit a machine-readable JSON summary to stdout.")
    args = parser.parse_args(argv)

    scenarios = discover(args.samples_root)

    if args.list:
        for s in scenarios:
            print(f"  [{s['category']:8}] {s['folder']}  ->  "
                  f"topics/{s['basename']}.mcs.yml")
        print(f"\n{len(scenarios)} scenario(s) available. Select with "
              f"--all, --employee, --manager, or --scenarios A,B,C.")
        return 0

    categories = []
    if args.all or args.employee:
        categories.append("employee")
    if args.all or args.manager:
        categories.append("manager")
    names = [n.strip() for n in args.scenarios.split(",")] \
        if args.scenarios else None

    if not categories and not names:
        parser.error("select scenarios with --all, --employee, --manager, "
                     "or --scenarios A,B,C (use --list to see options).")

    selected = select(scenarios, categories or None, names)
    if not selected:
        print("No matching scenarios. Use --list to see available names.")
        return 1

    agent_dir, schema_name, tenant = _resolve_config(args)
    result = install(selected, agent_dir, schema_name, tenant,
                     dry_run=args.dry_run)

    if result["written"] and not args.dry_run:
        write_manifest(args.manifest_out, result["written"])

    if args.json:
        print(json.dumps({
            "written": result["written"],
            "skipped": result["skipped"],
            "manifest": (args.manifest_out
                         if result["written"] and not args.dry_run else None),
            "dryRun": args.dry_run,
        }, indent=2))
    else:
        verb = "Would write" if args.dry_run else "Wrote"
        print(f"\n{verb} {len(result['written'])} topic(s):")
        for rel in result["written"]:
            print(f"  + {rel}")
        if result["skipped"]:
            print(f"\nSkipped {len(result['skipped'])} "
                  f"already-installed topic(s):")
            for s in result["skipped"]:
                print(f"  - {s['basename']} ({s['reason']})")
        if result["written"] and not args.dry_run:
            print(f"\nManifest: {args.manifest_out}")
            print("Next: python scripts/push.py --only-from "
                  f"{args.manifest_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
