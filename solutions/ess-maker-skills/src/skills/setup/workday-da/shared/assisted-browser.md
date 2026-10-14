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
- capture one bounded contextual screenshot around an inspected visible target when the shared-browser tool surface provides one;
- scroll an inspected target into view and show its approximate position in the companion rail;
- wait for revision-bound action, entry, or confirmation decisions;
- close the companion webview and loopback server when assistance ends.

Use text nodes only. Never render HTML supplied by a browser page, worksheet response, or user.

The following operations are allowed only when the phase-specific companion guide requires them and the stated preconditions are satisfied:

- Use browser tools only on the Integrated Browser page the human opened and explicitly shared with the agent.
- Activate a row-specific **Edit** control only to reveal already-existing values. The current companion view must name that exact control and disclose that it will be opened. Do not change or save anything.
- Request manual entry only after bounded inspection cannot reliably collect or disambiguate the required non-secret value.
- Use **Navigate and capture** only when the phase-specific guide permits a visible value to become a companion candidate. Otherwise use **Navigate only**.

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

The ESS Maker extension detects the workspace-local session file and opens the companion webview. If it does not open automatically, run **Agent Developer Kit: Open Workday setup companion** from the Command Palette.

Tell the human to:

1. open **View** > **Browser**;
2. navigate that user-owned browser page to the returned `applicationUrl`;
3. complete any sign-in or popup interaction themselves;
4. select **Share with Agent** for the application page;
5. keep the application page and companion webview visible beside Copilot Chat.

Do not use an agent-opened private browser page as a substitute. Before browser inspection or navigation, require evidence that the user-opened page is shared and still points at the intended Microsoft Entra surface. If the companion or shared browser cannot be prepared, return to the phase's existing manual interaction without changing lifecycle state.

## Present constrained guidance

Write a view under `.local/connect/workday-da/` and present it:

```powershell
python scripts/workday_assisted_browser.py present --view-file "{VIEW_FILE}"
python scripts/workday_assisted_browser.py status
```

Before claiming the view is ready, require:

- `connected: true`;
- `visible: true` when the human should act immediately;
- `renderedRevision` equal to `revision`.

A view may contain at most one interaction:

- `action` for row-scoped browser authorization;
- `confirmation` for a revision-bound human decision;
- `entry` for a bounded manual fallback.

Publishing a new view invalidates decisions from older revisions. Never invoke an action, entry, or confirmation endpoint on the human's behalf.

## Keep the session turn active

After publishing an interactive view, wait for that exact operation, interaction, and revision:

```powershell
python scripts/workday_assisted_browser.py wait `
  --operation "{OPERATION}" `
  --interaction "{collection|confirmation|entry}" `
  --revision {REVISION}
```

The wait command observes local companion state only. It does not choose an action, enter a value, decide a confirmation, or write lifecycle state.

Continue from the returned result without requiring a duplicate chat message. A timeout leaves the displayed view valid and does not imply rejection.

## Use the shared Integrated Browser

After the named row is authorized:

- use the agent's built-in browser tools as the VS Code implementation of the Edge version's bounded `inspect`, `follow`, `fill-search`, `capture`, `point`, and `reveal` operations;
- navigate to the returned `targetUrl` only when the authorization result supplies one;
- read and inspect the visible page before every click, fill, capture, or candidate decision;
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

After an inspected target is visible, write one or more semantic target positions to a JSON file and publish the same rail arrows used by the Edge implementation:

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
python scripts/workday_assisted_browser.py point-targets `
  --operation "{OPERATION}" `
  --targets-file "{TARGETS_FILE}"
```

When the shared-browser tool surface can save a bounded PNG around that target, publish the same optional **Show me what to click** evidence used by the Edge implementation:

```powershell
python scripts/workday_assisted_browser.py capture `
  --operation "{OPERATION}" `
  --image-file "{PNG_FILE}" `
  --label "{VISIBLE_TARGET_LABEL}"
```

After the authorized browser operation reaches the intended page state, record navigation completion before publishing a manual-entry fallback or moving to another row:

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
