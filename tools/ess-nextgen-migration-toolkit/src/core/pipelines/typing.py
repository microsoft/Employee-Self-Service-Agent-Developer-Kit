"""Runtime type helpers for the pipeline framework."""

from __future__ import annotations

from types import NoneType

PipelineTypeSpec = type[object] | tuple[type[object], ...]


def normalize_type_spec(type_spec: PipelineTypeSpec) -> tuple[type[object], ...]:
    """Normalize a supported runtime type declaration into a tuple."""
    if isinstance(type_spec, tuple):
        if not type_spec:
            raise ValueError("type specification must include at least one type.")
        return type_spec
    return (type_spec,)


def type_spec_name(type_spec: PipelineTypeSpec) -> str:
    """Return a deterministic display name for a runtime type declaration."""
    return " | ".join(sorted(type_.__name__ for type_ in normalize_type_spec(type_spec)))


def type_specs_compatible(
    produced_type: PipelineTypeSpec,
    accepted_type: PipelineTypeSpec,
) -> bool:
    """Return whether every produced type is accepted by the next step."""
    accepted_types = normalize_type_spec(accepted_type)
    return all(
        any(issubclass(output_type, input_type) for input_type in accepted_types)
        for output_type in normalize_type_spec(produced_type)
    )


def value_matches_type_spec(value: object, type_spec: PipelineTypeSpec) -> bool:
    """Return whether a runtime value conforms to a pipeline type declaration."""
    return isinstance(value, normalize_type_spec(type_spec))


NONE_TYPE: type[object] = NoneType
