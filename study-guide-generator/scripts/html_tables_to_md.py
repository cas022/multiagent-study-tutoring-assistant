#!/usr/bin/env python3
"""
html_tables_to_md.py - convert an HTML fragment to markdown, standard
library only.

WHY THIS FILE EXISTS
--------------------
Several role models in deck_schemas.py carry raw HTML rather than
structured fields: `contents.content_html`,
`freeform.content_html`, `two_section.left_content` /
`right_content`. Both downstream consumers of a validated deck - the
outline record (outline_from_json.py) and the fit report
(outline_from_json.py) - need that content as markdown, because a
markdown table is what the brief's own schema specifies for every
data-dense zone.

In the run this refactor is fixing, the agent improvised exactly this
converter mid-build, discovered it was silently dropping table rows,
patched it, and regenerated the outline. A dropped row in an outline
is a dropped row in the finished deck, and nothing downstream can
notice it. So this is a real module with real tests rather than an
inline regex: run `python3 html_tables_to_md.py --self-test` to execute
them.

WHAT IT HANDLES
---------------
- `<table>`: thead/tbody/tfoot, `<th>` as the header row, colspan AND
  rowspan resolved onto a proper grid, empty cells preserved, and a
  table with no thead still emitted with every body row intact.
- Nested tables: markdown has no nested-table syntax, so an inner table
  is rendered compactly inside its cell (cells joined by " / ", rows by
  " ; "). Compact, but never dropped - that is the property the tests
  assert.
- `<ul>`, `<ol>`, `<li>`, including nesting.
- `<p>`, `<br>`, `<strong>`/`<b>`, `<em>`/`<i>`, `<code>`, `<a>`,
  `<h1>`..`<h6>`, `<blockquote>`, `<hr>`.
- Entities (`&amp;`, `&nbsp;`, `&#8364;`) are decoded by HTMLParser
  itself with convert_charrefs=True.

Malformed markup is handled the way a browser does: an unclosed `<p>`,
`<li>`, `<tr>` or `<td>` is closed implicitly by the next one, and a
stray end tag with no matching open tag is ignored rather than
unwinding the stack.

Usage:
    python3 html_tables_to_md.py <file.html> [--out out.md]
    cat fragment.html | python3 html_tables_to_md.py -
    python3 html_tables_to_md.py --self-test

As a module:
    from html_tables_to_md import html_to_markdown
    md = html_to_markdown("<table>...</table>")
"""
import re
import sys
from html.parser import HTMLParser

__all__ = ["html_to_markdown", "looks_like_html"]

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "div", "dl", "fieldset",
    "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "main", "nav", "ol", "p", "pre", "section", "table",
    "ul",
}

# Opening one of these tags implicitly closes any of the tags in its set
# that is currently open at the top of the stack. This is the subset of
# HTML's optional-end-tag rules that actually matters for the markup this
# plugin sees.
IMPLIED_CLOSE = {
    "li": {"li"},
    "p": {"p"},
    "tr": {"tr", "td", "th"},
    "td": {"td", "th"},
    "th": {"td", "th"},
    "thead": {"td", "th", "tr"},
    "tbody": {"td", "th", "tr", "thead"},
    "tfoot": {"td", "th", "tr", "tbody"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
}

_WS = re.compile(r"[ \t\r\f\v\u00a0]+")


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []

    def __repr__(self):  # pragma: no cover - debugging aid only
        return f"<_Node {self.tag} children={len(self.children)}>"


class _TreeBuilder(HTMLParser):
    """Builds a forgiving element tree. Text nodes are plain strings."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("[document]")
        self.stack = [self.root]

    def _implied_close(self, tag):
        closes = IMPLIED_CLOSE.get(tag)
        if not closes:
            return
        while len(self.stack) > 1 and self.stack[-1].tag in closes:
            self.stack.pop()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self._implied_close(tag)
        node = _Node(tag, {k.lower(): (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        self._implied_close(tag)
        node = _Node(tag, {k.lower(): (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return
        # Stray end tag with nothing open to match it: ignore it rather
        # than unwinding the stack, which is what a browser does and what
        # keeps a single typo from swallowing the rest of the document.

    def handle_data(self, data):
        self.stack[-1].children.append(data)


# ---------------------------------------------------------------------
# Inline rendering
# ---------------------------------------------------------------------

def _clean_text(text, cell_mode=False):
    text = _WS.sub(" ", text)
    if cell_mode:
        text = text.replace("\n", " ")
    return text


def _render_inline(node, cell_mode=False):
    """Render an inline element (or a text string) to markdown text."""
    if isinstance(node, str):
        return _clean_text(node, cell_mode)

    tag = node.tag
    if tag == "br":
        return " " if cell_mode else "\n"
    if tag in VOID_TAGS:
        if tag == "img":
            alt = node.attrs.get("alt", "").strip()
            return f"[image: {alt}]" if alt else ""
        return ""

    inner = "".join(_render_inline(c, cell_mode) for c in node.children)

    if tag in ("strong", "b"):
        return f"**{inner.strip()}**" if inner.strip() else inner
    if tag in ("em", "i"):
        return f"*{inner.strip()}*" if inner.strip() else inner
    if tag in ("code", "tt", "kbd"):
        return f"`{inner.strip()}`" if inner.strip() else inner
    if tag == "a":
        href = node.attrs.get("href", "").strip()
        label = inner.strip()
        if href and label and not href.startswith("#"):
            return f"[{label}]({href})"
        return inner
    return inner


# ---------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------

def _collect_rows(table):
    """Return [(is_header, tr_node)] for THIS table only.

    A nested table's rows belong to the cell that holds them, never to
    the outer table, so this walk stops at any descendant `table`.
    """
    rows = []

    def walk(node, in_head):
        for child in node.children:
            if isinstance(child, str):
                continue
            if child.tag == "table":
                continue
            if child.tag == "tr":
                rows.append((in_head, child))
            elif child.tag == "thead":
                walk(child, True)
            elif child.tag in ("tbody", "tfoot"):
                walk(child, False)
            else:
                walk(child, in_head)

    walk(table, False)
    return rows


def _row_cells(tr):
    return [c for c in tr.children if not isinstance(c, str) and c.tag in ("td", "th")]


def _span(cell, name):
    raw = (cell.attrs.get(name) or "1").strip()
    try:
        value = int(raw)
    except ValueError:
        return 1
    return value if value >= 1 else 1


def _render_cell(cell):
    """Cell content as a single line of markdown-safe text."""
    parts = []
    for child in cell.children:
        if isinstance(child, str):
            parts.append(_clean_text(child, cell_mode=True))
        elif child.tag == "table":
            parts.append(_compact_table(child))
        elif child.tag in ("ul", "ol"):
            parts.append(_compact_list(child))
        elif child.tag in BLOCK_TAGS:
            parts.append(_render_cell(child))
        else:
            parts.append(_render_inline(child, cell_mode=True))
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return _escape_cell(text)


def _escape_cell(text):
    return _WS.sub(" ", text.replace("|", "\\|").replace("\n", " ")).strip()


def _compact_list(node):
    items = [
        _render_cell(c)
        for c in node.children
        if not isinstance(c, str) and c.tag == "li"
    ]
    return "; ".join(i for i in items if i)


def _compact_table(table):
    """A nested table, inlined into its parent cell.

    Markdown has no nested-table syntax. Compacting is the only option
    that keeps every row, and keeping every row is the requirement.
    """
    grid, _ = _build_grid(table)
    rows = [" / ".join(c for c in row) for row in grid]
    rows = [r.strip(" /") if r.strip(" /") else r for r in rows]
    return " ; ".join(r for r in rows if r.strip())


def _build_grid(table):
    """Resolve colspan and rowspan onto a rectangular grid of strings.

    Returns (rows, header_row_count_from_thead).
    """
    collected = _collect_rows(table)
    occupied = {}
    grid = []
    head_rows = 0

    for r, (is_head, tr) in enumerate(collected):
        if is_head:
            head_rows += 1
        row = {}
        col = 0
        for cell in _row_cells(tr):
            while (r, col) in occupied:
                col += 1
            colspan = _span(cell, "colspan")
            rowspan = _span(cell, "rowspan")
            text = _render_cell(cell)
            row[col] = text
            for dr in range(rowspan):
                for dc in range(colspan):
                    occupied[(r + dr, col + dc)] = True
                    if dr > 0 or dc > 0:
                        # A spanned-over position renders as an empty
                        # cell: the value stays in the anchor cell and
                        # the columns stay aligned.
                        pass
            col += colspan
        grid.append(row)

    ncols = 0
    for r, row in enumerate(grid):
        for c in row:
            ncols = max(ncols, c + 1)
    for (r, c) in occupied:
        if r < len(grid):
            ncols = max(ncols, c + 1)

    dense = []
    for row in grid:
        dense.append([row.get(c, "") for c in range(ncols)])
    return dense, head_rows


def _render_table(table):
    dense, head_rows = _build_grid(table)
    if not dense:
        return ""
    ncols = len(dense[0])

    if head_rows:
        header = dense[0]
        body = dense[1:]
    else:
        first_tr = _collect_rows(table)[0][1]
        cells = _row_cells(first_tr)
        all_th = bool(cells) and all(c.tag == "th" for c in cells)
        if all_th:
            header = dense[0]
            body = dense[1:]
        else:
            # No thead and no th row: emit a blank header rather than
            # promoting a data row into one. Markdown needs a header
            # row; inventing labels for it would be inventing content,
            # and promoting row 1 would drop it from the body.
            header = [""] * ncols
            body = dense

    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * ncols) + "|",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------

def _render_list(node, depth=0):
    ordered = node.tag == "ol"
    try:
        start = int((node.attrs.get("start") or "1").strip())
    except ValueError:
        start = 1

    lines = []
    index = start
    for child in node.children:
        if isinstance(child, str) or child.tag != "li":
            continue
        marker = f"{index}. " if ordered else "- "
        index += 1
        pad = " " * (len(marker) + 2 * depth)
        indent = " " * (2 * depth)

        own_inline = []
        nested = []  # (already_indented, markdown)
        for c in child.children:
            if isinstance(c, str):
                own_inline.append(_clean_text(c))
            elif c.tag in ("ul", "ol"):
                # _render_list indents its own items at depth + 1.
                nested.append((True, _render_list(c, depth + 1)))
            elif c.tag == "table":
                nested.append((False, _render_table(c)))
            elif c.tag in BLOCK_TAGS:
                own_inline.append(" ".join(_render_blocks(c, depth)))
            else:
                own_inline.append(_render_inline(c))

        text = _WS.sub(" ", "".join(own_inline)).strip()
        lines.append(indent + marker + text)
        for already_indented, block in nested:
            if not block:
                continue
            if already_indented:
                lines.append(block)
            else:
                lines.append("\n".join(pad + ln for ln in block.split("\n")))
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------

def _render_blocks(node, depth=0):
    """Render a container's children into a list of markdown blocks."""
    blocks = []
    inline = []

    def flush():
        text = _WS.sub(" ", "".join(inline)).strip()
        inline.clear()
        if text:
            blocks.append(text)

    for child in node.children:
        if isinstance(child, str):
            inline.append(_clean_text(child))
            continue
        tag = child.tag
        if tag in ("script", "style"):
            continue
        if tag == "table":
            flush()
            rendered = _render_table(child)
            if rendered:
                blocks.append(rendered)
        elif tag in ("ul", "ol"):
            flush()
            rendered = _render_list(child, depth)
            if rendered:
                blocks.append(rendered)
        elif re.fullmatch(r"h[1-6]", tag):
            flush()
            level = int(tag[1])
            text = _WS.sub(" ", _render_inline(child)).strip()
            if text:
                blocks.append("#" * level + " " + text)
        elif tag == "hr":
            flush()
            blocks.append("---")
        elif tag == "blockquote":
            flush()
            inner = _render_blocks(child, depth)
            for block in inner:
                blocks.append("\n".join("> " + ln for ln in block.split("\n")))
        elif tag == "pre":
            flush()
            text = "".join(_render_inline(c) for c in child.children)
            blocks.append(text.strip())
        elif tag in BLOCK_TAGS:
            flush()
            blocks.extend(_render_blocks(child, depth))
        elif tag == "br":
            inline.append("\n")
        else:
            inline.append(_render_inline(child))

    flush()
    return blocks


def html_to_markdown(html_text):
    """Convert an HTML fragment to markdown. Returns a plain string."""
    if not html_text:
        return ""
    builder = _TreeBuilder()
    builder.feed(html_text)
    builder.close()
    blocks = _render_blocks(builder.root)
    return "\n\n".join(b for b in blocks if b.strip()).strip()


_HTML_HINT = re.compile(
    r"<\s*(?:table|tr|td|th|ul|ol|li|p|br|div|span|strong|b|em|i|h[1-6])\b[^>]*>",
    re.IGNORECASE,
)


def looks_like_html(value):
    """True when a string field is carrying markup rather than plain text."""
    return isinstance(value, str) and bool(_HTML_HINT.search(value))


# ---------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------

def _self_test():
    import unittest

    class TestHtmlTablesToMd(unittest.TestCase):
        def test_simple_table_with_thead(self):
            md = html_to_markdown(
                "<table><thead><tr><th>Use</th><th>USD mm</th></tr></thead>"
                "<tbody><tr><td>Acquisition price</td><td>25.0</td></tr>"
                "<tr><td>Total uses</td><td>33.7</td></tr></tbody></table>"
            )
            lines = md.split("\n")
            self.assertEqual(lines[0], "| Use | USD mm |")
            self.assertEqual(lines[1], "|---|---|")
            self.assertEqual(lines[2], "| Acquisition price | 25.0 |")
            self.assertEqual(lines[3], "| Total uses | 33.7 |")
            self.assertEqual(len(lines), 4)

        def test_table_with_no_thead_keeps_every_row(self):
            md = html_to_markdown(
                "<table><tr><td>a</td><td>1</td></tr>"
                "<tr><td>b</td><td>2</td></tr>"
                "<tr><td>c</td><td>3</td></tr></table>"
            )
            lines = md.split("\n")
            # Blank header plus separator plus three body rows: nothing
            # was promoted out of the body and nothing was dropped.
            self.assertEqual(lines[0], "|  |  |")
            self.assertEqual(lines[1], "|---|---|")
            self.assertEqual(len(lines), 5)
            for token in ("a", "b", "c", "1", "2", "3"):
                self.assertIn(token, md)

        def test_th_first_row_without_thead_is_the_header(self):
            md = html_to_markdown(
                "<table><tr><th>Metric</th><th>Value</th></tr>"
                "<tr><td>Geometric multiplicity</td><td>1</td></tr></table>"
            )
            lines = md.split("\n")
            self.assertEqual(lines[0], "| Metric | Value |")
            self.assertEqual(len(lines), 3)

        def test_colspan_expands_and_keeps_alignment(self):
            md = html_to_markdown(
                "<table><tr><th colspan='2'>Sources</th><th>Total</th></tr>"
                "<tr><td>Senior debt</td><td>70%</td><td>23.6</td></tr></table>"
            )
            lines = md.split("\n")
            self.assertEqual(lines[0], "| Sources |  | Total |")
            self.assertEqual(lines[1], "|---|---|---|")
            self.assertEqual(lines[2], "| Senior debt | 70% | 23.6 |")

        def test_rowspan_keeps_columns_aligned(self):
            md = html_to_markdown(
                "<table>"
                "<tr><td rowspan='2'>Senior</td><td>LLCR</td><td>1.4x</td></tr>"
                "<tr><td>Rate</td><td>6.1%</td></tr>"
                "<tr><td>Mezz</td><td>Term</td><td>5 years</td></tr>"
                "</table>"
            )
            body = [ln for ln in md.split("\n") if ln.startswith("|")][2:]
            self.assertEqual(len(body), 3)
            self.assertEqual(body[0], "| Senior | LLCR | 1.4x |")
            self.assertEqual(body[1], "|  | Rate | 6.1% |")
            self.assertEqual(body[2], "| Mezz | Term | 5 years |")

        def test_empty_cells_are_preserved(self):
            md = html_to_markdown(
                "<table><tr><th>A</th><th>B</th><th>C</th></tr>"
                "<tr><td></td><td>x</td><td></td></tr></table>"
            )
            self.assertIn("|  | x |  |", md)

        def test_nested_table_drops_no_row(self):
            md = html_to_markdown(
                "<table><thead><tr><th>Zone</th><th>Detail</th></tr></thead>"
                "<tbody><tr><td>Sources</td><td>"
                "<table><tr><td>Senior</td><td>23.6</td></tr>"
                "<tr><td>Mezzanine</td><td>10.1</td></tr>"
                "<tr><td>Equity</td><td>0.0</td></tr></table>"
                "</td></tr></tbody></table>"
            )
            for token in ("Senior", "23.6", "Mezzanine", "10.1", "Equity", "0.0"):
                self.assertIn(token, md)
            # The outer table still has exactly one body row.
            self.assertEqual(len([ln for ln in md.split("\n") if ln.startswith("|")]), 3)

        def test_nested_table_rows_are_not_stolen_by_the_outer_table(self):
            md = html_to_markdown(
                "<table><tr><td>outer</td><td>"
                "<table><tr><td>inner1</td></tr><tr><td>inner2</td></tr></table>"
                "</td></tr></table>"
            )
            rows = [ln for ln in md.split("\n") if ln.startswith("|")]
            self.assertEqual(len(rows), 3)  # blank header, separator, one body row
            self.assertIn("inner1", rows[2])
            self.assertIn("inner2", rows[2])

        def test_entities_are_decoded(self):
            md = html_to_markdown(
                "<p>Costs &amp; fees &lt;5%&gt; &nbsp;&#8364;10.0mm</p>"
            )
            self.assertIn("Costs & fees", md)
            self.assertIn("<5%>", md)
            self.assertIn("\u20ac10.0mm", md)

        def test_pipe_in_cell_is_escaped(self):
            md = html_to_markdown("<table><tr><td>a|b</td><td>c</td></tr></table>")
            self.assertIn("a\\|b", md)

        def test_lists_and_nesting(self):
            md = html_to_markdown(
                "<ul><li>First</li><li>Second<ul><li>Nested</li></ul></li></ul>"
            )
            self.assertIn("- First", md)
            self.assertIn("- Second", md)
            self.assertIn("- Nested", md)

        def test_ordered_list_numbers(self):
            md = html_to_markdown("<ol><li>One</li><li>Two</li><li>Three</li></ol>")
            self.assertIn("1. One", md)
            self.assertIn("2. Two", md)
            self.assertIn("3. Three", md)

        def test_ordered_list_with_lettered_sublist_keeps_every_item(self):
            md = html_to_markdown(
                "<ol class='agenda'><li><strong>What this unit covers</strong> "
                "Authorization to engage advisors.</li>"
                "<li><strong>Worked example</strong> The 3x3 case is worked in lecture 8."
                "<ol class='sub'><li>Sub one</li><li>Sub two</li></ol></li></ol>"
            )
            for token in ("What this unit covers", "Worked example", "Sub one", "Sub two"):
                self.assertIn(token, md)

        def test_inline_formatting(self):
            md = html_to_markdown(
                "<p>A <strong>bold</strong> and <em>italic</em> and <b>b</b> and <i>i</i>.</p>"
            )
            self.assertIn("**bold**", md)
            self.assertIn("*italic*", md)
            self.assertIn("**b**", md)
            self.assertIn("*i*", md)

        def test_br_and_paragraphs(self):
            md = html_to_markdown("<p>line one<br>line two</p><p>second para</p>")
            self.assertIn("line one", md)
            self.assertIn("line two", md)
            self.assertIn("second para", md)
            self.assertIn("\n\n", md)

        def test_headings(self):
            md = html_to_markdown("<h2>Sources and uses</h2><h4>Detail</h4>")
            self.assertIn("## Sources and uses", md)
            self.assertIn("#### Detail", md)

        def test_unclosed_tags_do_not_lose_content(self):
            md = html_to_markdown(
                "<table><tr><td>a<td>b<tr><td>c<td>d</table><p>after"
            )
            for token in ("a", "b", "c", "d", "after"):
                self.assertIn(token, md)
            rows = [ln for ln in md.split("\n") if ln.startswith("|")]
            self.assertEqual(len(rows), 4)  # blank header, separator, two body rows

        def test_stray_end_tag_is_ignored(self):
            md = html_to_markdown("</div><p>content</p></span>")
            self.assertIn("content", md)

        def test_table_inside_div_is_found(self):
            md = html_to_markdown(
                "<div class='zone'><h3>Zone</h3>"
                "<table><tr><th>H</th></tr><tr><td>v</td></tr></table></div>"
            )
            self.assertIn("### Zone", md)
            self.assertIn("| H |", md)
            self.assertIn("| v |", md)

        def test_row_count_never_shrinks_on_a_wide_table(self):
            rows = "".join(f"<tr><td>r{i}</td><td>{i}</td></tr>" for i in range(40))
            md = html_to_markdown(f"<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody>{rows}</tbody></table>")
            body = [ln for ln in md.split("\n") if ln.startswith("|")][2:]
            self.assertEqual(len(body), 40)
            for i in range(40):
                self.assertIn(f"r{i}", md)

        def test_empty_input(self):
            self.assertEqual(html_to_markdown(""), "")
            self.assertEqual(html_to_markdown(None), "")

        def test_plain_text_passthrough(self):
            self.assertEqual(html_to_markdown("just words"), "just words")

        def test_looks_like_html(self):
            self.assertTrue(looks_like_html("<p>x</p>"))
            self.assertTrue(looks_like_html("<table><tr><td>1</td></tr></table>"))
            self.assertFalse(looks_like_html("5 < 6 and 7 > 2"))
            self.assertFalse(looks_like_html(""))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestHtmlTablesToMd)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


USAGE = (
    "Usage:\n"
    "  python3 html_tables_to_md.py <file.html> [--out out.md]\n"
    "  cat fragment.html | python3 html_tables_to_md.py -\n"
    "  python3 html_tables_to_md.py --self-test\n"
)


def main():
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(USAGE)
        return 0 if args else 2

    if "--self-test" in args:
        return _self_test()

    out_path = None
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

    if args[0] == "-":
        html_text = sys.stdin.read()
    else:
        try:
            with open(args[0], "r", encoding="utf-8") as f:
                html_text = f.read()
        except OSError as e:
            print(f"Could not read {args[0]}: {e}", file=sys.stderr)
            return 1

    markdown = html_to_markdown(html_text)

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(markdown + "\n")
        import json
        print(json.dumps({
            "out": out_path,
            "chars_in": len(html_text),
            "chars_out": len(markdown),
        }))
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
