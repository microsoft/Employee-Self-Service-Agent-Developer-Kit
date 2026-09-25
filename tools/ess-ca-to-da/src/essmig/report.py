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
from essmig.merge import ComponentResult, MergeResult, Outcome
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
) -> tuple[Path, Path]:
    """Write ``migration-report.md`` and ``migration-report.json``. Returns both paths."""
    destination.mkdir(parents=True, exist_ok=True)
    markdown_path = destination / "migration-report.md"
    json_path = destination / "migration-report.json"
    markdown_path.write_text(
        render_markdown(discovery, merged, package_path, import_result), encoding="utf-8"
    )
    json_path.write_text(
        json.dumps(render_json(discovery, merged, import_result), indent=2, default=str),
        encoding="utf-8",
    )
    return markdown_path, json_path


def render_json(
    discovery: DiscoveryResult,
    merged: MergeResult,
    import_result: ImportResult | None = None,
) -> dict[str, Any]:
    return {
        "generatedUtc": datetime.now(UTC).isoformat(timespec="seconds"),
        "vertical": merged.vertical,
        "sourceSolution": discovery.solution_unique_name,
        "assessment": assess(merged).to_json(),
        "delivery": import_result.to_json() if import_result is not None else None,
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


def render_markdown(
    discovery: DiscoveryResult,
    merged: MergeResult,
    package_path: Path | None,
    import_result: ImportResult | None = None,
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
    lines += ["", f"## Verdict: {verdict.verdict}", ""] + _verdict_body(verdict)
    if import_result is not None:
        lines += _delivery_body(import_result)
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
    lines += ["", "## Next steps", ""] + _next_steps(package_path, import_result)
    return "\n".join(lines) + "\n"


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


def _next_steps(package_path: Path | None, import_result: ImportResult | None = None) -> list[str]:
    package = f"`{package_path.name}`" if package_path is not None else "the package"
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
        "2. Import the package into your **development** environment. Import is a clean "
        "replace of the Declarative Agent in that environment only; Test and Production "
        "are not affected.",
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
