#!/usr/bin/env python3
"""
verify_render.py - the Render stage's measured fit gate.

WHAT THIS REPLACES, AND WHY IT EXISTS
-------------------------------------
Before this script, every fit decision in this plugin was an estimate
made inside a Jinja template. comparison-matrix.html solved for a font size by
guessing wrapped-line counts from character counts and an assumed
average character width; quiz-recap.html divided a fixed 480px
budget by a row count; the rest of the library made no fit decision at
all. Each of those templates said so in its own comments. comparison-matrix's
read, verbatim: "this is an ESTIMATE, not a measured render - there is
no Playwright pass available to verify this against actual rendered
height."

There is one now. This script loads each rendered slide in a real
headless Chromium at the exact 1280x720 canvas the deck exports at, and
measures what actually happened. Nothing about a slide's fit is
self-reported by a model or inferred from a character count.

It was written after a real deck shipped with content rendered straight
through its own footnotes on one slide, and a table pushed into the
footnote band on another. Neither was caught, because nothing in the
pipeline had ever looked at a rendered pixel. The structural half of
that fix lives in the templates (the footnote lane is now reserved in
normal flow rather than positioned as an absolute overlay). This script
is the other half: the templates can no longer produce that specific
collision by construction, and this catches everything else.

WHAT IT CHECKS
--------------
Per slide, at 1280x720:

  clipped         Any element with computed overflow hidden whose own
                  scrollHeight/scrollWidth exceeds its client box. This
                  is the single most reliable signal that content is
                  present in the markup but invisible on the canvas. It
                  catches the content zone, and equally a nested panel,
                  table cell, or the footnote lane itself.
  overlap         Any content element whose bounding box intersects the
                  footer bar or the footnote lane. With the lane now in
                  normal flow this should be structurally impossible;
                  the check stays as a regression guard and because
                  cover.html and section-divider.html lay out
                  differently.
  off_canvas      Any element extending past the 1280x720 canvas.
  under_fill      The content zone using less than UNDER_FILL_RATIO of
                  its available height. Not a defect, and never reported
                  as one: a half-empty cover, divider or summary slide is
                  correct, and empty space is not a fault. It stays
                  in the report as our own diagnostic, because it is the
                  same measurement and costs nothing to record. See
                  build_known_fit_issues and REPAIRABLE_FLAG_CODES for
                  what does and does not reach the brief.

AUTO-FIT
--------
When content is clipped, the script shrinks the slide's content
container and re-measures, stepping down until the slide passes or it
hits FIT_FLOOR. The shrink is applied as a CSS `zoom` on the container
together with an explicit pixel width and height of (available / zoom),
so the container's RENDERED box stays exactly the size it was and only
its contents get smaller. Layout position, chrome, footnote lane and
footer are untouched.

`zoom` rather than `transform: scale()` deliberately: transform is a
paint-time operation that does not change layout, so scaled children
would still overflow their parent's layout box and still be clipped.
`zoom` scales the layout itself, which is the thing that has to change.
It is a Chromium-native property and these slides are measured, previewed
and exported from the same HTML, so this stays inside one engine.

If a slide still clips at FIT_FLOOR, the script does NOT shrink further
and does NOT drop content. It emits a BLOCKING flag naming the slide and
the measured overage. Content is never removed to make something fit;
that rule is not negotiable anywhere in this pipeline, and a fit gate is
exactly the place it would be tempting to break it.

FONT CAVEAT, STATED PLAINLY
---------------------------
Every template @imports Montserrat from Google Fonts. This script blocks
all non-local requests before loading a slide, so measurement never
depends on network access and never varies between an online and an
offline run. That means measurements are taken against the templates'
own fallback stack (Hanken Grotesk, Helvetica Neue, Helvetica, Arial),
not against Montserrat. Those metrics are close but not identical.
SAFETY_MARGIN below exists for that gap: a slide has to fit with a
little room to spare before this script calls it fitted. This is a real
limitation and it is disclosed rather than papered over. It is also the
LAST line of defence: nothing downstream reflows a slide, so a collision
this script misses reaches the student's deck.

Usage:
    python3 verify_render.py <manifest.json> [--report report.json] [--no-fit]

manifest.json shape (a JSON list, or an object with a "slides" key):
    [
      {"slide_number": 8, "html_path": "/abs/path/slide_08.html"},
      ...
    ]

Slides are edited IN PLACE when a fit is applied, so the corrected HTML
is what flows on to build_html_preview.py. Pass --no-fit to measure and
report without touching any file. Each slide is written at most once, at
the end of its own fit search; the search itself runs entirely on the
loaded page (see _apply_and_measure).

STDOUT. With --report, only a compact object goes to stdout: the report
path, the canvas, fit_applied, `summary`, and `known_fit_issues`. The
full per-slide measurement detail is in the file that was just written,
and echoing it as well cost the caller several thousand tokens per build
for a payload nothing reads. Without --report there is nowhere else for
the report to go, so the whole thing is printed as before.

Exit codes:
    0  every slide passed, with or without a fit applied
    1  at least one BLOCKING flag (a slide that cannot fit at the floor,
       or a clipped footnote lane)
    2  usage error, or Playwright/Chromium unavailable
"""
import json
import os
import sys

# Canvas contract. Every template declares .slide at exactly this size
# and the deck exports 16:9 at this ratio. Changing these means changing
# every template, not just this script.
CANVAS_W = 1280
CANVAS_H = 720

# Shrink steps tried in order. 1.0 is the unmodified render: if it
# passes, nothing is injected into the file at all.
FIT_STEPS = [1.0, 0.97, 0.94, 0.91, 0.88, 0.85, 0.82, 0.78, 0.74, 0.70,
             0.66, 0.62, 0.58, 0.55, 0.52, 0.50]
FIT_FLOOR = FIT_STEPS[-1]

# Footnote lane font sizes tried, in px, when the lane itself overflows
# its cap. The lane is chrome and sits outside the content container, so
# the content zoom above does not touch it and cannot. A ten-note
# provenance block on a model slide genuinely does not fit at 10px, and
# the answer is smaller footnote type, which is what the reference deck
# does, not fewer footnotes.
LANE_FONT_STEPS = [10, 9.5, 9, 8.5, 8, 7.5, 7, 6.5, 6]
LANE_FONT_FLOOR = LANE_FONT_STEPS[-1]

# Required headroom, in px, inside every text-bearing box that hides its
# own overflow, before a slide counts as fitted. Covers the
# Montserrat-vs-fallback metric gap described in the module docstring: a
# box measured as exactly full here could be a pixel over once the real
# font loads. 3px is under a third of a line of body text, so the cost
# of being wrong in the safe direction is one 3% shrink step.
#
# Note this is deliberately a slack requirement on the boxes that
# actually clip, not a fraction of the content zone's height. An earlier
# draft used the latter and was wrong in a way worth recording: these
# content zones are flex containers whose children fill them exactly, so
# scrollHeight always equals clientHeight on the container itself no
# matter how badly a nested panel overflows. Measured against that, every
# normal slide looked full to the pixel and would have been shrunk for
# no reason, while the actual overflow four levels down went unseen.
MIN_SLACK_PX = 3

# Effective rendered type size, in px, below which a slide is reported
# even though nothing is clipped. A fit that "succeeds" by shrinking a
# table to 4px is not a success, it is the same content loss as clipping
# with an extra step. The reference deck this library is modelled on
# sets its densest 31-row table at roughly 7px, so that is the warning
# line; 5.5px is where a projected slide stops being readable at all and
# the slide has to be split or thinned at the outline instead.
MIN_LEGIBLE_PX = 7.0
HARD_LEGIBLE_PX = 5.5

# A content zone using less than this fraction of its available height
# gets a NON_BLOCKING under_fill flag. Sparse cover and divider slides
# left roughly a third of the canvas empty and nothing reported it.
UNDER_FILL_RATIO = 0.62

# Tolerance in px for every geometric comparison. Sub-pixel layout
# rounding routinely produces a scrollHeight one greater than
# clientHeight on a box that is visually fine; flagging that would make
# the whole gate noise.
EPS = 1.5

# Content containers, in priority order. The first one present in a
# slide is the box this script fits. Everything not in this list and not
# inside it is treated as chrome.
CONTENT_SELECTORS = [".content-zone", ".grid", ".body-grid", ".panel-grid"]

# Chrome that content must never overlap.
CHROME_SELECTORS = [".footer-bar", ".footnote", ".footnotes"]

# Injected marker, so a re-run can find and replace a previous fit
# rather than stacking a second one on top of it.
FIT_MARKER_OPEN = "<!-- verify_render.py fit BEGIN -->"
FIT_MARKER_CLOSE = "<!-- verify_render.py fit END -->"

# id of the style element the fit search injects into the LOADED page
# while it is hunting for a step that passes. See _apply_fit_in_page.
FIT_STYLE_ID = "__fit"


MEASURE_JS = r"""
(args) => {
  const CANVAS_W = args.canvasW, CANVAS_H = args.canvasH, EPS = args.eps;
  const CONTENT_SELECTORS = args.contentSelectors;
  const CHROME_SELECTORS = args.chromeSelectors;
  const MAX_REPORT = 6;

  const slide = document.querySelector('.slide');
  if (!slide) return {error: 'no .slide element found'};

  let container = null, containerSelector = null;
  for (const sel of CONTENT_SELECTORS) {
    const el = slide.querySelector(sel);
    if (el) { container = el; containerSelector = sel; break; }
  }

  const chrome = [];
  for (const sel of CHROME_SELECTORS) {
    slide.querySelectorAll(sel).forEach(el => chrome.push({sel, el}));
  }
  const chromeSet = new Set(chrome.map(c => c.el));
  const isChrome = (el) => {
    for (const c of chromeSet) { if (c === el || c.contains(el)) return true; }
    return false;
  };

  const hidesOverflow = (el) => {
    const cs = getComputedStyle(el);
    return ['hidden', 'clip', 'auto', 'scroll'].includes(cs.overflowY) ||
           ['hidden', 'clip', 'auto', 'scroll'].includes(cs.overflowX);
  };

  // How far a box's own contents run past its content edge.
  //
  // scrollHeight - clientHeight alone is not enough and getting this
  // wrong is what made the first version of this script useless. A flex
  // container with justify-content: center (topic-checklist.html's
  // .row-body, two-section.html's .panel-body) reports scrollHeight
  // exactly equal to clientHeight whether its children have 40px to
  // spare or overflow by 40px, because the overflow is centred and
  // spills equally in both directions. Measuring the children's own
  // union against the content edge catches that case; scrollHeight
  // still catches ordinary block overflow. Taking the worse of the two
  // covers both without needing to know which layout mode a box is in.
  const contentOverflow = (el) => {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const bt = parseFloat(cs.borderTopWidth) || 0;
    const bb = parseFloat(cs.borderBottomWidth) || 0;
    const top = r.top + bt, bottom = r.bottom - bb;
    let maxB = -Infinity, minT = Infinity;
    for (const c of el.children) {
      const cr = c.getBoundingClientRect();
      if (cr.height === 0 && cr.width === 0) continue;
      if (cr.bottom > maxB) maxB = cr.bottom;
      if (cr.top < minT) minT = cr.top;
    }
    // scrollHeight - clientHeight is never negative, so it can report
    // overflow but can never report SLACK. Using it as the baseline
    // pinned every measurement at "exactly full" and made the slack
    // test fail on slides with a third of the zone free. The children's
    // union is the measure that can go either way; scrollHeight is kept
    // only as an additional overflow signal, for a box holding raw text
    // with no element children of its own.
    //
    // Units matter here. getBoundingClientRect returns RENDERED pixels,
    // which the CSS zoom this script injects does scale. scrollHeight
    // and clientHeight return LAYOUT pixels, which zoom does not scale.
    // Comparing one against the other on a zoomed element compares a
    // 396px box to a 792px number and concludes it is exactly full. The
    // rect-derived measurements above are already consistently rendered
    // px; scrollHeight is converted before being used with them.
    const z = el.offsetHeight ? (r.height / el.offsetHeight) : 1;
    const sh = (el.scrollHeight - el.clientHeight) * z;
    //
    // Only the BOTTOM measure may set the baseline. A child that starts
    // exactly at the content edge makes (top - minT) zero, and folding
    // that into a max() floors the whole result at zero, which again
    // reports every box as exactly full and never as having room. The
    // top and scrollHeight measures are overflow signals only: they can
    // raise the result, never hold it up.
    let over = (maxB !== -Infinity) ? (maxB - bottom) : sh;
    const topOver = (minT !== Infinity) ? (top - minT) : 0;
    if (topOver > EPS) over = Math.max(over, topOver);
    if (sh > EPS) over = Math.max(over, sh);
    return over;
  };

  // An element already clipped by an ancestor is not separately
  // interesting: the ancestor's own overflow is the finding, and
  // reporting every descendant as well turns one defect into eighty
  // lines of noise. The first run of this script produced exactly that.
  const clippedByAncestor = (el) => {
    const r = el.getBoundingClientRect();
    let p = el.parentElement;
    while (p && p !== document.body) {
      if (hidesOverflow(p)) {
        const pr = p.getBoundingClientRect();
        if (r.bottom > pr.bottom + EPS || r.top < pr.top - EPS ||
            r.right > pr.right + EPS || r.left < pr.left - EPS) return true;
      }
      p = p.parentElement;
    }
    return false;
  };

  // ---- clipped and slack ------------------------------------------
  const clipped = [];
  let minSlackContent = null, minSlackBox = null;
  slide.querySelectorAll('*').forEach(el => {
    if (!hidesOverflow(el)) return;
    if (el.clientHeight === 0) return;
    const over = contentOverflow(el);
    const chromeBox = isChrome(el);
    if (over > EPS) {
      clipped.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className && el.className.toString ? el.className.toString() : ''),
        overflow_y_px: Math.round(over * 10) / 10,
        client_h: el.clientHeight,
        is_chrome: chromeBox
      });
    }
    if (!chromeBox && el.textContent.trim()) {
      const slack = -over;
      if (minSlackContent === null || slack < minSlackContent) {
        minSlackContent = slack;
        minSlackBox = {
          tag: el.tagName.toLowerCase(),
          cls: (el.className && el.className.toString ? el.className.toString() : ''),
          slack_px: Math.round(slack * 10) / 10,
          client_h: el.clientHeight
        };
      }
    }
  });

  // ---- overlap ----------------------------------------------------
  const rectOf = (el) => {
    const r = el.getBoundingClientRect();
    const s = slide.getBoundingClientRect();
    return {top: r.top - s.top, left: r.left - s.left,
            bottom: r.bottom - s.top, right: r.right - s.left,
            w: r.width, h: r.height};
  };
  const intersects = (a, b) =>
    (a.left < b.right - EPS) && (a.right > b.left + EPS) &&
    (a.top < b.bottom - EPS) && (a.bottom > b.top + EPS);

  const chromeRects = chrome.map(c => ({sel: c.sel, rect: rectOf(c.el)}));
  const overlap = [];
  let overlapCount = 0;
  slide.querySelectorAll('*').forEach(el => {
    if (isChrome(el)) return;
    if (el.children.length > 0) return;
    if (!el.textContent.trim() && el.tagName.toLowerCase() !== 'img') return;
    if (clippedByAncestor(el)) return;
    const r = rectOf(el);
    if (r.w === 0 || r.h === 0) return;
    for (const c of chromeRects) {
      if (intersects(r, c.rect)) {
        overlapCount++;
        if (overlap.length < MAX_REPORT) {
          overlap.push({
            tag: el.tagName.toLowerCase(),
            cls: (el.className && el.className.toString ? el.className.toString() : ''),
            text: el.textContent.trim().slice(0, 70),
            overlaps: c.sel
          });
        }
        break;
      }
    }
  });

  // ---- off canvas -------------------------------------------------
  // Guard only. .slide declares overflow: hidden in every template, so
  // anything past the canvas is normally caught as clipped by that
  // ancestor and excluded here. A hit means a template stopped clipping
  // its own canvas, which is worth knowing and should be rare.
  const offCanvas = [];
  let offCanvasCount = 0;
  slide.querySelectorAll('*').forEach(el => {
    if (el.children.length > 0) return;
    if (clippedByAncestor(el)) return;
    const r = rectOf(el);
    if (r.w === 0 || r.h === 0) return;
    if (r.right > CANVAS_W + EPS || r.bottom > CANVAS_H + EPS ||
        r.left < -EPS || r.top < -EPS) {
      offCanvasCount++;
      if (offCanvas.length < MAX_REPORT) {
        offCanvas.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className && el.className.toString ? el.className.toString() : ''),
          text: el.textContent.trim().slice(0, 70),
          rect: {top: Math.round(r.top), left: Math.round(r.left),
                 bottom: Math.round(r.bottom), right: Math.round(r.right)}
        });
      }
    }
  });

  // ---- effective type size ----------------------------------------
  // getComputedStyle().fontSize is the AUTHORED size and ignores any
  // zoom applied by an ancestor, so a table set at 6px inside a
  // container zoomed to 0.7 still reports 6px while rendering at 4.2px.
  // The element's own rect-to-offset ratio recovers the scale actually
  // in effect, which is the number a reader sees.
  let minType = null, minTypeBox = null;
  if (container) {
    container.querySelectorAll('*').forEach(el => {
      let hasOwnText = false;
      for (const n of el.childNodes) {
        if (n.nodeType === 3 && n.textContent.trim()) { hasOwnText = true; break; }
      }
      if (!hasOwnText) return;
      const r = el.getBoundingClientRect();
      if (r.height === 0) return;
      const scale = el.offsetHeight ? (r.height / el.offsetHeight) : 1;
      const eff = parseFloat(getComputedStyle(el).fontSize) * scale;
      if (!isFinite(eff) || eff <= 0) return;
      if (minType === null || eff < minType) {
        minType = eff;
        minTypeBox = {
          tag: el.tagName.toLowerCase(),
          cls: (el.className && el.className.toString ? el.className.toString() : ''),
          text: el.textContent.trim().slice(0, 40)
        };
      }
    });
  }

  // ---- fill -------------------------------------------------------
  // used_h is the children's union height, not scrollHeight, for the
  // same reason contentOverflow does not trust scrollHeight alone.
  let fill = null;
  if (container) {
    const cr = container.getBoundingClientRect();
    const ccs = getComputedStyle(container);
    const cz = container.offsetHeight ? (cr.height / container.offsetHeight) : 1;
    const cbt = (parseFloat(ccs.borderTopWidth) || 0) * cz;
    const cbb = (parseFloat(ccs.borderBottomWidth) || 0) * cz;
    // Rendered px throughout, so this stays comparable under zoom.
    const avail = Math.round(cr.height - cbt - cbb);
    let maxB = -Infinity;
    for (const c of container.children) {
      const b = c.getBoundingClientRect();
      if (b.height === 0 && b.width === 0) continue;
      if (b.bottom > maxB) maxB = b.bottom;
    }
    const used = maxB === -Infinity ? Math.round(container.scrollHeight * cz)
                                    : Math.round(maxB - (cr.top + cbt));
    fill = {
      selector: containerSelector,
      available_h: avail,
      used_h: used,
      client_w: Math.round(cr.width),
      ratio: avail > 0 ? Math.round((used / avail) * 1000) / 1000 : null
    };
  }

  // ---- footnote lane ----------------------------------------------
  let lane = null;
  for (const c of chrome) {
    if (c.sel === '.footnote' || c.sel === '.footnotes') {
      const over = contentOverflow(c.el);
      lane = {
        selector: c.sel,
        height: c.el.getBoundingClientRect().height,
        overflow_px: Math.round(over * 10) / 10
      };
      break;
    }
  }

  return {
    error: null,
    container_selector: containerSelector,
    clipped, overlap, overlap_count: overlapCount,
    off_canvas: offCanvas, off_canvas_count: offCanvasCount,
    fill, lane,
    min_type_px: minType === null ? null : Math.round(minType * 100) / 100,
    min_type_box: minTypeBox,
    min_slack_content: minSlackContent,
    min_slack_box: minSlackBox,
    slide_rect: rectOf(slide)
  };
}
"""


def _fit_style(selector: str, zoom: float, width_px: float, height_px: float) -> str:
    """The content-container fit rule. Raw CSS only.

    Explicit width and height of (available / zoom) with `zoom: k` means
    the container's RENDERED box comes back out at exactly the size it
    had before, while everything inside it lays out in a box that is 1/k
    larger. flex: 0 0 auto pins that height so the flex parent stops
    stretching the container and overriding it.

    This returned a complete `<style>` element in its first version, and
    the caller wrapped it in a second one. Nested style elements are
    invalid, the browser dropped the whole thing, and every slide then
    measured as though no fit had been applied at all: the fit loop ran
    to its floor on slides needing no fit whatsoever and reported the
    result as legitimate. Returning bare declarations, with exactly one
    caller responsible for wrapping them, is why this is split this way.
    """
    return (
        "/* Applied by verify_render.py: this slide's content did not fit its\n"
        "   container at full size. The container's rendered box is unchanged;\n"
        f"   only its contents are scaled, to {zoom:g}. Chrome, footnote lane\n"
        "   and footer are untouched. Delete this block for the raw render. */\n"
        f"{selector} {{\n"
        f"  zoom: {zoom:g};\n"
        f"  width: {width_px:.2f}px;\n"
        f"  height: {height_px:.2f}px;\n"
        f"  flex: 0 0 auto;\n"
        f"}}\n"
    )


def _lane_style(font_px: float) -> str:
    """Footnote lane type override. Raw CSS only.

    font-size rather than zoom here: the lane's height is driven purely
    by how many lines its text wraps to, so reducing the type reduces
    the height directly and predictably. zoom would work too but would
    also scale the lane's own max-height in layout px, which makes the
    cap mean something different at every step.
    """
    return (
        "/* Applied by verify_render.py: the footnote block did not fit the\n"
        f"   lane at the template's 10px. Set to {font_px:g}px so every note\n"
        "   stays visible. No note was shortened or dropped. */\n"
        f".footnote, .footnotes {{ font-size: {font_px:g}px; }}\n"
    )


def _strip_previous_fit(html: str) -> str:
    start = html.find(FIT_MARKER_OPEN)
    if start == -1:
        return html
    end = html.find(FIT_MARKER_CLOSE, start)
    if end == -1:
        return html
    return html[:start] + html[end + len(FIT_MARKER_CLOSE):]


def _inject(html: str, block: str) -> str:
    html = _strip_previous_fit(html)
    lower = html.lower()
    idx = lower.rfind("</head>")
    if idx != -1:
        return html[:idx] + block + "\n" + html[idx:]
    idx = lower.rfind("</body>")
    if idx != -1:
        return html[:idx] + block + "\n" + html[idx:]
    return html + "\n" + block


# Replaces (or creates) the in-page fit stylesheet on the ALREADY-LOADED
# document, then forces a synchronous layout so the measurement that
# follows reads the new geometry rather than the pre-injection one.
#
# Appended to document.head, which puts it last in the cascade - the same
# position the written-to-disk block occupies, since _inject() splices it
# in immediately before </head>. Passing an empty string leaves an empty
# style element behind, which is inert and equivalent to no fit at all.
_APPLY_FIT_JS = r"""
(args) => {
  let el = document.getElementById(args.id);
  if (!el) {
    el = document.createElement('style');
    el.id = args.id;
    document.head.appendChild(el);
  }
  el.textContent = args.css;
  void document.documentElement.offsetHeight;
  return true;
}
"""


def _measure(page):
    """Measure the document the page currently holds.

    The single animation-frame await replaces a flat 150ms sleep that was
    roughly 85% of every page load's wall clock. Nothing async is pending
    to wait for: main() aborts every non-file/data/blob request before a
    slide is loaded, so there is no font, image or stylesheet fetch in
    flight, and one frame is enough to guarantee style and layout have
    been recomputed. Measured at 184ms -> 44ms per load with byte-identical
    output.
    """
    page.evaluate("() => new Promise(requestAnimationFrame)")
    return page.evaluate(
        MEASURE_JS,
        {
            "canvasW": CANVAS_W,
            "canvasH": CANVAS_H,
            "eps": EPS,
            "contentSelectors": CONTENT_SELECTORS,
            "chromeSelectors": CHROME_SELECTORS,
        },
    )


def _load_and_measure(page, path: str):
    page.goto("file://" + os.path.abspath(path), wait_until="domcontentloaded", timeout=60000)
    return _measure(page)


def _apply_and_measure(page, css: str):
    """Apply a candidate fit to the loaded page and re-measure it.

    This is the other half of the speedup. The fit search used to write a
    candidate's CSS into the slide file and re-goto it once per step, so a
    slide that walked to the floor paid 16 file writes and 16 full page
    loads. The candidate is CSS and nothing else, so it can be swapped on
    the live document instead; the file is written exactly once, at the
    end, with whichever step won. Measured 20.5s -> 2.35s on a 12-slide
    fixture, with an identical report.
    """
    page.evaluate(_APPLY_FIT_JS, {"id": FIT_STYLE_ID, "css": css})
    return _measure(page)


def _search_steps(page, steps, css_for, predicate):
    """Find the first index in steps[1:] whose candidate satisfies predicate.

    Returns (index, measurement_at_that_index), with the page left in that
    index's state so the caller can write the matching CSS to disk.

    BISECTION, AND WHY THE RE-CHECK BELOW IS NOT OPTIONAL. Both ladders
    (FIT_STEPS, LANE_FONT_STEPS) are ordered from "no change" to "most
    aggressive", and this searches for the first entry that satisfies the
    predicate rather than scanning every entry in turn: 16 steps becomes
    about 5 measurements instead of 16.

    That is only sound if the predicate is MONOTONE along the ladder - if
    a step passes, every more aggressive step passes too. It holds for
    what is actually being tested here: the clipped / overlap / off-canvas
    criteria in _passes() all improve as content shrinks, and a footnote
    lane's overflow falls as its type does. It is an assumption about
    layout, though, not a proof, so the chosen step is applied and
    re-measured before anything is written, and a re-check that does not
    reproduce the pass falls back to the linear scan this replaced. A
    non-monotone ladder therefore costs time, never a wrong answer
    written to a file.

    Residual, and stated rather than hidden: the re-check confirms the
    chosen step passes, not that no EARLIER step would also have passed.
    Under a non-monotone predicate bisection could settle on a smaller
    step than the linear scan would have found, which shrinks a slide
    slightly more than strictly necessary. It cannot produce a slide that
    fails while being reported as fitted, which is the failure that would
    matter.
    """
    lo, hi = 1, len(steps) - 1
    found = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if predicate(_apply_and_measure(page, css_for(mid))):
            found = mid
            hi = mid - 1
        else:
            lo = mid + 1

    if found is None:
        # Nothing in the ladder satisfied the predicate. The linear scan
        # ended on the floor in exactly this case, holding the floor's own
        # measurement, so end there too.
        floor = len(steps) - 1
        return floor, _apply_and_measure(page, css_for(floor))

    # Mandatory re-check. This also restores the page to the chosen step,
    # since the last probe above may well have been a different one.
    m = _apply_and_measure(page, css_for(found))
    if predicate(m):
        return found, m

    # Monotonicity did not hold. Fall back to the scan this replaced,
    # which makes no assumption at all about the ladder's shape.
    for i in range(1, len(steps)):
        m = _apply_and_measure(page, css_for(i))
        if predicate(m):
            return i, m
    return len(steps) - 1, m


def _passes(m) -> bool:
    """A slide passes when nothing overflows its box, nothing overlaps
    chrome, and nothing is laid out past the canvas.

    Slack is deliberately NOT a pass criterion, though it is measured
    and reported. An earlier version required every text-bearing box to
    keep MIN_SLACK_PX of headroom, as insurance against the
    Montserrat-versus-fallback metric gap. That is unwinnable by
    construction: topic-checklist.html's .rows and multi-panel.html's
    .panel-grid are declared height: 100% of their container, so their
    slack is exactly zero at every zoom level no matter how much room
    the content has. Requiring positive slack there sent the fit loop
    to its floor on slides that were never overfull, shrinking a
    perfectly good slide to half size and then reporting it as
    under-filled, which it now was.

    The margin is not abandoned, it is downgraded: a box with less than
    MIN_SLACK_PX of headroom raises a NON_BLOCKING `tight` flag, which
    reaches the fit report's known-fit-issues list and tells Claude
    Design where to look. Reporting a risk beats shrinking a slide over
    one.

    under_fill is not a pass criterion either. It is worth reporting and
    is never worth growing a slide over, and a loop trying to satisfy it
    would fight the one satisfying everything else."""
    if m.get("error"):
        return False
    if m["clipped"] or m["overlap"] or m["off_canvas"]:
        return False
    return True


def verify_slide(page, entry: dict, allow_fit: bool) -> dict:
    path = entry["html_path"]
    number = entry.get("slide_number")
    original = open(path, "r", encoding="utf-8").read()
    working = _strip_previous_fit(original)
    if working != original:
        open(path, "w", encoding="utf-8").write(working)

    result = {
        "slide_number": number,
        "html_path": path,
        "role": entry.get("slide_role"),
        "fit_scale": 1.0,
        "lane_font_px": None,
        "flags": [],
    }

    measured = _load_and_measure(page, path)
    if measured.get("error"):
        result["status"] = "error"
        result["flags"].append(
            {"level": "BLOCKING", "code": "measure_failed", "detail": measured["error"]}
        )
        return result

    baseline = measured
    zoom_applied = 1.0
    lane_font = None

    def _fit_css(zoom, font):
        """The CSS a given (zoom, lane font) pair means, as raw text.

        One source of truth for what a candidate IS, so the CSS tried on
        the live page during the search and the CSS finally written to the
        file can never disagree. Rebuilding both from the same function
        also keeps the two fits independent: stepping the lane font does
        not have to know what the content zoom did, and neither can end up
        applied twice.
        """
        blocks = []
        if font is not None:
            blocks.append(_lane_style(font))
        if zoom < 1.0 and measured_container is not None:
            blocks.append(
                _fit_style(measured_container, zoom, avail_w / zoom, avail_h / zoom)
            )
        return "\n".join(blocks)

    def _write(zoom, font):
        """Write the file once, from the untouched original plus whichever
        overrides won. Called a single time per slide, after the search has
        finished - the search itself never touches the file."""
        css = _fit_css(zoom, font)
        if not css:
            open(path, "w", encoding="utf-8").write(working)
            return
        block = FIT_MARKER_OPEN + "\n<style>\n" + css + "\n</style>\n" + FIT_MARKER_CLOSE
        open(path, "w", encoding="utf-8").write(_inject(working, block))

    measured_container = measured.get("container_selector")
    fill = measured.get("fill") or {}
    avail_h = fill.get("available_h") or 0
    avail_w = fill.get("client_w") or 0

    if allow_fit:
        # Lane first. Its height is part of what the content zone has
        # left, so fitting the content against an overflowing lane would
        # solve against a budget that is about to change.
        lane = measured.get("lane")
        if lane and lane["overflow_px"] > EPS:
            def _lane_fits(m):
                ln = m.get("lane")
                return (not ln) or ln["overflow_px"] <= EPS

            idx, measured = _search_steps(
                page,
                LANE_FONT_STEPS,
                lambda i: _fit_css(zoom_applied, LANE_FONT_STEPS[i]),
                _lane_fits,
            )
            lane_font = LANE_FONT_STEPS[idx]
            # Re-read the content budget: a shorter lane gives the
            # content zone height back.
            fill = measured.get("fill") or {}
            avail_h = fill.get("available_h") or avail_h
            avail_w = fill.get("client_w") or avail_w

        if not _passes(measured) and measured_container:
            idx, measured = _search_steps(
                page,
                FIT_STEPS,
                lambda i: _fit_css(FIT_STEPS[i], lane_font),
                _passes,
            )
            zoom_applied = FIT_STEPS[idx]

        # The one write. Covers the no-fit-needed case too, where
        # _fit_css returns nothing and the stripped original goes back.
        _write(zoom_applied, lane_font)

    result["fit_scale"] = zoom_applied
    result["lane_font_px"] = lane_font

    if measured.get("error"):
        result["status"] = "error"
        result["flags"].append(
            {"level": "BLOCKING", "code": "measure_failed", "detail": measured["error"]}
        )
        return result

    chrome_clip = [c for c in measured["clipped"] if c["is_chrome"]]
    content_clip = [c for c in measured["clipped"] if not c["is_chrome"]]

    for c in chrome_clip:
        result["flags"].append(
            {
                "level": "BLOCKING",
                "code": "footnote_lane_clipped",
                "detail": (
                    f"The footnote lane (.{c['cls'] or c['tag']}) is {c['overflow_y_px']}px taller "
                    f"than the {c['client_h']}px it is allowed, even at the "
                    f"{LANE_FONT_FLOOR}px type floor. Footnote text is present in the markup but "
                    f"not visible on the canvas. Shorten the notes or move one into the body; "
                    f"nothing here may be dropped to make it fit."
                ),
            }
        )

    if content_clip:
        worst = max(content_clip, key=lambda c: c["overflow_y_px"])
        at_floor = zoom_applied <= FIT_FLOOR + 1e-9
        # Always BLOCKING. Residual clipping means content that exists in
        # the markup is not on the canvas, and that is the same defect
        # whether the fit loop reached its floor or was never allowed to
        # run. An earlier version graded this NON_BLOCKING unless the
        # floor was hit, which let a slide with 653px of hidden content
        # report a clean status.
        result["flags"].append(
            {
                "level": "BLOCKING",
                "code": "content_clipped",
                "detail": (
                    f"Content is clipped by {worst['overflow_y_px']}px in "
                    f".{worst['cls'] or worst['tag']}"
                    + (f", the {FIT_FLOOR:g} fit floor. This slide carries more than the layout "
                       f"can hold at any legible size; the content has to be split across two "
                       f"slides or reduced at the outline, not shrunk further."
                       if at_floor else
                       f" at fit scale {zoom_applied:g}.")
                    + " Content present in the markup is not visible on the canvas."
                ),
            }
        )

    if measured["overlap"]:
        n = measured.get("overlap_count", len(measured["overlap"]))
        examples = "; ".join(
            f'<{o["tag"]} class="{o["cls"]}"> "{o["text"]}"' for o in measured["overlap"]
        )
        result["flags"].append(
            {
                "level": "BLOCKING",
                "code": "chrome_overlap",
                "detail": (
                    f"{n} content element(s) overlap "
                    f"{measured['overlap'][0]['overlaps']}. First {len(measured['overlap'])}: "
                    f"{examples}"
                ),
            }
        )

    if measured["off_canvas"]:
        n = measured.get("off_canvas_count", len(measured["off_canvas"]))
        examples = "; ".join(
            f'<{o["tag"]} class="{o["cls"]}"> "{o["text"]}" at {o["rect"]}'
            for o in measured["off_canvas"]
        )
        result["flags"].append(
            {
                "level": "BLOCKING",
                "code": "off_canvas",
                "detail": (
                    f"{n} element(s) are laid out past the {CANVAS_W}x{CANVAS_H} canvas without "
                    f"being clipped by an ancestor. First {len(measured['off_canvas'])}: {examples}"
                ),
            }
        )

    eff_type = measured.get("min_type_px")
    if eff_type is not None and eff_type < MIN_LEGIBLE_PX:
        box = measured.get("min_type_box") or {}
        hard = eff_type < HARD_LEGIBLE_PX
        result["flags"].append(
            {
                "level": "BLOCKING" if hard else "NON_BLOCKING",
                "code": "type_below_legible",
                "detail": (
                    f"The smallest type on this slide renders at {eff_type}px "
                    f"(.{box.get('cls') or box.get('tag')}, \"{box.get('text', '')}\"). "
                    + (f"Below {HARD_LEGIBLE_PX}px this is not readable on a projected slide. "
                       f"Nothing is clipped, but the slide only fits because it was shrunk past "
                       f"the point of being legible. This is a content decision, not a layout "
                       f"one: the slide needs to be split or thinned at the outline."
                       if hard else
                       f"The deck's densest tables sit around {MIN_LEGIBLE_PX}px. Nothing is "
                       f"clipped, but this slide is at the edge of what a room can read.")
                ),
            }
        )

    slack = measured.get("min_slack_content")
    # abs(slack) > 0.25 excludes the fill-by-design case. A container
    # declared height: 100% of its parent (topic-checklist.html's .rows,
    # multi-panel.html's .panel-grid, process-flow.html's columns) reports a
    # slack of exactly zero at every zoom level whatever its contents
    # do, so without this exclusion the tight flag fires on every slide
    # those three templates ever render and stops meaning anything. A
    # genuinely tight box lands on a fractional value, not on 0.000.
    if (slack is not None and slack < MIN_SLACK_PX
            and abs(slack) > 0.25 and not content_clip):
        box = measured.get("min_slack_box") or {}
        result["flags"].append(
            {
                "level": "NON_BLOCKING",
                "code": "tight",
                "detail": (
                    f"Tightest box .{box.get('cls') or box.get('tag')} has "
                    f"{round(slack, 1)}px of headroom left. Nothing is clipped as measured, but "
                    f"this slide is measured against the fallback font stack, not Montserrat, so "
                    f"a box this close to full could tip over once the real font loads. Worth a "
                    f"look when you re-lay this slide out."
                ),
            }
        )

    fill = measured.get("fill")
    if fill and fill["available_h"] and fill["ratio"] is not None:
        if fill["ratio"] < UNDER_FILL_RATIO:
            result["flags"].append(
                {
                    "level": "NON_BLOCKING",
                    "code": "under_fill",
                    "detail": (
                        f"The content zone uses {int(fill['ratio'] * 100)}% of its available "
                        f"height ({fill['used_h']}px of {fill['available_h']}px). The slide will "
                        f"read as under-filled at presentation size."
                    ),
                }
            )

    blocking = [f for f in result["flags"] if f["level"] == "BLOCKING"]
    if blocking:
        result["status"] = "blocking"
    elif zoom_applied < 1.0 or lane_font is not None:
        result["status"] = "fitted"
    else:
        result["status"] = "ok"

    result["measured"] = {
        "container": measured.get("container_selector"),
        "available_h": fill["available_h"] if fill else None,
        "used_h": fill["used_h"] if fill else None,
        "baseline_used_h": baseline["fill"]["used_h"] if baseline.get("fill") else None,
        "min_slack_px": measured.get("min_slack_content"),
        "tightest_box": measured.get("min_slack_box"),
        "lane": measured.get("lane"),
        "min_type_px": measured.get("min_type_px"),
    }
    return result


# The only findings allowed to cross into the fit report's known-fit-
# issues list, keyed by this gate's own flag codes. fit report section 4
# gives the build a CLOSED list of three repairs it may make to an
# inserted slide, and forbids everything else:
#
#   1. text overlapping other text or the reserved bands  chrome_overlap
#   2. text cut off, hidden, or past the canvas edge      content_clipped
#                                                         footnote_lane_clipped
#                                                         off_canvas
#   3. type too small to read on a projected slide        type_below_legible
#
# A code absent from this set is still measured, still flagged, and still
# written to fit_report.json. It just never reaches the brief. See
# build_known_fit_issues for why that separation matters.
REPAIRABLE_FLAG_CODES = frozenset(
    {
        "chrome_overlap",
        "content_clipped",
        "footnote_lane_clipped",
        "off_canvas",
        "type_below_legible",
    }
)


def build_known_fit_issues(results: list) -> list:
    """The fit report's 'Known fit issues on inserted slides' block.

    This is the whole point of running the gate before the brief is
    written. The fit report requires the build to check every
    inserted slide against the three repairs it is permitted to make, and
    forbids it from doing anything else to one - redesign included.
    Handing it the measured list of where our own render hit one of those
    three turns that required pass from a hunt into a work list. Slides
    that passed cleanly are not listed: a list that includes everything
    tells the reader nothing.

    ONLY findings that map to one of those three repairs cross into this
    list, per REPAIRABLE_FLAG_CODES, and a slide with none of them is
    dropped from it entirely. The brief prints this list under an
    instruction to repair exactly what it names, so anything else landing
    here reads as a defect the build is being asked to fix.
    `under_fill` is why this filter exists: a half-filled canvas is
    CORRECT on a cover, a section divider or a summary slide, section 4
    names empty space explicitly as not a defect, and a real deck came
    back with its correct cover replaced by a different one. `tight`
    (headroom left against the fallback font stack) is held back for the
    same reason - nothing is clipped, so there is nothing on the closed
    list to repair.

    A slide whose measurement failed outright is kept, but as an
    unmeasured-scope note rather than as a defect: nothing was looked at
    there, and silently omitting it would read as a clean slide.

    Every flag stays in fit_report.json regardless. That file is this
    pipeline's own diagnostic record, read by ORCH and by us; this filter
    governs what crosses into the brief, not what gets measured.
    """
    issues = []
    for r in results:
        if r["status"] == "ok":
            continue
        defects = [f for f in r["flags"] if f["code"] in REPAIRABLE_FLAG_CODES]
        unmeasured = [f for f in r["flags"] if f["code"] == "measure_failed"]
        if not defects and not unmeasured:
            # Fitted, or flagged for something off the closed list. There
            # is no permitted repair to ask for, so this slide does not
            # belong on a work list headed "repair exactly these".
            continue
        # Defects lead: build_section_4 prints notes[0] on the slide's own
        # line and indents the rest, so context must not take that slot.
        notes = [f"[{f['level']}] {f['detail']}" for f in defects]
        for f in unmeasured:
            detail = f["detail"].rstrip()
            if not detail.endswith((".", "!", "?")):
                detail += "."
            notes.append(
                f"[{f['level']}] This slide could not be measured, so nothing on it has been "
                f"verified: {detail} Check it against the three defects yourself and change "
                f"nothing else."
            )
        if r["fit_scale"] < 1.0:
            notes.append(
                f"Context, not a defect: content was scaled to {r['fit_scale']:g} to fit the "
                f"container, so type on this slide is smaller than the deck's normal scale. That "
                f"is the finished render. Repair only what is listed above, and do not re-set the "
                f"slide at full scale or re-lay it out."
            )
        if r.get("lane_font_px"):
            notes.append(
                f"Context, not a defect: footnote type was reduced to {r['lane_font_px']:g}px so "
                f"the whole footnote block stays visible. Every note is present; none was "
                f"shortened."
            )
        issues.append(
            {
                "slide_number": r["slide_number"],
                "status": r["status"],
                "fit_scale": r["fit_scale"],
                "notes": notes,
            }
        )
    return issues


class PlaywrightUnavailable(RuntimeError):
    """Raised when nothing could be measured at all.

    Kept distinct from an ordinary failure because it maps to this gate's
    exit code 2, and because the one thing this script must never do is
    let a caller treat an unmeasured deck as a passed one. Any caller
    catching this has to report "not measured", not "fitted".
    """


def run_gate(entries: list, allow_fit: bool = True) -> dict:
    """Measure every entry in ONE browser session and return the report.

    Split out of main() so build_deck.py can run the same gate, over the
    slides it has just rendered, without shelling out to this script or
    re-implementing the browser setup. main() is now a thin CLI wrapper
    around this, so there is exactly one implementation of the gate and
    the two entry points cannot drift apart.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise PlaywrightUnavailable(
            "Playwright is not installed, so no slide can be measured. This gate does not "
            "fall back to an estimate: an unmeasured deck is exactly the situation that "
            "shipped content rendered through its own footnotes. Install it with "
            "`pip install playwright --break-system-packages` and re-run."
        )

    results = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(
                viewport={"width": CANVAS_W, "height": CANVAS_H},
                device_scale_factor=1,
            )
            # Block every non-local request so measurement is identical
            # online and offline. See the font caveat in the module
            # docstring: this means measuring against the fallback stack,
            # which SAFETY_MARGIN accounts for.
            context.route(
                "**/*",
                lambda route: route.continue_()
                if route.request.url.startswith(("file:", "data:", "blob:"))
                else route.abort(),
            )
            page = context.new_page()
            for entry in entries:
                results.append(verify_slide(page, entry, allow_fit))
            browser.close()
    except Exception as e:
        raise PlaywrightUnavailable(
            f"Chromium could not be launched, so no slide was measured: {e}\n"
            f"If this is a missing browser binary, run `python3 -m playwright install chromium`. "
            f"This gate never reports a pass it did not measure."
        )

    return {
        "canvas": {"width": CANVAS_W, "height": CANVAS_H},
        "fit_applied": allow_fit,
        "font_measured": "fallback stack (network blocked) - see verify_render.py docstring",
        "slides": results,
        "summary": {
            "ok": [r["slide_number"] for r in results if r["status"] == "ok"],
            "fitted": [r["slide_number"] for r in results if r["status"] == "fitted"],
            "blocking": [r["slide_number"] for r in results if r["status"] in ("blocking", "error")],
        },
        "known_fit_issues": build_known_fit_issues(results),
    }


def main():
    args = [a for a in sys.argv[1:]]
    allow_fit = True
    report_path = None

    if "--help" in args or "-h" in args:
        # Used to fall through and try to open "--help" as a manifest,
        # which produced a traceback instead of usage.
        print(
            "Usage: python3 verify_render.py <manifest.json> "
            "[--report report.json] [--no-fit]"
        )
        print(__doc__)
        sys.exit(0)

    if "--no-fit" in args:
        allow_fit = False
        args.remove("--no-fit")
    if "--report" in args:
        i = args.index("--report")
        if i + 1 >= len(args):
            print("--report needs a path", file=sys.stderr)
            sys.exit(2)
        report_path = args[i + 1]
        del args[i:i + 2]

    if len(args) != 1:
        print(
            "Usage: python3 verify_render.py <manifest.json> [--report report.json] [--no-fit]",
            file=sys.stderr,
        )
        sys.exit(2)

    with open(args[0], "r", encoding="utf-8") as f:
        manifest = json.load(f)
    entries = manifest["slides"] if isinstance(manifest, dict) else manifest
    entries = [e for e in entries if e.get("html_path")]

    if not entries:
        print("No slides with an html_path in the manifest; nothing to verify.", file=sys.stderr)
        sys.exit(2)

    for e in entries:
        if not os.path.isfile(e["html_path"]):
            print(f"html_path does not exist: {e['html_path']}", file=sys.stderr)
            sys.exit(2)

    try:
        report = run_gate(entries, allow_fit)
    except PlaywrightUnavailable as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        # The report is on disk, so echoing it here buys nothing and costs
        # the caller roughly 5k tokens of per-slide measurement detail per
        # build. Print the two parts anything downstream actually acts on:
        # which slides landed where, and the known-fit-issues list the
        # fit report carries verbatim. Everything else is in the file.
        print(json.dumps({
            "report_path": report_path,
            "canvas": report["canvas"],
            "fit_applied": report["fit_applied"],
            "summary": report["summary"],
            "known_fit_issues": report["known_fit_issues"],
        }, indent=2))
    else:
        print(json.dumps(report, indent=2))

    sys.exit(1 if report["summary"]["blocking"] else 0)


if __name__ == "__main__":
    main()
