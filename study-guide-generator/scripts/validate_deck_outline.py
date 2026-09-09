#!/usr/bin/env python3
"""
validate_deck_outline.py - the v2 validator for the per-slide deck model.
It replaced a v1 script, scripts/validate_outline.py, which is not in this
plugin: nothing here imports or runs it.

The build stage's validation step for the per-slide deck model, run as
real code instead of trusted from the model's own claim that its JSON is
well-formed. Call this at Part B step 4, after the draft outline
--apply` has assigned a `track` to every slide, AFTER the model has
written `deck_draft.json`, and AFTER the human has approved the outline
stage's markdown outline.

What this script checks, all as real code, none as model self-report:
    1. The deck JSON's slide_role sequence matches, in order and count,
       the deterministic "Template:" extraction from the APPROVED
       markdown (via extract_deck_roles.py's own regex, reimplemented
       here so this script has no import dependency on that one). A
       mismatch means `deck_draft.json` silently added, dropped, or
       reordered a slide relative to what the human actually approved -
       this is always a hard failure, never a warning to patch around.
    2. Every slide's `data` dict validates against its own role's model
       in deck_schemas.ROLE_MODEL_MAP - not a shared, one-size-fits-all
       schema. Missing plain-string fields are coerced to "TBD" first
       (recursing into nested models and lists of nested models), the
       same _coerce_missing_strings_to_tbd discipline the v1 script
       applied, adapted to run per-slide against whichever model that
       slide's role maps to instead of a single fixed model.
    3. Every slide's data validates against its role model  -
       job, run earlier at Part B step 1); it only refuses to validate a
       slide that shows up here without one.

Usage:
    python3 validate_deck_outline.py <approved-outline.md> <deck-tracked.json> [--out outline_validated.json]

With --out, the validated JSON is written to that path and stdout carries
only a compact summary: slide count, the slide roles in deck order, a
count per track, and the output path. This is the invocation the build
sequence uses - the validated deck is the next stage's input file, and
echoing the whole of it into the caller's context as well is several
thousand tokens spent on a payload that is already on disk.

Without --out, behaviour is exactly what it has always been: the full
validated StudyDeckOutline object is printed to stdout, so an existing
`validate_deck_outline.py a.md b.json > c.json` invocation keeps working
unchanged.

On success: exits 0.
On failure: prints a plain-language description of what failed to
stderr and exits 1 - this means `deck_draft.json` must be corrected and
the Part B chain re-run from the draft outline, not that the
caller should hand-patch the JSON and pass it through anyway.
"""
import json
import re
import sys

from pydantic import BaseModel, ValidationError
from typing import get_args, get_origin

from deck_schemas import StudyDeckOutline, Slide, ROLE_MODEL_MAP

# Kept byte-identical to extract_deck_roles.py's own pattern - this script
# deliberately has no import dependency on that one, so the two must be
# edited together. Anchored to start-of-line because the label is now the
# bare word "Template"; the older "Slide role:" spelling still matches.
_SLIDE_ROLE_PATTERN = re.compile(
    r"^[\s*`>-]*(?:Slide\s+)?(?:Template|role)\s*:[\s*`]*([a-z0-9_]+)",
    re.IGNORECASE | re.MULTILINE,
)

# Every failure below resolves the same way, and naming a stage that does
# not exist ("re-run Pass 2") leaves the agent with nowhere to go. There
# is exactly one model-authored artifact in the build stage, so the fix is
# always: correct deck_draft.json and run Part B again from the top.
_REDO = (
    "Correct deck_draft.json and re-run the Part B chain from "
    "the draft outline. Do not hand-patch the JSON this script "
    "was given and pass it through anyway."
)


def extract_slide_roles(markdown_text: str) -> list:
    return [m.group(1).lower() for m in _SLIDE_ROLE_PATTERN.finditer(markdown_text or "")]


def coerce_missing_strings_to_tbd(data, model_cls):
    if not isinstance(data, dict):
        return data

    for field_name, field_info in model_cls.model_fields.items():
        if field_name not in data:
            continue
        value = data[field_name]
        annotation = field_info.annotation

        if annotation is str and value is None:
            data[field_name] = "TBD"
            continue

        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if isinstance(value, dict):
                coerce_missing_strings_to_tbd(value, annotation)
            continue

        origin = get_origin(annotation)
        if origin is list:
            args = get_args(annotation)
            if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                if isinstance(value, list):
                    for item in value:
                        coerce_missing_strings_to_tbd(item, args[0])

    return data


_USAGE = (
    "Usage: python3 validate_deck_outline.py <approved-outline.md> "
    "<deck-tracked.json> [--out outline_validated.json]"
)


def main():
    args = sys.argv[1:]
    out_path = None

    if "--help" in args or "-h" in args:
        print(_USAGE)
        print(__doc__)
        sys.exit(0)

    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print("--out needs a path", file=sys.stderr)
            sys.exit(2)
        out_path = args[i + 1]
        del args[i:i + 2]

    if len(args) != 2:
        print(_USAGE, file=sys.stderr)
        sys.exit(2)

    with open(args[0], "r", encoding="utf-8") as f:
        approved_markdown = f.read()

    with open(args[1], "r", encoding="utf-8") as f:
        raw_json = f.read().strip()

    if raw_json.startswith("```"):
        raw_json = raw_json.split("\n", 1)[-1]
        raw_json = raw_json.rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as e:
        print(
            f"JSON parse error in the tracked deck: {e}\n"
            f"{_REDO}",
            file=sys.stderr,
        )
        sys.exit(1)

    slides = parsed.get("slides", [])

    # Check 1: slide_role sequence must match the approved markdown's own
    # deterministic extraction, exactly, in order and count.
    expected_roles = extract_slide_roles(approved_markdown)
    actual_roles = [s.get("slide_role") for s in slides]
    if actual_roles != expected_roles:
        print(
            "The deck's slide sequence does not match the approved outline's "
            "own \"Template:\" tags. " + _REDO,
            file=sys.stderr,
        )
        print(f"  approved markdown has: {expected_roles}", file=sys.stderr)
        print(f"  the tracked deck has:  {actual_roles}", file=sys.stderr)
        sys.exit(1)

    # Check 2: per-slide data validation against that role's own model.
    for slide in slides:
        role = slide.get("slide_role")
        model_cls = ROLE_MODEL_MAP.get(role)
        if model_cls is None:
            print(
                f"Slide {slide.get('slide_number')} has slide_role "
                f"{role!r}, which is not a recognized role in "
                f"deck_schemas.ROLE_MODEL_MAP. " + _REDO,
                file=sys.stderr,
            )
            sys.exit(1)

        data = slide.get("data")
        data = coerce_missing_strings_to_tbd(data, model_cls)
        slide["data"] = data

        try:
            model_cls.model_validate(data)
        except ValidationError as e:
            print(
                f"Slide {slide.get('slide_number')} ({role}) failed schema "
                f"validation against its own template's data shape. " + _REDO,
                file=sys.stderr,
            )
            print(str(e), file=sys.stderr)
            sys.exit(1)

    try:
        outline_validated = StudyDeckOutline.model_validate(parsed)
    except ValidationError as e:
        print(
            "The deck failed top-level schema validation. " + _REDO,
            file=sys.stderr,
        )
        print(str(e), file=sys.stderr)
        sys.exit(1)

    payload = outline_validated.model_dump_json(indent=2)

    if out_path is None:
        print(payload)
        return

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(payload + "\n")

    print(json.dumps({
        "output_path": out_path,
        "slide_count": len(outline_validated.slides),
        "roles_in_order": [s.slide_role for s in outline_validated.slides],
    }, indent=2))


if __name__ == "__main__":
    main()
