#!/usr/bin/env python3
"""
build_docx.py - render a finished research brief from markdown into a Word
document in the study-guide design system.

This script owns how the document looks. Nothing upstream decides styling,
and the brief markdown carries no formatting intent beyond structure:
headings, body, bullets, tables, links, and the tag markers.

Typography and page furniture:

    Doc title  (#)   Palatino  dusty rose #9E6474  20pt  ALL CAPS + rose keyline
    Section number   Palatino  rose      #D98F98  10pt  ALL CAPS
    Section   (##)   Palatino  dusty rose #9E6474  20pt  ALL CAPS + rose keyline
    Subsection(###)  Palatino  mid rose  #B98292  15pt  Capitalized
    Title    (####)  Palatino  mid rose  #B98292  11pt  bold, Capitalized
    Body             Times New Roman  black   11pt  justified, 1.15 spacing

    Header  MULTIAGENT STUDY & TUTORING ASSISTANT | RESEARCH BRIEF  every page
    Footer  [Document] | [Prepared for] | [Month Year]  centred,
            page number right, built from tab stops

Three formatting decisions specific to a research brief:

  - Bullets and tables are retained. A brief comparing four competing
    formulations of the same result across a table cannot be continuous
    prose, and a student skimming before an exam reads structure faster
    than paragraphs.
  - Tables get a dusty rose header row with white text, Times New Roman 10pt
    body, thin rules, no banding, near-square corners.
  - Caveat markers ([DERIVED ESTIMATE], [INFERRED - VERIFY], [PAYWALLED],
    [CONTEXT CONFLICT]) render in red where they appear, and inline
    citations [[n]](url) render as live hyperlinks. A student needs to see
    at a glance which claims are load-bearing and which are provisional.

The keyline appears beneath Sections only, never beneath Subsections or
Titles, even though those levels share the accent palette.

No emoji. No em dash: one in the input is an error in the input, and it is
reported rather than silently passed through.

Usage:
    python3 build_docx.py <brief.md> <out.docx> [--title T] [--prepared-for P]

Prints JSON to stdout:
    {"output_path", "sections", "tables", "hyperlinks", "red_runs",
     "unresolved_links", "dropped_blocks", "em_dashes"}
"""
import json
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROSE = RGBColor(0xD9, 0x8F, 0x98)
ROSE_DEEP = RGBColor(0x9E, 0x64, 0x74)
MID_ROSE = RGBColor(0xB9, 0x82, 0x92)
BLACK = RGBColor(0x00, 0x00, 0x00)
RED = RGBColor(0xC0, 0x1A, 0x1A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

HEAD_FONT = "Palatino Linotype"
BODY_FONT = "Times New Roman"

CAVEAT_MARKERS = [
    "[DERIVED ESTIMATE]",
    "[INFERRED - VERIFY]",
    "[PAYWALLED]",
    "[CONTEXT CONFLICT]",
    "[PDF PREVIEW ONLY]",
]

LINK_RE = re.compile(r"\[\[(\d+)\]\]\((https?://[^\s)]+)\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# `*[DERIVED ESTIMATE]*` - the writer wraps bracketed tags in markdown
# emphasis. The tag is already styled here, so the asterisks are pure noise
# and would otherwise print literally.
TAG_EMPHASIS_RE = re.compile(r"\*{1,2}(\[[^\[\]]{1,60}\])\*{1,2}")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


# ─── low-level helpers ───────────────────────────────────────────────────

def _set_font(run, name, size, color, bold=False, caps=False):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.all_caps = caps
    # East-Asian font binding, so Word does not substitute silently.
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rFonts.set(qn(attr), name)


def _keyline(paragraph, color="C9972B", size=8):
    """Gold rule beneath a Section title. Sections only."""
    pPr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    pPr.append(borders)


def _shade(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _add_hyperlink(paragraph, url, text):
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    for tag, val in (("w:color", "405A67"), ("w:u", "single")):
        el = OxmlElement(tag)
        el.set(qn("w:val"), "single" if tag == "w:u" else val)
        rPr.append(el)
    fonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi"):
        fonts.set(qn(attr), BODY_FONT)
    rPr.append(fonts)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "22")
    rPr.append(sz)
    new_run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


# ─── inline rendering ────────────────────────────────────────────────────

def _emit_inline(paragraph, text, stats, size=11, color=BLACK, bold_all=False):
    """Render one line of body text: links, caveat markers, bold."""
    text = TAG_EMPHASIS_RE.sub(r"\1", text)
    pos = 0
    for m in LINK_RE.finditer(text):
        if m.start() > pos:
            _emit_plain(paragraph, text[pos:m.start()], stats, size, color, bold_all)
        _add_hyperlink(paragraph, m.group(2), f"[{m.group(1)}]")
        stats["hyperlinks"] += 1
        pos = m.end()
    if pos < len(text):
        _emit_plain(paragraph, text[pos:], stats, size, color, bold_all)


def _emit_plain(paragraph, text, stats, size, color, bold_all):
    """Emit runs, handling **bold** and the red caveat markers together.

    Bold is resolved FIRST, then caveat markers inside each fragment. Doing it
    the other way round splits `**[DERIVED ESTIMATE] EUR 287M**` on the marker,
    orphans the two `**` halves into separate fragments where the bold pattern
    can no longer match either, and prints the asterisks literally.
    """
    for fragment, is_bold in _split_bold(text):
        for piece, is_caveat in _split_caveats(fragment):
            run = paragraph.add_run(piece)
            if is_caveat:
                # Red already carries the emphasis. Bolding it too makes a
                # dense page look shouted at.
                _set_font(run, BODY_FONT, size, RED, bold=False)
                stats["red_runs"] += 1
            else:
                _set_font(run, BODY_FONT, size, color, bold=(is_bold or bold_all))


def _split_bold(text):
    """[(fragment, is_bold), ...] - **markers** removed."""
    out, pos = [], 0
    for m in BOLD_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out or [(text, False)]


def _split_caveats(text):
    """[(piece, is_caveat), ...] - marker text kept, it is what turns red."""
    tokens = [(text, False)]
    for marker in CAVEAT_MARKERS:
        new = []
        for piece, flagged in tokens:
            if flagged:
                new.append((piece, True))
                continue
            parts = piece.split(marker)
            for i, part in enumerate(parts):
                if i:
                    new.append((marker, True))
                if part:
                    new.append((part, False))
        tokens = new
    return [t for t in tokens if t[0]]


# ─── block rendering ─────────────────────────────────────────────────────

def _add_heading(doc, text, level, stats):
    if level == 1:
        # The document's own title. Section styling, but no section number:
        # "SECTION 01" above the report's title reads as a numbering error.
        stats["titles"] += 1
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(12)
        r = p.add_run(text)
        _set_font(r, HEAD_FONT, 20, ROSE_DEEP, caps=True)
        _keyline(p)
        return
    if level == 2:
        stats["sections"] += 1
        num = doc.add_paragraph()
        num.paragraph_format.space_before = Pt(18)
        num.paragraph_format.space_after = Pt(0)
        r = num.add_run(f"SECTION {stats['sections']:02d}")
        _set_font(r, HEAD_FONT, 10, ROSE, caps=True)

        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(10)
        r = p.add_run(text)
        _set_font(r, HEAD_FONT, 20, ROSE_DEEP, caps=True)
        _keyline(p)
        return
    if level == 3:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(text)
        _set_font(r, HEAD_FONT, 15, MID_ROSE)
        return
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    _set_font(r, HEAD_FONT, 11, MID_ROSE, bold=True)


def _add_body(doc, text, stats, bullet=False):
    p = doc.add_paragraph(style="List Bullet" if bullet else None)
    pf = p.paragraph_format
    pf.line_spacing = 1.15
    pf.space_after = Pt(6)
    if not bullet:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    else:
        pf.left_indent = Inches(0.25)
    _emit_inline(p, text, stats)


def _add_table(doc, rows, stats):
    """Render a markdown table so the numbers are actually readable.

    A benchmarking memo's comparables matrix can run to eight or nine columns.
    Word's default autofit gives one long text cell most of the width and
    squeezes the numeric columns until they wrap mid-figure, which is exactly
    what makes a dense table unreadable. So: font size steps down as the table
    widens, column widths are proportional to the content each column actually
    holds (clamped so no column collapses), numeric columns are right-aligned,
    the header row repeats across page breaks, and the heavy full grid is
    replaced with thin rules.
    """
    stats["tables"] += 1
    ncols = max(len(r) for r in rows)

    # Font steps down with width. Eight columns at 10pt does not fit.
    size = 10 if ncols <= 4 else (9 if ncols <= 6 else 8)

    t = doc.add_table(rows=len(rows), cols=ncols)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    _thin_borders(t)

    # Cell padding is charged per column before anything is distributed, so a
    # three-character column is not left with less usable width than its own
    # margins. Wide tables get tighter margins to buy that space back.
    pad_in = 0.04 if ncols > 4 else 0.08
    _cell_margins(t, pad_in)

    # Proportional widths from the widest cell in each column, clamped so a
    # long prose column cannot starve the numeric ones.
    body = rows[1:] or rows
    numeric_col = [
        all(_is_numeric(r[ci]) for r in body if ci < len(r) and (r[ci] or "").strip())
        and any(ci < len(r) and (r[ci] or "").strip() for r in body)
        for ci in range(ncols)
    ]
    weights = []
    for ci in range(ncols):
        head = len(rows[0][ci]) if ci < len(rows[0]) else 0
        longest = max(
            [len((r[ci] if ci < len(r) else "")) for r in body] +
            # Headers are bold, so they need slightly more room per character
            # than the body text they sit above, or they wrap alone.
            [int(head * 1.3) + 1]
        )
        weights.append(max(8, min(longest, 40)))
    total = float(sum(weights)) or 1.0
    overhead = Inches(pad_in * 2 + 0.02)
    free = max(Inches(1.0), Inches(6.5) - overhead * ncols)
    col_w = [int(overhead + free * (w / total)) for w in weights]

    for ri, row in enumerate(rows):
        for ci in range(ncols):
            cell = t.cell(ri, ci)
            cell.width = col_w[ci]
            p = cell.paragraphs[0]
            for stale in list(p.runs):
                stale._element.getparent().remove(stale._element)
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            val = row[ci] if ci < len(row) else ""

            if ri == 0:
                _shade(cell, "20323B")
                # Header cells go through the inline renderer too, or a
                # markdown-bolded header prints its own asterisks.
                for frag, _ in _split_bold(val):
                    r = p.add_run(frag)
                    _set_font(r, BODY_FONT, size, WHITE, bold=True)
                if numeric_col[ci]:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            else:
                _emit_inline(p, val, stats, size=size)
                if numeric_col[ci] or _is_numeric(val):
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # The table grid has to agree with the cell widths, or Word re-lays the
    # table out from its own uniform default and every width above is ignored.
    for ci, w in enumerate(col_w):
        t.columns[ci].width = w

    _repeat_header(t)


def _cell_margins(table, inches: float):
    tblPr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for edge, val in (("top", 20), ("bottom", 20),
                      ("left", int(inches * 1440)), ("right", int(inches * 1440))):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tblPr.append(mar)


def _is_numeric(val: str) -> bool:
    """A cell that is essentially a figure, so it should sit right-aligned."""
    v = re.sub(r"\*\*|\[|\]", "", (val or "")).strip()
    if not v:
        return False
    return bool(re.fullmatch(r"[~<>=+-]?\s*(EUR|USD|GBP|€|\$|£)?\s*[\d][\d,.\s]*"
                             r"(%|M|bn|mm|km|MW|kW|x|/kW|/km|/mile|\s*-\s*[\d][\d,.]*)*\.?", v, re.I))


def _thin_borders(table):
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")          # 0.5pt
        el.set(qn("w:color"), "B8BEC4")
        borders.append(el)
    tblPr.append(borders)


def _repeat_header(table):
    trPr = table.rows[0]._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


# ─── page furniture ──────────────────────────────────────────────────────

def _header_footer(doc, title, prepared_for, period):
    for section in doc.sections:
        h = section.header.paragraphs[0]
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = h.add_run("MULTIAGENT STUDY & TUTORING ASSISTANT | RESEARCH BRIEF")
        _set_font(r, HEAD_FONT, 9, ROSE_DEEP, caps=True)

        f = section.footer.paragraphs[0]
        f.text = ""
        # tabStops, not PositionalTab: the page number otherwise collapses
        # next to the centred text instead of sitting at the right margin.
        width = section.page_width - section.left_margin - section.right_margin
        f.paragraph_format.tab_stops.add_tab_stop(int(width / 2), WD_TAB_ALIGNMENT.CENTER)
        f.paragraph_format.tab_stops.add_tab_stop(int(width), WD_TAB_ALIGNMENT.RIGHT)
        r = f.add_run("\t" + " | ".join(x for x in (title, prepared_for, period) if x) + "\t")
        _set_font(r, BODY_FONT, 9, ROSE_DEEP)
        _page_number(f)


def _page_number(paragraph):
    run = paragraph.add_run()
    _set_font(run, BODY_FONT, 9, ROSE_DEEP)
    for el, attrs, text in (
        ("w:fldChar", {"w:fldCharType": "begin"}, None),
        ("w:instrText", {"xml:space": "preserve"}, " PAGE "),
        ("w:fldChar", {"w:fldCharType": "end"}, None),
    ):
        e = OxmlElement(el)
        for k, v in attrs.items():
            e.set(qn(k), v)
        if text:
            e.text = text
        run._element.append(e)


# ─── driver ──────────────────────────────────────────────────────────────

def build(md_text, out_path, title=None, prepared_for=None, period=None):
    stats = {"titles": 0, "sections": 0, "tables": 0, "hyperlinks": 0, "red_runs": 0,
             "unresolved_links": [], "dropped_blocks": 0, "em_dashes": 0}

    stats["em_dashes"] = md_text.count("—")

    # A citation link whose target is not a real URL never reaches the page.
    for m in re.finditer(r"\[\[(\d+)\]\](?!\()", md_text):
        stats["unresolved_links"].append(m.group(0))

    doc = Document()
    for s in doc.sections:
        s.left_margin = s.right_margin = Inches(1.0)
        s.top_margin = s.bottom_margin = Inches(0.9)

    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if not line:
            i += 1
            continue

        if line.startswith("```"):
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                i += 1
            i += 1
            continue

        if re.match(r"^-{3,}$", line):
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            _add_heading(doc, m.group(2).strip(), min(len(m.group(1)), 4), stats)
            i += 1
            continue

        # table: a pipe row followed by a separator row
        if line.startswith("|") and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                r = lines[i].strip()
                if not TABLE_SEP_RE.match(r):
                    cells = [c.strip() for c in r.strip("|").split("|")]
                    rows.append(cells)
                i += 1
            if rows:
                _add_table(doc, rows, stats)
            continue

        if re.match(r"^[-*+]\s+", line):
            _add_body(doc, re.sub(r"^[-*+]\s+", "", line), stats, bullet=True)
            i += 1
            continue

        if re.match(r"^\d+[.)]\s+", line):
            _add_body(doc, line, stats, bullet=True)
            i += 1
            continue

        _add_body(doc, line, stats)
        i += 1

    _header_footer(doc, title or "Research Memo", prepared_for or "", period or "")
    doc.save(out_path)
    stats["output_path"] = out_path
    return stats


def main():
    argv = sys.argv[1:]
    opts = {}
    for flag, key in (("--title", "title"), ("--prepared-for", "prepared_for"),
                      ("--period", "period")):
        if flag in argv:
            j = argv.index(flag)
            opts[key] = argv[j + 1]
            del argv[j:j + 2]

    if len(argv) != 2:
        print("usage: build_docx.py <report.md> <out.docx> "
              "[--title T] [--prepared-for P] [--period P]", file=sys.stderr)
        sys.exit(2)

    with open(argv[0], "r", encoding="utf-8") as fh:
        md = fh.read()

    stats = build(md, argv[1], **opts)

    if stats["em_dashes"]:
        print(f"WARNING: {stats['em_dashes']} em dash(es) in the input. House "
              f"style forbids them; fix the markdown, do not fix it here.",
              file=sys.stderr)
    if stats["unresolved_links"]:
        print(f"WARNING: {len(stats['unresolved_links'])} citation marker(s) "
              f"with no URL: {stats['unresolved_links'][:5]}", file=sys.stderr)

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
