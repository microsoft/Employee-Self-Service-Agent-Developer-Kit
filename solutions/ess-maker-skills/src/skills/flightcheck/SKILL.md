# FlightCheck Skill

Pre-deployment readiness validation for ESS agents. Runs automated checks
against the live environment (licenses, Entra, Power Platform, Workday/
ServiceNow/SAP integrations) and validates extracted agent files on disk.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase it or narrate tools. Additional language is permitted only by
the profile onboarding and adaptive presentation contracts below.

## Maker communication profile

For direct entry, use eligible mode only after the canonical FlightCheck
entry gate and required scope/target selections pass, before checks execute.
When invoked by `/flightcheck`, inherit its entry. Reuse a caller-supplied
immutable profile and never count or claim again for a nested call, including
when invoked by Setup. Read
`src/skills/shared/user-profile-entry.md` and
`src/skills/shared/user-profile-contract.md`. Follow the claimed optional
onboarding conversation, then resume the same check and finish once with its
actual outcome. Preserve operational Message blocks and required fix/consent
turns exactly.
Step 3 explicitly permits profile-aware summaries, findings layouts, supported
explanations, and one optional tip. Use the same frozen profile on rechecks.
Do not add a style indicator or automatic learned-preference proposal.

---

## Start

The calling prompt applies the **FlightCheck entry contract** in
`.github/copilot-instructions.md`. When this skill is invoked directly, apply
that contract before continuing.

Continue with this skill for the contract's **Standalone FlightCheck** and
**Canonical setup ready** states. The contract owns the maker interaction and
next route for its other states.

Treat a config with `releaseLine: "da"` and no `dataverseEndpoint` as a native
no-Dataverse agent. Its supported scopes are `full`, `environment`,
`servicenow`, `workday`, `local`, and `infrastructure`. If
`dataverseEndpoint` is present, use the existing hybrid/legacy path even when
the release line is `da`.

---

## Step 1: Ask scope (optional)

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Scope",
    "question": "What would you like to check?",
    "options": [
      { "label": "Full check", "description": "All categories — licenses, environment, auth, integrations, agent files, publishing", "recommended": true },
      { "label": "Workday only", "description": "Workday connections, flows, env vars, and SOAP workflow tests" },
      { "label": "ServiceNow only", "description": "ServiceNow connections, flows, template configs, and local topics" },
      { "label": "Local files only", "description": "Validate extracted topic files, agent config, variables" },
      { "label": "Environment only", "description": "Validate environment readiness and Copilot Studio capacity" },
      { "label": "Prerequisites only", "description": "Licenses, roles, capacity" }
    ],
    "allowFreeformInput": false
  }
]
```

Map the selection to a scope flag:
- "Full check" → `full`
- "Workday only" → `workday`
- "ServiceNow only" → `servicenow`
- "Local files only" → `local`
- "Environment only" → `environment`
- "Prerequisites only" → `prerequisites`

For a native no-Dataverse agent, omit "Prerequisites only". Its full scope
runs exact-agent access, authored-content, native connection readiness,
environment capacity, and applicable local-file checks; it does not run
Dataverse, Graph, Power Platform Admin, or legacy flow checks.

---

## Step 1.5: Select the integration target (only when there is a choice)

A tenant can have **more than one** Workday Entra SSO enterprise app
(dev / test / prod, demos, trials) or more than one ServiceNow connection.
When that happens, checks like `WD-CONN-102` would otherwise validate *all*
of them together and a healthy prod app could be masked by an unrelated
sandbox app. This step lets the user pin the one they are verifying.

**Only run this step for scopes that touch those integrations:**
- native no-Dataverse agent → **skip this step entirely**; connection checks
  use the exact active agent and never guess among physical candidates
- scope is `full` or `workday` → discover Workday SSO apps
- scope is `full` or `servicenow` → discover ServiceNow connections
- any other scope (`local`, `prerequisites`, …) → **skip this step entirely.**

For each applicable integration, run the discovery helper in the terminal
(it authenticates, prints JSON, and runs **no** checks):

```
python scripts/flightcheck/cli.py --list-targets workday
```
```
python scripts/flightcheck/cli.py --list-targets servicenow
```

Parse the JSON on stdout. It has the shape
`{ "kind": "workday" | "servicenow", "targets": [ … ], "error": "…"? }`.
- Workday target rows: `{ "appId", "displayName", "id" }`.
- ServiceNow target rows: `{ "name", "displayName", "status" }`.

Decision:
- If `error` is present, or `targets` has **0 or 1** entries → do **not** ask;
  there is nothing to disambiguate. Leave the target flag unset.
- If `targets` has **2 or more** entries → ask the user to choose with
  `vscode_askQuestions`. Build one option per target plus an "All" option.
  Use `displayName` as the label and include the identifier in the
  description so duplicates are distinguishable. Example for Workday:

```json
[
  {
    "header": "Workday SSO app",
    "question": "Which Workday Entra SSO app should FlightCheck verify?",
    "options": [
      { "label": "All apps", "description": "Validate every Workday SAML app (default)", "recommended": true },
      { "label": "{displayName}", "description": "appId {appId}" }
    ],
    "allowFreeformInput": false
  }
]
```

Map the answer to a flag for Step 2:
- Workday, a specific app → `--workday-app-id {appId}` (from the chosen row).
- ServiceNow, a specific connection → `--servicenow-connection {name}`.
- "All apps" / "All connections" → no target flag (validate all).

If both a Workday app **and** a ServiceNow connection are being chosen (scope
`full` with multiples of each), collect **both** flags.

---

## Step 2: Run the check
## Step 2: Consent gate for the connectivity probe (MANDATORY — ask before running)

FlightCheck's connectivity check (INFRA-003) confirms the agent's external system
endpoints (Workday, ServiceNow, SAP SuccessFactors, custom HTTP) are reachable
**from the Power Platform environment's own egress** — the path the agent runtime
actually uses. The only way to prove that is the **live egress probe**
(`--runtime-reachability`): it briefly creates a transient Power Platform flow,
sends one outbound request, reads the result, then deletes the flow. This is the
**only** FlightCheck path that writes to the tenant.

Because it mutates the environment, you **MUST** ask for consent **before** you run
the check. Do not run first and ask later. The terminal CLI cannot prompt you in
chat (it is a non-interactive subprocess), so **you own the consent question**.

**WD-RUN-001** (the Workday run-health check) is **passive-only** and does **not**
use this probe: it grades a real, recent end-to-end Workday run from run history
and never writes to the tenant. If no fresh run exists it returns a guided
NOT_CONFIGURED — see the **WD-RUN-001 user-assisted run** loop in Step 3. So this
gate is about INFRA-003 only.

**This gate applies only when INFRA-003 runs its mutating probe: scope `full`.**
For `workday`, `workdayextension`, ServiceNow-only, Local-files-only, or
Prerequisites-only scopes, skip this gate and go straight to Step 2b.

For a native no-Dataverse agent, skip this gate for every supported scope.
Its AgentBuilder, connection-inventory, capacity, and local checks are
read-only and never create a transient flow.

Ask using this exact wording, swapping `<SYSTEM>` for the system being checked
(Workday / ServiceNow / SAP SuccessFactors / custom HTTP — use the connected
system(s) from `.local/config.json`; if more than one, name **all** of them,
since the probe tests every configured endpoint):

> To check that your connection to `<SYSTEM(S)>` is whitelisted, I'll create a temporary
> flow in your environment that sends a test network request, then delete it right
> after. It won't touch any of your data. Okay to proceed?

The reassurance points (no data touched, auto-deleted) are what earn user trust.
Keep them in whatever phrasing you use.

- **If the user says YES** → run the check **with** `--runtime-reachability` (Step 2b).
- **If the user says NO** → run the check **without** the flag (Step 2b), then in the
  summary note that the INFRA-003 connectivity probe was skipped by choice.
  INFRA-003 returns **Manual** guidance. Offer the manual verification path:

> Prefer to verify manually? You can confirm the connection is whitelisted:
>
> 1. In the Power Platform admin center, note your environment's region.
> 2. From Microsoft's [Managed connectors outbound IP addresses](https://learn.microsoft.com/en-us/connectors/common/outbound-ip-addresses)
>    list, get the ranges for that region. For a custom HTTP endpoint, use the
>    Power Automate service tags instead (the machine-readable ranges are in the
>    [Azure IP Ranges and Service Tags JSON](https://www.microsoft.com/en-us/download/details.aspx?id=56519)).
> 3. Work with your InfoSec / network team to confirm those ranges are allowlisted
>    in your `<SYSTEM>` firewall / WAF.

> **Note:** without `--runtime-reachability`, INFRA-003 returns **Manual** guidance —
> it does not fall back to a local probe (a probe from the maker's machine runs on a
> different network than Power Platform's egress, so it cannot prove the runtime
> path). The flag creates one transient probe flow per run, always deletes it (even
> on failure), and sweeps any orphan left by a crashed prior run.

---

## Step 2b: Run the check

Before the running message, apply `confirmationFrequency` from the frozen
profile using the adaptive contract below. A `frequent` recap is optional and
may occur at most once per top-level request, after required selections and
onboarding. Skip it when a required confirmation already covered this scope
and target or the caller forbids extra interaction. Never repeat it for quiz
replies, fix rechecks, or user-assisted validation.

**Message:**

Running readiness checks — this takes 1–3 minutes depending on scope...

**End message.**

Run in the terminal. Append any target flag(s) chosen in Step 1.5; always pass
`--select-targets never` so the CLI relies on this skill's selection instead of
trying to prompt in the non-interactive terminal. Also append
`--runtime-reachability` **only** if the user said YES at the Step 2 consent gate:

```
python scripts/flightcheck/cli.py --scope {SCOPE} --invocation-source adk --select-targets never {TARGET_FLAGS}
```

`{TARGET_FLAGS}` is empty when the user chose "All" (or there was nothing to
choose), or one/both of `--workday-app-id {appId}` / `--servicenow-connection {name}`.

On YES for runtime reachability:

```
python scripts/flightcheck/cli.py --scope {SCOPE} --invocation-source adk --select-targets never {TARGET_FLAGS} --runtime-reachability
```

Wait for the script to finish.

`cli.py` automatically opens the HTML report (`workspace/flightcheck/report.html`)
in the user's default browser when it finishes. **Do not open it yourself** — a
second `webbrowser.open` / `Start-Process` would launch a duplicate tab pointing
at the same file. If the report does not appear (Codespaces, headless box, or
the user passed `--no-open`), tell them to open it manually from the file
explorer rather than spawning another tab from this skill.

---

## Step 3: Read results and present findings

Read `workspace/flightcheck/results.json` and render the adaptive chat report
below **yourself, directly in your chat reply** using the frozen execution
profile. The chat presentation may adapt; the underlying checks, JSON, and full
HTML report never change because of communication preferences. Without a saved
profile, use the canonical resolved defaults, not a separate FlightCheck default.

**Do NOT write or run any code to render these results.** Read the JSON with your
file-reading tool and write the response inline. Never author a helper
script (`.py`, `.js`, `.ps1`, a shell one-liner, etc.) to parse `results.json`,
build the response, or print the summary, and never execute one. The values you
need (counts, `overall`, `duration_secs`, and each object in the `results` array)
are already in the JSON. Writing a script here is a bug: it dumps raw terminal
output into chat instead of the
clean formatted result, and it exposes internal process the user should never
see. If the file is large, read it in ranges — do not shortcut it with code.

### Adaptive presentation contract

Classify the output section by section. Verdict wording, source counts, evidence,
remediation, links, next-step owners, and mandatory choices are protected content.
Summary layout, findings layout, optional explanation, and optional tips are
flexible. A table used for adaptive findings is not an exact Message block.

Always show every non-passing result individually: Failed, Blocked, Error,
Warning, Manual, NotConfigured, and Skipped. Do not hide, merge, or downgrade
these findings, even for concise output, a low word budget, or tips set to off.
Keep each finding's checkpoint ID, category, priority, status, observed `result`,
complete `remediation`, `doc_link`, and next-step `roles` when supplied.
Copy source evidence and remediation faithfully; tone changes apply only to
surrounding explanation, never to factual values or required remediation wording.
Missing remediation or ownership is not permission to invent it. Surface missing
required guidance as a limitation. Never imply a skipped or manual check passed.

The six independent settings have these FlightCheck-specific effects:

| Setting | Chat behavior |
|---|---|
| `responseFormat` | `auto`: compact counts and a findings table for multiple findings, or one labeled bullet for a single finding. `prose`: counts in a sentence and a short labeled paragraph per finding. `bullets`: flat labeled bullets for counts and findings. `steps`: compact counts followed by numbered remediation/review steps, one per finding; these are proposed actions, not executed actions. `table_first`: counts table followed by a findings table. The protected verdict remains first in every format. |
| `detailLevel` | `concise`: all non-passing findings, passing count only, and essential next actions. `balanced`: the same non-passing findings, passing counts grouped by category, and brief evidence-grounded reasoning about the next action. `detailed`: every check, including each passing check, plus supported explanation of evidence, limitations, and remediation dependencies. A request for all results always includes every check regardless of the saved level. |
| `toneOfVoice` | `direct`: short, action-oriented explanatory sentences. `friendly_professional`: collaborative wording. `formal`: reserved, precise wording. `empathetic`: acknowledge the observed blocker or effort without guessing how the maker feels. Do not rewrite the verdict, source findings, remediation, or exact operational messages. |
| `confirmationFrequency` | `minimal`: no optional check-ins. `standard`: clarify only material ambiguity that remains after required selections. `frequent`: may add at most one scope/target recap before executing checks, with a choice to continue or change scope, unless a required confirmation already covered it. Never ask an extra question solely to report results. Scope/target selections, fix consent, and other mandatory approvals remain unchanged in every mode; a caller's stricter interaction contract wins. |
| `maximumResponseLength` | A soft word budget for the chat response. Shorten optional explanation and omit an optional tip before exceeding it. Never truncate a finding, remediation, role, link, count, required choice, or any check required by the selected detail level or explicit request. Exceed the budget when protected content does not fit. The HTML report and JSON are never shortened. |
| `proactiveSuggestions` | `off`: no optional tip. `contextual`: at most one evidence-supported improvement within the inspected scope. `on`: at most one evidence-supported adjacent next step instead. Never invent a finding or offer an unavailable operation. Required fixes, manual actions, warnings, and completion guidance appear in every mode; they are not optional suggestions. |

Settings do not select presets for each other: prose does not mean detailed,
concise does not imply a word cap, and minimal check-ins never approve fixes.
Explicit instructions for this request override saved style without changing
the stored profile. Do not reread the profile during rendering or rechecks.

If a report is missing, malformed, or contradictory, surface the observed
report error rather than inventing counts or a successful verdict. If an
unrecognized status occurs, retain its source label and evidence visibly as a
limitation; do not silently drop it or translate it into Passed.

### 3a — Verdict and counts

Always show the source verdict first, using this exact wording:

- READY → ✅ and "Your agent is ready for deployment"
- READY_WITH_WARNINGS → ⚠️ and "Ready with warnings"
- NOT_READY → ❌ and "Issues found — not ready for deployment"

Follow it with counts in the selected format. Include `total`, `passed`,
`failed`, `warnings`, and `not_configured`, plus `blocked`, `errors`, `manual`,
and `skipped` when nonzero. Copy these values from the source report; do not
recompute the verdict from the subset of checks shown in chat.
Always include the duration and this link:

```
Completed in {duration_secs}s - [View full report](workspace/flightcheck/report.html)
```

### 3b — Findings and passing coverage

Render the checks selected by `detailLevel` in the layout selected by
`responseFormat`. Order findings by Failed, Blocked, Error, Warning, Manual,
NotConfigured, Skipped, then Passed; preserve source order within each status.
For prose, bullets, or steps, use labeled fields so every protected value
remains identifiable. For a table, use:

```
| Checkpoint | Category | Priority | Status | Result | Remediation | Next-step owner |
|---|---|---|---|---|---|---|
| {checkpoint_id} | {category} | {priority} | {status_emoji} {status} | {result} | {remediation and doc_link, when supplied} | {roles, when supplied} |
```

If no checks qualify for individual display, say so; do not emit an empty
findings table. When passing rows are omitted, state how many are represented
by the passing count or category summary and that the full report contains
every check. No other status may be collapsed into passing coverage.

For example, with the same report, `prose` plus `concise` produces a count
sentence and paragraphs for non-passing findings only. `table_first` plus
`detailed` produces a counts table and a row for every check. Both preserve the
same verdict, counts, non-passing evidence, remediation, owners, and report link.

Status emoji mapping:
- Passed → ✅
- Failed → ❌
- Blocked → ⛔
- Error → 💥
- Warning → ⚠️
- Manual → 🔎
- NotConfigured → ℹ️
- Skipped → ⏭️

If permitted by `proactiveSuggestions` and the remaining word budget, place one
optional tip after the findings and before the required action/terminal block.
Do not append it after a terminal message or while waiting for a required user
choice. Optional tips are not automatic learned-preference proposals.

If WD-RUN-001 is NotConfigured, follow Step 3d before choosing a terminal
completion path below; neither concise output nor tips set to off can suppress
that required user-assisted validation.

### 3c — Offer to fix

After the findings, analyze every non-passing result and build a list
of things you CAN fix automatically vs. things that need manual action.
Use only supported fixes below and the source evidence; a preference never
adds permission or changes which operations this release supports.
Classify required action from the evidence, not just the status: a genuinely
non-applicable Skipped result does not automatically require a repair. If no
automatic fix or manual action is required, retain the source verdict and
report that no corrective action is required; do not invent a manual task.

**Auto-fixable** (offer to do these right now):
- Compile errors in topics → run `/scan` skill
- Missing Workday connection → run `/connect` skill
- Workday env vars not set → run `/connect workday` skill
- Workday connections in Error state → run `/connect workday` skill
- Disabled Workday/ServiceNow flows → enable via Dataverse MCP

**Needs manual action** (the findings already contain the supplied links):
- License issues → links to M365 admin center
- Agent instructions/starter prompts/topics → links to Copilot Studio
- DLP policies → links to Power Platform admin center
- Publishing items → links to deployment docs

The findings already contain the complete remediation and supplied links.
Do not repeat the whole findings list. Show the auto-fixable offer (if any)
and the required manual-action note. Keep the fix-selection table and consent
question below contractual, even when `responseFormat` is prose, bullets, or
steps. Never suppress manual remediation because `proactiveSuggestions` is off.

**If overall is "READY":**

Show:

```
No action needed. Run `/flightcheck` again anytime before publishing.
```

Use this terminal message only when no required remediation or user-assisted
validation remains. Otherwise retain the source verdict, explain the remaining
action from the findings, and use the appropriate action path below.
Stop after the terminal message; never append an optional tip afterward.

**If there are auto-fixable issues:**

Show:

```
I can fix some of these automatically. Want me to?

| # | Fix | What I'll do |
|---|-----|-------------|
| 1 | {description} | {what the skill will do} |
| 2 | {description} | {what the skill will do} |
| ... | | |

**Manual steps** (need your action):
- {issue}: {link to portal/docs}
```

Then use `vscode_askQuestions` to ask:

```json
[
  {
    "header": "AutoFix",
    "question": "Want me to fix the auto-fixable issues listed above?",
    "options": [
      { "label": "Yes — fix what you can", "recommended": true },
      { "label": "No — I'll handle it myself" }
    ],
    "allowFreeformInput": false
  }
]
```

**If they say yes**, execute each fix by reading and following the
appropriate skill file:
- Connection issues → read `src/skills/connect/SKILL.md` and follow it
- Compile errors → read `src/skills/cleanup/SKILL.md` and follow it
- Flow enablement → use Dataverse MCP to update flow state

After all auto-fixes complete, re-run flightcheck (reuse the **same** scope and
the **same** target flag(s) the user chose in Step 1.5, if any):

```
python scripts/flightcheck/cli.py --scope {SCOPE} --invocation-source adk --select-targets never {TARGET_FLAGS}
```

`cli.py` reopens the updated report in the browser automatically — **do not run
`Start-Process` or `webbrowser.open` yourself**, or the user will end up with
two tabs of the same report.

Then present the new results using the same frozen profile and adaptive
contract (3a → 3b → 3c).

**If they say no**, show:

```
No problem. Run `/flightcheck` again after making fixes.
```

**If there are NO auto-fixable issues (only manual):**

Show:

```
The issues above need manual action — follow the remediation links shown with the findings.

Run `/flightcheck` again after making changes.
```

**End of output. Stop here. Do not add commentary after this.**

### 3d — WD-RUN-001 Workday user-assisted run (only when WD-RUN-001 is NotConfigured)

WD-RUN-001 grades a **real, fresh** end-to-end Workday run — the full
`Copilot → Workday → response back to Copilot` path, not just `Flow → Workday`.
There is no safe headless way to trigger that path: the Workday connector is
invoker-scoped, so the flow does not carry the end user's Workday token, and
firing the flow directly only tests the flow leg. We have seen incidents where
the flow succeeded but the Copilot experience still failed, so the only trustworthy
signal is an actual user-driven run.

The check cannot start that run for the user. So when WD-RUN-001 comes back
**ℹ️ NotConfigured** (no Workday run finished in the last 60 minutes), walk the
user through producing one, then re-run. Show this:

```
WD-RUN-001 needs a fresh end-to-end Workday run to grade, and there isn't one in
the last 60 minutes. It only takes a moment to create one:

1. Sign in to your deployed ESS Copilot agent (Microsoft 365 Copilot or Teams —
   the same agent your employees use), as yourself.
2. Ask one safe, read-only Workday question and wait for the agent to answer:
   - "Who is my manager?"
   - "What is my job title?"
   These only read your own profile. They change nothing in Workday.
3. Once you get an answer back in chat, the full round-trip has run.

Tell me when that's done and I'll re-run the Workday check.
```

When the user confirms, re-run with the Workday scope (or the same scope they
started with, if broader) within the 60-minute window:

```
python scripts/flightcheck/cli.py --scope workday --invocation-source adk --select-targets never {TARGET_FLAGS}
```

Then present the new results using the same frozen profile and adaptive
contract (3a → 3b → 3c). If WD-RUN-001
is now ✅ Passed, the end-to-end path works. If it still comes back NotConfigured,
the run likely landed outside the 60-minute window or did not reach Workday — ask
the user to retry the safe question and re-run right after.
