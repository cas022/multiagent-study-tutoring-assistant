#!/usr/bin/env python3
"""
build_deck.py - the single render entrypoint: render, fit-gate, preview.

WHAT THIS REPLACES
------------------
Producing a deck's HTML used to take three classes of hand-written JSON
and roughly 2N+4 tool round-trips for an N-slide deck:

    slide_NN_spec.json      one per cowork slide, hand-written, then
                            render_slide.py invoked once per slide
    fit_manifest.json       hand-written, then verify_render.py
    preview_manifest.json   hand-written, then build_html_preview.py

Every one of those files is derivable from outline_validated.json, which
already holds each slide's role, data and number. None of them was
ever a decision - they were transcription. This script derives all three
in memory and runs the whole segment in one call:

    python3 build_deck.py outline_validated.json --outdir . \\
            --fit-report fit_report.json --preview deck_preview.html

Nothing here re-implements rendering or measurement. render_slide.render_slide
and verify_render.run_gate are imported and called, so a change to either
reaches this path automatically and the two entry points cannot drift.
Importing them also means the pydantic and jinja2 import cost, and the
Chromium launch, are each paid ONCE for the whole deck rather than once
per slide.

WHAT IT PRODUCES
----------------
    <outdir>/slide_NN.html   one per slide, NN zero-padded to
                             two digits and numbered by DECK POSITION
    --fit-report <path>      verify_render's report, verbatim
    --preview <path>         build_html_preview's output, covering EVERY
                             slide in the deck in deck order

Every slide in the deck is rendered here; there is no second track. A
slide that cannot be rendered still occupies its own numbered panel in
the preview, carrying the fixed note:

    SLIDE N - BUILD THIS SLIDE - see fit report Section 3, Slide N

That is not cosmetic. The fit report's INSERT lines say "take slide N
from the attached HTML file", which is only true while panel numbering
equals deck numbering, so no slide is ever skipped or renumbered.

NUMBERING. Filenames, footer page numbers and preview panels all use the
slide's position in the deck. A slide whose `slide_number` disagrees with
its position is reported on stderr rather than silently accommodated: the
fit report is written from `slide_number`, so a disagreement means the
brief and the preview will reference different slides, and that is an
upstream numbering fault to fix, not something for this script to paper
over by picking one of the two.

EXIT CODES
----------
    0  every slide rendered, and the gate found no BLOCKING issue
    1  at least one BLOCKING fit issue. INFORMATION, NOT A STOP - every
       artifact was still written. A BLOCKING issue means content exists
       in the markup that is not visible on the canvas, or type is below
       the legible floor; it is named in the fit report as a BLOCKING
       flag for the student to resolve by cutting content.
    2  Playwright or Chromium was unavailable, so NOTHING WAS MEASURED.
       The slides and the preview are still written, and no fit report is
       written at all - there is no measurement to put in one. A caller
       seeing exit 2 must report the deck as unmeasured. It has not
       passed the gate; the gate did not run.
    3  a hard failure - unreadable input, an unknown slide_role, or a
       slide whose data does not validate against its role's model.
       Nothing usable was produced.

--no-fit skips the gate entirely (the same flag verify_render.py takes).
Slides and the preview are still produced, no fit report is written, and
the exit code is 0 - a skipped gate is a caller's explicit choice, unlike
an unavailable one.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_html_preview  # noqa: E402
import verify_render  # noqa: E402
from render_slide import DEFAULT_ASSETS_DIR, render_slide  # noqa: E402

# Fixed, per the pipeline contract. Do not vary this wording: the Design
# Brief points at "Section 3, Slide N" and a reader matching the two by
# eye needs them to read the same way every time.
BUILD_NOTE = "SLIDE {n} - BUILD THIS SLIDE - see fit report Section 3, Slide {n}"

USAGE = (
    "Usage: python3 build_deck.py <outline_validated.json> [--outdir DIR] "
    "[--fit-report PATH] [--preview PATH] [--assets DIR] [--no-fit]"
)


def _parse_args(argv):
    opts = {
        "outline": None,
        "outdir": ".",
        "fit_report": None,
        "preview": None,
        "assets": None,
        "allow_fit": True,
    }
    positional = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--help", "-h"):
            print(USAGE)
            print(__doc__)
            sys.exit(0)
        elif a == "--no-fit":
            opts["allow_fit"] = False
            i += 1
        elif a in ("--outdir", "--fit-report", "--preview", "--assets"):
            if i + 1 >= len(argv):
                print(f"{a} needs a path", file=sys.stderr)
                sys.exit(3)
            opts[a[2:].replace("-", "_")] = argv[i + 1]
            i += 2
        elif a.startswith("-"):
            print(f"Unknown option {a!r}\n{USAGE}", file=sys.stderr)
            sys.exit(3)
        else:
            positional.append(a)
            i += 1

    if len(positional) != 1:
        print(USAGE, file=sys.stderr)
        sys.exit(3)
    opts["outline"] = positional[0]
    return opts


def render_deck(deck: dict, outdir: str, assets_path: str):
    """Render every slide in the deck. Returns (rendered, manifest).

    `rendered` is one entry per rendered slide, in deck order, shaped as
    verify_render expects its manifest entries. `manifest` is the preview
    manifest, which carries the same set: every slide renders here.
    """
    slides = deck.get("slides") or []
    rendered = []
    preview_manifest = []
    misnumbered = []

    for position, slide in enumerate(slides, start=1):
        role = slide.get("slide_role")

        if slide.get("slide_number") != position:
            misnumbered.append((slide.get("slide_number"), position, role))

        out_path = os.path.abspath(os.path.join(outdir, f"slide_{position:02d}.html"))
        try:
            html = render_slide(role, slide.get("data") or {}, position, assets_path)
        except Exception as e:
            raise SystemExit(
                f"Slide {position} ({role}) failed to render: {e}\n"
                f"Slides before this one were written and are now stale; no fit "
                f"report and no preview were produced. Fix the slide's data in the "
                f"validated outline and re-run; do not hand-edit the HTML."
            )
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        rendered.append({
            "slide_number": position,
            "slide_role": role,
            "html_path": out_path,
        })
        preview_manifest.append({
            "slide_number": position,
            "html_path": out_path,
        })

    return rendered, preview_manifest, misnumbered


def main():
    opts = _parse_args(sys.argv[1:])

    try:
        with open(opts["outline"], "r", encoding="utf-8") as f:
            deck = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Could not read {opts['outline']!r}: {e}", file=sys.stderr)
        sys.exit(3)

    slides = deck.get("slides")
    if not slides:
        print(
            f"{opts['outline']!r} has no slides. This script renders a validated "
            f"deck outline; run validate_deck_outline.py first.",
            file=sys.stderr,
        )
        sys.exit(3)

    outdir = opts["outdir"]
    os.makedirs(outdir, exist_ok=True)

    assets_path = opts["assets"] or DEFAULT_ASSETS_DIR
    if not os.path.isdir(assets_path):
        # Same discipline render_slide.py's own CLI applies: fall back and
        # say so, rather than emitting broken <img> paths silently.
        print(
            f"assets_path {assets_path!r} does not exist; falling back to the bundled "
            f"default ({DEFAULT_ASSETS_DIR!r}) instead of rendering with a broken image path.",
            file=sys.stderr,
        )
        assets_path = DEFAULT_ASSETS_DIR

    try:
        rendered, preview_manifest, misnumbered = render_deck(deck, outdir, assets_path)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        sys.exit(3)

    for actual, position, role in misnumbered:
        print(
            f"slide_number {actual!r} does not match deck position {position} "
            f"({role}). This script used position {position} for the filename, the "
            f"footer page number and the preview panel. The fit report is written "
            f"from slide_number, so fix the numbering upstream before relying on the "
            f"brief's INSERT lines.",
            file=sys.stderr,
        )

    # ---- fit gate -----------------------------------------------------
    fit_status = "skipped"
    fit_exit = 0
    blocking_slides = []
    blocking_flag_count = 0
    fit_report_path = None

    if not rendered:
        fit_status = "no_cowork_slides"
    elif not opts["allow_fit"]:
        fit_status = "skipped"
    else:
        try:
            report = verify_render.run_gate(rendered, allow_fit=True)
        except verify_render.PlaywrightUnavailable as e:
            print(str(e), file=sys.stderr)
            fit_status = "unavailable"
            fit_exit = 2
        else:
            blocking_slides = report["summary"]["blocking"]
            blocking_flag_count = sum(
                1
                for s in report["slides"]
                for fl in s["flags"]
                if fl["level"] == "BLOCKING"
            )
            fit_status = "blocking" if blocking_slides else "ok"
            fit_exit = 1 if blocking_slides else 0
            if opts["fit_report"]:
                with open(opts["fit_report"], "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=2)
                fit_report_path = opts["fit_report"]

    # ---- preview ------------------------------------------------------
    # After the gate, deliberately: verify_render edits fitted slides in
    # place, and the preview has to carry the fitted HTML, not the raw
    # render it replaced.
    preview_path = None
    if opts["preview"]:
        try:
            html, previewed, notes, _inlined, unresolved, _assets = build_html_preview.build(
                preview_manifest, subject=deck.get("subject")
            )
        except ValueError as e:
            print(f"Preview build failed: {e}", file=sys.stderr)
            sys.exit(3)
        with open(opts["preview"], "w", encoding="utf-8") as f:
            f.write(html)
        preview_path = opts["preview"]
        if unresolved:
            print(
                "WARNING: local asset reference(s) did not resolve on disk and were "
                "left as-is - these will render as broken images wherever the preview "
                "is opened:",
                file=sys.stderr,
            )
            for item in unresolved:
                print(f"  slide {item['slide_number']}: {item['ref']}", file=sys.stderr)

    print(json.dumps({
        "outdir": os.path.abspath(outdir),
        "slides_in_deck": len(slides),
        "slides_rendered": len(rendered),
        "rendered": [
            {"slide_number": r["slide_number"], "slide_role": r["slide_role"],
             "html_path": r["html_path"]}
            for r in rendered
        ],
        "fit_gate": {
            "status": fit_status,
            "exit_status": fit_exit,
            "blocking_flag_count": blocking_flag_count,
            "blocking_slides": blocking_slides,
            "report_path": fit_report_path,
            "measured": fit_status in ("ok", "blocking"),
        },
        "preview_path": preview_path,
        "exit_code": fit_exit,
    }, indent=2))

    sys.exit(fit_exit)


if __name__ == "__main__":
    main()
