# Entra profile coverage for ESS personalization

## Purpose and scope

`AUTH-PROFILE-001` measures standard Entra attribute availability, highlighting profile-enrichment opportunities for ESS knowledge personalization. Coverage gaps are non-blocking.

Guidance connects coverage to personalization and explains how to enrich relevant profile data. This scalar-attribute diagnostic does not establish complete personalization readiness.

| Attributes checked | Interpretation |
| --- | --- |
| `usageLocation` | Licensing-country coverage, not verified HR country or confirmation of the agent's runtime location source. |
| `preferredLanguage` | Profile data relevant to language-specific knowledge answers. |
| `country`, `officeLocation`, `jobTitle`, `department`, `employeeType`, `employeeId`, `employeeHireDate` | Additional profile coverage; no specific runtime experience or mandatory field requirement is asserted. |

Manager relationships, custom attributes, and HR-source comparison/applicability are excluded. An Entra gap need not be a runtime gap when HR supplies the value.

## Reads and limits

The check uses FlightCheck's own Graph client and admin-consented `User.Read.All`, already in its default scopes, not the agent's runtime permissions. Focused runs reuse existing consent; identity mismatches stop before reads.

Tenant mode reads Member accounts, including disabled and service accounts, not an employee roster. Sequential **999-account pages** stop at completion or **10,000 accounts**; unused final-page records are discarded.

Reports label **Tenant coverage** or **Sample coverage**, with the checked count, `isSample`, and `populationComplete`. Graph page order is not random sampling.

The **30-second budget after authentication** covers reads, retry delays, and aggregation. Each page shares three retries across retryable HTTP and transport failures. Backoff and `Retry-After` honor the deadline.

## Coverage and outcomes

Count nonblank values as `available`, null/blank as `empty`, and omitted properties as `notReturned`. Coverage is `available / usersChecked * 100`; omission is not empty.

| ADK result | Condition |
| --- | --- |
| `Passed` | Every selected attribute has at least **95%** coverage and no omitted properties, evaluated before two-decimal display rounding. |
| `Warning` - coverage | Measured gap or omitted property; personalization and enrichment guidance. |
| `Warning` - not checked | Consent or read access is unavailable. `coverageVerified: false`; no coverage figures are reported. |
| `Error` | Other authentication/identity failures; request or budget errors; invalid, empty, duplicate, or out-of-population data. |

Unavailable access uses ADK's existing warning result with `coverageVerified: false`. This change does not add a separate `Not verified` result type.

Failed or expired reads invalidate partial coverage. Focused FlightCheck warnings exit `0`; errors are nonzero. Other profile checks retain their existing gates.

## Report contract

One HTML/JSON finding shows attribute counts, percentages, and sample metadata. Guidance explains the personalization opportunity, then how the tenant administrator can enrich relevant attributes in Entra or through HR-to-Entra sync and rerun. It recommends neither new HR-system setup in ESS nor placeholder values.

Coverage evidence excludes profile values, user IDs, and tokens; telemetry contains outcomes only. Presence proves neither correctness nor runtime use. `hrCountryComparison` remains `NotApplicable`.

## Entry points and validation

The checkpoint runs in full/authentication FlightChecks and selected-DA diagnostics. The shared standalone command defaults to `--scope me` with `User.Read`; `--scope tenant` uses the tenant scan. Only standalone supports `--attributes`. Target selection uses `--tenant-id` and `--preferred-username`.

```powershell
python scripts\flightcheck\cli.py --checkpoint AUTH-PROFILE-001 --tenant-id '<tenant-guid>' --preferred-username '<work-account>' --output .local\entra-flightcheck --no-open
python scripts\check_entra_profile.py --scope me --tenant-id '<tenant-guid>' --preferred-username '<work-account>'
```

Commands run from `solutions\ess-maker-skills`. Standalone exit codes are `0` for passed checks, `1` for either warning, and `2` for errors; `--output` saves its JSON report.

Tests cover thresholds, paging, retry/deadline limits, access denial, identity guards, and consistent full/checkpoint/profile results. Live validation checks both populated-tenant and unavailable-permission HTML/JSON paths.

API contracts: [Graph schema](https://graph.microsoft.com/v1.0/$metadata), [Get user](https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0), [List users](https://learn.microsoft.com/en-us/graph/api/user-list?view=graph-rest-1.0).
