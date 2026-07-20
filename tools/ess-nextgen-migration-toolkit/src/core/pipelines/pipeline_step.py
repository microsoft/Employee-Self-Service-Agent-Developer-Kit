"""Pipeline step abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Generic, TypeVar

from core.pipelines.typing import PipelineTypeSpec, normalize_type_spec

TInput = TypeVar("TInput")
TOutput = TypeVar("TOutput")


class PipelineStep(ABC, Generic[TInput, TOutput]):
    """Base contract implemented by every typed pipeline step.

    Purpose:
        Encapsulate one deterministic unit of pipeline work.
    Responsibilities:
        Declare input/output types, decide whether it can run, execute one
        responsibility, and validate its output.
    Inputs:
        A value of ``TInput`` from the previous step or pipeline caller.
    Outputs:
        A value of ``TOutput`` passed to the next step.
    """

    def __init__(
        self,
        *,
        input_type: PipelineTypeSpec,
        output_type: PipelineTypeSpec,
        name: str | None = None,
        description: str | None = None,
        supported_modes: Iterable[str] = (),
    ) -> None:
        self._input_type = _validated_type_spec(input_type)
        self._output_type = _validated_type_spec(output_type)
        self._name = name if name is not None else self.__class__.__name__
        self._description = description if description is not None else self._name
        self._supported_modes = frozenset(supported_modes)

    @property
    def input_type(self) -> PipelineTypeSpec:
        """Runtime input type accepted by this step."""
        return self._input_type

    @property
    def output_type(self) -> PipelineTypeSpec:
        """Runtime output type produced by this step."""
        return self._output_type

    def name(self) -> str:
        """Return the deterministic step name used for registration."""
        return self._name

    def description(self) -> str:
        """Return a human-readable description of this step."""
        return self._description

    def supported_modes(self) -> frozenset[str]:
        """Return execution modes supported by this step, if mode-aware."""
        return self._supported_modes

    def can_execute(self, context: TInput) -> bool:
        """Return whether this step should execute for the supplied context."""
        return True

    @abstractmethod
    def execute(self, context: TInput) -> TOutput:
        """Execute this step and return the next pipeline value."""

    def validate(self, context: TOutput) -> None:
        """Validate this step's output.

        The default validator accepts the framework-level type validation.
        Concrete steps may override this for step-specific invariants.
        """


def _validated_type_spec(type_spec: PipelineTypeSpec) -> PipelineTypeSpec:
    normalized = normalize_type_spec(type_spec)
    return normalized[0] if len(normalized) == 1 else normalized
