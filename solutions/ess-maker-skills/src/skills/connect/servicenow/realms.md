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

## Tenant foundation and deployment scope

The Microsoft Entra application and ServiceNow administrator work is a
reusable tenant foundation. The package connection, runtime wiring, topics,
and maker validation are environment-and-agent specific.

- For a controller-verified Test or Production promotion in the same ALM
  family and Microsoft Entra tenant, reuse the recorded Dev tenant foundation
  and continue at Connections. Do not repeat either administrator handoff.
- Never reuse the foundation silently when the ServiceNow instance, the Entra
  application (client) ID, or the tenant differs from Dev. The controller keeps
  the stage blocked and returns the exact differences. Show them. Do not
  re-issue an administrator handoff automatically.
- Connect does not promote or publish an agent. In Test and Production it reads
  topic states and the portal value and never changes them. A fix belongs in
  Dev, followed by a new promotion and a new check.

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

Test requires Dev to be Ready. Production requires Test to be Ready. If the
prerequisite is not Ready, keep that realm active and show only its unfinished
stage.

- Maker said the agent was promoted, with no link:

  ```text
  python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} discover-realm-target --realm {test|prod}
  ```

- Maker pasted the Test or Production agent link:

  ```text
  python scripts/connect_servicenow_da.py --provider {SELECTED_PROVIDER} --agent-slug {SELECTED_AGENT_SLUG} discover-realm-target --agent-link "{PASTED_AGENT_LINK}"
  ```

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
`nextPhaseId` for every message. When `foundationReused` is true, say once that
the existing tenant foundation is reused. Test and Production use the same
three stages, completed separately per realm:

| Stage | Result |
|---|---|
| Connections | Done when the bound ServiceNow connection uses Microsoft Entra ID User Login, the Dev instance and Entra client ID, and is Connected. Otherwise show `connectionHandoff` for the maker. A difference is blocked, never auto-fixed. |
| Runtime configuration | Done when promoted topic states and the portal URL match Dev, read-only. Otherwise show `observations`. |
| Maker validation | The maker runs the ServiceNow scenario in this realm's Test pane. Record it with `record-realm-test --realm {test|prod} --prompt-category {CATEGORY} --result {pass|fail}`. |

Use `check-realm --realm {test|prod}` to re-read the stages after the maker
completes a handoff, and `select-realm --realm {dev|test|prod}` to switch
between realms that were already discovered. When Test or Production is Ready,
publishing and non-maker validation happen after this guided lifecycle.
