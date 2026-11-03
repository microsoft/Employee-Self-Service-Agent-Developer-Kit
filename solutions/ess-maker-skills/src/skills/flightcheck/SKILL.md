# FlightCheck Skill

Setup diagnostics for ESS makers. The maker workspace and standalone command
use the same CLI, selected target, scopes and structured result contract.
DA full checks inspect selected-agent configuration; local-only checks remain
an explicit option and never substitute for a requested full run.
Legacy/custom-engine scopes retain their broader environment checks.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## Start

The calling prompt applies the **FlightCheck entry contract** in
`.github/copilot-instructions.md`. When this skill is invoked directly, apply
that contract before continuing.

Continue with this skill for the contract's **Standalone FlightCheck**,
**Canonical setup ready**, and **Selected DA diagnostics** states. The contract
owns the maker interaction and next route for its other states. A selected DA
does not need completed connection readiness before running read-only
diagnostics; do not send it to setup merely because `connect_ready` is false.

Resolve the exact selected agent and its release line. DA `full` uses maker
setup diagnostics whether or not `dataverseEndpoint` is present. Do not switch
a hybrid DA to legacy full checks. A missing/ambiguous selection must be
resolved before continuing; never borrow a sibling's identity.

For a native no-Dataverse agent, supported scopes are `full`, `environment`,
`servicenow`, `workday`, `local`, and `infrastructure`.
DA `workday` and `servicenow` use the same selected-agent diagnostic producers
as full, restricted to the requested provider plus required prerequisites.
Other narrow scopes retain their existing behavior.
Honor the requested scope identically in the maker workspace and standalone
command. Invocation source identifies the caller, not different check coverage
or elevated permissions. With the same target, scope, permissions and evidence,
findings must agree; execution timestamps and durations can differ.

An explicit `--workday-app-id` overrides the saved Workday application selection
for this run only; it does not update workspace configuration. An explicit
`--environment-url` must match the selected environment's verified Dataverse
web or API root. An equivalent alias is allowed, not a different target.

---

## Step 1: Ask scope (optional)

### Focused Workday litmus request

If the maker requests `WD-RUN-001`, `/flightcheck WD-RUN-001`,
`/flightcheck wd litmus test`, or the Workday litmus test by name, skip the
scope picker and runtime-probe consent. Resolve the same exact selected DA
and run the existing checkpoint command, not the Workday scope or full suite:

```powershell
python scripts/flightcheck/cli.py --checkpoint WD-RUN-001 --agent-slug {AGENT_SLUG} --invocation-source adk --select-targets never --output workspace/flightcheck/workday-litmus
```

The separate folder preserves the full-suite report. Let the CLI open its
report once; do not open another browser tab. Its focused HTML shows only the
requested finding, while necessary prerequisite results remain in technical
details and the original JSON. Present any prerequisite blocker rather than
hiding it. Keep the same selected target for subsequent reruns.

For a DA litmus Manual finding, display the recorded
`evidence.manualVerificationSteps` in order and
`evidence.ifMissingOrIncorrect` as the exception guidance. These are the
code-defined customer instructions from `checks/da_validation.py`, shared with
the report. Preserve their wording, selected agent/environment names, sample
question and rerun instruction; do not generate or paraphrase another procedure.
Keep the Copilot Studio Test-pane question separate from the VS Code rerun.
Wait for the answer/completion before rerunning this checkpoint. Do not
automatically trigger a flow, enable scenarios, collect employee answers or
ask the maker to repeat prompts when history access is denied. If a run is
in progress, wait; if a confirmed failure is reported, follow that failure's
remediation first. Rerun only when the maker requests it or confirms completion.

At least one recent scoreable agent-facing success satisfies this passive
litmus; a top-level flow Succeeded is not enough and mixed failures remain
visible. It does not prove the maker's specific prompt, every scenario or
published employee success. Do not invoke the legacy Step 3d loop for a
diagnostic-only DA result. Other named-check aliases are not introduced here.

### Scope selection

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Scope",
    "question": "What would you like to check?",
    "options": [
      { "label": "Full check", "description": "Selected-agent setup for DA; comprehensive environment checks for legacy agents", "recommended": true },
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

For DA, omit "Prerequisites only" and describe Workday/ServiceNow choices as
connection and configuration checks, not legacy SOAP tests or templates.
If the maker already requested a scope, use it without asking again.
DA full checks exact-agent access/content,
ESS identity, environment metadata, conversation activation, instructions,
sign-in configuration, used connection bindings and applicable local setup.
The shared registry also includes tenant SKU/role observations, exact
environment capacity/billing/DLP, knowledge/access and manual QA/publishing
guidance. Attempt supported delegated reads; denied access or an unsupported
observation gets scoped Manual steps, while malformed data and unexpected
auth/service errors stay Errors. Inventory observations never prove
intended-user entitlement or current employee success.
Workday and ServiceNow are optional. Report enabled, disabled, configured
without active use, not configured and uncertain discovery distinctly.
Check enabled integrations' exact bindings and any invoked ServiceNow flows;
do not require legacy ServiceNow templates for native direct connector actions.
Run OOB Workday package/runtime checks only for enabled reviewed OOB topics,
not an arbitrary custom Workday connector. Disabled or unconfigured integrations
do not create defects or compulsory manual reviews.
They do not collect release approvals or submitted employee test evidence.
Native ServiceNow action checks cover employee-delegated authentication,
HRSD/ITSM setup/system topics and portal record links without requiring legacy
flows/templates. Knowledge-ingestion authentication and source ACLs are separate.
SharePoint filtering and Hub/connected-agent setup are optional: unknown
applicability gets conditional Manual guidance, not mandatory setup or an
assumed absence. Evaluation and publishing guidance distinguishes test-case
quality, completed agent evaluation, unpublished maker validation, catalog
approval/audience and published non-maker use in Microsoft 365 Copilot Chat.
Skills that need selected validations reference registered checkpoint IDs or
profiles through the CLI and consume structured JSON. Full discovers eligible
definitions automatically. Do not duplicate check logic in a skill or turn a
Manual result into Passed. Native-selected profiles share the producers while
retaining the existing Connect aggregate contract.
Dependency reads use the maker's access; inability to
inspect a resource is an explicit limitation, not proof that setup is broken.

---

## Step 1.5: Select the integration target (only when there is a choice)

A tenant can have **more than one** Workday Entra SSO enterprise app
(dev / test / prod, demos, trials) or more than one ServiceNow connection.
When that happens, checks like `WD-CONN-102` would otherwise validate *all*
of them together and a healthy prod app could be masked by an unrelated
sandbox app. This step lets the user pin the one they are verifying.

**Only run this step for scopes that touch those integrations:**
- DA full, Workday, ServiceNow, or local-only → **skip this step**; dependencies come from the exact selected
  agent, not Graph SSO-app discovery or unrelated connection candidates
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
and never writes to the tenant. Selected-DA diagnostics return **Manual** when
no scoreable recent response is available; use the focused Workday litmus
instructions above. Only legacy results use **NotConfigured** and the
**WD-RUN-001 user-assisted run** loop in Step 3. So this
gate is about INFRA-003 only.

**This gate applies only when INFRA-003 runs its mutating probe: scope `full`.**
For `workday`, `workdayextension`, ServiceNow-only, Local-files-only, or
Prerequisites-only scopes, skip this gate and go straight to Step 2b.

For DA full, skip this gate even when Dataverse is configured. Never append
`--runtime-reachability` or an import probe: the DA maker diagnostic is read-only.
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

**Message:**

Running setup checks — this takes 1–3 minutes depending on scope...

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

`cli.py` automatically opens `report.html` from the executed run's output
directory (normally `workspace/flightcheck`)
in the user's default browser when it finishes. **Do not open it yourself** — a
second `webbrowser.open` / `Start-Process` would launch a duplicate tab pointing
at the same file. If the report does not appear (Codespaces, headless box, or
the user passed `--no-open`), tell them to open it manually from the file
explorer rather than spawning another tab from this skill.

---

## Step 3: Read results and present findings

Read `results.json` from the executed run's output directory and link
`report.html` in that same directory. Use the command's `--output` value,
or the CLI default `workspace/flightcheck` when omitted. The focused litmus
command above uses `workspace/flightcheck/workday-litmus`; never substitute
an older full-suite JSON or report. Call this directory `{OUTPUT_DIRECTORY}`
in the presentation below.

For a DA result with `diagnostic_only: true`, present the actual diagnostic
outcome: setup checks passed, completed with notes, issues found, or some checks
could not run. Show confirmed problems separately from inaccessible/inconclusive
checks, with a compact area/finding/next-step/owner table and a passed count.
Explain local-only versus deployed inspection and link the generated HTML.
Keep portal suggestions and unperformed employee scenarios visibly unverified.
Use customer-facing category names: combine Workday implementation-module
labels into Workday, while preserving checkpoint IDs. Present each check's
purpose, recorded status and status-specific next step. Group applicable
portal-only and explicit administrator-verification items under Manual
verification with the responsible person, detailed steps and what to do if
the setting is missing or incorrect. Manual means unverified by automation,
not Passed or a confirmed defect; do not collect completion forms.
Do not translate the verdict to READY/NOT_READY, request attestations/review JSON,
claim release approval, or automatically change tenant configuration. Stop after
this summary unless the maker explicitly requests a repair.

For other results, retain the following legacy presentation:

Read `{OUTPUT_DIRECTORY}/results.json` and format the output below **yourself,
directly in your chat reply**. You MUST follow this exact format every time. Do
not improvise, add prose between sections, or skip any section.

**Do NOT write or run any code to render these results.** Read the JSON with your
file-reading tool and type the markdown tables inline. Never author a helper
script (`.py`, `.js`, `.ps1`, a shell one-liner, etc.) to parse `results.json`,
build the tables, or print the summary, and never execute one. The values you
need (counts, `overall`, `duration_secs`, and each object in the `results` array)
are already in the JSON — transcribe them into the tables below by hand. Writing
a script here is a bug: it dumps raw terminal output into chat instead of the
clean formatted result, and it exposes internal process the user should never
see. If the file is large, read it in ranges — do not shortcut it with code.

### 3a — Summary banner

Always show this first:

```
{VERDICT_EMOJI} **{VERDICT_TEXT}**

| | Count |
|---|---|
| ✅ Passed | {passed} |
| ❌ Failed | {failed} |
| ⚠️ Warnings | {warnings} |
| ℹ️ Not Configured | {not_configured} |
| **Total** | **{total}** |

*Completed in {duration_secs}s — [View full report]({OUTPUT_DIRECTORY}/report.html)*
```

Where VERDICT_EMOJI and VERDICT_TEXT are:
- READY → ✅ and "Your agent is ready for deployment"
- READY_WITH_WARNINGS → ⚠️ and "Ready with warnings"
- NOT_READY → ❌ and "Issues found — not ready for deployment"

### 3b — Detailed results table

Show ALL results from the JSON — not just failures. This mirrors the
HTML report exactly. One row per result. Sort by: Failed first, then
Warning, then NotConfigured, then Passed.

```
| Checkpoint | Category | Priority | Status | Result | Remediation |
|---|---|---|---|---|---|
| {checkpoint_id} | {category} | {priority} | {status_emoji} {status} | {result} | {remediation or "—"} |
| ... | | | | | |
```

Status emoji mapping:
- Passed → ✅
- Failed → ❌
- Warning → ⚠️
- NotConfigured → ℹ️
- Skipped → ⏭️
- Error → 💥

### 3c — Offer to fix

After the table, analyze the failed and warning results and build a list
of things you CAN fix automatically vs. things that need manual action.

**Auto-fixable** (offer to do these right now):
- Compile errors in topics → run `/scan` skill
- Missing Workday connection → run `/connect` skill
- Workday env vars not set → run `/connect workday` skill
- Workday connections in Error state → run `/connect workday` skill
- Disabled Workday/ServiceNow flows → enable via Dataverse MCP

**Needs manual action** (the Remediation column already contains direct links):
- License issues → links to M365 admin center
- Agent instructions/starter prompts/topics → links to Copilot Studio
- DLP policies → links to Power Platform admin center
- Publishing items → links to deployment docs

The Remediation column in the detailed results table already contains these
links. Do NOT repeat them in a separate list. Instead, after the table, just
show the auto-fixable offer (if any) and a brief note about manual items.

**If overall is "READY":**

Show:

```
No action needed. Run `/flightcheck` again anytime before publishing.
```

Stop here.

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

Then present the new results using the same format (3a → 3b → 3c).

**If they say no**, show:

```
No problem. Run `/flightcheck` again after making fixes.
```

**If there are NO auto-fixable issues (only manual):**

Show:

```
The issues above need manual action — follow the links in the Remediation column.

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

Then present the new results using the same format (3a → 3b → 3c). If WD-RUN-001
is now ✅ Passed, the end-to-end path works. If it still comes back NotConfigured,
the run likely landed outside the 60-minute window or did not reach Workday — ask
the user to retry the safe question and re-run right after.
