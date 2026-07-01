"""Generic immutable pipeline and fluent builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast, overload

from core.pipeline.exceptions import PipelineConfigurationError, PipelineExecutionError
from core.pipeline.registry import PipelineRegistry
from core.pipeline.step import PipelineStep
from core.pipeline.typing import (
    PipelineTypeSpec,
    type_spec_name,
    type_specs_compatible,
    value_matches_type_spec,
)

TInput = TypeVar("TInput")
TOutput = TypeVar("TOutput")
TCurrent = TypeVar("TCurrent")
TNext = TypeVar("TNext")


@dataclass(frozen=True)
class Pipeline(Generic[TInput, TOutput]):
    """Immutable ordered pipeline of typed steps.

    Purpose:
        Execute a deterministic sequence of type-compatible steps.
    Responsibilities:
        Preserve step order, validate runtime values, skip inapplicable steps,
        propagate failures, and return the final typed output.
    Inputs:
        A value of ``TInput`` supplied by the caller.
    Outputs:
        A value of ``TOutput`` produced by the final executed step.
    """

    name: str
    _steps: tuple[PipelineStep[Any, Any], ...] = field(default_factory=tuple)
    _input_type: PipelineTypeSpec | None = None
    _output_type: PipelineTypeSpec | None = None

    @overload
    @classmethod
    def builder(
        cls,
        name: str,
        *,
        input_type: type[TInput],
    ) -> PipelineBuilder[TInput, TInput]: ...

    @overload
    @classmethod
    def builder(
        cls,
        name: str,
        *,
        input_type: PipelineTypeSpec | None = None,
    ) -> PipelineBuilder[Any, Any]: ...

    @classmethod
    def builder(
        cls,
        name: str,
        *,
        input_type: PipelineTypeSpec | None = None,
    ) -> PipelineBuilder[Any, Any]:
        """Create a fluent builder for a pipeline named ``name``."""
        return PipelineBuilder(name=name, input_type=input_type, current_type=input_type)

    @property
    def steps(self) -> tuple[PipelineStep[Any, Any], ...]:
        """Return the immutable configured steps."""
        return self._steps

    @property
    def input_type(self) -> PipelineTypeSpec | None:
        """Return the runtime input type declared for this pipeline, if known."""
        return self._input_type

    @property
    def output_type(self) -> PipelineTypeSpec | None:
        """Return the runtime output type declared for this pipeline, if known."""
        return self._output_type

    def run(self, pipeline_input: TInput) -> TOutput:
        """Execute the pipeline sequentially and return the final output."""
        if self._input_type is not None and not value_matches_type_spec(
            pipeline_input,
            self._input_type,
        ):
            raise PipelineExecutionError(
                f"Pipeline '{self.name}' expected input type {type_spec_name(self._input_type)}."
            )

        current: object = pipeline_input
        for step in self._steps:
            if not value_matches_type_spec(current, step.input_type):
                raise PipelineExecutionError(
                    f"Step '{step.name()}' expected input type {type_spec_name(step.input_type)}."
                )

            typed_current = cast(Any, current)
            if not step.can_execute(typed_current):
                continue

            current = step.execute(typed_current)
            if not value_matches_type_spec(current, step.output_type):
                raise PipelineExecutionError(
                    f"Step '{step.name()}' produced incompatible output; expected "
                    f"{type_spec_name(step.output_type)}."
                )
            step.validate(cast(Any, current))

        if self._output_type is not None and not value_matches_type_spec(
            current,
            self._output_type,
        ):
            raise PipelineExecutionError(
                f"Pipeline '{self.name}' produced incompatible output; expected "
                f"{type_spec_name(self._output_type)}."
            )
        return cast(TOutput, current)


@dataclass(frozen=True)
class PipelineBuilder(Generic[TInput, TCurrent]):
    """Fluent type-threading pipeline builder.

    Purpose:
        Construct immutable pipelines from adjacent type-compatible steps.
    Responsibilities:
        Append steps in explicit order, reject duplicate names, reject
        incompatible adjacent step types, and produce an immutable Pipeline.
    Inputs:
        A sequence of ``PipelineStep`` instances whose types must thread.
    Outputs:
        A ``Pipeline[TInput, TCurrent]`` snapshot.
    """

    name: str
    input_type: PipelineTypeSpec | None = None
    current_type: PipelineTypeSpec | None = None
    registry: PipelineRegistry = field(default_factory=PipelineRegistry)

    def use(self, step: PipelineStep[TCurrent, TNext]) -> PipelineBuilder[TInput, TNext]:
        """Return a new builder with ``step`` appended after type validation."""
        if self.current_type is not None and not type_specs_compatible(
            self.current_type,
            step.input_type,
        ):
            raise PipelineConfigurationError(
                f"Step '{step.name()}' expects {type_spec_name(step.input_type)} "
                f"but previous output is {type_spec_name(self.current_type)}."
            )

        return PipelineBuilder(
            name=self.name,
            input_type=self.input_type if self.input_type is not None else step.input_type,
            current_type=step.output_type,
            registry=self.registry.register(step),
        )

    def build(self) -> Pipeline[TInput, TCurrent]:
        """Build an immutable executable pipeline."""
        return Pipeline(
            name=self.name,
            _steps=self.registry.steps(),
            _input_type=self.input_type,
            _output_type=self.current_type,
        )
