# ServiceNow knowledge evaluations: engineering implementation spec

**Status:** Engineering draft. This is not an approved API design and not a delivery promise.

**Based on the PM spec:** [Test employee knowledge answers with ADK, PR 5771115](https://dev.azure.com/O365Exchange/O365%20Core/_git/ideas-exp/pullrequest/5771115?_a=PlannerEngineering.easy-markdown-review.markdown-review-pr-tab&path=/specs/ess/adk-evals/spec.md), revision 13, PR iteration 23, commit `10f808c1c0d379a87bd9818235f4f155d83ae235`.

**Based on the code:** Local ADK checkout at `fbf9a28ef3d8ec784723f5e8f42d1f23bf1a0378`, checked on November 2, 2026. Unrelated authentication changes in that checkout are not part of this design.

**Updated November 19, 2026:** PM answers and the discussion with the Connect ServiceNow skill owner changed how knowledge evals start. The Connect skill sets up the KB and calls the eval skill. The eval skill reads the KB and writes the tests. Read section 2.1 first. Where it disagrees with older text, section 2.1 wins.

## 1. Purpose and labels

This document explains how engineering plans to build the first ServiceNow knowledge journey in the PM spec. If this document and the PM spec disagree, the PM spec wins.

Each item uses one of three labels:

- **Required:** The PM spec says we must do this.
- **Proposed:** Our engineering plan. It does not exist in the code yet.
- **Open:** We do not know this yet. It needs proof or a decision. Do not guess a value or act as if it already works.

The PM spec is marked `ready: false`. This document does not close any of its approval steps.

### Words used in this document

| Word | Meaning here |
| --- | --- |
| Maker | The person building and testing the agent in ADK. |
| Test case (or case) | One employee question plus the answer we expect the agent to give. |
| Evaluation set (or set) | A group of test cases saved together and run together. |
| KB | A ServiceNow knowledge base: a collection of articles. |
| Article | One published ServiceNow knowledge page. The original published article is the source of truth for policy. |
| Excerpt | The part of an article that answers the question being tested, including any conditions and exceptions. It is copied text, not a separate file. |
| Source reference | A link, article number, or other ID that points to where the excerpt came from. |
| Policy basis | The approved text the expected answer is based on. It must come from the article, not from the agent's own reply. "Independent" means independent of the agent's answer. It can still be inside the agent's KB. |
| Caller | A Connect skill (for example Connect ServiceNow) that sets up an integration on the agent, passes the source details (for ServiceNow KB: connection ID and KB sys_id), calls the eval skill, and gets a result back. |
| Eval skill | ADK's evaluation skill (`/evaluate`). Creates, reads, updates, and deletes evals, creates them in Copilot Studio, runs them, and returns results. For knowledge sources, it also reads the KB and writes the tests. |
| Connect skill | The ADK skill that sets up one integration (ServiceNow KB, SharePoint, Workday, ServiceNow ticketing, and so on). Owned by that integration's feature crew. |
| Handoff | The inputs a Connect skill passes to the eval skill (section 5.3). |
| Handback | The result the evaluation flow returns to the caller. |
| Graph connection ID | The ID of a Microsoft Graph connector connection, for example `ServiceNowKB2609040733`. Not a Power Platform connection ID, and not a KB ID. |
| KB sys_id | ServiceNow's ID for one knowledge base. One Graph connection can hold many KBs. |
| Provenance record | A saved note of where each expected answer came from and who confirmed it, and for which exact version of the test. |
| Fingerprint | A short code computed from a test's exact content. If the test changes, the code changes. Used to spot edits. |
| Reader / adapter | Code that reads an article automatically through a connection that already exists and is already allowed. Built in the eval skill. For ServiceNow KB it reads through Microsoft Graph (sections 6.1 and 7.5.1). |
| No-write check | Proof that the agent under test cannot change data in business systems (for example, cannot create tickets). |
| Native run | Running tests through Copilot Studio's built-in evaluation service. |
| Nonproduction | A test environment, not the one real employees use. |
| Duplicate start | Accidentally starting the same test run twice, for example after a timeout and retry. |
| OQ-*n*, FR-*n*, PR-*n* | Open question, functional requirement, and product requirement numbers from the PM spec. |

## 2. Scope and agreed direction

### 2.1 Direction update (November 19, 2026)

These decisions come from PM answers (Q1–Q3) and from the discussion with the Connect ServiceNow skill owner. They replace older text in this document where the two disagree.

| Topic | Decision |
| --- | --- |
| Who reads the KB and writes knowledge tests | **Decided.** The eval skill. It reads the KB through Microsoft Graph using the connection ID and KB sys_id from the handoff, pulls the excerpts, and writes the tests. The Connect skill does not write tests. This differs from the PM's Q1/Q3 answer that the Connect crew creates the test sets; align with PM (section 18). |
| What the eval skill is | Creates, reads, updates, and deletes evals for out-of-box topics (today's catalog-based evals), and writes knowledge tests from a KB named in the handoff. Creates them in Copilot Studio, runs them, and returns results. **PM decision:** no analysis. |
| How knowledge evals start | The Connect skill sets up the integration, then calls the eval skill with the source details (section 5.3). The eval skill reads the KB, writes the tests, saves, creates, and runs them, then hands back. The Connect skill continues its own steps. |
| KB must be set up first | **PM decision.** Yes. There are no knowledge tests without a connected knowledge source. Catalog-based evals keep working as today. |
| No ServiceNow KB | Hard stop. If the handoff has no KB (no `connectionId` or `kbSysId`), the eval skill stops and says so. It does not create or run knowledge tests. The eval skill trusts the Connect skill that a KB it names is set up on the agent; it does not check again. |
| "Evaluate my agent" | **PM decision.** Runs the existing evals. Does not create new ones. |
| Badly written knowledge tests | If knowledge tests fail because the tests themselves are poor, the eval skill re-reads the KB and rewrites them with the maker, then runs again. (The PM answer had the Connect skill regenerate them; updated because the eval skill now writes them.) |
| v1 experience | **PM decision.** Build the intended experience around the Connect skill. Knowledge evals become available when the Connect skill ships. The paste-excerpt path stays as it is (section 7). |
| Generic handoff | The eval skill is generic and driven by inputs. It does not read the Connect skill's internal files (for example its setup-state JSON). The eval skill team defines the handoff format (section 5.3). The same handoff serves every Connect skill (section 5.4). |
| Setup does not block saving | Saving tests does not wait for the integration setup to finish. Setup is checked when tests run, and problems are flagged then. |
| One KB per agent | Expect one ServiceNow KB source per agent for now. More than one is open (section 18). |
| Graph connector setup | Out of scope. An admin creates the tenant-wide Graph connector in the Microsoft 365 admin center. The Connect skill lists the connections, the maker picks one, and the Connect skill links it to the agent. |

**What this changes in this document:**

| Section | Change |
| --- | --- |
| 2 (scope) | Updated below. |
| 3, 4 | Owner column added. The Connect skill picks the source; the eval skill reads it and writes tests. |
| 5.2–5.4 | The Connect skill is now the main way knowledge evals start. New handoff format. New section on supporting any Connect skill. |
| 6 | The Connect skill picks the connection and KB. The eval skill checks them. Verified Graph findings added (section 6.1). |
| 7, 8 | Stay with the eval skill. Verified Graph reading added (section 7.5.1). The paste-excerpt path is unchanged. |
| 12.2 | There is a caller now. |
| 15, 16 | Example and story split updated. Stories need re-planning. |
| 18 | New open questions for the handoff. |

```mermaid
flowchart TD
    Admin["Admin creates the Graph connector<br/>(Microsoft 365 admin center, outside ADK)"]
    Pick["Connect skill lists connections;<br/>maker picks one; Connect skill links it to the agent"]
    Call["Connect skill calls the eval skill<br/>with connection ID + KB sys_id (section 5.3)"]
    Check{"Does the handoff name<br/>a knowledge source?"}
    Stop["Hard stop: say no KB is set up"]
    Read["Eval skill reads the KB through Graph<br/>and pulls excerpts (sections 6.1, 7)"]
    Write["Eval skill writes tests;<br/>maker confirms (section 8)"]
    Save["Eval skill saves the set,<br/>creates it in Copilot Studio"]
    Run["Eval skill runs it after maker permission<br/>(setup checked here)"]
    Back["Eval skill returns one outcome (section 12.2);<br/>Connect skill continues its steps"]
    Bad{"Did tests fail because<br/>the tests are poor?"}

    Admin --> Pick --> Call --> Check
    Check -->|No| Stop
    Check -->|Yes| Read --> Write --> Save --> Run --> Back --> Bad
    Bad -->|Yes| Read
```

### In scope

- Extend the existing evaluation skills and their Python helper scripts.
- Keep the current ways to start: plain-language requests and `/evaluate`. Add no new command. "Evaluate my agent" runs the existing evals and does not create new ones.
- Create, read, update, and delete evals for out-of-box topics, create them in Copilot Studio, run them, and return results.
- Accept a call from any Connect skill through one generic handoff (sections 5.2–5.4).
- For a ServiceNow KB in the handoff: read the KB through Microsoft Graph using the connection ID and KB sys_id, pull excerpts, write formal and everyday tests, and get maker confirmation.
- Keep the paste-excerpt path when automatic reading is not available.
- Hard stop when the handoff names no knowledge source. (The Connect skill is trusted that a named source is set up on the agent.)
- Save where each expected answer came from (provenance).
- Keep "is this a good test?" separate from "did the agent pass?"
- Run tests through the existing Copilot Studio evaluation path.
- Read real agent replies, and rerun the same tests after someone fixes the agent elsewhere.
- Keep current access rules, data rules, recovery behavior, and existing features working.

### Out of scope

- Setting up the integration on the agent. The Connect skill owns this.
- Analysis or analytics of results, automatic diagnosis, or repair.
- Building or turning on connector setup, including creating the Graph connector in the Microsoft 365 admin center.
- A feature on/off switch. PM decision: ship to everyone.
- Watching for changes made outside ADK, scheduled scans, Planner triggers, or push notifications.
- Scanning every KB or listing every untested integration.
- Multi-turn conversations, per-turn control, or business tasks (like creating tickets).
- Citation grading, advanced matching across copies, or release gates.
- A new reviewer role, notification service, or shared store of prompts and replies.
- New permissions, or reusing the connector's crawler or admin accounts.

### Decisions made in our discussion

Earlier decisions. Section 2.1 replaces any that disagree with it.

| Topic | Decision |
| --- | --- |
| Source of truth | The approved policy in the original published ServiceNow article. That article can be in the agent's own KB. A separate policy store is not needed. |
| Automatic reading | Only through a connection that already exists, is already allowed, and has been tested. Otherwise, ask the maker to paste an approved excerpt and its source reference. |
| Confirmation | Show every generated test in full. Offer both "confirm all shown" and "review one by one". Editing a test means confirming only that test again, not the whole set. No limit on how many tests "confirm all shown" covers; revisit if design review or testing shows one is needed. PM approved the behavior. UX goes to design review; who signs off is still to be confirmed. |
| Where tests are saved | In a matching evaluation set the maker picks, or in a new set tied to the selected agent. Save the source and confirmation details next to the tests. |
| What we save locally | Save the smallest relevant excerpt text, its source link, and a fingerprint in `provenance.json`. Never save passwords or real employee data. Needs privacy/compliance approval (OQ-9/OQ-10), including how long to keep it. |
| Quality scoring | Keep today's behavior: send only questions and expected answers to the GitHub Copilot API. Do not send the excerpt. Manual scoring stays available. Needs privacy/compliance approval (OQ-9). |
| Trigger from ServiceNow | **Replaced by section 2.1.** Earlier PM decision was no ServiceNow offer in the first release. Now: the Connect skill calls the eval skill after setting up the KB. |
| Rollout | PM decision: ship to everyone, with no on/off switch. All tenants and environments get it, because only declarative-agent (DA) customers use this and they are already filtered. Problems are handled by shipping a fix or reverting the change (section 14). |

These PM decisions differ from PM spec revision 13 (FR-44 requires the ServiceNow offer; OQ-7 asks for on/off controls). The PM spec should be updated to match.

### Flow at a glance

This diagram shows how the eval skill gets the approved policy text for the chosen KB and employee question.

```mermaid
flowchart TD
    Supplied{"Is approved policy text<br/>already supplied?"}
    Reader{"Is there a tested connection<br/>we are already allowed to use?"}
    Retrieve["Read the selected article"]
    Ask["Ask the maker to paste an approved excerpt<br/>and its source reference"]
    Validate["Check the source reference<br/>and that the text fits the question"]
    Sufficient{"Is the text enough to know<br/>the correct answer?"}
    Propose["Draft expected answers<br/>for the maker to confirm"]
    Missing["Say what is missing<br/>Leave expected answers undecided"]

    Supplied -->|Yes| Validate
    Supplied -->|No| Reader
    Reader -->|Yes| Retrieve
    Reader -->|No or not sure| Ask
    Retrieve -->|Text read| Validate
    Retrieve -->|Denied, failed, or partial| Ask
    Ask -->|Allowed text and reference given| Validate
    Ask -->|Cannot share allowed text| Missing
    Validate --> Sufficient
    Sufficient -->|Yes| Propose
    Sufficient -->|No or not sure| Missing
```

Notes on the diagram:

- Checking a reference uses only what we can see. It does not mean ADK can open the original article.
- If access is denied, we report it as denied. Pasting text is not a way around a denial. The maker may only paste text they are already allowed to use here.
- Missing reference, unclear fit, conflicting rules, or incomplete text means the expected answer stays undecided.

Section 7 explains this flow step by step. Sections 8-13 cover writing tests, maker confirmation, saving, quality checks, running safely (with separate permission), results, and reruns. All of these are eval skill work.

## 3. What exists today and what needs work

Paths are from the repository root. In the table, `scripts\...` and `src\...` are under `solutions\ess-maker-skills`.

| Area | What the code does today | What we will do |
| --- | --- | --- |
| Routing requests | `solutions\ess-maker-skills\src\skills\evaluations\dispatcher\SKILL.md` routes based on configured topics. | Add a route for the ServiceNow knowledge question. A matching topic must not be required to decide what the policy says. |
| Writing tests | Existing create/generate skills write native evaluation files. The catalogue generator uses built-in sample scenarios. | Reuse file handling. Add policy-based writing. Built-in sample content is not the customer's policy. |
| Adding one case | `scripts\evaluation_authoring.py` adds a case, checks the grading method, and updates the CSV. | Also keep each case's source and confirmation links. |
| Preview and allowed methods | `evaluation_presentation.py`, `evaluation_csv.py`, `evaluation_method_policy.py`. | Reuse exact set selection, full previews, strict export, and method checks. |
| Deployment | `evaluation_deployment.py` and `evaluation_promotion.py` prepare and promote sets. | Carry the new local records along. Do not invent an "update in place" API that Copilot Studio does not have. |
| Run and results | `evaluation_runs.py` and `minimalbot_evaluation.py` start runs and read history and results. | Reuse them. Verify reply details, run links, safety checks, and whether retrying a start is safe. |
| Review status | `review.json` stores review status and a base description. Deployment does not send it to Copilot Studio. | Do not treat it as policy approval or test confirmation. Add a separate provenance record. |
| Finding knowledge sources | FlightCheck reads local knowledge files and can list Copilot Studio bot components. | Reuse only after we prove it works for the selected declarative agent. |
| ServiceNow entry | `src\skills\connect\servicenow\integration.json` is marked `unavailable`. | The Connect ServiceNow skill is being built by its feature crew. When it ships, it calls the eval skill with the connection ID and KB sys_id (section 5.3). The eval skill then reads the KB and writes the tests (section 2.1). |
| ServiceNow MCP | Uses a shared username and password (Basic auth) and generic Table API read/write calls. | Not proven to read articles as the maker. Do not give this flow its broad read/write tools. |

## 4. Components

**Proposed:** Skills handle the conversation. Python scripts handle data and state, so the behavior is reliable.

**Owner** shows who builds each part after section 2.1.

| Component | Owner | Job |
| --- | --- | --- |
| Shared entry | Eval skill | Turns direct requests and Connect skill handoffs into one request format. Asks for anything missing. Keeps "save tests" and "run tests" as separate permissions. |
| Handoff checker | Eval skill | Checks the handoff is complete (section 5.3). Hard stop if no knowledge source is named. Trusts the Connect skill that the source is on the agent. |
| Knowledge source picker | Connect skill | Lists connections and KBs, lets the maker pick, links the source to the agent, and passes `connectionId` + `kbSysId` in the handoff. |
| Policy input handler | Eval skill | Uses supplied text, calls an allowed reader, or asks for an excerpt. |
| Conditional reader | Eval skill | Reads only the selected KB through Microsoft Graph (Search and Retrieval API, section 7.5.1) using the handoff's IDs. Has no tools that change data. |
| Test writer (knowledge tests) | Eval skill | Writes questions, expected answers, a short reason for each test, and links to the source. |
| Test writer (out-of-box topics) | Eval skill | Today's catalog-based test writing. Unchanged. |
| Provenance helper | Eval skill | Saves where each expected answer came from and ties confirmations and quality results to the exact test content. |
| Existing deploy/run helpers | Eval skill | Check and prepare the chosen set, start one run after permission, and fetch real results. |
| Result summarizer | Eval skill | Accounts for every requested case and returns one of the PM spec's outcome labels. |

This new path must not change how ordinary custom agents work today, and must not quietly redirect requests it does not support.

### Planned code changes

| Location under `solutions\ess-maker-skills` | Change |
| --- | --- |
| `.github\prompts\evaluate.prompt.md` and the evaluation dispatcher | Keep the same command. Add a way to pass in context. No second command. |
| Evaluation create/generate/update skills | Add a policy-based writing branch that starts from the handoff's KB. Also accept a ready-made test set if one is passed. Leave normal topic and catalogue behavior unchanged. |
| One shared helper under `scripts` | Put the handoff into one format, check it, compute fingerprints, and check confirmations. The file name is our choice, not a PM requirement. |
| Conditional reader (new script under `scripts`) | Reads the KB through Microsoft Graph using `connectionId` + `kbSysId`, reusing FlightCheck's Graph sign-in (`flightcheck\graph_client.py`, `checks\graph_connector_kb.py`). Sections 6.1 and 7.5.1. |
| `evaluation_authoring.py` and related save/import code | Save cases with their source links. Clear confirmation when a case is edited. |
| `evaluation_presentation.py` / `evaluation_csv.py` | Keep the preview matching the YAML. Show source and purpose, but do not quietly add policy text to exports. |
| `evaluation_review.py` and local metadata | Keep existing review status separate from maker confirmation. |
| `evaluation_promotion.py` / `evaluation_deployment.py` | Include the provenance record in local copy, compare, and permission checks. Do not send it to Copilot Studio, which does not accept it. |
| `evaluation_runs.py` / `minimalbot_evaluation.py` | Add safety checks, count every requested case, report incomplete runs clearly, and prevent duplicate starts. |
| Connect skills (callers) | Each Connect skill calls the eval skill through the handoff (section 5.3) after setting up its integration, passing the source IDs, and reads the result. The eval skill does not read Connect skill internal files. |

## 5. How evaluations start

### 5.1 Direct start

1. Recognize a plain-language evaluation request or `/evaluate`.
2. Find the currently selected agent using existing configuration helpers, when available.
3. If the agent or source is unclear, ask the maker to pick. Never use another agent's settings.
4. If it is unclear whether to write new tests or run existing ones, ask.
5. Writing tests locally can go ahead without run setup, where the current flow already allows that. Missing run setup blocks only deploying and running. It must not delete local work.
6. **PM decision:** "Evaluate my agent" runs the existing evals. It does not create new ones.
7. A direct request for knowledge tests ("test my ServiceNow PTO policy") is allowed when the agent already has the KB set up. The eval skill finds the connection and KB on the agent (section 6), or asks the maker, then follows the same path as section 5.2 steps 5–10. If no KB is set up, point the maker to the Connect skill.

### 5.2 Start from a Connect skill (the caller)

**PM decision (replaces the earlier deferral):** The Connect skill is the main way knowledge evals start.

1. An admin creates the tenant-wide Graph connector in the Microsoft 365 admin center. This is outside ADK.
2. The Connect skill lists the connections and the KBs in the chosen one. The maker picks a connection and a KB, and the Connect skill links it to the agent.
3. The Connect skill calls the eval skill with the handoff (section 5.3), including `connectionId` and `kbSysId`.
4. The eval skill checks the handoff is complete. If no knowledge source is named, it stops (hard stop). It trusts the Connect skill that the named source is set up on the agent.
5. The eval skill reads the KB through Microsoft Graph using those IDs (sections 6.1 and 7.5.1). If reading is not available, it asks the maker to paste an approved excerpt (section 7.7).
6. The eval skill writes formal and everyday tests and gets maker confirmation (section 8).
7. The eval skill saves the set and creates it in Copilot Studio. Saving does not wait for setup to finish.
8. With the maker's permission, the eval skill runs the set. Setup is checked here, and problems are flagged.
9. The eval skill shows the results to the maker in the Copilot chat, then returns one outcome (section 12.2). The Connect skill continues its own steps.
10. If knowledge tests fail because the tests are poor, the eval skill re-reads the KB and rewrites them with the maker, then runs again.

Rules:

- The eval skill uses only the handoff. It does not read the Connect skill's internal files.
- If the maker says no, return `skipped` and do not block the Connect skill's setup work.
- Expect one ServiceNow KB source per agent for now.

### 5.3 Handoff format (proposed)

The eval skill team defines this format. These are internal field ideas, not claims about any existing service format. The Connect skill owners must agree to it (section 18).

| Field | Required | Meaning |
| --- | --- | --- |
| `requestId` | Yes | Local ID to tie messages together. Not a run ID, and not protection against duplicate starts. |
| `caller` | Yes | Which skill is calling, for example `connect-servicenow`. `direct` for `/evaluate`. |
| `intent` | Yes | `save`, `save-and-run`, or `run`. Saving and running still need separate maker permission. |
| `target` | Yes | Tenant ID, environment ID, agent ID, and run mode. Each must be checked before running. |
| `sourceType` | Yes for knowledge tests | `servicenow-kb`, `sharepoint`, `workday`, `servicenow-ticketing`, and so on (section 5.4). |
| `sourceRef` | Yes for knowledge tests | What identifies the source. Depends on `sourceType` (table below). |
| `testSet` | Optional | Ready-made cases, if the Connect skill has any. Normally empty: the eval skill writes the tests from `sourceRef`. Uses the existing EvaluationSet/EvaluationData format. |
| `provenance` | Optional | Source details that come with a ready-made `testSet`. Saved as given (section 9). |
| `selectedSet` | Optional | An existing set to update or run: its folder and deployed ID if known. Never look it up by display name only. |
| `changeContext` | Optional | What the caller knows changed, marked "reported" or "checked". Empty means unknown, not "nothing changed". |
| `makerChoices` | Yes | Separate records of permission to save and permission to run. Earlier permission does not cover a changed action. |

`sourceRef` for each source type:

| `sourceType` | `sourceRef` fields |
| --- | --- |
| `servicenow-kb` | `connectionId` (Graph connection ID, required), `kbSysId` (the KB's ServiceNow ID; required when the connection holds more than one KB), `kbName` (display only). |
| `sharepoint` | Site and library (or folder) the agent uses. To be agreed with that crew. |
| `workday` | The connection and the operations it exposes. To be agreed with that crew. |
| `servicenow-ticketing` | The connection and the operations it exposes. To be agreed with that crew. |

Unknown values stay empty with a reason. Never fill them with guesses, similar-looking names, or the agent's reply. Never pass passwords or keys.

### 5.4 Works for any Connect skill

The eval skill does not know anything about ServiceNow. ServiceNow KB is the first source that uses the handoff.

- **Same for every source (eval skill):** check the handoff, write tests from excerpts, confirm with the maker, save the set, create it in Copilot Studio, run it, return the outcome, keep provenance, rerun and compare.
- **Different per source (Connect skill):** setting up the source, letting the maker pick it, and passing its IDs.
- **Small per-source adapter in the eval skill:** confirm the agent has the named source, and read its content. Adding a new knowledge source means adding a `sourceType` and its adapter. It does not change the rest of the eval skill.

There are two kinds of sources:

| Kind | Sources | What a test checks | Where the tests come from |
| --- | --- | --- | --- |
| Knowledge | ServiceNow KB, SharePoint | Does the agent answer correctly from the content? | The eval skill, from article or document text read through the source adapter. |
| Action | Workday, ServiceNow ticketing | Does the right topic or action run, with the right inputs? | Today's catalog-based evals for out-of-box topics. To be agreed with those crews. |

SharePoint can likely reuse the reading approach in section 7.5. The Copilot Retrieval API documents SharePoint and OneDrive as well as Graph connectors. We have only tested Graph connectors.

## 6. Find the selected knowledge source

**Owner after section 2.1:** The Connect skill lets the maker pick the connection and KB, and passes `connectionId` + `kbSysId` in the handoff. The eval skill trusts that the source is on the agent. For a direct request with no handoff, the eval skill uses the order below.

**Proposed order:**

1. Use context from the caller, if given. Check it against the selected agent where we can.
2. Look at the selected agent's local knowledge files.
3. Use live lookup in Copilot Studio where it is proven to work for that agent.
4. Show the possible sources with their type, reference, and how they were found.
5. Let the maker pick. If lookup is not supported, ask for a source reference. Do not say "no sources found".

Finding only one source makes confirming easier. It does not prove we have the right article or policy.

Things to keep in mind:

- A local file shows local settings. It does not prove the source is published or currently indexed.
- A connector reference may point to an environment variable that must be looked up.
- A display name can change, so it is not a reliable ID.
- A Microsoft Graph connection ID is not a ServiceNow KB ID.
- One connection can cover several KBs, or only part of one.
- Finding a source does not mean we are allowed to read its articles.
- Source settings do not tell us the employee question area or what changed.

**Open:** Prove this lookup works on the selected declarative agent. FlightCheck's current lookup is a good starting point, not a guarantee.

### 6.1 Verified: finding the KB from a Graph connection ID (November 2026)

We tested Microsoft Graph in a test tenant, signed in as a maker, through FlightCheck's existing Graph app. Results:

- `GET /v1.0/external/connections` lists the Graph connections. In the test tenant there were 17 ServiceNow KB connections (one still a draft). The connection ID looks like `ServiceNowKB2609040733`.
- **One connection can hold many KBs.** One connection had 293 articles across 17 KBs. So the connection ID alone is not enough to pick the KB. The maker must also pick a KB.
- Each article has `KbKnowledgeBaseUrl`, ending in the KB's ServiceNow ID (`…/kb_knowledge_base/<KB sys_id>`), and `KbKnowledgeBase`, the KB name.
  - Use the **KB sys_id** as the stable ID. Show the name to the maker only.
  - Use the article `Number` and `SysId` for each test's provenance.
  - `Topic` and `KbCategory` were mostly empty, so they are not reliable for narrowing.
- To list the KBs under a connection: search the connection (`POST /v1.0/search/query` with `contentSources` set to `/external/connections/{connectionId}`) and group the results by `KbKnowledgeBaseUrl`. Aggregations returned nothing (the fields are not refinable), so grouping must be done in code.
- To narrow to one KB: KQL in the search query works, for example `KbKnowledgeBaseUrl:"…/<KB sys_id>"` or `KbKnowledgeBase:"<name>"`.
- Results include only what the signed-in maker can see. 9 of the 17 connections returned no results. We could not tell whether those were empty or blocked (the connection operations call returned an error). Treat "no results" as "cannot see", never as "no articles". Tell the maker what came back (no articles were returned) without claiming the KB is empty; retry only when the call itself failed.
- A wrong connection ID returns a 400 error.
- No ServiceNow sign-in is needed.
- Permissions: delegated `ExternalConnection.Read.All` and `ExternalItem.Read.All`, with admin consent. FlightCheck's Graph app already had both in the test tenant. **Decided:** the eval skill only reads; it does not check permissions or consent first. If a call is refused, it reports the error to the maker.

**Resulting flow:** the Connect skill lists connections, the maker picks one, the Connect skill lists the KBs under it, the maker picks one, and the Connect skill passes `connectionId` + `kbSysId` in the handoff. The eval skill then narrows its search to that KB and reads the articles.

## 7. Getting the excerpt: full flow

**Owner after section 2.1:** The eval skill. For ServiceNow KB, it reads through Microsoft Graph using the `connectionId` and `kbSysId` from the handoff (sections 6.1 and 7.5.1). The paste-excerpt path (section 7.7) is unchanged.

An excerpt is the part of an approved article that answers the question, including the conditions and exceptions needed to understand it.

### 7.1 Start with the question to test

First confirm the source and the employee question area.

Example: "ServiceNow IT knowledge; can employees use personal USB drives?"

If a KB is chosen but no question area is given, ask what to test. Do not summarize the whole KB or make a default list.

### 7.2 Check text that was already supplied

If the caller or maker already gave text:

1. Check that both the text and its source reference are present.
2. Check that the text is approved and has no sensitive data (or has been cleaned), so it is safe to process here.
3. Note that it was supplied in this conversation. Do not collect extra personal details about who supplied it.
4. Check that it answers the chosen question and includes the relevant conditions.
5. Keep track of any gaps. Do not label it as "read automatically" or "independently verified".

A title, URL, KB ID, article number, or the agent's reply is not policy text on its own.

If the supplied text is enough, go to review (7.8). There is no need to fetch the article just to replace good supplied text.

### 7.3 Check if automatic reading is allowed

If good text was not supplied, all of these must be true:

| Check | What we need to see |
| --- | --- |
| A reader exists | Code built and supported for this agent and source. Not just any tool the AI model happens to have. |
| The right person is reading | The read happens as the maker (with their normal access), not as a crawler or admin account. |
| The app is allowed | The ADK app already has approved read access. Being able to open the article in a browser is not enough. |
| We know which article | The source and article are known, or can be picked through a tested lookup. |
| Data use is allowed | The text may be used for writing tests, quality scoring, local files, and running tests. |

If any check is false or unknown, skip automatic reading and say why. Do not try higher permissions or ask for admin passwords to find out.

### 7.4 Find the article if only the KB and question are known

Use only a tested lookup that searches inside the chosen source.

1. Search the chosen source for the employee question.
2. Show matching titles/references and any details about who or where they apply to.
3. If it is unclear which one is right, ask the maker to choose.
4. Read the chosen article with the allowed reader.

If this lookup is not available, ask the maker for the article reference and excerpt. Do not search the whole tenant, and do not guess IDs to fetch.

Search snippets help find candidates. They do not show the full rule.

### 7.5 Read the selected original article

**Conditional plan:** Build only the reader that the real setup supports. Do not build several readers before the first release.

| Option | What the public docs show | What we still need to prove |
| --- | --- | --- |
| ServiceNow Knowledge API | `GET /api/sn_km_api/knowledge/articles` and article detail calls such as `GET /api/sn_km_api/knowledge/articles/{id}`. Needs the `sn_km_api` plugin. | The customer's instance has the plugin; an approved sign-in as the maker; access rules are applied; the full relevant text is returned; the calls have no unwanted side effects. |
| Microsoft Graph search | `POST /v1.0/search/query` can search connector `externalItem` content within one connection. | Which connection maps to which KB; existing app and maker permissions; which fields are returned; limits of indexed text. Good for finding articles, not proof of the full original policy. |
| Graph external-item GET | `GET /v1.0/external/connections/{connectionId}/items/{itemId}`. | Valid item IDs; access behavior for this connector; existing permissions; whether the text returned is enough. Do not assume search result IDs are item IDs. |
| Copilot Retrieval API | `POST /v1.0/copilot/retrieval` with `dataSource: externalItem` and the connection ID. Also documents SharePoint and OneDrive. | **Tested (section 7.5.1).** Still to prove: the license requirement and full-article coverage. |

The earlier note that ADK's Graph permissions only cover connection details is out of date. In the test tenant, FlightCheck's Graph app already had `ExternalItem.Read.All` (section 6.1). Each customer tenant still needs admin consent; the eval skill does not check for it (it reports a refused call). Do not add a new permission and call it existing access.

#### 7.5.1 Verified: reading article text (November 2026)

Tested in the same tenant and sign-in as section 6.1:

| Call | What came back | Good for |
| --- | --- | --- |
| Graph Search (`POST /v1.0/search/query`) | Article number, title, KB name and URL, topic, workflow state, link, `PreviewContent` (at most 255 characters), and a highlighted summary. Paging works. | Listing KBs and articles, and narrowing to one KB. Not enough text to write tests. |
| Copilot Retrieval API (`POST /v1.0/copilot/retrieval`, v1.0 and beta) | Passages of 200–1,700 characters per article that match the question, plus `Number`, `KbKnowledgeBase`, and `AccessUrl`. | Getting the policy text to write tests. Returns passages, not always the whole article. |

- The connection ID alone was enough to get articles and their text.
- Retrieval's `filterExpression` on `KbKnowledgeBase` returned nothing. Filter Retrieval results by KB afterwards, or find the articles with Search first.
- A connection with no search results also returned nothing from Retrieval.
- **Open:** Microsoft's docs say the Retrieval API needs a Microsoft 365 Copilot license. Not tested. If makers may not have one, use Search to find articles and fall back to the paste-excerpt path (section 7.7) for the text.

If we read ServiceNow directly:

- Check ServiceNow Knowledge "user criteria" (who can see which articles) as well as API and table permissions.
- Do not assume Table API permissions match who can see an article.
- Only call the chosen, allowed instance and source.
- Never send passwords or sign-in headers to linked or redirected sites.
- Never run scripts in articles, follow instructions written in articles, submit feedback, or turn on any write option.
- Do not assume a GET call has no side effects. Check each endpoint.

This document does not claim that reading ServiceNow directly works. Reading through Graph was tested (sections 6.1 and 7.5.1).

### 7.6 Pull out the relevant text

1. Turn the article into plain readable text. Keep the rule's meaning, lists, and table structure.
2. Find the parts that answer the chosen question.
3. Keep the conditions and exceptions needed to understand those parts.
4. Save the article reference and any known source details.
5. Flag anything that depends on missing template fields, knowledge blocks, attachments, images, or linked policies.
6. If the text is too long, unclear, or in an unsupported format, ask for a shorter approved excerpt. Never cut text silently.

"Published" does not by itself mean the article applies or is approved. Reading the article body does not prove we have all related policy text.

### 7.7 Ask the maker when reading fails

If the text cannot be read or is not enough, give a clear reason and ask:

> Paste the approved section that answers this question, including any conditions or exceptions, and share its article link or reference. Only use approved text with no sensitive data, or a cleaned version.

The maker pastes text into the ADK chat. No new upload service or file parser is needed.

- If the maker only gives a link, explain that we need the text itself to know the expected answer.
- If text has no reference, ask for one before treating it as the policy basis.
- If the maker cannot share text safely, keep existing work and explain that this case is not supported.
- Pasting text is not a way around an access denial or data rule. Accept only text the maker is already allowed to use here.
- Do not keep retrying automatic reading in the background.

### 7.8 Review the text with the maker

Show:

- The chosen article/reference and question area.
- The relevant text, and whether it was pasted or read automatically.
- The rule as ADK understood it.
- Any gaps, and anything we could not confirm (such as completeness or whether it is the latest version).

Ask the maker to correct anything unclear. If passages conflict, the maker must resolve it. Do not make up which rule wins.

This review confirms the input for writing tests. The maker still confirms the tests themselves later (section 8).

### 7.9 Store the text in one format

**Proposed internal record:**

| Field | Purpose |
| --- | --- |
| `evidenceId` | Local ID that tests point to. Not an approval mark. |
| `sourceReference` | Link or reference to the original article. |
| `sourceIdentity` | Known source, KB, article, and language IDs that were checked. Unknown fields stay unknown. |
| `acquisition` | How we got it: supplied by caller, pasted by maker, or read automatically through a tested reader. |
| `approvedText` | The smallest relevant text allowed here, including needed conditions. |
| `sourceVersion` / `modifiedAt` | Only values the source itself provides. |
| `obtainedAt` | When ADK got the text. Does not prove the source was up to date. |
| `textDigest` | A fingerprint of the text, used to spot changes. Does not prove the text is approved, complete, or current. |
| `limitations` | Missing parts, unchecked details, or other limits. |
| `accessState` | Accessible, not accessible, does not exist, or unknown, with the reason we know. |

Which fields we keep long term, and how much text we may store, depends on OQ-9/OQ-10. Never store passwords, access tokens, raw customer records, or large copies of the source.

### 7.10 What happens in each situation

| Situation | What we do |
| --- | --- |
| Supplied text is approved and enough | Draft and confirm tests. Record how the text was obtained. |
| Automatic reading works and text is enough | Show the extracted rule and draft tests. |
| No reader, or permissions are unknown | Say automatic reading is not available. Ask for an approved excerpt. |
| Access denied | Report the denial. Do not say the article does not exist, and do not switch accounts. Offer pasting only within the maker's existing access. |
| Search finds nothing | Say no results came back. That does not prove the article does not exist. |
| Timeout, too many requests, or service error | Say reading failed or the result is unknown. Offer an allowed retry or pasting. Never guess the policy. |
| Text is partial or conflicting | Say what is missing or unclear and ask the maker to resolve it. |
| No good approved text at all | Do not mark any expected answer as accepted or ready to run. Keep work that can be recovered, and point to the existing review route for the right subject expert. |

## 8. Write and confirm each test

**Required:** Write tests only for the chosen question area and the confirmed policy text.

1. Find existing sets that fit and ask which exact set to use.
2. Add to that set, or suggest a new set for this integration if none fits.
3. Write the question two ways (formal and everyday wording), both testing the same rule.
4. Write a short, checkable expected answer. Do not copy the maker's instructions into it.
5. For each test, explain its purpose, which policy text it is based on, and whether it is a normal case, an edge case, or an out-of-scope case.
6. Out-of-scope expected answers must match what the agent can really do. Do not invent routing or policy.
7. Show every affected test and allow confirm, edit, or remove.
8. The maker confirms each affected test. After showing all tests in full, offer two choices: "confirm all shown" or "review one by one". "Confirm all shown" covers only the tests on screen. There is no limit on how many tests it covers; revisit if design review or testing shows one is needed. Any edit needs only that test confirmed again, not the whole set. PM approved this behavior; the screens go to design review.

Example with made-up policy:

| Question | Expected answer | Based on |
| --- | --- | --- |
| What USB drives may employees use? | Only company-issued, encrypted drives are allowed. Personal drives are not allowed. | Approved portable storage rule. |
| Can I use my own encrypted USB stick for work files? | No. Personal drives are not allowed, even if encrypted. | Same rule. |

The expected answer is only used for grading. Never send it to the agent as part of the test.

Today the feature accepts Compare Meaning, single-question sets with 1-100 cases. Keep valid existing pass thresholds and use the current defaults for new sets. These are ADK's current rules, not confirmed Copilot Studio limits.

An unsupported grading method, a missing expected answer, or a set that is too big must show a clear error or let the maker shrink the scope. Never silently drop cases or turn them into conversations.

## 9. Save tests and their provenance record

### 9.1 Use existing storage

| What | Where |
| --- | --- |
| Set written in the workspace | Existing `workspace\evaluations\{slug}\` in the Maker Kit workspace. |
| Set owned by an agent | The selected agent's `evaluations\{slug}\` folder. Use the folder the deployment helper returns, not a guessed path. |
| Native test files | Existing EvaluationSet/EvaluationData `.mcs.yml` files. |
| CSV | Existing `evaluations\exports\` folder of the chosen source, written by the strict exporter. The YAML is the main copy. |
| Source and confirmation details | **Proposed:** a local `provenance.json` next to the set. It stores the smallest relevant excerpt text, its source link, and a fingerprint. It stays on the maker's machine: `workspace\` is excluded from git by `solutions\ess-maker-skills\.gitignore`. Storing excerpt text and how long to keep it need privacy/compliance approval (OQ-9/OQ-10). |
| Real run replies and results | Existing Copilot Studio records we are allowed to read. No new local results store and no new local run-mapping file. |

A set must be linked to an agent on purpose. A workspace set is not automatically deployed or linked to every agent.

### 9.2 What the provenance record holds (proposed)

A versioned format containing:

- Which set this is and which agent it is linked to, if known.
- The source text records and which test uses which source text.
- Existing case IDs where they are stable. Missing IDs are marked as missing.
- A fingerprint of each test's question, expected answer, grading settings, and policy text.
- Whether each test is confirmed, and which fingerprint was confirmed.
- When it was confirmed and how, if known. No new reviewer role.
- For each quality score: the fingerprint that was scored and where the score came from.

File names, row order, display names, a fingerprint alone, or a status flag do not prove which test this is or that it was accepted.

**Proposed fingerprint rule:** Compute SHA-256 over a fixed, versioned UTF-8 text made from the exact question, expected answer, grading settings, and the policy text's ID and digest. Do not change case, reword, or tidy the test before computing it. Leave out display order, quality scores, and run times. A fingerprint shows that a test changed. It does not link a test to old runs, and it does not identify a fixed agent version.

**Example of what one save writes (made-up data, proposed shape pending OQ-10).** This uses the USB policy from section 8. A single save in this step writes three kinds of file into the set folder:

```text
evaluations\usb-policy\
  usb-policy.mcs.yml            existing format: set name and grading method
  usb-formal.mcs.yml            existing format: one test (question + expected answer)
  usb-everyday.mcs.yml          existing format: one test
  provenance.json               proposed: local only, never sent to Copilot Studio
  ..\exports\usb-policy.csv     existing: rebuilt from the YAML
```

The YAML uses the existing EvaluationSet/EvaluationData format and is the copy sent to Copilot Studio. It holds no excerpt, source, or confirmation details:

```yaml
# usb-policy.mcs.yml
kind: EvaluationSet
displayName: USB policy
graders:
  - kind: CompareMeaningGrader
    threshold: 0.7
```

```yaml
# usb-everyday.mcs.yml
kind: EvaluationData
rows:
  - input: "Can I use my own encrypted USB stick for work files?"
    expectedOutput: "No. Personal drives are not allowed, even if encrypted."
```

`provenance.json` links each test to the excerpt it is based on (the section 7.9 record) and records what the maker confirmed. Field names are illustrative only:

```json
{
  "schemaVersion": "1",
  "set": { "slug": "usb-policy", "linkedAgent": "employee-self-service-it" },
  "evidence": [
    {
      "evidenceId": "ev-1",
      "sourceReference": "https://contoso.service-now.com/kb?id=KB0012345",
      "sourceIdentity": { "kb": "IT Policies", "article": "KB0012345", "language": "en-US" },
      "acquisition": "pasted-by-maker",
      "approvedText": "Only company-issued, encrypted USB drives may be used. Personal drives are not allowed.",
      "sourceVersion": null,
      "obtainedAt": "2026-11-17T09:00:00Z",
      "textDigest": "sha256:…",
      "limitations": ["Article version not shown by the source"],
      "accessState": "accessible"
    }
  ],
  "tests": [
    {
      "file": "usb-everyday.mcs.yml",
      "caseId": null,
      "caseIdState": "missing",
      "evidenceIds": ["ev-1"],
      "fingerprint": "sha256:…",
      "confirmed": true,
      "confirmedFingerprint": "sha256:…",
      "confirmedAt": "2026-11-17T09:05:00Z",
      "confirmedHow": "confirm-all-shown",
      "quality": { "fingerprint": "sha256:…", "source": "automatic" }
    }
  ]
}
```

The `file` value is shown only to make the example readable; as stated above, a file name does not prove which test this is. If `fingerprint` and `confirmedFingerprint` differ, the test was edited after confirmation and needs confirming again (section 9.4).
**Open:** Check whether case IDs stay stable for imported tests and deployed copies. If not, ask for fresh confirmation and mark old links as unknown.

### 9.3 Save and promote rules

1. Check the tests, source links, and grading method before replacing any good files.
2. Prepare changes in a staging step and check them before saving.
3. Only mark a test as confirmed after it is saved successfully.
4. Rebuild the preview and CSV from the main files.
5. If any step fails, say which files were saved and which are out of date. A half-finished save must never look confirmed or up to date.
6. Update promote, copy, replace-preview, and cleanup checks so they keep the provenance file. Existing compare checks must not skip it.
7. Keep local confirmation checks out of the YAML sent to Copilot Studio. Do not assume extra files are uploaded or come back from Studio.
8. If only local records changed and the YAML is unchanged, do not create a new copy of the set in Copilot Studio.
9. Keep existing "pending review" gates. Maker confirmation does not clear them, and does not mean another reviewer approved.

Do not deploy just because the maker confirmed or saved tests.

### 9.4 Edits, imports, and missing records

| Event | What we do |
| --- | --- |
| Question, expected answer, or meaning of the policy changes | Ask the maker to confirm the affected tests again. Old quality scores for changed tests are no longer current. |
| Grading settings change | Recheck allowed methods. Old quality scores and comparisons for those tests no longer apply. Keep old run results as they were. |
| Source moves, can no longer be opened, or cannot be understood | List the affected tests and ask for confirmation again where meaning may have changed. Do not say the source is current. |
| Agent is fixed elsewhere; tests and policy stay the same | Keep the confirmation. Do not change expected answers to excuse the earlier failure. |
| Imported tests have no source or confirmation record | Do not assume they were accepted. Ask for the policy text and fresh confirmation. |
| CSV imported without a provenance record | Keep the tests, but say the record is missing. Do not rebuild it from names. |

## 10. Test quality

Reuse the existing quality checker and quality-fix flow. Use the PM spec's two labels: **Test-case quality** and **Agent test results**.

- Before scoring, explain what is checked and list the exact tests.
- Show the full test preview before the quality report.
- Tie each finding to the exact test version scored. An edited test must not keep an old score shown as current.
- Quality scoring does not run the agent and does not replace maker confirmation.
- Record where each score came from (automatic or manual), and keep the current sign-in and manual fallback choices.
- If scoring is not available, do not make up a score.
- Any quality fix that changes a question, expected answer, or policy text needs the maker to confirm again.

Today the automatic quality script sends the selected questions and expected answers to the GitHub Copilot API. **Proposed for the first release:** keep this as is and do not send the excerpt, so no new data flow is added. If the maker declines, manual scoring stays available. OQ-9 must still approve this path, along with Copilot Studio and local files. This is real data processing, not just logging. Sending the excerpt for a stronger check can be considered later, only with privacy/compliance approval.

Compare Meaning settings and sample policy tests need tuning evidence (PR-2/PR-4). Do not claim the grader catches every missing restriction until shown. If Copilot Studio gives no grading evidence, do not invent a judgment.

## 11. Get permission and run safely

### 11.1 Checks before running

Before starting, check and show:

- The exact saved set and the tests to run.
- The selected agent, tenant/environment, required connection, and run mode.
- That each test's confirmation matches its current content, and how it maps to the deployed copy.
- That the maker has access to do this.
- That the agent is in a nonproduction environment.
- Real proof (from capabilities or permissions) that the agent cannot change business systems.
- That the data use is allowed and who owns the results.

"These are only knowledge questions", an environment name, or a maker checkbox is not proof that the agent cannot write. The agent's tools may still allow writes.

**Open, blocks release:** OQ-9 must name how we actually check "no writes". If we cannot, running tests is not available. Saving or publishing test files is still allowed, with its own permission.

### 11.2 Reuse the existing run preparation

These commands are existing helpers. This document does not run them. Paths are from the Maker Kit workspace.

1. List sets: `python scripts\evaluation_runs.py list-sets --include-local`.
2. Show the options and wait for the maker to pick the exact set, in a separate turn as today.
3. Preview: `python scripts\evaluation_deployment.py preview --set-folder "{folder}" --action run`.
4. Show the scope, target, changes, and deployment plan. Get the needed permission.
5. List connections: `python scripts\evaluation_runs.py list-connections`.
6. Have the maker pick a connection. Check it in the selected environment.
7. Check again that the confirmed tests, source text, and target have not changed.
8. Start once through `run-prepared`, using the returned confirmation token and the checked connection.

Do not deploy and then also call a helper that deploys again. Push stays deploy-only.

The Copilot Studio evaluation connection is not the same as permission to read articles, and not the connector's crawler account.

Changed YAML may create a new copy of the set in Copilot Studio and leave the old one. Start only the ID returned by preparation. Do not assume in-place updates or fixed agent versions.

### 11.3 Keep each run clean

- Send only the saved employee questions as test input.
- Never send expected answers, the maker's chat, or other tests' conversations.
- Do not switch agent, connection, runner, or mode to make tests pass.
- If a test fails in published mode, show it. A draft-mode run (with its own permission) is a separate attempt.
- No custom Work IQ runner and no new business-task checks.

### 11.4 Starting, timeouts, retries, and cancelling

| Situation | What we do |
| --- | --- |
| Start accepted with a real run ID | Show the ID and status. Accepted does not mean finished. |
| HTTP 202 with no usable run ID | Record "accepted but cannot be tracked". Do not report success, and do not start again on our own. |
| Timeout or lost reply while starting | We do not know if it started. Check run history before any retry the maker approves. Do not treat a run with a similar name as proof. |
| Deploy works but start fails | Report both steps separately. Keep the prepared set. |
| Reading results fails | Retry only reads, within agreed limits. Never restart the run just to get results. |
| Maker stops waiting locally | Do not say the run was cancelled in the service. |
| Maker asks to cancel the run | Only use a supported service cancel. No such CLI option exists here today. |

The current client times out each HTTP request after 120 seconds. That is not how long a run is allowed to take. Its retry logic also retries some 429/5xx errors on POST/PUT. We must confirm that retrying a start cannot create a second run, or fix it, before reuse. Code comments saying it is safe are not proof.

**Open:** Service limits, how many runs at once, how often to check status, run time limits, read retry limits, duplicate-start protection, and cancel/resume behavior are OQ-4. Do not make up numbers.

Use the existing status/results commands. No endless polling, no push "finished" messages, and no second start just to get a results link.

## 12. Results and what we return to the caller

1. Fetch the selected run through existing history/results APIs.
2. Keep the service's original meaning, and put each case's status and details into one format.
3. Match results to tests only through supported IDs, not current display names.
4. Account for every requested test, including missing or unsupported ones.
5. Show real replies and grading details only where allowed.
6. Keep test-quality scores out of agent pass/fail.
7. Show a results link only if the helper really returned and checked it. Never make one up.

If some requested tests have no result, do not use "number of results returned" as the total. Not every non-pass is a definite policy failure.

### 12.1 Reading each test result

| What we see | What it means |
| --- | --- |
| Reply means the same thing and meets every required policy condition | Can pass, based on supported grading evidence. Exact wording matters only if the test asks for it. |
| Reply leaves out or contradicts a required restriction | A policy failure, where supported grading evidence shows it. |
| No reply, missing grading, access denied, or run not finished | Incomplete. Do not invent a judgment. |
| Formal question passes but everyday wording fails | The agent is sensitive to wording in these tests. This does not prove the cause (indexing, search, or query rewriting). |

### 12.2 Result returned to the caller

**Required:** Return exactly one of these:

| Outcome | Meaning |
| --- | --- |
| `skipped` | The maker said no to the offer. |
| `authored-not-run` | Tests were written/saved but not run. Include real confirmation and readiness details. Saving is not running. |
| `ran-passed` | Every requested test has a clear pass with the needed evidence. |
| `ran-failed` | Every requested test has a clear result, and at least one failed. |
| `ran-incomplete` | Some run, reply, or grading evidence is missing. Keep any known failures and the exact accepted/running/unknown status. Do not imply it finished. |
| `unavailable` | The requested path cannot be done because of a named missing requirement or limit. Keep work that can be recovered and any known references. |

The Connect skill is the caller (section 5.2), so `skipped` is used when the maker declines. Direct `/evaluate` requests never return `skipped`.

**Decided:** the eval skill shows the results to the maker in the Copilot chat (pass/fail, evidence, and how to find the run later). The Connect skill gets only the outcome above and does not show the results again.

In-progress states can exist internally. Do not add new final labels for the caller. If the caller must get an answer before the run finishes, return the real pending status and what is missing, never a pass.

### 12.3 What the handback includes (proposed)

- What was requested and which target was used.
- The context that was supplied, and what we could not check.
- The outcome and per-test details, including known failures and missing evidence.
- Any set/run IDs and a real results link.
- Which agent, configuration, and integration were tested.
- Whether results are current, changed, or unknown, and why.
- Which step failed and how to recover.

OQ-16 must decide the exact format, including how to show pending or unknown starts. Section 5.3 is the proposal. Freshness is "unknown" if there is no fair comparison. No new release gate is added.

### 12.4 Offer a source-backed regression test (FR-51)

After a confirmed answer problem or an identified coverage gap, offer to add a test that can catch the problem in future runs. Missing replies or grading alone do not prove an answer problem.

1. Check the selected tests for existing coverage. If an unchanged test already covers the problem, keep it for future reruns rather than creating a duplicate.
2. Where coverage is missing, explain the gap and ask whether the maker wants to add a source-backed regression test. Declining leaves the saved tests unchanged.
3. Only after the maker requests it, reuse the policy-input, test-writing, and confirmation flow in sections 7-9. Use approved text and its source reference, or ask for them if they are missing.
4. Show the proposed formal and everyday questions, expected answers, policy basis, and reason for the test. Get maker confirmation before treating the successfully saved tests as accepted.
5. Add only the requested, confirmed cases to the maker-selected compatible set, or propose a new set when none fits. Do not edit unrelated cases or rewrite an existing expectation to excuse a failed answer.
6. Do not run the new tests automatically. Running still needs a separate request and the normal safety checks. Adding a test does not change the earlier run or its outcome.

The results/recovery work item (8147419) owns the offer and hands authoring to the existing policy-based test-creation flow (8147415). No separate regression-test generator, automatic repair, or new reply archive is needed. A newly added test has no earlier result to compare until it has actually run.

## 13. Rerun the same tests after a fix

### 13.1 Explain how to select the first run later (FR-50)

When the first run has a usable returned run ID, show its test-set name, run ID, and known target alongside the results or partial status. Explain that the maker can find this run through existing evaluation history and select it as the baseline for a later rerun.

Example guidance, with the placeholder replaced only by the actual returned ID:

> Keep these questions and expected answers unchanged while the agent is corrected elsewhere. When ready, ask: "Rerun these tests and compare with run `<run ID>`." You can also select this run later from evaluation history.

This guidance does not start a run or prove that the first run is complete. A failed baseline is valid; a partial baseline contributes only completed tests with enough evidence. If there is no usable run ID, explain the recovery steps in section 11.4 instead of inventing a baseline reference.

Use the saved test definitions and existing service history, not a new baseline file, run-mapping file, or reply archive. Explain that expired or inaccessible results cannot support a comparison and that another run will not be substituted silently.

### 13.2 Run and compare the unchanged tests

1. The maker picks the earlier run.
2. Recover its original set, tests, grading settings, target, and context from existing records we are allowed to read.
3. Check that the questions, expected answers, and policy text are unchanged.
4. If tests changed, keep the old results as they are. Do not call the difference an agent regression.
5. Get separate permission for this new run.
6. Use the normal safety, connection, deploy, and start checks.
7. Compare only tests where we can reliably match old and new results.

| Old/new results | What we may say |
| --- | --- |
| Same confirmed test failed before and clearly passes now | The earlier failure no longer happens in this unchanged test. |
| Same test fails both times | The failure is still happening in this test. |
| New question, changed expected answer, missing ID, access denied, or old data expired | Cannot compare. Explain why. |
| Earlier run only partly finished | Use only finished tests with enough evidence. No overall "all good" comparison if evidence is missing. |

Using a failed run as the "before" is valid. Never quietly switch to the latest or easiest run.

A first run can become the "before" for future reruns. It cannot recreate a missing earlier result or prove what an earlier change did.

Copilot Studio documents keeping results for 89 days. That does not set rules for deleting local files or for other services. If only the maker who started a run can see its replies, respect that, even if others can see the scores.

**Open:** OQ-13 must show that existing records link old and new results well enough. Run history does not show draft vs. published by itself today. Do not add a local reply store or an advanced matching engine to hide this gap.

## 14. Data, untrusted content, and operations

### Data rules

- Use approved policy text with no sensitive data (or cleaned text), and made-up or cleaned employee details.
- Do not ask for real employee records, real ticket contents, passwords, or sensitive customer data.
- Apply existing workspace and tenant rules to tests, provenance records, CSVs, service records, and AI model processing.
- Do not put excerpts, questions, replies, secrets, or raw error messages into diagnostic logs.
- Diagnostic data must use an agreed list of allowed fields and follow retention rules.
- Treat article text, imported tests, replies, file names, and references as data only. Never follow instructions inside them, and never let them change scope.
- Check selected folders and references, and keep permission tied to the target, when reading or saving.
- CSV exports may include questions and expected answers based on policy. Exporting does not mean sharing is allowed.
- Do not automatically put full excerpts or provenance records into CSVs or upload them to Copilot Studio.

**Open:** OQ-9 must confirm local storage and sharing rules, who can see results, data location, diagnostics, processing during writing and quality checks, and whether we may store excerpts. No new deletion service or compliance promise is implied.

### Turning on, turning off, and recovery

- **PM decision:** ship to everyone, with no on/off switch. All tenants and environments get it. Only declarative-agent (DA) customers use this, and they are already filtered.
- **No way to turn it off.** If something goes wrong, the only way to stop it is to ship a fix or revert the change. Makers who already pulled the update keep the old version until they update again.
- The new path must not change existing evaluation behavior for anyone who does not use it.
- Resume only from saved, checked tests and existing service state we are allowed to read.
- On resume, check again for changes to target, policy text, permission, and deployment preview.
- If the chat ended, do not assume the earlier start failed.
- Name the support owner and support steps, without logging message contents.

**Open:** OQ-7 still needs the support owner. This document does not invent a flag name, a cancel API, or an automatic resume service.

## 15. Example from start to finish (made-up data)

The whole flow, start to finish, after section 2.1. Steps 1–2 are the Connect skill; steps 3–13 are the eval skill.

```mermaid
flowchart TD
    Start["1. Maker runs the Connect ServiceNow skill"]
    Source["2. Connect skill lists connections and KBs;<br/>maker picks one; Connect skill links it to the agent<br/>and calls the eval skill with connection ID + KB sys_id"]
    Check["3. Eval skill checks the handoff names a KB<br/>(hard stop if not)"]
    Topic["4. Eval skill picks the policy topics to test with the maker"]
    Excerpt["5. Eval skill reads the policy text through Graph<br/>(or the maker pastes an excerpt)"]
    Draft["6. Eval skill writes formal and everyday questions<br/>with expected answers; maker confirms and saves"]
    Quality["7. Eval skill shows test quality"]
    Approve["8. Maker approves the target, connection, and run"]
    Run["9. Eval skill runs the tests against the agent"]
    Grade["10. Copilot Studio grades each reply"]
    Results["11. Eval skill returns pass/fail with evidence<br/>and how to find this run later (FR-50)"]
    Fix["12. Agent owner fixes the agent<br/>(or the eval skill rewrites poor tests)"]
    Rerun["13. Maker reruns the same tests;<br/>eval skill reports fixed or still failing"]

    Start --> Source --> Check --> Topic --> Excerpt --> Draft --> Quality --> Approve --> Run --> Grade --> Results --> Fix --> Rerun
```

The numbered example below walks through the same flow with made-up data.

1. The maker runs the Connect ServiceNow skill.
2. The Connect skill lists the Graph connections and the KBs in the chosen one. The maker picks the IT KB. The Connect skill links it to the agent and calls the eval skill with `connectionId` and `kbSysId`.
3. The eval skill checks the handoff names a KB, and trusts the Connect skill that it is on the agent.
4. The maker picks "personal USB use" as a topic to test.
5. The eval skill searches that KB through Graph and reads the matching article text. If reading is not available, it asks the maker to paste an approved excerpt.
6. The text says only company-issued encrypted drives are allowed, and personal drives are not. The eval skill shows the rule as it understood it, drafts formal and everyday questions with expected answers, and the maker confirms and saves them.
7. The eval skill shows test quality separately. Any quality fix needs the maker to confirm again.
8. The maker separately approves the target, connection, and run, after the safety checks pass.
9. Suppose the everyday reply says personal encrypted drives are fine. The eval skill reports the failure and its evidence, not a guessed cause.
10. The agent owner fixes the agent elsewhere. If instead the test itself was poor, the eval skill re-reads the KB and rewrites it with the maker.
11. The maker picks the earlier run and reruns the same tests. The eval skill says "fixed" or "still failing" only when real evidence supports it.

This example does not prove a real agent will fail, or that the needed services already work.

## 16. Work split across the user stories

The five stories are under Feature 8199402 (ServiceNow Knowledge Evaluations for ESS Makers) and numbered by PM priority. The sprints match the iteration paths in Azure DevOps.

| # | Story | What to build | Effort | Sprint | Depends on |
| --- | --- | --- | --- | --- | --- |
| 1 | Shared flow and knowledge source (8147416) | Shared entry and result format, `/evaluate` and plain-language start, finding the agent's knowledge source, exact source/set selection, limited edits. No ServiceNow offer (deferred). | 3 days | 2601 (current, ends Nov 20) | Source lookup proven to work, or maker selection. |
| 2 | Policy-based test creation (8147415) | Full excerpt flow, conditional reader, formal/everyday tests, "confirm all shown" / "review one by one", handling source changes, local provenance. | 3.5 days | 2601 (current, ends Nov 20) | Story 1; OQ-9/OQ-10 approval to store excerpts; reader proof if we build one. |
| 3 | Run approved tests and grade replies (8147417) | Pre-run checks, no-write check, chosen connection/mode, native prepare/start, no duplicate starts, run recovery, quality tied to exact test version, reading Copilot Studio grading, complete vs. missing evidence, tuning. | 7 days (4 run + 3 grading; not re-estimated after the merge) | 2602 (next) | Story 2; OQ-4; OQ-9 sign-off on the no-write check; PR-2/PR-4 and the real grading/reply format. |
| 4 | Baseline comparison and recovery (8147419) | Complete results, unchanged reruns using existing history, FR-50 guidance (section 13.1), FR-51 regression-test offer (section 12.4), recovery, accessibility, measurements, maker testing. | 3 days | 2602 (next) | Story 3; OQ-13; design sign-off; OQ-7 support owner. |
| 5 | Task checks and advanced comparison (8147420) | Deferred: business-task checks, matching across new copies, comparing partly edited sets. | Later | Not planned for the first release (parked in 2602 in Azure DevOps) | Not in the first release. |

**Commitment:** stories 1 and 2 (6.5 days) in sprint 2601, which ends Nov 20. Stories 3 and 4 (10 days) in sprint 2602. Story 5 is later. Story 3 cannot start real runs until the OQ-4 and OQ-9 approvals arrive. If they are late, the grading part of story 3 and then story 4 slip first.

**Needs re-planning after section 2.1 (Azure DevOps not changed yet):**

- Story 1 adds the handoff (sections 5.2–5.4): handoff format, handoff checks, hard stop when no KB, and "evaluate my agent" runs existing evals.
- Story 2 stays with the eval skill. Its reader is now the Graph reader using `connectionId` + `kbSysId` (sections 6.1 and 7.5.1). The paste-excerpt path stays.
- Stories 3 and 4 stay as they are.
- The Connect-skill start depends on the Connect ServiceNow skill shipping. Direct `/evaluate` knowledge tests work once the KB is on the agent.

## 17. How we will verify it

This design does not claim anything has been built or accepted yet.

### 17.1 Automated tests

Extend existing test files for changed behavior. Add new test files only for new components.

| Area | Cases to cover |
| --- | --- |
| Context and start | `/evaluate` and plain-language requests in one format, missing/unclear source, lookup not supported, wrong target, separate write/run permission. |
| Excerpt capture | Good supplied text, reference only, missing reference, too little or conflicting text, denied read, timeout, partial text, unsafe data refused, asking for excerpt without asking for more access. |
| Conditional reader | Allowed and denied article, correct account and source, unclear choice, supported text formats, missing related content, redirects and sign-in limits. |
| Writing tests | Formal and everyday tests share the same policy text; expected answers are never sent to the agent; unrelated tests stay unchanged. |
| Provenance | Group confirmation, question/policy edits clear confirmation, imports without records, promote/cleanup keep the record, failed or half saves never look current. |
| Quality | Real score source, score not available, edited test clears old score, never mixed with agent pass/fail. |
| Deploy/run | New copy vs. reuse, changed preview token, disconnected profile, no-write status unknown, accepted with no ID, lost start reply, no duplicate retry, no false cancel. |
| Results | All pass; all clear with a failure; known failure plus missing reply; requested tests missing; empty results; run not finished; no made-up link or judgment. |
| Regression-test offer | Confirmed answer problem or coverage gap; missing evidence is not a confirmed failure; existing coverage avoids duplicates; declining makes no edits; requested cases reuse policy authoring and confirmation; no automatic run or expectation rewrite. |
| Rerun | First-run guidance uses the real run ID and existing history without starting a run; no ID means recovery guidance, not an invented baseline; unchanged failed "before", fix made elsewhere, changed test, new test, missing link, expired/denied evidence, partial "before". |
| Existing features | Custom-agent test writing, exports, review gates, push-only, and unrelated setup/connect flows still work. |

Existing test files include `tests\scripts\test_evaluation_authoring.py`, `test_evaluation_csv.py`, `test_evaluation_presentation.py`, `test_evaluation_method_policy.py`, `test_evaluation_promotion.py`, `test_evaluation_deployment.py`, `test_evaluation_runs.py`, and `test_evaluation_experience_contract.py`.

Tests with fake (mock) responses do not prove real tenant access or API support. Fake responses must match documented formats, vendor examples, or approved cleaned real samples. Follow the repo's stricter recorded-response (cassette) and tier rules wherever FlightCheck or shared mocks are used.

### 17.2 Proof needed from real systems

Before turning on a reader or claiming the full journey works:

1. Show source lookup working on the real selected agent, or show that maker selection works when lookup is not available.
2. For automatic reading: show an allowed read, a denied read, that the text is complete enough, and failure handling, all without new permissions.
3. Show a real "cannot write to business systems" check, not just knowledge-only questions.
4. Show a real run ID, real replies, grading evidence, and that every requested test is accounted for.
5. Show a rerun of unchanged tests using supported links, and when the comparison must stay unknown.
6. Show that existing evaluations still work for makers who do not use the new path, since there is no on/off switch.
7. Check resume, retention, access, and diagnostics controls.

The Connect skill's handoff, a declined offer (`skipped`), the hard stop when no KB exists, and the returned result are tested with the Connect ServiceNow skill once it ships. Before that, test them with a fake handoff.

### 17.3 Maker and design testing

- Test with makers who set up ServiceNow knowledge, are not experts, and did not build this feature.
- Use the PM acceptance plan cases that apply to the first release, not all 103 cases.
- Compare answer judgments to a separate manual check by a policy owner.
- Record M1/M3 as complete or incomplete, including any help given and missing evidence.
- Include a known failing test to check that failures are caught. If we do not have one, record the gap. Do not assume the USB example fails.
- Check text states, keyboard use, focus, screen readers, confirmation scope, partial results, and recovery against the approved design.
- Stop testing if data, access, no-write, or evidence rules cannot be met.

## 18. Open decisions that block work

Developers must not fill these in with guesses.

| Gate | What we need to know or show | What it blocks |
| --- | --- | --- |
| OQ-1/OQ-16 | **Decided:** the Connect skill calls the eval skill. The eval team defines the handoff format (section 5.3) and tells the Connect skill owners what to pass; no separate sign-off. | — |
| Who writes knowledge tests | **Decided:** the eval skill reads the KB (connection ID + KB sys_id from the handoff) and writes the tests. Still open: tell PM, because their Q1/Q3 answer said the Connect crew creates the test sets. | PM spec alignment. |
| Who picks the KB | **Decided:** one connection can hold many KBs (section 6.1). The Connect skill selects the KB and passes its `kbSysId` (with `connectionId`) to the eval skill in the handoff. | — |
| When the eval skill is called | **Decided:** the Connect ServiceNow skill calls the eval skill and owns when that happens. The eval skill does not need to handle the timing. | — |
| What goes back to the Connect skill | **Decided:** one outcome from section 12.2. The eval skill shows the results in the Copilot chat; the Connect skill does not repeat them. | — |
| Who confirms knowledge tests | **Decided:** the eval skill, since it writes them (section 8). | — |
| More than one KB on an agent | Expected one. If two or more: pick one, run all, or stop? | Handoff checks. |
| No results | **Decided:** tell the maker exactly what came back (for example, no articles found for that KB). Retry only when an API call failed or errored; do not retry an empty but successful result. | — |
| Connector not ready | **Decided:** the Connect skill checks the Graph connector is ready (not a draft, finished loading) before calling the eval skill. The eval skill trusts this and reports whatever it gets back. | — |
| Copilot license | **Decided:** OK if the Retrieval API needs a Microsoft 365 Copilot license. Fallback when it is not available: Search plus the paste-excerpt path. | — |
| Admin consent | **Decided:** the eval skill only reads the KB; it does no permission or consent check. A refused call is reported to the maker as returned. | — |
| Other sources | The eval team works out the `sourceRef` fields for SharePoint, Workday, and ServiceNow ticketing through its own POC or API probe, as done for the ServiceNow KB (section 6.1). | Adding those Connect skills (section 5.4). |
| Source lookup | **Proven (section 6.1):** connection → KBs → articles works through Graph Search. **Decided:** the eval skill trusts the Connect skill that the handoff's KB is on the agent; it does not check. | — |
| Automatic reading | **Partly proven (section 7.5.1):** Graph Search and the Retrieval API return article text. License and consent are decided (above). **Decided:** the eval skill reads the complete article, not just previews or passages. Still open: prove which call returns the full text (Search previews are 255 characters; Retrieval returns passages). | Automatic reading only. Pasted excerpts still work. |
| OQ-9 | **Decided:** the policy/article text read from the KB (excerpt text) is stored locally. Still open: existing data rules, a real "no business writes" check, and approving quality scoring as today (questions and expected answers only). | Unsafe processing or storage, and all unchecked run paths. |
| OQ-10 | Approve the proposed record fields (including excerpt text), how long to keep them, how confirmation ties to test versions, imports, and stable IDs. | Claims that confirmation is kept or recovered, and complete provenance. |
| PR-2/PR-4 | Real grading evidence and tuning, and telling a real judgment apart from missing evidence. | Trustworthy pass/fail conclusions. |
| OQ-4 | Service limits and safe timeout/retry/resume/cancel behavior; fix the risk of duplicate starts. | Safe running and recovery in production. |
| OQ-13 | Enough links between old and new tests, runs, grading, target, and context. | Clear rerun comparisons where those links are missing. |
| OQ-7 | **Partly decided:** ship to everyone, no on/off switch. Still open: the support owner. | Release readiness. |
| Design | Approved screens/steps for picking sources, pasting excerpts, confirming tests ("confirm all shown" and "review one by one", approved by PM), results, recovery, and accessibility. Goes to design review; who signs off on UX is still to be confirmed. | Customer-facing experience sign-off. |
| OQ-15 | **Decided:** five stories under Feature 8199402. Stories 1–2 in sprint 2601 (ends Nov 20), stories 3–4 in sprint 2602, story 5 later (section 16). | Depends on the approvals listed in section 16 arriving on time. |

We can start now on the handoff format and checks, the Graph reader, policy-based test writing, the paste-excerpt path, and the run and results work. Do not claim the full first release until the safety, run, provenance, and acceptance gates are closed and the Connect ServiceNow skill ships.

## 19. Links to PM requirements

| Engineering section | PM requirements |
| --- | --- |
| Start, context, and source selection (sections 5-6) | FR-13, FR-44 to FR-47, FR-49; PR-1/PR-7. |
| Excerpt and policy handling (section 7) | FR-11/FR-12/FR-16/FR-41/FR-55/FR-56; PR-6. |
| Writing, confirming, and saving (sections 8-9) | FR-1, FR-13 to FR-18, FR-41, FR-51, FR-55/FR-56; PR-1. |
| Quality (section 10) | FR-19 to FR-21; PR-2. |
| Running (section 11) | FR-2/FR-3/FR-5/FR-6/FR-9/FR-10/FR-22/FR-23/FR-32 to FR-37; PR-3/PR-6. |
| Results, handback, and regression-test offer (section 12) | FR-25 to FR-27/FR-31/FR-38/FR-42/FR-49/FR-51/FR-57 to FR-59; PR-4/PR-7. |
| Rerun and first-run guidance (section 13) | FR-28/FR-39/FR-40/FR-43/FR-50/FR-54/FR-56; PR-5. |
| Data, operations, and verification (sections 14, 17, 18) | FR-9/FR-10/FR-32 to FR-35; PR-6; M1/M3; GR-1 to GR-7. |

## 20. Sources

- PM spec and its acceptance plan: PR 5771115, revision 13, iteration and commit listed at the top. We have not checked any newer revision.
- Existing evaluation rules: `solutions\ess-maker-skills\src\skills\evaluations\experience-contract.md`, `deployment-flow.md`, and `run\SKILL.md`.
- Existing writing and routing skills: `dispatcher\SKILL.md`, `create\SKILL.md`, `generate\SKILL.md`, `update\SKILL.md`, and `validate\SKILL.md` in the evaluation skills folder.
- Existing Python helpers in `solutions\ess-maker-skills\scripts`: `evaluation_authoring.py`, `evaluation_review.py`, `evaluation_presentation.py`, `evaluation_csv.py`, `evaluation_method_policy.py`, `evaluation_promotion.py`, `evaluation_deployment.py`, `evaluation_runs.py`, and `minimalbot_evaluation.py`.
- Source lookup code in the same scripts folder: `flightcheck\pva_client.py`, `flightcheck\checks\local_files.py`, and `flightcheck\checks\graph_connector_kb.py`.
- ServiceNow status and sign-in: `solutions\ess-maker-skills\src\skills\connect\servicenow\integration.json` and `solutions\ess-maker-skills\src\mcp\servicenow\client.py`.
- [ServiceNow Knowledge Management REST API](https://www.servicenow.com/docs/r/api-reference/rest-apis/knowledge-api.html).
- [ServiceNow Knowledge access controls](https://servicenow.github.io/sdk/4.12.2/guides/knowledge-base-access-guide).
- [Microsoft Graph search of connector content](https://learn.microsoft.com/en-us/graph/search-concept-custom-types).
- [Microsoft Graph search access behavior](https://learn.microsoft.com/en-us/graph/api/resources/search-api-overview?view=graph-rest-1.0).
- [Microsoft Graph external item GET](https://learn.microsoft.com/en-us/graph/api/externalconnectors-externalitem-get?view=graph-rest-1.0).
- [Microsoft 365 Copilot Retrieval API](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/retrieval/copilotroot-retrieval).
- PM answers to Q1–Q3 (Teams, November 2026) and the discussion with the Connect ServiceNow skill owner (section 2.1).
- Graph calls run in a test tenant in November 2026 (sections 6.1 and 7.5.1).

Public API docs only show possible ways to do this. They do not prove the customer's setup, existing permissions, complete text, or an approved end-to-end design.
