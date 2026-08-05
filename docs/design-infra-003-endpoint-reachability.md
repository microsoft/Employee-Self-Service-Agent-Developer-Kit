# Design Decision: INFRA-003 External Endpoint Reachability

Status: Accepted
Decision: Option B, HTTP probe via transient test flow
Date: 2026-06-29
Owner: ESS FlightCheck

## Why this matters

The agent calls external systems to do its job: Workday, SAP SuccessFactors, ServiceNow, custom HTTP.

Each system lives at an endpoint URL. If the Power Platform environment cannot reach that URL, the agent fails for real employees.

A connection can look fully configured and still be blocked by network egress or a firewall.

INFRA-003 catches blocked endpoints during preflight, before users hit them. It also names the endpoint and the blocking hop, so the fix targets the network, not the agent.

## Relationship to INFRA-002 (important)

INFRA-002 was rescoped during work-item discussion. It no longer means "outbound IP allowlist". It now means: HR system reachability via a layer-by-layer DNS / TCP / TLS probe from the maker's machine. That is the existing `probe_endpoint()` in `infrastructure.py`.

So the two checks are complementary layers of one concern:
- INFRA-002: local probe from the maker's machine. Accuracy MEDIUM. A FAIL is always meaningful. A PASS is necessary but not sufficient, because the maker's network path differs from Power Platform's egress.
- INFRA-003: live probe from the Power Platform environment's egress, via a transient flow. This is the "sufficient" signal INFRA-002 cannot give.

Consequence: INFRA-003 is not gated on INFRA-002. It is the deeper layer that reuses INFRA-002's local probe as its fallback.

## Decision to make

How deep should the reachability probe go?

- Option A: TCP/TLS reachability using the existing probe.
- Option B: Full HTTP probe via a transient test flow (matches the literal spec).

## Option A: TCP/TLS probe (reuse `probe_endpoint()`)

Reuses the existing layered DNS to TCP to TLS probe in `infrastructure.py`.

Pros:
- Reuses code we already have.
- Read-only and idempotent. Satisfies AC7.
- Stdlib only. No new dependencies.
- No credentials and no application data sent.
- Covers dns-fail, cert-error, timeout, blocked-hop for AC6.

Cons:
- Proves the line is open, not that the app answers.
- Cannot read HTTP status codes (200, 401, 403, 404).
- A healthy TLS handshake can still hide an app-layer failure.

## Option B: HTTP probe via transient test flow

Creates a temporary flow per endpoint, sends a real HTTP request, checks status < 400 (or 401/403).

Pros:
- Matches the spec validation method exactly.
- Confirms the app responds, not just the port.
- Real status codes give a stronger signal.

Cons:
- Creates and deletes resources. Breaks the read-only and idempotent rule.
- Needs auth and credentials handling.
- Sends application-layer data, against the module design.
- More moving parts, more ways to fail or leave residue.

## Decision

Go with Option B, the HTTP probe via a transient test flow, structured per Apurva Banka's INFRA-002 thread approach:

- Opt-in behind a `--runtime-reachability` CLI flag. The live flow is not the silent default.
- Transient cloud flow with a single HTTP HEAD action to the target endpoint. No credentials sent, no body.
- Lifecycle: create, activate, get callback URL, trigger, poll result, delete.
- Fallback to INFRA-002's local TCP/TLS probe if flow creation, activation, or run fails (insufficient role, DLP blocking the HTTP connector). Fallback emits WARN with the caveat that it tested the maker's path, not Power Platform's.
- Reuses existing auth: `runner.dv_token`, `runner.env_url`, discovered target URLs. No new scopes.

Reason: the check must prove reachability from the Power Platform environment's egress, not from the maker's local machine. A local probe tests the wrong network path. Only code running inside Power Platform (a flow) exercises the real egress route. Option B also reads HTTP status codes, which gives a true app-level signal.

## Resolved: Option B vs AC7 (user-consent decision)

Origin: in the INFRA-002 thread, Apurva Banka noted that creating a temporary flow (Dataverse Option 2) "violates our AC7", and Senthil Mani leaned toward the transient-flow option but wanted more discussion.

Resolution: the AC7 / user-consent decision is **resolved**. The `--runtime-reachability` egress path ships as an **opt-in, consent-gated, self-cleaning** mutation, and the default path stays fully read-only. AC7 is satisfied under this interpretation:

- Scope of "read-only": no changes to the agent solution, connections, or business data. One ephemeral probe artifact is allowed because it is fully cleaned up.
- Deterministic naming: the probe flow uses a fixed display name (`flightcheck-infra003-probe`) so reruns detect and sweep leftovers via a `$filter` orphan scan.
- Guaranteed cleanup: the created flow is deleted on completion (even on failure, in a `finally`), and an orphan sweep runs at the start and end of every live run. No residue.
- Idempotent outcome: running twice yields the same result and the same final environment state.
- Opt-in + consent: the mutating path only runs under `--runtime-reachability`. The default path stays fully read-only (local probe), keeping AC7 intact by default.

### Consent model (Approach C: proactive offer)

The `--runtime-reachability` flag is tri-state so every run path can get consent the right way:

- `--runtime-reachability` (True): forced on. Consent already given (chat asked, or operator opted in explicitly). Prints a one-line transparency notice before mutating.
- `--no-runtime-reachability` (False): forced off. Never mutates. Used by CI and anyone who wants the local probe only.
- omitted (None): **proactive offer**. On a normal interactive terminal run, if endpoints exist and INFRA-003 is in scope, FlightCheck asks Y/N inline before creating the flow. Non-TTY / CI defaults to decline (safe, read-only). The ADK/chat path (`--invocation-source adk`) never prompts here because the skill already owns consent conversationally and passes the flag.

On decline (either an explicit `--no-runtime-reachability` or a "No" at the prompt), the reachable/failed rows note the egress probe was **skipped by choice** and surface the manual-verification links (outbound-IP article + Azure service-tags JSON) so the maker can self-verify allowlisting.

Implementation: production `flightcheck/live_egress_probe.py` (isolated, the kit's only mutating path); wired into `check_external_endpoint_reachability` in `flightcheck/checks/infrastructure.py`; validated against cassette `tests/fixtures/cassettes/flightcheck_infra003_flow.yaml`.

## Output format contract (Shared Steps 7433818 / 7433819 / 7433820)

The report has two layers.

Report level (deployment directive at first glance, detail unfolds below):
- High-level readiness summary: Ready / Not ready.
- Actionable failures pinned to the top.
- Detailed validation results below.
- Deployment stage-wise readiness indicator aligned to white-glove engagement stages. Stages not yet finalized, still under review.

Per-finding level (role-aware, maker-friendly first, expandable to IT Admin and Microsoft teams):
- Probable cause.
- Configuration Area or Scope. For INFRA-003 this is Network (and the specific system, e.g. Workday, ServiceNow).
- What it implies. The impact if left unfixed. New field added by Graham McMynn.
- Next steps.
- Responsible role. For INFRA-003 this is typically InfoSec / Network admin. Role mappings come from the onboarding guide.

Note: this is a five-field per-finding schema. AC5 still says "4-field schema", so the source spec is stale. The Shared Steps contract above wins.

## Risks to manage

- Credential handling: the probe uses the configured connection. Never log secrets or tokens.
- Residue on crash: if cleanup fails, the next run must detect and remove the orphaned probe flow by its deterministic name.
- Permissions: creating and deleting a flow needs the right Power Platform role. Surface a WARN if the role is missing rather than failing hard.
- Timeout budget: bound each probe so a slow endpoint cannot stall the whole flightcheck.

## Acceptance criteria mapping

- AC1 Enumerate endpoints: read connection references in the agent solution.
- AC2 PASS: all endpoints reachable.
- AC3 FAIL: any endpoint unreachable.
- AC4 WARN: timeout or unverifiable.
- AC5 Schema: emit the five-field role-aware finding (Probable cause / Scope / What it implies / Next steps / Responsible role) per Shared Steps. AC5's "4-field" wording is stale.
- AC6 Tests: all-reachable, one-blocked, dns-fail, cert-error, timeout.
- AC7 Idempotent and read-only: default path (local probe) is fully read-only. The `--runtime-reachability` path uses deterministic naming and guaranteed cleanup. The user-consent decision is resolved; see "Resolved: Option B vs AC7" above.
