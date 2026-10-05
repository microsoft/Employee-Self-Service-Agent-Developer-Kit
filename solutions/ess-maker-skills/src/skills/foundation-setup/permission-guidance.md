<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Foundation Setup Permission Guidance

Use this guidance whenever a Foundation Setup operation needs Microsoft sign-in, is denied, requires a Power Platform role, or hands work to an administrator.

## Evidence rules

- Treat VS Code command approval, Microsoft application approval, Power Platform environment access, agent access, and administrator roles as separate requirements.
- Let the requested service operation validate access. Do not reject an account through a blanket administrator-role check.
- An HTTP 401 means the operation needs authentication. An HTTP 403 means the selected account could not perform that operation. Neither result identifies a missing role by itself.
- Identify missing first-party application approval only when the authentication evidence explicitly reports missing application approval or consent. Do not reinterpret a generic 401 or 403 as an application-consent problem.
- Do not expose application IDs, OAuth scope values, access tokens, or raw authentication payloads in maker-facing guidance.
- An unavailable list is not an empty list. A denied environment or agent list does not prove that the environment or agent is absent.
- Published-agent sharing grants use of the published agent. It does not let setup retrieve that agent's content. Use the Microsoft login that created the exact agent.

## Roles and access boundaries

Use these names only in the relevant setup-path walkthrough or at the
operation that needs them:

| Operation                                                                                | Maker-facing requirement                                                                                                                                                                                                                                   |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| List accessible environments                                                             | The selected Microsoft login must be able to access the environment. Do not name an administrator role unless the service identifies one.                                                                                                                  |
| Read an existing agent for setup                                                         | Use the Microsoft login that created the exact agent. Setup reads the agent's metadata and content but does not edit or publish it. Sharing, another editor, an environment role, or an administrator role does not establish equivalent retrieval access. |
| Create a fresh agent                                                                     | The selected Microsoft login needs the **Environment Maker** security role in the target environment.                                                                                                                                                      |
| Create an environment, assign **Environment Maker**, or allocate Copilot Studio capacity | Hand the action to a **Power Platform administrator**. A Global Administrator may also be authorized, but do not present that broader role as the preferred path.                                                                                          |
| Verify environment capacity                                                              | Attempt verification with the selected account. Do not require an administrator role before the read and do not infer missing capacity when the read is unavailable.                                                                                       |

Do not use **System Administrator** as a general Foundation Setup prerequisite. Do not call the maker a **capacity administrator** or **environment administrator**.

## Forwardable administrator request

Render this request only when current evidence identifies the administrator
role and one exact action. The owning route supplies every value. Omit a field
when it does not apply; never render an empty placeholder.

**Message:**

### Administrator request: {ADMIN_ACTION_TITLE}

Please forward this section to the {ADMINISTRATOR_ROLE}.

**Requested action:** {EXACT_ADMINISTRATOR_ACTION}

**Environment:** {ENVIRONMENT_NAME}

**Environment URL:** {ENVIRONMENT_URL}

**Agent:** {AGENT_NAME}

**User:** {SETUP_ACCOUNT}

**Why this is needed:** {EVIDENCE_SUPPORTED_REASON}

**Open:** [{ADMIN_DESTINATION_NAME}]({ADMIN_DESTINATION_URL})

**When complete:** {RETURN_CONDITION}

**End message.**

Use one request for one action. Include a safe request or correlation ID only
when it helps the administrator locate the failed operation. Never include
tokens, credentials, authorization headers, customer content, raw response
bodies, unsupported billing guidance, or speculative role claims. Use the
ring-specific destination retained by the owning route; do not reconstruct it
from a logical ring name.

Setup remains incomplete while the request is outstanding. After the
administrator acts, rerun only the operation or Flight Check that owns the
requirement. Do not treat the maker's statement that the action is complete as
verification when an authoritative recheck is available.

## Setup-path people and role walkthrough

After the setup path, target environment, and Microsoft login are known,
but before the first agent inventory, exact-agent inspection, or agent-template
listing, render the matching walkthrough below. Render it once per setup path in
the invocation. Render it again when the effective setup path changes, including
an existing-agent path entering creation or a fresh-agent collision entering
existing-agent adoption, or when the maker changes the target environment or
login.

The availability answer is planning input, not proof that the selected account
has a role or can perform an operation. The later service operation remains
authoritative. Do not skip its permission check or convert the answer into
setup evidence.

After rendering either path table, ask exactly:

> Are the required people present?

Present **Yes, the required people are present**, **No, one or more required
people are unavailable**, and **Help me decide** with no preselected choice and custom entry disabled.
The question applies only to rows marked **Required now**. A conditional person
does not need to be present unless setup reaches the operation that needs them.

For **Help me decide**, follow the shared contract in `SKILL.md`. Explain which table rows are **Required now** and which are conditional, then ask which listed login or person is currently available. Recommend **Yes, the required people are present** only when every required-now row is available; recommend **No, one or more required people are unavailable** when any required-now row is unavailable. A conditional administrator row alone does not support recommending **No**.

### Existing-agent setup

**Message:**

**People and access for existing-agent setup**

| Person or access                               | Why setup may need them                                                             | When         |
| ---------------------------------------------- | ----------------------------------------------------------------------------------- | ------------ |
| Microsoft login used to create the exact agent | Verify the Dev-agent route and retrieve its content for the local workspace         | Required now |
| **Power Platform administrator**               | Change Copilot Studio capacity if setup confirms that a capacity change is required | Conditional  |

**Environment Maker**, another editor, and an administrator role do not replace
the Microsoft login used to create the exact agent. Setup will verify that login
against the exact agent before making local workspace changes. It will not edit
or publish the remote agent.

**End message.**

For **Yes, the required people are present**, continue to the existing-agent
operation. Do not record the answer as access evidence.

For **No, one or more required people are unavailable**, stop before the
existing-agent operation and say:

**Message:**

Setup paused before checking the existing agent. No environment, agent, role,
capacity, or local workspace change was made.

Use the Microsoft login that created the exact agent, choose another agent, or
return when that login is available. Setup cannot grant equivalent retrieval
access to another login.

**End message.**

Present **Use another account**, **Choose a different agent**, **Choose a
different environment**, and **Go back**. Route them through the owning setup
surface without claiming that an environment role will grant existing-agent
access.

### Fresh-agent setup

**Message:**

**People and access for fresh-agent setup**

| Person or access                                                                     | Why setup may need them                                                                                                    | When         |
| ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- | ------------ |
| Microsoft login with the **Environment Maker** security role in `{ENVIRONMENT_NAME}` | Create the fresh agent                                                                                                     | Required now |
| **Power Platform administrator**                                                     | Create an environment, assign **Environment Maker**, or change Copilot Studio capacity if setup reaches one of those needs | Conditional  |

Setup will let the creation operation verify the selected account. Confirming
that someone is available does not grant the role or prove authorization.

**End message.**

For **Yes, the required people are present**, continue through the owning setup
route. Do not record the answer as role evidence.

For **No, one or more required people are unavailable**, do not dispatch agent
creation and say:

**Message:**

Setup paused before creating a fresh agent. No agent, role, capacity, or local
workspace change was made.

A **Power Platform administrator** can assign **Environment Maker** to
`{SETUP_ACCOUNT}` in `{ENVIRONMENT_NAME}`.

**End message.**

Present **Use another account**, **Choose a different environment**, and **Go
back**. Apply the owning route's documented navigation for each choice. A route
may offer an additional read-only action only when that route defines and owns
the action.

## Microsoft authorization

Before opening the Microsoft account picker, explain that this sign-in is for the organization that owns the target environment and is separate from GitHub/Copilot sign-in. Signing in does not grant environment, agent, or administrator access; each requested operation verifies its own access.

When evidence explicitly identifies missing first-party application approval, say:

Render the shared **Forwardable administrator request** with:

- `{ADMIN_ACTION_TITLE}` — **Approve the Microsoft setup application**
- `{ADMINISTRATOR_ROLE}` — **Microsoft Entra administrator who manages application consent**
- `{EXACT_ADMINISTRATOR_ACTION}` — **Approve the Microsoft setup application for {REQUESTED_OPERATION} in this organization.**
- `{SETUP_ACCOUNT}` — the selected Microsoft login
- `{EVIDENCE_SUPPORTED_REASON}` — **The organization has not approved the Microsoft application for this operation. This is separate from the user's environment and agent access.**
- `{ADMIN_DESTINATION_NAME}` — **Microsoft Entra admin center**
- `{ADMIN_DESTINATION_URL}` — `https://entra.microsoft.com/`
- `{RETURN_CONDITION}` — **Let the requester know that application consent has been granted. They will return to Setup and retry {REQUESTED_OPERATION}.**

Omit the environment, environment URL, and agent fields. Setup has preserved
the work already completed.

Do not show this message for a generic authentication or authorization failure.

When the owning route's read-only account-establishment operation ends without
an authenticated account and the evidence does not identify a more specific
approval or access cause, say:

**Message:**

Microsoft sign-in was not completed. Setup has not continued to the requested
Microsoft operation.

**End message.**

Present **Retry Microsoft sign-in** and **Go back** with no preselected choice.
**Retry Microsoft sign-in** reruns the owning route's read-only
account-establishment operation with `--select-account`. **Go back** returns to
the choice surface that requested the operation. Do not infer picker
cancellation from a generic authentication failure. When the maker explicitly
says they cancelled the picker, setup may describe sign-in as cancelled without
reclassifying the service evidence.

When the maker explicitly named an expected account and `DA_AGENTBUILDER_AUTH_JSON:` reports a different account, do not silently adopt it. Say:

**Message:**

Microsoft sign-in completed as `{RETURNED_ACCOUNT}`, not `{EXPECTED_ACCOUNT}`. Setup will not use the returned operation result until you confirm which account to use.

**End message.**

Present **Continue with {RETURNED_ACCOUNT}**, **Choose another account**, and **Go back** with no preselected choice. Continuing adopts the returned account and its read-only result. Choosing another account reruns the same read-only operation with `--select-account`. Going back discards the result for routing purposes without claiming that the operation failed.

## Environment discovery

Before the first environment-list operation in an invocation, say:

**Message:**

**Environment access check:** Setup will use `{SETUP_ACCOUNT_OR_SELECTED_MICROSOFT_ACCOUNT}` to list the Power Platform environments this account can access. Setup does not require an administrator role for this read.

**End message.**

When environment discovery returns an authorization failure, say:

**Message:**

`{SETUP_ACCOUNT}` could not list Power Platform environments in the selected service ring. This does not prove that the target environment is missing or inaccessible by its direct URL.

Use another Microsoft login, provide the environment URL, or go back and choose another service ring.

**End message.**

Then use the existing environment-discovery recovery choices. Do not tell the maker to request **Environment Maker** or an administrator role for this read.

When the maker selects **Create a Power Platform environment**, explain that
environment creation is a **Power Platform administrator** operation. Show the
ring-correct Power Platform admin center instructions from the owning route and
stop until the maker confirms that the environment is ready or provides its
environment URL.

## Existing-agent discovery and access

Before the first direct operation against a selected exact agent in an invocation, say:

**Message:**

**Agent access check:** Setup will use `{SETUP_ACCOUNT}` to inspect `{AGENT_NAME_OR_SELECTED_AGENT}`. This must be the Microsoft login used to create the exact agent. The operation reads the agent's content; it does not edit or publish it. Sharing, another editor, an administrator role, or **Environment Maker** is not a substitute.

**End message.**

When agent inventory returns an authorization failure, say:

**Message:**

`{SETUP_ACCOUNT}` could not list agents in `{ENVIRONMENT_NAME}`. This does not prove that the environment has no agents.

If this is the Microsoft login used to create the intended agent, use its exact Microsoft Copilot Studio URL. Otherwise, use the creator login or try another environment.

**End message.**

Then use **Use a Microsoft Copilot Studio URL** and the existing target-recovery choices.

When direct inspection of an exact agent returns an authentication or authorization failure, say:

**Message:**

`{SETUP_ACCOUNT}` could not open `{AGENT_NAME_OR_SELECTED_AGENT}` for setup. Use the Microsoft login that created this exact agent.

Sharing the published agent, editor access, **Environment Maker**, and administrator access do not provide equivalent content-retrieval access.

**End message.**

Then use the existing different-account, different-agent, different-environment, and **Go back** routes. Do not recommend sharing, editor access, **Environment Maker**, or an administrator role as equivalent access to an existing agent.

## Fresh-agent creation

After the maker selects a specific agent to create and before dispatching the create operation, say:

**Message:**

Creating a fresh agent in `{ENVIRONMENT_NAME}` requires the **Environment Maker** security role. This role is used only for agent creation; by itself, it does not grant capacity-administration access or access to agents owned by another account.

**End message.**

When create returns an authentication or authorization failure that does not
explicitly identify a missing role or approval, say:

**Message:**

`{SETUP_ACCOUNT}` could not create the selected agent in `{ENVIRONMENT_NAME}`. The response does not identify a missing role or a specific administrator action. Nothing was changed.

**End message.**

For HTTP 401, return to Microsoft sign-in. After authentication completes,
return control to the owning creation route; that route owns its next operation
and request evidence. For HTTP 403, present **Use another account**, **Choose a
different environment**, and **Go back**. Do not offer an immediate retry. Do
not show a persona table or hand the generic result to an administrator. If the
evidence explicitly identifies missing first-party application approval, use
**Microsoft authorization** instead.

Only when the service evidence explicitly identifies missing creation access,
or the maker confirms that **Environment Maker** is unavailable, render:

Render the shared **Forwardable administrator request** with:

- `{ADMIN_ACTION_TITLE}` — **Grant agent-creation access**
- `{ADMINISTRATOR_ROLE}` — **Power Platform administrator**
- `{EXACT_ADMINISTRATOR_ACTION}` — **Assign the Environment Maker security role to {SETUP_ACCOUNT} in {ENVIRONMENT_NAME}.**
- `{ENVIRONMENT_NAME}` — the selected environment display name
- `{ENVIRONMENT_URL}` — the selected environment URL
- `{SETUP_ACCOUNT}` — the selected Microsoft login
- `{EVIDENCE_SUPPORTED_REASON}` — **This user needs Environment Maker to create the selected ESS agent in this environment.**
- `{ADMIN_DESTINATION_NAME}` — **Power Platform admin center**
- `{ADMIN_DESTINATION_URL}` — the retained `{POWER_PLATFORM_ADMIN_ORIGIN}/`
- `{RETURN_CONDITION}` — **Let the requester know that Environment Maker has been assigned. They will return to Setup and retry agent creation.**

Tell the maker to return after the administrator grants the access, then retry
creation. Present **Use another account**, **Choose a different environment**,
and **Go back**.

## Capacity verification and administration

Before running `ENV-CAPACITY-001` for the first time in an invocation, say:

**Message:**

**Capacity check:** Setup will attempt a read-only verification for `{ENVIRONMENT_NAME}`. Setup does not require an administrator role for this read. Administrator help is needed only if verified evidence requires a capacity change or the maker cannot access manual verification.

**End message.**

The `ENV-CAPACITY-001` state machine, exact maker-facing messages,
ring-specific administrator instructions, choices, evidence-application
commands, and render position belong to `da-existing-dev.md`. Do not reproduce
or append another capacity interaction from this file.

Apply the first matching outcome:

1. A successful read with a positive allocation needs no role guidance.
2. A successful read with no allocation proves that capacity is currently blocked. A **Power Platform administrator** can allocate capacity. Explain that local authoring remains available and keep the checkpoint unresolved until a recheck passes or the maker explicitly chooses the owning route's manual override after a second successful zero-allocation result.
3. An unavailable or denied read is **capacity not verified**. It is not proof that capacity is missing and must not trigger allocation instructions. Use the owning route's `Manual` path; when the maker cannot access capacity settings, identify a **Power Platform administrator** as the person who can verify them.
4. Manual attestation records only what the maker verified in Power Platform admin center. It does not convert an unavailable or denied API read into an automated pass. Preserve completed authoring work and the source evidence.
