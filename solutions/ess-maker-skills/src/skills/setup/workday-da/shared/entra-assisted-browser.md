<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Microsoft Entra worksheet companion

Use this guide only after `provision-entra-app.md` renders the Microsoft Entra administrator handoff and the human selects **Launch browser companion for assistance**. Follow `assisted-browser.md` for the session protocol.

## Session inputs

Use:

- the current `entra-handoff` packet;
- the exact rendered capture table and numbered manual tasks;
- any safe values already present in the current manual worksheet response;
- any customer-facing worksheet labels returned as missing or invalid when resuming a partial response.

Store the in-progress draft only under `.local/connect/workday-da/`.

## Worksheet operations

| Worksheet row               | Companion operation                         |
| --------------------------- | ------------------------------------------- |
| Directory name              | `entra-directory-display-name`              |
| Enterprise application      | `entra-enterprise-application-display-name` |
| Application ID              | `entra-application-id`                      |
| Selected Reply URL          | `entra-reply-url`                           |
| NameID source               | `entra-name-id-source`                      |
| SAML signing                | `entra-saml-signing-option`                 |
| Certificate thumbprint      | `entra-certificate-thumbprint`              |
| Certificate expiration date | `entra-certificate-expiration`              |
| SAML configuration          | `entra-saml-configuration`                  |
| Signing certificate         | `entra-signing-certificate-check`           |
| Authorized connector        | `entra-authorized-connector`                |
| Permissions and consent     | `entra-permissions-consent`                 |
| Employee assignment         | `entra-employee-assignment`                 |
| Existing configuration      | `entra-existing-configuration`              |

## Run the worksheet session

1. Start the `entra-configuration` surface using `assisted-browser.md`.
2. Initialize the ephemeral draft from safe values already supplied in the manual worksheet response, if any.
3. Process the unresolved worksheet rows in their original order:
   - present the row's existing manual location and instruction;
   - request **Navigate only** unless the row explicitly supports candidate capture;
   - continue when the human selects the row action;
   - use bounded inspection and navigation to assist the human;
   - publish the inspected target through the companion rail before asking the human to confirm it;
   - publish the bounded contextual screenshot when the shared-browser tool surface provides one;
   - present one candidate or required attestation for human confirmation;
   - after local confirmation, update only the ephemeral draft;
   - continue to the next unresolved row.
4. If the human rejects a row candidate, retain the row authorization and inspect again. Do not invalidate unrelated draft values.
5. A missing first result is not a completed search. Retain the row authorization, re-read the page, identify the visible search or filter control, and try the exact safe identifiers already available for that row. Inspect every visible result and available result page before concluding that no candidate can be verified.
6. Do not stop or return to chat because a shared-browser element reference became stale, one search term returned no match, the page refreshed, or the human rejected a candidate. Re-inspect and continue the same row.
7. When bounded inspection cannot reliably collect or disambiguate a required value after those retries, request manual entry for that row.
8. Open a row-specific **Edit** control only when the current companion view names that exact control and explains that it will reveal existing values. Do not change or save anything in the revealed panel.
9. For a worksheet setting that requires administrator attestation, present the worksheet's attestation and continue only after the human selects **Attest**.
10. Return `blocked` only when the authorized portal surface remains unreachable, every bounded search and manual fallback for the row has been exhausted, or continuing would require an ambiguous selection or prohibited mutation. Return to the existing combined worksheet interaction with a concise reason.

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
