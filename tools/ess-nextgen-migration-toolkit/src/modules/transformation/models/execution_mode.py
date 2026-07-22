"""ESS migration execution modes.

The generic framework (``core/``) treats a context's ``mode`` as an opaque
string; this enum supplies the ESS domain vocabulary for that string. Keeping it
in the domain layer lets ``core/`` stay product-agnostic.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionMode(StrEnum):
    """ESS migration execution modes.

    Being a StrEnum, values compare equal to their string form
    (e.g. ``ExecutionMode.READONLY == "READONLY"``), so they slot directly into
    the framework's generic ``ExecutionContext.mode: str`` field.

    - ``READONLY`` — run the full pipeline in-memory; never persist (serves the
      Discover and Preview customer intents).
    - ``WRITEBACK`` — run the pipeline and persist supported changes (Migrate).
    """

    READONLY = "READONLY"
    WRITEBACK = "WRITEBACK"
