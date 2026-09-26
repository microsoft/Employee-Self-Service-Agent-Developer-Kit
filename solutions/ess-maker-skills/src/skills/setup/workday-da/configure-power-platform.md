<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phases 4 and 5 - Connections and runtime

## Connections

Ask the maker to create or confirm exactly two connected Power Platform
connections in the selected environment:

- Workday OAuthUser, using the Workday SAML resource URL, token URL, and
  Workday OAuth client ID from controller state;
- Microsoft Dataverse, using the selected maker account.

Explain that Workday connector OAuth is another credential store and may open
its own sign-in. Do not ask the maker to paste connection IDs.

Run runtime discovery:

```powershell
python scripts/workday_connect.py runtime-plan
```

The command uses PAC to discover connected physical connections and one shared
Dataverse session to discover the installed connection references, reviewed
flows, selected agent, and User Context V2 topics.

- If exactly one connection exists for each connector, discovery is
  deterministic.
- If more than one exists, show safe display names and ask which connection to
  use, then rerun with `--workday-connection-id` and/or
  `--dataverse-connection-id`.
- If none exists or a connection is not connected, leave the phase waiting and
  show the exact missing connector.

After successful discovery, record evidence and set `connections` to
`complete`.

## Runtime approval and apply

Show one combined runtime plan:

- bind the two reviewed connection references;
- activate only the checked-in Workday flow catalog;
- authorize the exact agent to invoke those exact workflow IDs;
- redirect only an empty admin user-context scaffold to Workday User Context
  V2; and
- reread every changed record.

If the setup topic contains custom content, stop and preserve it. Do not
overwrite or approximate the topic.

Approve the exact plan:

```powershell
python scripts/workday_connect.py approve-plan --phase runtime --plan-json '{...}'
```

Apply using the returned hash and the same disambiguating connection IDs, if
any:

```powershell
python scripts/workday_connect.py runtime-apply --plan-hash "{hash}"
```

The controller rediscovers the current target, rejects stale approval, reuses
one Dataverse token for Python mutations, invokes the checked-in delegated
authorization script, and verifies bindings, flow state, authorization, and
User Context V2 after the write. Report permission issues only from an
explicit forbidden response, `[FAIL]` marker, ambiguity result, or nonzero
script exit.

Topic/business-scenario selection that is not represented by a reviewed
deterministic helper remains a concise manual handoff; do not expand it into a
per-topic internal checklist.
