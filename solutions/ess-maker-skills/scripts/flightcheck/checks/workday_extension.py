# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Workday Extension Pack Validation (skill-5).

Programmatic + attestation checks for the ``install-workday-extension-pack``
setup skill (master-checklist rows **S5.1 through S5.8**). Skill-5 reuses three
checkpoints already owned by ``checks/workday.py`` (``WD-PKG-001`` for S5.1,
``WD-CONN-012`` for S5.2, ``WD-FLOW-*`` for S5.6) and mints the five below, all
emitted by :func:`run_workday_extension_checks` and each runnable in isolation
via ``--checkpoint``:

  * ``WD-CONN-AUTH-001`` (S5.3) — the Workday connection uses **Microsoft Entra
    ID Integrated** authentication. **Always MANUAL echo:** the Power Platform
    admin API does not expose a documented, kit-verifiable fingerprint for the
    ``shared_workdaysoap`` "Microsoft Entra ID Integrated" auth type (the
    validated ``flightcheck_pp_admin.yaml`` cassette contains no Workday
    connection), so — per the cardinal rule in ``scripts/flightcheck/AGENTS.md``
    (never assert a verdict from an unconfirmed API response shape) — this
    checkpoint echoes the observed ``connectionParametersSet.name`` for the
    operator to confirm, rather than PASS/FAIL on a guessed value.
  * ``DV-CONN-001`` (S5.4) — the Workday SOAP connection reference reported by
    the Declarative Agent minimalBots components API is bound (``connectionId``
    present), and its owner is echoed so the operator can confirm it is their
    **own** account. Programmatic PASS/FAIL on the validated minimalBots
    components read (same endpoint + ``connectionReferenceChanges`` shape as the
    shipped native ``DA-CONN-001`` check).
  * ``WD-REST-001`` (S5.5) — the captured ``restBaseUrl`` is present and
    **trimmed to** ``/api``. Pure-config check, no client.
  * ``WD-REST-002`` (S5.7) — the agent's ``user-context-setup.mcs.yml`` topic
    contains a ``BeginDialog`` redirect to the Workday user-context system topic
    (``WorkdaySystemGetUserContextV2`` on the simplified pack). Pure local-file
    check; SKIPPED on the legacy install path.
  * ``WD-NET-001`` (S5.8) — the Workday REST + SOAP endpoints are allowlisted at
    the corporate firewall. **Always MANUAL attestation:** the kit has no
    reliable probe (a local reachability test proves only the dev machine's
    egress, not the managed-connector outbound path), so it echoes the endpoints
    that InfoSec/IT must allowlist.

Design invariants (per ``scripts/flightcheck/AGENTS.md``):
  * **Never raise** — the dispatcher wraps every emitter so an unexpected
    failure degrades to a WARNING for that checkpoint instead of aborting the
    whole run.
  * **One CheckResult per checkpoint** (principle 7).
  * **No guessed API shapes** — the two API-backed checks read documented fields
    only (minimalBots ``connectionReferenceChanges`` connector/connection ids; BAP
    ``connectionParametersSet.name`` / ``createdBy``), and degrade gracefully
    when a client is unavailable.
  * **Every** ``CheckResult`` declares ``roles=`` (enforced by
    ``tests/flightcheck/test_check_roles.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..runner import CheckResult, Priority, Role, Status
from ._da_connection_refs import read_active_agent_connection_references
from ..agent_scope import resolve_agent_directory, validate_agent_slug

DOC_BASE = (
    "https://learn.microsoft.com/en-us/copilot/microsoft-365/"
    "employee-self-service"
)
_DOC_SIMPLIFIED = f"{DOC_BASE}/workday-simplified-setup"

_CATEGORY = "Workday Extension"

# All four maker-owned rows (S5.3-S5.5, S5.7) are gated as "Environment Maker"
# in tasks.md; the FlightCheck role for that persona is ESS_MAKER (matches
# skill-2's ESS-SOLN-001).
_MAKER_ROLES = [Role.ESS_MAKER.value]
# S5.8 is gated "InfoSec/IT" in tasks.md, but there is no InfoSec Role enum
# value. POWER_PLATFORM_ADMIN is the closest infrastructure-owning role in the
# enum — the Power Platform admin owns the managed-connector egress and supplies
# the outbound IP ranges to the network team — and the remediation text names
# InfoSec/IT explicitly as the party who performs the firewall change.
_NET_ROLES = [Role.POWER_PLATFORM_ADMIN.value]

_NOT_CAPTURED = "\u2014 not captured yet"

# ---- Microsoft-shipped simplified extension-pack fingerprints ----
# The Workday OAuthUser (SOAP) connection reference the simplified pack ships.
_WORKDAY_AUTH_REF_SUFFIX = "ff0df"
_WORKDAY_RUNTIME_REF_LOGICAL_NAME = (
    "msdyn_sharedworkdaysoap_workdayruntime"
)
# The Workday SOAP connection reference the Declarative Agent reports via the
# minimalBots components API (connector ``shared_workdaysoap``).
_WORKDAY_CONNECTOR_SUFFIX = "/apis/shared_workdaysoap"
_REF_SUFFIX_RE = re.compile(r"_([0-9a-f]{5})$")

# ---- Local user-context topic (WD-REST-002) ----
_AGENTS_ROOT = "workspace/agents"
_INSTALLED_AGENTS_ROOT = ".local/agents"
_USER_CONTEXT_FILE = "user-context-setup.mcs.yml"
_SCHEMA_NAME_RE = re.compile(r"(?m)^\s*schemaName:\s*['\"]?([^'\"\s]+)")

_CONN_AUTH_DESC = (
    "Workday connection authentication type is Microsoft Entra ID Integrated"
)
_DV_CONN_DESC = (
    "Workday SOAP connection reference bound to a connection you own"
)
_REST_URL_DESC = "Workday REST base URL present and trimmed to '/api'"
_REDIRECT_DESC = (
    "User-context topic redirects to the Workday user-context system topic"
)
_NET_DESC = "Workday REST + SOAP endpoints allowlisted at the firewall"

_REDIRECT_REMEDIATION = (
    "Wire the user-context redirect: save a rollback checkpoint "
    "(scripts/checkpoint.py), then set the agent's "
    "topics/user-context-setup.mcs.yml OnRedirect to a BeginDialog that calls "
    "the installed Workday user-context system topic, and push "
    "(scripts/push.py). See the connect skill step 3 (§3.5d)."
)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _selected_agent_slug(runner) -> str:
    config = getattr(runner, "config", None) or {}
    slug = (
        getattr(runner, "agent_slug", None)
        or config.get("activeAgent")
        or (config.get("agent") or {}).get("slug")
    )
    return validate_agent_slug(str(slug)) if slug else ""


def _installed_user_context_dialogs(agent_slug: str) -> list[str]:
    agent_dir = resolve_agent_directory(
        Path(_INSTALLED_AGENTS_ROOT),
        agent_slug,
    )
    topics_dir = agent_dir / "topics"
    if not topics_dir.is_dir():
        return []

    dialogs: set[str] = set()
    for topic_file in sorted(topics_dir.glob("*.mcs.yml")):
        try:
            text = topic_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = _SCHEMA_NAME_RE.search(text)
        dialog = (
            match.group(1)
            if match
            else topic_file.name.removesuffix(".mcs.yml")
        )
        normalized = re.sub(r"[^a-z0-9]", "", dialog.casefold())
        if "workday" in normalized and "usercontext" in normalized:
            dialogs.add(dialog)
    return sorted(dialogs)


def _fmt(config, key: str) -> str:
    """Return the captured config value for ``key`` or a not-captured marker."""
    value = (config or {}).get(key)
    if value in (None, ""):
        return _NOT_CAPTURED
    return str(value)


def _ref_suffix(logical_name) -> str | None:
    """Return the trailing ``_<5hex>`` suffix of a connection-reference logical
    name (e.g. ``…_ff0df`` -> ``ff0df``), or ``None`` if it doesn't match."""
    if not logical_name:
        return None
    match = _REF_SUFFIX_RE.search(str(logical_name))
    return match.group(1) if match else None


def _is_workday_auth_ref(logical_name) -> bool:
    normalized = str(logical_name or "").casefold()
    return (
        _ref_suffix(logical_name) == _WORKDAY_AUTH_REF_SUFFIX
        or normalized == _WORKDAY_RUNTIME_REF_LOGICAL_NAME.casefold()
    )


def _host_of(url: str) -> str:
    """Return the host portion of an ``https://host/…`` URL for display."""
    match = re.match(r"https?://([^/]+)", str(url).strip())
    return match.group(1) if match else str(url)


def _resolve_owner(props: dict) -> str:
    """Return the most useful owner identity available on a BAP connection.

    Admin-scope connection listings frequently return ``accountName: null``
    even when the connection has a clear creator, so fall back through
    ``accountName`` -> ``createdBy.userPrincipalName`` ->
    ``createdBy.displayName`` -> ``"(unknown owner)"`` (mirrors WD-CONN-101's
    ``_resolve_owner`` in checks/workday.py).
    """
    account = props.get("accountName")
    if account:
        return account
    created_by = props.get("createdBy") or {}
    upn = created_by.get("userPrincipalName")
    if upn:
        return upn
    display = created_by.get("displayName")
    if display:
        return display
    return "(unknown owner)"


def _query_connection_references(runner):
    """Return the agent's connection references from the Declarative Agent
    minimalBots components API, normalized to the row shape
    ``_check_dv_connection`` consumes, or ``None`` when the AgentBuilder client
    or the active-agent ``botId`` is unavailable.

    Validated-tier read (minimalBots ``POST …/components``). The same endpoint
    and ``connectionReferenceChanges`` shape already back the shipped native
    ``DA-CONN-001`` check (``checks/native_agent.py``); see
    ``tests/fixtures/cassettes/INDEX.md`` and ``tests/mocks/
    agentbuilder_connectivity.py``. Fails loudly (lets the dispatcher degrade
    this checkpoint to a WARNING) rather than overclaiming: an
    ``AgentBuilderHTTPError`` propagates, and a 200 payload whose
    ``connectionReferenceChanges`` is present but not a list raises
    ``ValueError`` (mirrors ``native_agent._connection_references``). A missing
    changeset is treated as "no references" (genuine absence), not an error.

    The fetch + normalize + fail-loudly logic is shared with ``ENV-004`` via
    ``_da_connection_refs`` so the two DA connection-reference checks cannot
    drift apart; this wrapper pins DV-CONN-001 to the single active agent.
    """
    return read_active_agent_connection_references(runner)


def _get_connections(runner):
    """Return the BAP admin connection list, or ``None`` when the Power Platform
    admin client is unavailable or the listing errored. Owner/auth echo only —
    never the basis for a PASS/FAIL verdict here."""
    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    if pp is None or not env_id:
        return None
    try:
        conns = pp.get_connections(env_id)
    except Exception:  # noqa: BLE001 — owner echo is best-effort
        return None
    if isinstance(conns, dict) and "_error" in conns:
        return None
    return conns or []


def _find_connection_by_id(conns, connection_id):
    """Return the BAP connection whose ``name`` matches a connection reference's
    ``connectionid``, or ``None``."""
    if not conns or not connection_id:
        return None
    for conn in conns:
        if conn.get("name") == connection_id:
            return conn
    return None


# ─────────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────────


def run_workday_extension_checks(runner) -> list[CheckResult]:
    """Emit the five skill-5 Workday-extension checkpoints.

    Each emitter is invoked behind a guard so a single failure degrades to a
    WARNING for that checkpoint instead of aborting the remaining checks.
    """
    emitters = (
        (_check_connection_auth, "WD-CONN-AUTH-001", _CONN_AUTH_DESC, _MAKER_ROLES),
        (_check_dv_connection, "DV-CONN-001", _DV_CONN_DESC, _MAKER_ROLES),
        (_check_rest_base_url, "WD-REST-001", _REST_URL_DESC, _MAKER_ROLES),
        (_check_user_context_redirect, "WD-REST-002", _REDIRECT_DESC, _MAKER_ROLES),
        (_check_network_allowlist, "WD-NET-001", _NET_DESC, _NET_ROLES),
    )

    results: list[CheckResult] = []
    for fn, cp_id, description, roles in emitters:
        try:
            results.extend(fn(runner))
        except Exception as e:  # noqa: BLE001 — one emitter must not abort the rest
            results.append(CheckResult(roles=roles,
                checkpoint_id=cp_id, category=_CATEGORY,
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description=description,
                result=(
                    f"Unable to run {cp_id}: {type(e).__name__}: {e}"
                ),
                remediation=(
                    "Re-run FlightCheck; if this persists, report the "
                    f"checkpoint ID ({cp_id}) and the error above."
                ),
            ))
    return results


# ─────────────────────────────────────────────────────────────────────
# WD-CONN-AUTH-001 — Workday connection auth type (S5.3, always MANUAL echo).
# ─────────────────────────────────────────────────────────────────────


def _check_connection_auth(runner) -> list[CheckResult]:
    refs = getattr(runner, "_workday_connection_refs", None) or []
    auth_refs = [
        r
        for r in refs
        if _is_workday_auth_ref(r.get("connectionreferencelogicalname"))
    ]
    auth_ref = auth_refs[0] if len(auth_refs) == 1 else None
    connection_id = auth_ref.get("connectionid") if auth_ref else None
    auth_ref_name = (
        str(auth_ref.get("connectionreferencelogicalname"))
        if auth_ref
        else f"\u2026_{_WORKDAY_AUTH_REF_SUFFIX}"
    )

    observed_auth = None
    owner = None
    if connection_id:
        conn = _find_connection_by_id(_get_connections(runner), connection_id)
        if conn:
            props = conn.get("properties", {}) or {}
            param_set = props.get("connectionParametersSet") or {}
            observed_auth = param_set.get("name")
            owner = _resolve_owner(props)

    if len(auth_refs) > 1:
        result = (
            "Confirm in the portal — multiple Workday connection references "
            "match the runtime and legacy package fingerprints, so FlightCheck "
            "cannot determine which connection is active. Remove the obsolete "
            "package references, then verify the remaining connection uses "
            "'Microsoft Entra ID Integrated'."
        )
    elif observed_auth:
        result = (
            "Confirm in the portal — verify the Workday connection's "
            "authentication type. Observed connection auth parameter set: "
            f"'{observed_auth}' (owner: {owner}). This should correspond to "
            "'Microsoft Entra ID Integrated' (Entra SSO)."
        )
    elif auth_ref is not None:
        detail = (
            f" (bound connection {connection_id} was not found in the Power "
            "Platform admin listing)"
            if connection_id
            else " (the reference is not yet bound to a connection)"
        )
        result = (
            "Confirm in the portal — the Workday connection reference "
            f"({auth_ref_name}) is present, but its auth type "
            f"could not be read from the Power Platform admin API{detail}. "
            "Verify the connection uses 'Microsoft Entra ID Integrated'."
        )
    else:
        result = (
            "Confirm in the portal — the Workday connection reference "
            f"(\u2026_{_WORKDAY_AUTH_REF_SUFFIX} or "
            f"{_WORKDAY_RUNTIME_REF_LOGICAL_NAME}) was not found in the cached "
            "Dataverse connection references, so the auth type could not be "
            "read. Verify the Workday connection uses 'Microsoft Entra ID "
            "Integrated'."
        )

    return [CheckResult(roles=_MAKER_ROLES,
        checkpoint_id="WD-CONN-AUTH-001", category=_CATEGORY,
        priority=Priority.HIGH.value, status=Status.MANUAL.value,
        description=_CONN_AUTH_DESC,
        result=result,
        remediation=(
            "In Copilot Studio (or the Power Platform Connections list), open "
            "the Workday connection and confirm its authentication is "
            "'Microsoft Entra ID Integrated'. If it uses a different auth type, "
            "delete the connection, re-create it choosing 'Microsoft Entra ID "
            "Integrated', and re-bind the connection reference."
        ),
        doc_link=_DOC_SIMPLIFIED,
    )]


# ─────────────────────────────────────────────────────────────────────
# DV-CONN-001 — Workday SOAP connection reference binding (S5.4, PASS/FAIL).
# ─────────────────────────────────────────────────────────────────────


def _check_dv_connection(runner) -> list[CheckResult]:
    refs = _query_connection_references(runner)
    if refs is None:
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="DV-CONN-001", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=_DV_CONN_DESC,
            result=(
                "AgentBuilder client or active-agent botId not available — "
                "skipping the Workday connection-reference check."
            ),
        )]

    wd_ref = next(
        (
            r
            for r in refs
            if str(r.get("connectorid") or "")
            .lower()
            .endswith(_WORKDAY_CONNECTOR_SUFFIX)
        ),
        None,
    )

    if wd_ref is None:
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="DV-CONN-001", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_DV_CONN_DESC,
            result=(
                "The ESS Workday SOAP connection reference (connector "
                "shared_workdaysoap) was not found in the Declarative Agent "
                "components payload."
            ),
            remediation=(
                "Install or repair the Workday extension pack so its Workday "
                "SOAP connection reference is created, then bind it to a "
                "Workday connection you own."
            ),
            doc_link=_DOC_SIMPLIFIED,
        )]

    wd_ref_name = str(
        wd_ref.get("connectionreferencelogicalname") or "(unnamed)"
    )
    connection_id = wd_ref.get("connectionid")

    if not connection_id:
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="DV-CONN-001", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_DV_CONN_DESC,
            result=(
                "The ESS Workday SOAP connection reference "
                f"({wd_ref_name}) is unbound (connectionId=null)."
            ),
            remediation=(
                "In Power Platform / Copilot Studio, bind the Workday SOAP "
                "connection reference to an active Workday connection owned by "
                "your own account."
            ),
            doc_link=_DOC_SIMPLIFIED,
        )]

    conn = _find_connection_by_id(_get_connections(runner), connection_id)
    if conn:
        owner = _resolve_owner(conn.get("properties", {}) or {})
        owner_note = f" Owner: {owner} — confirm this is your own account."
    else:
        owner_note = (
            " Connection owner could not be read (Power Platform admin client "
            "unavailable) — confirm the connection is owned by your own account."
        )

    return [CheckResult(roles=_MAKER_ROLES,
        checkpoint_id="DV-CONN-001", category=_CATEGORY,
        priority=Priority.HIGH.value, status=Status.PASSED.value,
        description=_DV_CONN_DESC,
        result=(
            "The ESS Workday SOAP connection reference "
            f"({wd_ref_name}) is bound to a connection." + owner_note
        ),
        doc_link=_DOC_SIMPLIFIED,
    )]


# ─────────────────────────────────────────────────────────────────────
# WD-REST-001 — REST base URL trimmed to /api (S5.5, PASS/FAIL, no client).
# ─────────────────────────────────────────────────────────────────────


def _check_rest_base_url(runner) -> list[CheckResult]:
    config = getattr(runner, "config", None) or {}
    rest = config.get("restBaseUrl")

    if not rest:
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="WD-REST-001", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=_REST_URL_DESC,
            result=(
                "No Workday REST base URL has been captured yet (restBaseUrl "
                "is empty)."
            ),
            remediation=(
                "Capture the Workday REST base URL and trim it to end at "
                "'/api' (e.g. https://<host>/ccx/api)."
            ),
            doc_link=_DOC_SIMPLIFIED,
        )]

    trimmed = str(rest).rstrip("/")
    if trimmed.endswith("/api"):
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="WD-REST-001", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description=_REST_URL_DESC,
            result=f"REST base URL is present and trimmed to '/api': {rest}",
            doc_link=_DOC_SIMPLIFIED,
        )]

    return [CheckResult(roles=_MAKER_ROLES,
        checkpoint_id="WD-REST-001", category=_CATEGORY,
        priority=Priority.HIGH.value, status=Status.FAILED.value,
        description=_REST_URL_DESC,
        result=(
            f"REST base URL is present but not trimmed to '/api': {rest}. It "
            "must end at '/api' with no trailing path or version segment."
        ),
        remediation=(
            "Edit the captured restBaseUrl so it ends at '/api' (e.g. "
            "https://<host>/ccx/api) — remove any trailing path, version, or "
            "resource segment."
        ),
        doc_link=_DOC_SIMPLIFIED,
    )]


# ─────────────────────────────────────────────────────────────────────
# WD-REST-002 — user-context redirect wired (S5.7, PASS/FAIL, local YAML).
# ─────────────────────────────────────────────────────────────────────


def _check_user_context_redirect(runner) -> list[CheckResult]:
    config = getattr(runner, "config", None) or {}
    install_path = str(config.get("installPath") or "").strip().lower()

    if install_path == "legacy":
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="WD-REST-002", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=_REDIRECT_DESC,
            result=(
                "Skipped — legacy install path. This checkpoint applies to the "
                "simplified extension pack's REST user-context topic only."
            ),
        )]

    agent_slug = _selected_agent_slug(runner)
    if not agent_slug:
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="WD-REST-002", category=_CATEGORY,
            priority=Priority.HIGH.value,
            status=Status.NOT_CONFIGURED.value,
            description=_REDIRECT_DESC,
            result="No active agent was selected for user-context validation.",
            remediation=(
                "Select the target agent and rerun this checkpoint with its "
                "--agent-slug value."
            ),
            doc_link=_DOC_SIMPLIFIED,
        )]

    agents_root = Path(_AGENTS_ROOT)
    if not agents_root.is_dir():
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="WD-REST-002", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=_REDIRECT_DESC,
            result=f"No agent workspace found at {_AGENTS_ROOT}/.",
            remediation=(
                "Extract the agent locally (fetch_and_setup) so the "
                f"user-context topic can be inspected under {_AGENTS_ROOT}/."
            ),
        )]

    agent_dir = resolve_agent_directory(agents_root, agent_slug)
    topic_file = agent_dir / "topics" / _USER_CONTEXT_FILE
    if not topic_file.is_file():
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="WD-REST-002", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_REDIRECT_DESC,
            result=(
                f"No {_USER_CONTEXT_FILE} found for selected agent "
                f"'{agent_slug}' under {_AGENTS_ROOT}/{agent_slug}/topics/."
            ),
            remediation=_REDIRECT_REMEDIATION,
            doc_link=_DOC_SIMPLIFIED,
        )]

    installed_dialogs = _installed_user_context_dialogs(agent_slug)
    if not installed_dialogs:
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="WD-REST-002", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_REDIRECT_DESC,
            result=(
                "No installed Workday user-context system topic was found for "
                f"selected agent '{agent_slug}' under "
                f"{_INSTALLED_AGENTS_ROOT}/{agent_slug}/topics/."
            ),
            remediation=_REDIRECT_REMEDIATION,
            doc_link=_DOC_SIMPLIFIED,
        )]

    try:
        text = topic_file.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="WD-REST-002", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_REDIRECT_DESC,
            result=(
                f"The selected agent's {_USER_CONTEXT_FILE} could not be read: "
                f"{e}"
            ),
            remediation=_REDIRECT_REMEDIATION,
            doc_link=_DOC_SIMPLIFIED,
        )]

    matched_dialog = next(
        (
            dialog
            for dialog in installed_dialogs
            if "BeginDialog" in text and dialog in text
        ),
        None,
    )
    if not matched_dialog:
        return [CheckResult(roles=_MAKER_ROLES,
            checkpoint_id="WD-REST-002", category=_CATEGORY,
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_REDIRECT_DESC,
            result=(
                f"The selected agent '{agent_slug}' user-context topic does "
                "not redirect to any installed Workday user-context system "
                f"topic. Installed candidate(s): {', '.join(installed_dialogs)}."
            ),
            remediation=_REDIRECT_REMEDIATION,
            doc_link=_DOC_SIMPLIFIED,
        )]

    return [CheckResult(roles=_MAKER_ROLES,
        checkpoint_id="WD-REST-002", category=_CATEGORY,
        priority=Priority.HIGH.value, status=Status.PASSED.value,
        description=_REDIRECT_DESC,
        result=(
            "The user-context topic redirects to the Workday "
            f"'{matched_dialog}' system topic for selected agent "
            f"'{agent_slug}'."
        ),
        doc_link=_DOC_SIMPLIFIED,
    )]


# ─────────────────────────────────────────────────────────────────────
# WD-NET-001 — firewall allowlisting (S5.8, always MANUAL attestation).
# ─────────────────────────────────────────────────────────────────────


def _check_network_allowlist(runner) -> list[CheckResult]:
    config = getattr(runner, "config", None) or {}
    endpoints = []
    for label, key in (("REST", "restBaseUrl"), ("SOAP", "soapBaseUrl")):
        value = _fmt(config, key)
        host = _host_of(value) if value != _NOT_CAPTURED else _NOT_CAPTURED
        endpoints.append(f"{label}: {host}")

    return [CheckResult(roles=_NET_ROLES,
        checkpoint_id="WD-NET-001", category=_CATEGORY,
        priority=Priority.HIGH.value, status=Status.MANUAL.value,
        description=_NET_DESC,
        result=(
            "InfoSec/IT attestation — the kit cannot verify corporate firewall "
            "rules (a local probe would only prove this machine's egress, not "
            "the managed-connector outbound path). Confirm outbound access "
            "from the Power Platform Workday managed connectors to the Workday "
            "endpoints is allowlisted. Endpoints to allowlist — "
            + "; ".join(endpoints) + "."
        ),
        remediation=(
            "Have InfoSec/IT allowlist outbound access to the Workday REST and "
            "SOAP hosts above for the Power Platform managed connectors, then "
            "capture the change as evidence. A FlightCheck pass alone does not "
            "complete this attestation."
        ),
        doc_link=_DOC_SIMPLIFIED,
    )]
