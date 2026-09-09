"""
native_table.py — turn a "shape-grid" fake table into one real PowerPoint table.

The problem this solves
------------------------
Some pptx-authoring pipelines (notably HTML/DOM-to-pptx exporters, which is how
many HTML-to-pptx exporters produce slides this way) draw a
table by emitting one shape per visual element: a colored rectangle for each
cell's background, plus a separate text box for each cell's text. A modest
financial table can easily become 300-450 shapes on a single slide. It LOOKS
like a table but PowerPoint has no idea it's a table — it can't be selected,
resized, restyled, or edited as one; it can't be copied into Excel as a table;
and file size/complexity balloon.

This module detects that pattern and replaces it with a single native
<a:tbl> graphics frame (what you get from PowerPoint's own Insert > Table),
styled to look pixel-identical to the shape-grid version.

Two entry points:
  - extract_grid(slide, bbox, ...)   -> a plain-data description of the fake table
  - build_native_table(slide, extraction) -> creates the real table, deletes the
                                              original shapes, returns the new shape

See SKILL.md for the full workflow. See references/ for the border/style XML
gotchas this module works around.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from lxml import etree

# "No Style, No Grid" built-in table style GUID. Applying this stops PowerPoint
# from painting its own banding/borders on top of the fills you set per cell —
# without it, add_table()'s default theme style fights every fill() call you make.
NO_STYLE_NO_GRID = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"

_ALIGN_LOOKUP = {
    "left": PP_ALIGN.LEFT,
    "center": PP_ALIGN.CENTER,
    "right": PP_ALIGN.RIGHT,
    None: None,
}


# --------------------------------------------------------------------------
# Data shapes
# --------------------------------------------------------------------------

@dataclass
class RunSpec:
    text: str
    bold: bool = False
    italic: bool = False
    size_pt: Optional[float] = None
    font_name: Optional[str] = None
    color_hex: Optional[str] = None  # "RRGGBB", no '#'


@dataclass
class CellSpec:
    runs: list = field(default_factory=list)   # list[RunSpec]
    align: Optional[str] = None                # "left" | "center" | "right"
    fill_hex: Optional[str] = None              # None = no fill (transparent)
    bottom_border_hex: Optional[str] = None      # set on last row of a totals band
    bottom_border_pt: float = 1.25


@dataclass
class GridExtraction:
    matrix: list                 # list[list[CellSpec]], rows x cols
    row_heights_in: list          # inches, one per row (use pitch, not shape height — see note below)
    col_widths_in: list           # inches, one per column
    left_in: float
    top_in: float
    shapes_to_remove: list = field(default_factory=list)  # the original shapes this table replaces


# --------------------------------------------------------------------------
# Detection / extraction from an existing "shape-grid" table
# --------------------------------------------------------------------------

def _cluster(values, tol):
    values = sorted(values)
    buckets = []
    for v in values:
        if buckets and abs(v - buckets[-1][-1]) <= tol:
            buckets[-1].append(v)
        else:
            buckets.append([v])
    return [sum(b) / len(b) for b in buckets]


def _nearest(v, buckets):
    return min(range(len(buckets)), key=lambda i: abs(buckets[i] - v))


def _fill_hex(shape):
    try:
        if shape.fill.type is not None:
            return str(shape.fill.fore_color.rgb)
    except Exception:
        return None
    return None


def _runs_of(shape):
    if not shape.has_text_frame or not shape.text_frame.paragraphs:
        return None, None
    para = shape.text_frame.paragraphs[0]
    if not para.runs:
        return None, None
    align_map = {1: "left", 2: "center", 3: "right"}
    align = align_map.get(int(para.alignment) if para.alignment is not None else -1)
    runs = []
    for r in para.runs:
        color = None
        try:
            if r.font.color and r.font.color.type is not None:
                color = str(r.font.color.rgb)
        except Exception:
            pass
        runs.append(RunSpec(
            text=r.text, bold=bool(r.font.bold), italic=bool(r.font.italic),
            size_pt=(r.font.size.pt if r.font.size else None),
            font_name=r.font.name, color_hex=color,
        ))
    return runs, align


def extract_grid(slide, bbox, n_rows=None, row_tol=0.08, col_tol=0.15,
                  min_col_fill_frac=0.15, band_min_height_in=0.05):
    """
    Scan `slide` for shapes inside `bbox` (left, top, right, bottom — inches)
    and reassemble them into a row/column grid.

    Cell background is taken from the tallest "band" shape at that position
    (height >= band_min_height_in). Thinner shapes at the same position are
    treated as hairline border accents, not fills — many shape-grid exports
    build a totals row's top/bottom rule as a strip of skinny per-column
    rectangles instead of one border. If the last of those hairlines under a
    row is a different color from the row's own fill, it's recorded as that
    row's `bottom_border_hex` and applied as a real cell border on rebuild.

    Row height is the PITCH between consecutive row tops, not a cell's own
    shape height — shape heights in these exports are often taller than the
    actual row spacing (to allow vertical padding), and using them directly
    makes the rebuilt table overrun into whatever sits below it (e.g.
    footnotes). Using the gap between row tops instead reproduces the
    original spacing exactly.

    Columns present in fewer than `min_col_fill_frac` of rows are dropped —
    these are almost always unrelated shapes (footnote text, captions) that
    happened to fall inside `bbox`, not real table columns.

    Returns a GridExtraction. Inspect it (especially `matrix` text and
    `shapes_to_remove` count) before calling build_native_table — this is a
    heuristic clustering, not a guarantee, and you (Claude) should sanity
    check the dumped matrix against what the slide visually shows.
    """
    left, top, right, bottom = bbox
    cands = []
    for shp in slide.shapes:
        l, t, w, h = shp.left / 914400, shp.top / 914400, shp.width / 914400, shp.height / 914400
        if left <= l <= right and top <= t <= bottom:
            cands.append((shp, l, t, w, h))

    if not cands:
        raise ValueError("No shapes found inside bbox — check the coordinates (inches, EMU/914400).")

    row_tops = _cluster([c[2] for c in cands], row_tol)
    col_lefts = _cluster([c[1] for c in cands], col_tol)

    cells = {}
    for shp, l, t, w, h in cands:
        r = _nearest(t, row_tops)
        c = _nearest(l, col_lefts)
        key = (r, c)
        entry = cells.setdefault(key, {"bands": [], "hairlines": [], "text_shape": None})
        text = shp.text_frame.text if shp.has_text_frame else ""
        if text.strip():
            entry["text_shape"] = shp
        else:
            if h >= band_min_height_in:
                entry["bands"].append((_fill_hex(shp), w, h, l, t))
            else:
                entry["hairlines"].append((_fill_hex(shp), t))

    total_rows = n_rows or len(row_tops)
    row_range = range(total_rows)

    good_cols = []
    for c in range(len(col_lefts)):
        n_nonempty = sum(
            1 for r in row_range
            if cells.get((r, c), {}).get("text_shape") is not None
            and cells[(r, c)]["text_shape"].text_frame.text.strip()
        )
        if n_nonempty / max(total_rows, 1) >= min_col_fill_frac:
            good_cols.append(c)

    matrix = []
    row_bottom_border = []
    for r in row_range:
        row_out = []
        last_hairline = None
        for c in good_cols:
            entry = cells.get((r, c), {})
            fill_hex = entry["bands"][0][0] if entry.get("bands") else None
            runs, align = (None, None)
            if entry.get("text_shape") is not None:
                runs, align = _runs_of(entry["text_shape"])
            row_out.append(CellSpec(runs=runs or [], align=align, fill_hex=fill_hex))
            if entry.get("hairlines"):
                last_hairline = entry["hairlines"][-1][0]
        row_bottom_border.append(last_hairline)
        matrix.append(row_out)

    # apply detected bottom border color to every cell in that row
    for r, color in enumerate(row_bottom_border):
        if color and color != matrix[r][0].fill_hex:
            for cell in matrix[r]:
                cell.bottom_border_hex = color

    # row heights = pitch between consecutive tops (see docstring)
    row_heights = []
    for i in range(total_rows):
        if i + 1 < len(row_tops):
            row_heights.append(row_tops[i + 1] - row_tops[i])
        else:
            row_heights.append(row_heights[-1] if row_heights else 0.2)

    col_widths = []
    for c in good_cols:
        ws = [cells[(r, c)]["bands"][0][1] for r in row_range
              if (r, c) in cells and cells[(r, c)]["bands"]]
        if not ws:
            ws = [cells[(r, c)]["text_shape"].width / 914400 for r in row_range
                  if (r, c) in cells and cells[(r, c)].get("text_shape")]
        col_widths.append(max(ws) if ws else 1.0)

    table_left = min(
        (cells[(0, c)]["bands"][0][3] for c in good_cols if cells.get((0, c), {}).get("bands")),
        default=left,
    )

    shapes_to_remove = [shp for shp, l, t, w, h in cands]

    return GridExtraction(
        matrix=matrix, row_heights_in=row_heights, col_widths_in=col_widths,
        left_in=table_left, top_in=row_tops[0], shapes_to_remove=shapes_to_remove,
    )


# --------------------------------------------------------------------------
# Building the real table
# --------------------------------------------------------------------------

def _set_table_style(table, style_guid=NO_STYLE_NO_GRID):
    tbl = table._tbl
    tblPr = tbl.find(qn("a:tblPr"))
    if tblPr is None:
        tblPr = etree.SubElement(tbl, qn("a:tblPr"))
    for child in list(tblPr):
        tblPr.remove(child)
    tblPr.set("firstRow", "0")
    tblPr.set("bandRow", "0")
    style_id = etree.SubElement(tblPr, qn("a:tableStyleId"))
    style_id.text = style_guid


def _clear_cell_borders(cell):
    tc = cell._tc
    tcPr = tc.find(qn("a:tcPr"))
    if tcPr is None:
        tcPr = etree.SubElement(tc, qn("a:tcPr"))
    for edge in ("lnL", "lnR", "lnT", "lnB"):
        for el in tcPr.findall(qn(f"a:{edge}")):
            tcPr.remove(el)
        ln = etree.Element(qn(f"a:{edge}"))
        ln.set("w", "3175")
        etree.SubElement(ln, qn("a:noFill"))
        tcPr.insert(0, ln)


def set_cell_border(cell, edge, color_hex, width_pt=0.75):
    """edge in {'lnL','lnR','lnT','lnB'}. python-pptx has no high-level API for
    per-cell borders — this edits the <a:tcPr> XML directly."""
    tc = cell._tc
    tcPr = tc.find(qn("a:tcPr"))
    if tcPr is None:
        tcPr = etree.SubElement(tc, qn("a:tcPr"))
    tag = qn(f"a:{edge}")
    existing = tcPr.find(tag)
    if existing is not None:
        tcPr.remove(existing)
    ln = etree.Element(tag)
    ln.set("w", str(int(width_pt * 12700)))
    ln.set("cap", "flat")
    fill = etree.SubElement(ln, qn("a:solidFill"))
    clr = etree.SubElement(fill, qn("a:srgbClr"))
    clr.set("val", color_hex)
    tcPr.insert(0, ln)


def build_native_table(slide, extraction: GridExtraction, delete_originals=True,
                        default_font="Calibri", cell_margins_in=(0.05, 0.05, 0.01, 0.01)):
    """
    Create one real table shape on `slide` from a GridExtraction and (by
    default) delete the shapes it replaces. Returns the new GraphicFrame.

    cell_margins_in = (left, right, top, bottom), matching the tight vertical
    rhythm typical of financial tables — PowerPoint's table default margins
    (0.1in top/bottom) will visibly loosen row spacing versus the original.
    """
    n_rows = len(extraction.matrix)
    n_cols = len(extraction.matrix[0]) if n_rows else 0
    total_w = sum(extraction.col_widths_in)
    total_h = sum(extraction.row_heights_in)

    gframe = slide.shapes.add_table(
        n_rows, n_cols,
        Inches(extraction.left_in), Inches(extraction.top_in),
        Inches(total_w), Inches(total_h),
    )
    table = gframe.table
    _set_table_style(table)

    for c, w in enumerate(extraction.col_widths_in):
        table.columns[c].width = Inches(w)
    for r, h in enumerate(extraction.row_heights_in):
        table.rows[r].height = Inches(h)

    ml, mr, mt, mb = cell_margins_in
    for r in range(n_rows):
        for c in range(n_cols):
            spec: CellSpec = extraction.matrix[r][c]
            cell = table.cell(r, c)
            cell.margin_left, cell.margin_right = Inches(ml), Inches(mr)
            cell.margin_top, cell.margin_bottom = Inches(mt), Inches(mb)

            if spec.fill_hex:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(spec.fill_hex)
            else:
                cell.fill.background()

            _clear_cell_borders(cell)
            if spec.bottom_border_hex:
                set_cell_border(cell, "lnB", spec.bottom_border_hex, spec.bottom_border_pt)

            tf = cell.text_frame
            tf.word_wrap = True
            para = tf.paragraphs[0]
            for run_el in list(para._p.findall(qn("a:r"))):
                para._p.remove(run_el)
            para.alignment = _ALIGN_LOOKUP.get(spec.align)
            for rs in spec.runs:
                run = para.add_run()
                run.text = rs.text
                run.font.name = rs.font_name or default_font
                run.font.bold = rs.bold
                run.font.italic = rs.italic
                if rs.size_pt:
                    run.font.size = Pt(rs.size_pt)
                if rs.color_hex:
                    run.font.color.rgb = RGBColor.from_string(rs.color_hex)

    if delete_originals:
        for shp in extraction.shapes_to_remove:
            el = shp._element
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    return gframe


# --------------------------------------------------------------------------
# Convenience: build a table directly from plain data (new decks)
# --------------------------------------------------------------------------

def table_from_rows(slide, rows, left_in, top_in, col_widths_in, row_height_in=0.16,
                     header_fill="142838", header_font_color="FFFFFF",
                     band_fill=None, font_name="Calibri", font_size_pt=9,
                     header_font_size_pt=9):
    """
    Quick path for building a NEW native table from scratch (no shape-grid to
    convert) — e.g. when you're the one authoring the deck and want to do it
    right the first time instead of drawing per-cell rectangles + text boxes.

    rows: list[list[str]] — first row is treated as the header.
    band_fill: optional hex to shade every other data row (simple alternating
    banding). For row-specific shading (subtotal/total rows), build a
    GridExtraction-style matrix of CellSpec directly and call
    build_native_table instead — this helper is for the common simple case.
    """
    n_rows, n_cols = len(rows), len(rows[0])
    matrix = []
    for r, row in enumerate(rows):
        is_header = (r == 0)
        row_specs = []
        for c, text in enumerate(row):
            fill = header_fill if is_header else (band_fill if (band_fill and r % 2 == 0) else None)
            color = header_font_color if is_header else "000000"
            align = "left" if c == 0 else "right"
            row_specs.append(CellSpec(
                runs=[RunSpec(text=str(text), bold=is_header, size_pt=(header_font_size_pt if is_header else font_size_pt),
                              font_name=font_name, color_hex=color)],
                align=align, fill_hex=fill,
            ))
        matrix.append(row_specs)

    extraction = GridExtraction(
        matrix=matrix,
        row_heights_in=[row_height_in] * n_rows,
        col_widths_in=col_widths_in,
        left_in=left_in, top_in=top_in,
        shapes_to_remove=[],
    )
    return build_native_table(slide, extraction, delete_originals=False, default_font=font_name)
