<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Setup Step 4 — ALM Baseline

Mark the step in progress:

```text
python scripts/setup_state.py update-step --step SETUP-04 --status in-progress
```

> **Recommended for Dev/Test:** Use an unmanaged solution with a custom
> publisher so new customizations are preserved and can later move to UAT or
> Production. This configuration is optional.

Discover eligible unmanaged solutions in the locked environment:

```text
python scripts/preferred_solution.py --url "{ENVIRONMENT_URL}" list
```

Parse `UNMANAGED_SOLUTIONS_JSON:`. Build one `vscode_askQuestions` option per
entry in `solutions`:

- Label: `displayName`, adding **(Current preferred)** when `isPreferred` is
  true.
- Description: unique name, version, publisher name, and publisher prefix.
- Add **Default publisher — not recommended** when `publisherIsDefault` is
  true.
- Append **Skip preferred solution setup** with the description
  `Continue without configuring an unmanaged preferred solution`.

Do not ask the maker to type a solution ID, unique name, publisher prefix, or
version. These values come from Dataverse.

If the maker selects **Skip preferred solution setup**, do not run `ENV-009`.
Persist the decision, complete `SETUP-04`, and continue:

```text
python scripts/setup_state.py skip-alm
python scripts/setup_state.py update-step --step SETUP-04 --status done
```

If `solutions` is empty, first show:

> We recommend an unmanaged solution with a custom publisher for Dev/Test
> environments. It preserves new customizations so they can later move to UAT
> or Production.

1. Open [Power Apps](https://make.powerapps.com).
2. Select the `{ENVIRONMENT_NAME}` environment.
3. Open `Solutions`.
4. Choose `New solution`.
5. Enter a `Display name`, `Name`, and `Version`.
6. Select or create a custom `Publisher`.
7. Choose `Create`, then select **Check again** here.

Then use `vscode_askQuestions` with exactly three options:

```json
[
  {
    "header": "Preferred solution",
    "question": "How would you like to continue?",
    "options": [
      {
        "label": "Create unmanaged solution",
        "description": "Follow the guidance, then check again"
      },
      {
        "label": "Check again",
        "description": "Rediscover eligible unmanaged solutions now"
      },
      {
        "label": "Skip preferred solution setup",
        "description": "Continue without this optional ALM configuration"
      }
    ],
    "allowFreeformInput": false
  }
]
```

This is the only manual creation path. If the maker selects **Skip preferred
solution setup**, run `python scripts/setup_state.py skip-alm`, then complete
`SETUP-04`.

After the maker selects a solution, configure it:

```text
python scripts/preferred_solution.py \
  --url "{ENVIRONMENT_URL}" \
  select --solution-id "{SOLUTION_ID}"
```

The command must not trust the picker label. After the maker answers, it
rediscovers the selected solution and reads `GetPreferredSolution()`. If the
selected solution is not preferred, it invokes `SetPreferredSolution`. It then
always reads `GetPreferredSolution()` again and continues only when the selected
ID is retained. This final verification is mandatory even when the solution was
already marked **(Current preferred)**. It then persists the solution ID, unique
name, publisher prefix, and version to setup state.

Parse `PREFERRED_SOLUTION_JSON:` and show a concise confirmation. Do not ask for
another confirmation.

Verify the resulting live Dataverse configuration:

```text
python scripts/flightcheck/cli.py \
  --checkpoint ENV-009 \
  --quiet-auth \
  --environment-url "{ENVIRONMENT_URL}"
```

If Dataverse rejects the cached session with HTTP 401, the command clears only
the local token cache, prompts for sign-in, and retries once. If the retry also
fails, show the final error once and keep `SETUP-04` in progress. Do not repeat
the command error in a second setup message.

When `ENV-009` passes, record it directly on `SETUP-04`:

```text
python scripts/setup_state.py record-step-result \
  --step SETUP-04 \
  --checkpoint ENV-009 \
  --mode automated
```

The step record owns only its checkpoint, note, mode, and timestamp. Solution
metadata remains in the `alm` object.

When the maker configures a preferred solution, complete only after `ENV-009`
passes. When the maker skips, no validation is required.

```text
python scripts/setup_state.py update-step --step SETUP-04 --status done
```
