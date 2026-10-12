# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Create and read the administrator workbook templates used by Workday Connect."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence
from xml.sax.saxutils import escape
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException


WORKSHEET_HEADERS = (
    "Information to capture",
    "Where to find it",
    "What to record",
    "Example value",
    "Your tenant values",
)
WORKSHEET_SHEET_NAME = "Worksheet"
STEPS_SHEET_NAME = "Steps"
_SOLUTION_ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_ASSET_DIRECTORY = (
    _SOLUTION_ROOT
    / "src"
    / "skills"
    / "setup"
    / "workday-da"
    / "assets"
)
ENTRA_ADMIN_WORKBOOK_PATH = (
    WORKBOOK_ASSET_DIRECTORY / "entra-admin-handoff.xlsx"
)
WORKDAY_ADMIN_WORKBOOK_PATH = (
    WORKBOOK_ASSET_DIRECTORY / "workday-admin-handoff.xlsx"
)

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
_PACKAGE_REL_NS = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MAX_EXPANDED_BYTES = 25 * 1024 * 1024
_MAX_ZIP_ENTRIES = 100
_MAX_WORKSHEET_ROWS = 200
_CELL_REF_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


class WorkdayConnectWorkbookError(RuntimeError):
    """Raised when an administrator workbook is invalid or unsafe."""


def _xml_text(value: Any) -> str:
    return escape(str(value), {'"': "&quot;"})


def _column_name(index: int) -> str:
    result = ""
    current = index
    while current:
        current, remainder = divmod(current - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _inline_cell(
    row: int,
    column: int,
    value: Any,
    *,
    style: int,
) -> str:
    reference = f"{_column_name(column)}{row}"
    return (
        f'<c r="{reference}" s="{style}" t="inlineStr">'
        f'<is><t xml:space="preserve">{_xml_text(value)}</t></is></c>'
    )


def _sheet_xml(
    rows: Sequence[Sequence[Any]],
    *,
    column_widths: Sequence[float],
    freeze_header: bool,
) -> str:
    columns = "".join(
        (
            f'<col min="{index}" max="{index}" width="{width}" '
            'customWidth="1"/>'
        )
        for index, width in enumerate(column_widths, start=1)
    )
    row_documents = []
    for row_index, values in enumerate(rows, start=1):
        style = 1 if row_index == 1 else 2
        cells = "".join(
            _inline_cell(
                row_index,
                column_index,
                value,
                style=style,
            )
            for column_index, value in enumerate(values, start=1)
        )
        row_documents.append(
            f'<row r="{row_index}" ht="30" customHeight="1">{cells}</row>'
        )
    pane = (
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
        'state="frozen"/>'
        if freeze_header
        else ""
    )
    auto_filter = (
        f'<autoFilter ref="A1:{_column_name(len(column_widths))}{len(rows)}"/>'
        if freeze_header and rows
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_MAIN_NS}">'
        f"<sheetViews><sheetView workbookViewId=\"0\">{pane}</sheetView>"
        "</sheetViews>"
        '<sheetFormatPr defaultRowHeight="18"/>'
        f"<cols>{columns}</cols>"
        f"<sheetData>{''.join(row_documents)}</sheetData>"
        f"{auto_filter}"
        '<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" '
        'header="0.2" footer="0.2"/>'
        "</worksheet>"
    )


def _zip_write(archive: ZipFile, name: str, content: str) -> None:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content.encode("utf-8"))


def write_administrator_workbook(
    path: Path,
    *,
    title: str,
    administrator_role: str,
    actions: Iterable[str],
    capture_instructions: Iterable[Mapping[str, Any]],
    answers: Mapping[str, str] | None = None,
) -> Path:
    """Write a deterministic two-sheet administrator workbook."""
    normalized_answers = {
        str(label): str(value)
        for label, value in (answers or {}).items()
    }
    normalized_actions = [str(value).strip() for value in actions]
    if not normalized_actions or any(not value for value in normalized_actions):
        raise WorkdayConnectWorkbookError(
            "Administrator workbook actions must be non-empty."
        )
    normalized_instructions = []
    for instruction in capture_instructions:
        if not isinstance(instruction, Mapping):
            raise WorkdayConnectWorkbookError(
                "Administrator capture instructions must contain objects."
            )
        row = tuple(
            str(instruction.get(key) or "").strip()
            for key in (
                "information",
                "portalLocation",
                "instruction",
                "exampleValue",
            )
        )
        if any(not value for value in row):
            raise WorkdayConnectWorkbookError(
                "Administrator capture instructions are incomplete."
            )
        normalized_instructions.append(
            (*row, normalized_answers.pop(row[0], ""))
        )
    if not normalized_instructions:
        raise WorkdayConnectWorkbookError(
            "Administrator workbook requires capture instructions."
        )
    if normalized_answers:
        raise WorkdayConnectWorkbookError(
            "Administrator workbook answers contain unknown labels."
        )

    steps_rows = [
        ("Step", "Action"),
        (
            "Before you start",
            (
                f"{title}. This workbook is for the {administrator_role}. "
                "Complete the applicable actions, fill every row on the "
                "Worksheet sheet, and return this same .xlsx file to the maker."
            ),
        ),
        (
            "Security",
            (
                "Do not enter passwords, client secrets, access tokens, "
                "cookies, certificate contents, private keys, or employee "
                "membership lists."
            ),
        ),
        *[
            (str(index), action)
            for index, action in enumerate(normalized_actions, start=1)
        ],
    ]
    worksheet_rows = [WORKSHEET_HEADERS, *normalized_instructions]

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{_MAIN_NS}" xmlns:r="{_DOC_REL_NS}">'
        "<sheets>"
        f'<sheet name="{STEPS_SHEET_NAME}" sheetId="1" r:id="rId1"/>'
        f'<sheet name="{WORKSHEET_SHEET_NAME}" sheetId="2" r:id="rId2"/>'
        "</sheets>"
        '<calcPr calcId="0" fullCalcOnLoad="1"/>'
        "</workbook>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{_MAIN_NS}">'
        '<fonts count="2"><font><sz val="11"/><name val="Aptos"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/>'
        '<name val="Aptos"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid">'
        '<fgColor rgb="FF1F4E78"/><bgColor indexed="64"/>'
        "</patternFill></fill></fills>"
        '<borders count="2"><border><left/><right/><top/><bottom/>'
        '<diagonal/></border><border><left style="thin"><color rgb="FFD9E2F3"/>'
        '</left><right style="thin"><color rgb="FFD9E2F3"/></right>'
        '<top style="thin"><color rgb="FFD9E2F3"/></top>'
        '<bottom style="thin"><color rgb="FFD9E2F3"/></bottom>'
        "<diagonal/></border></borders>"
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
        'borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" '
        'borderId="0" xfId="0"/>'
        '<xf numFmtId="49" fontId="1" fillId="2" borderId="1" xfId="0" '
        'applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
        '<alignment wrapText="1" vertical="center"/></xf>'
        '<xf numFmtId="49" fontId="0" fillId="0" borderId="1" xfId="0" '
        'applyNumberFormat="1" applyBorder="1" applyAlignment="1">'
        '<alignment wrapText="1" vertical="top"/></xf>'
        "</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" '
        'builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types"><Default Extension="rels" ContentType="application/'
        'vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    root_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PACKAGE_REL_NS}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    workbook_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PACKAGE_REL_NS}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with ZipFile(temporary_path, mode="w") as archive:
            _zip_write(archive, "[Content_Types].xml", content_types)
            _zip_write(archive, "_rels/.rels", root_relationships)
            _zip_write(archive, "xl/workbook.xml", workbook_xml)
            _zip_write(
                archive,
                "xl/_rels/workbook.xml.rels",
                workbook_relationships,
            )
            _zip_write(archive, "xl/styles.xml", styles_xml)
            _zip_write(
                archive,
                "xl/worksheets/sheet1.xml",
                _sheet_xml(
                    steps_rows,
                    column_widths=(18, 110),
                    freeze_header=True,
                ),
            )
            _zip_write(
                archive,
                "xl/worksheets/sheet2.xml",
                _sheet_xml(
                    worksheet_rows,
                    column_widths=(32, 52, 65, 42, 52),
                    freeze_header=True,
                ),
            )
        os.replace(temporary_path, path)
    except OSError as exc:
        raise WorkdayConnectWorkbookError(
            f"Administrator workbook could not be written: {path}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return path


def _parse_xml(content: bytes, label: str) -> ET.Element:
    try:
        return ET.fromstring(content)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise WorkdayConnectWorkbookError(
            f"Administrator workbook {label} is invalid."
        ) from exc


def _validated_archive(path: Path) -> ZipFile:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise WorkdayConnectWorkbookError(
            f"Administrator workbook could not be read: {path}: {exc}"
        ) from exc
    if size > _MAX_FILE_BYTES:
        raise WorkdayConnectWorkbookError(
            "Administrator workbook exceeds the 10 MB size limit."
        )
    try:
        archive = ZipFile(path, mode="r")
    except (OSError, BadZipFile) as exc:
        raise WorkdayConnectWorkbookError(
            "Administrator workbook is not a valid .xlsx file."
        ) from exc
    entries = archive.infolist()
    if len(entries) > _MAX_ZIP_ENTRIES:
        archive.close()
        raise WorkdayConnectWorkbookError(
            "Administrator workbook contains too many files."
        )
    expanded_size = 0
    member_names: set[str] = set()
    for entry in entries:
        member = PurePosixPath(entry.filename)
        if member.is_absolute() or ".." in member.parts:
            archive.close()
            raise WorkdayConnectWorkbookError(
                "Administrator workbook contains an unsafe file path."
            )
        normalized_name = member.as_posix()
        if normalized_name in member_names:
            archive.close()
            raise WorkdayConnectWorkbookError(
                "Administrator workbook contains duplicate files."
            )
        member_names.add(normalized_name)
        expanded_size += entry.file_size
        if expanded_size > _MAX_EXPANDED_BYTES:
            archive.close()
            raise WorkdayConnectWorkbookError(
                "Administrator workbook expands beyond the 25 MB limit."
            )
    return archive


def _shared_strings(archive: ZipFile) -> list[str]:
    try:
        content = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = _parse_xml(content, "shared strings")
    strings = []
    for item in root.findall(f"{{{_MAIN_NS}}}si"):
        strings.append(
            "".join(
                node.text or ""
                for node in item.iter(f"{{{_MAIN_NS}}}t")
            )
        )
    return strings


def _worksheet_member(archive: ZipFile, sheet_name: str) -> str:
    try:
        workbook = _parse_xml(
            archive.read("xl/workbook.xml"),
            "workbook",
        )
        relationships = _parse_xml(
            archive.read("xl/_rels/workbook.xml.rels"),
            "workbook relationships",
        )
    except KeyError as exc:
        raise WorkdayConnectWorkbookError(
            "Administrator workbook is missing its workbook definition."
        ) from exc
    relationship_targets = {
        relationship.get("Id"): relationship.get("Target")
        for relationship in relationships.findall(
            f"{{{_PACKAGE_REL_NS}}}Relationship"
        )
    }
    for sheet in workbook.findall(
        f".//{{{_MAIN_NS}}}sheet"
    ):
        if sheet.get("name") != sheet_name:
            continue
        relationship_id = sheet.get(f"{{{_DOC_REL_NS}}}id")
        target = relationship_targets.get(relationship_id)
        if not target:
            break
        target_path = PurePosixPath(target)
        if target_path.is_absolute():
            normalized = PurePosixPath(*target_path.parts[1:])
        else:
            normalized = PurePosixPath("xl") / target_path
        if normalized.is_absolute() or ".." in normalized.parts:
            break
        return normalized.as_posix()
    raise WorkdayConnectWorkbookError(
        f"Administrator workbook is missing the '{sheet_name}' sheet."
    )


def _cell_value(cell: ET.Element, shared_strings: Sequence[str]) -> str:
    if cell.find(f"{{{_MAIN_NS}}}f") is not None:
        raise WorkdayConnectWorkbookError(
            "Administrator workbook answers must not contain formulas."
        )
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(
            node.text or ""
            for node in cell.iter(f"{{{_MAIN_NS}}}t")
        )
    value = cell.find(f"{{{_MAIN_NS}}}v")
    raw_value = value.text if value is not None and value.text is not None else ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)]
        except (ValueError, IndexError) as exc:
            raise WorkdayConnectWorkbookError(
                "Administrator workbook contains an invalid shared string."
            ) from exc
    return raw_value


def _column_index(reference: str) -> int:
    match = _CELL_REF_RE.fullmatch(reference)
    if match is None:
        raise WorkdayConnectWorkbookError(
            "Administrator workbook contains an invalid cell reference."
        )
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def read_administrator_workbook(path: Path) -> str:
    """Return the completed Worksheet sheet as labeled worksheet text."""
    if path.suffix.casefold() != ".xlsx":
        raise WorkdayConnectWorkbookError(
            "Administrator workbook must use the .xlsx file extension."
        )
    archive = _validated_archive(path)
    try:
        shared_strings = _shared_strings(archive)
        member = _worksheet_member(archive, WORKSHEET_SHEET_NAME)
        try:
            worksheet = _parse_xml(
                archive.read(member),
                "worksheet",
            )
        except KeyError as exc:
            raise WorkdayConnectWorkbookError(
                "Administrator workbook is missing its Worksheet content."
            ) from exc
    finally:
        archive.close()

    rows: list[dict[int, str]] = []
    for row in worksheet.findall(
        f".//{{{_MAIN_NS}}}sheetData/{{{_MAIN_NS}}}row"
    ):
        values: dict[int, str] = {}
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            reference = str(cell.get("r") or "")
            column = _column_index(reference)
            if column > len(WORKSHEET_HEADERS):
                if _cell_value(cell, shared_strings).strip():
                    raise WorkdayConnectWorkbookError(
                        "Administrator workbook contains unsupported columns."
                    )
                continue
            values[column] = _cell_value(cell, shared_strings)
        rows.append(values)
        if len(rows) > _MAX_WORKSHEET_ROWS:
            raise WorkdayConnectWorkbookError(
                "Administrator workbook contains too many worksheet rows."
            )
    if not rows:
        raise WorkdayConnectWorkbookError(
            "Administrator workbook Worksheet sheet is empty."
        )
    observed_headers = tuple(
        rows[0].get(index, "").strip()
        for index in range(1, len(WORKSHEET_HEADERS) + 1)
    )
    if observed_headers != WORKSHEET_HEADERS:
        raise WorkdayConnectWorkbookError(
            "Administrator workbook Worksheet headers were changed."
        )

    worksheet_lines = []
    for row in rows[1:]:
        label = row.get(1, "").strip()
        answer = " ".join(row.get(5, "").splitlines()).strip()
        if not label and not answer:
            continue
        if not label:
            raise WorkdayConnectWorkbookError(
                "Administrator workbook contains an answer without a label."
            )
        worksheet_lines.append(f"{label}: {answer}")
    if not worksheet_lines:
        raise WorkdayConnectWorkbookError(
            "Administrator workbook does not contain worksheet rows."
        )
    return "\n".join(worksheet_lines) + "\n"
