"""ESS-specific constants: solution names, schema prefixes, component types.

Two agent shapes are in play:

* **CA** — the Custom Engine Agent. A Dataverse managed solution
  (``msdyn_CopilotForEmployeeSelfServiceHR``) whose pieces are ``botcomponent``
  rows with schema names like ``msdyn_copilotforemployeeselfservicehr.topic.Foo``.
* **DA** — the Declarative Agent. An ALM *templated package* whose pieces are
  entries in a single ``agent.yml``, with schema names like
  ``gptagent_copilotforemployeeselfservicehr.topic.Foo``.

The shared join key between the two is the **schema-name suffix** — everything
after the agent prefix (``topic.Foo``). See :func:`schema_suffix`.
"""

from __future__ import annotations

# The ESS domain agents that sit *behind* the Core hub. "Vertical" is the historical
# name for them, kept because so much of the pipeline is keyed on it.
VERTICALS = ("hr", "it")

# Every first-class Declarative Agent this tool migrates. Core is the hub/router
# agent; HR and IT are the domain agents it delegates to (its instructions say so).
# Each target is migrated independently — its own CA source, its own DA template,
# its own package. Core is emphatically NOT shared components folded into HR/IT.
TARGETS = ("core", "hr", "it")

# --- CA (Dataverse) ---------------------------------------------------------

CA_PREFIX = "msdyn_"

# ESS-owned base (managed) solution unique names, from each solution manifest's
# Solution.xml -> <UniqueName>. Discovery walks dependencies-for-uninstall
# against the base solution for the selected target.
CA_SOLUTION_BY_VERTICAL = {
    "core": "msdyn_CopilotForEmployeeSelfServiceCore",
    "hr": "msdyn_CopilotForEmployeeSelfServiceHR",
    "it": "msdyn_CopilotForEmployeeSelfServiceIT",
}

# The shared "core" solutions. Their components are layered into both verticals and
# a large share of the DA's out-of-box content descends from them, so they are part
# of the OOB baseline even though they are never the discovery entry point.
CA_CORE_SOLUTIONS = (
    "msdyn_CopilotForEmployeeSelfService",
    "msdyn_CopilotForEmployeeSelfServiceCore",
)

# Managed ESS "extension pack" solutions (the vertical integrations shipped OOB).
# Verified against each solution manifest's <UniqueName>: several do NOT carry the
# folder name's "HCM" suffix, so do not infer these from folder names.
CA_EXTENSION_SOLUTIONS = (
    "msdyn_EssHRADP",
    "msdyn_EssHRServiceNowHRSD",
    "msdyn_EssHRServiceNowITSM",
    "msdyn_EssHRServiceNowLiveAgent",
    "msdyn_EssHRSuccessFactors",
    "msdyn_EssHRWorkday",
    "msdyn_EssITServiceNowHRSD",
    "msdyn_EssITServiceNowITSM",
    "msdyn_EssITServiceNowLiveAgent",
    "msdyn_EssITSuccessFactors",
    "msdyn_EssITWorkday",
    "msdyn_EssWorkdayRuntime",
    # Predecessors of the Ess* packs, still present in older installs.
    "msdyn_EmployeeSelfServiceServiceNowHRSD",
    "msdyn_EmployeeSelfServiceITHelpdeskServiceNowITSM",
    "msdyn_EmployeeSelfServiceServiceNowLiveAgent",
    "msdyn_EmployeeSelfServiceHRSuccessFactors",
    "msdyn_EmployeeSelfServiceHRWorkday",
)

# Every OOB ESS-owned managed solution. A component whose *only* layer sits in one
# of these is untouched out-of-box content and is not a customization. A layer in
# any other solution — including the unmanaged ``Active`` layer — is a customer
# change or a net-new component.
OOB_CA_SOLUTIONS = (
    frozenset(CA_SOLUTION_BY_VERTICAL.values())
    | frozenset(CA_EXTENSION_SOLUTIONS)
    | frozenset(CA_CORE_SOLUTIONS)
)

# CA extension-pack solutions that HAVE a shipped Declarative Agent equivalent.
# Their content is folded into the HR/IT DA agents (there is no standalone DA agent
# per pack — confirmed against ESSVivaCopilot sources/dev/solutions/EssDA*). A
# customization to one of these packs can therefore be migrated into HR/IT.
#
# MAINTAINER NOTE: this is the *current* DA coverage. When a new EssDA* pack ships,
# add its CA counterpart here. Anything in CA_EXTENSION_SOLUTIONS not listed below
# has no DA home yet, so its customizations are reported as **blocked** rather than
# folded into an agent where their referenced pack does not exist.
PORTED_EXTENSION_SOLUTIONS = frozenset(
    {
        "msdyn_EssHRServiceNowHRSD",
        "msdyn_EssHRWorkday",
        "msdyn_EssITServiceNowITSM",
        "msdyn_EssITWorkday",
    }
)

# CA extension packs with no Declarative Agent equivalent in this ESS release. A
# customer customization that belongs to one of these cannot be migrated: there is
# nothing in any DA agent for it to attach to. Reported as blocked, with the pack
# named, so the customer knows exactly what did not come across.
NON_PORTED_EXTENSION_SOLUTIONS = frozenset(CA_EXTENSION_SOLUTIONS) - PORTED_EXTENSION_SOLUTIONS


def non_ported_pack_of(solutions: object) -> str | None:
    """The first non-ported extension pack among ``solutions``, if any.

    ``solutions`` is any iterable of Dataverse solution unique names (typically a
    component's layer solution names). Returns the pack's unique name so the report
    can name it, or ``None`` when the component does not belong to a non-ported pack.
    """
    if not isinstance(solutions, (list, tuple, set, frozenset)):
        return None
    for name in solutions:
        if isinstance(name, str) and name in NON_PORTED_EXTENSION_SOLUTIONS:
            return name
    return None

# botcomponent.componenttype option set.
# Ref: https://learn.microsoft.com/power-apps/developer/data-platform/webapi/reference/botcomponent
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
    20: "Custom Metric Definition",
}

# Sub-types this tool migrates. Each maps onto a DA ``agent.yml`` component kind
# (see essmig.projection.DA_KIND_BY_COMPONENT_TYPE). Deliberately wider than the
# previous toolkit, which only ever looked at Topic (V2).
MIGRATABLE_COMPONENT_TYPES = frozenset({9, 12, 15, 16, 20})

# Additional customized types the tool detects and *reports* even though it does
# not carry them structurally into ``agent.yml``: agent-level settings and content
# that a package cannot ship (re-created by hand after import, with their
# configuration reproduced in the report), plus skills, which the Declarative Agent
# models as connected agents/actions rather than as a carried component. Surfacing
# these — instead of dropping them silently at discovery — is what lets the report
# tell a customer *everything* that will not come across on its own.
#   14 Bot File Attachment · 18 Copilot Settings · 19 Test Case (evaluations)
#    1 Skill · 13 Skill (V2)
REPORT_ONLY_COMPONENT_TYPES = frozenset({1, 13, 14, 18, 19})

# Every type the owned-component sweep asks Dataverse for. Net-new components of
# any other type still arrive via the dependency path and are reported too; this
# set only bounds the (per-component) layer queries for *in-place edits* of
# out-of-box content.
DETECTABLE_COMPONENT_TYPES = MIGRATABLE_COMPONENT_TYPES | REPORT_ONLY_COMPONENT_TYPES

# Lowercase CA agent schema-name prefixes. A component's schemaname must start
# with one of these; components layered from another agent are out of scope.
# ``core`` is the hub/router bot (``...core``), a distinct agent from the legacy
# monolith ``msdyn_copilotforemployeeselfservice`` — do not confuse the two.
CA_AGENT_SCHEMANAMES = {
    "hr": "msdyn_copilotforemployeeselfservicehr",
    "it": "msdyn_copilotforemployeeselfserviceit",
    "core": "msdyn_copilotforemployeeselfservicecore",
}

# --- DA (ALM package) -------------------------------------------------------

DA_PREFIX = "gptagent_"

DA_SCHEMANAME_BY_VERTICAL = {
    "core": "gptagent_copilotforemployeeselfservicecore",
    "hr": "gptagent_copilotforemployeeselfservicehr",
    "it": "gptagent_copilotforemployeeselfserviceit",
}

# Folder name of each target's DA template inside ESSVivaCopilot's
# sources/dev/AgentTemplates.
DA_TEMPLATE_FOLDER_BY_VERTICAL = {
    "core": "CopilotForEmployeeSelfServiceCore",
    "hr": "CopilotForEmployeeSelfServiceHR",
    "it": "CopilotForEmployeeSelfServiceIT",
}

_KNOWN_PREFIXES = (DA_PREFIX, CA_PREFIX)


def schema_suffix(schemaname: str) -> str:
    """The agent-independent join key for a component schema name.

    ``msdyn_copilotforemployeeselfservicehr.topic.ConversationStart`` and
    ``gptagent_copilotforemployeeselfservicehr.topic.ConversationStart`` both
    reduce to ``topic.ConversationStart``, which is how a CA component is matched
    to its DA counterpart.

    Returns the input unchanged when it carries no recognised agent prefix.
    """
    name = schemaname.strip()
    if not name.startswith(_KNOWN_PREFIXES):
        return name
    head, _, tail = name.partition(".")
    del head
    return tail or name


def schema_prefix(schemaname: str) -> str:
    """The agent-qualified prefix of a schema name (everything before the first dot)."""
    return schemaname.strip().partition(".")[0]
