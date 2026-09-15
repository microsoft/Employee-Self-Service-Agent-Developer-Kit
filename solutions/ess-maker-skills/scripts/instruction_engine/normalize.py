_ZERO_WIDTH = ("​", "‌", "‍", "﻿")


def normalize(raw):
    text = raw.replace(" ", " ")
    for ch in _ZERO_WIDTH:
        text = text.replace(ch, "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines), lines
