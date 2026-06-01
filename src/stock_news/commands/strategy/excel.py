"""策略快报 Excel 渲染."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from .utils import _unique_texts

Cell = tuple[Any, int | None]


def _col_name(index: int) -> str:
    name = ""
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _xml(value: object) -> str:
    return escape(str(value), quote=True)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(str(item) for item in value if item)
    return str(value)


def _cell(value: Any, style: int | None = None) -> Cell:
    return value, style


def _sheet_xml(rows: list[list[Cell]], widths: list[int]) -> str:
    col_defs = "".join(
        f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>'
        for i, width in enumerate(widths, start=1)
    )
    xml_rows: list[str] = []
    for row_idx, row in enumerate(rows, start=1):
        cells: list[str] = []
        for col_idx, (value, style) in enumerate(row, start=1):
            ref = f"{_col_name(col_idx)}{row_idx}"
            style_attr = f' s="{style}"' if style is not None else ""
            if value is None:
                cells.append(f'<c r="{ref}"{style_attr}/>')
            elif isinstance(value, int | float) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"{style_attr}><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"{style_attr}>'
                    f"<is><t>{_xml(_text(value))}</t></is></c>"
                )
        xml_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <cols>{col_defs}</cols>
  <sheetData>{"".join(xml_rows)}</sheetData>
</worksheet>
"""


def _workbook_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="推荐个股" sheetId="1" r:id="rId1"/>
    <sheet name="推荐人可信度" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>
"""


def _styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="1"><numFmt numFmtId="164" formatCode="0.0%"/></numFmts>
  <fonts count="2">
    <font><sz val="11"/><name val="Arial"/></font>
    <font><b/><sz val="11"/><name val="Arial"/></font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill>
      <patternFill patternType="solid">
        <fgColor rgb="FFEFEFEF"/><bgColor indexed="64"/>
      </patternFill>
    </fill>
  </fills>
  <borders count="1">
    <border><left/><right/><top/><bottom/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="4">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="1" borderId="0" xfId="0"
      applyFont="1" applyFill="1"/>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0"
      applyNumberFormat="1"/>
    <xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0"
      applyNumberFormat="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>
"""


def _candidate_rows(payload: dict[str, Any]) -> list[list[Cell]]:
    rows = [
        [
            _cell("标的", 1),
            _cell("代码", 1),
            _cell("Score", 1),
            _cell("置信度", 1),
            _cell("推荐人", 1),
            _cell("入选原因", 1),
            _cell("核心证据", 1),
            _cell("风险提示", 1),
        ]
    ]
    for item in payload.get("candidate_trades") or []:
        senders = "、".join(str(sender) for sender in item.get("senders", [])[:5])
        evidences = _unique_texts(item.get("evidences") or item.get("reasons") or [], 2)
        rows.append(
            [
                _cell(item.get("target_name")),
                _cell(item.get("ticker")),
                _cell(item.get("score"), 3),
                _cell(item.get("confidence"), 2),
                _cell(senders),
                _cell(_text(item.get("why_selected"))),
                _cell(_text(evidences)),
                _cell(_text(item.get("risks")) or "-"),
            ]
        )
    if len(rows) == 1:
        rows.append([_cell("本轮无新增可交易个股")] + [_cell(None)] * 7)
    return rows


def _sender_rows(payload: dict[str, Any]) -> list[list[Cell]]:
    rows = [
        [
            _cell("推荐人", 1),
            _cell("T+5胜率", 1),
            _cell("样本数", 1),
            _cell("T+5均收益", 1),
            _cell("T+5超额", 1),
            _cell("最近命中样本", 1),
        ]
    ]
    for item in payload.get("sender_credibility") or []:
        sender = str(item.get("sender") or "")
        if item.get("whitelisted"):
            sender = f"{sender}（白名单）"
        rows.append(
            [
                _cell(sender),
                _cell(item.get("win_rate_t5"), 2),
                _cell(item.get("count")),
                _cell(item.get("avg_ret_t5"), 2),
                _cell(item.get("avg_excess_t5"), 2),
                _cell("、".join(item.get("samples") or []) or "-"),
            ]
        )
    if len(rows) == 1:
        rows.append([_cell("本轮涉及推荐人暂无满足阈值的回测样本")] + [_cell(None)] * 5)
    return rows


def write_strategy_xlsx(payload: dict[str, Any], path: Path) -> None:
    """写出包含策略两张表的 xlsx 文件."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels"
    ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
""",
        )
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="xl/workbook.xml"/>
</Relationships>
""",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
    Target="styles.xml"/>
</Relationships>
""",
        )
        zf.writestr("xl/workbook.xml", _workbook_xml())
        zf.writestr("xl/styles.xml", _styles_xml())
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            _sheet_xml(_candidate_rows(payload), [16, 14, 10, 10, 24, 28, 54, 40]),
        )
        zf.writestr(
            "xl/worksheets/sheet2.xml",
            _sheet_xml(_sender_rows(payload), [20, 12, 10, 12, 12, 32]),
        )
