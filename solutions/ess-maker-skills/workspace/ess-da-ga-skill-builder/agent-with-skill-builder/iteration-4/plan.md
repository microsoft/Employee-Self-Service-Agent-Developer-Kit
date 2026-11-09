# Plan: `agent-with-skill-builder` (`hr-case-create`, `catalog-order`)

Iteration: 4. Tools and knowledge from: `workspace/ess-da-ga-skill-builder-capabilities/` (inventory: `iteration-1/inventory.json`).

Knowledge sources: none provided (no `knowledge/knowledge.json`). Neither scenario asks policy or how-to questions, so none is needed. Existing skills: none (0 of 8 slots used).

Tools: 28 from 2 servers.

- **ServiceNow** (`servicenow-fcc`, plugin namespace `sngeneric`, 21 tools). FCC (on-demand fetch) tools that read or change any table once told where: `sn__list_records`, `sn__get_record`, `sn__create_record`, `sn__update_record`, `sn__delete_record`, `sn__get_record_schema`, `sn__get_table_stats`, `sn__upload_attachment_file`. Purpose-built service catalog lookups (`sn__get_catalogs`, `sn__get_catalog_categories`, `sn__get_catalog_items`, `sn__get_catalog_item`) and one catalog write, `sn__order_item` (order now, optional requested-for). Also `sn__get_current_user_info`, `sn__get_record_types`, ServiceNow knowledge-article search and attachment tools. The plugin marks all 21 functions `isNonConsequential`: Copilot runs them without asking (RT-11).
- **ServiceNow views** (`servicenow-custom-widgets`, plugin namespace `snux`, 7 tools). `ux__show_records` shows records in a list or detail view for `catalog_item`, `change_request`, `hr_case`, `incident`, `problem`, `request` and `requested_item`. `ux__show_form` shows a create or edit form, supported for `hr_case` and `incident` only; the form saves when the user submits it. Five app-only tools (save, add comment, people search, HR service search, HR COE list) are called by the views, never by the model.

## Scenarios

**Job stories:**

1. When an employee has an HR issue they want HR to act on (a payslip problem, benefits and enrollment, leave, an employment verification letter, relocation and so on), they want to open a new HR case so that HR handles it.
2. When a manager has an HR issue to raise for one of their direct reports, they want to open a new HR case for that direct report so that HR handles it.
3. When an employee needs equipment, software or a service, they want to see what they can order from the ServiceNow service catalog so that they can choose.
4. When an employee knows what they need (a laptop, a monitor, software), they want to find that item and order it for themselves or for someone else so that it's delivered without a portal visit.

**Example requests:**

1. "My payslip for March is missing my overtime, can HR fix it?"
2. "I need an employment verification letter for my mortgage application."
3. "Open an HR case for my direct report Priya about her relocation allowance."
4. "I need help from HR with my benefits enrollment."
5. "What can I order from the service catalog?"
6. "I need a new laptop."
7. "Order a 27-inch monitor for Sam Lee."
8. "Can I get Visio installed?"

**Acceptance criteria:**

- [ ] The HR case form opens prefilled with the summary and details from the user's message, for the user or for a direct report verified in ServiceNow.
- [ ] An HR case is created only when the user submits the form; the agent never creates or changes a case in chat.
- [ ] The agent doesn't open a case for someone who isn't the user's direct report.
- [ ] Browsing and searching show only catalog items the user can order through the agent.
- [ ] An order is placed only after the user confirms the item, quantity, who it's for and every answer; the reply gives the request number (REQ…).
- [ ] Record producers, order guides and items with questions that can't be answered in chat are never offered for ordering; the user is pointed to the service portal.
- [ ] Each change happens once; a write that returned a result is never repeated.

**Out of scope:** checking or changing existing HR cases and orders, approvals, IT incidents and catalog item design. Policy questions (no knowledge source is connected).

## Capability map

| Scenario | Step | Tool and key arguments | Fit | What the skill must carry |
| --- | --- | --- | --- | --- |
| 1, 2 HR case | Understand the issue | None (the model) | — | What to extract: summary, details, who it's for |
| 1 HR case (self) | Identify the user | `sn__get_current_user_info()` | Purpose-built | Use the returned `sys_id` as the case's person |
| 2 HR case (direct report) | Find the user's direct reports | `sn__get_record_schema(table="sys_user")`, then `sn__list_records(table="sys_user", query="<manager field>=javascript:gs.getUserID()")` | FCC | Table, how to find the manager field at run time, the query, how to match the person |
| 1, 2 HR case | Choose the HR service | The form's own HR service picker | Purpose-built | Nothing; don't prefill it |
| 1, 2 HR case | Collect input and confirm | `ux__show_form(entity="hr_case", mode="create", values={...})` | Purpose-built (form) | Prefill keys and values; the form is the confirmation |
| 1, 2 HR case | Create | The form saves when the user submits it | Purpose-built | Never create in chat; never repeat |
| 1, 2 HR case | Report | The form | Purpose-built | One-sentence reply; viewing cases is out of scope |
| 3 Browse | List catalogs and categories | `sn__get_catalogs()`, `sn__get_catalog_categories(catalog_id=…)` | Purpose-built | When to list them; they have no view, so list names in chat |
| 3, 4 Browse and find | List or search items | `sn__get_catalog_items(text=…, catalog=…, category=…)` | Purpose-built | Keep only orderable item kinds |
| 3, 4 Browse and find | Show items | `ux__show_records(entity="catalog_item", records=…)` | Purpose-built (view) | One view per turn; one-sentence reply |
| 4 Order | Read the item's questions | `sn__get_catalog_item(sys_id=…)` | Purpose-built | How to walk variables and which question types can't be filled from chat |
| 4 Order | Collect answers | Chat (`ux__show_form` doesn't support catalog items) | Partial | Ask mandatory questions; send names and choice values; script defaults; portal-only cases |
| 4 Order | Find the person it's for | `sn__get_record_schema(table="sys_user")`, `sn__list_records(table="sys_user", query=…)` | FCC | Table, field lookup at run time, query, matching |
| 4 Order | Confirm | Chat | — | One message with every value; wait for yes |
| 4 Order | Order | `sn__order_item(sys_id=…, body={sysparm_quantity, variables, sysparm_requested_for})` | Purpose-built | Body shape, when to send `sysparm_requested_for`, error handling |
| 4 Order | Verify and report | `sn__get_record(table="sc_request", sys_id=<request_id>)` | FCC | Table and id from the order response; reply with the REQ number |
| 4 Order | Submit record producers and order guides | None | None | Gap: point to the service portal |

## Scenario verdicts

| Scenario | Verdict | Weight | Calls for a routine request | Why |
| --- | --- | --- | --- | --- |
| HR case for self or a direct report | Achievable | Thin (one FCC lookup) | 2 (self); 3 (direct report) | The form finds HR services and saves the case; the skill adds who the case is for and the direct-report check. |
| Browse, find and order catalog items for self or others | Partly achievable | Thick | 2 (browse); 4 to 5 (order an item found by search, over two turns); +2 when ordering for someone else | Catalog lookups and ordering are purpose-built, but there's no order form, so the skill carries question handling, requested-for and confirmation. No tool submits record producers or order guides. |

**Gaps (business terms):** No connected tool can submit catalog record producers or order guides, or fill multi-row, attachment or custom questions from chat. Maker's choice: build what works now and leave those items out (Round 3). Later, mandatory reference questions to tables other than users and mandatory lookup select boxes were also sent to the portal (Round 5).

**Latency:** ordering an item for someone else takes up to 7 calls across two or three turns (search, show, item, schema, person, order, read back). A purpose-built order form for catalog items would cut this and replace the chat confirmation.

## Skill plan

Free skill slots: 8 of 8 before this plan; 6 after.

| Skill | Scenarios | Weight | Shared rules it uses | Status |
| --- | --- | --- | --- | --- |
| `hr-case-create` | HR case for self or a direct report | Thin | none | Ready (iteration 2; packaged) |
| `catalog-order` | Browse, find and order catalog items for self or others | Thick | none | Ready (iteration 4; packaged) |

No shared rules skill: the only mechanic both share is finding a person, and it differs (direct reports only for HR cases, anyone for orders). Each skill carries its own short lookup rather than depending on a second skill being read (RT-07).

Suggested lines for the agent's instructions (maker chose "Rarely" for mixed requests):

```text
To open a new HR case, use the hr-case-create skill. To browse, find or order from the service catalog, use the catalog-order skill. When one message asks for both, handle one at a time and show one form or view per turn.
```

**Left out:** record producers, order guides and items whose mandatory questions can't be answered in chat (portal only); everything listed as out of scope.

## Decisions

| Round | Question | Maker's answer | Effect on the skill |
| --- | --- | --- | --- |
| 1 | Tool source | Not asked: one source (the capabilities folder) | Inventory from `workspace/ess-da-ga-skill-builder-capabilities/` |
| 1 | Knowledge | Not asked: no policy or how-to scenarios | No knowledge steps |
| 2 | Who | Not asked: the brief says employees for themselves, managers for direct reports (HR cases), and anyone for catalog orders | HR: self or verified direct report; catalog: self or someone named |
| 2 | Changes | Not asked: the brief says both (show, then create or order) | Both skills write |
| 2 | Confirm scenarios | Yes, continue | — |
| 3 | Plan | 2 focused skills: `hr-case-create` and `catalog-order` | Two skills, no shared rules |
| 3 | Gap (catalog) | Build what works now | Record producers, order guides and portal-only questions are left out and never offered |
| 3 | Mixed requests | Rarely | Routing rule for the agent's instructions; no orchestration skill |
| 4 | Explicitness (`hr-case-create`) | Exact for changes, flexible for lookups | Exact form call; lookups with a default call |
| 4 | Details (`hr-case-create`) | In the skill's steps | No reference file |
| 5 | Sources (`hr-case-create`) | What the kit and agent have | Facts from ESS samples, the kit's references and tool descriptions |
| 5 | Missing facts (`hr-case-create`) | Look them up at run time | Read `sys_user`'s schema for the manager, name and email fields; prefill the form with the previous process's field names |
| 6 | Confirm (`hr-case-create`) | Not asked: the form is the confirmation | — |
| 6 | For others (`hr-case-create`) | Not asked: the brief says direct reports | Skill checks the reporting line |
| 6 | Defaults (`hr-case-create`) | Leave them unset | No assignment group or priority prefilled |
| 7 | Review (`hr-case-create`, iteration 2) | Looks good | — |
| 8 | Try it (`hr-case-create`) | Skip for now | `iteration-2/evals.json` written, not run |
| 4 | Explicitness (`catalog-order`) | Exact for changes, flexible for lookups | Exact order body; browse lookups as goals with a default call |
| 4 | Details (`catalog-order`) | In the skill's steps | No reference file; item kinds table in `SKILL.md` |
| 5 | Sources (`catalog-order`) | What the kit and agent have | Facts from `src/reference/servicenow-service-catalog.md`, the catalog sample and tool descriptions |
| 5 | Record questions (`catalog-order`) | Send these items to the portal | Mandatory `lookup_select_box` questions and references to tables other than `sys_user` stop the order |
| 5 | `sys_user` field names (`catalog-order`) | Not asked again: same run-time lookup as `hr-case-create` | Read `sys_user`'s schema for the name and email fields |
| 6 | Confirm (`catalog-order`) | Not asked: no form supports catalog items, so chat confirmation is the only option | One chat confirmation with every value |
| 6 | For others (`catalog-order`) | Not asked: the brief says anyone, and ServiceNow decides whether the user may order for that person | Requested-for allowed when the item has a Requested For question |
| 6 | Defaults (`catalog-order`) | Not asked: no previous ordering process; quantity 1 comes from the tool's own example | Quantity defaults to "1" |
| 7 | Review (`catalog-order`, iteration 4) | Looks good | — |
| 8 | Try it (`catalog-order`) | Skip for now | `iteration-4/evals.json` written, not run |

No question about skill limits came up, so nothing needs adding to `limitations.md`.

## Domain facts

| Fact | Source |
| --- | --- |
| HR cases are created in `sn_hr_core_case` with `short_description` (subject), `description`, `priority` and `opened_for`; `assignment_group` was a placeholder (`<YOUR_HR_ASSIGNMENT_GROUP_SYS_ID>`) the customer fills in | `src/examples/ess-samples/ServiceNow/HRSDScenarios/ServiceNowHRSDCreateCase/msdyn_HRServiceNowHRSDCreateCase.json`, `README.md` |
| `opened_for` held the person the case is for (the requesting user), and "my cases" are read by `opened_for` = current user | `ServiceNowHRSDCreateCase/topic.yaml`, `README.md`; `src/examples/ess-samples/ServiceNow/HRSDScenarios/ServiceNowHRSDGetUserCases/msdyn_HRServiceNowHRSDGetUserCases.json` |
| The previous process asked the user for a priority (High, Medium, Low) and confirmed with a card before creating | `ServiceNowHRSDCreateCase/topic.yaml` |
| The HR case form (`ux__show_form`, `entity="hr_case"`) prefills `values` and saves the case itself when the user submits; supported for `hr_case` and `incident` only | `servicenow-ux-mcp-tools.json` (`ux__show_form`) |
| The form has people, HR service and HR COE pickers that only the view calls | `servicenow-ux-mcp-tools.json` (`ux__search_people`, `ux__search_hr_services`, `ux__get_hr_coes`) |
| Encoded queries join conditions with `^`; `javascript:gs.getUserID()` is the signed-in user; `limit` max 100 | `servicenow-generic-mcp-tools.json` (`sn__list_records`) |
| `LIKE` is the operator the ESS samples use to match part of a name | `src/examples/ess-samples/ServiceNow/CatalogScenarios/ServiceNowCMDBLookup/msdyn_ITServiceNowCMDBLookup.json` |
| A table's fields, labels and references can be read at run time | `servicenow-generic-mcp-tools.json` (`sn__get_record_schema`) |
| `sys_user` is the user table (people are identified by their `sys_user` sys_id) | `src/reference/servicenow-service-catalog.md` (Ordering) |
| The `sys_user` fields for manager, name and email aren't in any kit source | None: looked up at run time (maker's choice) |
| `sn__get_current_user_info` returns the signed-in user's sys_id, user name, name and email | `servicenow-generic-mcp-tools.json` |
| All generic ServiceNow functions are `isNonConsequential` | `servicenow-generic-plugin.json` |
| Item kinds by `type` and `sys_class_name`; only `catalog_item` with `sc_cat_item`, `pc_hardware_cat_item` or `pc_software_cat_item` can be ordered with order now; record producers, order guides and composite producers need other calls; content items are links | `src/reference/servicenow-service-catalog.md` (Item kinds) |
| A tool that only calls order now can't submit record producers or order guides; give the portal instead | `src/reference/servicenow-service-catalog.md` (Item kinds) |
| `sn__order_item` body: `sysparm_quantity`, `variables` keyed by question name, optional `sysparm_requested_for` (a user sys_id) | `servicenow-generic-mcp-tools.json` (`sn__order_item`); `src/reference/servicenow-service-catalog.md` (Ordering) |
| `sysparm_requested_for` applies only when the item has a Requested For question; ServiceNow decides whether the user may order for that person | `src/reference/servicenow-service-catalog.md` (Ordering) |
| The order response is the request: `request_number`, `request_id` (the `sc_request` sys_id) (**Observed**) | `src/reference/servicenow-service-catalog.md` (Ordering) |
| `sn__get_catalog_item` returns `variables` with `name`, `label`, `friendly_type`, `mandatory`, `value`, and `choices`, `reference` or `children`; key answers by `name`; send a choice's `value`; map on `friendly_type`; walk `children` | `src/reference/servicenow-service-catalog.md` (Questions); `sn__get_catalog_item` description |
| A default such as `javascript:gs.getUserID();` is a script; send the user's sys_id, never the script text (**Observed**) | `src/reference/servicenow-service-catalog.md` (Questions) |
| UI policies and client scripts don't run; mandatory questions are enforced only at submit, with a `400` "Mandatory Variables are required" | `src/reference/servicenow-service-catalog.md` (Questions) |
| Multi-row variable sets, attachments (`mandatory_attachment`) and `macro` or `ui_page` questions can't be filled from chat; a `lookup_select_box` has no usable `choices` | `src/reference/servicenow-service-catalog.md` (Questions) |
| Browse and search with the Service Catalog API, which applies user criteria; the `sc_cat_item` table doesn't. `GET items/{sys_id}` returns `400` for an item the user isn't entitled to | `src/reference/servicenow-service-catalog.md` (Browsing) |
| Sources disagree: the ESS browse sample searched the `sc_cat_item` table (`active=true`, `short_description LIKE`). Resolved in favour of the catalog tools, which the agent has and which apply user criteria | `src/examples/ess-samples/ServiceNow/CatalogScenarios/ServiceNowBrowseCatalog/README.md` vs `src/reference/servicenow-service-catalog.md` |
| The service portal link is `<instance>/sp?id=sc_cat_item&sys_id=<sys_id>`, but no tool gives the agent the instance URL | `src/reference/servicenow-service-catalog.md` (Item kinds); tool descriptions |

## Must hold even if the skill isn't read

**`hr-case-create`**

1. In the HR case form (`ux__show_form` with `entity="hr_case"`, and the view's save action), accept as the case's person (`opened_for`) only the signed-in user or one of their direct reports. The form's person picker accepts anyone, and the model may skip the skill (RT-02).
2. Keep the form the only way to create an HR case: `sn__create_record` can write to any table and Copilot runs it without asking (`isNonConsequential`, RT-11). Block HR case tables in `sn__create_record`, or remove `isNonConsequential` so Copilot asks first.
3. List the `hr_case` form's prefill keys (`short_description`, `description`, `opened_for`) in `ux__show_form`'s description, so prefilling doesn't depend on the skill.

**`catalog-order`**

1. Remove `isNonConsequential` from `sn__order_item` so Copilot asks before every order; today the skill's chat confirmation is the only check (RT-11).
2. Have `sn__order_item` accept only orderable items (`type` `catalog_item` with `sys_class_name` `sc_cat_item`, `pc_hardware_cat_item` or `pc_software_cat_item`) and return a plain error for record producers, order guides, composite producers and content items.
3. Have `sn__order_item` replace script defaults such as `javascript:gs.getUserID();` with the signed-in user's sys_id, and never forward script text as an answer.
4. Block `sc_request` and `sc_req_item` in `sn__create_record`, so orders go only through `sn__order_item`.

## Validation

- `hr-case-create` (iteration 2 and `workspace/skills/hr-case-create`), `--expect create`: `1 skill(s): 0 error(s), 0 warning(s)`. One INFO: Copilot won't ask before `sn__create_record` or `sn__update_record` (non-consequential). The skill names them only to forbid them; must-hold rule 2 covers it.
- `catalog-order` (iteration 4 and `workspace/skills/catalog-order`), `--expect read,create`: `1 skill(s): 0 error(s), 0 warning(s)`. One INFO: Copilot won't ask before `sn__create_record` or `sn__order_item`. The skill confirms in chat before `sn__order_item` and names `sn__create_record` only to forbid it; must-hold rules 1 and 4 cover it.

## Iterations

| Iteration | Change requested | What changed |
| --- | --- | --- |
| 1 | First draft (`hr-case-create`) | — |
| 2 | Builder self-review (`hr-case-create`) | Handles "one of my directs" with no name (list and ask); reads the current user once per conversation; maker then chose "Looks good" |
| 3 | First draft (`catalog-order`) | — |
| 4 | Builder self-review (`catalog-order`) | Script defaults resolve to the user, or to the requested-for person only for the Requested For question; person search query spelled out (email exact, else name `LIKE`); confirmation shows labels and names; catalogs and categories listed by name; maker then chose "Looks good" |
