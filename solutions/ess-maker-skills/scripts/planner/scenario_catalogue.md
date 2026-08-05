# ESS scenario catalogue (vendored — scenario planning data)

> **Provenance.** Vendored snapshot of the authoritative ESS scenario catalogue
> (the ESS agent's own scenario‑planning data). This file carries **only** the
> decision layer the planner needs to capture a sponsor's goal — the **scenario
> list, priority, and dependency order**. Per‑scenario detail (fields, setup
> steps, connector config, roles, region availability) is **fetched from Microsoft
> Learn at render time**, never duplicated here.
>
> **Do not invent.** Do not introduce a category, connector, persona, dependency
> edge, priority, tier, or order this file does not define. Re‑sync from the
> upstream ESS catalogue when it changes; this is a snapshot, not the master.

## Scenario list

Out‑of‑the‑box category map (43 OOB scenarios; `#` ranges index the inventory):

| # range | Category | Domain | Persona | Connector(s) |
|---|---|---|---|---|
| #1–19 | HR Knowledge & Profile (Read) | HR | Employee | SharePoint; ServiceNow Graph; SAP SuccessFactors; Workday |
| #20–25 | HR Profile Update (Write) | HR | Employee | Workday; SAP SuccessFactors |
| #26–31 | Manager Scenarios | HR | Manager | SAP SuccessFactors |
| #32–34 | HR Ticketing | HR | Employee | ServiceNow HRSD |
| #35–41 | IT Scenarios | IT | Employee | SharePoint; ServiceNow ITSM; Microsoft Self‑Help |
| #42–43 | Handoff Scenarios | Cross | Employee | ServiceNow (Now Assist / live agent) |

Named scenarios (enumerate specifics from Learn at runtime):

- **Knowledge & Profile Read (#1‑19):** HR Policy Lookup; HR Knowledge Retrieval (ServiceNow KB / SAP SuccessFactors); Workday profile reads — Employee ID, Job Details, Company Code, Cost Center, Hire Date, Compensation Ratio, Base Compensation, Service Anniversary, Employment/Contact Info, Emergency Contact, National IDs, Passports, Visas, Certifications, Language Info. Read‑only.
- **Profile Update Write (#20‑25):** Update Email, Phone, Preferred Name, Emergency Contact, Veteran Info, Race/Ethnicity.
- **Manager (#26‑31):** view/update direct‑reports Job Details, Cost Center, Company Code, Service Anniversary; Update Cost Center; Update Job Title.
- **HR Ticketing (#32‑34):** Read HR Tickets; Create HR Ticket; Update HR Case.
- **IT (#35‑41):** IT Knowledge Retrieval; Read/Create/Update IT Ticket; Windows Troubleshooting; M365 Support; IT Ticket Handoff to Live Agent.
- **Handoff (#42‑43):** to ServiceNow Now Assist; to Live Agent.

Extensible scenarios (not OOB — buildable via Copilot Studio / Power Platform; Tier 4 unless the Maker pins them):

| ID | Scenario | Category |
|---|---|---|
| E1 | Request Time Off | HR |
| E2 | Service Anniversaries | HR |
| E3 | Custom HR Policy Flows | HR |
| E4 | Advanced IT Request Workflows | IT |
| E5 | Experience Customization | Cross |
| E6 | Location‑Aware Eligibility | HR |
| E7 | Custom Connector Integration | Cross |
| Fac. | Facilities (room/desk booking, badge/building access, maintenance, move/relocation) | Facilities |

Out‑of‑ESS (matches no HR/IT/Facilities category — say so, don't force‑fit): travel, expense, CRM/Salesforce, payroll processing, procurement.

## Priority

**Default order (authoritative — emit verbatim unless the Maker overrides; never re‑derive):**

**Knowledge retrieval → Ticketing → Employee profile read/write → Agent handoff → Sensitive topics → Multi‑language → Mobile access.**

The first four are OOB categories; the last three are cross‑cutting rollout concerns (sequence last). A category's tier never moves it ahead of a category the default order sequences before it.

**Priority tiers (break ties; place any category the default line doesn't name):**

- **Tier 1 — Foundation (deflect first):** HR Knowledge Retrieval, IT Knowledge & Troubleshooting, HR Profile Read. High deflection, low governance.
- **Tier 2 — Transactions:** HR Ticketing, IT Ticketing. Handle what knowledge cannot deflect.
- **Tier 3 — Writes & manager:** HR Profile Write, Manager Direct‑Reports. Higher governance; enable a category's reads before its writes.
- **Tier 4 — Escalation & cross‑cutting:** Agent Handoff (needs a ticketing connector); the cross‑cutting rollout concerns above; any extensible domain.

**Tie‑break within a tier:** deflection ↓ → governance ↑ → change‑complexity ↑ → the Maker's stated emphasis. Connector readiness and cross‑role clarity are dependency/confidence signals, **not** tie‑break keys. Cost/price/ROI are **not** prioritization dimensions.

## Dependency order

Dependencies are connector/readiness prerequisites — distinct from priority.

**Scenario‑level prerequisite edges:**

- **Agent Handoff requires a Ticketing category** (HR or IT) — handoff escalates a ticket; Handoff without Ticketing is a gap.
- **Knowledge Retrieval is the deflection foundation** — Ticketing, Profile, and Handoff all work best after it; skipping Knowledge means more tickets are created instead of deflected.
- **Enable a category's reads before its writes** (HR Profile Read before HR Profile Write).

**Connector/readiness prerequisites:**

- Knowledge scenarios (#1‑3, #35) → SharePoint or ServiceNow Graph knowledge source configured.
- Profile read/write scenarios (#4‑25) → Workday or SAP SuccessFactors connector (reads before writes).
- Ticketing scenarios (#32‑34, #36‑38) → ServiceNow HRSD/ITSM connector.
- Handoff scenarios (#42‑43) → ServiceNow live agent / Now Assist **plus a Ticketing category** as the deflection path.
- Manager scenarios (#26‑31) → SAP SuccessFactors connector plus manager context.
