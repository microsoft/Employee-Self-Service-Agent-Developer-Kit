from dataclasses import dataclass


@dataclass
class Section:
    name: str
    level: int
    start_line: int
    end_line: int
    text: str


@dataclass
class Prompt:
    sections: list
    raw: str
    lines: list


@dataclass
class Finding:
    id: str
    severity: str
    category: str
    section: str
    line: int
    message: str
    suggestion: str
    source: str = "regex"
