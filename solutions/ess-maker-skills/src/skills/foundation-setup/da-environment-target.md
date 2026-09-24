<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Select a DA Target Environment

Use this shared path to resolve the Power Platform environment for DA foundation setup without Dataverse discovery or filtering.

## Resolve the service ring

Treat a recognized Copilot Studio hostname as authoritative ring evidence that completes ring selection. Map `copilotstudio.microsoft.com` and `copilotstudio.preview.microsoft.com` to `prod`, and infer `test` or `preprod` when the supplied URL explicitly identifies either ring. Whenever the current request and supplied target do not identify a ring, render this exact decision surface:

> Which Power Platform service ring should setup use?

Use the host's interactive single-selection control and offer exactly:

- **Production / Preview**
- **Pre-production**
- **Test**

Present all three labels unchanged with no default selection. Map **Production / Preview** to `prod`, **Pre-production** to `preprod`, and **Test** to `test`; retain the mapped value as `{RING}` and use it for every later operation in this invocation. A ring is resolved only by an explicit URL segment, supplied context, or the maker's selection from this template.

## Resolve the environment

When an environment URL is supplied, infer its environment ID and resolve its ring through **Resolve the service ring** above. Ask only when the environment ID is unclear.

When the target is not supplied, complete the shared account-selection step in `SKILL.md`. Before showing the shared authorization message or running environment discovery, resolve the ring through the exact decision surface above.

After the account and ring are selected, follow the shared authorization guidance in `SKILL.md`, then list environments visible to that account in the selected ring:

```text
python scripts/setup_existing_da.py list-environments \
  --ring "{RING}"
```

Parse `DA_ENVIRONMENT_LIST_JSON:` as the compact environment-selection result. Retain its `evidencePath` as the complete raw service evidence; the compact fields are sufficient for the picker, so read that file only when richer diagnostics or an unprojected service field is needed. Environment discovery is separate from agent discovery: do not run `list-agents`, infer agent visibility, or describe an empty environment result as an empty agent list. Present every environment returned by the Power Platform API without filtering by URL, Dataverse metadata, or environment type.

When environments are returned, show their display names and let the maker select one exact environment. Retain its exact environment ID and the selected ring for every later operation in this invocation.

When the command succeeds with an empty `environments` array, say:

> No Power Platform environments were listed for this account. No agent listing was performed.

Use the host's interactive single-selection control and offer exactly:

- **Use another account**
- **Use an environment URL**
- **Create a Power Platform environment**
- **Cancel setup**

Do not preselect a choice.

- For **Use another account**, return to **Choose the sign-in account** in `SKILL.md`, require a different account selection, and rerun `list-environments` only after that selection.
- For **Use an environment URL**, ask for the environment URL and continue with its inferred environment ID and ring. The later environment-scoped operation is authoritative for access; absence from the environment list is not proof that the supplied environment is inaccessible.
- For **Create a Power Platform environment**, say:

  > Open the [Power Platform admin center](https://admin.powerplatform.microsoft.com/), choose **Environments → New**, and create an environment for Copilot Studio. This DA setup does not require a Dataverse database. When the environment is ready, return here to list environments again or provide its environment URL.

  Stop until the maker confirms that the environment is ready or supplies its URL. Do not route into a Dataverse provisioning skill.

- For **Cancel setup**, make no changes and stop.

When environment discovery fails, parse `DA_ENVIRONMENT_LIST_ERROR_JSON:` and preserve it with `DA_ENVIRONMENT_LIST_ERROR_RESPONSE_JSON:` or `DA_ENVIRONMENT_LIST_ERROR_RESPONSE_TEXT:` as diagnostic evidence. When `authorizationFailure` is `true`, say that the selected account could not list its Power Platform environments and offer the same four choices. Do not convert an authorization failure into an empty environment list. For any other failure, report the observed blocker and stop.

## Retry setup with another target

Use this shared recovery surface when an environment was selected but its environment-scoped setup operation returns no selectable agents or products, or cannot load them.

State the observed result in maker language, then ask:

> How would you like to continue setup?

Use the host's interactive single-selection control and present these labels unchanged with the selection initially unset:

- **Try with a different user**
- **Try a different environment**
- **Cancel setup**

For **Try with a different user**, return to **Choose the sign-in account** in `SKILL.md`. After the maker selects or supplies a different user, rerun environment discovery for that account and continue from its environment picker.

For **Try a different environment**, retain the current account and ring, rerun `list-environments`, and continue from the returned environment picker.

For **Cancel setup**, make no changes and stop.

When direct agent lookup remains available after an empty visible-agent list, also offer **Use an agent URL**. Place it before the three shared choices, ask for the exact Copilot Studio agent URL when selected, and continue through direct inspection in `da-existing-dev.md`.
