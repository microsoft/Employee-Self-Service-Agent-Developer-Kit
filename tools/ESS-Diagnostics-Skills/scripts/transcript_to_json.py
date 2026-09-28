#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""transcript_to_json.py — faithful transcript -> JSON helper for the ESS
Diagnostics skill.

Parses a Copilot Studio / PVA transcript (JSON payload stored in a .txt) and
writes a LOSSLESS, pretty-printed JSON copy: every event and every field is
preserved exactly. The only additions are `_turn` and `_index`, annotated as
the first keys on each event (turn 0 for events before the first user message)
so a reader can navigate by conversation turn. Nothing is removed, so the
output round-trips back to the original once `_turn`/`_index` are dropped.

This is the faithful full dump. It is NOT the compact diagnostic "normalized"
view the skill builds for the 5 checks — it is the whole transcript, just as
real JSON.

Usage:
    python transcript_to_json.py <transcript.txt> [outFile.json]

- <transcript.txt>  path to the raw transcript export (required).
- [outFile.json]    where to write. If omitted, writes
                    `<basename>-transcript.json` into the OS temp dir under
                    `ess-diagnostics/<basename>/` (outside any repo, because
                    transcripts may contain employee PII).

Prints the absolute output path on success. Exits non-zero with an
`Error: ...` message on failure.
"""

import json
import os
import sys
import tempfile
from pathlib import Path


def fail(msg):
    sys.stderr.write("Error: " + msg + "\n")
    sys.exit(1)


def is_user_turn_start(e):
    return (
        isinstance(e, dict)
        and e.get("t") == "SynchronousIncomingActivity"
        and isinstance(e.get("p"), dict)
        and isinstance(e["p"].get("activity"), dict)
        and e["p"]["activity"].get("type") == "message"
    )


def main(argv):
    if len(argv) < 2:
        fail(
            "missing transcript path. Usage: "
            "python transcript_to_json.py <transcript.txt> [outFile.json]"
        )
    src_arg = argv[1]
    src_path = Path(src_arg)
    if not src_path.exists():
        fail("transcript file not found: " + src_arg)

    try:
        raw = src_path.read_text(encoding="utf-8")
    except OSError as e:
        fail("could not read transcript: " + str(e))

    # Strip a leading UTF-8 BOM if present, then parse.
    if raw and raw[0] == "﻿":
        raw = raw[1:]

    try:
        events = json.loads(raw)
    except ValueError as e:
        fail("transcript is not valid JSON: " + str(e))

    if not isinstance(events, list):
        fail(
            "expected the transcript to be a JSON array of events; got "
            + type(events).__name__
        )

    # Annotate each event with its conversation turn number, WITHOUT mutating any
    # existing field. A turn starts at each real user message; events before the
    # first user message are turn 0. `_turn`/`_index` are first keys on a shallow
    # copy; every original key/value is copied through untouched.
    annotated = []
    turn = 0
    for i, e in enumerate(events):
        if is_user_turn_start(e):
            turn += 1
        if isinstance(e, dict):
            annotated.append({"_turn": turn, "_index": i, **e})
        else:
            annotated.append({"_turn": turn, "_index": i, "_value": e})

    base = src_path.name
    dot = base.rfind(".")
    if dot > 0:
        base = base[:dot]

    wrote_to_temp = False
    if len(argv) >= 3 and argv[2]:
        out_file = Path(argv[2])
        try:
            out_file.resolve().parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            fail(
                "could not create output directory "
                + str(out_file.resolve().parent)
                + ": "
                + str(e)
            )
    else:
        out_dir = Path(tempfile.gettempdir()) / "ess-diagnostics" / base
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            fail("could not create output directory " + str(out_dir) + ": " + str(e))
        out_file = out_dir / (base + "-transcript.json")
        wrote_to_temp = True
        # Transcripts may contain employee PII and the default temp dir is
        # world-readable on POSIX. Restrict the per-run folder to the owner
        # (no-op on Windows, where os.chmod ignores these bits and %TEMP% is
        # already per-user).
        if os.name == "posix":
            try:
                os.chmod(out_dir, 0o700)
            except OSError:
                pass

    # Never overwrite the source transcript, even if it was passed as the output.
    if out_file.resolve() == src_path.resolve():
        fail("output path is the same as the transcript; refusing to overwrite it")

    try:
        out_file.write_text(
            json.dumps(annotated, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as e:
        fail("could not write output: " + str(e))

    # Owner-only on the PII-bearing temp output (POSIX; no-op on Windows).
    if wrote_to_temp and os.name == "posix":
        try:
            os.chmod(out_file, 0o600)
        except OSError:
            pass

    sys.stdout.write(str(out_file.resolve()) + "\n")


if __name__ == "__main__":
    main(sys.argv)
