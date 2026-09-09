# Study guide table theme — tokens

Colours, fonts and sizes matching this project's slide templates and
`build_pptx.py`. Use these as a starting preset when building tables in the
same house style; treat them as defaults to override, not hard requirements
- match whatever palette the actual deck uses.

## Colours

| Role | Hex | Used for |
|---|---|---|
| Header fill | `9E6474` | Header row background (dusty rose) |
| Header text | `FFFFFF` | Header row text, white and bold |
| Band fill | `FBF2F3` | Alternating body row band |
| Body fill | `FDF8F8` | The other body rows |
| Body text | `5F4E53` | Regular row text |
| Emphasis text | `9E6474` | Bold text on a summary or group-label row |
| Accent | `D98F98` | Keylines and the rule under a summary row |
| Muted | `B29AA0` | Footnotes beneath the table |
| Hairline | `F0DFE2` | Cell borders where a border is used at all |

## Typography

- **Font family:** Montserrat throughout, with Calibri as the fallback for
  machines that do not have it.
- **Header row:** 9pt, bold.
- **Body rows:** 9pt, regular. Bold on a group-label or summary row.
- **Footnotes beneath the table:** 8pt, muted.

These are larger than a dense financial table would use, deliberately. A
study guide is read at arm's length and often printed; a student squinting
at a 7pt definition will simply skip it.

## Layout

- **Header row height:** ~0.28in. **Data rows:** ~0.28in, which is loose
  enough that a wrapped two-line cell does not shove the table off the
  canvas.
- **Banding is alternating**, unlike a financial table where banding marks
  subtotals. A study table's rows are peers - topics, questions, cases - so
  even/odd striping is the correct read and helps the eye track across a
  wide row.
- **A group-label row** (the `comparison_matrix` role uses these) spans the
  label column with bold emphasis text and no data in the remaining columns.
- **Text columns left-aligned; short status or date columns left-aligned
  too.** Numeric columns right-align only where the numbers are meant to be
  compared down the column, which in this deck is rare.
- **No vertical gridlines.** Horizontal hairlines only where rows would
  otherwise be hard to track; the banding usually does that job already.
- **Missing values show as an en dash** (`–`), never blank and never "N/A".
  A blank cell reads as an oversight; an en dash reads as a deliberate
  "nothing here", which is what a study guide needs to say when a topic has
  not been reviewed yet.

## Applying this to a different palette

Keep the *structure* - header fill with white bold text, alternating body
band, bold emphasis on group and summary rows, muted footnotes, no vertical
rules - and swap in the actual header, accent and text colours. The
structure is what makes it read as a clean study table; the hex values above
are one instance of it.
