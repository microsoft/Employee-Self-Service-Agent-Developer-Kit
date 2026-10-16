<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Assisted browser session protocol

Use the browser companion only when a phase guide explicitly offers it. The companion is an optional local assistance surface around an existing manual workflow.

The companion may:

- host constrained guidance in the ESS Maker extension's webview;
- provide the bounded application URL for a user-opened VS Code Integrated Browser page;
- reuse an active companion session for the same lifecycle;
- open a named application surface defined by the helper;
- render constrained text, fields, steps, actions, confirmations, and manual-entry controls;
- inspect bounded visible-page evidence after the human authorizes the named operation;
- follow an already-inspected visible Entra link when the destination remains on `https://entra.microsoft.com`;
- fill an already-inspected visible search or filter input;
- attempt one bounded contextual screenshot around an inspected visible target after the human requests visual help;
- scroll an inspected target into view and show its approximate position in the companion rail;
- wait for revision-bound action, entry, confirmation, or visual-help decisions;
- close the companion webview and loopback server when assistance ends.

Use text nodes only. Never render HTML supplied by a browser page, worksheet response, or user.

The following operations are allowed only when the phase-specific companion guide requires them and the stated preconditions are satisfied:

- Use browser tools only on the Integrated Browser page the human opened and explicitly shared with the agent.
- Activate a row-specific **Edit** control only to reveal already-existing values. The current companion view must name that exact control and disclose that it will be opened. Do not change or save anything.
- Request manual entry when the human selected **Navigate only**, or after bounded inspection cannot reliably collect or disambiguate the required non-secret value.
- Use **Navigate and capture** only for a row marked `Sensitive: No` by the phase-specific guide. A row marked `Sensitive: Yes` must use **Navigate only** and must not expose captured text, detected-value confirmation, pointing, or screenshot controls.

When a loosely sanctioned operation cannot satisfy every precondition, fall back to written manual guidance.

The companion must not:

- authenticate, select an account, choose an application, or resolve an ambiguous target for the human;
- open the application page in a private agent-owned browser session;
- automate Integrated Browser chrome, sharing, popup sign-in, or auxiliary windows;
- click **Create**, **Manage**, **Save**, **Apply**, **Allow**, **Grant admin consent**, **Delete**, **Deactivate**, **Add**, **New**, sign-in, consent, or assignment controls;
- submit a portal form, select a modifying result, change a setting, upload a certificate, or transfer certificate contents;
- execute arbitrary JavaScript, selectors, URLs, or actions supplied through a companion view;

## Start the session

From the kit workspace root, start the companion for the surface named by the phase-specific guide:

```powershell
python scripts/workday_assisted_browser.py start --surface "{SURFACE}" --vscode
```

During a companion restart, run `stop` and `start` as separate commands. Read the session status after each start:

```powershell
python scripts/workday_assisted_browser.py status
```

The companion is ready for a view when status reports `running: true` and `surface: "{SURFACE}"`. When a running session has another surface or no surface, run the same `start --surface "{SURFACE}" --vscode` command again and read status again. Present the first view after the requested surface is ready.

The ESS Maker extension detects the workspace-local session file and opens the companion webview. If it does not open automatically, run **Agent Developer Kit: Open Workday setup companion** from the Command Palette.

Tell the human to:

1. open **View** > **Browser**;
2. navigate that user-owned browser page to the returned `applicationUrl`;
3. complete any sign-in or popup interaction themselves;
4. select **Share with Agent** for the application page;
5. keep the application page and companion webview visible beside Copilot Chat.

Do not use an agent-opened private browser page as a substitute. Before browser inspection or navigation, require evidence that the user-opened page is shared and still points at the intended Microsoft Entra surface. If the companion or shared browser cannot be prepared, return to the phase's existing manual interaction without changing lifecycle state.

## Present constrained guidance

Build the current view from the phase guide's canonical JSON template and present it. Prefer standard input so a previous row's view file cannot become workflow state:

```powershell
$view = @'
{CURRENT_VIEW_JSON}
'@
$view | python scripts/workday_assisted_browser.py present --view-file -
python scripts/workday_assisted_browser.py status
```

A workspace-local view file remains available for debugging, but it is only an input payload. Replace the complete payload for each revision rather than patching a previous row and never use it to infer worksheet progress, row authorization, or the next operation.

Before claiming the view is ready, require:

- `connected: true`;
- `visible: true` when the human should act immediately;
- `renderedRevision` equal to `revision`.

A view may contain at most one primary interaction:

- `action` for row-scoped browser authorization;
- `confirmation` for a revision-bound human decision;
- `entry` for a bounded manual fallback.

`visualHelp` is an auxiliary interaction that may accompany a detected-value `confirmation`. It requests a screenshot only after a human click and does not replace or decide the confirmation.

Publishing a new view invalidates decisions from older revisions. Never invoke an action, entry, confirmation, or visual-help endpoint on the human's behalf. Row authorization is held only in the active companion session. Do not create or use a local file as a second authorization record.

## Keep the session turn active

After publishing an interactive view, wait for that exact operation, interaction, and revision:

```powershell
python scripts/workday_assisted_browser.py wait `
  --operation "{OPERATION}" `
  --interaction "{collection|confirmation|entry|visual-help|any}" `
  --revision {REVISION}
```

The wait command observes local companion state only. It does not choose an action, enter a value, decide a confirmation, or write lifecycle state.

Use `--interaction any` when a candidate confirmation also offers visual help. If the result reports `visual-help`, attempt the screenshot and then wait again for `any` so the still-pending confirmation remains actionable. Continue from the returned result without requiring a duplicate chat message. A timeout leaves the displayed view valid and does not imply rejection.

## Use the shared Integrated Browser

After the named row is authorized:

- use the agent's built-in browser tools as the VS Code implementation of the Edge version's bounded `inspect`, `follow`, `fill-search`, `screenshot`, `point-targets`, and `reveal` operations;
- inspect the current shared page first and navigate to a returned `targetUrl` only when the page is not already at the authorized destination;
- read and inspect the visible page before every click, fill, screenshot, or candidate decision;
- keep the operation within the authorized worksheet row and action mode;
- re-inspect after navigation, popup completion, or page refresh;
- leave sign-in, consent, save, assignment, upload, and other mutations to the human.

Browser element references are fresh evidence, not durable portal contracts. Do not broaden the operation when an element is missing or the page is ambiguous. If a popup or auxiliary window contains a human-owned sign-in step, wait for the human to finish it and share the resulting application page if the browser tool no longer sees the intended parent page.

The shared-browser adapter must preserve the Edge companion's interaction model:

- keep the current row authorization active while inspecting, searching, following links, pointing to targets, showing a screenshot, or asking the human to confirm a candidate;
- treat an empty result, missed selector, stale element reference, or rejected candidate as a reason to re-inspect within the same row, not as a reason to end assistance;
- inspect all visible candidates and available result pages that remain within the authorized row before declaring the target unavailable;
- use only exact target facts already supplied by the phase, such as the application display name, Application ID, tenant, or Service Provider ID, when narrowing a search;
- never select an ambiguous application for the human;
- offer the row's existing manual-entry fallback only after bounded inspection cannot reliably collect or disambiguate the value.

For a non-sensitive detected value, publish the confirmation view before calculating pointer geometry. Retain the returned revision. The companion renders the candidate and confirmation immediately while target positioning remains pending:

```json
{
  "visualHelp": {
    "operation": "{OPERATION}",
    "label": "{VISIBLE_TARGET_LABEL}"
  }
}
```

If the phase-specific baseline returned pointer `targets`, retain that exact set in memory and submit it after the confirmation is published. For rows without baseline targets, scroll the current row's inspected targets into view after confirmation and re-inspect all post-scroll geometry in one browser call. Build `positionRatio` from the post-scroll geometry for each target. Set `centered` to `true` when the reinspection shows that centering succeeded. Publish every target required by the current row together:

```json
[
  {
    "label": "{VISIBLE_TARGET_LABEL}",
    "positionRatio": 0.5,
    "centered": true
  }
]
```

```powershell
$targetsJson | python scripts/workday_assisted_browser.py point-targets `
  --operation "{OPERATION}" `
  --revision {CONFIRMATION_REVISION} `
  --targets-file -
```

If geometry inspection fails, report the safe reason through the same revision-bound command:

```powershell
python scripts/workday_assisted_browser.py point-targets `
  --operation "{OPERATION}" `
  --revision {CONFIRMATION_REVISION} `
  --error "{SAFE_REASON}"
```

Pointer failure is non-blocking: the confirmation remains actionable and the companion reports that visual guidance is unavailable. If `point-targets` rejects a stale update because the human already decided the confirmation or a newer revision exists, treat that as normal completion and do not republish the candidate. Wait for the human to select **Show me what to click** only after the pointer set is ready. Only after `wait` reports `interaction: visual-help`, use the browser tool surface to attempt a bounded PNG around the already-pointed target and publish it:

```powershell
python scripts/workday_assisted_browser.py screenshot `
  --operation "{OPERATION}" `
  --image-file "{PNG_FILE}" `
  --label "{VISIBLE_TARGET_LABEL}"
```

If the screenshot attempt fails, report a safe reason and permit retry:

```powershell
python scripts/workday_assisted_browser.py screenshot-result `
  --operation "{OPERATION}" `
  --status failed `
  --error "{SAFE_REASON}"
```

The companion changes the control to **Screenshot unsuccessful** and keeps it actionable. Screenshot failure does not revoke row authorization or decide the candidate confirmation.

After the authorized browser operation reaches the intended page state, record navigation completion before publishing any post-navigation row interaction or moving to another row:

```powershell
python scripts/workday_assisted_browser.py shared-browser-result `
  --operation "{OPERATION}" `
  --status navigated
```

Report `--status failed --error "{SAFE_REASON}"` only when the shared browser itself is unusable or the authorized surface cannot be reached after recovery. A search with no matching candidate is not a browser failure and must not end assistance. Do not mark navigation complete merely because the action was authorized.

## End or cancel assistance

Stop the session when the phase-specific guide returns its assistance result, the human cancels assistance, the browser becomes unusable, or the lifecycle stops:

```powershell
python scripts/workday_assisted_browser.py stop
```

`stop` closes the loopback companion session. The user-owned Integrated Browser page remains open.

Cancellation returns control to the phase's existing manual interaction. It does not invalidate manually entered values or write a controller event.
