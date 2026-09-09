"""
layout_chrome.py — move template chrome that's duplicated on every slide onto
the Slide Layout, where it belongs.

The problem this solves
------------------------
The same export pipelines that draw tables as a grid of shapes (see
native_table.py) tend to also leave the slide layout and slide master
completely empty, and instead copy every piece of recurring template
"chrome" — a decorative icon, the client logo, a footer bar, an accent
line, a deck label, a page number — onto EVERY SLIDE as its own
freely movable shape. In PowerPoint terms, that's the same mistake as
redrawing your slide master by hand on every single slide: nothing stops
someone from nudging the logo half an inch on slide 14 by accident, and
there's no single place to update the footer text for the whole deck.

This module finds shapes that are byte-for-byte identical (same position,
size, fill, text) across every slide, and moves them onto the one Slide
Layout those slides share — after which they render exactly the same way,
but are no longer part of any individual slide, exactly like PowerPoint's
own Slide Master / Layout chrome. The one common exception — a page number
that legitimately differs slide to slide — is upgraded to a real
`<a:fld type="slidenum">` field that auto-computes per slide, the same
mechanism PowerPoint's own Insert > Header & Footer uses, instead of being
left as (or converted to) more static per-slide text.

Two entry points:
  - find_chrome_groups(prs)      -> classified groups: promote as-is,
                                     promote as a slide-number field, or
                                     leave alone (with the reason)
  - promote_chrome_to_layout(prs, groups) -> does the move, returns a summary

See SKILL.md Workflow C. This only handles slides that share ONE layout —
see the docstring on find_chrome_groups for what to do with multiple layouts.
"""

from __future__ import annotations

import copy
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn

RT_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_ALIGN_CODE = {1: "l", 2: "ctr", 3: "r"}


@dataclass
class ChromeGroup:
    kind: str                 # "static" | "slidenum" | "skipped"
    signature: tuple
    reason: Optional[str] = None       # set when kind == "skipped"
    items: list = field(default_factory=list)  # list[(slide_index, shape)]


def _bbox_in(shape):
    return (round(shape.left / 914400, 2), round(shape.top / 914400, 2),
            round(shape.width / 914400, 2), round(shape.height / 914400, 2))


def _fill_hex(shape):
    try:
        if shape.fill.type is not None:
            return str(shape.fill.fore_color.rgb)
    except Exception:
        return None
    return None


def _signature(shape):
    """Position + size + type + fill, deliberately ignoring text — this is
    what lets a page number (same position/style, different text) still
    group with itself across slides so it can be classified as a
    slide-number candidate rather than silently skipped."""
    return (_bbox_in(shape), str(shape.shape_type), _fill_hex(shape))


def find_chrome_groups(prs, slide_indices=None, min_fraction=1.0):
    """
    Group shapes by signature across the given slides (default: all slides
    in `prs` — pass `slide_indices` to scope this to just the slides that
    share one layout, if the deck has more than one).

    A group promotes only if it appears on at least `min_fraction` of the
    scoped slides (default 1.0 = every single one — loosen this if a few
    slides legitimately omit the chrome, e.g. a title slide, but check the
    'skipped' groups either way before promoting anything).

    Returns a list of ChromeGroup:
      - kind="static":   identical shape (including identical text, often
                         empty) on every slide -> promote verbatim.
      - kind="slidenum": identical position/style, but text differs and is
                         purely numeric on every slide -> promote as a real
                         auto-computing slide-number field instead of
                         cloning the literal text.
      - kind="skipped":  same position/style but text differs and ISN'T a
                         simple number (e.g. a title placeholder that
                         happens to sit in the same spot on every slide) —
                         left alone, `reason` explains why. Always read
                         these before promoting; a real title/body box
                         should never be moved to the layout.
    """
    slides = list(prs.slides)
    idxs = slide_indices if slide_indices is not None else range(len(slides))
    scoped = [(i, slides[i]) for i in idxs]

    buckets = defaultdict(list)
    for si, slide in scoped:
        for shp in slide.shapes:
            buckets[_signature(shp)].append((si, shp))

    threshold = max(1, int(round(min_fraction * len(scoped))))
    groups = []
    for sig, items in buckets.items():
        if len({si for si, _ in items}) < threshold:
            continue
        texts = {s.text_frame.text if s.has_text_frame else "" for _, s in items}
        if len(texts) == 1:
            groups.append(ChromeGroup(kind="static", signature=sig, items=items))
        elif all(t.strip().isdigit() for t in texts):
            groups.append(ChromeGroup(kind="slidenum", signature=sig, items=items))
        else:
            groups.append(ChromeGroup(
                kind="skipped", signature=sig, items=items,
                reason=f"same position/style but {len(texts)} different, "
                       f"non-numeric text values — likely real per-slide content",
            ))
    return groups


def _next_id_fn(spTree):
    existing = [int(e.get("id")) for e in spTree.iter(qn("p:cNvPr"))]
    counter = [(max(existing) + 1) if existing else 100]

    def _next():
        counter[0] += 1
        return counter[0] - 1
    return _next


def _clone_static_to_layout(shape, layout, next_id):
    el = copy.deepcopy(shape._element)
    cNvPr = el.find(".//" + qn("p:cNvPr"))
    if cNvPr is not None:
        cNvPr.set("id", str(next_id()))
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        blip = el.find(".//" + qn("a:blip"))
        old_rid = blip.get(qn("r:embed"))
        image_part = shape.part.rels[old_rid].target_part
        new_rid = layout.part.relate_to(image_part, RT_IMAGE)
        blip.set(qn("r:embed"), new_rid)
    layout.shapes._spTree.append(el)


def _slidenum_layout_placeholder(sample_shape, ph_idx, next_id):
    l, t, w, h = sample_shape.left, sample_shape.top, sample_shape.width, sample_shape.height
    para = sample_shape.text_frame.paragraphs[0]
    run = para.runs[0] if para.runs else None
    align = _ALIGN_CODE.get(int(para.alignment) if para.alignment is not None else -1, "r")
    font_name = (run.font.name if run else None) or "Calibri"
    font_size = (run.font.size.pt if run and run.font.size else 9)
    bold = "1" if (run and run.font.bold) else "0"
    color_hex = None
    try:
        if run and run.font.color and run.font.color.type is not None:
            color_hex = str(run.font.color.rgb)
    except Exception:
        pass
    color_xml = (f'<a:solidFill xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                 f'<a:srgbClr val="{color_hex}"/></a:solidFill>') if color_hex else ""
    xml = f'''<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                     xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p:nvSpPr>
        <p:cNvPr id="{next_id()}" name="Slide Number Placeholder"/>
        <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
        <p:nvPr><p:ph type="sldNum" sz="quarter" idx="{ph_idx}"/></p:nvPr>
      </p:nvSpPr>
      <p:spPr>
        <a:xfrm><a:off x="{l}" y="{t}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
      </p:spPr>
      <p:txBody>
        <a:bodyPr/><a:lstStyle/>
        <a:p>
          <a:pPr algn="{align}"/>
          <a:fld id="{{{uuid.uuid4()}}}" type="slidenum">
            <a:rPr lang="en-US" sz="{int(font_size * 100)}" b="{bold}">{color_xml}<a:latin typeface="{font_name}"/></a:rPr>
            <a:t>1</a:t>
          </a:fld>
        </a:p>
      </p:txBody>
    </p:sp>'''
    return parse_xml(xml)


def _slidenum_slide_echo(display_number, ph_idx, next_id):
    """The minimal per-slide reference a slide-number field needs to actually
    render (a layout-only placeholder, with no slide anywhere referencing it,
    does not display — verified against LibreOffice's renderer). No xfrm, no
    style: it inherits everything from the layout placeholder of the same
    idx, and is not meant to be dragged or restyled slide-by-slide — in
    PowerPoint this is what "Insert > Header & Footer > Slide Number" turns
    on for you, not a freeform text box."""
    xml = f'''<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                     xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p:nvSpPr>
        <p:cNvPr id="{next_id()}" name="Slide Number Placeholder"/>
        <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
        <p:nvPr><p:ph type="sldNum" sz="quarter" idx="{ph_idx}"/></p:nvPr>
      </p:nvSpPr>
      <p:spPr/>
      <p:txBody>
        <a:bodyPr/><a:lstStyle/>
        <a:p><a:fld id="{{{uuid.uuid4()}}}" type="slidenum"><a:t>{display_number}</a:t></a:fld></a:p>
      </p:txBody>
    </p:sp>'''
    return parse_xml(xml)


def promote_chrome_to_layout(prs, groups, layout=None, slidenum_ph_idx="100"):
    """
    Apply the groups from find_chrome_groups (skip "skipped" groups yourself
    — this function promotes whatever you pass it, so filter first). Returns
    a dict summary: {"promoted": [...], "removed_shapes": N}.
    """
    slides = list(prs.slides)
    layout = layout or slides[0].slide_layout
    next_id = _next_id_fn(layout.shapes._spTree)

    to_remove = []
    summary = {"promoted": [], "removed_shapes": 0}

    for grp in groups:
        if grp.kind == "skipped":
            continue
        if grp.kind == "static":
            _, sample = grp.items[0]
            _clone_static_to_layout(sample, layout, next_id)
            for si, shp in grp.items:
                to_remove.append(shp._element)
            summary["promoted"].append(("static", grp.signature))
        elif grp.kind == "slidenum":
            _, sample = grp.items[0]
            layout.shapes._spTree.append(
                _slidenum_layout_placeholder(sample, slidenum_ph_idx, next_id)
            )
            for si, shp in grp.items:
                echo = _slidenum_slide_echo(si + 1, slidenum_ph_idx, next_id)
                slides[si].shapes._spTree.append(echo)
                to_remove.append(shp._element)
            summary["promoted"].append(("slidenum", grp.signature))

    for el in to_remove:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    summary["removed_shapes"] = len(to_remove)
    return summary
