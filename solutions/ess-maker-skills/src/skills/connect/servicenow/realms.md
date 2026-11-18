# ServiceNow Test and Prod realms

Read this when the maker says the ESS agent was promoted to Test or
Production, chooses to configure Test or Production, or pastes a Test or
Production agent link. It applies to both ServiceNow HRSD and ITSM. It follows
the Workday Connect DEV, TEST, and PROD journey and leaves the Dev lifecycle
unchanged.

Use `/connect` with ServiceNow selected for every realm. Do not introduce or
suggest realm-specific slash commands. Every command below runs with the same
`--provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG}` prefix as
the Dev lifecycle, where the slug is the recorded Dev agent.

## Independent checks and expected values

Test and Production are checked on their own. A Dev lifecycle that is not
complete, or that has no record at all, does not block them, and a working Dev
agent or a shared ServiceNow instance is not evidence that the promoted realm
is configured. The local Setup-complete workspace and the recorded Dev agent
remain the anchor for finding the promoted agent. Dev and the other promoted
realm never change a realm's recorded state.

- Each check reads only the promoted realm: its own connection, the binding to
  its own agent, its own topics, and its own portal URL. Never suggest reusing
  the Dev connection.
- Expected values are the ServiceNow instance and the Microsoft Entra
  application (client) ID. Keep administrator-confirmed values only when they
  are reliably associated with this agent and tenant and still apply to the
  shared ServiceNow instance. When the Dev record holds such confirmed values
  for the same tenant, the controller uses them as a reference and reports any
  difference. Ask the maker only for what is missing or stale, then have the
  ServiceNow administrator confirm it. Do not re-issue an administrator
  handoff automatically.
- The required ServiceNow topics must be turned on in the promoted realm. They
  are not compared with Dev's topic states.
- Connect does not promote or publish an agent. In Test and Production it
  reads topic states and the portal value and never changes them. A fix
  belongs in Dev, followed by a new promotion through the maker's own ALM
  process and a new check.

## Resolve the realm

On every invocation, run the status first and use the controller's
`activeTargetRealm` and `targets`. Never infer the realm from conversation
text. A bare `/connect` after Dev is Ready does not activate Test or
Production.

```text
python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} realm-status
```

**How do I promote?** is not evidence that promotion happened. Explain that
Connect configures ServiceNow after promotion but does not promote or publish,
show the Dev agent's Copilot Studio link, and direct the deployment owner to
the organization's approved promotion process.

If the maker asks to check ServiceNow after promotion but does not say Test or
Production, and the controller's `activeTargetRealm` does not settle it, ask
with `ask_user`. Never infer the destination from conversation text. If the
agent is also unknown, ask for that next, and do not ask again for context that
is already established.

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "destination": {
        "type": "string",
        "title": "Destination",
        "description": "Which destination should we check, Test or Prod?",
        "oneOf": [
          { "const": "test", "title": "Test" },
          { "const": "prod", "title": "Prod" }
        ]
      }
    }
  }
}
```

If promotion completion is unknown, ask once with `ask_user`:

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "promotion": {
        "type": "string",
        "title": "Promotion",
        "description": "Has the agent already been promoted to the requested realm?",
        "oneOf": [
          { "const": "yes", "title": "Yes, promotion is complete - check again" },
          { "const": "no", "title": "No, I need to complete promotion first" },
          { "const": "later", "title": "Not now" }
        ]
      }
    }
  }
}
```

An explicit statement that promotion completed, or a pasted agent link,
already answers it. On **No**, give the Dev agent link and the deployment-owner
handoff, then ask the maker to return after promotion. **Not now** preserves
all progress.

## Discover the promoted agent

Test and Production can each be checked whenever the maker asks; neither
waits for Dev to be Ready, and Production does not wait for Test.

- Maker said the agent was promoted, with no link:

  ```text
  python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} discover-realm-target --realm {test|prod}
  ```

- Maker pasted the Test or Production agent link:

  ```text
  python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} discover-realm-target --agent-link "{PASTED_AGENT_LINK}"
  ```

Both commands, and `check-realm`, also accept `--expected-instance
"{INSTANCE}"`, `--expected-client-id "{CLIENT_ID}"` and `--admin-confirmed`.
Pass them only for values the maker gave you, and pass `--admin-confirmed` only
after the ServiceNow administrator confirmed those values.

The controller reads the realm from the agent and proves the exact promoted
sibling of the recorded Dev agent: same agent, ALM family, schema, deployed
commit, Microsoft Entra tenant, and environment. A Dev link, a link to an agent
outside the recorded Dev agent's family, or a link whose realm conflicts with
the requested realm is rejected with a clear message; never trust it.

Do not ask the maker for an environment ID, BotId, flow ID, ALM family, or
deployed commit.

If the controller cannot prove one environment, show the safe environment names
or URLs it returns and ask the maker to choose one. Leave the choice unset,
then rerun with `--environment "{ENVIRONMENT_NAME_OR_URL}"`.

If discovery fails, keep the active realm and all completed administrator work.
Show the observed failure and the returned remediation. Offer **Check again**,
**Choose another environment**, and **Not now** with `ask_user`. Reuse a supplied
environment selection on **Check again**. Do not send the maker back to Dev.

## Realm stages

After discovery succeeds, run `realm-status` and use `phases` and
`nextPhaseId` for every message. Test and Production use the same three
stages, completed separately per realm. Show each item in `items` with its
result (pass, fail, or not checked).

| Stage | Result |
|---|---|
| Connections | Read-only. Done when the connection exists in this environment, is Connected, is bound to this agent, uses Microsoft Entra ID User Login, and its instance and client ID match the expected values. When expected values are missing, ask only for the missing ones, then have the administrator confirm; do not check until confirmed. |
| Runtime configuration | Read-only. Done when the required ServiceNow topics are turned on and the portal URL is set. Otherwise show `observations` and the returned guidance: fix it in Dev, promote again through your own ALM process, then check again. |
| Maker validation | The maker runs the ServiceNow scenario in this realm's Test pane. Record it with `record-realm-test --realm {test|prod} --prompt-category {CATEGORY} --result {pass|fail}`. |

### Connection problems

When the connection is missing, is not bound to this agent, is disconnected,
or does not use the expected values, the controller returns a BLOCKED message
that names the condition found. Show it as is. The supported repair for
connections in a promoted environment is not yet defined, so:

- Do not give instructions to create, bind, share, or repair the connection,
  and do not show a connection handoff.
- Never suggest reusing the Dev connection and never claim success.
- Keep the check read-only. When the maker says their own process resolved the
  condition, run `check-realm --realm {test|prod}` again.

Use `check-realm` to re-read the stages, and `select-realm --realm
{dev|test|prod}` to switch between realms that were already discovered.

## Maker-facing wording

Use these messages for Test and Prod. Fill in the agent name, the environment
name (or its URL when no name is known) and the ServiceNow instance from the
controller status. Use "Prod" and "Test" as the maker would. In the HR agent
use "HR case" and "Show my open HR cases"; in the IT agent use "IT ticket" and
"Show my open IT tickets". Keep identifiers, command names and field names out
of maker-visible text.

**Start of a realm run**

> We'll check the ServiceNow setup for **{Agent} in {Environment}**, then
> you'll run an {HR|IT} request to confirm the result.
>
> We're working with:
>
> - **Agent:** {Agent}
> - **Environment:** {Environment}
> - **ServiceNow instance:** {Instance URL}
>
> We'll retain the administrator-confirmed sign-in setup and mapping that still
> applies. You don't need to resend earlier replies unless a specific
> confirmation is missing or no longer applies.
>
> We're checking whether your account can configure this agent in
> {Environment}. Validation will wait until that check completes.

**Account cannot configure the agent (denied)**

> Your account doesn't have the required access to configure **{Agent} in
> {Environment}**. Ask a maker with the Environment Maker role and permission
> to edit this agent to run `/connect servicenow` using their own account.

**Access could not be verified (inconclusive)**

> We couldn't verify whether your account can configure **{Agent} in
> {Environment}**. Validation is paused; this doesn't mean your access was
> denied. Check again to continue.

Do not treat an inconclusive result as denied or as success.

**Request for the maker to run in the Test pane**

> In Copilot Studio, open **{Agent} in {Environment}** and run an {HR|IT}
> request in that agent's **Test pane** that should return your real ServiceNow
> data.
>
> For example, use **"Show my open {HR cases|IT tickets},"** if you have open
> ones. Use the agent in {Environment}, not the Dev agent.
>
> Return here and tell us what happened and whether it matched what you
> expected. You don't need to paste case contents or employee identifiers.

For Prod, add before the last paragraph: "The Test pane is where you try the
Prod agent; it doesn't switch this run to the Test environment." In the IT
agent say "ticket contents" instead of "case contents".

**Reply gives no usable result**

When the maker replies with only "Done", "Finished", or anything else that does
not say what the request returned, do not treat it as pass or fail and do not
run `record-realm-test`. Ask once, and keep asking until the reply says what
was returned and whether it matched:

> What did the request from **{Agent} in {Environment}** return, and was that
> what you expected?

Record `record-realm-test` only when the maker states a result: pass when it
returned what they expected, fail when it did not.

**Result recorded as pass (lookup worked)**

Show the controller's completion message as is. It says what was verified (the
lookup for the tested account and this agent in that environment) and what was
not (creation of records, other employees' sign-in mapping, and, for Test,
Prod behavior or, for Prod, release readiness). Do not add anything about
publishing or what to do next.

### Recovery rules

- **Wrong environment tested.** When the result came from the Dev agent (or from
  Test while Prod is being checked): "That's a {Dev|Test} result; we still need
  a result from **{Environment}**. Open **{Agent} in {Environment}** and run
  the request in that agent's Test pane, then tell us what happened." Do not
  record the result.
- **Expected empty result.** Check the setup items first. If no cause shows,
  ask: "Did the Test pane show an error, or only an empty result?" Tell the
  maker to send only the error text. If the maker may simply have no records,
  suggest a request for data they know exists. Never blame sign-in mapping,
  connection references or promotion without evidence.
- **Sign-in identity does not match (HR and IT).** Tell the maker the account
  used in the Test pane could not be matched to a ServiceNow user, and offer a
  ready-to-send message for the ServiceNow administrator: "The sign-in identity
  claim from Microsoft Entra ID does not match the ServiceNow user field used
  to find users. Please correct the mapping for the integration used by this
  agent. Do not change an OIDC configuration serving single sign-on or the
  Graph connector. Reply with a confirmation and the values you used, without
  employee identifiers or secrets." Re-check after the maker says it is fixed.
- **Empty HR service areas (HR only).** "The HR service-area list is empty.
  Employees using HR scenarios need one of the ServiceNow roles
  `sn_hr_core.basic`, `sn_hr_core.manager`, or `sn_hr_core.admin`. Ask your
  ServiceNow administrator to review the access for the account used in this
  request. This skill doesn't check or assign those roles."

## Manual validation

| Check | Expected result |
|---|---|
| Dev has no lifecycle record, then Test is checked | Connect asks only for the missing instance and client ID, waits for administrator confirmation, then checks Test. |
| Connection is on in Dev but missing in Test | Blocked: no connection found. No repair steps, no Dev connection suggested. |
| Connection exists in Test but is not bound to the agent | Blocked: not bound. |
| Connection in Test is disconnected | Blocked: disconnected. |
| Instance or client ID differs from the expected value | Blocked with the exact difference. |
| Required topic off, or portal URL not set, in Prod | Blocked with the Dev fix and re-promote guidance. Nothing is edited. |
| Prod is checked before Test is Ready | Prod is checked on its own. |
| Condition is resolved by the maker, then `check-realm` runs | The item turns to pass without repeating earlier answers. |
| Maker asks to check ServiceNow after promotion without saying Test or Prod | Connect asks "Which destination should we check, Test or Prod?" and does not guess. |
| Account lacks access (denied) vs. access check could not finish | Denied: ask a maker with the Environment Maker role to run it. Inconclusive: validation is paused, not denied, check again. |
| Maker replies only "Done." to the Test-pane request | Connect does not record pass or fail and asks what the request from the agent in that environment returned and whether it matched. |
| Maker tested the Dev agent instead of the promoted one | Connect asks for a result from the promoted environment and records nothing. |
| Maker's expected data came back empty | Connect checks setup first, then asks whether the Test pane showed an error or only an empty result. |
| Pass is recorded in Test or Prod | The completion message says what was verified and what was not, and does not mention publishing. |
