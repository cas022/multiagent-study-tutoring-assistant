---
name: pptx-native-tables
description: "Use whenever a .pptx (including any HTML-to-pptx or 'editable pptx' export) has content that should be a real PowerPoint table, or has template chrome (logo, icon, footer bar, page number) duplicated as movable shapes on every slide instead of living on the Slide Layout/Master. Exporters often draw a 'table' as one rectangle plus one text box per cell instead of a real table, and copy recurring decoration onto each slide, leaving the Layout/Master empty. Use this to build tables and chrome correctly from the start, or to retrofit an export: collapse a shape-grid into one table, and promote repeated per-slide chrome onto the Layout. Trigger on: 'make this an actual table', 'the table is a bunch of shapes', 'this logo/footer shouldn't be movable', 'this should be on the slide master', or cleaning up a template-based deck."
---

# PPTX Native Tables & Layout Chrome

This skill fixes two related anti-patterns that show up in the same kind of
pptx exports, particularly anything generated from HTML or a DOM: tables
built as a grid of individual shapes, and template decoration duplicated on
every slide instead of living on the Slide Layout/Master. Jump to
[Tables](#the-problem) or
[Layout chrome](#anti-pattern-2--template-chrome-duplicated-per-slide).

## The problem

Open a "table" from an HTML-to-pptx export and select it in PowerPoint:
instead of one table object, you get a rubber band around dozens or hundreds
of individual shapes. The exporter has drawn one coloured rectangle per cell
background, one text box per cell's text, and often built the rule under a
total row from a row of skinny rectangles, one per column, rather than a
single line. A thirty-row table across eight columns lands in the low
hundreds of shapes.

It looks like a table. PowerPoint does not think it is one. It cannot be
selected, resized or restyled as a table, cannot be pasted into a
spreadsheet as one, breaks screen readers, and bloats the file. This skill
fixes that in two directions:

1. **Building new** - construct the table as one real `<a:tbl>` graphics
   frame from the start.
2. **Retrofitting** - detect an existing shape-grid "fake table" in a deck
   and rebuild it as one real table, styled to look identical.

In this project the roles that carry real tabular content are
`comparison_matrix`, `mastery_heatmap` and `quiz_recap`. `build_pptx.py`
already builds those natively, so the retrofit path here is for decks that
come from somewhere else.

## Is this actually the anti-pattern? Quick check

If you are about to write, or you find code that writes, a loop over rows
and columns computing `x = left + col*col_width`, `y = top + row*row_height`,
and then for each `(row, col)` draws a background rectangle *and* a text box
at that position: **stop, that is the anti-pattern.** Any time content has a
header row plus repeating data rows and columns, it belongs in one table
shape, not N shapes.

## Workflow A — building a table from scratch

Prefer this whenever you are the one generating the slide.

**With `python-pptx`** - use `scripts/native_table.py`'s `table_from_rows()`
for a simple table, or build a `CellSpec` matrix yourself and call
`build_native_table()` for row-specific shading (a banded header, a shaded
summary row), which is the same function Workflow B uses.

**With `pptxgenjs`** - use `slide.addTable(rows, options)` with a 2D array
of cell objects. This is ONE call producing ONE table object, never a loop
of `addShape` + `addText`:

```js
slide.addTable(rows, {
  x: 0.58, y: 1.85, w: 12.17,
  colW: [0.5, 3.0, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1],
  border: { type: "none" },   // kill pptxgenjs's default grid - see gotchas
  autoPage: false,
});
```

Each cell is `{ text, options: { bold, color, fill: { color }, align,
fontFace, fontSize } }`. See `references/pptxgenjs-table-example.md` for a
full worked example.

## Workflow B — retrofitting an existing shape-grid table

```bash
# 1. Dry run - find the bounding box of the fake table (inches), then:
python scripts/convert_existing_table.py deck.pptx --slide 0 \
    --bbox 0.58,1.85,12.75,6.6

#    This prints the detected row/col count and a text preview of every
#    cell. READ IT before proceeding - check it against what the slide
#    actually shows. A stray shape just outside the real grid can add a
#    phantom row or column; --rows pins the row count if the auto-detected
#    one is off by one.

# 2. Apply once the dry-run dump looks right.
python scripts/convert_existing_table.py deck.pptx --slide 0 \
    --bbox 0.58,1.85,12.75,6.6 --apply -o deck-fixed.pptx
```

Finding the bbox: read shape `.left/.top/.width/.height` (divide EMU by
914400 for inches) for a few cells at the corners of the visible table, or
eyeball it against a render. Give the bbox a little slack on every side but
**stop short of any title, subtitle, footnote or logo** - those stay as
their own shapes, untouched.

`extract_grid()` separates each cell's tall background rectangle (the real
fill) from any thin hairline rectangles at the same position (border accents
some exporters use instead of a real border), and reconstructs row height
from the **pitch between row tops**, not from any one shape's own height.
Using a cell's raw height instead reliably makes the rebuilt table overrun
into whatever sits below it.

## Scripts

| Script | What it does |
|---|---|
| `scripts/native_table.py` | The library: `extract_grid()` detects a shape-grid table, `build_native_table()` rebuilds it as one real table, `table_from_rows()` is a quick path for simple new tables. |
| `scripts/convert_existing_table.py` | CLI for Workflow B - dry-run preview, then `--apply`. |
| `scripts/layout_chrome.py` | The library: `find_chrome_groups()` detects shapes duplicated across every slide (classifying page-number-like ones separately), `promote_chrome_to_layout()` moves them onto the Slide Layout. |
| `scripts/promote_layout_chrome.py` | CLI for Workflow C - dry-run preview, then `--apply`. |

## Styling gotchas (python-pptx)

- **`add_table()` applies a default theme style that overrides your fills.**
  Strip it immediately: set the table style to the "No Style, No Grid" GUID
  (`native_table.NO_STYLE_NO_GRID` = `{2D5ABB26-0587-4C30-8999-92F81FD0307C}`)
  and clear `firstRow`/`bandRow` on `<a:tblPr>` - otherwise every `cell.fill`
  call you make gets partially overridden by the built-in banding.
- **python-pptx has no high-level API for per-cell borders.**
  `set_cell_border()` edits `<a:tcPr><a:lnB>` XML directly; there is no
  `cell.border_bottom = ...`.
- **Default cell margins are loose** (~0.1in top/bottom). A dense table needs
  `cell.margin_top/bottom` at ~0.01 to 0.02in, or every row grows visibly
  taller than the source.
- **`text_frame.text = "..."` collapses formatting to one plain run** - clear
  and re-add `<a:r>` runs individually so per-run bold, colour and size
  survive.
- **Column widths must sum to the table's stated width**, and row heights are
  a floor, not a cap: PowerPoint grows a row if the text does not fit, so
  oversized text still overflows visually even in a real table.

## QA (required)

Render before declaring success:

```bash
python /mnt/skills/public/pptx/scripts/office/validate.py deck-fixed.pptx --original deck.pptx
python /mnt/skills/public/pptx/scripts/office/soffice.py --headless --convert-to pdf deck-fixed.pptx
pdftoppm -jpeg -r 200 deck-fixed.pdf slide
```

Then specifically check:

1. **Shape count dropped** - the region that was N shapes is now 1. Confirm
   with python-pptx: the new shape's `.shape_type` should be `TABLE (19)`, a
   `GraphicFrame`, not another `AUTO_SHAPE`.
2. **Visual diff** - stack the before/after renders and compare. Look
   especially at row spacing: the pitch-vs-shape-height gotcha above is the
   most common way a conversion looks "almost right" but drifts.
3. **Select it in PowerPoint** - one click should select the whole table,
   not one of hundreds of shapes.

For layout-chrome fixes, also check that the promoted shapes still render on
every slide using that layout, that a page-number field shows the right
number per slide rather than a frozen digit, and that python-pptx reports
those shapes only under `slide.slide_layout.shapes`.

---

## Anti-pattern 2: template chrome duplicated per-slide

The same exports usually show a second version of the same underlying
mistake: every slide separately carries its own copy of the decorative icon
beside the title, the footer bar, the accent line, and the page number,
while the shared slide layout sits completely empty. That is the same
relationship as redrawing your slide master by hand on every slide. Nothing
stops one of those shapes being nudged out of place on one slide, and there
is no single place to update the footer for the whole deck.

**If you find yourself copying the same shape onto multiple slides to keep a
decoration consistent, stop - it belongs on the layout.**

### Detecting it

A shape is layout chrome, not slide content, if it is in the **same
position, size and style on every slide that uses that layout**, and either
(a) has identical text, including identically *empty* text, since most
decoration has no text at all, or (b) has text that varies but is purely
numeric (a page number).

A shape in the same position with real text that *differs and is not a
simple number* - each slide's title in the same title-shaped box - is
genuine slide content and must be left alone. `scripts/layout_chrome.py`
classifies exactly this way and reports its reasoning; sanity-check its
dry-run output regardless.

### Workflow C — promoting chrome to the layout

```bash
python scripts/promote_layout_chrome.py deck.pptx                            # dry run
python scripts/promote_layout_chrome.py deck.pptx --apply -o deck-fixed.pptx  # apply
```

If the deck has more than one slide layout, run it once per layout, scoped
with `--slides 0,1,2` to the indices that share it. Chrome that repeats
identically *across different layouts* belongs on the Slide **Master**
instead, one level higher; these scripts target a layout by default because
promoting to the master affects every layout at once and deserves a
deliberate choice, not an automatic one.

### The page-number exception

A literal page-number text box (`"06"`, `"07"`, ...) copied onto each slide
is upgraded to a real `<a:fld type="slidenum">` field on the layout - the
same mechanism PowerPoint's own Insert > Header & Footer > Slide Number
uses. Two things about it are not obvious from the OOXML docs, both verified
by rendering the result:

- **A slide-number placeholder that exists ONLY on the layout does not
  render at all.** It needs a minimal placeholder "echo" on every slide -
  same `type="sldNum"` and `idx`, but with no `<a:xfrm>` and no style
  overrides - purely to tell that slide "show the layout's slide-number
  placeholder here." `layout_chrome.py` adds this automatically; do not skip
  it, and do not give the echo its own position or formatting, or you have
  rebuilt the anti-pattern in miniature.
- **The field genuinely auto-computes per slide.** Reordering slides later
  keeps the numbers correct automatically, which per-slide text boxes never
  could.

## Design tokens

`references/study-table-theme.md` has the colours, fonts and sizes this
project's decks use as a ready preset - useful when building more tables in
the same house style rather than starting the palette from scratch.
