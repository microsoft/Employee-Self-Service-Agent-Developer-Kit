"""Interactive conflict resolution for ``migrate``.

When a topic was edited both by the customer and by ESS, the structural merge
cannot pick a winner on its own. Rather than always deferring to a human via the
report, ``migrate`` can offer each contested spot at the console and bake the
chosen version straight into the package.

This module is the console side of that: it renders one :class:`~essmig.merge.Conflict`
in plain terms and asks *keep ESS's*, *keep mine*, or *open an editor to merge by
hand*, with an "apply to the rest of this topic" shortcut so a customer need not
answer the same way twenty times. The merge itself stays pure — it only calls the
resolver callback this module builds.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from collections.abc import Callable

from essmig.discovery import CaComponent
from essmig.merge import Conflict, ConflictResolver, Decision, Resolution
from essmig.projection import dump, load_fragment

Prompt = Callable[[str], str]
Echo = Callable[[str], None]
Edit = Callable[[str], str]

_MERGE_MARKER = "# ==== EDIT BELOW THIS LINE — this is what goes into the package ===="


def console_resolver_factory(
    *, prompt: Prompt = input, echo: Echo = print, edit: Edit | None = None
) -> Callable[[CaComponent], ConflictResolver]:
    """A resolver factory that prompts at the console, one resolver per component.

    ``edit`` opens the hand-merge text in an editor and returns the saved text; it
    defaults to the user's ``$VISUAL``/``$EDITOR`` (or Notepad on Windows) and is
    injectable for tests.
    """
    editor = edit or _open_in_editor

    def factory(component: CaComponent) -> ConflictResolver:
        return _ConsoleResolver(component, prompt=prompt, echo=echo, edit=editor)

    return factory


class _ConsoleResolver:
    """Resolves a single component's conflicts by asking at the console.

    Fresh per component, so the "apply to the rest of this topic" choice is scoped
    to that component and never leaks into the next one.
    """

    def __init__(
        self, component: CaComponent, *, prompt: Prompt, echo: Echo, edit: Edit
    ) -> None:
        self._component = component
        self._prompt = prompt
        self._echo = echo
        self._edit = edit
        self._sticky: Decision | None = None
        self._headed = False

    def __call__(self, conflict: Conflict) -> Decision | None:
        # The GPT ``instructions`` scalar is reconciled by the model, not by a blunt
        # keep-mine/keep-ESS pick — let it flow through to that path untouched.
        if conflict.path.endswith(".instructions"):
            return None
        if self._sticky is not None:
            return self._sticky

        self._render(conflict)
        while True:
            answer = self._ask_choice()
            if answer == "manual":
                merged = self._hand_merge(conflict)
                if merged is _EDIT_FAILED:
                    continue  # parsing failed; back to the choice prompt
                return Decision.manual(merged)
            decision = Decision.theirs() if answer == "theirs" else Decision.ours()
            if self._ask_apply_rest(decision.resolution):
                self._sticky = decision
            return decision

    def _render(self, conflict: Conflict) -> None:
        if not self._headed:
            self._echo("")
            self._echo(f'Conflicts in "{self._component.name}":')
            self._headed = True
        self._echo("")
        self._echo(f"  Spot: {_short_path(conflict.path)}")
        self._echo(f"  What: {conflict.reason}")

        delta = _delta(conflict.base, conflict.ours)
        if delta is None:
            # No baseline to diff against — fall back to showing your value in full.
            self._echo("  Your version:")
            self._emit(_pretty(conflict.ours))
        else:
            self._echo("  What you changed (compared with the version ESS originally shipped):")
            self._emit(delta)

        self._echo("  ESS's version (what the package has now):")
        self._emit(_pretty(conflict.theirs))

    def _emit(self, lines: list[str]) -> None:
        for line in lines:
            self._echo(f"    {line}")

    def _ask_choice(self) -> str:
        while True:
            answer = self._prompt(
                "  Keep [E]SS's, keep [M]ine, or [O]pen an editor to merge by hand? [E]: "
            ).strip().lower()
            if answer in ("", "e", "ess"):
                return "theirs"
            if answer in ("m", "mine"):
                return "ours"
            if answer in ("o", "open", "edit", "editor"):
                return "manual"
            self._echo("  Please answer E (keep ESS's), M (keep mine), or O (open an editor).")

    def _ask_apply_rest(self, choice: Resolution) -> bool:
        which = "yours" if choice is Resolution.OURS else "ESS's"
        answer = self._prompt(
            f"  Apply 'keep {which}' to the rest of this topic too? [y/N]: "
        ).strip().lower()
        return answer in ("y", "yes")

    def _hand_merge(self, conflict: Conflict) -> object:
        """Open both versions in an editor and parse back the value the human saves.

        Returns the parsed value, or ``_EDIT_FAILED`` if the saved text would not
        parse (so the caller can re-prompt).
        """
        edited = self._edit(_editor_template(conflict))
        body = _after_marker(edited)
        if not body.strip():
            self._echo("  Nothing below the edit line — leaving this spot for you to redo.")
            return _EDIT_FAILED
        try:
            value = load_fragment(body)
        except Exception as error:  # noqa: BLE001 — any YAML error means "try again"
            self._echo(f"  Could not parse your edited YAML ({error}).")
            return _EDIT_FAILED
        self._echo("  Using your hand-merged version.")
        return value


_EDIT_FAILED = object()
"""Sentinel: the edited text could not be used; ask again."""


def _editor_template(conflict: Conflict) -> str:
    """The seed text opened in the editor: both sides for reference, ESS's to edit."""
    lines = [
        f"# Manual merge for: {_short_path(conflict.path)}",
        f"# What changed: {conflict.reason}",
        "#",
        "# Below the marker is YAML that will be written into the package. It is",
        "# pre-filled with ESS's version; edit it into the result you want, then save",
        "# and close the editor. Your version and ESS's version are shown as comments",
        "# for reference. Lines starting with '#' are ignored.",
        "#",
        "# ----- YOUR VERSION -----",
        *(f"# {line}" for line in _yaml_lines(conflict.ours)),
        "# ----- ESS'S VERSION -----",
        *(f"# {line}" for line in _yaml_lines(conflict.theirs)),
        "#",
        _MERGE_MARKER,
    ]
    seed = "" if conflict.theirs is None else dump(conflict.theirs)
    return "\n".join(lines) + "\n" + seed


def _yaml_lines(value: object) -> list[str]:
    """A value as YAML lines, matching the format the human edits below the marker."""
    if value is None:
        return ["(removed — not present in this version)"]
    return dump(value).splitlines()


def _after_marker(text: str) -> str:
    """Everything after the edit marker — the value the human wants placed."""
    _, sep, rest = text.partition(_MERGE_MARKER)
    return rest if sep else text


def _open_in_editor(initial: str) -> str:
    """Write ``initial`` to a temp file, open it in the user's editor, return the result."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    command = shlex.split(editor) if editor else (["notepad"] if os.name == "nt" else ["vi"])
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, encoding="utf-8", newline=""
    )
    try:
        handle.write(initial)
        handle.close()
        subprocess.run([*command, handle.name], check=False)  # noqa: S603 — editor from env
        with open(handle.name, encoding="utf-8") as saved:
            return saved.read()
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


def _short_path(path: str) -> str:
    """Drop the component-suffix prefix so the spot reads from the topic down."""
    _, _, rest = path.partition(".")
    return rest or path


# --- rendering a conflict in terms of *what changed* -------------------------

# Keys that identify a list item, so two lists can be aligned to show what the
# customer added, removed or changed — in preference order. ``propertyName`` beats
# ``kind`` because many items share a kind but differ by property.
_ALIGN_KEYS = ("id", "propertyName", "name", "variable", "actionId", "schemaName", "kind")


def _delta(base: object, other: object) -> list[str] | None:
    """Describe how ``other`` (your version) differs from ``base`` (what ESS shipped).

    Returns human-readable lines, or ``None`` when there is no baseline to compare
    against (the caller then shows the value in full).
    """
    if base is None:
        return None
    if other is None:
        return ["(you removed this entirely)"]

    b, o = _plain(base), _plain(other)
    if isinstance(b, dict) and isinstance(o, dict):
        return _dict_delta(b, o) or ["(no change — only formatting or ordering differs)"]
    if isinstance(b, list) and isinstance(o, list):
        lines = _list_delta(b, o)
        return _pretty(other) if lines is None else lines
    if b == o:
        return ["(no change)"]
    return [f"changed from {_short(b)} to {_short(o)}"]


def _dict_delta(base: dict[str, object], other: dict[str, object]) -> list[str]:
    lines: list[str] = []
    for key, value in other.items():
        if key not in base:
            lines.append(f"+ {key}: {_short(value)}")
        elif _plain(base[key]) != _plain(value):
            lines.append(f"~ {key}: {_short(base[key])} -> {_short(value)}")
    for key, value in base.items():
        if key not in other:
            lines.append(f"- {key}: {_short(value)}")
    return lines


def _list_delta(base: list[object], other: list[object]) -> list[str] | None:
    """Align two lists by an item key and describe the difference, or ``None``.

    ``None`` means the items can't be aligned (no stable key or duplicate keys), so
    the caller shows the list in full instead of an unhelpful item-by-item guess.
    """
    raw_base_keys = [_key_of(item) for item in base]
    raw_other_keys = [_key_of(item) for item in other]
    if not raw_base_keys or not raw_other_keys:
        return None
    if None in raw_base_keys or None in raw_other_keys:
        return None
    base_keys = [key for key in raw_base_keys if key is not None]
    other_keys = [key for key in raw_other_keys if key is not None]
    if len(set(base_keys)) != len(base_keys) or len(set(other_keys)) != len(other_keys):
        return None

    base_by = dict(zip(base_keys, base, strict=True))
    other_by = dict(zip(other_keys, other, strict=True))
    lines: list[str] = []
    for key in other_keys:
        if key not in base_by:
            lines.append(f"+ added {key[1]}")
            continue
        sub = _delta(base_by[key], other_by[key])
        no_change = (["(no change)"], ["(no change — only formatting or ordering differs)"])
        if sub and sub not in no_change:
            detail = "; ".join(line[2:] if line.startswith("~ ") else line for line in sub)
            lines.append(f"~ changed {key[1]}: {detail}")
    for key in base_keys:
        if key not in other_by:
            lines.append(f"- removed {key[1]}")
    return lines or ["(reordered; no items added, removed or changed)"]


def _key_of(item: object) -> tuple[str, str] | None:
    if isinstance(item, dict):
        for key in _ALIGN_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value:
                return (key, value)
    return None


def _short(value: object) -> str:
    """A one-line rendering of a value, for inline before/after summaries."""
    try:
        text = json.dumps(_plain(value), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= 80 else text[:77] + "…"


def _pretty(value: object) -> list[str]:
    """A compact, multi-line rendering of one whole side of a conflict."""
    if value is None:
        return ["(removed — not present in this version)"]
    try:
        text = json.dumps(_plain(value), indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > 1200:
        text = text[:1200] + "\n… (truncated)"
    return text.splitlines()


def _plain(node: object) -> object:
    """Normalize YAML round-trip wrapper types to plain dict/list/scalars."""
    if isinstance(node, dict):
        return {str(key): _plain(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_plain(item) for item in node]
    return node
