<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Assisted browser handoffs

Use the split-screen companion only for the native DA Workday lifecycle's browser-owned actions. `scripts/workday_connect.py` remains the sole lifecycle authority. The companion is ephemeral guidance, render evidence, and a row-scoped authorization and candidate-confirmation surface; it is not a lifecycle approval surface or completion record. The maker or responsible administrator remains the human operator for the current phase.

## Safety boundary

- The companion may navigate an isolated Edge application pane to one of the script's named surfaces and render constrained guidance beside it.
- The helper may inspect page URLs, target identity, visibility, viewport size, and shared Edge window identity through CDP. It may navigate and collect a portal value only when the current companion view names a supported fixed operation and the human selects its authorization button. After the session presents a candidate, the human confirms it or requests another search in the companion.
- After row authorization, the helper may capture one bounded contextual screenshot around an already-inspected visible control and show it in the companion.
- Never use browser automation to select an account, application, or connection; click **Create**, **Manage**, **Save**, **Allow**, **Grant admin consent**, consent, or sign-in controls; send a Test-pane prompt; or interpret a browser click as lifecycle completion. The form-fill exception is an already-inspected visible search/filter input.
- The maker or responsible administrator owns every portal mutation, authentication step, consent decision, application or connection selection, certificate transfer, parameter-sharing change, topic visibility confirmation, and Test-pane interaction.
- Verify outcomes through the existing controller command for the phase. Companion `status` proves only that guidance was rendered and visible.
- Do not include passwords, secrets, access tokens, cookies, certificate bodies, or other sensitive values in a companion view.
- Split Screen pairing is a maker action. The helper must not automate Edge browser chrome.

## Start and pair

From the kit workspace root, start the exact named surface:

```powershell
python scripts/workday_assisted_browser.py start --surface "{SURFACE}" --launch
```

The helper reuses `cdp_driver.py` to launch the application and companion as two tabs in one Edge InPrivate window with a dedicated profile and CDP port. It must not create the companion through a normal-profile browser context after launch. If this lifecycle already has an active assisted session, it reuses that session. Never attach to a pre-existing CDP browser unless its ownership has been verified; only then pass `--attach-existing`.

Tell the maker that the application and Connect Workday guide opened as two tabs in the isolated Edge window. Ask them to pair those two tabs using Edge Split Screen, such as **Ctrl+Shift+2**, and return when both panes are visible. Then run:

```powershell
python scripts/workday_assisted_browser.py inspect-layout
```

Continue with companion guidance only when `splitScreenReady` is `true`. If pairing is unavailable, state that the side-by-side guide could not be prepared and continue with the existing chat guidance. Do not claim that the pages are paired from tab creation alone.

## Present guidance

Write one constrained view to `.local/connect/workday-da/assisted-view.json`, then present it:

```powershell
python scripts/workday_assisted_browser.py present --view-file ".local\connect\workday-da\assisted-view.json"
python scripts/workday_assisted_browser.py status
```

The view contract is:

```json
{
  "schemaVersion": 1,
  "phase": "Connections",
  "title": "Create the Workday connection",
  "status": "waiting",
  "summary": "Use the values shown here in the application pane.",
  "steps": ["Complete one maker-owned step."],
  "fields": [{ "label": "Field", "value": "Non-secret value" }],
  "waitingFor": "Return to chat after the application shows Connected."
}
```

The companion prohibits remote-state modification in every assistance mode and also prohibits sign-in. It must not activate Save, Apply, consent, Delete, Deactivate, Add, New, registration, assignment, permission-granting, or other mutation controls. It must not submit a form, select a result with a modifying effect, change a setting, or invoke an arbitrary button.

Only these fields are allowed. A view may additionally contain one interaction: a bounded `action` with a supported `operation` and human-readable `label`, a `confirmation` with a supported `operation`, prompt, confirm label, and reject label, or a conditional `entry` with a supported operation and text-field labels. Do not combine interactions in one view. The renderer uses text nodes and does not accept HTML, links, scripts, arbitrary URLs, selectors, actions, or styling. Before saying the guide is visible, require `connected: true`, `visible: true`, and `renderedRevision` equal to `revision`.

Use `action` to request row-scoped browser authorization. Label navigation-first actions **Navigate only**:

```json
{
  "action": {
    "label": "Navigate only",
    "operation": "entra-reply-url"
  }
}
```

Both modes may perform bounded visible-page reads for the active worksheet row. **Navigate only** uses those reads to locate controls and values, guide the administrator, position arrows, and support manual comparison, but it does not convert a read value into a worksheet candidate automatically. **Navigate and capture** may additionally collect a visible value as a row-scoped candidate and present that candidate for the administrator's one recording confirmation.

After publishing an action, confirmation, or manual-entry view, immediately run `workday_assisted_browser.py wait` for that operation, interaction type, and published revision. Keep the session turn active until the administrator responds or the bounded wait times out. Continue from the returned interaction result without requiring the administrator to send a separate chat message. The wait operation observes companion state only; it does not select an action, decide a confirmation, or submit a value.

After a row confirmation is accepted by its controller operation, immediately present the next outstanding worksheet row and start its bounded wait. Do not return to chat between rows merely to announce completion.

After the final row is controller-accepted and no Entra fields remain outstanding, build the final return worksheet and a companion review view from the same accumulated safe values. The review view must show every labeled worksheet value that will be submitted, including the confirmation outcomes, and use the dedicated `entra-final-worksheet` confirmation operation. Do not include object IDs, scope GUIDs, tenant IDs, certificate contents, tokens, credentials, or values that are not part of the return worksheet.

Use the title **Review final Microsoft Entra worksheet**, the confirmation prompt **Do these final worksheet values accurately reflect the completed Microsoft Entra setup?**, the confirm label **Confirm and submit worksheet**, and the reject label **Review worksheet rows**. Immediately wait for the final confirmation revision:

```powershell
python scripts/workday_assisted_browser.py wait `
  --operation entra-final-worksheet `
  --interaction confirmation `
  --revision {revision}
```

Only after the result is `confirmed` may the session submit that exact worksheet through `record-entra`. A rejected final review blocks forwarding. Reopen the affected worksheet rows, update both the accumulated evidence and final worksheet, and present a new final review revision. The final confirmation is a submission review, not lifecycle completion; verify controller acceptance before reporting that the handoff is complete.

After navigation, try bounded live inspection before asking the administrator to transcribe anything. Only when the value cannot be collected or disambiguated reliably may the next revision contain a manual `entry` for the same already-authorized operation:

```json
{
  "entry": {
    "operation": "entra-certificate-thumbprint",
    "label": "Certificate thumbprint",
    "placeholder": "Paste the active certificate thumbprint",
    "submitLabel": "Submit worksheet value"
  }
}
```

The server rejects manual entry unless **Navigate only** already authorized that exact row. **Submit worksheet value** is the human's one recording decision for a manually entered row; do not present a second confirmation. Pass the submitted value to the controller and reopen the entry only if controller validation rejects it.

After live inspection establishes one candidate, replace the action with a companion confirmation:

```json
{
  "confirmation": {
    "operation": "entra-reply-url",
    "prompt": "Is this the Reply URL intended for this Workday tenant?",
    "confirmLabel": "Confirm Reply URL",
    "rejectLabel": "Search again"
  }
}
```

Read `status.confirmation`. Record the row only when its status is `confirmed`. A `rejected` decision means the candidate was wrong, not that the worksheet row failed; the existing row authorization remains active so the session can inspect again and present a new candidate.

The current Entra worksheet proof of concept supports these row-scoped
operations:

```json
{
  "Directory name": "entra-directory-display-name",
  "Enterprise application": "entra-enterprise-application-display-name",
  "Application ID": "entra-application-id",
  "Selected Reply URL": "entra-reply-url",
  "NameID source": "entra-name-id-source",
  "SAML signing": "entra-saml-signing-option",
  "Certificate thumbprint": "entra-certificate-thumbprint",
  "Certificate expiration date": "entra-certificate-expiration",
  "SAML configuration": "entra-saml-configuration"
}
```

The final worksheet review uses `entra-final-worksheet` only as a confirmation operation. It cannot authorize navigation, inspection, capture, search filling, pointing, reveal actions, or manual entry.

For Directory name, the button authorizes navigation to Microsoft Entra ID Overview. For Enterprise application, it authorizes navigation to the Enterprise applications list. Application ID reuses the exact application pane reached during the preceding collaboration and authorizes continued reads without changing the page. Selected Reply URL, NameID source, and SAML signing continue from that exact application into its SAML surfaces. Read `status` and require `collection.status: authorized` with the expected `worksheetField` before inspecting.

Use the live inspection operation as the bot-test probe uses candidate-selector evidence:

```powershell
python scripts/workday_assisted_browser.py inspect `
  --operation entra-directory-display-name `
  --selector "label" `
  --limit 20
```

An initial selector is a heuristic, not a source of truth. Inspect the returned frame list, match counts, visible text, parent text, roles, and accessible labels. Adapt the next selector from that live evidence. A selector miss or ambiguity does not revoke the human's row-scoped authorization; continue bounded Playwright reads until the row is resolved or return the uncertainty to the human. Do not accept or execute arbitrary JavaScript, mutate the page, inspect another tab, or broaden beyond the authorized worksheet row.

When inspection identifies a visible Entra link that advances the authorized row, follow that exact inspected match:

```powershell
python scripts/workday_assisted_browser.py follow `
  --operation entra-enterprise-application-display-name `
  --selector "{selector from live evidence}" `
  --frame-index {frame-index} `
  --match-index {match-index}
```

`follow` accepts only a visible `<a>` and only when its resolved destination remains on `https://entra.microsoft.com`. It cannot click a button, submit a form, or follow another origin. Re-inspect after navigation; selectors and frame indexes are fresh evidence, not durable identities.

When written directions are not enough, capture context around the exact inspected visible control:

```powershell
python scripts/workday_assisted_browser.py capture `
  --operation entra-saml-signing-option `
  --selector "{selector from live evidence}" `
  --frame-index {frame-index} `
  --match-index {match-index}
```

`capture` does not activate the control. It takes a bounded viewport crop around the inspected match and makes that image available through the companion's separate **Show me what to click** button. Do not display the screenshot automatically. Present written directions with the optional screenshot because portal layout may change and the image is evidence, not a durable selector contract.

When navigation reaches a list with an inspected visible search box, fill the filter without asking the administrator to type it:

```powershell
python scripts/workday_assisted_browser.py fill-search `
  --operation entra-certificate-thumbprint `
  --selector "{selector from live evidence}" `
  --frame-index {frame-index} `
  --match-index {match-index} `
  --value "Workday"
```

`fill-search` works generically across all supported worksheet operations and portal lists after either **Navigate only** or **Navigate and capture**. It accepts a visible `<input>` whose role or accessible description identifies it as search/filter. It fills but does not submit a form, select a result, or activate a portal control.

**Navigate only** may inspect visible-page evidence, including worksheet-value elements, to locate targets and support administrator comparison. It may fill search/filter inputs, show a contextual screenshot, scroll and point to inspected targets, and follow a visible inspected link. A read does not attest to or record a worksheet value.

The sole modification-control exception is a row-specific **Edit** click used only to reveal values that the portal gates or hides behind that control before the row's own confirmation. The row's manual instructions determine the Edit control, and the current companion action must display a disclaimer naming that exact Edit control and stating that navigation includes clicking it only to display the row's values. The exception does not authorize changing, saving, applying, or confirming any value. Arbitrary Edit controls are still prohibited.

When the session has an inspected target that the administrator must use, scroll that target once in the application pane and publish its position to the companion rail:

```powershell
python scripts/workday_assisted_browser.py point `
  --operation entra-certificate-thumbprint `
  --selector "{selector from live evidence}" `
  --frame-index {frame-index} `
  --match-index {match-index}
```

`point` uses fixed helper logic to call `scrollIntoView` on the inspected target, preferring vertical centering and respecting reduced-motion settings. It maps the resulting application viewport position into the companion's dedicated left rail. The rail persistently shows only the approved `←` icon; guidance text appears only while the arrow is hovered, keyboard-focused, or tapped. If the target cannot be centered, the tooltip says it is visible but approximately positioned. Polling must not repeat the scroll or reconstruct the pointer.

Navigation may activate a row-specific **Edit** control only under the disclosed value-reveal exception above. Then use:

```powershell
python scripts/workday_assisted_browser.py reveal `
  --operation entra-saml-configuration `
  --selector "[aria-label='Edit basic SAML configuration']" `
  --frame-index 0 `
  --match-index 0
```

`reveal` accepts an inspected Edit button only when the active row's manual instructions and companion disclaimer name that exact control. It cannot activate Save, Apply, consent, sign-in, or an arbitrary Edit control. Opening the display panel does not attest, record, or modify a worksheet value.

Revealing a panel clears pointers for the pre-navigation control because their viewport positions are now stale. After navigation finishes, inspect each visible post-navigation value target and call `point` again so the rail tracks the values the administrator should use. Point to the value control rather than its section heading. Use `--append` after the first target to retain one arrow per additional value. Do not preserve or reuse coordinates from before the navigation.

For every worksheet row, determine whether the administrator must compare more than one application target. When multiple targets are present, publish them together with `point-targets` instead of sequential `point --append` calls. The batch operation positions the combined target range once and atomically replaces the rail pointers, preventing later scrolling from making earlier arrows stale.

The collaborating session interprets the visible evidence and shows each candidate value to the administrator in a companion confirmation. State that confirmation records the non-secret candidate in the worksheet and does not modify Entra. Use a button label such as **Record worksheet value**, not **Use this value**. For Directory name, pair the value with the controller Tenant ID. For Enterprise application and Application ID, never choose by display name alone: establish that the selected application is the exact Workday application using the packet's Service Provider ID and that the enterprise application and app registration share the same Application ID. Only after `status.confirmation.status` is `confirmed` may the session pass that row through `record-administrator-evidence`. Do not ask for the same authorization or confirmation again in chat while the companion is active. Inspection evidence and companion decisions are not lifecycle completion. Never invoke the action or confirmation endpoint on the maker's behalf.

## Move between bounded surfaces

Navigate only the existing application pane:

```powershell
python scripts/workday_assisted_browser.py open --surface "{SURFACE}"
```

Supported surfaces are:

- `entra-configuration`
- `dataverse-connection`
- `workday-connection`
- `agent-connections`
- `workday-topics`
- `maker-validation`

The Entra surface opens the Microsoft Entra admin center without selecting a directory or application. The two connection surfaces resolve the environment and service ring from the authoritative Workday controller state. The remaining surfaces open the exact recorded agent in Copilot Studio. Do not construct a different environment or agent URL. The human operator must verify the displayed directory and select the exact application using the packet's identity rules.

## Stop

When the browser-owned step is complete, the maker defers it, or the lifecycle stops:

```powershell
python scripts/workday_assisted_browser.py stop
```

This stops the loopback companion and removes its ephemeral session metadata. When the helper launched Edge, it also closes that exact CDP-enabled browser and verifies that the debugging endpoint stopped before discarding ownership metadata. When the maker explicitly supplied an existing browser with `--attach-existing`, that user-owned browser remains open.
