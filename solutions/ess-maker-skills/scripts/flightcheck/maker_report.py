# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline maker diagnostics using the existing report's visual design."""

from collections import Counter
from html import escape
import json
import re

from .runner import RunResult, _REPORT_CSS, _mask_sensitive, _render_custom_tags, _render_header, _slug


_LABELS = {
    "problem": "Problem found", "unverified": "Could not verify",
    "admin": "Needs administrator review", "next": "Note to review",
    "passed": "Passed", "optional": "Optional / not enabled", "manual": "Manual verification",
}
_FILTERS = (
    ("all", "All"), ("passed", "Passed"), ("problem", "Failed"),
    ("warnings", "Warnings"), ("manual", "Manual"),
)
_TITLES = {
    "DA-AGENT-001": "Access to this agent", "DA-CONTENT-001": "Agent content",
    "ESS-SOLN-001": "Employee Self-Service identity", "ENV-004": "Connections used by this agent",
    "WD-DA-PKG-001": "Workday components", "WD-DA-FLOW-001": "Workday automated tasks",
    "WD-DA-AUTH-001": "Permission to run Workday tasks", "WD-DA-TOPIC-001": "Workday conversations",
    "WD-DA-WIRING-001": "Workday conversation setup",
}
_PURPOSES = {
    "DA-AGENT-001": "Checks that your signed-in account can read the exact selected agent in the selected environment.",
    "DA-CONTENT-001": "Checks that the selected agent's cloud-authored components can be read and belong to that agent.",
    "ESS-SOLN-001": "Checks that the selected agent has the Employee Self-Service identity.",
    "ENV-001": "Checks that the environment returned by the service matches the selected environment ID.",
    "ENV-002": "Inspects the linked Dataverse provisioning state without treating database type as proof of successful provisioning.",
    "DA-ENV-LINK-001": "Inspects the environment's declared Dataverse link; a native-only agent does not require Dataverse.",
    "ENV-003": "Reports the selected environment's type.",
    "ENV-004": "Checks that connections required by this agent's active conversations and flows are present, bound and use the expected connectors.",
    "DA-TOPIC-001": "Inspects conversation activation, distinguishing active, inactive and unknown; disabled optional conversations are not defects.",
    "DA-AUTH-001": "Inspects the agent's configured sign-in mode and trigger; it does not test an employee signing in.",
    "DA-INSTRUCTIONS-001": "Checks for readable, nonempty instructions in the cloud-authored agent; it does not assess answer quality.",
    "WD-INTEGRATION-001": "Determines whether this agent's Workday integration is enabled, disabled, configured but unused, absent or undetermined.",
    "SN-INTEGRATION-001": "Determines whether this agent's ServiceNow integration is enabled, disabled, configured but unused, absent or undetermined.",
    "WD-CONN-001": "Checks the exact connection bindings used by this agent's enabled Workday integration, not unrelated connections.",
    "SN-CONN-001": "Checks the exact connection bindings used by this agent's enabled ServiceNow integration, not unrelated connections.",
    "SN-FLOW-001": "Checks the state of ServiceNow flows this agent actually invokes; direct connector actions do not require flows.",
    "WD-DA-PKG-001": "Checks that the Microsoft-provided components required by this agent's enabled Workday integration are installed.",
    "WD-DA-FLOW-001": "Checks that the required Workday automation flows are present once and active.",
    "WD-DA-AUTH-001": "Checks that the selected agent has the required access to its Workday automation flows.",
    "WD-DA-TOPIC-001": "Checks that the required Workday system conversations are active and unique; intentionally unused employee scenarios are optional.",
    "WD-DA-WIRING-001": "Checks that conversation startup initializes the Workday configuration before loading user context.",
    "DV-CONN-001": "Checks that Workday's runtime Dataverse connection reference is active and bound.",
    "WD-REST-002": "Checks the User Context redirect in Development's selected local files or Test/Production's selected native agent. This does not prove publication or employee runtime success.",
    "WD-DA-ATTACH-001": "Guides manual inspection of both agent connection references and their parameter-sharing settings; flow authorization is a separate check.",
    "CONFIG-007": "Checks that the selected agent's local instructions are present.",
    "CONFIG-005": "Inspects the starter prompts in the selected agent's local files.",
    "TOPIC-011": "Inventories the selected agent's local conversation files without imposing a minimum count.",
    "CONFIG-014": "Checks local conversation descriptions for placeholder text and parse errors, not an arbitrary word count.",
}
_SUMMARY = (
    ("passed", "Passed", "pass", "green"), ("problem", "Failed", "fail", "red"),
    ("admin", "Needs administrator review", "warn", "amber"),
    ("unverified", "Could not verify", "warn", "amber"),
    ("next", "Notes to review", "warn", "amber"), ("manual", "Manual verification", "manual", "gray"),
    ("optional", "Optional / not enabled", "na", "gray"),
)
_PILLS = {"Passed": "pass", "Failed": "fail", "Blocked": "warn", "Error": "warn",
          "Skipped": "na", "Warning": "warn", "Manual": "manual", "NotConfigured": "na"}


def _kind(row):
    if row.status == "Manual":
        return "manual"
    if row.status == "Failed":
        return "problem"
    if row.status == "Blocked" and row.evidence.get("reviewOwner") == "administrator":
        return "admin"
    if row.status == "NotConfigured" and row.evidence.get("applicability") in {
        "not_configured", "disabled", "configured", "not_applicable",
    }:
        return "optional"
    if row.status in {"Blocked", "Error", "Skipped"} or row.evidence.get("dependencyCoverageComplete") is False:
        return "unverified"
    return "passed" if row.status == "Passed" else "next"


def _customer_text(text):
    return re.sub(r"\bagent owner\b", "Environment Maker user", text, flags=re.IGNORECASE)


def _roles(row):
    return _customer_text(
        ", ".join(row.roles).replace("ESS Maker / Agent Developer", "Environment Maker user")
    ) or "Environment Maker user"


def _prose(text):
    escaped = escape(_mask_sensitive(_customer_text(text)), quote=True)
    return re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', escaped,
    ).replace("\n", "<br>")


def _category(row):
    if _kind(row) in {"manual", "admin"}:
        return "Manual verification"
    if row.checkpoint_id.startswith("WD-") or row.checkpoint_id == "DV-CONN-001":
        return "Workday"
    if row.checkpoint_id.startswith("SN-"):
        return "ServiceNow"
    if row.checkpoint_id == "ENV-004":
        return "Connections"
    return {
        "Native Agent": "Agent", "Agent setup": "Agent", "Agent configuration": "Agent",
        "Workday DA": "Workday", "Workday Extension": "Workday",
        "Local authored files": "Agent",
        "Local Files": "Agent", "Local files": "Agent", "Agent source files": "Agent",
    }.get(row.category, row.category)


def _next_step(row):
    if _kind(row) == "optional":
        return "No action is required unless you intend to enable this integration or use this optional configuration."
    if row.remediation:
        return row.remediation
    if row.status == "Manual":
        return "Detailed verification steps were not supplied by this check. Ask the listed owner to consult the linked setup documentation before changing settings."
    if row.status == "Failed":
        return "Ask the listed owner to inspect the finding and the linked setup documentation, repair the confirmed defect, and rerun this check."
    if row.status == "Warning":
        return "Review this recommendation with the listed owner. If it applies to your setup, follow the linked guidance and rerun."
    return "Ask the listed owner to resolve the reported access or evidence limitation and rerun. An unverified result is not a confirmed configuration defect."


def _render_finding(row, index):
    kind = _kind(row)
    filter_group = {"admin": "manual", "unverified": "warnings", "next": "warnings"}.get(kind, kind)
    manual = _category(row) == "Manual verification"
    purpose = _PURPOSES.get(row.checkpoint_id, row.description)
    attention_html = ""
    if kind != "passed":
        steps = row.evidence.get("manualVerificationSteps")
        next_step = (
            "\n".join(f"{number}. {step}" for number, step in enumerate(steps, 1))
            if row.status == "Manual" and isinstance(steps, list) and steps and all(isinstance(step, str) for step in steps)
            else _next_step(row)
        )
        missing = row.evidence.get("ifMissingOrIncorrect")
        attention_html = (
            f'<p><b>Who should check or fix this:</b> {escape(_roles(row))}</p>'
            f'<p><b>{"Verification steps" if manual else "Next step"}:</b> {_prose(next_step)}</p>'
            + (f'<p><b>If missing or incorrect:</b> {_prose(missing)}</p>' if isinstance(missing, str) and missing else "")
        )
    return (
        f'<article class="finding" id="finding-{index}" data-kind="{kind}" '
        f'data-filter-group="{filter_group}" '
        f'data-recorded-status="{escape(row.status)}" aria-labelledby="finding-{index}-title">'
        f'<div class="finding-heading"><h3 class="finding-label" id="finding-{index}-title">'
        f'<code class="check-id">{escape(row.checkpoint_id)}</code>'
        f'<strong>{escape(_TITLES.get(row.checkpoint_id, row.description))}</strong></h3>'
        f'<div class="finding-status"><span class="pill {_PILLS.get(row.status, "na")}">'
        f'{escape(row.status.replace("NotConfigured", "Not configured"))}</span>'
        + _render_custom_tags(row.custom_tags)
        + '</div></div><div class="finding-body">'
        f'<p class="finding-purpose"><b>What this checks:</b> {_prose(purpose)}</p>'
        f'<p><b>Result:</b> {_prose(row.result)}</p>'
        + attention_html
        + '</div>'
        f'<p class="finding-links"><a href="#technical-{index}">Technical details</a>'
        + (f' | <a href="{escape(row.doc_link, quote=True)}" target="_blank" rel="noopener noreferrer">Setup documentation</a>'
           if row.doc_link.startswith(("https://", "http://")) else "")
        + '</p></article>'
    )


def _render_technical_details(row, index, *, supporting_target=None):
    evidence = {
        key: value for key, value in row.evidence.items()
        if key not in {
            "agentSlug", "apiContract", "assertionScope",
            "manualVerificationSteps", "ifMissingOrIncorrect",
        }
    }
    scope = evidence.get("verificationScope")
    if isinstance(scope, dict) and scope.get("targetVerified") is True:
        evidence.pop("verificationScope")
    for key, displayed in (("verificationReason", row.result), ("expectedSetting", row.description)):
        if evidence.get(key) == displayed:
            evidence.pop(key)
    return (
        f'<details class="technical-entry" id="technical-{index}" '
        f'data-check-id="{escape(row.checkpoint_id, quote=True)}">'
        f'<summary><code class="check-id">{escape(row.checkpoint_id)}</code> '
        f'<strong>{escape(_TITLES.get(row.checkpoint_id, row.description))}</strong> '
        f'<span class="pill {_PILLS.get(row.status, "na")}">{escape(row.status.replace("NotConfigured", "Not configured"))}</span></summary>'
        + (f'<p><b>Supporting validation:</b> {_prose(row.result)}</p>'
           + (f'<p>{_prose(row.remediation)}</p>' if row.remediation else "") if supporting_target else "")
        + (f'<pre>{escape(_mask_sensitive(json.dumps(evidence, indent=2)))}</pre>' if evidence else
           '<p>No additional technical observations are recorded beyond the finding and guidance above.</p>')
        + (f'<p><a href="#{supporting_target}">View requested finding</a></p>' if supporting_target else
           f'<p><a href="#finding-{index}">View finding and guidance for {escape(row.checkpoint_id)}</a></p>')
        + '</details>'
    )


def render_maker_report(result: RunResult) -> str:
    from .runner import maker_diagnostic_outcome

    requested = result.coverage.get("requested", []) if result.scope == "checkpoint" else []
    selected = set()

    def include(key):
        replacements = result.coverage.get("aliases", {}).get(key)
        if replacements:
            for replacement in replacements:
                include(replacement)
        else:
            selected.add(key)

    for key in requested:
        include(key)
    visible = [
        (index, row) for index, row in enumerate(result.results)
        if not requested or row.checkpoint_id in selected
    ]
    if requested and not visible:
        raise ValueError("The requested FlightCheck has no recorded result to display.")
    supporting = {index for index, row in enumerate(result.results) if requested and row.checkpoint_id not in selected}
    counts = Counter(_kind(row) for _, row in visible)
    outcome = maker_diagnostic_outcome(result)
    title = {
        "ISSUES_FOUND": "Setup issues found",
        "SOME_CHECKS_UNVERIFIED": "Some checks could not run",
        "CHECKED_WITH_NOTES": "Setup checks completed with notes",
        "SETUP_CHECKS_PASSED": "Setup checks passed",
    }[outcome]
    if outcome == "CHECKED_WITH_NOTES" and counts["manual"] and not counts["next"]:
        title = "Automated checks passed; manual verification remains" if counts["passed"] else "Manual verification remains"
    color = "red" if counts["problem"] else "amber" if any(counts[k] for k in ("unverified", "admin", "next", "manual")) else "green"
    ledger = '<div class="syn-stats" aria-label="Status legend and totals">' + "".join(
        f'<span class="stat {style}"><i class="dot {dot}" aria-hidden="true"></i>'
        f'<b>{counts[kind]}</b> {label}</span>'
        for kind, label, style, dot in _SUMMARY
    ) + '</div>'
    categories = {}
    actions, findings = [], {}
    for index, row in visible:
        kind = _kind(row)
        category = _category(row)
        categories.setdefault(category, []).append(row)
        owner = _roles(row)
        row_title = _TITLES.get(row.checkpoint_id, row.description)
        row_id = f"finding-{index}"
        finding = row.result
        brief = finding if len(finding) <= 260 else finding[:260].rsplit(" ", 1)[0] + "..."
        if kind not in {"passed", "optional", "manual", "admin"}:
            actions.append(
                f'<tr><th scope="row" data-label="Area"><a href="#{row_id}">'
                f'<code>{escape(row.checkpoint_id)}</code> {escape(row_title)}</a>'
                f'<span class="advisory">{escape(row.status)} - {_LABELS[kind]}</span>'
                f'<p class="finding-summary">{_prose(brief)}</p></th>'
                f'<td data-label="Next step">{_prose(_next_step(row))}</td>'
                f'<td data-label="Who can help">{escape(owner)}</td></tr>'
            )
        findings.setdefault(category, []).append(_render_finding(row, index))
    if "Manual verification" in categories:
        categories["Manual verification"] = categories.pop("Manual verification")
    tiles, sections = [], []
    for stage, (category, rows) in enumerate(categories.items(), 1):
        kinds = {_kind(row) for row in rows}
        category_color = "red" if "problem" in kinds else "amber" if kinds & {"unverified", "admin", "next"} else "gray" if kinds <= {"optional", "manual"} else "green"
        category_label = (
            "Problem found" if "problem" in kinds else "Could not fully verify" if kinds & {"unverified", "admin"}
            else "Manual verification" if "manual" in kinds else "Notes to review" if "next" in kinds else "Optional / not enabled" if kinds == {"optional"} else "Checks passed"
        )
        anchor = "manual-verification" if category == "Manual verification" else "cat-" + _slug(category)
        tiles.append(
            f'<a class="syn-tile {category_color}" href="#{anchor}">'
            f'<div class="syn-no">Stage {stage}</div>'
            f'<div class="syn-name">{escape(category)}</div>'
            f'<div class="syn-role">{category_label}</div></a>'
        )
        if category == "Manual verification":
            continue
        sections.append(
            f'<details class="sec category" id="{anchor}" open><summary>{escape(category)}'
            f'<span class="advisory">{len(rows)} recorded check(s)</span></summary>'
            f'<div class="sec-body">{"".join(findings[category])}</div></details>'
        )
    filters = "".join(
        f'<button type="button" data-filter="{kind}" aria-pressed="{"true" if kind == "all" else "false"}">'
        f'{label}</button>'
        for kind, label in _FILTERS
    )
    reading_guide = (
        '<section class="reading-guide" aria-label="How to read this report"><h2>How to read this report</h2><ul>'
        '<li><b>Green / Passed:</b> the stated configuration was checked. No repair is indicated for that check.</li>'
        '<li><b>Red / Failed:</b> a specific configuration defect was found. Follow its next steps and rerun.</li>'
        '<li><b>Warnings:</b> recommendations and checks that could not be verified. Read the recorded status and follow the next step.</li>'
        '<li><b>Manual:</b> the person listed must inspect the setting. Follow the steps in Manual verification.</li>'
        '<li><b>Optional integrations:</b> disabled or unconfigured items appear under All and do not require action.</li>'
        '<li><b>Check details:</b> results are visible without expanding a check. Findings needing attention also show the responsible person and next steps.</li>'
        '<li><b>After changes:</b> rerun relevant checks after configuration changes.</li></ul>'
        + ('<p>This run checked local files only; it did not inspect deployed settings.</p>' if result.scope == "local" else "")
        + (f'<p>This focused report shows {len(visible)} requested finding(s). '
           f'{len(supporting)} supporting validation(s) remain in the technical details and original JSON; '
           'header execution totals include those validations.</p>' if requested else "")
        + '</section>'
    )
    verdict_class = {"red": "verdict-not-ready", "amber": "verdict-warnings", "green": "verdict-ready"}[color]
    header = _render_header(
        result, verdict_class, "", title,
        "Configuration inspection only, not release approval or proof that employee tasks work.",
        reading_guide=reading_guide,
    )
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark"><title>ESS maker setup checks</title>'
        f'<style>{_REPORT_CSS}{_CSS}</style></head><body><main class="wrap">'
        + header
        + '<section class="actions-panel"><div class="ap-head"><h2>Action items</h2>'
        '<span class="ap-sub">What to do next for the configuration inspected.</span></div>'
        + ('<table class="action-table"><thead><tr><th>Area</th><th>Next step</th><th>Who can help</th></tr></thead>'
           f'<tbody>{"".join(actions)}</tbody></table>' if actions else '<p>No setup issues were found in the checks performed.</p>')
        + (f'<p><a href="#manual-verification">{len(categories.get("Manual verification", []))} item(s) need a person to verify settings.</a> '
           'See Manual verification for the responsible person and detailed steps.</p>' if categories.get("Manual verification") else "")
        + '</section><section class="synopsis"><div class="syn-head"><h2>Readiness at a glance</h2>'
        '<span class="hint">Select any category to inspect its recorded findings.</span></div>'
        f'{ledger}'
        f'<div class="syn-grid">{"".join(tiles)}</div></section>'
        '<section class="checks-card" id="check-details"><h2>Check details</h2><div class="filters maker-filters" hidden>'
        f'{filters}<label>Search <input id="search" type="search"></label></div>'
        f'{"".join(sections)}<p id="no-match" hidden>No matching checks.</p></section>'
        '<section class="checks-card category manual-verification" id="manual-verification"><h2>Manual verification</h2>'
        '<p>These settings need to be checked by the person listed below.</p>'
        + "".join(findings.get("Manual verification", []))
        + ('<p>No manual verification items were identified for this run.</p>' if not categories.get("Manual verification") else "")
        + '</section>'
        '<section class="checks-card" id="technical-details"><h2>Technical details</h2>'
        '<p>For troubleshooting with your administrator or support: inspect observed values, '
        'missing resources and read errors by FlightCheck ID. These details do not prove that employee tasks work.</p>'
        '<p>Repeated instructions and common scope metadata are omitted here. Manual means a person still needs '
        'to verify the setting, not a confirmed defect or a pass. The original JSON download retains all recorded details.</p>'
        '<div class="technical-search-controls" hidden><label for="technical-search">Search technical details by FlightCheck ID</label>'
        '<input id="technical-search" type="search" placeholder="e.g. WD-CONN-001" autocomplete="off">'
        '<p id="technical-match-count" class="advisory" role="status"></p></div>'
        + "".join(
            _render_technical_details(
                row, index, supporting_target=f"finding-{visible[0][0]}" if index in supporting else None,
            )
            for index, row in enumerate(result.results)
        )
        + '<p id="no-technical-match" hidden>No matching FlightCheck IDs.</p></section>'
        '<footer><a href="results.json">Download original check results</a></footer>'
        f'</main><script>{_SCRIPT}</script></body></html>'
    )


_CSS = """
.wrap>section,.wrap>header{margin-bottom:16px}.checks-card{padding:20px}
.checks-card h2{font-size:20px;font-weight:600;margin:0 0 12px}
.report .meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px 24px;overflow-wrap:anywhere}
.reading-guide{border-top:1px solid var(--line);margin-top:16px;padding-top:12px;font-size:13px}
.reading-guide h2{font-size:16px;line-height:22px;margin:0 0 8px}
.reading-guide ul{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 28px;margin:0;padding-left:18px}
.reading-guide p{margin:8px 0 0}
.action-table{width:100%;border-collapse:collapse;table-layout:fixed}
.action-table th,.action-table td{padding:12px;vertical-align:top;border-bottom:1px solid var(--line);text-align:left;overflow-wrap:anywhere}
.action-table th:first-child{width:28%}.action-table th:last-child{width:23%}
.advisory{display:block;font-size:12px;color:var(--muted)}
.sec-body{display:block}
.finding{min-width:0;padding:12px;border:1px solid var(--line);border-radius:4px}
.finding+.finding{margin-top:12px}
.finding-heading{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,35%);align-items:start;gap:10px}
.finding-label{display:flex;flex-direction:column;gap:4px;min-width:0;margin:0}
.finding-status{display:flex;flex-direction:column;align-items:flex-end;gap:8px;min-width:0}
.finding-status .custom-tags{justify-content:flex-end;margin:0}
.finding-status .custom-tag{text-align:right}
.check-id{font-size:12px;font-weight:400;color:var(--muted)}.finding-label strong{font-size:14px}
.finding-purpose{color:var(--muted)}
.finding-body{display:block}.finding-body p{font-size:13px;margin:10px 0 0}
.finding-links{font-size:12px;margin:12px 0 0}
.technical-entry{border-top:1px solid var(--line);padding:12px 0;font-size:13px}
.technical-entry summary{cursor:pointer;overflow-wrap:anywhere}.technical-entry summary .pill{margin-left:8px}
.technical-entry pre{white-space:pre-wrap;overflow-wrap:anywhere}
.technical-search-controls{margin:16px 0}.technical-search-controls label{display:block;font-size:13px}
.technical-search-controls input{display:block;box-sizing:border-box;width:100%;max-width:360px;padding:8px;margin-top:6px}
.finding-summary{font-size:13px;font-weight:400;margin:6px 0 0}
.finding p{overflow-wrap:anywhere}
.finding-status .pill{align-self:flex-end;max-width:100%;white-space:normal;overflow-wrap:anywhere}.finding-purpose,.finding-label{overflow-wrap:anywhere}
.maker-filters{display:flex;gap:8px;flex-wrap:wrap;padding:12px 0}
.maker-filters button[aria-pressed=true]{font-weight:600;color:var(--accent);border-bottom-color:var(--accent)}
.maker-filters input{max-width:100%}[hidden]{display:none!important}
@media(max-width:600px){.action-table,.action-table tbody,.action-table tr,.action-table td,.action-table tbody th{display:block;width:100%}
.report .meta,.reading-guide ul{grid-template-columns:minmax(0,1fr)}
.action-table thead{display:none}.action-table td[data-label]::before{content:attr(data-label);display:block;font-weight:600}
.action-table th:first-child,.action-table th:last-child{width:100%}.checks-card{padding:12px}}
"""

_SCRIPT = """
const filters = Array.from(document.querySelectorAll('[data-filter]'));
const findings = Array.from(document.querySelectorAll('.finding'));
const technicalEntries = Array.from(document.querySelectorAll('.technical-entry'));
const technicalSearch = document.getElementById('technical-search');
let kind = 'all';
document.querySelector('.maker-filters').hidden = false;
document.querySelector('.technical-search-controls').hidden = false;
function applyFilter() {
  const search = document.getElementById('search').value.trim().toLowerCase();
  findings.forEach(row => row.hidden = !(kind === 'all' || row.dataset.filterGroup === kind) ||
    !row.textContent.toLowerCase().includes(search));
  document.querySelectorAll('.category').forEach(category => {
    category.hidden = !Array.from(category.querySelectorAll('.finding')).some(row => !row.hidden);
    if (!category.hidden && (kind !== 'all' || search)) category.open = true;
  });
  filters.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === kind)));
  document.getElementById('no-match').hidden = findings.some(row => !row.hidden);
}
filters.forEach(button => button.addEventListener('click', () => {
  kind = button.dataset.filter; applyFilter();
}));
document.getElementById('search').addEventListener('input', applyFilter);
function applyTechnicalFilter() {
  const search = technicalSearch.value.trim().toLowerCase();
  technicalEntries.forEach(entry => {
    entry.hidden = !entry.dataset.checkId.toLowerCase().includes(search);
    entry.open = Boolean(search) && !entry.hidden;
  });
  const visible = technicalEntries.filter(entry => !entry.hidden).length;
  document.getElementById('no-technical-match').hidden = visible > 0;
  document.getElementById('technical-match-count').textContent =
    `${visible} of ${technicalEntries.length} check(s)`;
}
technicalSearch.addEventListener('input', applyTechnicalFilter);
applyTechnicalFilter();
function openTarget(hash) {
  const target = document.getElementById(hash.slice(1));
  if (!target) return;
  if (target.closest('#technical-details')) {
    technicalSearch.value = ''; applyTechnicalFilter();
  } else {
    kind = 'all'; document.getElementById('search').value = ''; applyFilter();
  }
  let current = target;
  while (current) {
    if (current.tagName === 'DETAILS') current.open = true;
    current = current.parentElement;
  }
  target.scrollIntoView({block:'start'});
}
document.querySelectorAll('a[href^="#"]').forEach(link => link.addEventListener('click',
  () => openTarget(link.getAttribute('href'))));
window.addEventListener('hashchange', () => openTarget(location.hash));
if (location.hash) openTarget(location.hash);
"""
