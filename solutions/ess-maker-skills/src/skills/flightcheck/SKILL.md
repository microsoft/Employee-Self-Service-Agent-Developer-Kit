# FlightCheck Skill

Pre-deployment readiness validation for ESS agents. Runs automated checks
against the live environment (licenses, Entra, Power Platform, Workday/
ServiceNow/SAP integrations) and validates extracted agent files on disk.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## Start

Read `.local/setup/config.json` and `.local/config.json`.

Classify the active configuration before choosing a state:

- A config with `releaseLine: "da"` and no `dataverseEndpoint` is a native
  no-Dataverse agent. Its supported scopes are `full`, `environment`,
  `servicenow`, `workday`, `local`, and `infrastructure`.
- A config with `dataverseEndpoint` uses the Dataverse-backed FlightCheck
  scopes, including when its release line is `da`.

Take the first case that applies:

1. **Standalone FlightCheck installation:** local config has
   `flightCheckOnly: true`. Continue at **Step 1** with the scopes supported by
   its configured environment and selected agent. A standalone configuration
   without a selected agent omits the local-files scope; its full run remains
   available and reports agent-specific checks as not configured. Canonical
   authoring setup and a materialized authoring workspace are not prerequisites
   for this mode.
2. **Canonical setup ready:** canonical state has `schema_version: 4` and an
   `agents` entry whose `agent.workspace_slug` matches local config's
   `activeAgent`, whose workspace has both `folder` and `agent_path`, and whose
   `connect_ready` is `true`. Continue at **Step 1**.
3. **Workspace materialized with readiness outstanding:** the matching
   canonical agent has both `workspace.folder` and `workspace.agent_path`, with
   `connect_ready` equal to `false`. Follow **Readiness recovery routing**
   below.
4. **Local agent workspace unavailable:** every other state, including a
   missing canonical agent or missing `workspace.folder` or
   `workspace.agent_path`, shows the following message and finishes the request.

**Message:**

FlightCheck needs a local agent workspace. Run `/setup` to create or resume it,
then run FlightCheck again.

**End message.**

### Readiness recovery routing

Select the path from the maker's request:

- When the maker explicitly requests a full FlightCheck or supplies
  `--scope full`, follow **Full FlightCheck during incomplete DA setup** below.
- When the maker invokes `/flightcheck` without a scope, use
  `vscode_askQuestions`:

  ```json
  [
    {
      "header": "Readiness scope",
      "question": "Your local workspace is ready, but setup readiness still needs attention. What would you like to check?",
      "options": [
        {
          "label": "Recheck setup readiness",
          "description": "Check agent access, environment capacity, connections, and agent content.",
          "recommended": true
        },
        {
          "label": "Run full FlightCheck",
          "description": "Recheck setup readiness, then also validate local agent files and configuration."
        }
      ],
      "allowFreeformInput": false
    }
  ]
  ```

  Follow **DA setup readiness recovery** for the first choice and **Full
  FlightCheck during incomplete DA setup** for the second.
- For other setup or environment readiness requests, follow **DA setup
  readiness recovery**.

### DA setup readiness recovery

Read **Maintain native FlightCheck evidence** in
`src/skills/foundation-setup/da-existing-dev.md` for the checkpoint commands and
maintenance calls. Use the paragraphs beginning **Use the same five rows and
order** and **Use the most consequential current evidence** under **Interpret
results** for the status mapping. Use the active canonical agent ID and
workspace evidence throughout this recovery.

This recovery consists of the four checkpoint commands and their corresponding
`maintain-flightcheck` calls:

1. Run all four setup-owned checkpoints whose prerequisites remain available:
   agent access, environment capacity, native connections, and agent content.
2. For each checkpoint that produced evidence, pass `maintain-flightcheck` the
   `results.json` written by that checkpoint command during this recovery at the
   path defined under **Maintain native FlightCheck evidence**.
3. Render the five-row runtime-readiness table from the fresh evidence.
4. Explain the specific observed blocker and its supported remediation in
   maker-facing language.

For a setup-readiness request, present the runtime-readiness table and complete
the request. The latest maintenance result supplies `connectReady` and
determines canonical runtime readiness.

The FlightCheck response for this path consists of the `### Setup readiness`
section defined at **Step 3a.1**, populated from the fresh maintenance results.

### Full FlightCheck during incomplete DA setup

Run two ordered phases and use the files written by the existing FlightCheck
CLI as the authoritative result documents:

1. Follow **DA setup readiness recovery** steps 1–2 for the active canonical
   agent, including a `maintain-flightcheck` call for every checkpoint that
   produced results.
2. Build the five-row runtime-readiness table and blocker explanation for the
   final combined response.
3. Continue at **Step 1.5** with scope fixed to `full`. Follow the standard
   target-selection and Step 2 consent rules for the active configuration. The
   native no-Dataverse path naturally skips target selection and consent
   because its supported checks are read-only.
4. Present the normal full FlightCheck output and include the retained setup
   table at **Step 3a.1**.

The maintenance phase determines `connect_ready` and may complete canonical
setup readiness. Every full-scope result independently contributes to the
broader FlightCheck verdict, including local-file findings. When a repeated
remote row differs between the two phases, report the newer observation as a
timing difference and recommend refreshing setup readiness.

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
For that native picker, replace the "Full check" description with "Agent
access, environment capacity, connections, agent content, and local files."
For a standalone FlightCheck configuration without a selected agent, omit
"Local files only". Its full scope remains available.

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

The **same** `--runtime-reachability` probe also powers **WD-RUN-001** (the Workday
active connector check): it stands up the same kind of transient flow, makes one
read-only Workday call through the maker's connection, then deletes the flow. So
the consent gate is required whenever **either** mutating probe is in scope.

**This gate applies when the scope runs a mutating probe: `full` (INFRA-003 and
WD-RUN-001), `workday`, or `workdayextension` (WD-RUN-001).** For ServiceNow-only,
Local-files-only, or Prerequisites-only scopes, skip this gate and go straight to
Step 2b.

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
  summary note that the connectivity probe was skipped by choice. The passive
  fallback depends on scope:
  - **Workday scope (WD-RUN-001)** → the check falls back to the **passive
    run-history** signal (recent Workday connector runs on the environment). No
    manual step is required; just note that the active probe was declined.
  - **INFRA-003 (full scope)** → INFRA-003 returns **Manual** guidance. Offer the
    manual verification path:

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

Read `workspace/flightcheck/results.json` and format the output below **yourself,
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

*Completed in {duration_secs}s — [View full report](workspace/flightcheck/report.html)*
```

Where VERDICT_EMOJI and VERDICT_TEXT are:
- READY → ✅ and "Your agent is ready for deployment"
- READY_WITH_WARNINGS → ⚠️ and "Ready with warnings"
- NOT_READY → ❌ and "Issues found — not ready for deployment"

### 3a.1 — Setup readiness after an incomplete-setup full run

For a setup-readiness request, this section is the complete response. When
**Full FlightCheck during incomplete DA setup** retained a fresh
runtime-readiness table, place this section after the summary banner and before
the detailed results table:

```text
### Setup readiness

| Check | Status | Details |
|---|---|---|
| Agent access | {agent access status} | {agent access evidence summary} |
| Environment capacity | {environment capacity status} | {environment capacity evidence summary} |
| Connections | {connections status} | {connections evidence summary} |
| Agent content | {agent content status} | {agent content evidence summary} |
| **Overall** | **{overall readiness status}** | **{maker-facing readiness summary}** |
```

Use the statuses, evidence, row order, and overall interpretation from
`src/skills/foundation-setup/da-existing-dev.md`. Put the retained blocker and
remediation explanation in the applicable Details cell and the Overall
summary. This is the single setup-readiness rendering for the composed path.
Populate it from the canonical setup maintenance results.

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
- Missing Workday/ServiceNow connection → run `/connect` skill
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
