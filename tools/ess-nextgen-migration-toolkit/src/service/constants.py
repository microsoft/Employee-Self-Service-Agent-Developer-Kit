"""Shared constants for the ESS Migration Toolkit."""

# Supported execution modes for the ESS migration pipeline.
SUPPORTED_MODES = ("READONLY", "WRITEBACK")

# ESS customer-facing report filename (the product deliverable). The generic
# framework defaults to a neutral name; the ESS toolkit supplies this one.
REPORT_FILENAME = "migration_report.md"

# ESS-owned base (managed) solution unique names, sourced from the HR/IT
# solution manifests (Solution.xml -> <UniqueName>). Customization discovery
# queries dependencies-for-uninstall against these fixed solutions based on the
# selected agent's vertical.
ESS_SOLUTION_BY_VERTICAL = {
    "hr": "msdyn_CopilotForEmployeeSelfServiceHR",
    "it": "msdyn_CopilotForEmployeeSelfServiceIT",
}

# Managed ESS "extension pack" solutions (the vertical integrations shipped OOB),
# by unique name (msdyn_ prefix).
ESS_EXTENSION_SOLUTIONS = (
    "msdyn_EssHRADPHCM",
    "msdyn_EssHRServiceNowHRSD",
    "msdyn_EssHRServiceNowITSM",
    "msdyn_EssHRServiceNowLiveAgent",
    "msdyn_EssHRSuccessFactorsHCM",
    "msdyn_EssHRWorkdayHCM",
    "msdyn_EssITServiceNowHRSD",
    "msdyn_EssITServiceNowITSM",
    "msdyn_EssITServiceNowLiveAgent",
    "msdyn_EssITSuccessFactorsHCM",
    "msdyn_EssITWorkdayHCM",
)

# All OOB ESS-owned managed solutions: the base HR/IT copilots plus the extension
# packs. Customization discovery treats a lone-layer component as untouched OOB
# when its layer belongs to one of these; a layer in any other solution (e.g. the
# unmanaged "Active" layer) signals a customer customization or net-new component.
OOB_ESS_SOLUTIONS = frozenset(ESS_SOLUTION_BY_VERTICAL.values()) | frozenset(
    ESS_EXTENSION_SOLUTIONS
)

# Copilot (bot) component sub-types — the botcomponent.componenttype option set.
# Full catalog kept for reference/reporting; the migration allow-list below is a
# subset of these keys.
# Ref: https://learn.microsoft.com/en-us/power-apps/developer/data-platform/webapi/reference/botcomponent?view=dataverse-latest#properties
BOT_COMPONENT_TYPE_LABELS = {
    0: "Topic",
    1: "Skill",
    2: "Bot variable",
    3: "Bot entity",
    4: "Dialog",
    5: "Trigger",
    6: "Language understanding",
    7: "Language generation",
    8: "Dialog schema",
    9: "Topic (V2)",
    10: "Bot translations (V2)",
    11: "Bot entity (V2)",
    12: "Bot variable (V2)",
    13: "Skill (V2)",
    14: "Bot File Attachment",
    15: "Custom GPT",
    16: "Knowledge Source",
    17: "External Trigger",
    18: "Copilot Settings",
    19: "Test Case",
}

# Component sub-types the toolkit migrates today. Only Topic (V2) for now;
# maintained separately from the full catalog so the allow-list can grow
# independently as more component types are supported.
ALLOWED_BOT_COMPONENT_TYPES = frozenset({9})

# Bot schemaname prefixes for the ESS HR/IT agents (lowercase). A migrated
# component's schemaname (e.g. "msdyn_copilotforemployeeselfservicehr.topic.X")
# must contain one of these — a partial match — so components layered from other
# agents (e.g. the shared "...core" agent) are excluded.
ESS_AGENT_SCHEMANAMES = (
    "msdyn_copilotforemployeeselfservicehr",
    "msdyn_copilotforemployeeselfserviceit",
)
