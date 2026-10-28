# Workday OSS native installer runtime contract

## Source and ordering

The source manifest is fixed to `samples/Workday`:

1. `WorkdayOSSTemplateConfigurationSetup.yaml`
2. the 11 folders listed by `samples/Workday/Employee/README.md`
3. the 5 folders listed by `samples/Workday/Manager/README.md`

Each result includes the repository-relative source path and SHA-256. A subset
retains this order and still includes the shared setup topic first.

## Authentication boundary

The process attaches over CDP to an existing signed-in exact-agent Copilot
Studio page on the production or preview host. Details, Overview, Tools, and
adaptive topic-editor routes are accepted. It observes one authenticated POST
to:

```text
{validated-environment-host}/copilotstudio/minimalBots/api/{agentId}/components?api-version={observed-version}
```

The host, agent path, and nonempty API version are validated before use. The
authorization header is copied only into process memory. The browser context's
request client supplies that context's cookies. No token cache, cookie export,
storage-state file, HAR, request-header file, or authentication diagnostic is
created.

The script stops on 401/403. It does not switch identity, downgrade to
Dataverse, alter TLS validation, or derive another host.

## Create contract

YAML is converted by `scripts/agentbuilder_object_model.py`. The PUT body uses a
fresh read `changeToken`, one `BotComponentInsert`, one `DialogComponent`, and
the empty non-topic change collections used by the current native update
contract.

The component identity is deterministic:

```text
UUIDv5(NAMESPACE_URL, "ess-adk:workday-oss:{agentId}:{schemaName}")
```

`extensionData.UseProvidedBotComponentId` is true. This makes an indeterminate
write reconcilable by exact ID without replaying it.

## Duplicate and verification rules

Before creation, existing dialog components are indexed by case-insensitive
`displayName` and `schemaName`.

- one match: preserve it;
- no match: create it;
- multiple matches or display/schema resolving to different components: fail.

After every write, the script requires response identity and a fresh component
read. Read-back must match ID, schema, display name, active state/status, and
canonical Object Model content, with no blocking diagnostics. The next topic is
not attempted until that verification succeeds.

The installer never updates, deletes, deactivates, publishes, or runtime-tests
topics.
