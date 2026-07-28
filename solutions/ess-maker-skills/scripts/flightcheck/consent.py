# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Consent UX for the runtime-reachability probe (INFRA-003).

WHY THIS EXISTS
---------------
The ``--runtime-reachability`` egress probe is the ONE FlightCheck path that
mutates the operator's tenant: it briefly creates, triggers, and deletes a
transient Power Platform flow so a single HTTP request leaves from the agent's
OWN network egress (see ``live_egress_probe.py`` and
``docs/design-infra-003-endpoint-reachability.md``). Because it writes to the
tenant, every run path must obtain explicit consent before the flow is created.

This module is the single source of truth for that consent UX so the terminal
CLI, the installer, and the ADK/chat skill all present the same wording and the
same manual-verification fallback. It performs no network or Dataverse calls;
it only decides whether the probe is allowed to run and renders the copy.

RUN-PATH BEHAVIOR (consent is ALWAYS surfaced when there is something to probe)
-------------------------------------------------------------------------------
- ``--runtime-reachability``      -> consent granted up front. No prompt, but
                                     FlightCheck announces exactly what the probe
                                     will do (create + delete a transient flow)
                                     so passing the flag is never a silent
                                     mutation.
- ``--no-runtime-reachability``   -> declined up front; shows the skip + manual
                                     fallback.
- neither flag, interactive TTY   -> FlightCheck ALWAYS offers the probe and
                                     asks Y/N before doing anything.
- neither flag, no TTY (CI/pipe)  -> stays read-only, but explains that it could
                                     not ask for permission, how to re-run with
                                     ``--runtime-reachability`` (which both runs
                                     the check and counts as consent), and how to
                                     verify manually.
- ADK/chat                        -> the skill asks conversationally BEFORE the
                                     run (mandatory gate) and passes
                                     ``--runtime-reachability`` on YES, so the
                                     terminal offer is suppressed for that path.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, TextIO

# --- Official Microsoft references surfaced on the manual-verification path ---
# Human-readable per-region outbound IP / service-tag list for managed connectors.
OUTBOUND_IP_ARTICLE_URL = (
    "https://learn.microsoft.com/en-us/connectors/common/outbound-ip-addresses"
)
# The downloadable JSON of Azure IP ranges + service tags (Public Cloud). Used
# to allowlist Power Automate / Azure service tags for a custom HTTP endpoint.
SERVICE_TAGS_JSON_URL = "https://www.microsoft.com/en-us/download/details.aspx?id=56519"

_DEFAULT_LABEL = "your external system"

# Normalize the selected third-party system to a display label so one string
# serves every integration. Keys are lowercased, punctuation-stripped names.
_SYSTEM_LABELS = {
    "workday": "Workday",
    "servicenow": "ServiceNow",
    "successfactors": "SAP SuccessFactors",
    "sapsuccessfactors": "SAP SuccessFactors",
    "sap": "SAP SuccessFactors",
}


def system_label(name: str | None) -> str:
    """Map a raw system name to a user-facing label (default: generic phrase)."""
    if not name:
        return _DEFAULT_LABEL
    key = "".join(ch for ch in name.lower() if ch.isalnum())
    return _SYSTEM_LABELS.get(key, name)


def systems_label(names: list[str] | None) -> str:
    """Combine one or more raw system names into a single user-facing label.

    The egress probe touches EVERY discovered endpoint, so the consent offer
    must name them all — not just the first — for consent to be informed
    (PR #197 review). De-duplicates mapped labels and joins them naturally:
    "ServiceNow", "Workday and ServiceNow", "Workday, ServiceNow, and SAP
    SuccessFactors". Falls back to the generic phrase when nothing is
    discoverable.
    """
    if not names:
        return _DEFAULT_LABEL
    labels: list[str] = []
    for name in names:
        mapped = system_label(name)
        if mapped not in labels:
            labels.append(mapped)
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def build_offer_prompt(label: str) -> str:
    """Primary terminal consent copy (standalone / installer)."""
    return (
        "\n"
        "Network connectivity check — permission required\n"
        f"To confirm that your connection to {label} has been whitelisted, "
        "FlightCheck needs to temporarily create a Power Platform flow in your "
        "environment. This flow sends a network request from the same service "
        "boundary as your agent to each configured endpoint, so we can verify "
        "each connection is allowed through your network security rules.\n"
        "It only tests connectivity — no business data is read, written, or "
        "changed.\n"
        "The flow is automatically deleted as soon as the check finishes.\n"
    )


def build_skip_message(label: str) -> str:
    """Shown when the operator declines the runtime-reachability probe."""
    return (
        "\n"
        "Connectivity check skipped\n"
        "No problem — we won't create anything in your environment.\n"
        f"Because this check didn't run, we can't confirm whether your "
        f"connection to {label} is whitelisted. If the IP ranges aren't "
        "whitelisted, your agent may fail to connect at runtime.\n"
        "You can run this check anytime by re-running FlightCheck and approving "
        "the connectivity step (or passing --runtime-reachability)."
    )


def build_manual_fallback(label: str) -> str:
    """Manual allowlist-verification steps, with direct links to the official
    outbound-IP article and the Azure service-tags / IP-ranges JSON file.

    Uses markdown link syntax ``[text](url)`` so the HTML report renders these
    as clickable links (see runner._md_links_to_html); in the terminal they
    show as copyable ``[text](url)`` text.
    """
    return (
        "Prefer to verify manually? You can confirm the connection is "
        "whitelisted:\n"
        "1. In the Power Platform admin center, note your environment's region.\n"
        "2. From Microsoft's "
        f"[Managed connectors outbound IP addresses]({OUTBOUND_IP_ARTICLE_URL}) "
        "list, get the ranges for that region. For a custom HTTP endpoint, use "
        f"the [Azure service tags / IP ranges JSON]({SERVICE_TAGS_JSON_URL}) "
        "instead.\n"
        f"3. Work with your InfoSec / network team to confirm those ranges are "
        f"allowlisted in your {label} firewall / WAF."
    )


def build_offer_prompt_conversational(label: str) -> str:
    """Shorter conversational consent copy for the ADK / chat (co-create) path.

    The chat skill MUST ask this before running FlightCheck when the egress
    probe is in scope. Kept here so the terminal CLI, the installer, and the
    skill all share one canonical wording (this module's single-source-of-truth
    contract). The skill mirrors this text in SKILL.md.
    """
    return (
        f"To check that your connection to {label} is whitelisted, I'll create a "
        "temporary flow in your environment that sends a test network request, "
        "then delete it right after. It won't touch any of your data. Okay to "
        "proceed?"
    )


def build_forced_on_notice(label: str) -> str:
    """Announcement shown when ``--runtime-reachability`` is passed explicitly.

    Passing the flag is itself consent, so we do not re-prompt — but we still
    state exactly what will happen so a caller who did not see the interactive
    offer is never surprised by a tenant mutation. Emphasizes the two trust
    points: only connectivity is tested, and the flow is auto-deleted.
    """
    return (
        "\n"
        "Network connectivity check — running with your consent "
        "(--runtime-reachability)\n"
        f"FlightCheck will temporarily create a Power Platform flow in your "
        f"environment to test egress to {label}, then delete it as soon as the "
        "check finishes.\n"
        "It only tests connectivity — no business data is read, written, or "
        "changed."
    )


def build_cannot_prompt_message(label: str) -> str:
    """Shown when the probe was not run because we could not ask for permission.

    Covers the non-interactive terminal (CI / piped, no TTY) and the
    infrastructure-only scope (no probe tokens without the flag). Explains that
    nothing was created or verified, and that re-running with
    ``--runtime-reachability`` both runs the check and counts as consent.
    """
    return (
        "\n"
        "Network connectivity check — not run\n"
        "FlightCheck could not ask for permission in this session, so it did "
        "NOT create anything in your environment.\n"
        f"Because this check didn't run, we can't confirm whether your "
        f"connection to {label} is whitelisted. If the IP ranges aren't "
        "whitelisted, your agent may fail to connect at runtime.\n"
        "To run it, re-run FlightCheck with --runtime-reachability. That flag "
        f"briefly creates and deletes a transient flow to test egress to {label} "
        "(no business data is read, written, or changed), and passing it counts "
        "as your consent to that one-time flow."
    )


@dataclass
class ConsentDecision:
    """Outcome of resolving whether the runtime-reachability probe may run.

    - ``enabled``  -> the probe is allowed to create its transient flow.
    - ``declined`` -> the operator (or ``--no-runtime-reachability``) said no, so
                      the report should surface the skip + manual-verification
                      guidance. Distinct from "not offered" (no endpoints / no
                      TTY), where ``declined`` is False.
    - ``prompted`` -> an interactive question was actually asked this run.
    """

    enabled: bool
    declined: bool = False
    prompted: bool = False


def resolve_consent(
    flag: bool | None,
    *,
    endpoints_present: bool,
    interactive: bool,
    prompt_fn: Callable[[], bool] | None = None,
) -> ConsentDecision:
    """Decide whether the runtime-reachability probe runs.

    ``flag`` is the tri-state ``--runtime-reachability`` value: ``True`` (forced
    on), ``False`` (forced off), or ``None`` (not specified -> maybe offer).
    ``prompt_fn`` performs the interactive Y/N and returns the answer; it is
    only called when an offer is warranted. Never raises.
    """
    if flag is True:
        return ConsentDecision(enabled=True, declined=False, prompted=False)
    if flag is False:
        return ConsentDecision(enabled=False, declined=True, prompted=False)
    # flag is None: offer only when there is something to probe AND we can ask.
    if not endpoints_present or not interactive or prompt_fn is None:
        return ConsentDecision(enabled=False, declined=False, prompted=False)
    answer = bool(prompt_fn())
    return ConsentDecision(enabled=answer, declined=not answer, prompted=True)


def ask_yes_no(
    label: str,
    *,
    stream_in: TextIO | None = None,
    stream_out: TextIO | None = None,
    max_attempts: int = 3,
) -> bool:
    """Print the offer copy and read a Y/N answer from the terminal.

    Safe by default: an ambiguous/empty answer after ``max_attempts``, EOF, or a
    closed stream all resolve to DECLINE (never silently mutate the tenant).
    """
    out = stream_out or sys.stdout
    inp = stream_in or sys.stdin
    out.write(build_offer_prompt(label))
    for _ in range(max_attempts):
        out.write("Do you want to continue? [Y] Yes  /  [N] No: ")
        out.flush()
        try:
            raw = inp.readline()
        except (EOFError, ValueError, OSError):
            return False
        if raw == "":  # EOF
            return False
        answer = raw.strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        out.write("Please answer Y or N.\n")
    return False
