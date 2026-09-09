#!/usr/bin/env python3
"""
build_html_preview.py - combines every rendered slide (and, optionally,
any slide supplied with its own pre-rendered HTML
export) into one scrollable, single-file preview document, framed at a
consistent 16:9 size and labeled by slide number.

Why this exists: reviewing a deck one slide file at a time is slow, and
the thing a student actually wants to check before studying from a guide
is whether it reads well end to end. This gives the whole deck on one
scrollable page. It is a review view, not the deliverable - build_pptx.py
produces the editable .pptx from the same validated outline:
see the module note below on why cross-slide asset dedup was measured and
declined. This formalizes what an earlier session's orchestrator
improvised ad hoc (an unofficial
"final_deck.html quick-view" delivered alongside a real pptx) into a
real, repeatable artifact this plugin actually produces on request.

This script does not re-render or re-interpret any slide's HTML - it wraps
each slide's markup inside its own <iframe>, at the same fixed 1280x720
canvas every template already renders at (see css_layout.py's
CANVAS_W/CANVAS_H). Each slide keeps its own <style> and its own DOM -
none of that is merged into a shared page, precisely so two slides built
from two different templates (which may reuse class names like `.slide`
or `.veil` with different meanings) can never collide or bleed into each
other visually the way a raw HTML concatenation would risk.

**Self-contained output.** This file has to survive being moved, mailed
or opened from a different folder, so the slide markup and every asset it
references travel inside it. So:

  - Slide markup is embedded via <iframe srcdoc="...">, not
    <iframe src="file://...">. The previous src= form referenced slides by
    absolute local path, which meant the preview file carried no slide
    content at all and was useless anywhere except the machine that built
    it.
  - Local image assets a slide references (the brand logos and the cover
    photo, which render_slide.py emits as ordinary <img src> and CSS
    url() paths) are inlined as base64 data URIs, so no slide arrives with
    a broken logo.

The result is one file with no external dependencies of any kind. Remote
URLs and existing data: URIs are left exactly as they are; only local
paths that actually resolve on disk are inlined.

**Why the asset payload is repeated per slide, and stays repeated.** Every
template references the brand logo, so the same base64 blob is embedded
once per slide and a 12-slide preview runs to roughly 1.5MB, of which
about 60% is the same three images over and over. That is worth removing
from a file meant to be shared, and it was measured and rejected rather
than overlooked. There is no static HTML mechanism for one document to
reference a byte payload held in another: an iframe's srcdoc is a separate
document, and a separate document can only reach an image by URL, which
means an external file and the end of the self-contained property this
whole section exists to establish. Every dedup that does work needs
JavaScript at view time - a parent script assembling each srcdoc from a
shared asset map, or patching each frame's <img> after load. Both were
confirmed to work in Chromium over file://, and both were declined for the
same reason: this file has to render correctly for anything that reads
the markup without executing scripts, and a slide whose images only exist
inside a script the reader may never run is a slide that arrives
broken. What IS deduplicated is the work: each distinct asset is read
and base64-encoded exactly once per process (_ASSET_CACHE), no matter how
many slides embed it. The summary reports `assets_inlined` against
`assets_distinct` so the repetition is visible rather than assumed away.

Usage:
    python3 build_html_preview.py <manifest.json> <output.html>

manifest.json shape (a JSON list, in final slide order, OR an object with
a top-level "slides" list plus an optional "subject"):
    [
      {"slide_number": 1, "html_path": "/abs/path/slide_01.html"},
      {"slide_number": 2, "html_path": "/abs/path/slide_02.html"},
      {"slide_number": 3, "note": "Not rendered - see the build report"},
      ...
    ]

A slide entry needs either `html_path` (a real, existing HTML file, any
or `note` (a short string shown in place of a frame, for a slide with
nothing to preview) - never neither,
and this script refuses to build a preview with a silently-skipped gap
rather than dropping a slide it can't show.

`track` is accepted and ignored: it is a leftover key from an earlier
two-track build and drove a per-slide badge. Both the second track and the
badge are gone. The key is still accepted so existing manifests keep
working.

Prints a JSON summary to stdout on success:
    {"output_path": "...", "slide_count": N, "previewed": N, "notes": N}
"""
import base64
import html as html_mod
import json
import os
import re
import sys

# Extension -> mime, for inlining local image assets as data URIs. Kept as
# an explicit map rather than mimetypes.guess_type so the set of things
# this script will inline is visible and bounded.
_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}

# Matches src="..." / src='...' and CSS url(...) with or without quotes.
_ASSET_REF = re.compile(
    r"""(?P<pre>\bsrc\s*=\s*(?P<q1>["'])|url\(\s*(?P<q2>["']?))(?P<path>[^"')]+)(?P<post>(?P=q1)|(?P=q2)\s*\))""",
    re.IGNORECASE | re.VERBOSE,
)


def _is_local_path(ref: str) -> bool:
    ref = ref.strip()
    if not ref:
        return False
    lowered = ref.lower()
    return not (
        lowered.startswith("data:")
        or lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("//")
        or lowered.startswith("#")
    )


# {absolute path -> "data:<mime>;base64,<...>"}. The brand logo is
# referenced by every template in the library, so a 12-slide deck used to
# re-read and re-base64 the same file a dozen times. Encoding is the
# expensive half and the result is a pure function of the file's bytes, so
# it is computed once per distinct asset per process.
#
# Deliberately module-level rather than per-build() so a caller that
# builds several previews in one process (build_deck.py does not, but
# nothing stops one) pays the encode once overall. Nothing here is
# invalidated mid-run: these are build inputs, read once, at the end of a
# render step that has already finished writing them.
_ASSET_CACHE = {}


def _encode_asset(abs_path: str, mime: str) -> str:
    cached = _ASSET_CACHE.get(abs_path)
    if cached is None:
        with open(abs_path, "rb") as fh:
            cached = f"data:{mime};base64," + base64.b64encode(fh.read()).decode("ascii")
        _ASSET_CACHE[abs_path] = cached
    return cached


def _inline_assets(markup: str, base_dir: str):
    """Replace local image references with base64 data URIs.

    Returns (markup, inlined_count, unresolved, distinct_paths).
    `unresolved` lists local paths that did not resolve on disk - reported
    rather than silently left as a broken reference, since a missing logo
    is exactly the kind of thing that is invisible until the deck is in
    front of a committee. `distinct_paths` is the set of assets this slide
    actually embedded, which the caller aggregates to report how much of
    the finished file is repeated payload.
    """
    inlined = 0
    unresolved = []
    distinct = set()

    def _replace(match):
        nonlocal inlined
        raw = match.group("path")
        if not _is_local_path(raw):
            return match.group(0)

        path = raw.split("?", 1)[0].split("#", 1)[0]
        if path.startswith("file://"):
            path = path[len("file://"):]
        candidate = path if os.path.isabs(path) else os.path.join(base_dir, path)
        candidate = os.path.normpath(candidate)

        ext = os.path.splitext(candidate)[1].lower()
        if ext not in _MIME_BY_EXT or not os.path.isfile(candidate):
            unresolved.append(raw)
            return match.group(0)

        data_uri = _encode_asset(candidate, _MIME_BY_EXT[ext])
        inlined += 1
        distinct.add(candidate)
        return match.group(0).replace(raw, data_uri)

    return _ASSET_REF.sub(_replace, markup), inlined, unresolved, distinct

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #2b2f36; font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
  .scaffolding-banner {{ color: #a9adb3; padding: 18px 28px 4px; font-size: 12px; letter-spacing: .02em; }}
  .slide-panel {{ margin: 24px auto; width: 1280px; }}
  .slide-badge {{ color: #d7dae0; font-size: 13px; margin-bottom: 6px; }}
  .slide-badge .num {{ font-weight: 700; color: #f0f0f0; font-size: 15px; }}
  .frame-wrap {{ width: 1280px; height: 720px; border-radius: 4px; overflow: hidden; box-shadow: 0 4px 18px rgba(0,0,0,.35); background: #fff; }}
  .frame-wrap iframe {{ width: 1280px; height: 720px; border: 0; display: block; }}
  .note-panel {{ width: 1280px; height: 720px; border-radius: 4px; display: flex; align-items: center; justify-content: center; background: #1c1f24; border: 2px dashed #4a4f57; color: #9aa0a8; font-size: 15px; text-align: center; padding: 40px; box-sizing: border-box; }}
</style>
</head>
<body>
<!-- SCAFFOLDING BANNER - NOT DECK CONTENT -->
<div class="scaffolding-banner">{subtitle}</div>
{panels}
</body>
</html>
"""

PANEL_TEMPLATE = """<!-- SLIDE {number} BEGIN -->
<div class="slide-panel" data-slide-number="{number}">
  <div class="slide-badge"><span class="num">Slide {number}</span></div>
  {body}
</div>
<!-- SLIDE {number} END -->
"""


def build(slides: list, subject: str = None):
    if not slides:
        raise ValueError("Manifest has no slides - nothing to preview.")

    panels = []
    previewed = 0
    notes = 0
    assets_inlined = 0
    unresolved_assets = []
    distinct_assets = set()

    for entry in slides:
        number = entry.get("slide_number")
        track = entry.get("track")
        html_path = entry.get("html_path")
        note = entry.get("note")

        if html_path:
            if not os.path.isfile(html_path):
                raise ValueError(
                    f"Slide {number}: html_path {html_path!r} does not exist - "
                    f"refusing to build a preview with a silently-skipped gap."
                )
            abs_path = os.path.abspath(html_path)
            with open(abs_path, "r", encoding="utf-8") as fh:
                markup = fh.read()
            markup, n_inlined, unresolved, distinct = _inline_assets(
                markup, os.path.dirname(abs_path)
            )
            assets_inlined += n_inlined
            distinct_assets |= distinct
            unresolved_assets.extend(
                {"slide_number": number, "ref": ref} for ref in unresolved
            )
            # srcdoc carries the slide's whole document as an attribute
            # value, so it has to be HTML-escaped; the browser unescapes it
            # back to the identical markup before rendering.
            body = (
                f'<div class="frame-wrap">'
                f'<iframe srcdoc="{html_mod.escape(markup, quote=True)}" loading="lazy"></iframe>'
                f'</div>'
            )
            previewed += 1
        elif note:
            body = f'<div class="note-panel">{note}</div>'
            notes += 1
        else:
            raise ValueError(f"Slide {number} has neither html_path nor note - nothing to show.")

        panels.append(PANEL_TEMPLATE.format(number=number, body=body))

    title = f"{subject} - slides" if subject else "Slides"
    # Deliberately terse and self-describing as scaffolding. This file is read
    # by tooling as well as by a person, and any prose in the wrapper is
    # text a reader may mistake for
    # content or instruction. Say what the wrapper is, tell a reader to ignore
    # it, and stop.
    subtitle = (
        f"SCAFFOLDING, NOT DECK CONTENT. This page is a viewer wrapper around "
        f"{len(slides)} slide(s). Each panel below is one slide's real rendered "
        f"markup. Ignore this banner and the slide-number labels; they are not "
        f"part of any slide."
    )

    html = PAGE_TEMPLATE.format(title=title, subtitle=subtitle, panels="\n".join(panels))

    # How much of the finished file is the same asset embedded again. See
    # the module docstring's note on why this is reported and not removed.
    unique_bytes = 0
    for p in distinct_assets:
        try:
            unique_bytes += os.path.getsize(p)
        except OSError:
            pass
    assets = {
        "embedded": assets_inlined,
        "distinct": len(distinct_assets),
        "distinct_source_bytes": unique_bytes,
    }
    return html, previewed, notes, assets_inlined, unresolved_assets, assets


def main():
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print("Usage: python3 build_html_preview.py <manifest.json> <output.html>")
        print(__doc__)
        sys.exit(0)

    if len(sys.argv) != 3:
        print("Usage: python3 build_html_preview.py <manifest.json> <output.html>", file=sys.stderr)
        sys.exit(2)

    manifest_path, output_path = sys.argv[1], sys.argv[2]

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    slides = manifest if isinstance(manifest, list) else manifest.get("slides", [])
    subject = manifest.get("subject") if isinstance(manifest, dict) else None

    try:
        html, previewed, notes, assets_inlined, unresolved, assets = build(
            slides, subject=subject
        )
    except ValueError as e:
        print(f"Preview build failed: {e}", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    if unresolved:
        print(
            "WARNING: local asset reference(s) did not resolve on disk and were "
            "left as-is - these will render as broken images wherever this file "
            "is opened:",
            file=sys.stderr,
        )
        for item in unresolved:
            print(f"  slide {item['slide_number']}: {item['ref']}", file=sys.stderr)

    print(json.dumps({
        "output_path": output_path,
        "output_bytes": os.path.getsize(output_path),
        "slide_count": len(slides),
        "previewed": previewed,
        "notes": notes,
        "assets_inlined": assets_inlined,
        "assets_distinct": assets["distinct"],
        "unresolved_assets": unresolved,
        "self_contained": not unresolved,
    }, indent=2))


if __name__ == "__main__":
    main()
