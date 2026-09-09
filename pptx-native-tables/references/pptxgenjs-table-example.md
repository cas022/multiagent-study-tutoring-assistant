# pptxgenjs worked example — one native table object

Reproduces the header / subtotal-band / total-row look from
`study-table-theme.md` using a single `addTable()` call. Adapt the
`rows` data and `THEME` colors; keep the structure (one call, 2D array,
per-cell `options`) — never fall back to a loop of `addShape` + `addText`.

```js
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5in — set before addSlide()
const slide = pres.addSlide();

const THEME = {
  headerFill: "142838",
  headerText: "FFFFFF",
  bandFill: "E5EBEE",
  boldText: "142838",
  bodyText: "808A92",
  font: "Montserrat",
};

// Each data row: [label, isSubtotal, [values...]]
const dataRows = [
  ["Net capacity (MW)", false, ["n/s","n/s","n/s","n/s","n/s","n/s","n/s","n/s"]],
  ["Revenues",          true,  ["16.8","266.8","400.4","408.3","416.3","424.6","432.9","441.5"]],
  ["COGS",              true,  ["(12.3)","(220.0)","(320.9)","(327.0)","(333.0)","(339.0)","(345.1)","(351.3)"]],
  // ...
];
const years = ["2028","2029","2030","2031","2032","2033","2034","2035"];

function cell(text, { bold = false, color = THEME.bodyText, fill = null, align = "right" } = {}) {
  const opts = { bold, color, align, fontFace: THEME.font, fontSize: 7.13, valign: "middle" };
  if (fill) opts.fill = { color: fill };
  return { text: String(text), options: opts };
}

const headerRow = [
  cell("#", { bold: true, color: THEME.headerText, fill: THEME.headerFill, align: "center", fontSize: 6.75 }),
  cell("ITEM", { bold: true, color: THEME.headerText, fill: THEME.headerFill, align: "left", fontSize: 6.75 }),
  ...years.map(y => cell(y, { bold: true, color: THEME.headerText, fill: THEME.headerFill, fontSize: 6.75 })),
];

const rows = [headerRow];
dataRows.forEach(([label, isSubtotal, values], i) => {
  const fill = isSubtotal ? THEME.bandFill : null;
  const color = isSubtotal ? THEME.boldText : THEME.bodyText;
  rows.push([
    cell(i + 1, { bold: isSubtotal, color, fill, align: "left" }),
    cell(label, { bold: isSubtotal, color, fill, align: "left" }),
    ...values.map(v => cell(v, { bold: isSubtotal, color, fill })),
  ]);
});

slide.addTable(rows, {
  x: 0.58, y: 1.85, w: 12.17,
  colW: [0.27, 3.04, 1.11, 1.11, 1.11, 1.11, 1.11, 1.11, 1.11, 1.11],
  rowH: [0.24, ...Array(dataRows.length).fill(0.142)],
  border: { type: "none" },     // no grid — this look has zero gridlines
  autoPage: false,
  margin: [1, 4, 1, 4],          // tight vertical margin (points) to match the source's dense row pitch
});

// A single rule under the final total row: pptxgenjs table cell `border`
// options are per-cell and per-edge, so target just the bottom edge of the
// last row's cells instead of turning the whole-table border back on.
const lastRowIdx = rows.length - 1;
rows[lastRowIdx].forEach(c => {
  c.options.border = [
    { type: "none" }, { type: "none" }, { type: "none" },
    { type: "solid", color: "142838", pt: 1 }, // bottom edge only
  ];
});
```

## Gotchas specific to pptxgenjs tables

- **`border: { type: "none" }` at the table level, then per-cell `border`
  arrays for the one row that needs a rule** — setting a table-level border
  and per-cell borders both is redundant; per-cell wins, so it's simplest to
  turn the table border fully off and add exactly the one rule you need.
- **`rowH` accepts an array** — use it to give the header a taller row than
  the tight data-row pitch, matching the source's 0.24in header vs 0.142in
  body rows.
- **`fill` is per-cell, not per-row** — the loop above applies it to every
  cell in a subtotal row rather than trying to set a "row fill" (pptxgenjs
  has no such option).
- **`margin` on `addTable` is in points, not inches** (unlike most other
  pptxgenjs options) — this is easy to miss and will make rows look
  needlessly tall if you pass an inch value by habit.
