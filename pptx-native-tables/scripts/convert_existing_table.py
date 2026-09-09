#!/usr/bin/env python3
"""
Retrofit a shape-grid fake table in an existing .pptx into one native table.

Usage
-----
# 1. Dry run first — always. Dumps the detected grid as text so you can check
#    it against the slide before touching anything.
python convert_existing_table.py deck.pptx --slide 0 --bbox 0.58,1.85,12.75,6.6

# 2. Once the dump looks right, apply and save.
python convert_existing_table.py deck.pptx --slide 0 --bbox 0.58,1.85,12.75,6.6 \
    --apply -o deck-native-table.pptx

bbox is "left,top,right,bottom" in inches, covering exactly the region the
fake table occupies — nothing more (leave out titles, footnotes, logos).
Find it fast with python-pptx: print each shape's .left/.top/.width/.height
divided by 914400, or eyeball it against scripts/office in the pptx skill's
thumbnail render.

If --rows is omitted, the number of rows is inferred from clustering — check
the dry-run dump carefully in that case, since a stray shape just outside the
real grid can add a phantom row.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from native_table import extract_grid, build_native_table  # noqa: E402

from pptx import Presentation


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pptx_path")
    ap.add_argument("--slide", type=int, default=0)
    ap.add_argument("--bbox", required=True, help="left,top,right,bottom in inches")
    ap.add_argument("--rows", type=int, default=None)
    ap.add_argument("--row-tol", type=float, default=0.08)
    ap.add_argument("--col-tol", type=float, default=0.15)
    ap.add_argument("--apply", action="store_true", help="Actually rebuild and save. Without this, just dry-run and print.")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    bbox = tuple(float(x) for x in args.bbox.split(","))
    if len(bbox) != 4:
        ap.error("--bbox needs exactly 4 comma-separated numbers: left,top,right,bottom")

    prs = Presentation(args.pptx_path)
    slide = prs.slides[args.slide]

    extraction = extract_grid(slide, bbox, n_rows=args.rows, row_tol=args.row_tol, col_tol=args.col_tol)

    n_rows = len(extraction.matrix)
    n_cols = len(extraction.matrix[0]) if n_rows else 0
    print(f"Detected grid: {n_rows} rows x {n_cols} cols")
    print(f"Shapes that will be removed: {len(extraction.shapes_to_remove)}")
    print(f"Table position: left={extraction.left_in:.3f}in top={extraction.top_in:.3f}in "
          f"size={sum(extraction.col_widths_in):.3f}in x {sum(extraction.row_heights_in):.3f}in")
    print()
    print("Content preview (first run's text per cell):")
    for r, row in enumerate(extraction.matrix):
        cells = []
        for cell in row:
            txt = cell.runs[0].text if cell.runs else ""
            cells.append(txt[:14])
        marker = " <- bottom border" if any(c.bottom_border_hex for c in row) else ""
        print(f"  {r:>2} {cells}{marker}")

    if not args.apply:
        print("\nDry run only — pass --apply -o output.pptx to rebuild and save.")
        return

    if not args.output:
        ap.error("--apply requires -o/--output")

    build_native_table(slide, extraction, delete_originals=True)
    prs.save(args.output)
    print(f"\nSaved: {args.output}")
    print("Now run the pptx skill's validate.py and render to image to QA the result.")


if __name__ == "__main__":
    main()
