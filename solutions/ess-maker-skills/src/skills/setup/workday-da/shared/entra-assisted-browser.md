<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Microsoft Entra worksheet companion

Use this guide only after `provision-entra-app.md` renders the Microsoft Entra administrator handoff and the human selects **Launch browser companion for assistance**. Follow `assisted-browser.md` for the session protocol.

## Session inputs

Use:

- the current `entra-handoff` packet;
- the exact rendered capture table and numbered manual tasks;
- any safe values already present in the current manual worksheet response;
- any customer-facing worksheet labels returned as missing or invalid when resuming a partial response.

The helper stores the in-progress draft only at `.local/connect/workday-da/entra-companion-draft.json`. Do not create, open, or edit this file directly. `worksheet-record` owns its validated atomic updates. The draft is one JSON object whose keys are the exact worksheet row labels from the table below and whose values are the confirmed worksheet text:

```json
{
  "Directory name": "{CONFIRMED_DIRECTORY_NAME}",
  "Enterprise application": "{CONFIRMED_APPLICATION_NAME}"
}
```

The draft stores confirmed worksheet values only. It does not store row authorization, browser references, pointers, screenshots, pending candidates, or interaction status. Do not initialize or infer `Existing configuration`; add that downstream-required row only after the administrator selects one of its two canonical outcomes on the final summary.

## Worksheet operations

A **worksheet row** is one entry in the rendered Microsoft Entra capture table. Its exact label maps to one companion operation and one sensitivity marker. Each row produces one confirmed worksheet value or attestation. A worksheet row is not an HTML table row or another visual element in the Microsoft Entra portal.

| Worksheet row                                        | Companion operation                         | Sensitive |
| ---------------------------------------------------- | ------------------------------------------- | --------- |
| Directory name                                       | `entra-directory-display-name`              | No        |
| Enterprise application                               | `entra-enterprise-application-display-name` | No        |
| Application ID                                       | `entra-application-id`                      | No        |
| Selected Reply URL                                   | `entra-reply-url`                           | No        |
| NameID source                                        | `entra-name-id-source`                      | No        |
| SAML signing                                         | `entra-saml-signing-option`                 | No        |
| Certificate thumbprint (active certificate row)      | `entra-certificate-thumbprint`              | No        |
| Certificate expiration date (active certificate row) | `entra-certificate-expiration`              | No        |
| SAML configuration                                   | `entra-saml-configuration`                  | No        |
| Signing certificate                                  | `entra-signing-certificate-check`           | No        |
| Authorized connector                                 | `entra-authorized-connector`                | No        |
| Permissions and consent                              | `entra-permissions-consent`                 | No        |
| Employee assignment                                  | `entra-employee-assignment`                 | No        |

The `Sensitive` column is authoritative. Never infer sensitivity from the row label, the visible value, or browser capabilities. For `No`, offer both actions with these literal labels:

```json
{
  "actions": [
    {
      "label": "Navigate only",
      "operation": "{OPERATION}",
      "mode": "navigate-only"
    },
    {
      "label": "Navigate and capture",
      "operation": "{OPERATION}",
      "mode": "navigate-and-capture"
    }
  ]
}
```

The companion renders these static explanations below the action group:

- **Navigate only:** Assists without capturing values for ADK. You remain responsible for any authentication.
- **Navigate and capture:** Assists and captures values for ADK. You remain responsible for any authentication.

For any future row marked `Yes`, offer only **Navigate only**. Do not copy the application value, present a detected-value confirmation, call `point-targets`, or offer a screenshot for that row.

`Existing configuration` is not a browser-navigation row. Its operation, `entra-existing-configuration`, is reserved for the final summary, where the administrator selects the downstream preservation outcome after reviewing the 13 collected values.

## Run the worksheet session

Load this guide and `assisted-browser.md` when entering or materially resuming assisted mode. During one uninterrupted worksheet loop, do not reread the root setup skill, phase guide, these shared guides, CLI help, or script source unless a tool reports a contract error that its returned details cannot resolve.

1. Start or reconnect to the `entra-configuration` surface using `assisted-browser.md`. Preserve any existing helper-owned draft values. Record new values only through accepted companion interactions; do not seed the draft by editing its file.
2. Choose the requested worksheet lifecycle:
   - **Resume:** preserve the draft and current companion interaction, then read current progress:

     ```powershell
     python scripts/workday_assisted_browser.py worksheet-status
     ```

     Continue `activeRow` when present. If it has a pending interaction, go directly to the exact `wait`; do not inspect the browser, search files, call `status`, or present a replacement view first. When `preservationAttestation` is present, resume its exact entry wait instead of reopening a browser row.

   - **Reset:** only when the human explicitly asks to restart worksheet value collection, cancel any foreground `wait` using native terminal cancellation, then run:

     ```powershell
     python scripts/workday_assisted_browser.py worksheet-reset
     ```

     This clears only worksheet draft and companion interaction state. It preserves the Workday lifecycle and Entra phase boundary. Use the returned `status`; do not stop and manually delete files.

   Otherwise use `worksheet.nextRow`; `worksheet.recordedRows` lists completed rows and `worksheet.nextOperation` retains the compact operation identifier. If neither an active row nor a next row exists, proceed to the final summary. The projection deliberately omits confirmed values and historical views. Do not reconstruct progress from conversation history, old companion views, temporary view files, or browser snapshots.

3. Use the selected row's exact label, sensitivity marker, and `navigationHints`. These are navigation starting points, not current portal facts. Do not run `navigationHints.baselineScript` before the human chooses an assistance mode. The selected mode determines whether the browser operation may read the worksheet value.
4. For a new row, publish its canonical collection view:

   ```powershell
   python scripts/workday_assisted_browser.py worksheet-present --operation "{OPERATION}" --stage collection
   ```

   Never manually author, patch, or reuse a row view payload. Use the returned revision for every interaction with that view.

5. Wait for the exact operation, interaction, and revision using the `wait` command from `assisted-browser.md`.
6. Perform only the mode selected by the human:
   - execute the row's baseline once before calling `read_page` or otherwise inspecting the current page. The baseline owns the initial URL comparison, direct navigation, readiness waits, target discovery, and structured success or failure result. If it succeeds, publish that result immediately without a page read;
   - after **Navigate only**, when `navigationHints.baselineSupportsNavigateOnly` is `true`, execute the function in `navigationHints.baselineScript` with `{ capture: false }`. This reuses the exact capture route and targeting logic but must return neither a `value` nor `values` field or evidence. Treat any of those as a contract failure and leave the row pending. The Enterprise application Overview operation may return its exact `applicationUrl` as navigation context; retain it for subsequent Entra baselines. When the flag is absent, navigate through read-only portal controls using `startUrl`, `lastKnownUrlTemplate`, `portalPath`, visible landmarks, and the row's observed or fallback hints. Locate the value-bearing page or control for geometry only. The browser result may include pointer `targets`, but it must not read or return the worksheet value through `innerText`, `textContent`, `inputValue`, value-bearing attributes, or equivalent extraction;
   - after **Navigate and capture**, execute `navigationHints.baselineScript` with the built-in code runner from the `Browser Pages` entry for the currently shared VS Code Browser Page. If that code runner accepts a workspace filename, pass the returned path directly. Otherwise read that file once and execute its browser function unchanged. A direct-value success contains the detected worksheet `value` and pointer `targets`. The Enterprise application Overview success instead contains a `values` object with the separate `Enterprise application` and `Application ID` worksheet values plus both pointer `targets`; it also returns the exact `applicationUrl`, which must be retained as navigation input for subsequent Entra baselines. The SAML signing success contains a `values` object with `SAML signing` and `Certificate expiration date (active certificate row)` plus both pointer `targets`. An attestation-row success contains a safe evidence summary and may include pointer `targets` when a specific visible control is part of the attestation. The companion supplies the row's canonical choices from the same contract as the administrator handoff and worksheet parser.

   Only when the first baseline execution fails and its structured result does not provide enough state to choose a safe recovery, call `read_page` and use this bounded observation loop:
   - Observe the current URL, visible landmarks, active blade or frame, loading overlays, target locator count and state, and the filter or tab controlling the visible results.
   - Treat the row's intended destination as the recovery invariant. Use the navigation hints and visible landmarks to resume the same read-only route a human would follow, and finish on the stated value-bearing page or control.
   - Select the smallest adjustment supported by that observation that advances or stabilizes the intended route, such as waiting for attachment, waiting for an overlay to clear, selecting the matching frame, refining a selector on the destination page, applying the expected filter, or resuming from the current route landmark.
   - Re-execute the same baseline after the bounded adjustment. Repeat observation, adjustment, and baseline execution only while the browser-operation budget remains.
   - On success, keep the target visible while publishing the canonical row interaction and its pointer targets.
   - At the end of the operation budget, report the final `failedAt`, observed page state, and attempted adjustments through `shared-browser-result --operation "{OPERATION}" --status failed --error "{SAFE_REASON}"`. The worksheet row remains pending.

7. Report successful navigation and publish the canonical post-navigation interaction in one terminal call. This shared ordering prevents either mode from presenting a row interaction before its browser work is complete.

   For **Navigate only**:

   ```powershell
   python scripts/workday_assisted_browser.py worksheet-browser-complete --operation "{OPERATION}"
   ```

   Direct-value rows render text entry with the manual table's **What to record** instruction. The Enterprise application Overview operation renders two inputs and submits the application name and Application ID together. The SAML signing operation renders two inputs and submits the signing option and active certificate expiration together. Single-choice attestation rows render confirmation with their canonical worksheet response.

   For **Navigate and capture**, use the successful baseline result for the current worksheet row. For a direct-value row, pipe only its detected worksheet `value` through stdin so it does not enter command history. For an attestation row, pipe only the safe baseline evidence summary:

   ```powershell
   $detectedValue | python scripts/workday_assisted_browser.py worksheet-browser-complete --operation "{OPERATION}" --value-file - --target-label "{VISIBLE_TARGET_LABEL}"
   ```

   For the Enterprise application Overview and SAML signing operations, serialize only the returned `values` object as JSON and pipe that JSON through `--value-file -` instead of `$detectedValue`.

   `worksheet-browser-complete` validates the authorized mode, records navigation completion, and publishes the matching entry or confirmation in one bounded companion transition. For either mode, read its returned `interaction` and revision instead of assuming the interaction type. If navigation is recorded but presentation fails, the command reports that partial outcome explicitly; retry the same command to publish the interaction without repeating browser navigation. Navigate and capture renders a detected-value confirmation for direct-value rows or the shared instruction and canonical worksheet response for single-choice attestations. Capture evidence renders separately from the worksheet response.

   When the successful browser operation returned `targets`, retain that exact target set in memory and pipe the complete set directly to one revision-bound `point-targets` call:

   ```powershell
   $targetsJson | python scripts/workday_assisted_browser.py point-targets --operation "{OPERATION}" --revision {INTERACTION_REVISION} --targets-file -
   ```

   If bounded geometry inspection fails, report the safe reason without blocking or replacing the row interaction:

   ```powershell
   python scripts/workday_assisted_browser.py point-targets --operation "{OPERATION}" --revision {INTERACTION_REVISION} --error "{SAFE_REASON}"
   ```

   Pointer enrichment remains optional. The same revision-bound arrow rail is used for both assistance modes, including when the human submits or confirms before pointers arrive. A stale pointer result after a newer revision was published is normal completion. Do not republish the row or repeat navigation. Navigate and capture retains `visualHelp`, so **Show me what to click** becomes available after the pointer set is ready and before a screenshot exists. Navigate only provides arrows without screenshot capture. Wait with `--interaction any`.
   When a baseline returns multiple targets, publish the complete array in one `point-targets` call. The companion renders one labeled marker per target and separates nearby markers on the rail; do not collapse the set to one representative target.

8. If the result is `visual-help`, attempt the screenshot only after the human selects **Show me what to click**. On failure, report **Screenshot unsuccessful** through `screenshot-result`. Wait again with `--interaction any` for the still-pending row interaction.
9. After confirmation or accepted entry, record the exact revision-bound interaction:

   ```powershell
   python scripts/workday_assisted_browser.py worksheet-record --operation "{OPERATION}" --revision {INTERACTION_REVISION}
   ```

   `worksheet-record` reads the accepted interaction from companion state, maps combined results to their separate worksheet rows, preserves unrelated rows, writes the draft atomically, and returns the updated worksheet status. Do not pass the worksheet value again, open the draft, or run a separate `worksheet-status` after a successful record. `capture`, `screenshot`, and `screenshot-result` are image operations, not worksheet-recording tools.

10. Continue with the returned `worksheet.nextOperation`. Do not reread the guides between rows. Pass the retained `applicationUrl` in the baseline options for rows that target the same Enterprise application. Each baseline compares the current URL with its expected URL and navigates only when they differ.

### Interruptions

If a new user message interrupts `wait`, cancel that foreground terminal command using the terminal tool's native cancellation. Do not call `workday_assisted_browser.py stop`. Answer the user, run `worksheet-status`, and start a fresh wait only when the same interaction remains pending. An explicit human request to restart collection follows the `worksheet-reset` branch above instead.

### Recovery

Follow the structured error returned by the failed tool. Run `worksheet-status` when progress is uncertain. Inspect CLI help, documentation, or source only when the error indicates a contract mismatch or lacks enough recovery detail.

A missing first result is not a completed search. If the human rejects a candidate or the search is incomplete, retain the row authorization, try the exact safe identifiers already available for the row, and inspect every visible result and available result page. Do not stop or return to chat because an element reference became stale, one search returned no match, the page refreshed, or the human rejected a candidate. Re-inspect the same row or request manual entry when bounded inspection cannot reliably collect or disambiguate the value.

Open a row-specific **Edit** control only when the current companion view names that exact control and explains that it will reveal existing values. Do not change or save anything in the revealed panel. Return `blocked` only when the authorized portal remains unreachable, bounded search and manual fallback are exhausted, or continuing would require an ambiguous selection or prohibited mutation.

For direct-value rows, `worksheet-present --stage confirmation` generates this canonical detected-value shape:

```json
{
  "fields": [
    {
      "label": "Detected {WORKSHEET_ROW}",
      "value": "{DETECTED_VALUE}"
    }
  ],
  "confirmation": {
    "operation": "{OPERATION}",
    "prompt": "This is the value detected for {WORKSHEET_ROW}. Record it in the worksheet?",
    "confirmLabel": "Record worksheet value",
    "rejectLabel": "Search again"
  },
  "visualHelp": {
    "operation": "{OPERATION}",
    "label": "{VISIBLE_TARGET_LABEL}"
  }
}
```

For attestation rows, the same command renders the shared administrator instruction and accepted worksheet choice instead of labeling readiness text as a detected value.

## Protect the worksheet

- Keep the canonical worksheet labels, allowed choices, examples, and validation behavior unchanged.
- Ask only for values already present in the worksheet.
- Do not infer a missing value, convert an unlabeled statement into a worksheet value, or treat "done" as a completed worksheet.
- Do not grant consent, assign users or groups, add permissions, create scopes, edit claims, save settings, upload a certificate, or perform another Microsoft Entra mutation.
- Do not include application tokens, credentials, or private keys.
- Return only exact labeled worksheet text. Do not return a JSON evidence object.

## Review and return the worksheet

1. When `worksheet.complete` is `true` after all 13 interactive rows, publish the canonical summary:

   ```powershell
   python scripts/workday_assisted_browser.py worksheet-present --operation entra-existing-configuration --stage summary
   ```

   The generated **Review final Microsoft Entra worksheet** page renders all 13 collected labels and values as fields. Do not manually author, patch, or reuse the summary payload.

2. The same summary presents exactly two buttons for the downstream-required `Existing configuration` row:
   - **Preserved without changes**
   - **Remediated without replacing unrelated configuration**
3. Wait for the `entra-existing-configuration` entry and the returned summary revision. The selected button submits immediately and is the administrator's final worksheet attestation.
4. Record the accepted preservation entry with `worksheet-record --operation entra-existing-configuration --revision {SUMMARY_REVISION}` and require the returned `worksheet.submissionReady` to be `true`.
5. Produce the exact 14-row labeled worksheet text accepted by the existing parser and return `completed`. Do not infer or default the preservation outcome.
6. If the human needs to revise a displayed value before selecting a preservation outcome, retain unaffected draft values, reopen only the identified interactive rows, and publish a new summary after the correction.
7. If the human cancels assistance, return `cancelled` without worksheet text.
8. Stop the assisted-browser session and return control to `provision-entra-app.md`.
