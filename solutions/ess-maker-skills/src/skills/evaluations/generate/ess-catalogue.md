# ESS scenario catalogue

Scenario-planning data for the Employee Self-Service (ESS) experience. This file is **data only** — the eval generation skill owns the behavior. Read it before you classify, order, surface dependencies, or decompose scenarios into tasks, and do not introduce a category, connector, persona, role, dependency edge, criterion, priority, tier, or order it does not define.

It carries only the decision layer that is **not reliably fetchable at runtime** (priority rubric, category map, dependency edges, extensible domains, adoption lifecycle, roles). Per-scenario specifics — fields, setup steps, connector config, role permissions, country/region availability — are fetched from Microsoft Learn at render time, never duplicated here, so the catalogue cannot drift.

## ESS agent goals

The business goals that motivate prioritization:

- **Ticket deflection** — resolve HR/IT issues in the agent before a ticket is created. This is the primary value driver.
- **Employee satisfaction and confidence** — end-to-end resolution, not just a link.
- **Operational efficiency** — lower cost-per-resolution by shifting volume to self-service.
- **Time-to-resolution reduction** — faster than traditional ticket workflows.
- **Knowledge quality and reuse** — knowledge-first resolution before escalation.

A scenario **deflects** when the interaction resolves without creating a downstream ticket. The four deflection types: pre-ticket resolution, guided self-service, decision closure, and knowledge confirmation.

## Prioritization framework

Five criteria for deciding enablement order. Weigh them together and name which criteria drove a recommendation; never improvise another framework.

1. **Frequency + ticket deflection** — how often the scenario is triggered and its deflection potential (knowledge and profile reads are highest).
2. **Governance safety** — least privilege, auditability, compliance risk (reads are safer than writes).
3. **Connector readiness** — whether the required connector is available and stable in the tenant.
4. **Change-management complexity** — how much organizational change is required.
5. **Cross-role clarity** — whether the roles and responsibilities are clear.

Principles:

- Start with high-confidence, low-risk scenarios (for example, HR Policy Lookup, employee profile reads), then expand.
- Avoid scenarios that require heavy per-country logic early.
- MVP scope drives priority — not a numeric ranking.
- Readiness checklists are go/no-go gates for scenario activation.

Confidence (`High` / `Med` / `Low`) is derived by applying these criteria to the selection, not stored per category; lower it when a required connector or prerequisite is unmet.

Cost, price, cheapest-first, budget, and ROI are **not** among these criteria and are not supported prioritization dimensions.

## Default order and priority tiers

Default order (the deterministic baseline — emit verbatim unless the Maker overrides; never re-derive):

**Knowledge retrieval → Ticketing → Employee profile read/write → Agent handoff → Sensitive topics → Multi-language → Mobile access.**

The default order is authoritative and emitted verbatim; a category's tier never moves it ahead of a category the default order sequences before it. The first four are OOB categories; the last three are cross-cutting rollout concerns (sequence last). The tiers below break ties and place any category the default line does not name:

- **Tier 1 — Foundation (deflect first):** HR Knowledge Retrieval, IT Knowledge & Troubleshooting, HR Profile Read. High deflection, low governance.
- **Tier 2 — Transactions:** HR Ticketing, IT Ticketing. Complementary to deflection — they handle what knowledge cannot deflect.
- **Tier 3 — Writes & manager:** HR Profile Write, Manager Direct-Reports. Higher governance; enable a category's reads before its writes.
- **Tier 4 — Escalation & cross-cutting:** Agent Handoff (needs a ticketing connector); the cross-cutting rollout concerns above; and any extensible domain.

Tie-break within a tier: deflection descending → governance ascending → change complexity ascending → the Maker's stated emphasis. Connector readiness and cross-role clarity act as dependency and confidence signals, not tie-break keys.

## Scenario inventory

The supported OOB category map Cocreate maps goals to. Fetch each category's specific scenarios and setup detail from Learn at runtime; the `#` ranges below index the OOB scenario inventory (43 scenarios).

| Category                      | Domain | Persona  | Scenarios | Connector(s)                                              |
| ----------------------------- | ------ | -------- | --------- | --------------------------------------------------------- |
| HR Knowledge & Profile (Read) | HR     | Employee | #1-19     | SharePoint; ServiceNow Graph; SAP SuccessFactors; Workday |
| HR Profile Update (Write)     | HR     | Employee | #20-25    | Workday; SAP SuccessFactors                               |
| Manager Scenarios             | HR     | Manager  | #26-31    | SAP SuccessFactors                                        |
| HR Ticketing                  | HR     | Employee | #32-34    | ServiceNow HRSD                                           |
| IT Scenarios                  | IT     | Employee | #35-41    | SharePoint; ServiceNow ITSM; Microsoft Self-Help          |
| Handoff Scenarios             | Cross  | Employee | #42-43    | ServiceNow (Now Assist / live agent)                      |

Representative scenarios (for goal mapping — enumerate specifics from Learn):

- **Knowledge & Profile Read (#1-19):** HR Policy Lookup; HR Knowledge Retrieval (ServiceNow KB / SAP SuccessFactors); Workday profile reads — Employee ID, Job Details, Company Code, Cost Center, Hire Date, Compensation Ratio, Base Compensation, Service Anniversary, Employment/Contact Info, Emergency Contact, National IDs, Passports, Visas, Certifications, Language Info. Read-only.
- **Profile Update Write (#20-25):** Update Email, Phone, Preferred Name, Emergency Contact, Veteran Info, Race/Ethnicity. Flow: get → confirm → submit → success/fail.
- **Manager (#26-31):** view/update direct-reports Job Details, Cost Center, Company Code, Service Anniversary; Update Cost Center; Update Job Title.
- **HR Ticketing (#32-34):** Read HR Tickets; Create HR Ticket; Update HR Case.
- **IT (#35-41):** IT Knowledge Retrieval; Read/Create/Update IT Ticket; Windows Troubleshooting; M365 Support; IT Ticket Handoff to Live Agent.
- **Handoff (#42-43):** to ServiceNow Now Assist; to Live Agent.

## Outcome-level scenarios

Meta-scenarios that span multiple topics and name the end-to-end outcome, with the success metric:

- **End-to-End Ticket Avoidance** — resolve fully so no ticket exists. Key topics: HR Policy Lookup, IT Knowledge Retrieval, profile reads, Windows Troubleshooting, M365 Support. Metric: deflection rate.
- **Self-Service First, Escalation Second** — try knowledge → try action → only then a pre-filled ticket or handoff. Metric: escalation rate and escalated-ticket quality.
- **Knowledge-First Resolution** — knowledge is the primary path; tickets are the exception. Metric: knowledge resolution rate.
- **Single Front Door** — one entry point routes/resolves/escalates across HR and IT. Metric: cross-domain resolution rate; fewer "wrong door" tickets.
- **Deflection with Dignity** — context-aware handoff (history, employee details, attempted resolutions) avoids bot dead-ends. Key topics: Handoff scenarios; Create HR/IT Ticket. Metric: handoff satisfaction; post-escalation time-to-resolution.

## Dependencies and readiness

Dependencies are connector/readiness prerequisites — distinct from priority.

Connector groupings:

- Knowledge scenarios (#1-3, #35) require SharePoint or the ServiceNow Graph Connector knowledge source configured.
- Profile read/write scenarios (#4-25) require the Workday or SAP SuccessFactors connector installed and configured; enable reads before writes.
- Ticketing scenarios (#32-34, #36-38) require the ServiceNow HRSD/ITSM connector.
- Handoff scenarios (#42-43) require ServiceNow live agent or Now Assist configuration, plus a Ticketing category as the deflection path.
- Manager scenarios (#26-31) require the SAP SuccessFactors connector plus manager context.

Scenario-level prerequisite edges:

- **Agent Handoff requires a Ticketing category** (HR or IT) — handoff escalates a ticket, so Handoff without Ticketing is a gap.
- **Knowledge Retrieval is the deflection foundation** — Ticketing, Profile, and Handoff all work best after it; skipping Knowledge means more tickets are created instead of deflected.

## Extensible scenarios

Not preconfigured OOB — buildable via Copilot Studio and Power Platform (Cocreate supports planning and scaffolding, not content authoring). Extensible domains are Tier 4 unless the Maker pins them.

| ID   | Scenario                                                                                             | Category   | Extension type                                    |
| ---- | ---------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------- |
| E1   | Request Time Off                                                                                     | HR         | Custom topic + connector                          |
| E2   | Service Anniversaries                                                                                | HR         | Experience-level scenario                         |
| E3   | Custom HR Policy Flows                                                                               | HR         | Custom topic + knowledge                          |
| E4   | Advanced IT Request Workflows                                                                        | IT         | Custom connector workflow                         |
| E5   | Experience Customization                                                                             | Cross      | Experience Manager config                         |
| E6   | Location-Aware Eligibility                                                                           | HR         | Custom topic logic                                |
| E7   | Custom Connector Integration                                                                         | Cross      | Custom connector                                  |
| Fac. | Facilities (room/desk booking, badge/building access, maintenance requests, move/relocation support) | Facilities | Custom topic + Facilities/security/ITSM connector |

Out-of-ESS examples — a goal that matches no ESS HR/IT/Facilities category at all: travel, expense, CRM/Salesforce, payroll processing, procurement.

New domains beyond HR / IT / Cross / Facilities (e.g. Operations) and new scenarios are added by editing this catalogue (configuration, not code) and existing plans keep working; a scenario may be marked `deprecated` — still shown on an existing plan with a deprecation notice, but never offered in new intake.

## Roles and personas

`persona` and `role` are distinct:

- **Persona** — the end user of the configured agent that a scenario serves: `Employee`, or `Manager` for direct-reports scenarios.
- **Deployment role** — the actor who configures the scenario in Cocreate. A scenario typically needs several roles and so decomposes into multiple single-role tasks (one assignee each).

Scenario-planning roles:

| Role                          | Responsibility                              |
| ----------------------------- | ------------------------------------------- |
| Maker (Copilot Studio)        | Topics, instructions, connectors, workflows |
| Experience Manager (in-agent) | Localized prompts, landing-page experience  |
| Admin                         | Enablement, user assignment, governance     |

For coarse planning, reason only from the scenario-planning roles above (Maker, Experience Manager, Admin) to judge which kinds of actor a scenario involves and to flag a missing actor as a risk — do not enumerate any finer role list here. The role LABEL shown on a rendered task (and its Learn link) MUST be taken VERBATIM from that task's Learn page — never relabeled, invented, or mapped to a fixed catalogue list. When Learn lists alternative eligible roles for one task, name them as Learn presents them (`any of: X / Y / Z`); when Learn assigns distinct responsibilities to different roles, SPLIT into separate single-role tasks. Fetch the role, its permissions, and connector-auth responsibilities from Learn at render time; never fabricate a role.

## Customer adoption lifecycle

- **Discovery** — scenario definition and governance readiness; understand org structure, HR/IT ownership, decision authority; identify systems (ServiceNow, Workday, SAP SuccessFactors, SharePoint); assess governance maturity. Output: prioritized scenario list, role/ownership clarity, blockers.
- **Build** — in Copilot Studio + Cocreate; a planning/guidance layer, not an execution engine; guides scenario setup; produces persistent artifacts; tracks progress without changing platform state.
- **Pilot** — controlled, scenario-scoped, tenant-limited; a small known cohort (often internal HR/IT first); one or two high-value scenarios; explicit success criteria up front.
- **Production** — gated by governance confidence, scenario stability, connector reliability, adoption readiness; Cocreate persists post-go-live as a planning/decision surface.

## Onboarding journey

Reference for the staged discovery flow — the skill owns advancing one stage per turn and the plan gate. Decision layer only: every product specific here (pillar wording, Workday capabilities/fields, deployment roles) is fetched and cited from Microsoft Learn at render time, never surfaced from here as authoritative.

- **Value pillars** — at Fit, name ≥2 ESS value themes and a one-line product summary, taken from the Learn overview this turn. Cocreate guides Workday setup only.
- **Workday framing** (non-fetchable guardrails only): a solution accelerator (Topics + Connectors + Flows + Templates) and a profile read/write connector, not a knowledge source; Preview — Dev/UAT co-build, start small, not production; don't overclaim (no payroll, no benefits enrollment), never promise SLAs/ROI or disparage the portal. The OOB read/write field set is connector config — fetch it from the Workday Learn page, never inline it here.
- **Deployment roles** — identify one owner per required role via the coarse role rule and the Learn role tables (fetched at render time); do NOT keep a separate discovery roster here.
- **Canonical plan sequence** (Cocreate task skeleton — the order is decision layer; each step's content is fetched from Learn): new Early Release environment → Prepare → Readiness FlightCheck → Install ESS HR starter → Install ESS ADK → Configure Workday (ADK) → FlightCheck (Workday) → Customize → Write evals.

## KPIs and measurement

- KPIs: ticket deflection rate; assist-to-deflect ratio; average time to resolution; agent adoption (daily/weekly/monthly active users); repeat usage / return rate; user satisfaction (thumbs up/down, or customer satisfaction).
- Measurement methods: conversation-level outcomes (resolved vs. escalated); system-level correlation (no ticket created after the interaction); user confirmation signals.

## Connector setup scope

Connectors in scope for full setup guidance: **Workday only**. All others (ServiceNow HRSD/ITSM, SAP SuccessFactors, Dynamics 365, and any other) are prerequisite-only — a scenario needing them still appears in the plan, with the connector named as a prerequisite.

## Microsoft Learn anchors

ESS Learn seed pages — search entry points and a fallback citation when a this-turn fetch returns nothing, NOT pre-authorized links. Any clickable/deep link must be fetched this turn (per `instructions.md` grounding + Links rules); use these only to seed search and to know which page is canonical (e.g. `workday-simplified-setup` is current, `workday` is legacy). Never invent or alter a URL.

- overview: <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/overview>
- deployment-checklist: <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/deployment-checklist>
- prerequisites: <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/prerequisites>
- prepare: <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/prepare>
- install: <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/install>
- customize: <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/customize>
- design-best-practices: <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/design-best-practices>
- servicenow: <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/servicenow>
- workday (simplified setup, default for new deployments): <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/workday-simplified-setup>
- workday-legacy (ISU + RaaS; existing deployments only): <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/workday>
- deploy-overview-alm: <https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/deploy-overview-alm>

## Walkthrough example (reference)

A worked example of the four-part walkthrough shape for an ESS install task (the skill owns the shape in "Rendering a task walkthrough"; each step ends with an inline `learn.microsoft.com` link, not a citation pill). Fill links from Learn at render time; never render `url` literally.

```text
Sure - here's what installing the HR starter involves.

### Install the HR agent starter

**Role:** Environment administrator - one person with this role installs the starter end to end. ([Power Platform environment roles](url))

Installing the HR starter puts the ESS agent and its accelerator packages into your environment - the Install stage of the Prepare, Install, Customize, Publish lifecycle. Prerequisite: a Global admin has assigned the Power Platform Administrator and Environment Maker roles and created a new environment.

### Steps

- **Open your target ESS environment in Copilot Studio.** As the Environment administrator, sign in to Copilot Studio and switch to the new ESS environment via the environment picker in the top bar. You are in the right place when the environment name shows in the header and no agent is listed yet under Agents. ([Copilot Studio environments](url))
- **Install the Employee Self-Service HR starter.** From the ESS install entry point, add the agent and its HR accelerator packages and accept the connector prompts. It succeeded when the new agent appears under Agents; deploying both HR and IT, install one at a time so each package settles. ([install the ESS agent](url))
- **Confirm readiness with FlightCheck.** Run FlightCheck to validate licenses, environment config, integrations, and agent files. All-green means you can customize; if a check fails, open it, fix the flagged item, and rerun before moving on. ([FlightCheck](url))

| Steps | Task |
| --- | --- |
| 1 | Open the target environment |
| 2 | Install the HR starter |
| 3 | Confirm readiness with FlightCheck |

### 📚 Help & resources

- [Introduction to Employee Self-Service](url) - what the agent and the HR/IT starters do.
- [Customize the Employee Self-Service agent](url) - roles, building blocks, knowledge sources, topics.
```
