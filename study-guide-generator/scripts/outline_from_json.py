#!/usr/bin/env python3
"""
outline_from_json.py - generate the human-readable outline record FROM
the deck JSON.

WHY THIS FILE EXISTS
--------------------
Before this, the build stage authored the deck's content twice: once as
`outline.md` (Part A) and once as `pass2_raw.json` (Part C), by hand,
with a script whose entire job was to check that the two agreed. That
check is real and stays - a deck that says one thing in markdown and
another in JSON is exactly the failure it was written to catch - but
having the model produce both sides of it is the single largest source
of duplicated output tokens in the pipeline. In v2 the model writes
`deck_draft.json` only, and this script derives the markdown from it, so
the two cannot disagree by construction.

TWO DOWNSTREAM CONSUMERS PARSE THIS MARKDOWN
--------------------------------------------
`extract_deck_roles.py` and `validate_deck_outline.py` each run the same
regex over this file:

    ^[\\s*`>-]*(?:Slide\\s+)?(?:Template|role)\\s*:[\\s*`]*([a-z0-9_]+)

They take the sequence of matches, in order, as the deck's role
sequence. So this script must emit exactly one matching line per slide,
in deck order, and - just as important - must never emit a SECOND line
that happens to match. That is not hypothetical: a bullet reading
"Role: project lead" in a slide's own data matches the same pattern and
would inject a phantom slide into the sequence, failing
validate_deck_outline.py's check 1 with a message about deck_draft.json
that has nothing to do with what actually went wrong. `_deconflict()` below
guards every content line against that, and it is the reason this file
carries a copy of the regex at all.

The role tag is printed on its own `Template: <tag>` line, matching the
label the outline has used since the v2 rename.

WHAT THIS FILE IS AND IS NOT
----------------------------
It is a record for a human reader and the input to the deterministic
role check. It is NOT a round-trip format: `deck_tracked.json` is the
source of record, and nothing reconstructs a deck from this markdown.
Where the two pull in different directions - a nested cell structure
that would round-trip precisely but read as noise - this file favours
legibility.

Usage:
    python3 outline_from_json.py <deck_tracked.json> [--out outline.md]

Accepts either a tracked deck draft or `outline_validated.json`: both
are {subject, guide_title, guide_date, prepared_for, slides[]} and both
`--out` defaults to outline.md; the markdown is
only printed to stdout when `--out -` is given explicitly.

Prints a short JSON summary to stdout: slides written, roles in order,
and the output path.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from html_tables_to_md import html_to_markdown, looks_like_html  # noqa: E402

# Byte-identical to extract_deck_roles.py's own pattern. Kept as a local
# copy for the same reason that script and validate_deck_outline.py each
# keep one: no import dependency between them. Here it is used in
# reverse - not to find role lines, but to make sure no content line
# accidentally looks like one.
_SLIDE_ROLE_PATTERN = re.compile(
    r"^[\s*`>-]*(?:Slide\s+)?(?:Template|role)\s*:[\s*`]*([a-z0-9_]+)",
    re.IGNORECASE | re.MULTILINE,
)

# Prefixed to any content line that would otherwise be read as a role
# tag. A bullet character is not in the pattern's leading character class
# ([\s*`>-]), so one character is enough to defeat the match, and the
# line still reads as a bullet to a human.
_DECONFLICT_PREFIX = "\u2022 "


def _deconflict(text):
    """Stop a content line from being mistaken for a `Template:` line."""
    out = []
    for line in text.split("\n"):
        if not _SLIDE_ROLE_PATTERN.match(line):
            out.append(line)
            continue
        stripped = line.lstrip()
        indent = line[:len(line) - len(stripped)]
        if stripped.startswith("- "):
            # Swap the bullet marker rather than stacking a second one.
            out.append(indent + _DECONFLICT_PREFIX + stripped[2:])
        else:
            out.append(_DECONFLICT_PREFIX + line)
    return "\n".join(out)


def _label(key):
    return key.replace("_", " ").strip().capitalize()


def _scalar(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _md_table(headers, rows):
    """Build a markdown table. Every row is padded to the header width."""
    width = max([len(headers)] + [len(r) for r in rows]) if (headers or rows) else 0
    if width == 0:
        return ""
    headers = list(headers) + [""] * (width - len(headers))
    lines = [
        "| " + " | ".join(_cell(h) for h in headers) + " |",
        "|" + "|".join(["---"] * width) + "|",
    ]
    for row in rows:
        padded = list(row) + [""] * (width - len(row))
        lines.append("| " + " | ".join(_cell(c) for c in padded) + " |")
    return "\n".join(lines)


def _cell(value):
    if isinstance(value, dict):
        value = _flatten_cell(value)
    elif isinstance(value, list):
        value = "; ".join(_cell(v) for v in value)
    text = _scalar(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _flatten_cell(cell):
    """An comparison_matrix bulleted cell, flattened for a table cell."""
    bullets = cell.get("bullets")
    if isinstance(bullets, list):
        parts = []
        for b in bullets:
            if isinstance(b, dict):
                text = _scalar(b.get("text", ""))
                subs = b.get("sub_bullets") or []
                if subs:
                    text = text + " (" + "; ".join(_scalar(s) for s in subs) + ")"
                parts.append(text)
            else:
                parts.append(_scalar(b))
        return "; ".join(p for p in parts if p)
    return "; ".join(f"{k}: {_scalar(v)}" for k, v in cell.items())


def _bullets(items, indent=0):
    pad = " " * indent
    out = []
    for item in items or []:
        if isinstance(item, str) and looks_like_html(item):
            out.append(pad + "- " + html_to_markdown(item).replace("\n", " "))
        else:
            out.append(pad + "- " + _scalar(item))
    return "\n".join(out)


def _maybe_html(value):
    if isinstance(value, str) and looks_like_html(value):
        return html_to_markdown(value)
    return _scalar(value)


# ---------------------------------------------------------------------
# Generic renderer - the fallback for any shape without a role handler
# ---------------------------------------------------------------------

SKIP_KEYS = {"title", "key_message"}


def _render_generic(data, depth=0):
    blocks = []
    for key, value in data.items():
        if key in SKIP_KEYS:
            continue
        blocks.extend(_render_field(key, value, depth))
    return blocks


def _render_field(key, value, depth=0):
    label = _label(key)
    if value is None or value == "" or value == [] or value == {}:
        return []

    if isinstance(value, (str, int, float, bool)):
        rendered = _maybe_html(value)
        if "\n" in rendered or len(rendered) > 110:
            return [f"**{label}:**", rendered]
        return [f"**{label}:** {rendered}"]

    if isinstance(value, list):
        if all(isinstance(v, (str, int, float, bool)) for v in value):
            return [f"**{label}:**", _bullets(value)]
        if all(isinstance(v, list) for v in value):
            return [f"**{label}:**", _md_table([], value)]
        blocks = [f"**{label}:**"]
        for i, item in enumerate(value, 1):
            if isinstance(item, dict):
                name = item.get("title") or item.get("section_title") or item.get("section_name") or item.get("label") or item.get("name")
                heading = f"*{label} {i}" + (f" - {_scalar(name)}*" if name else "*")
                blocks.append(heading)
                blocks.extend(_render_generic(item, depth + 1) if name else _render_dict_all(item, depth + 1))
            else:
                blocks.append(f"- {_scalar(item)}")
        return blocks

    if isinstance(value, dict):
        blocks = [f"**{label}:**"]
        blocks.extend(_render_dict_all(value, depth + 1))
        return blocks

    return [f"**{label}:** {_scalar(value)}"]


def _render_dict_all(data, depth=0):
    blocks = []
    for key, value in data.items():
        blocks.extend(_render_field(key, value, depth))
    return blocks


# ---------------------------------------------------------------------
# Role handlers
# ---------------------------------------------------------------------

def _h_cover(d):
    blocks = []
    for key in ("subtitle", "course_line", "scope_line", "prepared_for_line", "date_line"):
        if d.get(key):
            blocks.append(f"**{_label(key)}:** {_scalar(d[key])}")
    return blocks


def _h_section_divider(d):
    blocks = []
    if d.get("section_number") is not None:
        blocks.append(f"**Section number:** {_scalar(d['section_number'])}")
    if d.get("eyebrow"):
        blocks.append(f"**Eyebrow:** {_scalar(d['eyebrow'])}")
    if d.get("lede"):
        blocks.append(f"**Lede:** {_scalar(d['lede'])}")
    return blocks


def _h_content_grid(d):
    blocks = []
    for i, quad in enumerate(d.get("quads") or [], 1):
        blocks.append(f"*Zone {i} - {_scalar(quad.get('title', ''))} "
                      f"({_scalar(quad.get('content_type', ''))})*")
        if quad.get("bullets"):
            blocks.append(_bullets(quad["bullets"]))
        if quad.get("table_rows") or quad.get("table_headers"):
            rows = [list(r) for r in (quad.get("table_rows") or [])]
            if quad.get("table_total"):
                rows.append(list(quad["table_total"]))
            blocks.append(_md_table(quad.get("table_headers") or [], rows))
    if d.get("footnote"):
        blocks.append(f"**Footnote:** {_scalar(d['footnote'])}")
    return blocks


def _h_comparison_matrix(d):
    columns = d.get("columns") or []
    rows = []
    for group in d.get("groups") or []:
        label = group.get("group_label")
        if label:
            rows.append([f"**{_scalar(label)}**"] + [""] * (len(columns) - 1))
        for row in group.get("rows") or []:
            rows.append(list(row.get("cells") or []))
    blocks = [_md_table(columns, rows)]
    if d.get("footnotes"):
        blocks.append("**Footnotes:**")
        blocks.append(_bullets(d["footnotes"]))
    return blocks


def _h_multi_panel(d):
    blocks = []
    for section in d.get("sections") or []:
        blocks.append(f"*Panel - {_scalar(section.get('section_title', ''))} "
                      f"({_scalar(section.get('content_type', ''))})*")
        if section.get("bullets"):
            blocks.append(_bullets(section["bullets"]))
        if section.get("table_rows") or section.get("table_headers"):
            rows = [list(r) for r in (section.get("table_rows") or [])]
            if section.get("table_total"):
                rows.append(list(section["table_total"]))
            blocks.append(_md_table(section.get("table_headers") or [], rows))
        if section.get("chart_bars"):
            prefix = _scalar(section.get("chart_unit_prefix", ""))
            suffix = _scalar(section.get("chart_unit_suffix", ""))
            rows = [[_scalar(b.get("label")), f"{prefix}{_scalar(b.get('value'))}{suffix}"]
                    for b in section["chart_bars"]]
            blocks.append(_md_table(["Bar", "Value"], rows))
        if section.get("image_placeholder_text"):
            blocks.append(f"Image placeholder: {_scalar(section['image_placeholder_text'])}")
    if d.get("footnote"):
        blocks.append(f"**Footnote:** {_scalar(d['footnote'])}")
    return blocks


def _h_topic_checklist(d):
    blocks = []
    for topic in d.get("topics") or []:
        head = f"*{_scalar(topic.get('topic_name', ''))}*"
        if topic.get("status"):
            head += f"  [{_scalar(topic['status'])}]"
        blocks.append(head)
        blocks.append(_bullets(topic.get("bullets") or []))
    if d.get("footnote"):
        blocks.append(f"**Footnote:** {_scalar(d['footnote'])}")
    return blocks


def _h_mastery_heatmap(d):
    blocks = []
    meta = []
    for key in ("course_name", "assessment_name", "assessment_date"):
        if d.get(key):
            meta.append(f"**{_label(key)}:** {_scalar(d[key])}")
    last = d.get("last_review") or {}
    if last:
        meta.append(
            "**Last review:** by " + _scalar(last.get("reviewed_by", "")) +
            ", last reviewed " + _scalar(last.get("last_reviewed", "")) +
            ", next review " + _scalar(last.get("next_review", ""))
        )
    blocks.extend(meta)

    headers = ["#", "Topic", "Source", "Status",
               "First covered", "Last reviewed", "Next review", "Resource"]
    rows = []
    for t in d.get("topics") or []:
        rows.append([
            _scalar(t.get("id", "")), _scalar(t.get("topic", "")),
            _scalar(t.get("source", "")), _scalar(t.get("status", "")),
            _scalar(t.get("first_covered", "")), _scalar(t.get("last_reviewed", "")),
            _scalar(t.get("next_review", "")), _scalar(t.get("resource", "")),
        ])
    blocks.append(_md_table(headers, rows))
    if d.get("footnote"):
        blocks.append(f"**Footnote:** {_scalar(d['footnote'])}")
    return blocks


def _h_process_flow(d):
    blocks = []
    for section in d.get("sections") or []:
        blocks.append(f"*{_scalar(section.get('section_title', ''))}*")
        blocks.append(f"Start: {_scalar(section.get('start_label', ''))}")
        steps = []
        for i, step in enumerate(section.get("steps") or [], start=1):
            marker = (chr(64 + i) if section.get("marker_style") == "alpha" else str(i))
            line = f"{marker}. {_scalar(step.get('name', ''))}"
            if step.get("kind") and step["kind"] != "step":
                line += f"  [{_scalar(step['kind'])}]"
            if step.get("detail"):
                line += f" - {_scalar(step['detail'])}"
            steps.append(line)
        blocks.append("\n".join(steps))
        blocks.append(f"End: {_scalar(section.get('end_label', ''))}")
    if d.get("footnotes"):
        blocks.append("**Footnotes:**")
        blocks.append(_bullets(d["footnotes"]))
    return blocks


def _h_quiz_recap(d):
    columns = d.get("columns") or []
    rows = [[_scalar(r.get("question"))] + [_scalar(v) for v in (r.get("values") or [])]
            for r in d.get("rows") or []]
    if d.get("summary_label") and d.get("summary_values"):
        rows.append([f"**{_scalar(d.get('summary_label', ''))}**"] +
                    [_scalar(v) for v in (d.get("summary_values") or [])])
    blocks = [_md_table(["Question"] + [_scalar(c) for c in columns], rows)]
    if d.get("footnotes"):
        blocks.append("**Footnotes:**")
        blocks.append(_bullets(d["footnotes"]))
    return blocks


def _h_flashcard_grid(d):
    headers = ["#", "Front", "Back", "Source", "Tag"]
    rows = []
    n = 0
    for section in d.get("sections") or []:
        if section.get("section_title"):
            rows.append(["", f"**{_scalar(section['section_title'])}**", "", "", ""])
        for card in section.get("cards") or []:
            n += 1
            rows.append([
                str(n), _scalar(card.get("front", "")), _scalar(card.get("back", "")),
                _scalar(card.get("source", "")), _scalar(card.get("tag", "")),
            ])
    blocks = [_md_table(headers, rows)]
    if d.get("footnotes"):
        blocks.append("**Footnotes:**")
        blocks.append(_bullets(d["footnotes"]))
    return blocks


def _h_contents(d):
    blocks = [html_to_markdown(d.get("content_html", ""))]
    if d.get("footnote"):
        blocks.append(f"**Footnote:** {_scalar(d['footnote'])}")
    return [b for b in blocks if b]


def _h_two_section(d):
    blocks = []
    if d.get("left_title") or d.get("left_content"):
        blocks.append(f"*Left - {_scalar(d.get('left_title', ''))}*")
        blocks.append(html_to_markdown(d.get("left_content", "")))
    if d.get("right_title") or d.get("right_content") or d.get("right_image"):
        blocks.append(f"*Right - {_scalar(d.get('right_title', ''))}*")
        if d.get("right_content"):
            blocks.append(html_to_markdown(d["right_content"]))
        image = d.get("right_image") or {}
        if image:
            blocks.append("Image zone: " + _scalar(
                image.get("placeholder") or image.get("alt") or image.get("src") or "unspecified"
            ))
    if d.get("footnote"):
        blocks.append(f"**Footnote:** {_scalar(d['footnote'])}")
    return [b for b in blocks if b]


def _h_freeform(d):
    blocks = [html_to_markdown(d.get("content_html", ""))]
    if d.get("footnote"):
        blocks.append(f"**Footnote:** {_scalar(d['footnote'])}")
    return [b for b in blocks if b]


ROLE_HANDLERS = {
    "cover": _h_cover,
    "section_divider": _h_section_divider,
    "content_grid": _h_content_grid,
    "comparison_matrix": _h_comparison_matrix,
    "multi_panel": _h_multi_panel,
    "topic_checklist": _h_topic_checklist,
    "mastery_heatmap": _h_mastery_heatmap,
    "process_flow": _h_process_flow,
    "quiz_recap": _h_quiz_recap,
    "flashcard_grid": _h_flashcard_grid,
    "contents": _h_contents,
    "two_section": _h_two_section,
    "freeform": _h_freeform,
}


def render_data(role, data):
    """Render one slide's `data` as legible markdown blocks."""
    if not isinstance(data, dict):
        return [_scalar(data)]
    handler = ROLE_HANDLERS.get(role)
    blocks = handler(data) if handler else _render_generic(data)
    return [b for b in blocks if b and b.strip()]


def slide_title(slide):
    """The slide's own title, from its data. Falls back to the role name."""
    data = slide.get("data") or {}
    for key in ("title", "section_title", "name"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _scalar(slide.get("slide_role", "untitled")).replace("_", " ")


def render_slide(slide):
    role = _scalar(slide.get("slide_role", ""))
    number = slide.get("slide_number")
    title = slide_title(slide)

    parts = [f"SLIDE {number} - {role.upper()} - {title.upper()}", ""]
    parts.append(f"Template: {role}")
    parts.append("")
    parts.append(f"Track: {_scalar(slide.get('track') or 'unassigned')}"
                 + (" (escalated)" if slide.get("escalated") else ""))
    parts.append("")

    key_message = slide.get("key_message") or (slide.get("data") or {}).get("key_message")
    parts.append(f"Key message: {_scalar(key_message) if key_message else 'Not stated in the deck draft.'}")
    parts.append("")

    parts.append("Content zones:")
    parts.append("")
    blocks = render_data(role, slide.get("data") or {})
    parts.append("\n\n".join(blocks) if blocks else "No content in this slide's data.")
    parts.append("")

    parts.append("Flags:")
    flags = slide.get("flags") or []
    parts.append(_bullets(flags) if flags else "- None.")

    body = "\n".join(parts)
    # Guard every line except the deliberate `Template:` line.
    head, _, rest = body.partition(f"Template: {role}")
    return head + f"Template: {role}" + _deconflict(rest)


def render_outline(deck):
    slides = deck.get("slides") or []
    project = _scalar(deck.get("subject") or "Untitled subject")

    header = [f"# {project} - Study Guide Outline", ""]
    if deck.get("guide_date"):
        header.append(f"Date: {_scalar(deck['guide_date'])}")
    if deck.get("prepared_for"):
        header.append(f"Prepared for: {_scalar(deck['prepared_for'])}")
    header.append(f"Slides: {len(slides)}")
    header.append("")
    header.append("This file is generated from the deck JSON by "
                  "scripts/outline_from_json.py. Edit the deck JSON and "
                  "regenerate; do not hand-edit this file.")
    header.append("")

    chunks = ["\n".join(header)]
    for slide in slides:
        chunks.append("---")
        chunks.append(render_slide(slide))
    return "\n\n".join(chunks).rstrip() + "\n"


USAGE = "Usage: python3 outline_from_json.py <deck_tracked.json> [--out outline.md]\n"


def main():
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(USAGE)
        return 0 if args else 2

    out_path = "outline.md"
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print("--out needs a path", file=sys.stderr)
            return 2
        out_path = args[i + 1]
        del args[i:i + 2]

    if len(args) != 1:
        print(USAGE, file=sys.stderr)
        return 2

    try:
        with open(args[0], "r", encoding="utf-8") as f:
            deck = json.load(f)
    except OSError as e:
        print(f"Could not read {args[0]}: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"{args[0]} is not valid JSON: {e}", file=sys.stderr)
        return 1

    if not isinstance(deck, dict) or not isinstance(deck.get("slides"), list):
        print(
            f"{args[0]} is not a deck object - expected "
            "{{subject, guide_date, slides: [...]}}.",
            file=sys.stderr,
        )
        return 1

    slides = deck["slides"]
    if not slides:
        print(f"{args[0]} has no slides; nothing to write.", file=sys.stderr)
        return 1

    markdown = render_outline(deck)

    # A self-check on the one property downstream depends on: exactly one
    # role line per slide, in deck order. Failing here is far cheaper than
    # failing inside validate_deck_outline.py with a message pointing at
    # deck_draft.json.
    found = [m.group(1).lower() for m in _SLIDE_ROLE_PATTERN.finditer(markdown)]
    expected = [_scalar(s.get("slide_role", "")).lower() for s in slides]
    if found != expected:
        print(
            "Generated outline does not carry exactly one Template line per "
            "slide in deck order - refusing to write it:",
            file=sys.stderr,
        )
        print(f"  deck roles:      {expected}", file=sys.stderr)
        print(f"  extracted roles: {found}", file=sys.stderr)
        return 1

    if out_path == "-":
        sys.stdout.write(markdown)
        return 0

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(json.dumps({
        "out": out_path,
        "slides": len(slides),
        "roles": expected,
        "chars": len(markdown),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
