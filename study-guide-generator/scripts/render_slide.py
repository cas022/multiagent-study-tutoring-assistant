#!/usr/bin/env python3
"""
render_slide.py - the Render stage's real code, for cowork-track slides
only. This is the piece that resurrects actual rendering in this plugin
(dropped in v1.0.x when this plugin's job ended at a design-brief
document; see docs/README.md's "The measured fit gate" section for why
real rendering and real measurement are back).

Given a single slide's validated data (already checked against its own
role's model in deck_schemas.ROLE_MODEL_MAP by validate_deck_outline.py),
this script runs real Jinja2 rendering against the bundled template file
in templates/ - it never asks a model to write HTML by hand. Every slide
in the deck renders through here; there is no second track.

Registers one custom Jinja global, `days_between`, for the date
arithmetic Jinja has no native support for. Dates are
expected in DD-MMM-YY, DD-MMM-YYYY or YYYY-MM-DD form (e.g.
"04-Aug-26"), matching the date fields used across these templates; a
non-parseable value (including the literal string "TBD") returns None.

**No bundled template currently calls it.** mastery-heatmap.html,
which used to, now does its own parsing and subtraction in a local
`date_serial()` macro: `days_between` reads only the three formats
above, and real workplan trackers also hand us DD/MM/YYYY and other
separators, where a date this parser cannot read is indistinguishable
from a date nobody tracked. That distinction is exactly what the
template's current-due-date fallback turns on, so the parsing moved into
the template beside the fallback. The global stays registered and still
works, for any template that wants plain date arithmetic in one of the
three formats.

Usage:
    python3 render_slide.py <slide_spec.json> <output.html>

slide_spec.json shape:
    {
      "slide_role": "cover",
      "data": { ...validated fields for this role... },
      "page_number": 1,
      "assets_path": "./assets"
    }

`assets_path` is optional - templates that don't reference it (most of
the dense-table ones) simply ignore it; templates that do (cover,
section-divider, and any template with a logo) need it pointed at
wherever logo-horizontal-navy.png / logo-horizontal-white.png /
cover-infrastructure.png actually live. This script does not bundle
those image assets itself - see docs/README.md for the disclosed gap.

Writes the rendered HTML to <output.html> and prints that path to
stdout on success.

A real bug found while building this script, fixed here rather than in
the templates: every template's `{% if footnote %}`-style checks assume
Jinja's default lenient Undefined (falsy, no exception) for any field
that's optional and simply wasn't supplied. Rendering with
StrictUndefined instead (the safer-looking default) breaks on the very
first optional field a caller omits rather than passes as an explicit
null. The fix is not to loosen undefined handling - it's to always run
the slide's data through its own Pydantic model first
(model_validate().model_dump()) before handing it to Jinja, so every
field the template expects is always present, with a real None for any
optional field the caller didn't supply. Pydantic still catches a truly
missing REQUIRED field; Jinja never has to guess at an absent key.

A second, related bug found the same way, in comparison-matrix.html and
flashcard-grid.html: those two templates use the
`{{ optional_field | default(fallback) }}` filter form, not just
`{% if optional_field %}`. Jinja's `default()` filter only substitutes
for a genuinely *undefined* variable, not for one whose value is the
real Python object None - so dumping every optional field as an
explicit None (model_dump()'s ordinary behavior) sails straight past
`| default(...)` and breaks whatever runs on the result next (e.g.
`None | length`, `x in None`). The fix is model_dump(exclude_none=True):
a field the caller never supplied is left out of the context entirely,
so Jinja sees it as genuinely undefined - matching what both template
conventions were actually written assuming. `{% if optional_field %}`
checks are unaffected either way, since undefined and None are equally
falsy.
"""
import json
import os
import sys
from datetime import datetime

from jinja2 import Environment, FileSystemLoader
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deck_schemas import ROLE_TEMPLATE_FILE, ROLE_MODEL_MAP  # noqa: E402

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")

# The real, bundled brand assets (logo-horizontal-navy.png,
# logo-horizontal-white.png, cover-infrastructure.png) now ship in this
# plugin's own assets/ directory, sibling to templates/ - this used to be
# a disclosed gap ("this script does not bundle those image assets
# itself"), fixed once the actual asset files were made available. Used
# as the default assets_path whenever a caller doesn't supply one, so a
# slide spec that omits assets_path entirely still resolves logos
# correctly instead of silently rendering with a broken image path.
DEFAULT_ASSETS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
)

_DATE_FORMATS = ["%d-%b-%y", "%d-%b-%Y", "%Y-%m-%d"]


def _parse_date(value):
    if not isinstance(value, str):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def days_between(earlier, later):
    d1 = _parse_date(earlier)
    d2 = _parse_date(later)
    if d1 is None or d2 is None:
        return None
    return (d2 - d1).days


def build_environment():
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        # Default (lenient) Undefined, deliberately - see the module
        # docstring's note on why StrictUndefined breaks these templates'
        # own `{% if optional_field %}` convention.
        autoescape=False,  # these templates already mark user-HTML fields `| safe`
    )
    env.globals["days_between"] = days_between
    return env


def render_slide(slide_role: str, data: dict, page_number, assets_path: str = "") -> str:
    if slide_role not in ROLE_TEMPLATE_FILE:
        raise ValueError(
            f"Unknown slide_role {slide_role!r} - not in deck_schemas.ROLE_TEMPLATE_FILE. "
            f"render_slide.py only renders roles with a real bundled template."
        )

    model_cls = ROLE_MODEL_MAP[slide_role]
    try:
        validated = model_cls.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"data for slide_role {slide_role!r} failed schema validation:\n{e}")

    template_file = ROLE_TEMPLATE_FILE[slide_role]
    env = build_environment()
    template = env.get_template(template_file)

    # exclude_none=True: an optional field the caller never supplied is
    # left out of the context entirely (genuinely undefined to Jinja),
    # rather than dumped as an explicit None that would silently break
    # `{{ x | default(...) }}` filters elsewhere in these templates. See
    # the module docstring's second bug note for the full account.
    context = validated.model_dump(exclude_none=True)

    # Confirmed real bug in the bundled comparison-matrix.html itself, not a
    # data-shape problem on this script's end: when column_widths is
    # omitted, the template tries to rebuild an equal-weight fallback
    # with `{% set widths = widths + [1] %}` inside a `{% for %}` loop  - 
    # but a plain {% set %} inside a Jinja for-loop is scoped to that
    # loop body and does not persist outside it, so `widths` silently
    # stays [] and a later lookup indexes past the end of it
    # (`list index out of range` / "list object has no element 0").
    # Not fixed in the template (it's the authoritative bundled source,
    # not this plugin's to rewrite) - worked around here by always
    # supplying an explicit equal-weight column_widths ourselves when the
    # slide didn't provide one, so the template's own broken fallback
    # branch is never reached at all.
    if slide_role == "comparison_matrix" and not context.get("column_widths"):
        context["column_widths"] = [1] * len(context.get("columns", []))

    context["page_number"] = page_number
    context["assets_path"] = assets_path

    return template.render(**context)


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 render_slide.py <slide_spec.json> <output.html>", file=sys.stderr)
        sys.exit(2)

    spec_path, output_path = sys.argv[1], sys.argv[2]

    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)

    slide_role = spec.get("slide_role")
    data = spec.get("data", {})
    page_number = spec.get("page_number", "")
    assets_path = spec.get("assets_path") or DEFAULT_ASSETS_DIR

    # A caller-supplied assets_path that doesn't actually exist used to
    # sail straight through - `spec.get("assets_path") or DEFAULT_ASSETS_DIR`
    # only falls back when the field is empty/omitted, not when it's a
    # non-empty but wrong path (e.g. the literal "./assets" example from
    # this module's own docstring, resolved against some other caller's
    # cwd). Real, disclosed bug: a live test's rendered cover slide and
    # corner logos came out missing entirely because of exactly this -
    # not because DEFAULT_ASSETS_DIR's own fallback was broken, but
    # because it was never reached. Fixed here, not by trusting the
    # caller more: fall back and say so, rather than rendering broken
    # <img> paths silently.
    if not os.path.isdir(assets_path):
        print(
            f"assets_path {assets_path!r} does not exist; falling back to the bundled "
            f"default ({DEFAULT_ASSETS_DIR!r}) instead of rendering with a broken image path.",
            file=sys.stderr,
        )
        assets_path = DEFAULT_ASSETS_DIR

    try:
        html = render_slide(slide_role, data, page_number, assets_path)
    except Exception as e:
        print(f"Render failed for slide_role {slide_role!r}: {e}", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(output_path)


if __name__ == "__main__":
    main()
