#!/usr/bin/env python3
"""
build_pptx.py - render a validated deck outline into an editable .pptx.

This is the terminal step of the `build` stage and the thing that replaces
the external design handoff the pipeline used to end in. It reads the same
validated deck JSON that build_deck.py renders to HTML, so the two outputs
can never describe different content: one input, two renderings.

**The two outputs are not the same artifact, and the difference is
deliberate.**

  preview.html   Exact. Jinja-rendered at 1280x720 and measured by
                 verify_render.py, so what is on screen is what fits.
                 This is the reading and printing view.
  guide.pptx     Editable. Real PowerPoint text frames, tables and
                 shapes built natively here, so a student can retype a
                 definition, drop a slide, or paste one into a study
                 group's deck.

An image-per-slide export would have matched the HTML pixel for pixel and
been far less code. It was rejected: a deck of flat pictures cannot be
corrected, and the single most likely thing a student does with a study
guide is fix something in it. Fidelity is what the HTML is for; this file
exists to be edited. Where the two disagree visually, the HTML is correct.

Layout here is data-driven, not a per-template pixel copy. Each role maps
to a generic arrangement (title band, key message, then the role's own
content as text frames or a native table) using the same palette as the
templates. It reads as the same deck without pretending to be a second
rendering engine.

Usage:
    python3 build_pptx.py <deck.json> <out.pptx> [--title T]

Prints JSON to stdout:
    {"output_path", "slides", "tables", "roles", "unsupported_roles"}
"""
import json
import re
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Emu, Inches, Pt

# ─── Palette ─────────────────────────────────────────────────────────────
# Mirrors templates/*.html. If the templates are recoloured, these move
# with them: this file is the only other place the deck's colours live.
DEEP      = RGBColor(0x9E, 0x64, 0x74)   # grounds: title band, table head
MID       = RGBColor(0xB9, 0x82, 0x92)   # accent tab, section labels
ACCENT    = RGBColor(0xD9, 0x8F, 0x98)   # keylines, markers
INK       = RGBColor(0x5F, 0x4E, 0x53)   # body text
KEY_MSG   = RGBColor(0x63, 0x50, 0x54)
MUTED     = RGBColor(0xB2, 0x9A, 0xA0)   # footnotes
HAIRLINE  = RGBColor(0xF0, 0xDF, 0xE2)
FILL      = RGBColor(0xFD, 0xF8, 0xF8)
FILL_ALT  = RGBColor(0xFB, 0xF2, 0xF3)
WHITE     = RGBColor(0xFF, 0xFF, 0xFF)

FONT = "Montserrat"
FONT_FALLBACK = "Calibri"

# 16:9 at the same aspect as the 1280x720 HTML canvas
SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
M_L = Inches(0.58)          # left margin, matches the templates' 56px
M_R = Inches(0.58)
BODY_W = SLIDE_W - M_L - M_R


# ─── Text helpers ────────────────────────────────────────────────────────
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _plain(value) -> str:
    """HTML-bearing fields (freeform, two_section, contents) carry markup.

    PowerPoint has no HTML importer, so the markup is stripped to text
    rather than rendered. List structure is preserved as line breaks so a
    contents page does not collapse into one paragraph. This is lossy and
    it is the reason the HTML preview stays the reference rendering.
    """
    if value is None:
        return ""
    s = str(value)
    # Order matters here. Headings are matched FIRST, while their closing
    # tags still exist: the generic close-tag rule below would otherwise
    # have already consumed </h1-6> and left nothing to match.
    s = re.sub(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]\s*>",
               lambda m: "\n" + _TAG.sub("", m.group(1)).strip().upper() + "\n",
               s, flags=re.I | re.S)
    # A nested <ol>/<ul> opening inside an <li> has no closing tag before the
    # child's text, so without this the parent item and its first child run
    # together as one word ("DiagonalizationThe criterion").
    s = re.sub(r"<(ol|ul|dl)\b[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"</(li|p|div|dd|tr|h[1-6])>", "\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _TAG.sub("", s)
    s = s.replace("&amp;", "&").replace("&nbsp;", " ")
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&middot;", "-")
    lines = [_WS.sub(" ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _txbox(slide, left, top, width, height):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    return box, tf


def _style(run, size, color, bold=False, italic=False, caps_font=FONT):
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.italic = italic
    run.font.name = caps_font


def _para(tf, text, size, color, bold=False, space_after=4, first=False,
          italic=False, bullet_char=None):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    body = f"{bullet_char}  {text}" if bullet_char else str(text)
    run = p.add_run()
    run.text = body
    _style(run, size, color, bold, italic)
    p.space_after = Pt(space_after)
    return p


def _rect(slide, left, top, width, height, fill=None, line=None):
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(0.75)
    shp.shadow.inherit = False
    return shp


# ─── Shared chrome ───────────────────────────────────────────────────────
def _chrome(slide, title, key_message, page_number):
    """Accent tab, title, key message, keyline, footer bar, page number.

    Geometry is proportional to the HTML chrome rather than copied from it:
    matching to the pixel would mean re-solving each template's type-fitting
    maths here, which is exactly the duplication this file avoids.
    """
    _rect(slide, Emu(0), Inches(0.48), Inches(0.31), Inches(0.375), fill=MID)

    _, tf = _txbox(slide, M_L, Inches(0.42), BODY_W, Inches(0.5))
    _para(tf, str(title).upper(), 24, DEEP, bold=True, first=True, space_after=0)

    top = Inches(0.95)
    if key_message:
        _, tf = _txbox(slide, M_L, top, BODY_W, Inches(0.3))
        _para(tf, key_message, 13, KEY_MSG, first=True, space_after=0)
        top = Inches(1.30)

    _rect(slide, M_L, top, BODY_W, Pt(0.75), fill=HAIRLINE)

    _rect(slide, Emu(0), SLIDE_H - Inches(0.40), SLIDE_W, Inches(0.40), fill=DEEP)
    _rect(slide, Emu(0), SLIDE_H - Inches(0.42), SLIDE_W, Inches(0.02), fill=ACCENT)
    _, tf = _txbox(slide, M_L, SLIDE_H - Inches(0.31), Inches(3), Inches(0.22))
    _para(tf, "STUDY GUIDE", 9, WHITE, bold=True, first=True, space_after=0)
    _, tf = _txbox(slide, SLIDE_W - Inches(1.2), SLIDE_H - Inches(0.31),
                   Inches(0.62), Inches(0.22))
    p = _para(tf, str(page_number), 10, WHITE, bold=True, first=True, space_after=0)
    p.alignment = PP_ALIGN.RIGHT

    return top + Inches(0.22)


def _footnotes(slide, notes):
    if not notes:
        return
    if isinstance(notes, str):
        notes = [notes]
    _, tf = _txbox(slide, M_L, SLIDE_H - Inches(1.02), BODY_W, Inches(0.55))
    for i, n in enumerate(notes):
        _para(tf, _plain(n), 8, MUTED, first=(i == 0), space_after=1)


def _table(slide, left, top, width, headers, rows, col_widths=None):
    n_rows = len(rows) + 1
    n_cols = len(headers)
    height = Inches(0.28) * n_rows
    shape = slide.shapes.add_table(n_rows, n_cols, left, top, width, height)
    tbl = shape.table

    if col_widths and len(col_widths) == n_cols:
        total = float(sum(col_widths)) or 1.0
        for i, w in enumerate(col_widths):
            tbl.columns[i].width = Emu(int(width * (w / total)))

    tbl.first_row = True
    for c, h in enumerate(headers):
        cell = tbl.cell(0, c)
        cell.fill.solid(); cell.fill.fore_color.rgb = DEEP
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = cell.margin_right = Inches(0.06)
        p = cell.text_frame.paragraphs[0]
        p.clear()
        _style(p.add_run(), 9, WHITE, bold=True)
        p.runs[0].text = str(h)

    for r, row in enumerate(rows, start=1):
        for c in range(n_cols):
            cell = tbl.cell(r, c)
            cell.fill.solid()
            cell.fill.fore_color.rgb = FILL if r % 2 else FILL_ALT
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = cell.margin_right = Inches(0.06)
            p = cell.text_frame.paragraphs[0]
            p.clear()
            _style(p.add_run(), 9, INK)
            p.runs[0].text = _plain(row[c]) if c < len(row) else ""
    return shape


def _panel(slide, left, top, width, height, heading, lines, bullet="▪"):
    _rect(slide, left, top, width, Pt(0.75), fill=HAIRLINE)
    _, tf = _txbox(slide, left, top + Inches(0.08), width, Inches(0.22))
    _para(tf, str(heading).upper(), 9, MID, bold=True, first=True, space_after=0)
    _, tf = _txbox(slide, left, top + Inches(0.38), width, height - Inches(0.38))
    for i, ln in enumerate(lines):
        if isinstance(ln, tuple):
            term, meaning = ln
            _para(tf, term, 10, DEEP, bold=True, first=(i == 0), space_after=0)
            _para(tf, meaning, 9, INK, space_after=5)
        else:
            _para(tf, _plain(ln), 9.5, INK, first=(i == 0), space_after=4,
                  bullet_char=bullet)


# ─── Per-role layouts ────────────────────────────────────────────────────
def _r_cover(slide, d, page):
    _rect(slide, Emu(0), Emu(0), SLIDE_W, SLIDE_H, fill=DEEP)
    _, tf = _txbox(slide, M_L, Inches(2.1), Inches(8.6), Inches(1.6))
    _para(tf, _plain(d.get("title", "")).upper(), 40, WHITE, bold=True,
          first=True, space_after=6)
    _, tf = _txbox(slide, M_L, Inches(3.75), Inches(8.6), Inches(0.4))
    _para(tf, _plain(d.get("subtitle", "")).upper(), 15, ACCENT, bold=True,
          first=True, space_after=0)
    _, tf = _txbox(slide, M_L, Inches(4.45), Inches(8.6), Inches(1.1))
    for i, k in enumerate(("course_line", "scope_line", "prepared_for_line")):
        if d.get(k):
            _para(tf, _plain(d[k]), 10, WHITE, first=(i == 0), space_after=3)
    _rect(slide, M_L, Inches(6.35), BODY_W, Pt(0.75), fill=ACCENT)
    _, tf = _txbox(slide, M_L, Inches(6.6), Inches(4), Inches(0.25))
    _para(tf, "STUDY GUIDE", 9, WHITE, bold=True, first=True, space_after=0)
    _, tf = _txbox(slide, SLIDE_W - Inches(4.6), Inches(6.6), Inches(4), Inches(0.25))
    p = _para(tf, _plain(d.get("date_line", "")).upper(), 9, WHITE, first=True,
              space_after=0)
    p.alignment = PP_ALIGN.RIGHT


def _r_section_divider(slide, d, page):
    _rect(slide, Emu(0), Emu(0), SLIDE_W, SLIDE_H, fill=DEEP)
    _, tf = _txbox(slide, M_L, Inches(2.3), Inches(3), Inches(0.5))
    _para(tf, str(d.get("section_number", "")), 22, ACCENT, bold=True,
          first=True, space_after=0)
    _, tf = _txbox(slide, M_L, Inches(2.95), Inches(9), Inches(0.35))
    _para(tf, _plain(d.get("eyebrow", "")).upper(), 10, ACCENT, bold=True,
          first=True, space_after=0)
    _, tf = _txbox(slide, M_L, Inches(3.35), Inches(9.5), Inches(0.9))
    _para(tf, _plain(d.get("title", "")).upper(), 34, WHITE, bold=True,
          first=True, space_after=0)
    if d.get("lede"):
        _, tf = _txbox(slide, M_L, Inches(4.45), Inches(8.5), Inches(0.5))
        _para(tf, _plain(d["lede"]), 12, WHITE, first=True, space_after=0)


def _r_content_grid(slide, d, page):
    top = _chrome(slide, d.get("title"), d.get("key_message"), page)
    quads = (d.get("quads") or [])[:4]
    col_w = (BODY_W - Inches(0.5)) / 2
    row_h = Inches(2.25)
    for i, q in enumerate(quads):
        left = M_L + (col_w + Inches(0.5)) * (i % 2)
        t = top + Inches(0.15) + (row_h + Inches(0.35)) * (i // 2)
        ct = q.get("content_type")
        if ct == "definitions":
            lines = [(_plain(x.get("term", "")), _plain(x.get("meaning", "")))
                     for x in (q.get("definitions") or [])]
            _panel(slide, left, t, col_w, row_h, q.get("title", ""), lines)
        elif ct == "table":
            _, tf = _txbox(slide, left, t + Inches(0.08), col_w, Inches(0.22))
            _para(tf, str(q.get("title", "")).upper(), 9, MID, bold=True,
                  first=True, space_after=0)
            _table(slide, left, t + Inches(0.38), col_w,
                   q.get("table_headers") or [], q.get("table_rows") or [])
        else:
            _panel(slide, left, t, col_w, row_h, q.get("title", ""),
                   q.get("bullets") or [])
    _footnotes(slide, d.get("footnote"))


def _r_comparison_matrix(slide, d, page):
    top = _chrome(slide, d.get("title"), d.get("key_message"), page)
    cols = d.get("columns") or []
    rows = []
    for g in d.get("groups") or []:
        if g.get("group_label"):
            rows.append([_plain(g["group_label"])] + [""] * (len(cols) - 1))
        for r in g.get("rows") or []:
            out = []
            for cell in r.get("cells") or []:
                if isinstance(cell, dict):
                    out.append(" / ".join(
                        _plain(b.get("text", "")) for b in cell.get("bullets") or []))
                else:
                    out.append(_plain(cell))
            rows.append(out)
    if cols:
        _table(slide, M_L, top + Inches(0.2), BODY_W, cols, rows,
               d.get("column_widths"))
    _footnotes(slide, d.get("footnotes"))


def _r_multi_panel(slide, d, page):
    top = _chrome(slide, d.get("title"), d.get("key_message"), page)
    secs = d.get("sections") or []
    n = max(1, min(len(secs), 3))
    gap = Inches(0.4)
    col_w = (BODY_W - gap * (n - 1)) / n
    for i, s in enumerate(secs[:n]):
        left = M_L + (col_w + gap) * i
        if s.get("content_type") == "table":
            _, tf = _txbox(slide, left, top + Inches(0.18), col_w, Inches(0.22))
            _para(tf, str(s.get("section_title", "")).upper(), 9, MID, bold=True,
                  first=True, space_after=0)
            _table(slide, left, top + Inches(0.48), col_w,
                   s.get("table_headers") or [], s.get("table_rows") or [])
        else:
            lines = s.get("bullets") or []
            if s.get("content_type") == "chart":
                lines = [f"{b.get('label')}: {b.get('value')}"
                         for b in (s.get("chart_bars") or [])]
            elif s.get("content_type") == "image-placeholder":
                lines = [s.get("image_placeholder_text") or "[image]"]
            _panel(slide, left, top + Inches(0.18), col_w, Inches(4.2),
                   s.get("section_title", ""), lines)
    _footnotes(slide, d.get("footnote"))


def _r_topic_checklist(slide, d, page):
    top = _chrome(slide, d.get("title"), d.get("key_message"), page)
    topics = d.get("topics") or []
    if not topics:
        return
    band = Inches(0.16)
    avail = SLIDE_H - top - Inches(1.35)
    row_h = min(Inches(1.1), avail / max(1, len(topics)))
    tag_w = Inches(2.0)
    for i, t in enumerate(topics):
        y = top + Inches(0.2) + row_h * i
        _rect(slide, M_L, y, tag_w, row_h - band, fill=DEEP)
        _, tf = _txbox(slide, M_L + Inches(0.12), y + Inches(0.1),
                       tag_w - Inches(0.24), row_h - band - Inches(0.2))
        _para(tf, str(i + 1), 11, FILL, bold=True, first=True, space_after=1)
        _para(tf, _plain(t.get("topic_name", "")).upper(), 9, WHITE, bold=True,
              space_after=1)
        if t.get("status"):
            # Blush, not ACCENT: ACCENT on the DEEP tag ground measures
            # about 1.6:1 and disappeared entirely in the exported deck.
            _para(tf, _plain(t["status"]).upper(), 7.5, FILL, bold=True,
                  space_after=0)
        bx = M_L + tag_w
        _rect(slide, bx, y, BODY_W - tag_w, row_h - band,
              fill=WHITE, line=HAIRLINE)
        _, tf = _txbox(slide, bx + Inches(0.18), y + Inches(0.12),
                       BODY_W - tag_w - Inches(0.36), row_h - band - Inches(0.24))
        for j, b in enumerate(t.get("bullets") or []):
            _para(tf, _plain(b), 9.5, INK, first=(j == 0), space_after=3,
                  bullet_char="▪")
    _footnotes(slide, d.get("footnote"))


def _r_mastery_heatmap(slide, d, page):
    top = _chrome(slide, d.get("title"), d.get("key_message"), page)
    meta = " - ".join(x for x in [
        _plain(d.get("course_name")), _plain(d.get("assessment_name")),
        _plain(d.get("assessment_date"))] if x)
    if meta:
        _rect(slide, M_L, top + Inches(0.12), BODY_W, Inches(0.28), fill=FILL_ALT)
        _, tf = _txbox(slide, M_L + Inches(0.12), top + Inches(0.17),
                       BODY_W - Inches(0.24), Inches(0.2))
        _para(tf, meta, 9, MID, bold=True, first=True, space_after=0)
    headers = ["ID", "Topic", "Source", "Status", "First covered",
               "Last reviewed", "Next review", "Resource"]
    rows = [[t.get("id", ""), t.get("topic", ""), t.get("source", ""),
             t.get("status", ""), t.get("first_covered", ""),
             t.get("last_reviewed", ""), t.get("next_review", ""),
             t.get("resource", "")] for t in (d.get("topics") or [])]
    if rows:
        _table(slide, M_L, top + Inches(0.5), BODY_W, headers, rows,
               [0.5, 2.4, 0.8, 1.1, 1.2, 1.2, 1.1, 1.0])
    _footnotes(slide, d.get("footnote"))


def _r_process_flow(slide, d, page):
    top = _chrome(slide, d.get("title"), d.get("key_message"), page)
    secs = d.get("sections") or []
    n = max(1, min(len(secs), 2))
    gap = Inches(0.5)
    col_w = (BODY_W - gap * (n - 1)) / n
    if n == 1:
        col_w = min(col_w, Inches(9.2))
    for i, s in enumerate(secs[:n]):
        left = M_L + (col_w + gap) * i
        _, tf = _txbox(slide, left, top + Inches(0.14), col_w, Inches(0.22))
        _para(tf, _plain(s.get("section_title", "")).upper(), 9, MID, bold=True,
              first=True, space_after=0)
        y = top + Inches(0.44)
        _rect(slide, left, y, col_w, Inches(0.34), fill=DEEP)
        _, tf = _txbox(slide, left + Inches(0.14), y + Inches(0.07),
                       col_w - Inches(0.28), Inches(0.22))
        _para(tf, _plain(s.get("start_label", "")), 10, WHITE, bold=True,
              first=True, space_after=0)
        steps = s.get("steps") or []
        y += Inches(0.5)
        step_h = min(Inches(0.62),
                     (SLIDE_H - Inches(1.6) - y) / max(1, len(steps)))
        for j, st in enumerate(steps):
            marker = (chr(65 + j) if s.get("marker_style") == "alpha" else str(j + 1))
            _rect(slide, left, y + step_h * j, Inches(0.26), Inches(0.26),
                  fill=ACCENT if st.get("kind") != "result" else DEEP)
            _, tf = _txbox(slide, left, y + step_h * j + Inches(0.04),
                           Inches(0.26), Inches(0.2))
            p = _para(tf, marker, 8, WHITE, bold=True, first=True, space_after=0)
            p.alignment = PP_ALIGN.CENTER
            _, tf = _txbox(slide, left + Inches(0.4), y + step_h * j,
                           col_w - Inches(0.4), step_h)
            _para(tf, _plain(st.get("name", "")), 10, DEEP, bold=True,
                  first=True, space_after=1)
            if st.get("detail"):
                _para(tf, _plain(st["detail"]), 8.5, INK, space_after=0)
        y += step_h * max(1, len(steps)) + Inches(0.08)
        _rect(slide, left, y, col_w, Inches(0.34), fill=ACCENT)
        _, tf = _txbox(slide, left + Inches(0.14), y + Inches(0.07),
                       col_w - Inches(0.28), Inches(0.22))
        _para(tf, _plain(s.get("end_label", "")), 10, WHITE, bold=True,
              first=True, space_after=0)
    _footnotes(slide, d.get("footnotes"))


def _r_quiz_recap(slide, d, page):
    top = _chrome(slide, d.get("title"), d.get("key_message"), page)
    headers = ["Question"] + [_plain(c) for c in (d.get("columns") or [])]
    rows = [[_plain(r.get("question"))] + [_plain(v) for v in (r.get("values") or [])]
            for r in (d.get("rows") or [])]
    if d.get("summary_label") and d.get("summary_values"):
        rows.append([_plain(d["summary_label"])] +
                    [_plain(v) for v in d["summary_values"]])
    if len(headers) > 1:
        _table(slide, M_L, top + Inches(0.2), BODY_W, headers, rows,
               [2.4] + [1.0] * (len(headers) - 1))
    _footnotes(slide, d.get("footnotes"))


def _r_flashcard_grid(slide, d, page):
    top = _chrome(slide, d.get("title"), d.get("key_message"), page)
    cards = []
    for s in d.get("sections") or []:
        for c in s.get("cards") or []:
            cards.append(c)
    cols, gap = 3, Inches(0.22)
    card_w = (BODY_W - gap * (cols - 1)) / cols
    rows = max(1, (len(cards) + cols - 1) // cols)
    avail = SLIDE_H - top - Inches(1.35)
    card_h = min(Inches(1.55), (avail - gap * (rows - 1)) / rows)
    for i, c in enumerate(cards[:cols * 4]):
        left = M_L + (card_w + gap) * (i % cols)
        y = top + Inches(0.2) + (card_h + gap) * (i // cols)
        _rect(slide, left, y, card_w, card_h, fill=FILL, line=HAIRLINE)
        _rect(slide, left, y, card_w, Inches(0.04), fill=ACCENT)
        _, tf = _txbox(slide, left + Inches(0.14), y + Inches(0.16),
                       card_w - Inches(0.28), card_h - Inches(0.3))
        _para(tf, _plain(c.get("front", "")), 10, DEEP, bold=True, first=True,
              space_after=4)
        _para(tf, _plain(c.get("back", "")), 9, INK, space_after=3)
        meta = " ".join(x for x in [_plain(c.get("tag", "")).upper(),
                                    _plain(c.get("source", ""))] if x)
        if meta:
            _para(tf, meta, 7.5, MUTED, space_after=0)
    _footnotes(slide, d.get("footnotes"))


def _r_contents(slide, d, page):
    top = _chrome(slide, d.get("title"), None, page)
    _, tf = _txbox(slide, M_L, top + Inches(0.25), BODY_W, Inches(4.6))
    for i, ln in enumerate(_plain(d.get("content_html", "")).split("\n")):
        _para(tf, ln, 12, INK, first=(i == 0), space_after=7)
    _footnotes(slide, d.get("footnote"))


def _r_two_section(slide, d, page):
    top = _chrome(slide, d.get("title"), d.get("key_message"), page)
    col_w = (BODY_W - Inches(0.5)) / 2
    for i, (t_key, c_key) in enumerate((("left_title", "left_content"),
                                        ("right_title", "right_content"))):
        left = M_L + (col_w + Inches(0.5)) * i
        body = d.get(c_key)
        if body is None and i == 1 and d.get("right_image"):
            body = (d["right_image"] or {}).get("placeholder") or "[image]"
        _panel(slide, left, top + Inches(0.18), col_w, Inches(4.0),
               d.get(t_key, ""), _plain(body).split("\n"), bullet=None)
    _footnotes(slide, d.get("footnote"))


def _r_freeform(slide, d, page):
    top = _chrome(slide, d.get("title"), d.get("key_message"), page)
    _, tf = _txbox(slide, M_L, top + Inches(0.25), BODY_W, Inches(4.4))
    for i, ln in enumerate(_plain(d.get("content_html", "")).split("\n")):
        _para(tf, ln, 11, INK, first=(i == 0), space_after=5)
    _footnotes(slide, d.get("footnote"))


RENDERERS = {
    "cover": _r_cover,
    "section_divider": _r_section_divider,
    "content_grid": _r_content_grid,
    "comparison_matrix": _r_comparison_matrix,
    "multi_panel": _r_multi_panel,
    "topic_checklist": _r_topic_checklist,
    "mastery_heatmap": _r_mastery_heatmap,
    "process_flow": _r_process_flow,
    "quiz_recap": _r_quiz_recap,
    "flashcard_grid": _r_flashcard_grid,
    "contents": _r_contents,
    "two_section": _r_two_section,
    "freeform": _r_freeform,
}


def build(deck: dict, out_path: str) -> dict:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    blank = prs.slide_layouts[6]

    roles, unsupported, tables = [], [], 0
    for i, slide_spec in enumerate(deck.get("slides") or [], start=1):
        role = slide_spec.get("slide_role")
        data = slide_spec.get("data") or {}
        slide = prs.slides.add_slide(blank)
        fn = RENDERERS.get(role)
        if fn is None:
            # An unknown role is reported, never silently dropped: a missing
            # slide in a study guide is worse than an ugly one.
            unsupported.append({"slide_number": i, "slide_role": role})
            _chrome(slide, data.get("title") or role, data.get("key_message"), i)
            _, tf = _txbox(slide, M_L, Inches(3), BODY_W, Inches(1))
            _para(tf, f"[no .pptx layout for role '{role}' - see preview.html]",
                  12, MUTED, first=True, space_after=0)
        else:
            fn(slide, data, i)
            if role in ("comparison_matrix", "mastery_heatmap", "quiz_recap"):
                tables += 1
        roles.append(role)

    prs.save(out_path)
    return {
        "output_path": out_path,
        "slides": len(roles),
        "tables": tables,
        "roles": roles,
        "unsupported_roles": unsupported,
    }


def main():
    args = [a for a in sys.argv[1:]]
    if len(args) < 2 or "--help" in args or "-h" in args:
        print("Usage: python3 build_pptx.py <deck.json> <out.pptx>", file=sys.stderr)
        return 2
    with open(args[0], "r", encoding="utf-8") as f:
        deck = json.load(f)
    print(json.dumps(build(deck, args[1]), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
