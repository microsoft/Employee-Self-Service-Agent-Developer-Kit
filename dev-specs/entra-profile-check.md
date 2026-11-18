# Microsoft 365 profile coverage for ESS personalization

## Purpose and scope

`AUTH-PROFILE-001` measures Microsoft 365 profile availability to highlight enrichment opportunities for ESS personalization. It reads the public Microsoft Graph beta profile API rather than only Entra `/users` attributes. Returned profiles can include data contributed by Entra, Organizational Data Service (ODS), people-data connectors, SharePoint profiles and user edits. The check is read-only.

The scope is a selected core of identity and organizational properties defined by the public Microsoft 365 profile, ODS and Entra contracts. It is not a requirement to populate every property supported by those services. Coverage describes returned data availability, not the correctness of values or end-to-end agent behavior.

## Default checks

These are the **12 default availability checks**. All paths below are relative to `/beta/users/{id}/profile` or `/beta/me/profile`; position fields use explicitly current records.

| Property | Public profile field | Potential sources |
| --- | --- | --- |
| Display name | `names[].displayName` | Entra, ODS, people-data connectors |
| User principal name | `account[].userPrincipalName` | Entra account identity |
| Primary/work email | `emails[].address`, with type `main` or `work` | Entra email identities, people-data connectors |
| Job title | `positions[].detail.jobTitle` | Entra, ODS, people-data connectors |
| Employment type | `positions[].detail.employeeType` | Entra, ODS, people-data connectors |
| Department | `positions[].detail.company.department` | Entra, ODS, people-data connectors |
| Company name | `positions[].detail.company.displayName` | Entra, ODS, people-data connectors |
| Office location | `positions[].detail.company.officeLocation` | Entra, ODS, people-data connectors |
| Workplace country/region | `positions[].detail.company.address.countryOrRegion` | ODS, people-data connectors, Entra-derived address data where present |
| Employee ID | `positions[].detail.employeeId` | Entra, ODS, people-data connectors |
| Company code | `positions[].detail.company.companyCode` | ODS, people-data connectors |
| Cost center | `positions[].detail.company.costCenter` | Entra organizational data, ODS, people-data connectors |

The source column describes possible contributors, not inferred provenance. Actual contribution depends on tenant configuration and the profile's `sources` metadata. ODS `Microsoft_PersonEmail` is a record-matching key, not evidence that the returned email collection is populated. UPN and email are checked separately and need not be equal.

Only these 12 properties are checked. Given name, surname, manager/colleague relationships, hire/position dates and other profile enrichment fields are excluded; there is no optional check group. The selected properties are enrichment opportunities, not deployment requirements.

Public basis: [ODS profile-supported attributes and mappings](https://learn.microsoft.com/en-us/microsoft-365-apps/org-data-service/import/orgdata-attributes), [Entra user properties](https://learn.microsoft.com/en-us/graph/api/resources/user?view=graph-rest-1.0#properties), [profile data sources](https://learn.microsoft.com/en-us/graph/people-data-sources), [people-data connector mappings](https://learn.microsoft.com/en-us/plugins/build-connectors-with-people-data), and the [live beta schema](https://graph.microsoft.com/beta/$metadata).

## Reads and limits

Tenant scans reuse existing delegated `User.Read.All` consent. Sequential Graph v1.0 `/users` paging lists Member IDs and user type, evaluating at most **100 profiles**. Member accounts include disabled and service accounts, not just employees.

The checker sends batches of up to **20 read-only GET requests** to Graph beta `/$batch`. Each subrequest reads `/users/{id}/profile`; only the configured properties are evaluated. Batching saves network round trips; every subrequest remains subject to Graph throttling. Responses are correlated by ID, never array order. Retryable failed subrequests are retried without rereading successful profiles, honoring `Retry-After`.

One **30-second data-read budget**, excluding authentication, covers enumeration, batch requests, retry delays, fallback reads and aggregation. DNS resolution remains cancellable. Deadline expiry or failed/malformed requests discard partial coverage rather than publish a successful subset.

If directory/profile permission is unavailable, FlightCheck uses a separate `User.Read` client for `/beta/me/profile`, bound to the same account and tenant. It never prompts for new directory consent or downgrades other checks' clients. Other authentication, identity, network and data errors do not trigger fallback. Authentication, malformed-response and terminal request errors take precedence over a permission denial in the same batch, regardless of response order.

## Interpreting profile data

Nonblank text is available. Explicit null/blank values and empty collections are empty. Omitted or null sections are not returned. Continuation/truncation signals affecting the selected family or property path remain unverified; unrelated fields and their continuations are ignored.

The email check requires a nonblank address on a `work` or `main` (primary) email record; a label alone does not count. Personal/other addresses do not satisfy it. If no qualifying address is available, missing/unknown types or omitted qualifying addresses remain unverified. Explicit null/blank qualifying addresses are empty. Multiple qualifying addresses establish presence without requiring them to be identical.

Current-position fields use only records explicitly marked `isCurrent`. Multiple candidate records must agree on the selected value and its presence state. Otherwise the field is unverified. The checker neither picks the first current position nor invents source precedence.

For each tenant field, report available, empty, not-returned and unverified counts. Calculate `available / usersChecked * 100` only when that field has no unverified/not-returned accounts; otherwise show **Unverified**, not a misleading percentage. Every included check uses the **95% threshold**, evaluated before display rounding.

## Results and reporting

| Result | Meaning |
| --- | --- |
| Passed | All included tenant checks have verified coverage of at least 95%. |
| Warning - coverage | One or more checks have lower coverage or unverified evidence. |
| Warning - own profile only | Only the signed-in profile was checked; list per-field availability without tenant percentages. |
| Warning - not checked | Neither tenant nor self-profile permission was available. |
| Error | Authentication/identity, request, deadline or response-validation failure. |

Warnings are non-blocking. Own-profile fallback always remains Warning, even when all fields are populated. `coverageVerified: false` identifies unverified tenant coverage; `profileVerified: true` identifies a successful self-profile read. Complete and capped scans are labelled **Tenant coverage** or **Sample coverage**, with the checked count; samples follow Graph order and are not random estimates.

HTML/JSON evidence contains no profile values, user IDs or tokens. Guidance explains potential personalization benefits, points to the configured data source and the [organizational attribute reference](https://learn.microsoft.com/en-us/microsoft-365-apps/org-data-service/import/orgdata-attributes), and does not ask users to fill gaps with placeholders. Existing telemetry remains outcome-only.

## Entry points and validation

The existing checkpoint ID works in full, authentication, focused and selected-DA runs. The standalone filename remains `scripts\check_entra_profile.py`; `--scope me` checks only the signed-in profile and explicit `--scope tenant` never silently falls back. `--attributes` selects named checks. JSON uses `m365-profile-check.v2`.

Tests cover the exact core property set, primary/work email filtering, public beta schema, batched correlation/retries, source conflicts, missing fields, permissions, identity guards, deadlines/DNS cleanup and report parity. Live tests verify self-profile and permitted tenant reads. API contracts: [Profile](https://learn.microsoft.com/en-us/graph/api/profile-get?view=graph-rest-beta), [email records](https://learn.microsoft.com/en-us/graph/api/resources/itememail?view=graph-rest-beta), [batching](https://learn.microsoft.com/en-us/graph/json-batching).
