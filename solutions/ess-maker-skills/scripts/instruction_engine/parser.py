import re
from .normalize import normalize
from .models import Section, Prompt

_HEADER = re.compile(r"^\s*#+\s*(.+?)\s*$")
_CAPS_MARKER = re.compile(r"^[A-Z][A-Z ]{8,}$")

def _is_header(line):
    m = _HEADER.match(line)
    if m:
        return m.group(1)
    if _CAPS_MARKER.match(line.strip()):
        return line.strip()
    return None

def parse(raw: str) -> Prompt:
    text, lines = normalize(raw)
    sections, cur_name, cur_start = [], None, 0
    buf = []

    def flush(end):
        if cur_name is None and not any(b.strip() for b in buf):
            return
        name = cur_name if cur_name is not None else "(preamble)"
        sections.append(Section(name=name, level=1,
                                start_line=cur_start + 1, end_line=end,
                                text="\n".join(buf)))

    for i, line in enumerate(lines):
        header = _is_header(line)
        if header is not None:
            flush(i)
            cur_name, cur_start, buf = header, i, []
        else:
            buf.append(line)
    flush(len(lines))
    return Prompt(sections=sections, raw=text, lines=lines)
