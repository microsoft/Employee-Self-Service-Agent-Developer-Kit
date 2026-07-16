# Authoring invariants for ESS topics

When you extend the ESS agent with a new topic, you are building **on top of** shared infrastructure the ESS
base solution already ships — the shared system topics, the orchestrator flow, and the agent's response
orchestration. That infrastructure gives your topic several behaviors **for free**, but only if the topic is
authored to route through it. This doc lists the **invariants** — the structural patterns to preserve so those
guarantees hold. Staying inside them means less to get right by hand; working around them silently gives up
the guarantee.

These are forward-looking authoring guidance (they inform `topics/create` and `topics/update`); the
`topics/review` skill flags a topic that has broken one of them.

## Invariant 1 — Delegate the backend call to the shared system topic

For any scenario that calls a backend ESS supports (ServiceNow, Workday, SuccessFactors), the topic **calls
the existing shared system topic** (e.g. `ServiceNowHRSDSystemGetCommonExecution`,
`WorkdaySystemGetCommonExecution`) via `BeginDialog`, passing a scenario name and parameters. It does **not**
build its own cloud flow to reach the connector.

This is the umbrella invariant — Invariants 2 and 3 only hold because the call is delegated. The shared system
topic owns the connector call, the failure handling, and the response shaping; your topic supplies inputs and
renders outputs. (See `customization/customize.md` for the template-config pattern this uses.)

## Invariant 2 — Render backend data with the standard parse → iterate → table pattern

Take the response the shared system topic returns and shape it with the standard pattern: `ParseValue` the
response, then `ForAll` over the parsed rows into a response-table variable that the message/card renders.

Preserving this matters because the agent's response orchestration recognizes it: when the backend returns
**empty or no data**, the orchestration generates an appropriate "no results" message for the user on its own.
You do not need to hand-author an empty-state branch for the normal data path.

Avoid two shapes that opt out of that behavior:

- A **hardcoded Adaptive Card** that renders regardless of data — it will show an empty/broken card on
  no-data instead of the generated message.
- **Concatenating parsed values into a string** (rather than `ForAll` into a table) — a null field can surface
  a literal `"null"` in the output.

## Invariant 3 — Let failures flow through the shared error path

Because the backend call is delegated (Invariant 1), a failure is handled **centrally**: the shared system
topic routes errors to the shared error handling, which shows the user an error and stops the dialog. Your
topic does not need to — and should not — reimplement this.

Two things to preserve:

- **Do not add a custom error handler that returns to your topic and continues** with empty data. Route errors
  through the shared error path rather than swallowing them and proceeding as if the call succeeded.
- **Do not show a success message before success is confirmed.** Gate any confirmation on the shared call's
  `isSuccess = true` result; a message that fires regardless of outcome can tell the user an action succeeded
  when it failed.

## What you get by staying inside the invariants

| Preserve | You get, for free |
| --- | --- |
| Delegate to the shared system topic | The connector call, auth, and response shaping are handled for you |
| Standard parse → iterate → table | The agent generates the empty/no-data message automatically |
| Shared error path | Failures show the user an error and stop, without a hand-authored branch |

## Security-critical behavior belongs to the ISV

This tool generates topics — the experience and orchestration layer. Don't use a generated topic as a
security control:

- **Authorization is the ISV's job.** The ISV (Workday, ServiceNow, SuccessFactors) enforces who can access
  what through its own permission model. A topic that hides a field or restricts a choice is a usability
  affordance, not an access boundary — never rely on it to gate data or actions the ISV would otherwise allow.
- **Parameter encoding for the connector call is handled by the shared execution path** — you do not
  reimplement connector input-escaping in the topic. If a scenario has security requirements beyond what the
  ISV's permission model covers, address those in your ISV or connector configuration, not by generating
  enforcement logic in a topic.

## Note for external makers

The shared system topics, orchestrator flow, and response orchestration are part of the installed ESS base
solution — they are present in any environment where you installed ESS, so these invariants apply whether or
not you have access to the ESS source. Build your topics to route through that shared infrastructure and let
it own the connector call, empty-state messaging, and error surfacing.
