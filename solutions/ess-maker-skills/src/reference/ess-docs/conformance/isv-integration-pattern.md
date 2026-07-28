# ISV integration pattern check

Analysis guidance for the **ISV integration pattern** check used by the `topics/review` skill. It verifies
that a topic integrating an ESS-orchestrated backend (ServiceNow HRSD, ServiceNow ITSM, Workday HCM, SAP
SuccessFactors HCM) uses the ESS template-config + shared-orchestrator pattern, rather than bypassing it
with a standalone cloud flow. This check reads only the authored topic — it needs no reference docs.

## The conformant pattern

A user-facing topic for one of these backends collects the user's input and then delegates the backend
call to a **shared system topic** via `BeginDialog`, passing a `scenarioName` and `parameters`. The shared
system topic (its name contains `System`, e.g. `WorkdaySystemGetCommonExecution`,
`ServiceNowHRSDSystemCommonExecution`, `ServiceNowITSMSystemGetTicketDetails`) runs the shared
orchestrator flow and returns `isSuccess` / response data. The user topic then parses and renders the
result. The user topic itself does **not** call a cloud flow directly.

## The anti-pattern to flag

A user-facing topic for a ServiceNow / Workday / SAP SuccessFactors scenario that calls its **own**
cloud flow directly — a `kind: InvokeFlowAction` with a `flowId` — instead of delegating to the shared
system topic. This bypasses the ESS orchestrator and the template-config mechanism, so the topic no longer
benefits from the shared request/response mapping, error shaping, and connection handling, and it
diverges from every other topic for that backend.

Signals that a topic targets an ESS-orchestrated backend:

- it passes a `scenarioName` whose prefix is `HRWorkdayHCM`, `ServiceNowHRSD`, `ITHelpdeskServiceNowITSM`,
  or a SuccessFactors HCM scenario; or
- it (or a topic it would normally call) references one of the shared `*System*` execution topics for
  those backends; or
- its purpose is clearly to read or write ServiceNow / Workday / SAP SuccessFactors data.

## What NOT to flag

Standalone cloud flows are the **correct** choice for connectors that have no ESS orchestrator — for
example Jira, a custom HTTP API, or other non-ESS connectors. A topic that calls its own flow for one of
those is conformant, not a bypass. Only flag a direct flow call when the backend is one of the
ESS-orchestrated systems above, which are expected to go through the shared system topic.

## Reporting

Apply the same precision bar and reachability scoring as the shared
[`finding-contract.md`](finding-contract.md). This check uses the `BTIP` finding-ID prefix. When you flag
a bypass, locate it by the `InvokeFlowAction` node's identity, and the suggested fix is to route the
backend call through the shared system topic for that backend (passing `scenarioName` + `parameters`)
instead of the direct flow call.
