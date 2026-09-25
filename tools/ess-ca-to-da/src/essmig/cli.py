"""Command line entry point.

Three commands:

``vendor``   maintainer-only: refresh the reference data from an ESSVivaCopilot clone.
``inspect``  read the customer's Custom Engine Agent, write a snapshot of what they
             customized, and give an eligibility verdict. Read-only, and the fastest
             way to answer "is this customer ready to migrate, and if not, why not?".
``migrate``  the whole job: discover, merge onto the DA template, emit the package
             and the report.

Nothing in this tool writes to Dataverse or to the customer's tenant. The output
is a package the customer imports themselves.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from essmig import customizations as customizations_module
from essmig import reference as reference_module
from essmig.assessment import Assessment, assess
from essmig.auth import discover_tenant, provider_for, provider_for_target
from essmig.dataverse import DataverseClient
from essmig.deliver import ImportResult, ImportTarget, import_package
from essmig.discovery import (
    AgentMetadata,
    CaComponent,
    DiscoveryResult,
    discover,
    installed_targets,
)
from essmig.ess import TARGETS
from essmig.instructions import keep_target_instructions, skip_instruction_reconciliation
from essmig.merge import Outcome, merge
from essmig.packaging import check_pointers, package_bytes, write_package, zip_package
from essmig.report import summarize, write_reports
from essmig.resolve import console_resolver_factory


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (RuntimeError, ValueError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ess-ca-to-da",
        description="Migrate ESS Custom Engine Agent customizations onto the Declarative Agent.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    vendor = subparsers.add_parser(
        "vendor", help="refresh reference data from an ESSVivaCopilot clone (maintainers)"
    )
    vendor.add_argument("--ess-root", type=Path, required=True)
    vendor.set_defaults(handler=_vendor)

    inspect = subparsers.add_parser(
        "inspect", help="read the customer's agent and report what is customized"
    )
    _add_source_arguments(inspect)
    inspect.add_argument("--out", type=Path, default=Path("out"))
    inspect.set_defaults(handler=_inspect)

    migrate = subparsers.add_parser(
        "migrate", help="produce the Declarative Agent package and the migration report"
    )
    _add_source_arguments(migrate)
    migrate.add_argument("--out", type=Path, default=Path("out"))
    migrate.add_argument(
        "--snapshot",
        type=Path,
        help="use a customizations.json from a previous 'inspect' instead of "
        "connecting to Dataverse",
    )
    migrate.add_argument("--no-zip", action="store_true", help="write the folder but not the zip")
    migrate.add_argument(
        "--keep-instructions",
        action="store_true",
        help="do not use the model to migrate edited agent instructions; keep the "
        "DA's shipped wording and report the instruction edit as a conflict instead "
        "(use when 'gh' Copilot access is unavailable or deterministic output is needed)",
    )
    migrate.add_argument(
        "--non-interactive",
        action="store_true",
        help="never prompt to resolve conflicts; contested spots keep ESS's version "
        "and are listed in the report for a human (the default when output is not a "
        "terminal, e.g. in CI)",
    )
    _add_target_arguments(migrate)
    migrate.set_defaults(handler=_migrate)
    return parser


def _add_target_arguments(parser: argparse.ArgumentParser) -> None:
    """Flags that name and deliver to a target Declarative Agent instance.

    Off by default: without ``--import`` the tool only builds the package, exactly
    as before. With it, the built package is imported into the target agent's Dev
    ring — the tool's one write path.
    """
    parser.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="import the built package into the target Declarative Agent (writes to "
        "the target's Dev ring). Requires --target-environment-id.",
    )
    parser.add_argument(
        "--target-environment-id",
        help="the target Power Platform environment GUID to import the agent into",
    )
    parser.add_argument(
        "--target-tenant-id",
        help="target tenant GUID; defaults to the source environment's tenant "
        "(the source and target share a tenant)",
    )
    parser.add_argument(
        "--target-schema-name",
        help="schema name of the target agent; defaults to the template's "
        "(e.g. gptagent_copilotforemployeeselfservicehr). Override only for a "
        "renamed install.",
    )
    parser.add_argument(
        "--target-api-base",
        help="base URL of the Copilot Studio ALM import API "
        "(default https://api.powerplatform.com; also ESSMIG_TARGET_API_BASE)",
    )


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--environment-url",
        help="Dataverse environment root, e.g. https://contoso.crm.dynamics.com",
    )
    parser.add_argument(
        "--vertical",
        choices=TARGETS,
        default=None,
        help="which ESS agent to migrate: 'core' (the hub/router), 'hr' or 'it' "
        "(the domain agents behind it). Each is migrated independently. Omit this "
        "to auto-detect every ESS agent installed in the environment and migrate "
        "each one into its own subfolder of --out.",
    )
    parser.add_argument(
        "--preferred-solution",
        help="unique name of the customer's preferred (unmanaged) solution; "
        "scopes the migration to the components it contains",
    )


def _vendor(args: argparse.Namespace) -> int:
    written = reference_module.vendor(args.ess_root)
    if not written:
        print("No Declarative Agent templates were found; nothing vendored.", file=sys.stderr)
        return 1
    print(f"Vendored reference data for: {', '.join(written)}")
    return 0


def _inspect(args: argparse.Namespace) -> int:
    client = _client(args)
    auto = args.vertical is None
    verticals = _resolve_verticals(args, client)
    if auto:
        print(f"Detected ESS agent(s): {', '.join(verticals)}\n")
    exit_code = 0
    for vertical in verticals:
        out = args.out / vertical if auto else args.out
        if auto:
            print(f"=== {vertical} ===")
        exit_code = _inspect_one(client, args, vertical, out) or exit_code
    return exit_code


def _inspect_one(
    client: DataverseClient, args: argparse.Namespace, vertical: str, out: Path
) -> int:
    result = discover(client, vertical, preferred_solution=args.preferred_solution)
    reference = reference_module.load(vertical)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "customizations.json"
    path.write_text(json.dumps(_snapshot(result), indent=2), encoding="utf-8")

    merged = merge(
        reference,
        result.components,
        vertical,
        agent_metadata=result.agent,
        merge_instructions=keep_target_instructions,
    )
    outcomes = {component.suffix: component for component in merged.results}

    diff_path = out / "customizations.md"
    diff_path.write_text(
        customizations_module.render_markdown(result, reference.baseline, outcomes),
        encoding="utf-8",
    )

    print(f"Found {len(result.components)} customization(s) in {result.solution_unique_name}:")
    for component in sorted(result.components.values(), key=lambda c: c.schemaname):
        marker = "new" if component.is_net_new else "edited"
        print(f"  [{marker:>6}] {component.component_type_label:<18} {component.suffix}")
    if result.skipped:
        print(f"  ({len(result.skipped)} skipped — see {path.name})")

    verdict = assess(merged)
    verdict_path = out / "assessment.json"
    verdict_path.write_text(json.dumps(verdict.to_json(), indent=2), encoding="utf-8")
    _print_verdict(verdict)

    print(f"\nWrote {path}, {diff_path} and {verdict_path}\n")
    return 0


def _print_verdict(verdict: Assessment) -> None:
    print(f"\n{verdict.verdict}.")
    for heading, items in (
        ("Cannot be migrated", verdict.blockers),
        ("Needs work before publishing", verdict.worklist),
    ):
        if items:
            print(f"\n{heading}:")
            for item in items:
                print(f"  - {item}")


def _migrate(args: argparse.Namespace) -> int:
    if args.snapshot is not None:
        vertical = args.vertical or _snapshot_vertical(args.snapshot)
        return _migrate_one(None, args, vertical, args.out)

    client = _client(args)
    auto = args.vertical is None
    verticals = _resolve_verticals(args, client)
    if auto:
        print(f"Detected ESS agent(s): {', '.join(verticals)}")
        if len(verticals) > 1 and args.do_import and args.target_schema_name:
            raise ValueError(
                "--target-schema-name cannot be combined with auto-detected "
                "multi-agent migration (it would name every agent the same). Run one "
                "agent at a time with --vertical to override a single agent's schema."
            )
    exit_code = 0
    for vertical in verticals:
        out = args.out / vertical if auto else args.out
        if auto:
            print(f"\n=== {vertical} ===")
        exit_code = _migrate_one(client, args, vertical, out) or exit_code
    return exit_code


def _migrate_one(
    client: DataverseClient | None, args: argparse.Namespace, vertical: str, out: Path
) -> int:
    if args.snapshot is not None:
        discovery = _load_snapshot(args.snapshot, vertical)
    else:
        assert client is not None
        discovery = discover(client, vertical, preferred_solution=args.preferred_solution)

    reference = reference_module.load(vertical)
    interactive = not args.non_interactive and sys.stdin.isatty()
    if interactive:
        print(
            "Conflicts (spots you and ESS both changed) will be offered here to resolve; "
            "press Enter to keep ESS's version."
        )
    merged = merge(
        reference,
        discovery.components,
        vertical,
        agent_metadata=discovery.agent,
        merge_instructions=skip_instruction_reconciliation if args.keep_instructions else None,
        resolver_factory=console_resolver_factory() if interactive else None,
    )

    plugin = write_package(out, reference, merged.agent)
    unbound = check_pointers(merged.agent, reference.config)
    if unbound:
        print(
            "warning: these config values are referenced by the agent but not defined, "
            "and must be bound before publishing: " + ", ".join(unbound),
            file=sys.stderr,
        )

    package_path: Path | None = None
    if not args.no_zip:
        package_path = zip_package(plugin, out / f"{reference.da_schemaname}.zip")

    import_result: ImportResult | None = None
    if args.do_import:
        import_result = _deliver(args, reference, package_bytes(plugin))

    markdown, _ = write_reports(
        out, discovery, merged, package_path=package_path, import_result=import_result
    )
    print(summarize(merged.results) or "nothing to migrate")
    _print_verdict(assess(merged))
    if package_path is not None:
        print(f"\nPackage: {package_path}")
    if import_result is not None:
        _print_import(import_result)
    print(f"Report:  {markdown}")
    if merged.count(Outcome.FAILED) or (import_result is not None and not import_result.ok):
        return 1
    return 0


def _deliver(
    args: argparse.Namespace, reference: reference_module.ReferenceSet, package: bytes
) -> ImportResult:
    """Build the target from the flags and import the package into it."""
    if not args.target_environment_id:
        raise ValueError("--import requires --target-environment-id.")

    tenant_id = args.target_tenant_id
    if not tenant_id:
        if not args.environment_url:
            raise ValueError(
                "--import needs a tenant: pass --target-tenant-id, or --environment-url "
                "so the shared tenant can be discovered from the source."
            )
        tenant_id = discover_tenant(args.environment_url.rstrip("/"))

    schema_name = args.target_schema_name or reference.da_schemaname
    api_base = args.target_api_base or os.environ.get("ESSMIG_TARGET_API_BASE")
    target = ImportTarget(
        tenant_id=tenant_id,
        environment_id=args.target_environment_id,
        schema_name=schema_name,
        **({"api_base": api_base} if api_base else {}),
    )
    print(f"\nImporting into target environment {target.environment_id} as {schema_name} ...")
    return import_package(target, package, provider_for_target(tenant_id))


def _print_import(result: ImportResult) -> None:
    status = f" (HTTP {result.status})" if result.status is not None else ""
    outcome = "Imported" if result.ok else "Import FAILED"
    print(f"{outcome}{status}: {result.detail}")
    if result.operation_url:
        print(f"  Track: {result.operation_url}")


def _client(args: argparse.Namespace) -> DataverseClient:
    if not args.environment_url:
        raise ValueError("--environment-url is required unless --snapshot is supplied.")
    return DataverseClient(args.environment_url, provider_for(args.environment_url))


def _resolve_verticals(args: argparse.Namespace, client: DataverseClient) -> list[str]:
    """The agents this run will migrate: the named one, or every one installed."""
    if args.vertical is not None:
        return [args.vertical]
    found = installed_targets(client)
    if not found:
        raise RuntimeError(
            "No ESS Custom Engine Agent solutions (Core, HR or IT) were found in this "
            "environment. Check --environment-url, or name one explicitly with --vertical."
        )
    return found


def _snapshot_vertical(path: Path) -> str:
    """Recover which agent a prior 'inspect' snapshot was taken for."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    vertical = payload.get("vertical")
    if not isinstance(vertical, str) or vertical not in TARGETS:
        raise ValueError(
            f"Cannot tell which agent {path} is for; pass --vertical explicitly."
        )
    return vertical


def _snapshot(result: DiscoveryResult) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "vertical": result.vertical,
        "solution": result.solution_unique_name,
        "components": {
            component_id: component.to_json()
            for component_id, component in result.components.items()
        },
        "skipped": result.skipped,
    }
    if result.agent is not None:
        snapshot["agent"] = result.agent.to_json()
    return snapshot


def _load_snapshot(path: Path, vertical: str) -> DiscoveryResult:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    components = {
        component_id: CaComponent(
            component_id=component_id,
            schemaname=entry.get("schemaname", ""),
            name=entry.get("name", ""),
            component_type=entry.get("component_type"),
            data=entry.get("data"),
            statecode=entry.get("statecode"),
            statuscode=entry.get("statuscode"),
            layers=[{"msdyn_solutionname": name} for name in entry.get("solutions") or []],
        )
        for component_id, entry in (payload.get("components") or {}).items()
    }
    return DiscoveryResult(
        vertical=payload.get("vertical", vertical),
        solution_unique_name=payload.get("solution", ""),
        solution_id="",
        components=components,
        skipped=payload.get("skipped") or [],
        agent=AgentMetadata.from_json(payload.get("agent")),
    )


if __name__ == "__main__":
    raise SystemExit(main())
