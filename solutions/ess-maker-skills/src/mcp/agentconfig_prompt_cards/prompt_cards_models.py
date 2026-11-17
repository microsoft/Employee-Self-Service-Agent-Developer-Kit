# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Prompt-card maker contracts; names intentionally match the widget wire format."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr,
    field_validator, model_validator,
)


def _guid(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("must be a GUID") from None
    if not parsed.int:
        raise ValueError("must be a nonempty GUID")
    return str(parsed)


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _utf16_limit(limit: int):
    def validate(value: str) -> str:
        # The backend's string.Length counts UTF-16 code units.
        if len(value.encode("utf-16-le", errors="surrogatepass")) // 2 > limit:
            raise ValueError(f"must not exceed {limit} UTF-16 code units")
        return value
    return AfterValidator(validate)


Guid = Annotated[StrictStr, AfterValidator(_guid)]
Name = Annotated[StrictStr, Field(max_length=80), _utf16_limit(80), AfterValidator(_nonblank)]
Prompt = Annotated[StrictStr, Field(max_length=2000), _utf16_limit(2000), AfterValidator(_nonblank)]
Presentation = Annotated[StrictStr, Field(max_length=1000), _utf16_limit(1000)]
Audience = Annotated[list[Guid], Field(max_length=15)]
Order = Annotated[StrictInt, Field(ge=0, le=2147483647)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PromptCardCreate(Contract):
    definitionName: Name
    dataPrompt: Prompt
    presentationGuidance: Presentation | None = None
    audience: Audience | None = None
    isDisabled: StrictBool = False
    sortOrder: Order = 0


class PromptCardPatch(Contract):
    definitionName: Name | None = None
    dataPrompt: Prompt | None = None
    presentationGuidance: Presentation | None = None
    audience: Audience | None = None
    isDisabled: StrictBool | None = None
    sortOrder: Order | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("patch must contain at least one changed field")
        for field in self.model_fields_set - {"presentationGuidance", "audience"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class PromptCardDefinition(PromptCardCreate):
    # OData annotations are response metadata, not authored properties.
    model_config = ConfigDict(extra="ignore")
    definitionId: Guid
    isDisabled: StrictBool
    sortOrder: Order
    audience: Audience = Field(default_factory=list)

    @field_validator("audience", mode="before")
    @classmethod
    def normalize_audience(cls, value):
        return [] if value is None else value


class PromptCardOrder(Contract):
    definitionId: Guid
    sortOrder: Order


class PromptCardReorder(Contract):
    definitions: Annotated[list[PromptCardOrder], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        ids = [item.definitionId for item in self.definitions]
        if len(set(ids)) != len(ids):
            raise ValueError("definition IDs must be unique")
        return self
