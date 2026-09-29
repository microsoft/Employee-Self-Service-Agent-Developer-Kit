# Verify scope-derived ServiceNow prerequisites

Treat this as one complete high-level setup step. Give the Maker the full
handoff below, then ask one completion question for the whole step. Do not
pause between the individual prerequisite checks.

## Goal and owner

- **Goal:** confirm this HRSD instance has both its HR data foundation and the
  OIDC capability required by Microsoft Entra ID User Login.
- **Owner role:** ServiceNow Admin.

## Complete admin instructions

1. Open ServiceNow **All -> System Definition -> Plugins** (or the tenant's
   approved plugin-management path).
2. Confirm HR Core is installed and Active. Use plugin identifier
   `com.sn_hr_core` / scope `sn_hr_core`.
3. Open **All -> System OAuth -> Application Registry**.
4. Confirm **Configure an OIDC provider to verify ID tokens** is available.
   If it is unavailable, enable the tenant-supported OIDC/Multi-Provider SSO
   capability.

HR Core is derived from the `hrsd` scope. ITSM must not inherit this HR-only
requirement. OIDC capability is derived from `entraIDUserLogin`.

## Completion signal and evidence

The Maker should return one non-secret confirmation that:

- HR Core is installed and Active; and
- the OIDC provider registration option is available.

There is no supported kit API for activating these ServiceNow capabilities.
If either item is missing, show the exact remediation above and return
`ACTION_RESULT = "waiting"`.

Ask one question only: whether the ServiceNow Admin completed the entire
plugin-prerequisites step. While that question is pending, do not return an
action result. After explicit completion or approved reuse, record the single phase handoff:

```text
python scripts/connect_servicenow_da.py record-admin-phase --phase plugin-prerequisites --status <completed|reused>
```

Return `ACTION_RESULT = "recorded"` after the whole step is recorded.
