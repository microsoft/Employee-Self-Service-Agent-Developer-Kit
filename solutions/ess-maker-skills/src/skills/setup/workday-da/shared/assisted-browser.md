<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Assisted browser session protocol

Use the browser companion only when a phase guide explicitly offers it. The companion is an optional local assistance surface around an existing manual workflow.

The companion may:

- launch an isolated Edge InPrivate window with one application tab and one loopback companion tab;
- reuse a helper-owned active session for the same lifecycle;
- open a named application surface defined by the helper;
- render constrained text, fields, steps, actions, confirmations, and manual-entry controls;
- inspect bounded visible-page evidence after the human authorizes the named operation;
- follow an already-inspected visible Entra link when the destination remains on `https://entra.microsoft.com`;
- fill an already-inspected visible search or filter input;
- capture one bounded contextual screenshot around an inspected visible target;
- scroll an inspected target into view and show its approximate position in the companion rail;
- wait for revision-bound action, entry, or confirmation decisions;
- close the exact helper-owned browser and loopback server when assistance ends.

Use text nodes only. Never render HTML supplied by a browser page, worksheet response, or user.

The following operations are allowed only when the phase-specific companion guide requires them and the stated preconditions are satisfied:

- Attach to an existing CDP browser only after its ownership and intended target have been verified. Prefer a helper-launched isolated browser.
- Activate a row-specific **Edit** control only to reveal already-existing values. The current companion view must name that exact control and disclose that it will be opened. Do not change or save anything.
- Request manual entry only after bounded inspection cannot reliably collect or disambiguate the required non-secret value.
- Use **Navigate and capture** only when the phase-specific guide permits a visible value to become a companion candidate. Otherwise use **Navigate only**.

When a loosely sanctioned operation cannot satisfy every precondition, fall back to written manual guidance.

The companion must not:

- authenticate, select an account, choose an application, or resolve an ambiguous target for the human;
- automate Edge Split Screen or other browser chrome;
- click **Create**, **Manage**, **Save**, **Apply**, **Allow**, **Grant admin consent**, **Delete**, **Deactivate**, **Add**, **New**, sign-in, consent, or assignment controls;
- submit a portal form, select a modifying result, change a setting, upload a certificate, or transfer certificate contents;
- execute arbitrary JavaScript, selectors, URLs, or actions supplied through a companion view;

## Start the session

From the kit workspace root, launch the surface named by the phase-specific guide:

```powershell
python scripts/workday_assisted_browser.py start --surface "{SURFACE}" --launch
```

The helper opens the application and companion as two tabs in one isolated Edge window. Tell the human what opened. The human may arrange those tabs side by side. Do not claim Split Screen is active unless `inspect-layout` reports `splitScreenReady: true`.

```powershell
python scripts/workday_assisted_browser.py inspect-layout
```

If side-by-side layout is unavailable, the companion may remain in its own tab. If the helper cannot prepare a usable session, return to the phase's existing manual interaction without changing lifecycle state.

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

## Use bounded browser operations

After the named row is authorized, the phase-specific guide may use:

```powershell
python scripts/workday_assisted_browser.py inspect --operation "{OPERATION}" --selector "{SELECTOR}" --limit 20
python scripts/workday_assisted_browser.py follow --operation "{OPERATION}" --selector "{SELECTOR}" --frame-index {FRAME} --match-index {MATCH}
python scripts/workday_assisted_browser.py capture --operation "{OPERATION}" --selector "{SELECTOR}" --frame-index {FRAME} --match-index {MATCH}
python scripts/workday_assisted_browser.py fill-search --operation "{OPERATION}" --selector "{SELECTOR}" --frame-index {FRAME} --match-index {MATCH} --value "{VALUE}"
python scripts/workday_assisted_browser.py point --operation "{OPERATION}" --selector "{SELECTOR}" --frame-index {FRAME} --match-index {MATCH}
python scripts/workday_assisted_browser.py point-targets --operation "{OPERATION}" --targets-file "{TARGETS_FILE}"
python scripts/workday_assisted_browser.py reveal --operation "{OPERATION}" --selector "{SELECTOR}" --frame-index {FRAME} --match-index {MATCH}
```

Selectors and match indexes are fresh evidence, not durable portal contracts. Re-inspect after navigation. Do not broaden the operation when a selector misses or the page is ambiguous.

## End or cancel assistance

Stop the session when the phase-specific guide returns its assistance result, the human cancels assistance, the browser becomes unusable, or the lifecycle stops:

```powershell
python scripts/workday_assisted_browser.py stop
```

If the helper launched Edge, `stop` closes that exact browser and verifies that its CDP endpoint stopped. An explicitly attached user-owned browser remains open.

Cancellation returns control to the phase's existing manual interaction. It does not invalidate manually entered values or write a controller event.
