"""The migration report — the tool's primary human-facing output.

The package is only half the deliverable. Measured against the real ESS templates,
a meaningful share of customer edits to out-of-box topics will conflict, because
ESS rewrote much of the content when it built the Declarative Agent. The honest
product, therefore, is an accurate classification plus a precise worklist: exactly
which topics came across, which were disabled and why, and which need a human.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from essmig.assessment import Assessment, assess
from essmig.deliver import ImportResult
from essmig.discovery import DiscoveryResult
from essmig.flows import FlowFindings
from essmig.knowledge import GraphConnection
from essmig.merge import ComponentResult, MergeResult, Outcome
from essmig.minimalbot_deliver import MinimalBotDeliveryResult
from essmig.projection import dump

_HEADLINE = {
    Outcome.MERGED: "Merged onto the new template",
    Outcome.CARRIED_NEW: "Carried across as-is (your own topics)",
    Outcome.CONFLICTED: "Needs your attention",
    Outcome.LOCKED: "Could not be carried (template-locked)",
    Outcome.MANUAL: "Re-create these in the agent's settings",
    Outcome.NO_TARGET: "Not recognised by this tool — check by hand",
    Outcome.BLOCKED: "Cannot be migrated (no Declarative Agent equivalent)",
    Outcome.UNCHANGED: "Unchanged from the shipped version",
    Outcome.FAILED: "Could not be processed",
}

_ORDER = (
    Outcome.CONFLICTED,
    Outcome.FAILED,
    Outcome.BLOCKED,
    Outcome.NO_TARGET,
    Outcome.MANUAL,
    Outcome.LOCKED,
    Outcome.CARRIED_NEW,
    Outcome.MERGED,
    Outcome.UNCHANGED,
)


def write_reports(
    destination: Path,
    discovery: DiscoveryResult,
    merged: MergeResult,
    *,
    package_path: Path | None = None,
    import_result: ImportResult | None = None,
    minimalbot_result: MinimalBotDeliveryResult | None = None,
    flow_findings: FlowFindings | None = None,
    flows_zip: Path | None = None,
    knowledge_bindings: list[GraphConnection] | None = None,
) -> tuple[Path, Path]:
    """Write ``migration-report.md`` and ``migration-report.json``. Returns both paths."""
    destination.mkdir(parents=True, exist_ok=True)
    markdown_path = destination / "migration-report.md"
    json_path = destination / "migration-report.json"
    markdown_path.write_text(
        render_markdown(
            discovery,
            merged,
            package_path,
            import_result,
            flow_findings,
            flows_zip,
            knowledge_bindings,
            minimalbot_result,
        ),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(
            render_json(
                discovery,
                merged,
                import_result,
                flow_findings,
                knowledge_bindings,
                minimalbot_result,
            ),
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return markdown_path, json_path


def render_json(
    discovery: DiscoveryResult,
    merged: MergeResult,
    import_result: ImportResult | None = None,
    flow_findings: FlowFindings | None = None,
    knowledge_bindings: list[GraphConnection] | None = None,
    minimalbot_result: MinimalBotDeliveryResult | None = None,
) -> dict[str, Any]:
    return {
        "generatedUtc": datetime.now(UTC).isoformat(timespec="seconds"),
        "vertical": merged.vertical,
        "sourceSolution": discovery.solution_unique_name,
        "assessment": assess(merged).to_json(),
        "delivery": import_result.to_json() if import_result is not None else None,
        "liveDelivery": (
            minimalbot_result.to_json() if minimalbot_result is not None else None
        ),
        "flows": _flows_json(flow_findings),
        "knowledgeSources": _knowledge_json(knowledge_bindings),
        "summary": {outcome.value: merged.count(outcome) for outcome in _ORDER},
        "components": [
            {
                **{k: v for k, v in asdict(result).items() if k != "conflicts"},
                "outcome": result.outcome.value,
                "conflicts": [
                    {
                        "path": conflict.path,
                        "reason": conflict.reason,
                        "yours": conflict.ours,
                        "ess": conflict.theirs,
                    }
                    for conflict in result.conflicts
                ],
            }
            for result in merged.results
        ],
        "skippedDuringDiscovery": discovery.skipped,
    }


def _flows_json(flow_findings: FlowFindings | None) -> dict[str, Any] | None:
    if flow_findings is None or not (flow_findings.carried or flow_findings.dangling):
        return None
    return {
        "carried": [
            {
                "workflowId": flow.workflow_id,
                "name": flow.name,
                "connectors": list(flow.connectors),
            }
            for flow in flow_findings.carried
        ],
        "dangling": list(flow_findings.dangling),
        "templateProvided": list(flow_findings.template_provided),
        "connectionsToRebind": flow_findings.connectors(),
    }


def _knowledge_json(bindings: list[GraphConnection] | None) -> list[dict[str, Any]] | None:
    if not bindings:
        return None
    return [
        {
            "schemaName": binding.knowledge_schema,
            "displayName": binding.display_name,
            "connectionName": binding.connection_name,
            "environmentVariable": binding.envvar_schema,
            "carriedValue": binding.value,
        }
        for binding in bindings
    ]


def render_markdown(
    discovery: DiscoveryResult,
    merged: MergeResult,
    package_path: Path | None,
    import_result: ImportResult | None = None,
    flow_findings: FlowFindings | None = None,
    flows_zip: Path | None = None,
    knowledge_bindings: list[GraphConnection] | None = None,
    minimalbot_result: MinimalBotDeliveryResult | None = None,
) -> str:
    verdict = assess(merged)
    lines: list[str] = [
        f"# ESS migration report — {merged.vertical.upper()}",
        "",
        f"Generated {datetime.now(UTC).isoformat(timespec='seconds')}",
        "",
        f"- Source (Custom Engine Agent): `{discovery.solution_unique_name}`",
        f"- Customizations found: **{len(discovery.components)}**",
    ]
    if package_path is not None:
        lines.append(f"- Package: `{package_path}`")
    if import_result is not None:
        state = "succeeded" if import_result.ok else "FAILED"
        lines.append(f"- Delivery to target: **{state}**")
    if minimalbot_result is not None:
        lines.append(f"- Live delivery: **{_live_state(minimalbot_result)}**")
    lines += ["", f"## Verdict: {verdict.verdict}", ""] + _verdict_body(verdict)
    if import_result is not None:
        lines += _delivery_body(import_result)
    if minimalbot_result is not None:
        lines += _live_delivery_body(minimalbot_result)
    lines += _flows_body(flow_findings, flows_zip, package_path)
    lines += _knowledge_body(knowledge_bindings)
    lines += ["", "## Summary", "", "| Outcome | Count |", "| --- | ---: |"]
    for outcome in _ORDER:
        count = merged.count(outcome)
        if count:
            lines.append(f"| {_HEADLINE[outcome]} | {count} |")

    conflicted = merged.conflicted
    if conflicted:
        lines += [
            "",
            "## What needs your attention",
            "",
            "You and ESS both changed the same thing in these topics. Your version was "
            "**not** discarded — it is listed below — but the package contains the ESS "
            "version, because choosing between them needs a human. Review each one and "
            "re-apply what you still need in Copilot Studio after importing.",
        ]
        for result in conflicted:
            lines += ["", f"### {result.display_name or result.suffix}", ""]
            lines.append(f"`{result.schemaname}`")
            if result.customer_state:
                verb = "disabled" if result.customer_state == "Inactive" else "enabled"
                lines += [
                    "",
                    f"> ⚠️ You had **{verb}** this topic. Because of the conflict the ESS "
                    "version was kept and that setting was **not** applied — re-apply it "
                    "by hand after import.",
                ]
            for conflict in result.conflicts:
                lines += [
                    "",
                    f"**{conflict.path}** — {conflict.reason}",
                    "",
                    "Your version:",
                    "",
                    "```yaml",
                    _snippet(conflict.ours),
                    "```",
                    "",
                    "ESS's version:",
                    "",
                    "```yaml",
                    _snippet(conflict.theirs),
                    "```",
                ]
            if result.customer_version:
                lines += [
                    "",
                    "Your complete version of this topic (so every edit — including any "
                    "that merged cleanly and is not listed as a conflict above — is on "
                    "record for manual re-application):",
                    "",
                    "```yaml",
                    _snippet(result.customer_version),
                    "```",
                ]

    upgraded = [result for result in merged.results if result.conversions]
    if upgraded:
        lines += [
            "",
            "## Automatically upgraded to supported building blocks",
            "",
            "These topics used an `AnswerQuestionWithAI` (generative answers) node only to "
            "phrase data the topic had already fetched. That has no Declarative Agent "
            "equivalent, so the tool rewrote each one into a deterministic `SetVariable` "
            "that renders the parsed record — exactly how the GA templates compose "
            "`InvokeFlow → ParseValue → SendActivity` responses. These topics stay active.",
            "",
        ]
        for result in upgraded:
            lines.append(f"- **{result.display_name or result.suffix}**")
            for note in result.conversions:
                lines.append(f"  - {note}")

    deprecated = [result for result in merged.results if result.deprecated]
    if deprecated:
        lines += [
            "",
            "## Disabled, but preserved",
            "",
            "These topics use building blocks the Declarative Agent does not support. "
            "Nothing was deleted — each topic was carried across with all of its logic "
            "intact, then marked `Inactive` and prefixed `[DEPRECATED]` so you can read "
            "it and rebuild it on supported pieces.",
            "",
        ]
        for result in deprecated:
            lines.append(f"- **{result.display_name or result.suffix}** — "
                         f"{'; '.join(result.unsupported)}")
            for guidance in result.guidance:
                lines.append(f"  - {guidance}")

    for outcome in (
        Outcome.BLOCKED,
        Outcome.MANUAL,
        Outcome.NO_TARGET,
        Outcome.LOCKED,
        Outcome.FAILED,
    ):
        section = [result for result in merged.results if result.outcome is outcome]
        if not section:
            continue
        lines += ["", f"## {_HEADLINE[outcome]}", ""]
        for result in section:
            lines.append(
                f"- **{result.display_name or result.suffix}** "
                f"(`{result.component_type_label}`) — {result.detail}"
            )
            if result.configuration:
                lines += ["", "  Your configuration:", "", "```yaml", result.configuration, "```"]

    carried = [
        result
        for result in merged.results
        if result.outcome in (Outcome.MERGED, Outcome.CARRIED_NEW) and not result.deprecated
    ]
    if carried:
        lines += ["", "## Carried across cleanly", ""]
        for result in carried:
            lines.append(f"- {result.display_name or result.suffix} — {result.detail}")

    if discovery.skipped:
        lines += [
            "",
            "## Skipped during discovery",
            "",
            "Found in your environment but out of scope for this migration.",
            "",
        ]
        for entry in discovery.skipped:
            lines.append(f"- `{entry.get('schemaname')}` — {entry.get('reason')}")

    lines += ["", "## What changes for your employees", ""] + [
        f"- {impact}" for impact in verdict.employee_impact
    ]
    lines += ["", "## Next steps", ""] + _next_steps(package_path, import_result, flow_findings)
    return "\n".join(lines) + "\n"


def _knowledge_body(bindings: list[GraphConnection] | None) -> list[str]:
    if not bindings:
        return []
    lines = ["", "## Knowledge sources", ""]
    lines += [
        "Your agent carries ServiceNow knowledge source(s). Each one reaches its "
        "content through a Graph-connector connection that is specific to the "
        "environment it was set up in, so the connection is carried as a starting "
        "point and must be **rebound in the target** before the source returns "
        "results:",
        "",
    ]
    for binding in bindings:
        lines.append(
            f"- **{binding.display_name}** — `{binding.knowledge_schema}` "
            f"(connection: `{binding.connection_name}`)"
        )
    lines += [
        "",
        "After importing the agent package, open the agent's knowledge settings, "
        "rebind each connection above to a connection in the target environment, "
        "and confirm the source returns results. Until it is rebound the source is "
        "present but cannot retrieve anything.",
    ]
    return lines


def _flows_body(
    flow_findings: FlowFindings | None, flows_zip: Path | None, package_path: Path | None
) -> list[str]:
    if flow_findings is None or not (flow_findings.carried or flow_findings.dangling):
        return []
    lines = ["", "## Cloud flows", ""]
    if flow_findings.carried:
        zip_name = f"`{flows_zip.name}`" if flows_zip is not None else "a separate flows solution"
        package = f"`{package_path.name}`" if package_path is not None else "the agent package"
        lines += [
            "Topics you migrated call cloud flows. The agent package can *reference* a "
            "flow but cannot *contain* one — a flow is an environment component, "
            f"installed by a solution import. So these flows travel in {zip_name}, which "
            "you must import **before** the agent package:",
            "",
        ]
        for flow in flow_findings.carried:
            binds = f" (connections: {', '.join(flow.connectors)})" if flow.connectors else ""
            lines.append(f"- **{flow.name}** — `{flow.workflow_id}`{binds}")
        lines += [
            "",
            f"1. Import {zip_name} into the target environment. The flows keep their "
            "original ids, so the migrated topics' references resolve.",
        ]
        connectors = flow_findings.connectors()
        if connectors:
            lines.append(
                "2. Rebind each flow's connection — the connection references travel "
                f"unbound and must be pointed at a connection in the target: "
                f"{', '.join(connectors)}. Turn the flows on."
            )
            lines.append(f"3. Import {package}.")
        else:
            lines.append(f"2. Import {package}.")
    if flow_findings.dangling:
        lines += [
            "",
            "> ⚠️ These flows are invoked by a migrated topic but their definitions are "
            "not available to carry (they were not in the source, or the source was a "
            "live environment this tool cannot read flow definitions from). **The agent "
            "import will fail** until each one exists in the target — re-create it, or "
            "re-run the migration from an exported package that contains it:",
            "",
        ]
        lines += [f"- `{flow_id}`" for flow_id in flow_findings.dangling]
    return lines


def _live_state(result: MinimalBotDeliveryResult) -> str:
    if result.dry_run:
        return "dry-run (nothing written)" if result.ok else "dry-run FAILED"
    return "delivered" if result.ok else "FAILED"


def _live_delivery_body(result: MinimalBotDeliveryResult) -> list[str]:
    lines = ["", "## Live delivery to the target Declarative Agent", ""]
    verb = "would apply" if result.dry_run else ("applied" if result.ok else "attempted")
    lines.append(
        f"Customer edits to shipped topics are overlaid live via the MinimalBot "
        f"components API ({verb}) to bot `{result.bot_id}` on the **{result.ring}** "
        f"ring: {result.updated} topic edit(s). {result.detail}"
    )
    if result.dry_run:
        lines += [
            "",
            "> This was a **dry-run** — nothing was written. Review the planned changes "
            "below, then re-run with `--deliver-apply` to write them to the live agent.",
        ]
    if result.renamed_to:
        verb_rename = "would rename" if result.dry_run else "renamed"
        lines += [
            "",
            f"The agent was {verb_rename} to **{result.renamed_to}** (the main-panel "
            "agent name, carried on the bot entity).",
        ]
    if result.planned:
        lines += [
            "",
            "### Shipped-topic edits delivered live",
            "",
            "| Action | Component kind | Schema name |",
            "| --- | --- | --- |",
        ]
        lines += [
            f"| {change.action} | {change.kind} | `{change.schema_name}` |"
            for change in result.planned
        ]
    if result.deferred:
        lines += [
            "",
            "### New topics routed to the ALM package import",
            "",
            "These are brand-new, customer-authored topics with no counterpart on the "
            "template. They cannot be compiled to the components-API runtime form, so "
            "they ride in the ALM package instead — re-run with `--import` (or import "
            "the built package manually).",
            "",
            "| Component kind | Schema name |",
            "| --- | --- |",
        ]
        lines += [
            f"| {change.kind} | `{change.schema_name}` |" for change in result.deferred
        ]
    if result.notes:
        lines += [
            "",
            "### Edits that need your attention",
            "",
            "These per-field edits touch expression, structured, or template fields "
            "that could not be fully overlaid onto the live component. Review each and "
            "finish it by hand in the agent:",
            "",
        ]
        lines += [f"- {note}" for note in result.notes]
    if not result.ok and not result.dry_run:
        lines += [
            "",
            f"- Endpoint: `{result.endpoint}`",
            f"- Reason: {result.detail}",
        ]
    return lines


def _delivery_body(import_result: ImportResult) -> list[str]:
    lines = ["", "## Delivery to the target Declarative Agent", ""]
    if import_result.ok:
        lines += [
            f"The package was imported into the target agent "
            f"`{import_result.schema_name}`. {import_result.detail} This replaced the "
            "agent's content in the target environment's **development** ring only — "
            "Test and Production are untouched until you promote.",
        ]
        if import_result.operation_url:
            lines.append(f"Track the async import at: `{import_result.operation_url}`")
    else:
        lines += [
            f"The import into `{import_result.schema_name}` **failed** and the target "
            "agent was not changed.",
            "",
            f"- Endpoint: `{import_result.endpoint}`",
            f"- Reason: {import_result.detail}",
            "",
            "The package on disk is valid; you can retry the import once the cause is "
            "resolved, or import it by hand.",
        ]
    lines.append(
        "\nItems listed under *Re-create these in the agent's settings* below are **not** "
        "carried by this import — the package format cannot hold them. Apply those by "
        "hand in the target agent after the import."
    )
    return lines


def _verdict_body(verdict: Assessment) -> list[str]:
    lines: list[str] = []
    if verdict.blockers:
        lines += [
            "These cannot be migrated. Decide whether to accept the loss or wait for "
            "the capability before you cut employees over.",
            "",
        ]
        lines += [f"- {blocker}" for blocker in verdict.blockers]
    if verdict.worklist:
        if lines:
            lines.append("")
        lines += ["Before you publish, you need to:", ""]
        lines += [f"- {item}" for item in verdict.worklist]
    if not lines:
        lines.append(
            "Everything you customized carried across with no conflicts and nothing "
            "disabled. Test the package, then publish."
        )
    return lines


def _next_steps(
    package_path: Path | None,
    import_result: ImportResult | None = None,
    flow_findings: FlowFindings | None = None,
) -> list[str]:
    package = f"`{package_path.name}`" if package_path is not None else "the package"
    flows_first = (
        "Import the flows solution first (see *Cloud flows* above), then "
        if flow_findings is not None and flow_findings.needs_flow_import
        else ""
    )
    if import_result is not None and import_result.ok:
        return [
            "1. Nothing in this migration touched your Custom Engine Agent — it is still "
            "running, unchanged.",
            "2. The package was already imported into the target Declarative Agent's "
            "**development** environment. Open it and verify it there before promoting; "
            "Test and Production were not affected.",
            "3. Rebind connections in the target environment. Connection ids and secrets "
            "are deliberately not included in the package.",
            "4. Apply any *Re-create these in the agent's settings* items above by hand, "
            "then work through the conflicts and disabled topics, and promote.",
        ]
    if import_result is not None and not import_result.ok:
        return [
            "1. The import failed and the target agent was not changed (see *Delivery* "
            "above). Resolve the cause and retry `migrate --import`, or import "
            f"{package} by hand.",
            "2. Nothing touched your Custom Engine Agent — it is still running, unchanged.",
        ]
    return [
        f"1. Review the sections above. Nothing in {package} touches your Custom Engine "
        "Agent — it is still running, unchanged.",
        f"2. {flows_first}import the package into your **development** environment. Import "
        "is a clean replace of the Declarative Agent in that environment only; Test and "
        "Production are not affected.",
        "3. Rebind connections in the destination environment. Connection ids and secrets "
        "are deliberately not included in the package.",
        "4. Work through the conflicts and the disabled topics, then publish and promote.",
    ]


def _snippet(node: Any, limit: int = 1600) -> str:
    text = dump(node).rstrip() if node is not None else "(removed)"
    return text if len(text) <= limit else text[:limit] + "\n# ... truncated"


def summarize(results: list[ComponentResult]) -> str:
    """One-line console summary."""
    counts: dict[Outcome, int] = {}
    for result in results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
    return ", ".join(
        f"{counts[outcome]} {outcome.value}" for outcome in _ORDER if counts.get(outcome)
    )
