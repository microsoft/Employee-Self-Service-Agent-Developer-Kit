# Microsoft 365 profile coverage for ESS personalization

## Purpose and scope

`AUTH-PROFILE-001` checks profile data availability for ESS personalization using the read-only [Microsoft Graph beta profile API](https://learn.microsoft.com/en-us/graph/api/profile-get?view=graph-rest-beta).

The properties below are a **subset of attributes supported by Microsoft 365 People Profile** that assist with ESS personalization.

## Properties currently checked

Property paths are relative to `/beta/users/{id}/profile` or `/beta/me/profile`.

| Property | Public profile field | Potential sources |
| --- | --- | --- |
| Display name | `names[].displayName` | Entra, ODS, people-data connectors |
| User principal name | `account[].userPrincipalName` | Entra account identity |
| Email | `emails[].address` | Entra email identities, people-data connectors |
| Job title | `positions[].detail.jobTitle` | Entra, ODS, people-data connectors |
| Employment type | `positions[].detail.employeeType` | Entra, ODS, people-data connectors |
| Department | `positions[].detail.company.department` | Entra, ODS, people-data connectors |
| Company name | `positions[].detail.company.displayName` | Entra, ODS, people-data connectors |
| Office location | `positions[].detail.company.officeLocation` | Entra, ODS, people-data connectors |
| Workplace country/region | `positions[].detail.company.address.countryOrRegion` | ODS, people-data connectors, Entra-derived address data where present |
| Employee ID | `positions[].detail.employeeId` | Entra, ODS, people-data connectors |
| Company code | `positions[].detail.company.companyCode` | ODS, people-data connectors |
| Cost center | `positions[].detail.company.costCenter` | Entra organizational data, ODS, people-data connectors |

## Populating profile data

When a property is missing, update the configured source system. These references describe supported attributes and ways to ingest data into Microsoft 365 People Profile:

- [Organizational Data Service (ODS) attributes](https://learn.microsoft.com/en-us/microsoft-365-apps/org-data-service/import/orgdata-attributes): reserved attributes and their mappings into the profile.
- [Microsoft Entra user attributes](https://learn.microsoft.com/en-us/graph/api/resources/user?view=graph-rest-1.0#properties): directory properties Entra can provide.
- [People data sources in Microsoft 365](https://learn.microsoft.com/en-us/graph/people-data-sources): how Entra, ODS, people-data connectors, SharePoint and user edits supply profile data, with links to ingestion guidance.

## Reads and limits

Tenant scans use existing delegated `User.Read.All` consent. Graph v1.0 `/users` is used only to list up to **100 Member user IDs**; disabled and service user accounts can be included.

Profile data is then read from **Graph beta `/users/{id}/profile`**. These GET requests are sent through Graph beta `/$batch`, with up to **20 requests per batch**. Results are matched to request IDs. Retryable failures are retried, honoring `Retry-After` when provided.

One **30-second budget**, excluding authentication, covers data reads, retries, fallback reads and aggregation. A failed or timed-out scan produces an Error without partial coverage.

On a permission-only failure, FlightCheck falls back to `/beta/me/profile` with `User.Read`, using the same verified account and tenant. Other authentication, request and data failures produce errors.

## Interpreting profile data

Nonblank text is **Available**. Explicit null/blank values and empty collections are **Empty**. Properties omitted from the response are **Not returned**. Incomplete or ambiguous data is **Unverified**.

Email is available when at least one record contains a nonblank address, regardless of email type.

Employment properties use records marked `isCurrent`. If current records disagree on a property's value or availability, that property is unverified.

For each property, report available, empty, not-returned and unverified counts. Coverage is `available / usersChecked * 100` when all observations for that property are verified; otherwise show **Unverified**. The **95% threshold** is evaluated before display rounding.

## Results and reporting

| Result | Meaning |
| --- | --- |
| Passed | All checked properties have verified coverage of at least 95%. |
| Warning - coverage | One or more properties have lower coverage or unverified data. |
| Warning - own profile only | Tenant access was unavailable; report the signed-in profile's availability. |
| Warning - not checked | Neither tenant nor self-profile permission was available. |
| Error | Authentication/identity, request, deadline or response-validation failure. |

Warnings are non-blocking. Reports distinguish **Tenant coverage**, capped **Sample coverage** and **Own profile only** results. Samples follow Graph order.

HTML/JSON reports contain counts and availability states, excluding profile values, user IDs and tokens. Telemetry remains outcome-only.

## Entry points

The checkpoint runs in full, authentication, focused and declarative-agent diagnostics.

The standalone script is `scripts\check_entra_profile.py`. Use `--scope me` for the signed-in profile or `--scope tenant` for tenant coverage without fallback. `--attributes` selects properties to check. JSON uses `m365-profile-check.v2`.
