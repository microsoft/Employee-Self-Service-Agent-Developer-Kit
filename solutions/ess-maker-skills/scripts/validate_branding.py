# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validate changed ESS landing-page accent colors for WCAG AA contrast."""

from __future__ import annotations

import argparse
import json
import re
import sys


HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
REQUIRED_RATIO = 4.5
BACKGROUNDS = {
    "light": "#FFFFFF",
    "dark": "#242424",
}


def _channel_luminance(value: int) -> float:
    channel = value / 255
    if channel <= 0.03928:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _relative_luminance(color: str) -> float:
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    return (
        _channel_luminance(red) * 0.2126
        + _channel_luminance(green) * 0.7152
        + _channel_luminance(blue) * 0.0722
    )


def contrast_ratio(first: str, second: str) -> float:
    """Return the Vorpal-compatible contrast ratio rounded to two decimals."""
    first_luminance = _relative_luminance(first)
    second_luminance = _relative_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def evaluate_theme(theme: str, color: str) -> dict[str, object]:
    """Validate one changed theme and return its advisory contrast result."""
    normalized = color.upper()
    if not HEX_COLOR.fullmatch(normalized):
        raise ValueError(
            f"{theme} must be a six-digit hex color such as #0A7EF4"
        )

    background = BACKGROUNDS[theme]
    ratio = contrast_ratio(normalized, background)
    return {
        "theme": theme,
        "accentColor": normalized,
        "backgroundColor": background,
        "ratio": ratio,
        "required": REQUIRED_RATIO,
        "passes": ratio >= REQUIRED_RATIO,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate changed landing-page accent colors."
    )
    parser.add_argument("--light", help="Changed light-theme accent (#RRGGBB)")
    parser.add_argument("--dark", help="Changed dark-theme accent (#RRGGBB)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.light is None and args.dark is None:
        parser.error("provide --light, --dark, or both")

    try:
        themes = []
        if args.light is not None:
            themes.append(evaluate_theme("light", args.light))
        if args.dark is not None:
            themes.append(evaluate_theme("dark", args.dark))
    except ValueError as error:
        print(
            json.dumps({"passes": False, "error": str(error)}),
            file=sys.stderr,
        )
        return 2

    passes = all(bool(theme["passes"]) for theme in themes)
    print(json.dumps({"passes": passes, "themes": themes}))
    return 0 if passes else 1


if __name__ == "__main__":
    raise SystemExit(main())
