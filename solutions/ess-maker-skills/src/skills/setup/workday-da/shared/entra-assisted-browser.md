<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Microsoft Entra worksheet companion

Use this guide only after `provision-entra-app.md` renders the Microsoft Entra administrator handoff and the human selects **Launch browser companion for assistance**. Follow `assisted-browser.md` for the session protocol.

## Session inputs

Use:

- the current `entra-handoff` packet;
- the exact rendered capture table and numbered manual tasks;
- any safe values already present in the current manual worksheet response;
- any customer-facing worksheet labels returned as missing or invalid when resuming a partial response.

Store the in-progress draft only at `.local/connect/workday-da/entra-companion-draft.json`. The draft is one JSON object whose keys are the exact worksheet row labels from the table below and whose values are the confirmed worksheet text:

```json
{
  "Directory name": "{CONFIRMED_DIRECTORY_NAME}",
  "Enterprise application": "{CONFIRMED_APPLICATION_NAME}"
}
```

The draft stores confirmed worksheet values only. It does not store row authorization, browser references, pointers, screenshots, pending candidates, or interaction status.

## Worksheet operations

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
| Existing configuration                               | `entra-existing-configuration`              | No        |

The `Sensitive` column is authoritative. Never infer sensitivity from the row label, the visible value, or browser capabilities. For `No`, offer both actions with these literal labels:

```json
{
  "actions": [
    {
      "label": "Navigate only",
      "operation": "{OPERATION}",
      "mode": "navigate-only",
      "disclaimer": "{ROW_SPECIFIC_NAVIGATION_DISCLAIMER}"
    },
    {
      "label": "Navigate and capture",
      "operation": "{OPERATION}",
      "mode": "navigate-and-capture",
      "disclaimer": "{ROW_SPECIFIC_CAPTURE_DISCLAIMER}"
    }
  ]
}
```

For any future row marked `Yes`, offer only **Navigate only**. Do not copy the application value, present a detected-value confirmation, call `point-targets`, or offer a screenshot for that row.

## Run the worksheet session

1. Start the `entra-configuration` surface using `assisted-browser.md`.
2. Initialize the canonical ephemeral draft from safe values already supplied in the manual worksheet response, if any.
3. Read the compact worksheet projection:

   ```powershell
   python scripts/workday_assisted_browser.py worksheet-status
   ```

   Use `activeRow` for the current revision-bound interaction, `worksheet.recordedRows` for completed rows, and `worksheet.nextOperation` for the first unresolved row. The projection deliberately omits confirmed values and historical views. Do not reconstruct progress by rereading an old companion view or prior browser snapshots.

4. Process the unresolved worksheet rows in their original order:
   - present the row's existing manual location and instruction;
   - for every current `Sensitive: No` row, present both **Navigate only** and **Navigate and capture** using the canonical actions template;
   - continue when the human selects the row action;
   - use bounded inspection and navigation to assist the human;
   - after **Navigate only**, record navigation completion and present the existing manual-entry fallback;
   - after **Navigate and capture**, copy only the visible non-sensitive application value;
   - scroll the application target into view, attempt vertical centering, re-inspect its post-scroll position, and publish it with `point-targets` before asking the human to confirm it;
   - present one candidate or required attestation for human confirmation using the detected-value template below;
   - include `visualHelp` so **Show me what to click** is visible before a screenshot exists;
   - attempt the screenshot only after the human selects **Show me what to click**; on failure report **Screenshot unsuccessful** and allow retry without revoking row authorization;
   - after local confirmation, update only the canonical ephemeral draft and call `worksheet-status` again;
   - continue to the next unresolved row.
5. If the human rejects a row candidate, retain the row authorization and inspect again. Do not invalidate unrelated draft values.
6. A missing first result is not a completed search. Retain the row authorization, re-read the page, identify the visible search or filter control, and try the exact safe identifiers already available for that row. Inspect every visible result and available result page before concluding that no candidate can be verified.
7. Do not stop or return to chat because a shared-browser element reference became stale, one search term returned no match, the page refreshed, or the human rejected a candidate. Re-inspect and continue the same row.
8. When bounded inspection cannot reliably collect or disambiguate a required value after those retries, request manual entry for that row.
9. Open a row-specific **Edit** control only when the current companion view names that exact control and explains that it will reveal existing values. Do not change or save anything in the revealed panel.
10. For a worksheet setting that requires administrator attestation, present the worksheet's attestation and continue only after the human selects **Attest**.
11. Return `blocked` only when the authorized portal surface remains unreachable, every bounded search and manual fallback for the row has been exhausted, or continuing would require an ambiguous selection or prohibited mutation. Return to the existing combined worksheet interaction with a concise reason.

Use this canonical detected-value view shape for every current row after **Navigate and capture**:

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

## Protect the worksheet

- Keep the canonical worksheet labels, allowed choices, examples, and validation behavior unchanged.
- Ask only for values already present in the worksheet.
- Do not infer a missing value, convert an unlabeled statement into a worksheet value, or treat "done" as a completed worksheet.
- Do not grant consent, assign users or groups, add permissions, create scopes, edit claims, save settings, upload a certificate, or perform another Microsoft Entra mutation.
- Do not include application tokens, credentials, or private keys.
- Return only exact labeled worksheet text. Do not return a JSON evidence object.

## Review and return the worksheet

1. When every required label has a draft value, produce the exact labeled worksheet text accepted by the existing parser.
2. Present **Review final Microsoft Entra worksheet** with every submitted label and value as fields. Use:
   - operation: `entra-final-worksheet`;
   - prompt: **Do these final worksheet values accurately reflect the completed Microsoft Entra setup?**
   - confirm label: **Send values to ADK**
   - reject label: **Review worksheet rows**
3. If the human rejects the review, retain unaffected draft values, reopen only the identified rows, and present a new final review revision.
4. If the human selects **Send values to ADK**, return `completed` with the exact reviewed worksheet text.
5. If the human cancels assistance, return `cancelled` without worksheet text.
6. Stop the assisted-browser session and return control to `provision-entra-app.md`.
