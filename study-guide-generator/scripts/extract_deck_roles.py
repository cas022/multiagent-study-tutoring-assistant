#!/usr/bin/env python3
"""
extract_deck_roles.py - the deterministic role extractor for this plugin.
It replaced a v1 script of a similar name that no longer ships here.

Deterministic regex extraction of "Template: <tag>" values out of a
Pass-1 markdown outline, in the order they appear. The older "Slide role:"
spelling is still accepted, so an outline approved before that rename
still parses. This is the same
Role extraction is a regex check run as real code, never re-derived by
the model, against the 13-role taxonomy in deck_schemas.ROLE_MODEL_MAP.

REQUIRED_SLIDE_ROLES is the minimum a study guide deck has to carry to be
usable: a cover, so the guide says what course and what assessment it is
for, and at least one content_grid, which is the role that states what the
unit actually covers. Everything else is optional by design - a flashcard
deck, a single worked example, and a full exam review are all legitimate
shapes for this deck, and requiring a review tracker or a quiz recap on
every one of them would be a policy this pipeline has no basis for.

Usage:
    python3 extract_deck_roles.py <path-to-approved-outline.md>

Prints JSON to stdout:
    {
      "slide_roles": ["cover", "contents", ...],
      "missing_required": []
    }

The missing_required check is PASSIVE by design - do not block or
auto-revise on a non-empty missing_required list; surface it to the
student at the outline checkpoint instead.
"""
import json
import re
import sys

REQUIRED_SLIDE_ROLES = ["cover", "content_grid"]

# [\s*`]* absorbs markdown noise between the label and the tag (e.g. a bold
# marker right after the colon) - carried forward unchanged from the v1
# script, since the same markdown-noise problem applies here too.
#
# Anchored to start-of-line (MULTILINE) because the label is now the bare
# word "Template", which is common enough to appear mid-sentence in a
# bullet; the old "Slide role:" label was distinctive enough that an
# unanchored match was safe, this one is not. The leading [\s*`>-]* class
# still allows indentation, list markers, blockquotes, and bold markers
# ahead of the label. "Slide role:" and "Slide Template:" both still match.
_SLIDE_ROLE_PATTERN = re.compile(
    r"^[\s*`>-]*(?:Slide\s+)?(?:Template|role)\s*:[\s*`]*([a-z0-9_]+)",
    re.IGNORECASE | re.MULTILINE,
)


def extract_slide_roles(markdown_text: str) -> list:
    return [m.group(1).lower() for m in _SLIDE_ROLE_PATTERN.finditer(markdown_text or "")]


def missing_required_roles(present_roles: list) -> list:
    present = set(present_roles)
    return [r for r in REQUIRED_SLIDE_ROLES if r not in present]


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python3 extract_deck_roles.py <outline.md>")
        sys.exit(0 if len(sys.argv) > 1 else 2)

    if len(sys.argv) != 2:
        print("Usage: python3 extract_deck_roles.py <path-to-outline.md>", file=sys.stderr)
        sys.exit(2)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        text = f.read()

    roles = extract_slide_roles(text)
    missing = missing_required_roles(roles)

    print(json.dumps({"slide_roles": roles, "missing_required": missing}, indent=2))


if __name__ == "__main__":
    main()
