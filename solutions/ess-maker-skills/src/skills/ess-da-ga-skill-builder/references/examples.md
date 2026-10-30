# Example skills

Read in Round 7 before drafting, to calibrate how much a skill should say. The examples are shortened. Tool names are illustrative; a real skill names tools exactly as the inventory does.

## Contents

- A thin skill over purpose-built tools
- A thick skill over building blocks
- An orchestration skill across knowledge and actions
- What to notice

## A thin skill over purpose-built tools

The tools include `sn__get_hr_cases` (the user's own cases, with filters, in a widget), `sn__create_hr_case_form` (a form that looks up HR services itself), `sn__get_hr_services` and `sn__update_hr_case` (with a `work_note` field). The skill only routes and sets boundaries.

```text
---
name: hr-cases
description: Shows, opens and updates the employee's own HR cases in ServiceNow, and adds notes to them. Use when someone wants to see their cases, check a case number (HRC…), open a case about pay, benefits, leave or personal details, change a case, cancel it or add a note, even if they only describe the problem ("my payslip is wrong"). Catalog requests are handled by service-catalog.
---

# HR cases

| User wants                  | Call                                                     | Notes                                           |
| --------------------------- | -------------------------------------------------------- | ----------------------------------------------- |
| See or find their cases     | `sn__get_hr_cases` with the filters they gave            | Call again every turn; never answer from memory |
| Open a case                 | `sn__create_hr_case_form`                                | Prefill subject, details and HR service         |
| Change or cancel a case     | `sn__get_hr_cases(number=..., action="edit")`            | Opens the edit form                             |
| Add a note                  | Confirm the text, then `sn__update_hr_case(sys_id=..., work_note=...)` |                                   |

To prefill the HR service, call `sn__get_hr_services(name=...)` with the issue's key words. If none clearly matches, open the form without one; the user picks.

## Rules

- The HR team assigns cases. If asked to reassign, say so in one sentence and call nothing.
- Closed or cancelled cases can't change; a new issue needs a new case.
- The widget is the answer: reply in one short sentence and don't restate its records.
```

## A thick skill over building blocks

The tools are `sn__list_records`, `sn__get_record`, `sn__create_record` and `sn__update_record` for any table, plus `sn__get_current_user_info`. The skill carries the procedure and the facts the old process had.

```text
---
name: hr-case-create
description: Opens a new HR case in ServiceNow for the employee or someone they name, in the HR service that matches the issue (payroll, benefits, leave, relocation, employment letters and more), and confirms it with its case number. Use when someone wants to open, raise, file or report an HR case or issue, or says something like "I need help with my payslip". Viewing and updating cases are hr-cases-view and hr-case-update.
---

# Open an HR case

Follow servicenow-basics for queries, finding people, confirmation and errors.

## Step 1: Understand the issue
Extract a summary (becomes short_description, under 100 characters), details (description), who it's for (default: the user) and urgency only if stated. Ask one question only if the summary is missing.

## Step 2: Choose the HR service
sn__list_records(table="sn_hr_core_service", query="active=true^nameLIKE<word>", fields="sys_id,name,service_table", limit=10)
One clear match: use it. Several: show up to 5 and ask. None: show the areas in references/coe-tables.md and ask which fits. Never ask the user for a table name.

## Step 3: Confirm
"I'll open a <service> case: "<summary>" for <person>. OK?" Skip if the user already said "go ahead" with everything.

## Step 4: Create
sn__create_record(table="<service_table of the service>", body={"hr_service": "<sys_id>", "short_description": "<summary>", "description": "<details>", "opened_for": "<person sys_id>", "subject_person": "<person sys_id>", "priority": "2"})
Priority "2" is what the previous HR process sent. If service_table is empty, use sn_hr_core_case.

## Step 5: Verify and report
Read the record back with sn__get_record and reply in one sentence with the case number. A 403 means the user can't open cases in that area: say so and suggest the HR portal.

## Don'ts
- Don't set assigned_to, assignment_group or state; HR routing sets them.
- Never repeat a create that returned a result.
```

## An orchestration skill across knowledge and actions

Modeled on the ESS agent's `hr-request-orchestration` skill. The agent has knowledge sources (an HR SharePoint site and a Copilot connector) and three area skills. The orchestration skill plans; the area skills do the work.

```text
---
name: hr-request-orchestration
description: Plans and routes compound, conditional or ambiguous HR requests across knowledge and the agent's HR actions. Use when one message mixes a policy or how-to question with the employee's own records, HR cases, catalog requests or Workday changes; has several asks ("check my request and explain the policy"); depends on an earlier result ("if I'm eligible, apply"); or has an unclear target ("change that request"). Single-intent requests go straight to the matching skill.
---

# HR request orchestration

## 1. Separate the intents
List each requested outcome, its target, and any order or condition. A question, a request to prepare a form and an instruction to submit are different intents; respect "don't submit yet".

| Intent                                        | Route                     |
| --------------------------------------------- | ------------------------- |
| Policy, process, benefits, how-to             | The agent's knowledge search |
| HR case list, detail, create or update        | hr-cases                  |
| Catalog items, requests and their status      | service-catalog           |
| The employee's own Workday data and changes   | workday-self-service      |
| Anything no skill or source covers            | Say so; continue the rest |

## 2. Clarify only what blocks the next step
Ask one question at a time. Run independent reads before asking about the unclear part.

## 3. Respect dependencies
Resolve a record before changing it. "If allowed, then apply" needs an authoritative answer first; a missing or unclear policy doesn't satisfy the condition.

## 4. Execute through the area skills
Follow each area skill's steps and confirmations. Show at most one widget per turn; say which form comes next and show it when the user replies. Never write twice because a form was opened.

## 5. Report every outcome
Mark each as done, waiting for the user, unsupported or failed. A failure stops only the steps that depend on it. Keep the policy answer, with its citations, separate from the user's records.
```

## What to notice

- The thin skill is mostly a routing table and boundaries; everything else is in the tools' descriptions. The thick skill names tables, fields, codes, defaults and the call order, because the tools don't know them.
- The orchestration skill names no tool steps at all: it routes to knowledge search and to the area skills, and owns only ordering, clarification, one widget per turn and reporting. Build it only when compound requests are common, and only after the area skills exist.
- Both descriptions say what the skill does, list how users ask, and draw the boundary with the neighbouring skill.
- Neither promises anything its tools can't do.
- Each fact the thick skill carries came from a source (the previous process's configuration, the instance's tables); write none from memory.
