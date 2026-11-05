# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Content-free LPC usage measurements from recognized configuration shapes."""

from __future__ import annotations

from typing import Any

from operation_telemetry import annotate_usage


def record_configuration(config: Any, *, draft: bool = False) -> None:
    if not isinstance(config, dict):
        return
    if not draft:
        annotate_usage(
            config_branding_present="branding" in config,
            config_quick_links_present="quickLinksConfig" in config,
            config_pivots_present="pivots" in config,
        )
    links_config = config.get("quickLinksConfig")
    if isinstance(links_config, dict):
        links = links_config.get("quickLinks")
        if isinstance(links, list) and all(
            isinstance(link, dict)
            and isinstance(link.get("displayText"), str)
            and isinstance(link.get("address"), str)
            for link in links
        ):
            if draft:
                annotate_usage(draft_quick_link_count=len(links))
            else:
                annotate_usage(quick_link_count=len(links))
    pivots = config.get("pivots")
    if not isinstance(pivots, list) or not all(
        isinstance(pivot, dict) and isinstance(pivot.get("displayName"), str)
        for pivot in pivots
    ):
        return
    if draft:
        annotate_usage(draft_pivot_count=len(pivots))
    else:
        annotate_usage(pivot_count=len(pivots))
    # A category is a pivot with a display-name field, not a distinct text value.
    if draft:
        annotate_usage(draft_category_count=len(pivots))
    else:
        annotate_usage(category_count=len(pivots))
    prompt_lists = [pivot.get("conversationStarterPrompts") for pivot in pivots]
    if all(
        isinstance(prompts, list) and all(
            isinstance(prompt, dict)
            and isinstance(prompt.get("title"), str)
            and isinstance(prompt.get("displayText"), str)
            for prompt in prompts
        )
        for prompts in prompt_lists
    ):
        count = sum(len(prompts) for prompts in prompt_lists)
        if draft:
            annotate_usage(draft_prompt_count=count)
        else:
            annotate_usage(prompt_count=count)
