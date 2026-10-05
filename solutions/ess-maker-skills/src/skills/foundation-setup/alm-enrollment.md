<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Optional ALM Enrollment

Use this shared path only after selected-agent product reconciliation has established one exact supported native-agent identity and direct inspection returned `alm.isEnrolled: false`. Never enroll an unresolved inventory row, infer enrollment from an HTTP failure, or use this path for solution-backed agents, successful native imports, or a Prod-to-Dev relationship that already proves the ALM family.

Enter this path only when `inspect-agent` returned `routeStatus: not-established` with `alm.isEnrolled: false` from the direct Swagger-defined `MinimalBotCard` contract. Explain that setup cannot currently use an ALM authoring route for this exact agent. Do not say that the agent itself is unusable.

Send this exact Message block:

**Message:**

This agent is not enrolled in ALM.

Enroll this agent in ALM to prepare it for safer releases, repeatable deployments, and version-controlled collaboration. [Learn more](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/alm).

**End message.**

Then ask exactly:

> Enroll this agent in ALM?

Use the host's interactive single-selection control and present these choices in this order:

- **Continue (Recommended)**
- **Skip enrollment**

Leave the selection initially unset and disable free-form input. Selecting **Continue (Recommended)** is the confirmation for the exact remote ALM-setting change described above.

## Continue with enrollment

Run:

```text
python scripts/setup_existing_da.py ensure-alm \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --agent-id "{AGENT_ID}"
```

Append the retained `--account`, `--tenant-id`, `--host`, and `--api-version` values when available. Never pass `--select-account` after the setup account has already been established.

Parse `DA_ALM_ENROLLMENT_ANNOTATIONS_JSON:` and its response body when present, then `DA_ALM_ENROLLMENT_JSON:` on success. A verification failure may instead emit `DA_ALM_ENROLLMENT_VERIFY_ANNOTATIONS_JSON:`, its response body, or `DA_ALM_ENROLLMENT_VERIFY_JSON:`.

Continue only when the final result reports `outcome: enabled` or `outcome: already-enabled` with `persistedValue: true`. The result proves only the persisted setting; it does not prove route readiness, attachment, publication, or deployment.

For a rejected precondition or update, preserve the HTTP status, service error code, request ID, and redacted response evidence and stop without attachment. For an uncertain write, do not rerun `ensure-alm`. The operation performs one authoritative component read-back: continue only when its final result proves `persistedValue: true`; otherwise preserve the redacted transport exception chain and stop without another write or attachment.

Then run:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --agent-id "{AGENT_ID}"
```

Interpret `DA_AGENT_ROUTE_JSON:`:

- For resolved `dev`, return to the caller's exact Dev continuation. Use `da-existing-dev.md` unless the caller defines a narrower attachment or replacement continuation.
- For resolved `prod`, continue through `da-prod-to-dev.md`.
- For `not-established`, state that the ALM setting persisted but direct metadata has not established enrollment or an authoring realm. Stop without retrying enrollment, attaching, or publishing.
- For another service or transport failure, preserve its evidence and stop without another write.

## Skip enrollment

Show:

**Message:**

ALM enrollment skipped. The agent was not changed.

Local authoring does not require ALM enrollment. Setup will validate the exact agent and component identity before preparing this workspace. Enrollment will still be required later for ALM lifecycle operations such as import, export, promotion, or realm-family management.

**End message.**

When selected-agent product reconciliation already established this exact supported native identity and the caller's continuation is local authoring, return to the caller's exact attachment command and append `--allow-unenrolled-authoring`. Preserve caller-owned provenance arguments such as `--setup-source` and `--expected-schema-name`.

For the ordinary existing-agent path, run:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --agent-id "{AGENT_ID}" \
  --allow-unenrolled-authoring
```

Append the retained `--account`, `--tenant-id`, `--host`, and `--api-version` values when available. Never pass `--select-account` after the setup account has already been established.

The explicit flag authorizes only non-mutating local attachment after the maker declined enrollment. It bypasses ALM route discovery, validates the exact direct `botId`, requires the Swagger-defined direct metadata to normalize to `alm.isEnrolled: false`, fetches `/components`, validates the exact returned `cdsBotId` and schema, and materializes the workspace. It records `alm.isEnrolled: false` and omits `realm`; it must not reinterpret missing or null service realm as a Dev realm. It does not enroll, publish, import, export, promote, or establish an ALM family.

On `connectionStatus: workspace-ready`, continue through the native FlightCheck maintenance and completion contract in `da-existing-dev.md`. Preserve any exact validation or component-fetch failure and stop without reinterpreting it as an ALM requirement.

When the caller requested an ALM lifecycle operation such as package replacement, import, export, promotion, or realm-family management, skipping enrollment does not authorize that operation. Return to the caller without a write or attachment unless the maker separately selected the local-authoring continuation. The caller must preserve the lifecycle blocker and its own recovery choices.
