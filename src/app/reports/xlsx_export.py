"""Minimal multi-sheet XLSX writer (stdlib only — Excel-compatible OOXML)."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_xml(headers: list[str], rows: list[list[str]]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>',
    ]
    cells = []
    for i, h in enumerate(headers, start=1):
        ref = f"{_col_letter(i)}1"
        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(h))}</t></is></c>')
    parts.append(f'<row r="1">{"".join(cells)}</row>')
    for r_idx, row in enumerate(rows, start=2):
        cells = []
        for c_idx, val in enumerate(row, start=1):
            ref = f"{_col_letter(c_idx)}{r_idx}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(val))}</t></is></c>'
            )
        parts.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def build_xlsx(sheets: dict[str, tuple[list[str], list[list[str]]]]) -> bytes:
    """sheets: name -> (headers, data rows). Returns .xlsx bytes."""
    if not sheets:
        sheets = {"Sheet1": (["empty"], [])}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        ct = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
            '<Default Extension="xml" ContentType="application/xml"/>',
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        ]
        wb_sheets: list[str] = []
        wb_rels = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        ]
        for i, (name, (headers, rows)) in enumerate(sheets.items(), start=1):
            path = f"xl/worksheets/sheet{i}.xml"
            zf.writestr(path, _sheet_xml(headers, rows))
            safe = escape((name or f"Sheet{i}")[:31])
            wb_sheets.append(f'<sheet name="{safe}" sheetId="{i}" r:id="rId{i}"/>')
            wb_rels.append(
                f'<Relationship Id="rId{i}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{i}.xml"/>'
            )
            ct.append(
                f'<Override PartName="/{path}" '
                f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        ct.append("</Types>")
        wb_rels.append("</Relationships>")
        zf.writestr("[Content_Types].xml", "".join(ct))
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(wb_sheets)}</sheets></workbook>',
        )
        zf.writestr("xl/_rels/workbook.xml.rels", "".join(wb_rels))
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>',
        )
    return buf.getvalue()
