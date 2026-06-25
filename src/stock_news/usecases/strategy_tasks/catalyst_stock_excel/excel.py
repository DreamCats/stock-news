"""策略任务 Excel 文件生成。

这里用标准库生成最小 xlsx，避免为简单表格引入额外依赖。
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape


@dataclass(frozen=True)
class ExcelTable:
    """待写入 xlsx 的表格数据。"""

    headers: list[str]
    rows: list[list[object]]
    sheet_name: str = "Sheet1"


def write_xlsx(path: Path, table: ExcelTable) -> Path:
    """写入一个单工作表 xlsx 文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml())
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("xl/workbook.xml", _workbook_xml(table.sheet_name))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml())
        archive.writestr("xl/worksheets/sheet1.xml", _worksheet_xml(table))
    return path


def _worksheet_xml(table: ExcelTable) -> str:
    rows: list[list[object]] = [list(table.headers), *table.rows]
    row_xml = "\n".join(
        _row_xml(row_index, row) for row_index, row in enumerate(rows, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<cols><col min="1" max="1" width="8" customWidth="1"/>'
        '<col min="2" max="2" width="28" customWidth="1"/>'
        '<col min="3" max="3" width="20" customWidth="1"/>'
        '<col min="4" max="4" width="36" customWidth="1"/>'
        '<col min="5" max="5" width="42" customWidth="1"/></cols>'
        f"<sheetData>{row_xml}</sheetData>"
        "</worksheet>"
    )


def _row_xml(row_index: int, values: list[object]) -> str:
    cells = "".join(
        _cell_xml(row_index, column_index, value)
        for column_index, value in enumerate(values, start=1)
    )
    return f'<row r="{row_index}">{cells}</row>'


def _cell_xml(row_index: int, column_index: int, value: object) -> str:
    ref = f"{_column_name(column_index)}{row_index}"
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _column_name(index: int) -> str:
    name = ""
    current = index
    while current:
        current, remainder = divmod(current - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _content_types_xml() -> str:
    rels_type = "application/vnd.openxmlformats-package.relationships+xml"
    workbook_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    )
    worksheet_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Default Extension="rels" ContentType="{rels_type}"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{workbook_type}"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        f'ContentType="{worksheet_type}"/>'
        "</Types>"
    )


def _root_rels_xml() -> str:
    rel_type = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
        "officeDocument"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">'
        f'<Relationship Id="rId1" Type="{rel_type}" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(sheet_name: str) -> str:
    escaped_name = escape(sheet_name[:31] or "Sheet1")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{escaped_name}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""


def _workbook_rels_xml() -> str:
    rel_type = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">'
        f'<Relationship Id="rId1" Type="{rel_type}" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
