#!/usr/bin/env python3
"""
Find shapes duplicated on every slide (a decorative icon, a logo, a footer
bar, a deck label, a page number) and move them onto the Slide
Layout, where recurring template chrome belongs.

Usage
-----
# 1. Dry run first — always. Lists what would be promoted, what would be
#    left alone, and why.
python promote_layout_chrome.py deck.pptx

# 2. Once it looks right, apply and save.
python promote_layout_chrome.py deck.pptx --apply -o deck-fixed.pptx

If the deck uses more than one slide layout, run this once per layout with
--slides, scoping to just the slide indices (0-based) that share it —
promoting to a layout only affects slides using that layout, but shapes are
only detected as "chrome" within the scope you give it.

    python promote_layout_chrome.py deck.pptx --slides 0,1,2
    python promote_layout_chrome.py deck.pptx --slides 3,4,5,6 --apply -o deck-fixed.pptx
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from layout_chrome import find_chrome_groups, promote_chrome_to_layout  # noqa: E402

from pptx import Presentation


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pptx_path")
    ap.add_argument("--slides", default=None, help="comma-separated 0-based slide indices sharing one layout; default = all slides")
    ap.add_argument("--min-fraction", type=float, default=1.0, help="fraction of scoped slides a shape must appear on to count as chrome (default 1.0 = every slide)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    prs = Presentation(args.pptx_path)
    slide_indices = [int(x) for x in args.slides.split(",")] if args.slides else None

    layouts_in_scope = {id(prs.slides[i].slide_layout) for i in (slide_indices or range(len(prs.slides)))}
    if len(layouts_in_scope) > 1:
        print(f"WARNING: the scoped slides use {len(layouts_in_scope)} different layouts. "
              f"Shapes will only promote to slides[0]'s layout — re-run with --slides "
              f"scoped to one layout at a time for a mixed-layout deck.\n")

    groups = find_chrome_groups(prs, slide_indices=slide_indices, min_fraction=args.min_fraction)

    static = [g for g in groups if g.kind == "static"]
    slidenum = [g for g in groups if g.kind == "slidenum"]
    skipped = [g for g in groups if g.kind == "skipped"]

    print(f"Will promote to the layout ({len(static)} static + {len(slidenum)} slide-number):")
    for g in static + slidenum:
        bbox, shape_type, fill = g.signature
        sample_text = next(iter({s.text_frame.text if s.has_text_frame else '' for _, s in g.items}))
        print(f"  [{g.kind:8}] {shape_type:14} at {bbox} fill={fill} text={sample_text!r}"
              f" (on {len(g.items)} slides)")

    if skipped:
        print(f"\nLeft alone ({len(skipped)} groups — same position/style, but real per-slide content):")
        for g in skipped:
            bbox, shape_type, fill = g.signature
            print(f"  [skipped ] {shape_type:14} at {bbox} — {g.reason}")

    if not args.apply:
        print("\nDry run only — pass --apply -o output.pptx to rebuild and save.")
        return

    if not args.output:
        ap.error("--apply requires -o/--output")

    layout = prs.slides[slide_indices[0] if slide_indices else 0].slide_layout
    summary = promote_chrome_to_layout(prs, static + slidenum, layout=layout)
    prs.save(args.output)
    print(f"\nPromoted {len(summary['promoted'])} groups, removed {summary['removed_shapes']} per-slide shapes.")
    print(f"Saved: {args.output}")
    print("Now run the pptx skill's validate.py and render to image to QA the result —")
    print("especially the slide-number field, which only proves itself correct when rendered.")


if __name__ == "__main__":
    main()
