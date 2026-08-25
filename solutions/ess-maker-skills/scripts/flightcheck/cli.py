# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — FlightCheck CLI

Entry point for running pre-deployment validation checks.

Usage:
    python scripts/flightcheck/cli.py [--scope SCOPE]

Scopes:
    full            — Run all checks (default)
    prerequisites   — Licenses, roles only
    infrastructure  — Network connectivity probes
    environment     — PP environment, Dataverse, DLP
    solution        — ESS base agent solution installed (ESS-SOLN-*)
    authentication  — Entra ID, SSO, CA policies
    entraapp        — Workday Entra app: scope, consent, assignment (WD-ENTRA-*, WD-ASSIGN-001)
    workdaytenant   — Workday tenant config: API client, Tenant Security (WD-API-CLIENT-001, WD-TENANT-001)
    workdayextension — Workday extension pack: connection auth, Dataverse conn, REST URL, user-context redirect, firewall (WD-CONN-AUTH-001, DV-CONN-001, WD-REST-*, WD-NET-001)
    topics          — New-topic validation: trigger phrases + definition, integration wiring (TOPIC-TRIGGER-*, TOPIC-INTEGRATION-*)
    external        — Integration discovery (flows)
    handoff         — Enabled auto-handoff topics set a concrete target agent id, not the shipped placeholder (TOPIC-020)
    workday         — Workday deep validation
    servicenow      — ServiceNow deep validation
    local           — Local agent file validation
    publishing      — Publishing/QA checklist
    cloudpolicy     — Cloud Policy feedback checks (POL-FB-*)
"""

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

# Ensure scripts/ is on the path so we can import auth
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flightcheck.runner import (
    FlightCheckRunner,
    save_results,
    Status,
    bucket_results,
    BUCKET_ACTION,
    BUCKET_MANUAL,
    BUCKET_PASSED,
)
from flightcheck.graph_client import GraphClient
from flightcheck.pp_admin_client import PPAdminClient, derive_environment_id
from flightcheck.pva_client import PVAClient
from flightcheck.powerplatform_client import PowerPlatformClient
from flightcheck.azure_arm_client import AzureArmClient

# Check modules
from flightcheck.checks.prerequisites import run_prerequisites_checks
from flightcheck.checks.environment import run_environment_checks
from flightcheck.checks.authentication import run_authentication_checks
from flightcheck.checks.external_systems import run_external_systems_checks
from flightcheck.checks.solution import run_solution_checks
from flightcheck.checks.entra_app import run_entra_app_checks
from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks
from flightcheck.checks.agent_handoff import run_handoff_topic_checks
from flightcheck.checks.workday import run_workday_checks
from flightcheck.checks.workday_tenant import run_workday_tenant_checks
from flightcheck.checks.workday_extension import run_workday_extension_checks
from flightcheck.checks.topics import run_topic_checks
from flightcheck.checks.servicenow import run_servicenow_checks
from flightcheck.checks.local_files import run_local_file_checks
from flightcheck.checks.publishing import run_publishing_checks
from flightcheck.checks.licensing import run_licensing_checks
from flightcheck.checks.cloud_policy import run_cloud_policy_checks
from flightcheck.checks.infrastructure import run_infrastructure_checks
from flightcheck import consent


SCOPE_MAP = {
    "prerequisites": [("Prerequisites", run_prerequisites_checks)],
    "infrastructure": [("Infrastructure", run_infrastructure_checks)],
    "environment": [("Environment", run_environment_checks)],
    "solution": [("Solution", run_solution_checks)],
    "authentication": [("Authentication", run_authentication_checks)],
    "entraapp": [("Entra App", run_entra_app_checks)],
    "workdaytenant": [("Workday Tenant", run_workday_tenant_checks)],
    "external": [("External Systems", run_external_systems_checks)],
    "workday": [
        ("External Systems", run_external_systems_checks),
        ("Workday", run_workday_checks),
    ],
    "workdayextension": [
        ("External Systems", run_external_systems_checks),
        ("Workday", run_workday_checks),
        ("Workday Extension", run_workday_extension_checks),
    ],
    "topics": [("Workday Topics", run_topic_checks)],
    "graphconnector": [
        ("External Systems", run_external_systems_checks),
        ("Graph Connector KB", run_graph_connector_kb_checks),
    ],
    "handoff": [("Agent Handoff", run_handoff_topic_checks)],
    "servicenow": [
        ("External Systems", run_external_systems_checks),
        ("ServiceNow", run_servicenow_checks),
    ],
    "local": [("Local Files", run_local_file_checks)],
    "publishing": [("Publishing", run_publishing_checks)],
    "licensing": [("Licensing", run_licensing_checks)],
    "cloudpolicy": [("Cloud Policies", run_cloud_policy_checks)],
}

FULL_SCOPE = [
    ("Prerequisites", run_prerequisites_checks),
    ("Infrastructure", run_infrastructure_checks),
    ("Environment", run_environment_checks),
    ("Solution", run_solution_checks),
    ("Authentication", run_authentication_checks),
    ("Entra App", run_entra_app_checks),
    ("Workday Tenant", run_workday_tenant_checks),
    ("External Systems", run_external_systems_checks),
    ("Workday", run_workday_checks),
    ("Workday Extension", run_workday_extension_checks),
    ("Workday Topics", run_topic_checks),
    ("Graph Connector KB", run_graph_connector_kb_checks),
    ("Agent Handoff", run_handoff_topic_checks),
    ("ServiceNow", run_servicenow_checks),
    ("Local Files", run_local_file_checks),
    ("Licensing", run_licensing_checks),
    ("Publishing", run_publishing_checks),
    ("Cloud Policies", run_cloud_policy_checks),
]

# Scopes whose checks query the Copilot Studio Island Gateway (PVA) and so
# require PVA authentication in main(). Keep in sync with the SCOPE_MAP checks
# that read ``runner.pva``:
#   - local          -> CONFIG-013 (knowledge-source runtime status)
#   - graphconnector -> Graph Connector KB runtime status
#   - handoff        -> TOPIC-020 (agent_handoff.run_handoff_topic_checks)
# "full" always authenticates PVA because it runs all of the above. A scope
# omitted here gets ``runner.pva = None``, so any PVA-dependent check wired
# into it silently returns [] without ever querying the tenant.
PVA_SCOPES = frozenset({"full", "local", "graphconnector", "handoff"})


def _endpoint_systems_for_offer(runner) -> list[str]:
    """External-system names that have a discoverable endpoint, for the consent
    offer. Read-only; never raises (a discovery failure just means no offer)."""
    try:
        from flightcheck.checks.infrastructure import _discover_external_endpoints

        return [ep.system for ep in _discover_external_endpoints(runner)]
    except Exception:  # noqa: BLE001 - discovery is best-effort for the offer
        return []


def _apply_runtime_reachability_consent(args, runner, checks) -> None:
    """Resolve consent for the mutating runtime-reachability probe and record the
    decision on the runner. Consent is ALWAYS surfaced when the egress probe is
    in scope: we prompt on an interactive terminal, announce the mutation when
    the flag forces it on, and explain the skip (plus how to opt in) when we
    cannot ask.

    Sets ``runner.runtime_reachability`` (bool: may the probe create its flow?)
    and ``runner.runtime_reachability_declined`` (bool: surface the skip +
    manual-verification guidance in the report). The probe only ever runs after
    an explicit YES (interactive answer) or an explicit ``--runtime-reachability``
    flag, so a run we could not get consent for stays read-only.
    """
    runner.runtime_reachability = False
    runner.runtime_reachability_declined = False

    # Tri-state flag: True (forced on), False (forced off), None (must offer).
    # getattr keeps this robust for callers that build args without the flag.
    flag = getattr(args, "runtime_reachability", None)

    # The egress probe lives in the Infrastructure category (INFRA-003) and in
    # the Workday category (WD-RUN-001 active connector probe). Consent must
    # be surfaced whenever EITHER mutating probe is in scope, so a Workday-only
    # readiness check asks first and falls back to the passive run-history path
    # on NO, instead of silently requiring the --runtime-reachability flag.
    infra_in_scope = any(fn is run_infrastructure_checks for _, fn in checks)
    workday_in_scope = any(fn is run_workday_checks for _, fn in checks)
    active_probe_in_scope = infra_in_scope or workday_in_scope
    if not active_probe_in_scope:
        runner.runtime_reachability = flag is True
        return

    # The manual IP-allowlist fallback (build_manual_fallback) is an INFRA-003
    # remedy: confirm the environment's egress IP ranges are whitelisted on the
    # external endpoint. When ONLY the Workday active probe is in scope,
    # WD-RUN-001 auto-falls-back to the passive run-history signal on a decline,
    # so no manual step is required (see SKILL.md). Printing the IP-allowlist
    # block there is misdirected, so suppress it for the Workday-only case.
    workday_only = workday_in_scope and not infra_in_scope

    systems = _endpoint_systems_for_offer(runner)
    # Name EVERY discovered system, not just the first: the probe tests all of
    # them, so consent must cover all of them (PR #197 review).
    #
    # WD-RUN-001's active probe reaches Workday through the managed connector it
    # selects from the BAP connection list (pp.get_connections), a source that is
    # independent of the .local/config.json ``connections`` map that
    # _endpoint_systems_for_offer reads. A Workday BAP connection that was never
    # recorded in that config (e.g. connected outside the kit's /connect skill)
    # would otherwise be probed without Workday appearing in the consent prompt.
    # Name Workday explicitly whenever the Workday active probe is in scope so
    # the consent copy can never omit a system the probe will contact.
    if workday_in_scope:
        systems = [*systems, "Workday"]
    label = consent.systems_label(systems)

    # --- Explicit flag wins; the flag is the consent, but never silent. -------
    if flag is True:
        # Passing the flag IS consent — do not re-prompt — but announce exactly
        # what will happen so the tenant mutation is never a surprise.
        runner.runtime_reachability = True
        print(consent.build_forced_on_notice(label))
        return
    if flag is False:
        # Explicit opt-out: surface the skip + manual-verification guidance.
        runner.runtime_reachability_declined = True
        print(consent.build_skip_message(label))
        if not workday_only:
            print(consent.build_manual_fallback(label))
        return

    # --- No flag: consent must be surfaced (flag is None). --------------------
    # ADK/chat path: the skill asks the user conversationally BEFORE the run and
    # passes --runtime-reachability on YES, so reaching here with no flag means
    # the skill did not get a YES. Stay read-only and let the skill own the chat
    # messaging (prompting the non-tty subprocess again would be wrong).
    if getattr(args, "invocation_source", "cli") == "adk":
        return

    # Infrastructure-only scope intentionally skips Dataverse / Power Platform
    # auth unless --runtime-reachability is explicitly passed (see the cli auth
    # block). Without the flag there are no probe tokens, so we cannot run the
    # probe even with a YES. Tell the operator how to opt in rather than
    # prompting for something we cannot honor.
    if getattr(args, "scope", None) == "infrastructure":
        print(consent.build_cannot_prompt_message(label))
        print(consent.build_manual_fallback(label))
        return

    interactive = (
        sys.stdin is not None
        and sys.stdin.isatty()
        and sys.stdout is not None
        and sys.stdout.isatty()
    )

    if not interactive:
        # No TTY (CI / piped): we cannot ask a human. Stay read-only, but explain
        # what did not run and how to opt in (the flag doubles as consent).
        print(consent.build_cannot_prompt_message(label))
        if not workday_only:
            print(consent.build_manual_fallback(label))
        return

    # Interactive terminal: ALWAYS ask before touching the tenant.
    decision = consent.resolve_consent(
        flag,
        endpoints_present=bool(systems),
        interactive=True,
        prompt_fn=lambda: consent.ask_yes_no(label),
    )
    runner.runtime_reachability = decision.enabled
    runner.runtime_reachability_declined = decision.declined

    if decision.declined:
        print(consent.build_skip_message(label))
        if not workday_only:
            print(consent.build_manual_fallback(label))


def open_report_in_browser(output_dir):
    """Open the FlightCheck HTML report in the default browser.

    Uses ``Path.as_uri()`` to build an RFC 8089 ``file://`` URI so paths
    with spaces or non-ASCII characters (e.g. Windows OneDrive paths like
    ``C:\\Users\\foo\\OneDrive - Microsoft Corporation\\...``) open
    reliably across platforms.

    Returns:
        True if a browser tab was launched, False if the report file is
        missing (e.g. FlightCheck aborted before save_results ran) or
        ``webbrowser.open()`` reported it could not find a browser.
    """
    report_path = Path(output_dir) / "report.html"
    if not report_path.exists():
        return False
    return webbrowser.open(report_path.resolve().as_uri())


def _print_checkpoint_list():
    """Print the registered setup checkpoints/families for --list-checkpoints.

    Reads the static registry only — no broad run, no auth. Dynamic families
    print with a ``-*`` suffix (e.g. ``WD-FLOW-*``); fixed checkpoints print as
    their literal ID.
    """
    from flightcheck import registry

    specs = registry.list_checkpoints()
    print("Registered setup checkpoints (run one with --checkpoint <ID>):")
    print()
    print(f"  {'CHECKPOINT':<16} {'PRIORITY':<10} {'CATEGORY':<20} ROLES")
    print("  " + "-" * 76)
    for spec in specs:
        key = f"{spec.key}-*" if spec.is_family else spec.key
        roles = ", ".join(spec.roles) if spec.roles else "-"
        print(f"  {key:<16} {spec.priority:<10} {spec.category_label:<20} {roles}")
    print()
    print("Families (-*) run every emitted member; an exact dynamic ID "
          "(e.g. WD-FLOW-002) runs the family and reports just that row.")


def _print_unknown_checkpoint(target):
    """Print a clear error naming the valid checkpoint IDs/families."""
    from flightcheck import registry

    print(f"ERROR: unknown checkpoint '{target}'.")
    print("Valid checkpoints (use --list-checkpoints for full detail):")
    for spec in registry.list_checkpoints():
        key = f"{spec.key}-*" if spec.is_family else spec.key
        print(f"  {key}")


# ─────────────────────────────────────────────────────────────────────────
# Standalone-scope target selection (Workday SSO app / ServiceNow connection)
# ─────────────────────────────────────────────────────────────────────────
#
# Only the scope-mode main() resolves a selection; --checkpoint mode never
# does. These sets say which --scope values actually run a check that the
# selection scopes, so we don't prompt (or make discovery API calls) on a
# scope that ignores the pin.
_WORKDAY_APP_SCOPES = frozenset({"full", "workday", "authentication", "entraapp"})
_SERVICENOW_SCOPES = frozenset({"full", "servicenow"})

# Sentinel returned by the picker when the operator explicitly chooses "All".
_SELECT_ALL = "__all__"


def _discover_workday_apps(graph) -> list[dict]:
    """Return the federated Workday SAML enterprise apps (candidates the
    WD-CONN-102 selection scopes to), each as ``{appId, displayName, id}``.

    Uses the same Graph listing WD-CONN-102 consumes, so the picker shows
    exactly the set the check would otherwise validate together.
    """
    sps = graph.get_workday_saml_service_principals()
    return [
        {
            "appId": sp.get("appId", ""),
            "displayName": sp.get("displayName", ""),
            "id": sp.get("id", ""),
        }
        for sp in (sps or [])
    ]


def _discover_servicenow_connections(pp_admin, env_id) -> list[dict]:
    """Return the ServiceNow connections in the environment (candidates the
    SN-CONN-* selection scopes to), each as ``{name, displayName, status}``.
    """
    if not env_id or pp_admin is None:
        return []
    from flightcheck.checks.connections import (
        filter_connections_by_connector,
        get_connection_status,
    )

    all_conns = pp_admin.get_connections(env_id)
    if isinstance(all_conns, dict):  # ``{"_error": ...}`` shape
        return []
    conns = filter_connections_by_connector(all_conns, ["service-now", "servicenow"])
    return [
        {
            "name": c.get("name", ""),
            "displayName": c.get("properties", {}).get("displayName", ""),
            "status": get_connection_status(c),
        }
        for c in conns
    ]


def _list_targets(args):
    """Discovery-only entry point for the /flightcheck picker.

    Authenticates the single client needed for ``args.list_targets`` and
    prints ``{"kind": ..., "targets": [...]}`` as JSON on stdout, then
    returns. Any failure prints ``{"kind": ..., "targets": [], "error": ...}``
    so the caller can degrade gracefully. Never runs checks.
    """
    payload = {"kind": args.list_targets, "targets": []}

    config_path = os.path.join(".local", "config.json")
    if not os.path.exists(config_path):
        payload["error"] = ".local/config.json not found. Run /setup first."
        print(json.dumps(payload))
        return
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    env_url = args.environment_url or config.get("dataverseEndpoint", "")
    from auth import discover_tenant

    try:
        tenant_id = discover_tenant(env_url) if env_url else "organizations"
    except Exception:  # noqa: BLE001 — tenant discovery best-effort
        tenant_id = "organizations"

    try:
        if args.list_targets == "workday":
            graph = GraphClient(tenant_id)
            graph.authenticate()
            payload["targets"] = _discover_workday_apps(graph)
        else:  # servicenow
            from auth import authenticate

            dv_token = None
            try:
                dv_token = authenticate(env_url) if env_url else None
            except Exception:  # noqa: BLE001 — dv token only aids env-id derivation
                dv_token = None
            pp_admin = PPAdminClient(tenant_id)
            pp_admin.authenticate()
            env_id = args.environment_id or derive_environment_id(
                env_url, dv_token, pp_admin=pp_admin
            )
            payload["targets"] = _discover_servicenow_connections(pp_admin, env_id)
    except Exception as e:  # noqa: BLE001 — surface discovery failure as JSON
        payload["error"] = str(e)

    print(json.dumps(payload))


def _prompt_choice(candidates: list[dict], *, kind: str):
    """Interactively prompt the operator to pick one target.

    Returns the pin value (appId for Workday, connection name for
    ServiceNow), the ``_SELECT_ALL`` sentinel when the operator picks
    "All", or None on EOF/blank (treated as All).
    """
    label = "Workday SSO app" if kind == "workday" else "ServiceNow connection"
    print(f"\n  Multiple {label}s found. Which one should FlightCheck verify?")
    for i, c in enumerate(candidates, 1):
        if kind == "workday":
            print(f"    {i}. {c.get('displayName') or '(unnamed)'}  "
                  f"(appId={c.get('appId')})")
        else:
            print(f"    {i}. {c.get('displayName') or c.get('name')}  "
                  f"(status={c.get('status')})")
    print(f"    0. All — validate every {label}")
    while True:
        try:
            raw = input("  Enter number [0]: ").strip()
        except EOFError:
            return None
        if raw in ("", "0"):
            return _SELECT_ALL
        if raw.isdigit() and 1 <= int(raw) <= len(candidates):
            c = candidates[int(raw) - 1]
            if kind == "workday":
                return c.get("appId") or _SELECT_ALL
            return c.get("name") or c.get("displayName") or _SELECT_ALL
        print("  Invalid selection — enter a number from the list.")


def _is_interactive() -> bool:
    """True when both stdin and stdout are attached to a TTY.

    The gate for any interactive target prompt so piped runs and the
    installer's captured child process never block waiting on ``input()``.
    """
    return bool(
        getattr(sys.stdin, "isatty", lambda: False)()
        and getattr(sys.stdout, "isatty", lambda: False)()
    )


def _maybe_prompt(candidates: list[dict], *, kind: str, args):
    """Decide whether/how to prompt for a target and return the chosen pin.

    Returns a pin value, the ``_SELECT_ALL`` sentinel, or None (no
    selection made). Prompts only when there is a genuine ambiguity
    (>= 2 candidates) and the terminal is interactive (or the operator
    forced it with ``--select-targets always``).
    """
    if args.select_targets == "never":
        return None
    if not candidates or len(candidates) < 2:
        # Zero or one candidate ⇒ nothing to disambiguate; validating "all"
        # is already the single (or empty) app.
        return None

    interactive = _is_interactive()
    if not interactive:
        flag = "--workday-app-id" if kind == "workday" else "--servicenow-connection"
        print(f"  Multiple {kind} targets found but this is not an interactive "
              f"terminal — validating all. Pass {flag} <value> to scope.")
        return None

    return _prompt_choice(candidates, kind=kind)


def _confirm_persisted_workday_app(app_id: str, graph) -> bool:
    """Show the Workday SSO app FlightCheck will scope to — the one the
    connect/Workday-setup flow persisted — and let the operator confirm it.

    Doubles as a reminder that this is the app subsequent Workday
    configuration steps use, so a stale or wrong pin surfaces before every
    check is silently scoped to it.

    Returns True to proceed with ``app_id`` (confirmed, or non-interactive so
    the installer / a piped run is never blocked). Returns False only when an
    operator at an interactive terminal declines — the caller then falls back
    to the picker so they can choose a different app for this run.
    """
    display = ""
    if graph is not None:
        try:
            for row in _discover_workday_apps(graph):
                if row.get("appId") == app_id:
                    display = row.get("displayName") or ""
                    break
        except Exception:  # noqa: BLE001 — the name is cosmetic; fall back to id
            display = ""

    label = f"{display}  (appId {app_id})" if display else f"appId {app_id}"
    print("\n  Workday SSO app on file (from your setup config):")
    print(f"      {label}")
    print("  FlightCheck and your subsequent Workday configuration will use "
          "this app.")

    if not _is_interactive():
        print("  (non-interactive terminal — using this app. Pass "
              "--workday-app-id <appId> or --select-targets always to change.)")
        return True

    while True:
        try:
            raw = input("  Use this app? [Y/n]: ").strip().lower()
        except EOFError:
            return True
        if raw in ("", "y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please answer 'y' or 'n'.")


def _resolve_workday_app(args, runner):
    """Resolve and apply the Workday SSO-app selection for this run.

    The pin lives on ``runner.config['entraAppId']`` so it flows through the
    existing ``_workday_hints`` path every Workday-SSO-app check reads.

    Precedence:
      1. An explicit ``--workday-app-id`` flag always wins.
      2. Otherwise, when selection is left on the default ``auto``, the app the
         connect/Workday-setup flow already provisioned — the operator's
         persisted ``entraAppId`` resolved by the shared ``_workday_hints``
         (``runner.config`` or ``.local/connect/workday/config.json``, the same
         source WD-CONN-102 / AUTH-005 / WD-ASSIGN-001 scope to) — is offered
         to the operator for confirmation (a reminder that this is the app
         subsequent configuration uses). At an interactive terminal they can
         decline to fall through to the picker; a non-interactive run (the
         installer child process, a pipe) proceeds with it automatically so an
         in-flow readiness report never blocks. Pass ``--select-targets
         always`` to force the picker even when a persisted app exists, or
         ``--workday-app-id`` to override it.
      3. Otherwise the interactive picker runs (``auto`` with no persisted app,
         a declined persisted app, or ``always``). Choosing "All" clears any
         hint so every app is checked.
    """
    graph = getattr(runner, "graph", None)
    cfg = getattr(runner, "config", None)
    chosen = (args.workday_app_id or "").strip()

    # No explicit flag + default (auto) selection: offer the app the
    # connect/setup flow already provisioned (the same pin the Workday-SSO-app
    # checks resolve via ``_workday_hints``). Confirmed / non-interactive ⇒ use
    # it and skip the picker; declined at a TTY ⇒ fall through to the picker.
    # ``always`` still forces the picker; ``never`` opts out.
    if not chosen and args.select_targets == "auto":
        from flightcheck.checks._workday_app_assignment import _workday_hints
        persisted, _ = _workday_hints(cfg)
        if persisted and _confirm_persisted_workday_app(persisted, graph):
            if isinstance(cfg, dict):
                cfg["entraAppId"] = persisted
            print(f"  Scoping Workday SSO-app checks to appId={persisted} "
                  "(from setup config).")
            return

    if not chosen and args.select_targets != "never" and graph is not None:
        try:
            candidates = _discover_workday_apps(graph)
        except Exception as e:  # noqa: BLE001 — discovery failure ⇒ validate all
            print(f"  Target selection: could not list Workday SSO apps ({e}); "
                  "validating all.")
            candidates = []
        choice = _maybe_prompt(candidates, kind="workday", args=args)
        if choice == _SELECT_ALL:
            if isinstance(cfg, dict) and cfg.get("entraAppId"):
                cfg["entraAppId"] = ""
            print("  Validating all Workday SSO apps (no scoping).")
            return
        chosen = choice or ""

    if chosen:
        if isinstance(cfg, dict):
            cfg["entraAppId"] = chosen
        print(f"  Scoping Workday SSO-app checks to appId={chosen}.")


def _resolve_servicenow_connection(args, runner):
    """Resolve and apply the ServiceNow connection selection for this run.

    The pin lives on ``runner.servicenow_connection_pin`` (consumed by
    SN-CONN-* via ``check_connector_connections``). An explicit flag wins;
    otherwise the interactive picker runs.
    """
    pp_admin = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    chosen = (args.servicenow_connection or "").strip()

    if not chosen and args.select_targets != "never" and pp_admin is not None and env_id:
        try:
            candidates = _discover_servicenow_connections(pp_admin, env_id)
        except Exception as e:  # noqa: BLE001 — discovery failure ⇒ validate all
            print(f"  Target selection: could not list ServiceNow connections "
                  f"({e}); validating all.")
            candidates = []
        choice = _maybe_prompt(candidates, kind="servicenow", args=args)
        if choice == _SELECT_ALL:
            print("  Validating all ServiceNow connections (no scoping).")
            return
        chosen = choice or ""

    if chosen:
        runner.servicenow_connection_pin = chosen
        print(f"  Scoping ServiceNow connection checks to '{chosen}'.")


def _resolve_target_selection(args, runner):
    """Standalone-scope-only: pin the Workday SSO app / ServiceNow connection
    the operator wants this run scoped to.

    Reached ONLY from the scope-mode main(); ``--checkpoint`` mode builds its
    own runner and never calls this, so setup gates stay deterministic and
    non-interactive.
    """
    scope = getattr(runner, "scope", "")
    if scope in _WORKDAY_APP_SCOPES:
        _resolve_workday_app(args, runner)
    if scope in _SERVICENOW_SCOPES:
        _resolve_servicenow_connection(args, runner)


def _run_single_checkpoint(args):
    """Run exactly one checkpoint (or family) by ID and report only its result.

    Resolves the target via the registry, initialises ONLY the clients/config
    its transitive prerequisite closure declares (so an Entra-only checkpoint
    runs with no Dataverse endpoint configured), registers the prerequisite +
    owning category functions in canonical order to hydrate shared state, then
    relies on the runner's target filter to keep just the requested rows.

    Always calls sys.exit(): 0 when the checkpoint passes / is manual /
    not-configured, 1 when it fails or errors, 2 for an unknown ID.
    """
    from flightcheck import registry

    target = args.checkpoint
    spec = registry.resolve(target)
    if spec is None:
        _print_unknown_checkpoint(target)
        sys.exit(2)

    plan = registry.transitive_requirements(target)
    needed = plan.clients

    # --- Per-checkpoint config / Dataverse-endpoint gate (not the global one) ---
    config = {}
    config_path = os.path.join(".local", "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    elif plan.requires_config:
        print("ERROR: .local/config.json not found. Run /setup first.")
        sys.exit(1)

    env_url = args.environment_url or config.get("dataverseEndpoint", "")
    if plan.requires_dataverse_endpoint and not env_url:
        print("ERROR: No dataverseEndpoint in .local/config.json.")
        sys.exit(1)

    quiet_auth = getattr(args, "quiet_auth", False)
    if not quiet_auth:
        print()
        print("=" * 64)
        print("  ESS FLIGHTCHECK — Single Checkpoint")
        print("=" * 64)
        print(f"  Checkpoint:  {target}")
        print(f"  Category:    {spec.category_label}")
        if env_url:
            print(f"  Environment: {env_url}")
        print(f"  Clients:     {', '.join(sorted(needed)) or '(none)'}")
        print("=" * 64)
        print()

    dv_token = None
    tenant_id = None
    graph = None
    pp_admin = None
    pva = None
    powerplatform = None

    # Tenant discovery feeds Graph / Power Platform / PVA auth. Normally read
    # from the Dataverse environment's auth challenge; when this checkpoint
    # needs no Dataverse endpoint (Entra-only), fall back to the multi-tenant
    # "organizations" authority so interactive sign-in resolves the operator's
    # home tenant.
    if needed & {registry.GRAPH, registry.PP_ADMIN, registry.PVA, registry.DATAVERSE, registry.POWERPLATFORM}:
        from auth import discover_tenant
        if env_url:
            try:
                tenant_id = discover_tenant(env_url)
            except Exception as e:
                print(f"  Tenant discovery: WARNING — {e}")
                tenant_id = "organizations"
        else:
            tenant_id = "organizations"

    if registry.DATAVERSE in needed and env_url:
        from auth import authenticate
        if not quiet_auth:
            print("Authenticating to Dataverse...")
        try:
            dv_token = authenticate(env_url)
            if not quiet_auth:
                print("  Dataverse: OK")
        except Exception as e:
            print(f"  Dataverse: WARNING — {e}")
            dv_token = None

    if registry.GRAPH in needed:
        if not quiet_auth:
            print("Authenticating to Microsoft Graph...")
        graph = GraphClient(tenant_id)
        try:
            graph.authenticate()
            if not quiet_auth:
                print("  Graph: OK")
        except Exception as e:
            print(f"  Graph: WARNING — {e}")
            graph = None

    if registry.PP_ADMIN in needed:
        if not quiet_auth:
            print("Authenticating to Power Platform Admin API...")
        pp_admin = PPAdminClient(tenant_id)
        try:
            pp_admin.authenticate()
            if not quiet_auth:
                print("  Power Platform: OK")
        except Exception as e:
            print(f"  Power Platform: WARNING — {e}")
            pp_admin = None

    env_id = None
    if registry.PP_ADMIN in needed:
        if args.environment_id:
            env_id = args.environment_id
        elif env_url:
            env_id = derive_environment_id(env_url, dv_token, pp_admin=pp_admin)

    if registry.PVA in needed:
        if not quiet_auth:
            print("Authenticating to Copilot Studio (Island Gateway)...")
        pva = PVAClient(tenant_id, env_url)
        try:
            pva.authenticate()
            if not quiet_auth:
                print("  Copilot Studio: OK")
        except Exception as e:
            print(f"  Copilot Studio: WARNING — {e}")
            pva = None

    if registry.POWERPLATFORM in needed:
        if not quiet_auth:
            print("Authenticating to Power Platform API (capacity allocation)...")
        powerplatform = PowerPlatformClient(tenant_id)
        try:
            powerplatform.authenticate()
            if not quiet_auth:
                print("  Power Platform API: OK")
        except Exception as e:
            print(f"  Power Platform API: WARNING — {e}")
            powerplatform = None

    # --- Build runner with the target filter (hydrate-then-filter) ---
    runner = FlightCheckRunner(
        scope=f"checkpoint:{target}",
        target_matcher=lambda cid: registry.matches(target, cid),
    )
    runner.config = config
    runner.env_url = env_url
    runner.dv_token = dv_token
    runner.env_id = env_id
    runner.graph = graph
    runner.pp_admin = pp_admin
    runner.pva = pva
    runner.powerplatform = powerplatform
    runner.azure_arm = None

    # No runtime-reachability consent here: INFRA-003 is not individually
    # targetable in single-checkpoint mode (there is no INFRA CheckpointSpec in
    # registry.py, and plan.ordered_fns holds only leaf check fns, never
    # run_infrastructure_checks), so the egress probe never runs on this path.
    # Consent is resolved on the --scope path only. If an INFRA checkpoint is
    # ever registered, wire _apply_runtime_reachability_consent here then.

    for label, fn in plan.ordered_fns:
        runner.register(label, fn)

    if not quiet_auth:
        print("\nRunning checkpoint...\n")
    result = runner.run()

    _print_prioritized_summary(result, verbose_manual=True)
    save_results(result, args.output)

    if not result.results:
        print(f"\nNOTE: checkpoint {target} produced no result rows (the owning "
              "check may have skipped it for this tenant state).")
        if not getattr(spec, "is_family", False):
            sys.exit(1)

    # --- Emit anonymous outcome telemetry (best-effort; never affects exit) ---
    # Single-checkpoint mode never auto-opens the HTML report; results.json /
    # report.html are still written to args.output for anyone who wants them.
    # Single-checkpoint runs are the "connect" invocation source: incremental
    # FlightChecks that gate individual setup/connect steps (ADO 7587431).
    # Without this, checkpoint runs were invisible to the Aria dashboards even
    # though they exercise the same checks a full run does.
    if not getattr(args, "no_telemetry", False):
        # Explicit --invocation-source wins; otherwise checkpoint mode attributes
        # the run to "connect" (vs "cli"/"adk"/"installer" for --scope runs).
        _inv_source = getattr(args, "invocation_source", None) or "connect"
        _tele_debug = os.environ.get(
            "ESS_FLIGHTCHECK_TELEMETRY_DEBUG", ""
        ).strip().lower() in ("1", "on", "true", "yes")
        # Resolve the active agent from config (may be empty for Entra-only
        # checkpoints run before /setup writes a full config).
        _agents = config.get("agents", [])
        if not _agents:
            _agent_entry = config.get("agent", {})
            if _agent_entry:
                _agents = [_agent_entry]
        _active = config.get("activeAgent", config.get("agent", {}).get("slug", ""))
        _active_agent = next(
            (a for a in _agents if a.get("slug") == _active),
            _agents[0] if _agents else {},
        )
        # Best-effort tenant display name (OII; privacy-approved). Reuses the
        # already-authenticated Graph client when one was needed; never re-auths.
        # Falls back to the persisted ``.local/.tenant_name`` cache when the
        # live lookup is unavailable (e.g. infra-only scope where ``graph`` is
        # None, or Graph auth failed for lack of ``Organization.Read.All``
        # consent) so previously-resolved tenants keep their name on the event
        # instead of emitting blank. Same-tenant guard is enforced inside the
        # cache helper.
        tenant_name = ""
        try:
            if graph is not None:
                tenant_name = (graph.get_organization() or {}).get("displayName", "") or ""
        except Exception:  # noqa: BLE001 — telemetry name is best-effort
            tenant_name = ""
        try:
            from flightcheck import telemetry

            if not tenant_name and (tenant_id or ""):
                tenant_name = telemetry.get_cached_tenant_name(tenant_id or "")
            elif tenant_name and (tenant_id or ""):
                telemetry.cache_tenant_name(tenant_id or "", tenant_name)

            _tele = telemetry.emit_flightcheck_telemetry(
                result,
                tenant_id=tenant_id or "",
                tenant_name=tenant_name,
                agent_id=_active_agent.get("botId", ""),
                scope=f"checkpoint:{target}",
                agent_count=len(_agents),
                invocation_source=_inv_source,
            )
            if _tele_debug:
                print(
                    f"[telemetry] env={_tele.get('env')} sent={_tele.get('sent')} "
                    f"events={_tele.get('events')} status={_tele.get('status')} "
                    f"reason={_tele.get('reason')}"
                )
        except Exception as _tele_err:  # never break the run
            if _tele_debug:
                print(f"[telemetry] skipped — {type(_tele_err).__name__}: {_tele_err}")

        # Additive adk.* event family (spec Feature #7403772), mirroring the
        # --scope emit so checkpoint runs also count toward the adk.* cubes.
        try:
            import adk_telemetry as _adk

            _agent_id = _active_agent.get("botId", "")
            if tenant_id or tenant_name:
                _adk.set_identity(tenant_id=tenant_id or "", tenant_name=tenant_name)
            _ridx = _adk.next_run_index(_agent_id)
            _adk.emit_flightcheck_run(agent_id=_agent_id, run_index=_ridx)
            _result_map = {
                "READY": "pass",
                "READY_WITH_WARNINGS": "partial",
                "NOT_READY": "fail",
            }
            _adk.emit_flightcheck_result(
                agent_id=_agent_id,
                run_index=_ridx,
                result=_result_map.get(result.overall, "fail"),
                duration_ms=int(getattr(result, "duration_secs", 0) * 1000),
            )
            _adk.flush(timeout=3)
        except Exception:  # noqa: BLE001 — adk telemetry must never break the run
            pass

    sys.exit(1 if result.failed > 0 or result.errors > 0 else 0)


def main():
    # Force UTF-8 console output so summary glyphs (→, •) don't crash on
    # Windows cp1252 terminals. Without this, _print_prioritized_summary
    # raises UnicodeEncodeError before save_results/telemetry are reached.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="ESS FlightCheck — Pre-deployment Validator")
    parser.add_argument(
        "--scope", default=None,
        choices=["full"] + list(SCOPE_MAP.keys()),
        help="Validation scope (default: full). Mutually exclusive with --checkpoint.",
    )
    parser.add_argument(
        "--output", default="workspace/flightcheck",
        help="Output directory (default: workspace/flightcheck)",
    )
    parser.add_argument(
        "--environment-url",
        help="Override the Dataverse environment URL (used by environment_picker.py)",
    )
    parser.add_argument(
        "--environment-id",
        help="Override the Power Platform environment ID (used by environment_picker.py)",
    )
    parser.add_argument(
        "--no-open", action="store_true",
        help="Don't open the HTML report in a browser after running",
    )
    parser.add_argument(
        "--checkpoint",
        help="Run exactly one checkpoint (or a family, e.g. WD-FLOW-*) by ID and "
             "report only its result. Hydrates the checkpoint's declared "
             "prerequisites and initialises only the clients it needs. Mutually "
             "exclusive with --scope.",
    )
    parser.add_argument(
        "--list-checkpoints", action="store_true",
        help="List the registered setup checkpoint IDs and families (no broad "
             "run), then exit.",
    )
    parser.add_argument(
        "--no-telemetry", action="store_true",
        help="Don't emit anonymous FlightCheck outcome telemetry",
    )
    parser.add_argument(
        "--quiet-auth",
        action="store_true",
        help="Suppress routine authentication and single-checkpoint banner output; "
             "interactive prompts, refresh notices, warnings, and failures remain.",
    )
    parser.add_argument(
        "--runtime-reachability",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Runtime-reachability egress probe for INFRA-003. Stands up a "
            "transient test flow, triggers it once to probe each external "
            "endpoint from the Power Platform environment's OWN egress, then "
            "deletes it — the only FlightCheck path that mutates the tenant. "
            "--runtime-reachability forces it on (consent given); "
            "--no-runtime-reachability forces it off. Omit both to be asked "
            "interactively during a normal run; non-interactive runs stay "
            "read-only and report INFRA-003 as MANUAL guidance."
        ),
    )
    parser.add_argument(
        "--invocation-source", default=None,
        choices=["adk", "installer", "cli", "connect"],
        help="How FlightCheck was invoked (adk=slash-command, installer=standalone "
             "installer, cli=direct Python CLI, connect=incremental single-checkpoint "
             "run from a connect/setup skill). Default: cli for --scope runs, connect "
             "for --checkpoint runs.",
    )
    parser.add_argument(
        "--workday-app-id", default=None,
        help="Scope Workday SSO-app checks (WD-CONN-102 and the other "
             "Workday enterprise-app checks) to this Entra enterprise-app "
             "appId. Standalone scope runs only; ignored with --checkpoint.",
    )
    parser.add_argument(
        "--servicenow-connection", default=None,
        help="Scope ServiceNow connection checks (SN-CONN-*) to this "
             "connection (its name/id or a displayName substring). "
             "Standalone scope runs only; ignored with --checkpoint.",
    )
    parser.add_argument(
        "--select-targets", choices=["auto", "always", "never"], default="auto",
        help="When multiple Workday SSO apps / ServiceNow connections exist "
             "and no --workday-app-id/--servicenow-connection is given, prompt "
             "to choose one. auto=prompt on an interactive terminal only "
             "(default); always=prompt (falls back to all on a non-TTY); "
             "never=disable and validate all (legacy behavior).",
    )
    parser.add_argument(
        "--list-targets", choices=["workday", "servicenow"], default=None,
        help="Discovery helper for the /flightcheck picker: authenticate, "
             "print candidate Workday SSO apps or ServiceNow connections as "
             "JSON, then exit without running any checks.",
    )
    args = parser.parse_args()

    # --- Single-checkpoint mode (additive; leaves all --scope behavior intact) ---
    if args.list_checkpoints:
        _print_checkpoint_list()
        sys.exit(0)

    if args.list_targets:
        # Discovery-only mode for the skill-driven picker: authenticate the
        # one client we need, print candidate targets as JSON, and exit. No
        # checks run. Never touches --scope / --checkpoint behavior.
        _list_targets(args)
        sys.exit(0)

    if args.checkpoint:
        if args.scope is not None:
            print("ERROR: --checkpoint and --scope are mutually exclusive.")
            sys.exit(2)
        _run_single_checkpoint(args)
        return  # _run_single_checkpoint always exits; defensive only.

    # Normal scope mode: --scope defaults to "full" when omitted. (Default is
    # None on the parser so checkpoint-mode can detect an explicit --scope.)
    if args.scope is None:
        args.scope = "full"

    # --invocation-source defaults to "cli" for scope-mode runs. (Default is
    # None on the parser so checkpoint-mode can default it to "connect" instead
    # while still honouring an explicit --invocation-source.)
    if args.invocation_source is None:
        args.invocation_source = "cli"

    # Load config
    config_path = os.path.join(".local", "config.json")
    if not os.path.exists(config_path):
        print("ERROR: .local/config.json not found. Run /setup first.")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    infra_only_scope = args.scope == "infrastructure"
    env_url = args.environment_url or config.get("dataverseEndpoint", "")
    if not env_url and not infra_only_scope:
        print("ERROR: No dataverseEndpoint in .local/config.json.")
        sys.exit(1)

    # --- Banner ---
    agents = config.get("agents", [])
    active = config.get("activeAgent", config.get("agent", {}).get("slug", ""))
    if not agents:
        # Backward compat: single agent in config
        agent_entry = config.get("agent", {})
        if agent_entry:
            agents = [agent_entry]

    print()
    print("=" * 64)
    print("  ESS FLIGHTCHECK — Pre-deployment Validation")
    print("=" * 64)
    if len(agents) == 1:
        print(f"  Agent:       {agents[0].get('name', 'N/A')}")
    else:
        print(f"  Agents:      {len(agents)} discovered")
        for a in agents:
            marker = "->" if a.get("slug") == active else "  "
            print(f"    {marker} {a.get('name', 'Unknown')}")
    print(f"  Environment: {env_url}")
    print(f"  Scope:       {args.scope}")
    print("=" * 64)
    print()

    if infra_only_scope:
        # Infrastructure scope skips auth to stay fast and read-only. The one
        # exception is the INFRA-003 egress probe: when explicitly opted in with
        # --runtime-reachability it needs Dataverse + Power Platform tokens to
        # stand up its transient flow, so acquire just those (no Graph / PVA).
        graph = None
        tenant_id = None
        dv_token = None
        pp_admin = None
        env_id = args.environment_id or None
        if getattr(args, "runtime_reachability", None) is True and env_url:
            from auth import authenticate, discover_tenant

            print("Authenticating to Dataverse (runtime-reachability probe)...")
            dv_token = authenticate(env_url)
            tenant_id = discover_tenant(env_url)

            print("Authenticating to Power Platform Admin API...")
            pp_admin = PPAdminClient(tenant_id)
            try:
                pp_admin.authenticate()
                print("  Power Platform: OK")
            except Exception as e:
                print(f"  Power Platform: WARNING — {e}")
                print("  (Runtime-reachability probe can't run without Power "
                      "Platform auth — INFRA-003 will report MANUAL guidance)")
                pp_admin = None

            if not args.environment_id:
                env_id = derive_environment_id(env_url, dv_token, pp_admin=pp_admin)
        else:
            print(
                "Skipping Dataverse/Graph/Power Platform auth for infrastructure scope."
            )
    else:
        # --- Authenticate ---
        from auth import authenticate, discover_tenant

        print("Authenticating to Dataverse...")
        dv_token = authenticate(env_url)

        tenant_id = discover_tenant(env_url)
        print(f"Tenant: {tenant_id}")

        # Initialize clients
        print("Authenticating to Microsoft Graph...")
        graph = GraphClient(tenant_id)
        try:
            graph.authenticate()
            print("  Graph: OK")
        except Exception as e:
            print(f"  Graph: WARNING — {e}")
            print("  (Some checks will be skipped)")
            # Discard the unauthenticated client so Graph-dependent checks see a
            # clean None and emit SKIPPED, rather than each call raising
            # "Call authenticate() first". Mirrors the pp_admin / powerplatform /
            # azure_arm failure handling below.
            graph = None

        print("Authenticating to Power Platform Admin API...")
        pp_admin = PPAdminClient(tenant_id)
        try:
            pp_admin.authenticate()
            print("  Power Platform: OK")
        except Exception as e:
            print(f"  Power Platform: WARNING — {e}")
            print("  (Some checks will be skipped)")
            pp_admin = None

        # Derive the BAP environment ID. This MUST run after pp_admin is
        # authenticated: the correct id comes from the BAP env list
        # (matched on linkedEnvironmentMetadata.instanceUrl), not from the
        # Dataverse WhoAmI OrganizationId (which is a different guid for
        # almost every tenant — see derive_environment_id docstring).
        #
        # derive_environment_id intentionally tolerates pp_admin=None and
        # falls back to the WhoAmI/OrganizationId path so that operators
        # whose Power Platform sign-in failed (network issue, cancelled
        # browser, MSAL error) can still run the substantial fraction of
        # FlightCheck that doesn't need pp_admin — PRE-* (license SKUs),
        # AUTH-*, WD-ENV-* (Workday env vars / ISU format), WD-WF-*
        # (Workday SOAP runtime), and CONFIG-* (local agent / topic /
        # knowledge source). Erroring out here would block those.
        print("Deriving Power Platform environment ID...")
        if args.environment_id:
            env_id = args.environment_id
            print(f"Environment ID: {env_id} (provided via --environment-id)")
        else:
            env_id = derive_environment_id(env_url, dv_token, pp_admin=pp_admin)
            if env_id and pp_admin is not None:
                print(f"Environment ID: {env_id}")
            elif env_id:
                # pp_admin is None: we fell back to WhoAmI/OrganizationId.
                # That value is wrong for BAP admin calls AND for any URL
                # that embeds an env id (Copilot Studio, maker portal, ...).
                print(
                    f"Environment ID: {env_id} (Dataverse OrganizationId fallback "
                    "— Power Platform sign-in failed, so BAP-scoped checks "
                    "(ENV-*, EXT-*, WD-CONN-*) will be skipped)"
                )
            elif pp_admin is not None:
                # BAP auth succeeded but no env matched the Dataverse hostname.
                # Usually means the signed-in user lacks admin access on the
                # env hosting this Dataverse instance. Tell the operator how
                # to override so deep links and BAP-scoped checks still work.
                print(
                    f"WARNING: Could not find a BAP environment whose linked "
                    f"Dataverse instance matches {env_url}. You may not have "
                    "Power Platform admin access on that environment. "
                    "BAP-scoped checks (ENV-*, EXT-*, WD-CONN-*) will be skipped "
                    "and Copilot Studio deep links will fall back to the "
                    "homepage. To override, pass --environment-id <guid> "
                    "(find it in the Power Platform admin center or in the "
                    "Copilot Studio bot URL: "
                    "https://copilotstudio.microsoft.com/environments/<guid>/bots/...)."
                )
            else:
                print(
                    f"WARNING: Could not derive environment ID for {env_url}. "
                    "BAP-scoped checks (ENV-*, EXT-*, WD-CONN-*) will be skipped; "
                    "license, auth, Workday env-var, Workday SOAP, and local-file "
                    "checks will still run."
                )

    # Gate PVA (Copilot Studio Island Gateway) auth on scope.
    # Only CONFIG-013 needs PVA today, and it lives in run_local_file_checks.
    # Authenticating unconditionally would prompt for a second interactive login
    # on scopes like --scope prerequisites that don't need it.
    pva = None
    if infra_only_scope:
        print("Skipping Copilot Studio auth for infrastructure scope.")
    elif args.scope in PVA_SCOPES:
        print("Authenticating to Copilot Studio (Island Gateway)...")
        pva = PVAClient(tenant_id, env_url)
        try:
            pva.authenticate()
            if pva.is_configured:
                print("  Copilot Studio: OK")
            else:
                print("  Copilot Studio: WARNING — Could not discover gateway URL")
                print("  (Knowledge source status check will use local-only validation)")
        except Exception as e:
            print(f"  Copilot Studio: WARNING — {e}")
            print("  (Knowledge source status check will use local-only validation)")
            pva = None
    else:
        print("Skipping Copilot Studio auth (not required for this scope).")

    # Gate the PayG billing clients (PRE-005) on scope. Only the
    # prerequisites checks read them, and each is a separate interactive
    # sign-in (Power Platform API + Azure ARM are distinct audiences), so
    # don't prompt on scopes that won't run PRE-005. Mirrors the PVA gating.
    powerplatform = None
    azure_arm = None
    if args.scope in ("full", "prerequisites"):
        print("Authenticating to Power Platform API (billing policies)...")
        powerplatform = PowerPlatformClient(tenant_id)
        try:
            powerplatform.authenticate()
            print("  Power Platform API: OK")
        except Exception as e:
            print(f"  Power Platform API: WARNING — {e}")
            print("  (PRE-005 PayG check will be skipped)")
            powerplatform = None

        print("Authenticating to Azure (subscription health)...")
        azure_arm = AzureArmClient(tenant_id)
        try:
            azure_arm.authenticate()
            print("  Azure: OK")
        except Exception as e:
            print(f"  Azure: WARNING — {e}")
            print("  (PRE-005 will report PayG subscription health as unverifiable)")
            azure_arm = None

    # --- Build runner ---
    runner = FlightCheckRunner(scope=args.scope)
    runner.config = config
    runner.env_url = env_url
    runner.dv_token = dv_token
    runner.env_id = env_id
    runner.graph = graph
    runner.pp_admin = pp_admin
    runner.pva = pva
    runner.powerplatform = powerplatform
    runner.azure_arm = azure_arm

    # --- Target selection (standalone scope runs only) ---
    # Pin the Workday SSO app / ServiceNow connection the operator wants this
    # run scoped to (explicit flag > persisted setup config on default `auto` >
    # interactive picker). This is reached ONLY from the scope-mode main();
    # --checkpoint mode builds its own runner and never calls this, keeping
    # setup gates deterministic.
    _resolve_target_selection(args, runner)

    # Register checks based on scope
    if args.scope == "full":
        checks = FULL_SCOPE
    else:
        checks = SCOPE_MAP.get(args.scope, FULL_SCOPE)

    # Resolve consent for the mutating runtime-reachability probe (INFRA-003)
    # before any check runs. This is the only FlightCheck path that writes to
    # the tenant, so it never proceeds without an explicit YES.
    _apply_runtime_reachability_consent(args, runner, checks)

    for category, fn in checks:
        runner.register(category, fn)

    # --- Execute ---
    print("\nRunning checks...\n")
    result = runner.run()

    # --- Print summary ---
    _print_prioritized_summary(result)

    # Save results
    save_results(result, args.output)

    # Emit anonymous outcome telemetry (best-effort; never affects exit code).
    if not args.no_telemetry:
        # Telemetry status is internal detail makers shouldn't normally see;
        # only surface it when explicitly debugging telemetry.
        _tele_debug = os.environ.get(
            "ESS_FLIGHTCHECK_TELEMETRY_DEBUG", ""
        ).strip().lower() in ("1", "on", "true", "yes")
        # Resolve the active agent once, up front, so both the legacy and the
        # adk.* telemetry blocks can use it even if the first block raises early.
        active_agent = next(
            (a for a in agents if a.get("slug") == active),
            agents[0] if agents else {},
        )
        # Best-effort tenant display name (OII; privacy-approved). Reuses the
        # already-authenticated Graph client's /organization record — no extra
        # auth. Falls back to the persisted ``.local/.tenant_name`` cache when
        # ``graph`` is None or the live lookup fails (e.g. Graph auth was
        # skipped or ``Organization.Read.All`` isn't consented on this tenant)
        # so previously-resolved tenants keep their name instead of blank.
        # Never blocks the run.
        tenant_name = ""
        try:
            if graph is not None:
                tenant_name = (graph.get_organization() or {}).get("displayName", "") or ""
        except Exception:  # noqa: BLE001 — telemetry name is best-effort
            tenant_name = ""
        try:
            from flightcheck import telemetry

            if not tenant_name and tenant_id:
                tenant_name = telemetry.get_cached_tenant_name(tenant_id)
            elif tenant_name and tenant_id:
                telemetry.cache_tenant_name(tenant_id, tenant_name)

            _tele = telemetry.emit_flightcheck_telemetry(
                result,
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                agent_id=active_agent.get("botId", ""),
                scope=args.scope,
                agent_count=len(agents),
                invocation_source=args.invocation_source,
            )
            if _tele_debug:
                print(
                    f"[telemetry] env={_tele.get('env')} sent={_tele.get('sent')} "
                    f"events={_tele.get('events')} status={_tele.get('status')} "
                    f"reason={_tele.get('reason')}"
                )
        except Exception as _tele_err:  # never break the run
            if _tele_debug:
                print(f"[telemetry] skipped — {type(_tele_err).__name__}: {_tele_err}")

        # Additive adk.* event family (spec Feature #7403772). Emitted alongside
        # the legacy ESSMakerKit.FlightCheck.* events; never affects the run.
        try:
            import adk_telemetry as _adk

            _agent_id = active_agent.get("botId", "")
            if tenant_id or tenant_name:
                _adk.set_identity(tenant_id=tenant_id, tenant_name=tenant_name)
            _ridx = _adk.next_run_index(_agent_id)
            _adk.emit_flightcheck_run(agent_id=_agent_id, run_index=_ridx)
            _result_map = {
                "READY": "pass",
                "READY_WITH_WARNINGS": "partial",
                "NOT_READY": "fail",
            }
            _adk.emit_flightcheck_result(
                agent_id=_agent_id,
                run_index=_ridx,
                result=_result_map.get(result.overall, "fail"),
                duration_ms=int(getattr(result, "duration_secs", 0) * 1000),
            )
            _adk.flush(timeout=3)
        except Exception:  # noqa: BLE001 — adk telemetry must never break the run
            pass
    else:
        if os.environ.get(
            "ESS_FLIGHTCHECK_TELEMETRY_DEBUG", ""
        ).strip().lower() in ("1", "on", "true", "yes"):
            print("[telemetry] disabled via --no-telemetry")

    # Open the HTML report only when the run includes a MANUAL check — those
    # need the browser's rich remediation view. Runs with no manual items are
    # fully covered by the compact chat table (skip with --no-open too).
    if not args.no_open and result.manual > 0:
        open_report_in_browser(args.output)

    # Exit code
    sys.exit(1 if result.failed > 0 else 0)


def _print_prioritized_summary(result, *, verbose_manual=False):
    """Print a triage-first summary that mirrors the HTML layout.

    Three sections, biggest signal first:
      1. Verdict banner (one line).
      2. Counts strip.
      3. ACTION REQUIRED — full per-row detail (Failed / Error).
      4. NEEDS MANUAL VERIFICATION — one line per row (Warning /
         Manual / NotConfigured).
      5. PASSED — count only (includes Passed + Skipped); point to
         report.html for the list.

    The goal is for an operator scanning the terminal to see, in
    order: am I OK? what must I fix? what must I verify? — without
    having to read every passing row.
    """
    buckets = bucket_results(result.results)
    action = buckets[BUCKET_ACTION]
    manual = buckets[BUCKET_MANUAL]
    passed = buckets[BUCKET_PASSED]

    print()
    print("=" * 64)
    print("  FLIGHTCHECK SUMMARY")
    print("=" * 64)

    # Verdict line — single most important signal in the terminal.
    if result.overall == "READY":
        print("  [READY] Ready for deployment")
        if manual:
            print(f"          ({len(manual)} item(s) need manual "
                  "verification -- see below)")
    elif result.overall == "READY_WITH_WARNINGS":
        print(f"  [WARN]  Ready with warnings -- {result.warnings} "
              "warning(s) to verify")
    else:
        # Headline counts only the blocking items (failures + errors).
        # Warnings live in the manual-verification section and aren't
        # blockers, so counting them here would overstate the action
        # load.
        failing = result.failed + result.errors
        word = "issue" if failing == 1 else "issues"
        print(f"  [FAIL]  Not ready -- {failing} {word} need "
              "attention")

    print()
    # Counts strip — every status in one line so the operator can
    # cross-reference with the detail sections below.
    print(f"  Failed: {result.failed}   Errored: {result.errors}   "
          f"Warnings: {result.warnings}   Manual: {result.manual}   "
          f"NotConfigured: {result.not_configured}   "
          f"Skipped: {result.skipped}   Passed: {result.passed}")
    print(f"  Total checks: {result.total}   "
          f"Duration: {result.duration_secs}s")
    print("=" * 64)

    # Section 1 — ACTION REQUIRED (full detail)
    if action:
        print()
        print(f"  ACTION REQUIRED ({len(action)})")
        print("  " + "-" * 62)
        for r in action:
            tag = _status_tag(r.status)
            role_text = f" | {', '.join(r.roles)}" if r.roles else ""
            print(f"  {tag} {r.checkpoint_id} [{r.priority}{role_text}]: {r.result}")
            if r.remediation:
                # Indent multi-line remediation under the arrow so
                # multi-step fixes stay visually grouped with their
                # finding.
                lines = r.remediation.splitlines()
                print(f"       -> {lines[0]}")
                for cont in lines[1:]:
                    print(f"          {cont}")
            print()

    # Section 2 — NEEDS MANUAL VERIFICATION. In scope runs this stays a
    # one-liner per row (the full prose lives in report.html so the terminal
    # stays scannable). In single-checkpoint mode (verbose_manual) we print
    # the full result + verification steps inline so the manual steps surface
    # directly in Copilot chat — no HTML popup needed.
    if manual:
        print()
        print(f"  NEEDS MANUAL VERIFICATION ({len(manual)})")
        print("  " + "-" * 62)
        for r in manual:
            tag = _status_tag(r.status)
            role_text = f" | {', '.join(r.roles)}" if r.roles else ""
            if verbose_manual:
                print(f"  {tag} {r.checkpoint_id} [{r.priority}{role_text}]: "
                      f"{r.result}")
                if r.remediation:
                    # Indent multi-line remediation under the arrow so the
                    # verification steps stay grouped with their finding
                    # (mirrors the ACTION REQUIRED section).
                    lines = r.remediation.splitlines()
                    print(f"       -> {lines[0]}")
                    for cont in lines[1:]:
                        print(f"          {cont}")
                print()
            else:
                print(f"  {tag} {r.checkpoint_id} [{r.priority}{role_text}]: "
                      f"{r.description}")
        if not verbose_manual:
            print("  (Open report.html for the full result + verification "
                  "steps.)")

    # Section 3 — PASSED (count only; the operator doesn't need to
    # scroll past 200+ green rows to find what needs their attention).
    print()
    print(f"  PASSED ({len(passed)})")
    print("  " + "-" * 62)
    if passed:
        print("  See report.html for the full list of passing checks.")
    else:
        print("  No passing checks in this run.")
    print()


def _status_tag(status: str) -> str:
    """Return a 6-char tag in [BRACKETS] for terminal alignment.

    Matches the existing [PASS]/[FAIL]/[WARN]/[INFO] convention used
    elsewhere in cli.py so the report visually fits the rest of the
    terminal output.
    """
    return {
        Status.FAILED.value: "[FAIL]",
        Status.ERROR.value: "[ERR ]",
        Status.WARNING.value: "[WARN]",
        Status.MANUAL.value: "[MAN ]",
        Status.NOT_CONFIGURED.value: "[CFG ]",
        Status.SKIPPED.value: "[SKIP]",
        Status.PASSED.value: "[PASS]",
    }.get(status, "[?   ]")


if __name__ == "__main__":
    main()
