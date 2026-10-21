# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline, presentation-only DA report with shared work and distinct assertions."""

from __future__ import annotations

from collections import Counter
from html import escape
import json
from pathlib import Path
import re
import shlex

from .da_readiness import DA_EVIDENCE_SCHEMA
from .runner import RunResult, _mask_sensitive, _slug


_BASE_FIELDS = {"observedAt", "source", "reviewerRole", "configurationRevision"}
_GROUPS = {
    "Flow licensing": ("LIC-FLOW-001", "LIC-FLOW-002"),
    "Workday connection configuration": ("WD-CONN-AUTH-001", "WD-CONN-013", "WD-DA-ATTACH-001"),
    "Entra administrator handoff": (
        "WD-ENTRA-SCOPE-001", "WD-ENTRA-CONSENT-001", "WD-ASSIGN-001",
        "WD-ENTRA-NAMEID-001", "WD-ENTRA-SIGNOPT-001", "WD-CONN-010", "WD-CONN-102",
    ),
    "Workday administrator handoff": (
        "WD-API-CLIENT-001", "WD-TENANT-001", "WD-NET-001", "WD-SEC-003", "WD-REST-001",
    ),
    "Billing and capacity review": ("PRE-004", "PRE-005", "PRE-006", "ENV-CAPACITY-001"),
    "Dependency discovery and exact bindings": ("ENV-004", "DA-CONN-001", "SN-CONN-001"),
    "Evaluation and release approval": ("QA-001", "QA-002", "QA-012", "PUB-003", "PUB-006"),
}
_GROUP_BY_ID = {key: title for title, keys in _GROUPS.items() for key in keys}
_REASONS = {
    "required_evidence_unverified": "Required evidence has not been accepted.",
    "unknown_applicability": "Decide whether this capability is in scope for the assessed target.",
    "missing_results": "A required result was not produced.",
    "evidence_revision_mismatch": "The reviewed evidence belongs to a different configuration revision.",
    "evidence_expired_or_future": "The evidence is outside its declared validity window.",
}


def _e(value) -> str:
    return escape(str(value), quote=True)


def _prose(value: str) -> str:
    tokens = re.split(r"(\[[^\]]+\]\(https?://[^\s)]+\)|\*\*[^*]+\*\*)", _mask_sensitive(value))
    parts = []
    for token in tokens:
        link = re.fullmatch(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", token)
        if link:
            parts.append(f'<a href="{_e(link[2])}" target="_blank" rel="noopener noreferrer">{_e(link[1])}</a>')
        elif token.startswith("**") and token.endswith("**"):
            parts.append(f"<strong>{_e(token[2:-2])}</strong>")
        else:
            parts.append(_e(token).replace("\n", "<br>"))
    return "".join(parts)


def _field_name(value: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", value).replace("_", " ").capitalize()


def _badge(status: str) -> str:
    color = {
        "Passed": "success", "satisfied": "success", "Failed": "danger", "defect": "danger",
        "Error": "danger", "Blocked": "attention", "Warning": "attention",
    }.get(status, "neutral")
    return f'<span class="badge {color}">{_e(status)}</span>'


def _kind(entry: dict, rows: list) -> str:
    if entry["coverageState"] == "unknown":
        return "applicability"
    if any(row.evidence.get("administratorCheckDeferred") is True for row in rows):
        return "administrator"
    if entry["requiredEvidenceFields"]:
        return "evidence"
    return "verification"


def _template(assessment: dict, entry: dict) -> str:
    key = entry["checkpointId"]
    fields = set(entry["requiredEvidenceFields"]) - _BASE_FIELDS
    details = {field: "" for field in sorted(fields)}
    for field in {"employeeTestRunIds", "employeeTestRuns"} & fields:
        details[field] = []
    if "outcomes" in fields:
        details["outcomes"] = {}
    kind = (
        "published_employee_runtime" if key in {"DA-RUNTIME-001", "DA-SN-RUNTIME-001"}
        else "maker_test_pane" if key == "WD-DA-MAKER-001" else "manual_attestation"
    )
    return json.dumps({
        "schemaVersion": DA_EVIDENCE_SCHEMA,
        "records": [{
            "checkpointId": key, "target": assessment["target"],
            "configurationRevision": assessment["configurationRevision"],
            "reviewed": False, "reviewerRole": "", "source": "",
            "observedAt": "", "reviewedAt": "", "validUntil": "", "outcome": "",
            "evidenceKind": kind, "details": details,
        }],
    }, indent=2)


def _requirement(assessment: dict, entry: dict, rows: list, *, single: bool = False) -> str:
    key = entry["checkpointId"]
    title = rows[0].description if rows else _field_name(key)
    kind = _kind(entry, rows)
    observed = " · ".join(dict.fromkeys(row.status for row in rows))
    reason = entry["applicabilityReason"] if entry["coverageState"] == "unknown" else " ".join(
        _REASONS.get(code, _field_name(code) + ".") for code in entry["reasonCodes"]
    )
    criteria = list(dict.fromkeys(
        row.evidence.get("acceptanceCriteria") or row.remediation
        for row in rows if row.evidence.get("acceptanceCriteria") or row.remediation
    ))
    if not rows:
        criteria = [entry["applicabilityReason"]]
    if entry["coverageState"] == "unsupported":
        criteria.append("This requirement needs an approved implementation; a maker attestation cannot replace it.")
    content = (
        f'<details class="requirement" id="chk-{_slug(key)}" data-kind="{kind}">'
        f'<summary><span><strong>{_e("Acceptance criteria and evidence" if single else title)}</strong><code>{_e(key)}</code></span>'
        f'{_badge(observed or entry["coverageState"])}</summary><div class="requirement-body">'
        f'<p class="muted">{_e(reason)}</p>'
        f'<p><b>Owning reviewer:</b> {_e(", ".join(entry["roles"]))}</p>'
        + "".join(f"<p>{_prose(action)}</p>" for action in criteria)
    )
    fields = entry["requiredEvidenceFields"]
    if fields:
        domain_fields = [field for field in fields if field not in _BASE_FIELDS]
        content += (
            "<h4>Evidence to collect</h4><ul class=\"field-list\">"
            + "".join(f"<li>{_e(_field_name(field))} <code>{_e(field)}</code></li>" for field in domain_fields)
            + "</ul><p class=\"muted\">Also required: observation/review times, owning reviewer, "
            "source, explicit expiry and the exact target/configuration revision.</p>"
            '<details class="template"><summary>Unreviewed evidence template</summary>'
            '<p>Complete the fields and obtain the owning review. Copying this template does not verify anything.</p>'
            f'<textarea readonly aria-label="Unreviewed evidence template for {_e(key)}" spellcheck="false">'
            f'{_e(_template(assessment, entry))}</textarea>'
            '<button type="button" class="copy-template">Copy template</button>'
            '<span class="copy-status" role="status"></span></details>'
        )
    if rows and not fields:
        content += '<details><summary>Observed diagnostic detail</summary>'
        for row in rows:
            if key in {"ENV-004", "DA-CONN-001", "SN-CONN-001"}:
                content += '<p>See <a href="#dependency-detail">shared dependency discovery</a> and the diagnostic inventory below.</p>'
            else:
                content += f"<p>{_prose(row.result)}</p>"
        content += "</details>"
    return content + "</div></details>"


def _work_queue(r: RunResult) -> tuple[str, int]:
    assessment = r.da_assessment
    groups: dict[str, list] = {}
    rows_by_id: dict[str, list] = {}
    for row in r.results:
        rows_by_id.setdefault(row.checkpoint_id, []).append(row)
    for entry in assessment["coverage"]:
        if not entry["deploymentRequired"] or entry["evidenceState"] == "satisfied":
            continue
        rows = [row for observed in entry["observed"] for row in rows_by_id.get(observed["checkpointId"], [])
                if row.status == observed["status"]]
        # A checkpoint can emit several status buckets; retain each actual row once.
        rows = list({id(row): row for row in rows}.values())
        title = (
            "Applicability decisions" if entry["coverageState"] == "unknown" else
            _GROUP_BY_ID.get(entry["checkpointId"], rows[0].description if rows else entry["checkpointId"])
        )
        groups.setdefault(title, []).append((entry, rows))
    cards = []
    def urgency(item):
        entries = item[1]
        if any(entry["evidenceState"] == "defect" for entry, _ in entries):
            return 0
        ranks = {"verification": 1, "applicability": 2, "administrator": 3, "evidence": 4}
        return min(ranks[_kind(entry, rows)] for entry, rows in entries)

    for title, entries in sorted(groups.items(), key=urgency):
        kinds = sorted({_kind(entry, rows) for entry, rows in entries})
        owners = sorted({role for entry, _ in entries for role in entry["roles"]})
        defect = any(entry["evidenceState"] == "defect" for entry, _ in entries)
        cards.append(
            f'<article class="work-card" data-kinds="{_e(" ".join(kinds))}">'
            f'<div class="card-heading"><h3>{_e(title)}</h3>{_badge("defect" if defect else "Evidence needed")}</div>'
            f'<p class="muted">{len(entries)} distinct requirement(s) · {_e(", ".join(owners))}</p>'
            + ("<p>Collect the shared handoff once; review each named assertion separately.</p>" if len(entries) > 1 else "")
            + (f'<details class="bundle"><summary>Review {len(entries)} named requirements</summary>' if len(entries) > 3 else "")
            + "".join(_requirement(assessment, entry, rows, single=len(entries) == 1) for entry, rows in entries)
            + ("</details>" if len(entries) > 3 else "")
            + "</article>"
        )
    return "".join(cards), len(groups)


def _rerun(assessment: dict) -> str:
    rerun = assessment.get("rerun")
    if not rerun:
        return "<p>The original standalone invocation was not recorded. Reuse its exact target and realm; maker /flightcheck is local-only.</p>"
    args = ["python", str(Path("scripts") / "flightcheck" / "cli.py"), *rerun["arguments"]]
    if rerun["shell"] == "powershell":
        command = " ".join("'" + arg.replace("'", "''") + "'" if index else arg
                           for index, arg in enumerate(args))
    else:
        command = shlex.join(args)
    root = r"solutions\ess-maker-skills" if rerun["shell"] == "powershell" else "solutions/ess-maker-skills"
    return (
        f'<p>Run from <code>{_e(root)}</code> '
        f'using {_e(rerun["shell"])} and the original approved maker account. This preserves the original target inputs.</p>'
        f'<pre class="command">{_e(command)}</pre>'
        "<p>To submit reviewed evidence, add <code>--da-evidence</code> with your evidence file "
        "(or replace its existing value). Never substitute the maker's local-only slash command.</p>"
    )


def _coverage(assessment: dict) -> str:
    rows = []
    for entry in assessment["coverage"]:
        observed = ", ".join(f"{row['checkpointId']}: {row['status']}" for row in entry["observed"]) or "Not scheduled / no row"
        reason = " ".join(_REASONS.get(code, _field_name(code) + ".") for code in entry["reasonCodes"])
        rows.append(
            f'<tr data-required="{str(entry["deploymentRequired"]).lower()}"><th scope="row"><code>{_e(entry["checkpointId"])}</code></th>'
            f'<td>{_e(entry["applicability"])}</td><td>{"Required" if entry["deploymentRequired"] else "Advisory / excluded"}</td>'
            f'<td>{_e(observed)}</td><td>{_badge(entry["evidenceState"])}</td>'
            f'<td>{_e(reason or entry["applicabilityReason"])}</td></tr>'
        )
    counts = assessment["counts"]
    return (
        '<section id="coverage" class="panel"><h2>Coverage and traceability</h2>'
        '<p>Catalog definitions, scheduled selectors, diagnostic rows and human work items are different measures. '
        'Shared evidence does not turn distinct assertions into additional executed checks.</p>'
        f'<details><summary>Coverage reconciliation: {counts["catalogDefinitions"]} definitions, '
        f'{counts["scheduledSelectors"]} scheduled selectors, {counts["observedRows"]} result rows</summary>'
        '<label class="coverage-toggle"><input id="required-only" type="checkbox"> Show required definitions only</label>'
        '<div class="table-scroll"><table><thead><tr><th>Checkpoint</th><th>Applicability</th><th>Requirement</th>'
        '<th>Observed rows</th><th>Evidence</th><th>Reason</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table></div></details></section>"
    )


def _diagnostics(r: RunResult) -> str:
    coverage = {entry["checkpointId"]: entry for entry in r.da_assessment["coverage"]}
    counts = Counter(row.status for row in r.results)
    rows = []
    for row in r.results:
        advisory = row.checkpoint_id in coverage and not coverage[row.checkpoint_id]["deploymentRequired"]
        summary = "Shared discovery warning; see root cause above." if row.checkpoint_id in {"ENV-004", "ENV-004-COVERAGE"} else row.result
        rows.append(
            f"<tr><th scope=\"row\"><code>{_e(row.checkpoint_id)}</code><br>{_e(row.description)}"
            + ("<span class=\"advisory\">Advisory / observation</span>" if advisory else "")
            + f"</th><td>{_badge(row.status)}</td><td><details><summary>{_e(_mask_sensitive(summary[:160]))}"
            + ("…" if len(summary) > 160 else "")
            + "</summary>"
            + ('<p><a href="#dependency-detail">Shared dependency discovery</a></p>' if row.checkpoint_id in {"ENV-004", "ENV-004-COVERAGE"}
               else f"<p>{_prose(row.result)}</p>")
            + (f"<p>{_prose(row.remediation)}</p>" if row.remediation else "")
            + (f'<p>{_prose(f"[Documentation]({row.doc_link})")}</p>' if row.doc_link else "")
            + f"</details></td><td>{_e(', '.join(row.roles))}</td></tr>"
        )
    stats = " ".join(
        f'<span class="stat">{counts[status]} {_e(status)}</span>'
        for status in ("Passed", "Failed", "Blocked", "Error", "Warning", "Manual", "Skipped", "NotConfigured")
    )
    return (
        '<section id="diagnostics" class="panel"><h2>Diagnostic inventory</h2>'
        f'<p>Diagnostics: {_e(r.overall)}. Diagnostic statuses are unchanged; deployment readiness is a separate decision.</p>'
        f'<div class="status-counts">{stats}</div>'
        '<p>Skipped means not verified, never Passed. Blocked means verification could not finish, not a confirmed defect. '
        'Advisory observations do not create evidence tasks.</p>'
        f'<details><summary>Inspect all {len(r.results)} diagnostic rows</summary><div class="table-scroll">'
        '<table><thead><tr><th>Check</th><th>Status</th><th>Observation and guidance</th><th>Owner</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table></div></details></section>"
    )


def render_da_report(r: RunResult) -> str:
    assessment = r.da_assessment
    counts, target = assessment["counts"], assessment["target"]
    work, work_count = _work_queue(r)
    state = assessment["deploymentReadiness"]
    state_class = {"READY": "success", "NOT_READY": "danger"}.get(state, "attention")
    metrics = "".join(
        f'<div class="metric"><strong>{counts[key]}</strong><span>{label}</span></div>'
        for key, label in (
            ("requiredDefinitions", "Required definitions"), ("satisfied", "Satisfied requirements"),
            ("defects", "Confirmed required defects"), ("incomplete", "Unresolved requirements"),
        )
    )
    dependency = next((row for row in r.results if row.checkpoint_id == "ENV-004-COVERAGE"), None)
    root_cause = (
        '<details class="root-cause" id="dependency-detail"><summary>Shared dependency discovery needs review</summary>'
        '<p>This affects the exact-binding checks below. SAP checks remain excluded, but names alone do not prove '
        'unclassified topics inactive or unrelated to the selected agent. Do not discard dependencies by filename.</p>'
        f'<p>{_prose(dependency.result)}</p></details>'
    ) if dependency else ""
    reviews = "".join(
        f'<li><code>{_e(review["checkpointId"])}</code>: '
        + ("accepted reviewed attestation" if review["accepted"] else
           "rejected — " + _e("; ".join(_REASONS.get(code, _field_name(code)) for code in review["reasonCodes"])))
        + (f'; source: {_e(_mask_sensitive(review["source"]))}; valid until {_e(review["validUntil"])}'
           if review["accepted"] else "")
        + "</li>" for review in assessment["evidenceReviews"]
    )
    issues = "".join(f"<li>{_e(_field_name(issue))}</li>" for issue in assessment["issues"])
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark"><title>DA FlightCheck assessment</title>'
        f"<style>{_CSS}</style></head><body>"
        '<a class="skip-link" href="#overview">Skip to assessment</a><div class="app">'
        '<aside class="sidebar"><div class="brand"><span class="brand-icon" aria-hidden="true">✓</span>'
        '<div>Employee Self-Service<br><strong>FlightCheck</strong></div></div>'
        '<nav aria-label="Report sections"><a href="#overview">Assessment overview</a><a href="#work">Work queue</a>'
        '<a href="#evidence">Evidence and rerun</a><a href="#diagnostics">Diagnostic inventory</a>'
        '<a href="#coverage">Coverage and traceability</a></nav>'
        '<p class="sidebar-note">Read-only assessment<br>No automatic repairs, publishing or employee transactions.</p></aside>'
        '<main><header id="overview" class="panel overview"><div><p class="eyebrow">DA deployment readiness</p>'
        f'<h1>{_e(target["agentSlug"] or "Selected DA")}</h1><span class="decision {state_class}">{_e(state)}</span>'
        '<p>Approval applies only to this exact target and realm. Missing proof is not a confirmed defect.</p></div>'
        '<dl class="target"><dt>Deployment realm</dt>'
        f'<dd>{_e(target["realm"])}</dd><dt>Service ring</dt><dd>{_e(target["serviceRing"])}</dd>'
        f'<dt>Run</dt><dd>{_e(r.started)}</dd><dt>Duration</dt><dd>{r.duration_secs}s</dd></dl>'
        f'<div class="metrics">{metrics}</div>'
        '<p class="overview-note">Complete accounting is not complete verification. Skipped administrator checks '
        'and unaccepted manual evidence cannot make deployment READY.</p>'
        + (f'<div class="context-gaps"><h3>Assessment context needs attention</h3><ul>{issues}</ul></div>' if issues else "")
        + '</header>'
        '<section id="work"><div class="section-heading"><div><h2>Work queue</h2>'
        f'<p>{work_count} grouped work items · {counts["incomplete"]} unresolved required definitions · '
        f'{counts["unknownApplicability"]} unknown-applicability definitions. '
        'Each named requirement keeps its own acceptance criteria.</p></div></div>'
        '<div class="toolbar" hidden><label>Filter work<select id="work-filter"><option value="all">All work</option>'
        '<option value="evidence">Evidence collection</option><option value="administrator">Administrator handoffs</option>'
        '<option value="verification">Automated verification</option><option value="applicability">Applicability decisions</option>'
        '</select></label><label class="search-label">Search<input id="work-search" type="search" placeholder="Requirement, owner or checkpoint"></label>'
        '<span id="visible-work" role="status"></span></div>'
        + root_cause
        + (f'<div class="work-grid">{work}</div>' if work else '<div class="panel">No unresolved required work items.</div>')
        + '<p id="no-work-match" hidden>No work items match this filter.</p></section>'
        '<section id="evidence" class="panel"><h2>Evidence and rerun</h2><div class="evidence-grid"><div>'
        '<h3>How evidence becomes accepted</h3><ol><li>Collect the specific evidence listed under each requirement.</li>'
        '<li>Have the owning reviewer record its source, outcome and explicit validity window for this target/revision.</li>'
        '<li>Submit the reviewed JSON envelope with <code>--da-evidence</code> on the next standalone full run.</li></ol>'
        '<p>Combine the reviewed records into one envelope, with one record per checkpoint. Retain still-valid '
        'records from earlier reviews when adding evidence for another requirement.</p>'
        '<p>No browser checkbox verifies a requirement. Templates start unreviewed. '
        'Administrator and employee evidence is reviewer-declared, not an automatically authenticated test.</p>'
        f'<details><summary>Exact target and configuration revision</summary><pre>{_e(json.dumps(target, indent=2))}</pre>'
        f'<p>Configuration revision: <code>{_e(assessment["configurationRevision"] or "Unavailable: exact snapshot not verified")}</code></p></details>'
        + (f"<h3>Evidence reviews</h3><ul>{reviews}</ul>" if reviews else "<p>No external evidence was submitted for review.</p>")
        + (f'<p>Unrecognized evidence checkpoints: {_e(", ".join(assessment["unrecognizedEvidenceCheckpoints"]))}</p>'
           if assessment["unrecognizedEvidenceCheckpoints"] else "")
        + (f"<h3>Assessment context gaps</h3><ul>{issues}</ul>" if issues else "")
        + "</div><div><h3>Rerun this full assessment</h3>" + _rerun(assessment)
        + '</div></div></section>'
        + _diagnostics(r) + _coverage(assessment)
        + '<footer>Offline report · No external assets or tracking · '
        '<a href="results.json">Full JSON evidence</a></footer></main></div>'
        f"<script>{_SCRIPT}</script></body></html>"
    )


_CSS = """
:root{font-family:'Segoe UI Variable','Segoe UI',system-ui,sans-serif;color-scheme:light dark;
 --bg:#f5f5f5;--surface:#fff;--ink:#242424;--muted:#616161;--line:#e0e0e0;--accent:#0f6cbd;
 --success:#0e6b0e;--success-bg:#dff6dd;--danger:#a4262c;--danger-bg:#fde7e9;
 --attention:#835b00;--attention-bg:#fff4ce;--neutral-bg:#f0f0f0;--radius:8px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.55}
a{color:var(--accent);text-underline-offset:3px}button,input,select,textarea{font:inherit}
button,select,input[type=search]{border:1px solid var(--line);border-radius:4px;padding:8px 10px;background:var(--surface);color:var(--ink)}
button{cursor:pointer;color:var(--accent);font-weight:600}button:hover{background:var(--neutral-bg)}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
[hidden]{display:none!important}.app{display:grid;grid-template-columns:232px minmax(0,1fr);max-width:1920px;margin:auto}
.sidebar{position:sticky;top:0;height:100vh;padding:28px 18px;border-right:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:12px;font-size:13px;margin:0 8px 28px}
.brand strong{font-size:20px}.brand-icon{display:grid;place-items:center;width:38px;height:38px;border-radius:8px;background:var(--accent);color:white;font-size:23px}
nav{display:grid;gap:5px}nav a{padding:10px 14px;color:var(--ink);text-decoration:none;border-radius:4px}
nav a:hover{background:var(--surface);color:var(--accent)}.sidebar-note{margin:32px 12px;font-size:12px;color:var(--muted)}
main{padding:28px 36px;min-width:0}section,header{scroll-margin-top:20px;margin-bottom:28px}
.panel,.work-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 2px 4px #00000005}
.panel{padding:24px}.overview{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:20px 32px;border-top:3px solid var(--accent)}
.eyebrow{font-weight:600;color:var(--muted);margin:0 0 8px}h1{font-size:28px;line-height:1.25;overflow-wrap:anywhere;margin:0 0 16px;font-weight:600}
h2{font-size:21px;line-height:1.35;margin:0 0 8px;font-weight:600}h3{font-size:16px;margin:0 0 8px;font-weight:600}h4{font-size:14px;margin:18px 0 6px}
p{margin:8px 0 12px}.muted,.section-heading p{color:var(--muted);font-size:13px}.overview p{max-width:760px}
.decision{display:inline-flex;border-radius:4px;padding:5px 14px;font-size:17px;font-weight:600}
.success{color:var(--success);background:var(--success-bg)}.danger{color:var(--danger);background:var(--danger-bg)}
.attention{color:var(--attention);background:var(--attention-bg)}.neutral{color:var(--muted);background:var(--neutral-bg)}
.target{display:grid;grid-template-columns:auto auto;gap:6px 18px;align-content:start;font-size:13px}
dt{color:var(--muted)}dd{margin:0;font-weight:600}.metrics{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.metric{padding:16px;border:1px solid var(--line);border-radius:6px}.metric strong{display:block;font-size:30px;line-height:1.3;font-weight:600}
.metric span{color:var(--muted);font-size:13px}.overview-note{grid-column:1/-1;color:var(--muted);font-size:13px;margin:0}
.context-gaps{grid-column:1/-1;background:var(--attention-bg);padding:16px;border-radius:4px}
.toolbar{display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin:18px 0}.toolbar label{display:grid;gap:4px;font-size:12px;color:var(--muted)}
.search-label{flex:1;min-width:180px}.toolbar input{width:100%}#visible-work{color:var(--muted);font-size:12px;padding-bottom:8px}
.work-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;align-items:start}
.work-card{padding:20px;min-width:0}.card-heading{display:flex;align-items:start;justify-content:space-between;gap:12px}
.badge{display:inline-block;white-space:nowrap;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600}
summary{cursor:pointer;font-weight:600;padding:10px 0;overflow-wrap:anywhere}details[open]>summary{margin-bottom:4px}
.requirement{border-top:1px solid var(--line);margin-top:12px}.requirement summary{display:flex;align-items:start;justify-content:space-between;gap:12px}
.requirement summary>span:first-child{min-width:0}.requirement summary strong{font-size:13px;font-weight:600}
.requirement summary code{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:3px}
.requirement summary::before{content:'+';color:var(--accent);font-size:17px;line-height:1.2}
.requirement[open]>summary::before{content:'−'}.requirement summary>span:first-of-type{flex:1}
.requirement-body{font-size:13px;padding:0 0 8px 20px}.field-list{padding-left:18px}.field-list code{font-size:11px;color:var(--muted)}
.root-cause{background:var(--attention-bg);border:1px solid var(--line);border-left:3px solid var(--attention);padding:8px 18px;border-radius:6px;margin:16px 0}
.root-cause p{font-size:13px;overflow-wrap:anywhere}.evidence-grid{display:grid;grid-template-columns:1fr 1fr;gap:32px}
pre,textarea{font-family:Consolas,ui-monospace,monospace;font-size:12px;line-height:1.6}
pre{padding:16px;background:var(--neutral-bg);border-radius:4px;white-space:pre-wrap;overflow-wrap:anywhere}
code{font-family:Consolas,ui-monospace,monospace;font-size:.9em;overflow-wrap:anywhere}
textarea{display:block;width:100%;min-height:240px;resize:vertical;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:4px;padding:12px;margin:10px 0}
.copy-status{font-size:12px;margin-left:10px}.table-scroll{overflow:auto;max-width:100%}table{width:100%;border-collapse:collapse;font-size:12px;text-align:left}
th,td{padding:12px;vertical-align:top;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
thead{background:var(--neutral-bg)}tbody th{font-weight:600;min-width:180px}td details{min-width:180px;max-width:680px}
.status-counts{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.stat{padding:5px 10px;background:var(--neutral-bg);border-radius:4px;font-size:12px}
.advisory{display:block;font-size:11px;color:var(--muted);font-weight:400}.coverage-toggle{display:block;margin:12px 0}
footer{display:flex;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:12px;padding-bottom:16px}
.skip-link{position:absolute;left:12px;top:-100px;padding:10px;background:var(--surface);z-index:10}.skip-link:focus{top:12px}
@media(min-width:1700px){.work-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:1100px){.app{grid-template-columns:190px minmax(0,1fr)}main{padding:24px}.work-grid{grid-template-columns:1fr}}
@media(max-width:760px){.app{display:block}.sidebar{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line);padding:16px}
 .brand{margin:0 0 12px}nav{display:flex;flex-wrap:wrap;gap:0}nav a{padding:6px 10px;font-size:12px}.sidebar-note{display:none}
 main{padding:16px}.panel,.work-card{padding:18px}.overview{grid-template-columns:1fr}.target{justify-content:start}
 .metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.evidence-grid{grid-template-columns:1fr}.metric strong{font-size:26px}
 .card-heading{flex-wrap:wrap}.requirement summary{flex-wrap:wrap}.requirement summary>.badge{margin-left:28px}h1{font-size:24px}}
@media(prefers-color-scheme:dark){:root{--bg:#141414;--surface:#1f1f1f;--ink:#f5f5f5;--muted:#c2c2c2;--line:#424242;--accent:#75b6e7;
 --success:#9fd89f;--success-bg:#052505;--danger:#f1bbbc;--danger-bg:#442726;--attention:#fce100;--attention-bg:#443b18;--neutral-bg:#292929}}
@media print{.app{display:block}.sidebar,.toolbar,.copy-template{display:none}main{padding:0}.work-grid{display:block}.work-card{break-inside:avoid;margin-bottom:12px}}
"""


_SCRIPT = """
document.querySelector('.toolbar').hidden = false;
const cards = Array.from(document.querySelectorAll('.work-card'));
function filterWork() {
  const kind = document.getElementById('work-filter').value;
  const search = document.getElementById('work-search').value.trim().toLowerCase();
  let shown = 0;
  cards.forEach(card => {
    card.hidden = !((kind === 'all' || card.dataset.kinds.split(' ').includes(kind)) &&
      card.textContent.toLowerCase().includes(search));
    if (!card.hidden) shown++;
  });
  document.getElementById('visible-work').textContent = shown + ' of ' + cards.length + ' work items';
  document.getElementById('no-work-match').hidden = shown !== 0;
}
document.getElementById('work-filter').addEventListener('change', filterWork);
document.getElementById('work-search').addEventListener('input', filterWork);
document.getElementById('required-only').addEventListener('change', event => {
  document.querySelectorAll('#coverage tr[data-required]').forEach(row => {
    row.hidden = event.target.checked && row.dataset.required !== 'true';
  });
});
document.addEventListener('click', async event => {
  const button = event.target.closest('.copy-template');
  if (!button) return;
  const template = button.closest('.template');
  const text = template.querySelector('textarea');
  const status = template.querySelector('.copy-status');
  try {
    await navigator.clipboard.writeText(text.value);
    status.textContent = 'Unreviewed template copied. Owning review is still required.';
  } catch (error) {
    text.focus(); text.select();
    status.textContent = 'Clipboard unavailable. Copy the selected template manually.';
  }
});
function openTarget(hash) {
  const target = hash && document.getElementById(hash.slice(1));
  if (!target) return;
  let element = target;
  while (element) {
    if (element.tagName === 'DETAILS') element.open = true;
    element = element.parentElement;
  }
  const card = target.closest('.work-card');
  if (card && card.hidden) {
    document.getElementById('work-filter').value = 'all';
    document.getElementById('work-search').value = '';
    filterWork();
  }
  target.scrollIntoView({block: 'start'});
}
document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="#"]');
  if (link) openTarget(link.getAttribute('href'));
});
openTarget(location.hash);
window.addEventListener('hashchange', () => openTarget(location.hash));
filterWork();
"""
