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
  application (client) ID. The controller decides from the recorded Dev
  lifecycle, never from the model, which of two cases applies, and returns the
  case in `renderBlock.case` and its explanation in `renderBlock.text`:
  - **Dev reuse (`dev-reuse`):** the Dev record holds the
    administrator-confirmed instance, Entra Client ID and User Claim, and the
    employee mapping (User Field) for this agent and tenant. Do not run any
    administrator handoff. The block explains that the setup is reused and then
    shows the checklist.
  - **Independent (`independent`):** there is no Dev record, or it lacks any one
    of those confirmed values, for example a missing employee mapping or a
    different tenant. Run the full administrator flow for the destination, then
    the checks. Partial reuse is never offered. The block shows the two
    administrator rows before the connection check and, for the one open step,
    the question or the ready-to-send administrator message (see
    [Independent administrator flow](#independent-administrator-flow)).
- The required ServiceNow topics must be turned on in the promoted realm. They
  are not compared with Dev's topic states.
- We do not promote or publish an agent. The checks in Test and Production are
  read-only. A required topic that is off, or a missing portal URL, is handled
  as the destination's own repair (see [Runtime problems](#runtime-problems));
  the controller records what should change, never a Dev-side fix, and does not
  mutate the destination itself.

### Independent administrator flow

Emit the block verbatim; it already carries the one open step. Do not write
your own administrator message and never ask the maker for a tenant ID.

1. **ServiceNow instance.** The block asks for the instance name. Rerun
   `check-realm --realm {test|prod} --expected-instance "{INSTANCE}"` with the
   maker's answer.
2. **Microsoft Entra administrator.** The block carries the same message as Dev.
   When the maker pastes the reply, run:

   ```text
   python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} record-realm-admin --realm {test|prod} --stage entra --client-id "{CLIENT_ID}" --claim-name "{CLAIM_NAME}"
   ```

3. **ServiceNow administrator.** The block carries the same message as Dev,
   filled with the recorded Client ID and User Claim. When the maker pastes the
   reply, and only after the administrator confirmed that the configuration is
   saved and that the User Field holds the same value as the User Claim, run:

   ```text
   python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} record-realm-admin --realm {test|prod} --stage servicenow --user-field "{USER_FIELD}" --confirm-saved-mapping
   ```

The checks run once both replies are recorded. Never pass `--expected-client-id`
or `--admin-confirmed` in an independent run; the Client ID comes only from the
Entra administrator's reply. A claim named `aud` is rejected. When the maker
replies "Done" for any step, run `check-realm --realm {test|prod}`; only that
step is expected to change.

## Resolve the realm

**Request names both agents.** When one request names both ESS agents or all
of them (for example "Check HR and IT in Prod"), do not run `realm-status` or
any other command first. Run `validation-notice --situation multi-agent`, send
`chatMessage` verbatim as the whole reply (no preamble, no trailer, no
checklist), and end the turn. It says:

> This skill validates one ESS agent per run. Which should we check first—**Employee Self-Service HR** or **Employee Self-Service IT**?

No choice is preselected, no run starts, and nothing is recorded. When the
maker names one agent, select it with `agent-chooser --agent-name` and continue
only that agent for the destination they originally named; the other agent is a
separate run later.

**Agent names differ across environments.** The promoted agent can have a
different display name in Test or Prod than in Dev. When the maker names an
agent together with a destination (for example "test the IT agent in Prod"),
pass the words as typed to `agent-chooser --agent-name "{NAME_AS_TYPED}"`; the
controller splits off the destination itself. It resolves the Dev agent from
stable evidence only: the Dev agent's name, a promoted agent that realm
discovery already verified and recorded (its recorded name or its Copilot
Studio link), or a single prepared agent of that kind (HR or IT). When the
result is `ready`, continue with `selectedAgent`, use `realmHint` as the
destination, and **run `discover-realm-target --realm {realmHint}` next**
without asking the maker anything. That command finds the promoted agent and
its link by itself through the read-only ALM family check from the Dev agent,
whatever its display name is, and records its name, ID, and link. A saved Dev
target never means the promoted agent is unknown: always run discovery first.
Never decide which agent a name belongs to yourself, never pick between
candidates, and never infer the agent from a display name alone. Never write
your own "please paste the URL" or "the saved target is Dev" message. Only the
controller asks, and only after discovery ran: when `discover-realm-target`
returns `status: realm-target-not-found`, send its `chatMessage` verbatim and
end the turn (it names what was searched). Texts about the destination use the
destination agent's recorded name.

On every invocation, run the status first and use the controller's
`activeTargetRealm` and `targets`. Never infer the realm from conversation
text. A bare `/connect` after Dev is Ready does not activate Test or
Production.

```text
python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} realm-status
```

**How do I promote?** and **Can you move it to Prod?** are not evidence that
promotion happened. Say, with the real destination name:

> This ServiceNow run can validate the connection for the agent in {Prod|Test}
> after your deployment. It doesn't deploy or publish the agent.
>
> Complete the promotion through your existing deployment process, then return
> with the destination agent. We'll retain any applicable administrator-confirmed
> ServiceNow setup.

Show the Dev agent's Copilot Studio link when it helps, and do not promote,
publish, or give deployment instructions.

If the maker asks to check ServiceNow after promotion but does not say Test or
Production, and the controller's `activeTargetRealm` does not settle it, ask
with `ask_user` (card title = the question, Yes/No only; put any explanation
in the chat message). Never infer the destination from conversation text. If the
agent is also unknown, ask for that next, and do not ask again for context that
is already established.

Ask the destination as a sequence of Yes/No questions, never a Test/Prod
picker. First ask "Should we check Test?". On **Yes**, the destination is
`test`. On **No**, ask "Should we check Prod?". On **Yes**, the destination is
`prod`. If both are **No**, ask in chat which destination to check and wait for
a typed reply; do not run a realm command.

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "checkTest": {
        "type": "string",
        "title": "Should we check Test?",
        "oneOf": [
          { "const": "yes", "title": "Yes" },
          { "const": "no", "title": "No" }
        ]
      }
    }
  }
}
```

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "checkProd": {
        "type": "string",
        "title": "Should we check Prod?",
        "oneOf": [
          { "const": "yes", "title": "Yes" },
          { "const": "no", "title": "No" }
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
          { "const": "yes", "title": "Yes" },
          { "const": "no", "title": "No" }
        ]
      }
    }
  }
}
```

An explicit statement that promotion completed, a pasted agent link, or a
request to check or test the agent in a named Test or Prod destination already
answers it: run `discover-realm-target` (see **Discover the promoted agent**)
instead of asking. Ask this question only when the maker's request leaves
promotion genuinely open. On **No**, give the Dev agent link and the
deployment-owner handoff, then ask the maker to return after promotion. All
progress is preserved.

## Discover the promoted agent

Test and Production can each be checked whenever the maker asks; neither
waits for Dev to be Ready, and Production does not wait for Test.

**Discovery always runs first.** As soon as the maker names Test or Prod for HR
or IT (for example "check IT in Prod", "test the IT agent in Prod", or "we
promoted it"), and the recorded targets do not already include that realm, run
`discover-realm-target --realm {test|prod}` before anything else. Do not ask
"Has the agent already been promoted?", do not ask for an agent link, and do
not tell the maker that only Dev is saved. The command reads the promoted agent
from the Dev agent's ALM family through the API and finds it even when its
display name or link is different in each environment. Ask the maker only when
it returns `realm-target-not-found`, with its `chatMessage` verbatim.

- Maker named the destination, or said the agent was promoted, with no link:

  ```text
  python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} discover-realm-target --realm {test|prod}
  ```

- Maker pasted the Test or Production agent link:

  ```text
  python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} discover-realm-target --agent-link "{PASTED_AGENT_LINK}"
  ```

Both commands, and `check-realm`, also accept `--expected-instance
"{INSTANCE}"`. In the Dev reuse case they also accept `--expected-client-id
"{CLIENT_ID}"` and `--admin-confirmed`; pass those only for values the maker
gave you, and `--admin-confirmed` only after the ServiceNow administrator
confirmed them. An independent run rejects both; use `record-realm-admin`.

The controller reads the realm from the agent and proves the exact promoted
sibling of the recorded Dev agent: same agent, ALM family, schema, deployed
commit, Microsoft Entra tenant, and environment. A Dev link, a link to an agent
outside the recorded Dev agent's family, or a link whose realm conflicts with
the requested realm is rejected with a clear message; never trust it.

Do not ask the maker for an environment ID, BotId, flow ID, ALM family, or
deployed commit.

If the controller finds no promoted agent, or more than one, it returns
`status: realm-target-not-found` with a fixed `chatMessage` that says what was
searched and asks for the agent link. Send it verbatim as the whole reply and
end the turn; follow its `afterReply` when the maker answers. It records
nothing. This is the only case where the maker is asked for a link.

If discovery fails any other way, keep the active realm and all completed administrator work.
Show the observed failure and the returned remediation. Ask one Yes/No question with `ask_user`: "Should we check again?" Reuse a supplied
environment selection on **Yes**. On **No**, ask in chat which environment to use, or
stop and preserve all progress. Do not send the maker back to Dev.

## Realm stages

After discovery succeeds, `discover-realm-target`, `check-realm`,
`realm-status`, `select-realm`, and `record-realm-test` each return
`renderBlock.text`: a step checklist for the active Test or Prod run. Emit it
verbatim as an assistant message before any other tool call. Never write your
own checklist, status table, or item list, and do not paraphrase its rows, its
explanation, or its instruction. Use `phases` and `nextPhaseId` only to decide
what to do next.

The block opens with a one-paragraph explanation of the case (Dev reuse or
independent). The checklist uses the same icons as the Dev view: ✅ done, ⏳
waiting, ❌ needs attention, ⬜ not checked yet. Its steps are permission to
configure the agent, then, in an independent run only, the Microsoft Entra
administrator and the ServiceNow administrator, then the ServiceNow connection,
topics, the portal URL, and the real-data test in the Test pane. The
administrator rows show ⏳ until the reply is recorded. The checks are
read-only API reads. They stop at the first step that needs attention or is
waiting, so later steps stay ⬜. When a step needs attention or is waiting, the
block ends with that step's own instruction; emit it as part of the block.
When the maker replies "Done", run `check-realm --realm {test|prod}` and emit
the new block; only the step that needed attention is expected to change. When
every check passes, the real-data row shows ⏳ Waiting for you, followed by the
request to run in the Test pane.

Test and Production use the same three stages, completed separately per realm.

| Stage | Result |
|---|---|
| Connections | Read-only. Done when the connection exists in this environment, is Connected, is bound to this agent, uses Microsoft Entra ID User Login, and its instance and client ID match the expected values. In an independent run the checks start only after both administrator replies are recorded. |
| Runtime configuration | Read-only check. Done when the required ServiceNow topics are turned on and the portal URL is set. Otherwise the block says which one needs attention (see [Runtime problems](#runtime-problems)); nothing is promoted or published. |
| Maker validation | The maker runs the ServiceNow scenario in this realm's Test pane. Record it with `record-realm-test --realm {test|prod} --prompt-category {CATEGORY} --result {pass|fail|untested}`. Use `untested` only when the maker chooses to finish without testing; it is never a pass, never completes validation, and a later pass or fail replaces it. If the maker reports the expected data while only the portal URL is missing, the pass is saved as reported (not complete) until the portal is fixed and rechecked. |

### Connection problems

When the connection is missing, is not linked to this agent, is disconnected,
or does not use the expected values, the block shows ❌ on the connection step
and ends with the controller's "Validation is paused" text naming the condition
found. The repair mechanism for a destination connection is an open
engineering question, so the text does not give a menu path or numbered
steps. Do not invent one. It ends by asking the maker to return once the
supported destination repair is complete, and says we'll recheck the
destination setup. Never suggest reusing the Dev connection and never claim
success. The checks stay read-only: nothing is created, linked, or changed for
the maker. When the maker returns, run `check-realm --realm {test|prod}` again.

### Runtime problems

- **Required topic off.** The block says: "A required ServiceNow {HR|IT} topic
  is off in **{Agent} in {Environment}**, so the agent can't complete that
  request." then "We'll enable the affected built-in topic and leave unrelated
  topics unchanged." The controller records the topics to enable as a request
  (`repairs.enableTopics` in `realm-status`). The controller never changes the
  destination, and no supported command for it exists yet; do not invent one
  or send the maker to a menu path. Tell the maker the change is pending and
  to return when it is complete, then run `check-realm --realm {test|prod}`.
- **Portal URL missing.** The block says the agent is missing its employee
  portal URL so its {case|ticket} links may not open correctly, and asks: "What
  is the full HTTPS base URL employees should use for {HR cases|IT tickets}?"
  Run this with the maker's answer:

  ```text
  python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} record-realm-portal-url --realm {test|prod} --portal-url "{URL}"
  ```

  The URL must be HTTPS on the recorded ServiceNow instance. When the maker
  gave it without `https://`, the command records nothing and returns a
  confirmation question; after the maker confirms, rerun it with
  `--confirm-portal-url`. It records the request only and returns: "We'll save
  that URL for the {HR|IT} agent in {Environment}. The shared identity setup
  stays in place." The controller never changes Test or Prod itself and no
  supported command for that exists yet, so do not invent one. Tell the maker
  the change is pending and to return when it is complete, then run
  `check-realm`. Keep the shared identity setup.
- **Expected data returned but the portal URL is missing.** When the maker
  reports a pass while only the portal URL is missing, `record-realm-test`
  records it as reported. The block says: "Your {HR|IT} request returned the
  expected data, but the agent in **{Environment}** is missing its employee
  portal URL. We need to fix that before this setup can be called complete."
  and asks the portal URL question. After the portal is fixed and rechecked,
  the result becomes a pass without asking the maker to repeat the request.

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
> denied. Retry the permission check to continue.

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
>
> You can also finish without testing; this integration in {Environment} will
> remain untested.

For Prod, add before the last two paragraphs: "The Test pane is where you try
the Prod agent; it doesn't switch this run to the Test environment." and end
with "You can also finish without testing; the Prod integration will remain
untested. Test it before employees use it." In the IT agent say "ticket
contents" instead of "case contents".

**Maker pauses**

When the maker says they will run the request later, run `realm-reply-notice
--realm {test|prod} --situation pause` and send `chatMessage` verbatim. Write
nothing before or after it and no statement about what was or was not
recorded; the command records nothing. It says:

> We're waiting for your real-data request in **{Agent} in {Environment}**.
>
> When you return, tell us what happened and whether it matched what you
> expected. Don't include case contents, employee identifiers, tokens, or other
> secrets. The completed setup information stays in place.

**Finish without testing (untested)**

When the maker asks to finish without testing and no setup blocker remains, run
`record-realm-test --realm {test|prod} --prompt-category {CATEGORY} --result
untested` and show the controller's message with the real environment name:

> **The applicable ServiceNow setup steps in {Environment} are finished, but
> this destination integration remains untested.** Test this agent before
> employees use it.
>
> Your progress is saved at the destination Test-pane request. When you return,
> we'll continue there.

An untested finish is never a pass: no completion message, no final validation,
and no success claim. The Dev result does not substitute for Test, and a Test
result does not substitute for Prod. When the maker returns, run
`check-realm --realm {test|prod}` to recheck permission and the affected setup,
then resume at the Test-pane request; a later pass or fail replaces the
untested result.

If a setup blocker remains when the maker asks to finish without testing, run
the same `record-realm-test --result untested` command: while a connection or
runtime step is blocked the controller saves it as untested (never a pass) and
the block shows the specific validation-paused message ending with "This
destination remains untested; its setup isn't complete. Your progress is saved
at the destination connection repair." If an earlier step is only waiting (for
example an administrator reply), the command refuses and records nothing; show
that step's instruction instead. When the maker returns after the repair,
`check-realm` rechecks and resumes at the Test-pane request.

**Reply gives no usable result**

When the maker replies with only "Done", "Finished", or anything else that does
not say what the request returned, do not treat it as pass or fail and do not
run `record-realm-test`. Run `realm-reply-notice --realm {test|prod}
--situation no-result` and send `chatMessage` verbatim with nothing before or
after it. Keep asking until the reply says what was returned and whether it
matched. It says:

> What did the request from **{Agent} in {Environment}** return, and was that
> what you expected?

Record `record-realm-test` only when the maker states a result: pass when it
returned what they expected, fail when it did not.

**Result recorded as pass (lookup worked)**

Show the controller's completion message, replacing the generic "Test" or
"Prod" and "this agent" with the real environment and agent names so it reads:

> **Your {HR case|IT ticket} lookup worked in {Environment}.** {Agent} returned
> the {result reported} you expected for your account. This confirms the lookup
> for your tested account and this agent in {Environment}, not {case
> creation|ticket creation, the HR agent}, other employees' sign-in mapping, or
> {Prod behavior|release readiness}.

It says what was verified (the lookup for the tested account and this agent in
that environment) and what was not. Do not add anything about publishing or
what to do next.

### Recovery rules

Each situation below that has a `realm-reply-notice` command is controller-owned
fixed text. When the maker's reply matches, run the command, send `chatMessage`
verbatim with nothing before or after it (no preamble, no trailer, no sentence
about what was or was not recorded), and end your turn. Do not improvise these
replies from this guide.

- **Wrong environment tested.** When the result came from the Dev agent (or from
  Test while Prod is being checked), run `realm-reply-notice --realm
  {test|prod} --situation wrong-realm --reported-realm {dev|test}` and do not
  record the result. It says:

  > That's a {Dev|Test} result; we still need a result from **{Environment}**.
  >
  > Open **{Agent} in {Environment}** and run the request in that agent's
  > **Test pane**. Then tell us whether it returns the expected data.
- **Expected empty result.** Record it with `record-realm-test --result fail
  --failure-category empty-result`. The controller's checklist block already
  ends with the text below; send `chatMessage` verbatim and add nothing,
  including any statement about what was recorded. It opens with: "That doesn't
  match the result you expected. We'll check the available setup information
  for the agent in **{Environment}** before asking you for anything else." When
  no setup cause shows it continues: "We can't identify the cause from the
  information available yet." and asks: "Did the Test pane show an error or only
  an empty result?" It tells the maker to send only the error text, without case
  or ticket contents, employee identifiers, tokens, or other secrets. Never
  blame sign-in mapping, connection references or promotion without evidence.
- **Empty result that matches what the maker expected (no records).** Run
  `realm-reply-notice --realm {test|prod} --situation empty-matches` (nothing
  is recorded, and it is not a pass). It says:

  > That matches what you expected, but an empty result alone doesn't show
  > whether the agent can retrieve your HR data.
  >
  > Try a supported request for ServiceNow data you know exists for your
  > account, then tell us whether the result matches. You can also finish
  > without testing.

  In the IT agent it says "your IT data" instead of "your HR data".
- **Maker offers the Dev connection.** For example "Use the connection from Dev.
  It already works." Run `realm-reply-notice --realm {test|prod} --situation
  dev-connection`, then run `check-realm`. Do not assume a cross-environment
  connection can be selected directly. It says:

  > A working Dev connection doesn't tell us whether a usable connection is
  > available and linked to this agent in **{Environment}**.
  >
  > We'll check the destination's connection and agent link. You don't need to
  > resend applicable administrator confirmations.
- **Dev was never tested.** For example "Dev was configured, but we skipped the
  test. We've deployed to Test now." Run `realm-reply-notice --realm
  {test|prod} --situation dev-untested`, then run the realm check. Do not
  upgrade Dev's status or ask the maker to restart Dev. It says:

  > The Dev integration was left untested, so we don't have a working result
  > from that realm.
  >
  > This run will establish the result for **{Agent} in {Environment}**. We still
  > need its destination connection and agent link, followed by your real-data
  > request.
- **Target changes in Dev (environment, agent, instance, tenant, or signed-in
  user).** Get the Message from the controller
  (`target-change-handoff --change ...`, see `entry.md`) and send `chatMessage`
  verbatim; it records nothing, and earlier evidence is reused only after the
  permission and applicability checks pass.
- **Maker changes the realm.** For example "Check Prod instead." Say the
  following, using the destination the maker named and the other realm's name
  in the last sentence:

  > We'll switch to **{Agent} in {Environment}**, verify your permission there,
  > and revalidate the destination connection and agent link.
  >
  > The {Test|Prod} result won't count as a {Prod|Test} result.
- **Maker says the destination uses a different ServiceNow instance.** Pass the
  named instance with `--expected-instance "{INSTANCE}"` on `check-realm`. When
  it differs from the retained instance, the controller pauses the destination
  (`instancePause`), keeps the earlier result for its original instance, and
  returns the text below as `message`. Send it verbatim and do not continue
  with the new instance; every other realm command returns the same pause
  until the maker names the retained instance again. The resolution path for a
  different instance is an open product decision: do not invent one.
  `target-change-handoff --change instance` returns the same text while a
  Test or Prod run is active.
  > That changes the shared-instance assumption behind this promotion path. We
  > can't treat the earlier administrator setup as evidence for a different
  > instance.
  >
  > This destination run is paused while support for the different-instance path
  > is resolved. We'll retain the earlier result only for its original instance
  > and identify which setup information needs review.
- **Sign-in identity does not match (HR and IT).** Use this when the maker
  pastes a Test-pane error that says no ServiceNow user matches the sign-in
  claim value (or the user was not found for the sign-in claim), or a
  supported check shows the mismatch. Never infer it from a generic failure.
  Run `realm-reply-notice --realm {test|prod} --situation identity-mismatch`
  and send `chatMessage` verbatim (intro and ready-to-send message). Do not
  add a preamble such as "the setup checks passed" and do not add a trailer
  such as "tell me when it's fixed". The command needs the confirmed instance
  name and never includes a tenant ID. It says:

  > The supplied evidence shows that the sign-in claim value doesn't match the
  > administrator-confirmed ServiceNow user field.
  >
  > Send the message below to your ServiceNow administrator. It asks them to
  > review the mapping with your Entra administrator, including its existing
  > uses.
  >
  > Bring back their non-sensitive confirmation of the completed setup and exact
  > mapping. We'll recheck the affected setup before you repeat the request in
  > the destination agent's Test pane.
  >
  > Don't include employee identifiers or secrets. We'll retain unrelated
  > healthy work and recheck any dependencies affected by the identity repair.

  Then give this ready-to-send message:

  > During setup validation of **{Agent} in {Environment}**, the available
  > evidence identified a mismatch between the sign-in claim value and the
  > confirmed ServiceNow user field.
  >
  > Please review the intended claim-to-field mapping with the Entra
  > administrator for **{Instance URL}**. This identity setup is shared across
  > Dev, Test, and Prod.
  >
  > Do not change an existing OIDC configuration serving SSO or the Microsoft
  > Graph connector. Any coexistence conflict needs manual coordination using the
  > [coexistence guidance](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/declarative-agent-servicenow-hr-it#coexistence-with-the-microsoft-graph-connector-for-servicenow).
  >
  > **Please send back:** confirmation that the corrected configuration is saved
  > and supports this ESS setup, the exact User Claim and User Field, and any
  > changed Client ID or custom claim name that applies. If the
  > custom claim setup changed, include its exact configured name and
  > confirmation that it is complete, including the appropriate format and
  > populated source attribute for every intended employee.
  >
  > **If the mapping or compatibility is unresolved:** report the remaining
  > blocker instead of confirming completion.
  >
  > **Do not send employee identifiers, record contents, or secrets.**

  Re-check after the maker returns: record only the administrators'
  non-sensitive reply with the existing identity commands, then run
  `check-realm --realm {test|prod}`. A fresh Test-pane request is still
  required; earlier success does not validate the changed configuration.
- **Empty HR service areas (HR only).** Get the Message from the controller
  (`empty-service-areas-handoff --realm {test|prod}`) and send `chatMessage`
  verbatim; it records nothing. The text is:

  > The HR service-area list is empty. Employees using HR scenarios need one of
  > the ServiceNow roles `sn_hr_core.basic`, `sn_hr_core.manager`, or
  > `sn_hr_core.admin`.
  >
  > Ask your ServiceNow administrator to review the access for the account used
  > in this request. This skill doesn't check or assign those roles.
  >
  > Bring back their non-sensitive reply after any required access work is
  > complete. We'll recheck the applicable setup before you repeat the request in
  > the destination agent's Test pane.
- **Maker returns after leaving mid-validation.** Say:

  > We're continuing ServiceNow validation for **{Agent} in {Environment}**.
  >
  > We're rechecking your permission and the affected destination setup before we
  > continue. If those checks find no blocking issue, the outstanding step is
  > your real-data request in this agent's Test pane.

  Then run `check-realm --realm {test|prod}`. After an untested finish, its
  block already opens with this text; emit it verbatim.
- **Basic ADK setup is not complete (realm commands).** The controller gates
  every realm command: when the workspace is not Setup-complete it returns
  `status: setup-required` with the text below. Send `chatMessage` verbatim,
  hand over to `/setup`, and return afterward. It records nothing.

  > Before we can continue, we need to finish basic ADK setup. We'll hand over
  > to the setup skill and return here afterward.

  When setup finishes and the maker returns, run
  `realm-setup-handoff --situation complete` and send:

  > We'll continue with the ESS agent you just set up. You can select a
  > different supported ESS agent before we continue.

## Manual validation

| Check | Expected result |
|---|---|
| Dev has no lifecycle record, or lacks any administrator-confirmed value, then Test is checked | The block explains that the full ServiceNow setup runs for Test, asks for the instance, then walks the Entra administrator and ServiceNow administrator steps (⏳ until each reply is recorded) before checking the connection, topics, and portal. |
| Dev holds every administrator-confirmed value, then Test is checked | The block explains that the Dev sign-in setup and mapping are reused, shows no administrator step, and checks the Test connection, topics, portal URL, and real-data test. |
| Connection is on in Dev but missing in Test | The checklist shows ❌ on the connection step with "Validation is paused" and the return-after-repair wording; no menu path or Dev connection is suggested. |
| Connection exists in Test but is not bound to the agent | ❌ on the connection step; the text says the connection isn't linked to the agent and asks the maker to return once the supported repair is complete. |
| Connection in Test is disconnected | ❌ on the connection step; the text says it is disconnected and asks the maker to return once the supported repair is complete. |
| Instance or client ID differs from the expected value | ❌ on the connection step with the exact difference and the same return-after-repair wording. |
| Required topic off in Test or Prod | ❌ on the Topics step; "We'll enable the affected built-in topic and leave unrelated topics unchanged." The request is recorded; nothing is changed by the controller. |
| Portal URL not set in Test or Prod | ❌ on the Portal URL step; the block asks for the full HTTPS base URL. `record-realm-portal-url` records the request and confirms with "We'll save that URL for the {HR\|IT} agent in {Environment}." |
| Maker reports the expected data but the portal URL is missing | The pass is saved as reported (not complete); the block says the request returned the expected data but the agent is missing its portal URL and asks the URL question. |
| Maker names a different ServiceNow instance for the destination | The destination run is paused and the earlier result is retained for the original instance; other realm commands return the pause text. |
| Realm command before basic ADK setup is complete | `setup-required` with "Before we can continue, we need to finish basic ADK setup." Nothing is recorded. || Everything passes before the Test-pane request | Permission, connection, topics, and portal rows show ✅ and the real-data row shows ⏳ Waiting for you, followed by the Test-pane request. |
| A step fails | Later rows stay ⬜ and only the failing step's instruction is shown. |
| Prod is checked before Test is Ready | Prod is checked on its own. |
| Maker replies "Done" after fixing a step | `check-realm` reruns; the step turns ✅ without repeating earlier answers. |
| Maker asks to check ServiceNow after promotion without saying Test or Prod | We ask "Should we check Test?" and, on No, "Should we check Prod?" as Yes/No cards, and do not guess. |
| Account lacks access (denied) vs. access check could not finish | Denied: ask a maker with the Environment Maker role to run it. Inconclusive: validation is paused, not denied, retry the permission check. |
| Maker replies only "Done." to the Test-pane request | We don't record pass or fail and ask what the request from the agent in that environment returned and whether it matched. |
| Maker says "Finish without testing" and no setup blocker remains | `record-realm-test --result untested` saves it as untested (not a pass) and we show the untested-finish message. A later pass or fail replaces it. |
| Maker says "Finish without testing" while a setup blocker remains | `record-realm-test --result untested` saves it as untested when a connection or runtime step is blocked, and we show the validation-paused message plus "This destination remains untested; its setup isn't complete." |
| Maker tested the Dev agent instead of the promoted one | We ask for a result from the promoted environment and record nothing. |
| One request names both agents ("Check HR and IT in Prod") | `validation-notice --situation multi-agent` is the first action: "This skill validates one ESS agent per run. Which should we check first—**Employee Self-Service HR** or **Employee Self-Service IT**?" Plain chat, no preselected choice, no run, nothing recorded. |
| Maker's expected data came back empty | We check setup first, then ask whether the Test pane showed an error or only an empty result. |
| Pass is recorded in Test or Prod | The completion message says what was verified and what was not, and does not mention publishing. |
