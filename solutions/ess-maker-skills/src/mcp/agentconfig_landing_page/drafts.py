# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Typed suggested-draft inputs for landing-page widget openers."""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DraftModel(BaseModel):
    """Reject fields owned by the route, server, client, or widget."""

    model_config = ConfigDict(extra="forbid")


class AccentThemeDraft(DraftModel):
    name: Literal["light", "dark"]
    accentColor: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


class BrandingDraft(DraftModel):
    theming: Annotated[list[AccentThemeDraft], Field(max_length=2)]

    @model_validator(mode="after")
    def require_unique_theme_names(self) -> BrandingDraft:
        names = [theme.name for theme in self.theming]
        if len(names) != len(set(names)):
            raise ValueError("theming entries must have unique names")
        return self


class AccentColorDraft(DraftModel):
    branding: BrandingDraft


class QuickLinkDraft(DraftModel):
    displayText: Annotated[str, Field(min_length=1, max_length=300)]
    address: Annotated[str, Field(min_length=1, max_length=2000)]

    @field_validator("address")
    @classmethod
    def require_absolute_https_address(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("address must be an absolute HTTPS URL")
        return value


class QuickLinksConfigDraft(DraftModel):
    quickLinks: Annotated[list[QuickLinkDraft], Field(max_length=10)]


class QuickLinksDraft(DraftModel):
    quickLinksConfig: QuickLinksConfigDraft


class StarterPromptDraft(DraftModel):
    title: Annotated[str, Field(max_length=128)]
    displayText: Annotated[str, Field(max_length=4000)]


class StarterPromptPivotDraft(DraftModel):
    displayName: Annotated[str, Field(max_length=35)]
    conversationStarterPrompts: Annotated[
        list[StarterPromptDraft],
        Field(max_length=12),
    ]


class StarterPromptsDraft(DraftModel):
    pivots: Annotated[list[StarterPromptPivotDraft], Field(max_length=10)]
