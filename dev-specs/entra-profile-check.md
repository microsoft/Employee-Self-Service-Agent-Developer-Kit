# Microsoft 365 profile coverage for ESS personalization

## Purpose and scope

`AUTH-PROFILE-001` measures Microsoft 365 profile availability to highlight enrichment opportunities for ESS personalization. It reads the public Microsoft Graph beta profile API rather than only Entra `/users` attributes. Returned profiles can include data contributed by Entra, Organizational Data Service, people-data connectors, SharePoint profiles and user edits. The check is read-only and uses no internal Microsoft endpoints.

The diagnostic checks individual identity/current-employment fields and whether other standard profile sections contain data. Coverage describes the API response, not the correctness of profile values or end-to-end agent behavior.

## Default checks

| Group | Checks |
| --- | --- |
| Identity | Display name, given name, surname and user principal name |
| Current position | Job title, secondary title, role, secondary role, level, layer, employee ID, employee type, position start/end dates, description and summary |
| Company | Company name/code, cost center, division, department, secondary department, office location, pronunciation and website |
| Workplace address | Street, city, state, postal code, PO box and country/region |
| Relationships | Presence of manager and colleague data on the current position |
| Other profile sections | Addresses, anniversaries, awards, certifications, education, emails, interests, languages, notes, patents, phones, projects, publications, responsibilities, skills, web accounts and websites |

These are 50 availability checks, not 50 required employee properties. Custom extensions, source IDs, audit metadata, first-party-only pronouns and mailbox settings are excluded. Position start date is not hire date; profile languages are not Entra `preferredLanguage`; workplace country is not licensing `usageLocation`.

## Reads and limits

Tenant scans reuse existing delegated `User.Read.All` consent. Sequential Graph v1.0 `/users` paging lists Member IDs and user type, evaluating at most **100 profiles**. Member accounts include disabled and service accounts, not just employees.

The checker sends batches of up to **20 read-only GET requests** to Graph beta `/$batch`. Each subrequest reads `/users/{id}/profile`. Default profile reads avoid `$select` failures for advertised beta sections that live tenants do not expose; absent sections remain unverified. Batching saves network round trips; every subrequest remains subject to Graph throttling. Responses are correlated by ID, never array order. Retryable failed subrequests are retried without rereading successful profiles, honoring `Retry-After`.

One **30-second data-read budget**, excluding authentication, covers enumeration, batch requests, retry delays, fallback reads and aggregation. DNS resolution remains cancellable. Deadline expiry or failed/malformed requests discard partial coverage rather than publish a successful subset.

If directory/profile permission is unavailable, FlightCheck uses a separate `User.Read` client for `/beta/me/profile`, bound to the same account and tenant. It never prompts for new directory consent or downgrades other checks' clients. Other authentication, identity, network and data errors do not trigger fallback.

## Interpreting profile data

Nonblank text and valid integers, including layer zero, are available. Explicit null/blank scalar values and empty collections are empty. Omitted or null sections are not returned; metadata-only records and continuation/truncation signals remain unverified.

Current-position fields use only records explicitly marked `isCurrent`. Multiple candidate records must agree on the selected value and its presence state; relationship collection order does not affect agreement. Otherwise the field is unverified. The checker neither picks the first current position nor invents source precedence.

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

HTML/JSON evidence contains no profile values, user IDs or tokens. Guidance explains potential personalization benefits, points to the configured data source and the [organizational attribute reference](https://learn.microsoft.com/en-us/microsoft-365-apps/org-data-service/import/orgdata-attributes), and does not ask users to fill optional fields with placeholders. Existing telemetry remains outcome-only.

## Entry points and validation

The existing checkpoint ID works in full, authentication, focused and selected-DA runs. The standalone filename remains `scripts\check_entra_profile.py`; `--scope me` checks only the signed-in profile and explicit `--scope tenant` never silently falls back. `--attributes` selects named checks. JSON uses `m365-profile-check.v2`.

Tests cover the public beta schema, batched correlation/retries, source conflicts, missing sections, permissions, identity guards, deadlines/DNS cleanup and report parity. Live tests verify self-profile and permitted tenant reads. API contracts: [Profile](https://learn.microsoft.com/en-us/graph/api/profile-get?view=graph-rest-beta), [batching](https://learn.microsoft.com/en-us/graph/json-batching), [sources](https://learn.microsoft.com/en-us/graph/people-data-sources).
