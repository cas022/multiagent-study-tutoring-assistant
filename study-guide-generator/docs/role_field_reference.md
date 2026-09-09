# Slide role field reference

**Generated file. Do not hand-edit.** Regenerate with:

```
python3 scripts/deck_schemas.py --markdown > docs/role_field_reference.md
```

Every field list, type and required flag below is read out of the Pydantic
models in `scripts/deck_schemas.py` at generation time, so this document
cannot drift from what the pipeline actually validates against. Editing it
by hand would only make it lie until the next regeneration.

This file exists so that authoring a deck needs no exploratory reading. It
carries, per slide role, everything that used to require opening
`deck_schemas.py` plus the role's template: the canonical `slide_role` tag,
the role's backing template, its full field list, the
practical length limit on every list-shaped field, and one realistic
`data` example that validates against the model.

## How to read this

- **Required** fields have no default and must be present. **Optional**
  fields may be omitted entirely; do not pass an explicit `null` where you
  mean "absent", because several templates use Jinja's `default()` filter,
  which substitutes for an undefined variable but not for a real `None`.
- **Length limits are not validated.** A list longer than the limit shown
  passes the model, then gets measured by `verify_render.py`, which shrinks
  the slide and eventually raises a BLOCKING flag. The limits are here so a
  deck is authored at a workable length rather than discovered to be over
  at the gate.
- Nested models are expanded inline under the field that uses them.


## Roles at a glance

| `slide_role` | Template | Data model |
|---|---|---|
| `cover` | `templates/cover.html` | `CoverData` |
| `section_divider` | `templates/section-divider.html` | `SectionDividerData` |
| `content_grid` | `templates/content-grid.html` | `ContentGridData` |
| `comparison_matrix` | `templates/comparison-matrix.html` | `ComparisonMatrixData` |
| `multi_panel` | `templates/multi-panel.html` | `MultiPanelData` |
| `topic_checklist` | `templates/topic-checklist.html` | `TopicChecklistData` |
| `mastery_heatmap` | `templates/mastery-heatmap.html` | `MasteryHeatmapData` |
| `process_flow` | `templates/process-flow.html` | `ProcessFlowData` |
| `quiz_recap` | `templates/quiz-recap.html` | `QuizRecapData` |
| `flashcard_grid` | `templates/flashcard-grid.html` | `FlashcardGridData` |
| `contents` | `templates/contents.html` | `ContentsData` |
| `two_section` | `templates/two-section.html` | `TwoSectionData` |
| `freeform` | `templates/freeform.html` | `FreeformData` |

---

## `cover`

- **`slide_role` tag:** `cover`
- **Template:** `templates/cover.html`
- **Data model:** `CoverData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `subtitle` | `str` | required |  |
| `course_line` | `str` | required |  |
| `scope_line` | `str` | required |  |
| `prepared_for_line` | `str` | required |  |
| `date_line` | `str` | required |  |

### Example `data`

```json
{
  "title": "Eigenvalues and Diagonalization",
  "subtitle": "Midterm 2 Review Guide",
  "course_line": "Course: Linear Algebra",
  "scope_line": "Scope: Lectures 6 to 9, textbook chapter 5",
  "prepared_for_line": "Prepared for: Midterm 2",
  "date_line": "04 March 2026"
}
```

---

## `section_divider`

- **`slide_role` tag:** `section_divider`
- **Template:** `templates/section-divider.html`
- **Data model:** `SectionDividerData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `section_number` | `int` | required |  |
| `eyebrow` | `str` | required |  |
| `title` | `str` | required |  |
| `lede` | `Optional[str]` | optional | `null` |

### Example `data`

```json
{
  "section_number": 2,
  "eyebrow": "Section 2",
  "title": "Diagonalization",
  "lede": "When a matrix is diagonalizable, and what to do when it is not."
}
```

---

## `content_grid`

- **`slide_role` tag:** `content_grid`
- **Template:** `templates/content-grid.html`
- **Data model:** `ContentGridData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `key_message` | `str` | required |  |
| `quads` | `List[ContentGridQuad]` | required |  |
| `footnote` | `Optional[str]` | optional | `null` |

### Nested models

**`ContentGridQuad`**

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `content_type` | `Literal['bullets', 'table', 'definitions']` | required |  |
| `bullets` | `Optional[List[str]]` | optional | `null` |
| `table_headers` | `Optional[List[str]]` | optional | `null` |
| `table_rows` | `Optional[List[List[str]]]` | optional | `null` |
| `table_total` | `Optional[List[str]]` | optional | `null` |
| `definitions` | `Optional[List[DefinitionPair]]` | optional | `null` |

**`DefinitionPair`**

| Field | Type | Required | Default |
|---|---|---|---|
| `term` | `str` | required |  |
| `meaning` | `str` | required |  |

### Practical length limits

- **`quads`** - Exactly 4. The grid is a fixed 2x2; fewer quads render but leave visible gaps.
- **`quads[].bullets`** - 5 to 6 single-line bullets per quad (13px type, 1.5 line-height, ~180px of quad body). 3 to 4 if they wrap.
- **`quads[].table_rows`** - 5 to 6 rows per quad including the header (12px type, ~26px per row).
- **`quads[].definitions`** - 4 to 5 term/meaning pairs per quad. A meaning longer than about 90 characters wraps to a second line and costs a pair.
- **`footnote`** - One line. The lane is capped at 74px, which is about 5 lines at 10px, but the layout reads best at 1 to 2.

### Example `data`

```json
{
  "title": "What This Unit Covers",
  "key_message": "Four ideas, and every exam question is a combination of them.",
  "quads": [
    {
      "title": "Core definitions",
      "content_type": "definitions",
      "definitions": [
        {
          "term": "Eigenvector",
          "meaning": "A nonzero v with Av = lambda v"
        },
        {
          "term": "Eigenvalue",
          "meaning": "The scalar lambda in that relation"
        },
        {
          "term": "Characteristic polynomial",
          "meaning": "det(A - lambda I)"
        },
        {
          "term": "Algebraic multiplicity",
          "meaning": "Multiplicity of lambda as a root"
        }
      ]
    },
    {
      "title": "What you must be able to do",
      "content_type": "bullets",
      "bullets": [
        "Compute the characteristic polynomial of a 2x2 and 3x3",
        "Find eigenvalues and a basis for each eigenspace",
        "Decide whether a given matrix is diagonalizable",
        "Write A = PDP^-1 and use it to compute A^k"
      ]
    },
    {
      "title": "Where each topic is covered",
      "content_type": "table",
      "table_headers": [
        "Topic",
        "Lecture",
        "Reading"
      ],
      "table_rows": [
        [
          "Characteristic polynomial",
          "L6",
          "5.1"
        ],
        [
          "Eigenspaces",
          "L7",
          "5.1 to 5.2"
        ],
        [
          "Diagonalization",
          "L8",
          "5.3"
        ],
        [
          "Symmetric case",
          "L9",
          "5.5"
        ]
      ]
    },
    {
      "title": "Common traps",
      "content_type": "bullets",
      "bullets": [
        "Forgetting that eigenvectors must be nonzero",
        "Assuming distinct eigenvalues are necessary, not just sufficient",
        "Mixing up algebraic and geometric multiplicity",
        "Dropping the order of P and D in A = PDP^-1"
      ]
    }
  ],
  "footnote": "Lecture references are to the Winter 2026 offering."
}
```

---

## `comparison_matrix`

- **`slide_role` tag:** `comparison_matrix`
- **Template:** `templates/comparison-matrix.html`
- **Data model:** `ComparisonMatrixData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `key_message` | `str` | required |  |
| `columns` | `List[str]` | required |  |
| `column_widths` | `Optional[List[float]]` | optional | `null` |
| `show_letter_header` | `bool` | optional | `false` |
| `groups` | `List[ComparisonGroup]` | required |  |
| `footnotes` | `Optional[List[str]]` | optional | `null` |

### Nested models

**`ComparisonGroup`**

| Field | Type | Required | Default |
|---|---|---|---|
| `group_label` | `Optional[str]` | optional | `null` |
| `rows` | `List[ComparisonRow]` | required |  |

**`ComparisonRow`**

| Field | Type | Required | Default |
|---|---|---|---|
| `cells` | `List[Union[str, ComparisonCell]]` | required |  |

**`ComparisonCell`**

| Field | Type | Required | Default |
|---|---|---|---|
| `bullets` | `List[ComparisonSubBullet]` | required |  |

**`ComparisonSubBullet`**

| Field | Type | Required | Default |
|---|---|---|---|
| `text` | `str` | required |  |
| `sub_bullets` | `Optional[List[str]]` | optional | `null` |

### Practical length limits

- **`columns`** - 2 to 6. Column widths are proportional shares; 4 to 5 is the usual shape. The first column is the thing being compared, the rest are the dimensions of comparison.
- **`column_widths`** - Must be the same length as `columns`, or it is ignored and equal widths are used.
- **`groups[].rows`** - About 15 single-line rows at the 12px ceiling, up to about 24 at the 8px floor. The template solves type size against a 480px budget less the footnote lane, then verify_render.py measures the result.
- **`groups[].rows[].cells`** - One cell per entry in `columns`, always.
- **`footnotes`** - Up to 8 to 10 short notes. The lane is capped at 130px and sets itself in 2 columns from 3 notes and 3 columns from 6.

### Example `data`

```json
{
  "title": "Diagonalizable or Not",
  "key_message": "Geometric multiplicity is the only test that always decides it.",
  "columns": [
    "Case",
    "Characteristic polynomial",
    "Geometric multiplicity",
    "Diagonalizable?"
  ],
  "groups": [
    {
      "group_label": "Distinct eigenvalues",
      "rows": [
        {
          "cells": [
            "n distinct roots",
            "n simple roots",
            "1 for each",
            "Always"
          ]
        }
      ]
    },
    {
      "group_label": "Repeated eigenvalues",
      "rows": [
        {
          "cells": [
            "Repeated root, full eigenspace",
            "Root of multiplicity k",
            "Equals k",
            "Yes"
          ]
        },
        {
          "cells": [
            "Repeated root, deficient eigenspace",
            "Root of multiplicity k",
            "Less than k",
            "No"
          ]
        }
      ]
    }
  ],
  "footnotes": [
    "Distinct eigenvalues are sufficient but not necessary for diagonalizability."
  ]
}
```

---

## `multi_panel`

- **`slide_role` tag:** `multi_panel`
- **Template:** `templates/multi-panel.html`
- **Data model:** `MultiPanelData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `key_message` | `str` | required |  |
| `sections` | `List[MultiPanelSection]` | required |  |
| `footnote` | `Optional[str]` | optional | `null` |

### Nested models

**`MultiPanelSection`**

| Field | Type | Required | Default |
|---|---|---|---|
| `section_title` | `str` | required |  |
| `content_type` | `Literal['table', 'bullets', 'chart', 'image-placeholder']` | required |  |
| `table_headers` | `Optional[List[str]]` | optional | `null` |
| `table_rows` | `Optional[List[List[str]]]` | optional | `null` |
| `table_total` | `Optional[List[str]]` | optional | `null` |
| `bullets` | `Optional[List[str]]` | optional | `null` |
| `chart_bars` | `Optional[List[MultiPanelChartBar]]` | optional | `null` |
| `chart_unit_prefix` | `Optional[str]` | optional | `null` |
| `chart_unit_suffix` | `Optional[str]` | optional | `null` |
| `image_placeholder_text` | `Optional[str]` | optional | `null` |

**`MultiPanelChartBar`**

| Field | Type | Required | Default |
|---|---|---|---|
| `label` | `str` | required |  |
| `value` | `float` | required |  |

### Practical length limits

- **`sections`** - 2, 3, 4 or 6. The grid solves for these counts; 5 renders with a gap.
- **`sections[].bullets`** - 4 to 6 single-line bullets per panel at a 3-panel layout, fewer as panel count rises.
- **`sections[].table_rows`** - 6 to 8 rows including the header at 2 panels, 4 to 5 at 4 panels.
- **`sections[].chart_bars`** - 3 to 7 bars. Labels longer than about 14 characters truncate.

### Example `data`

```json
{
  "title": "Worked Example: A 3x3 Case",
  "key_message": "The whole method in one pass, with the arithmetic shown.",
  "sections": [
    {
      "section_title": "The matrix",
      "content_type": "bullets",
      "bullets": [
        "A has rows (2,1,0), (0,2,0), (0,0,3)",
        "Upper triangular, so eigenvalues read off the diagonal"
      ]
    },
    {
      "section_title": "Eigenvalues",
      "content_type": "table",
      "table_headers": [
        "lambda",
        "Algebraic mult.",
        "Geometric mult."
      ],
      "table_rows": [
        [
          "2",
          "2",
          "1"
        ],
        [
          "3",
          "1",
          "1"
        ]
      ]
    },
    {
      "section_title": "Conclusion",
      "content_type": "bullets",
      "bullets": [
        "Geometric multiplicity of lambda = 2 is 1, less than 2",
        "So A is not diagonalizable"
      ]
    }
  ],
  "footnote": "Worked in lecture 8; the same matrix appears on problem set 4."
}
```

---

## `topic_checklist`

- **`slide_role` tag:** `topic_checklist`
- **Template:** `templates/topic-checklist.html`
- **Data model:** `TopicChecklistData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `key_message` | `str` | required |  |
| `topics` | `List[ChecklistTopic]` | required |  |
| `footnote` | `Optional[str]` | optional | `null` |

### Nested models

**`ChecklistTopic`**

| Field | Type | Required | Default |
|---|---|---|---|
| `topic_name` | `str` | required |  |
| `bullets` | `List[str]` | required |  |
| `status` | `Optional[Literal['Not started', 'In progress', 'Confident']]` | optional | `null` |

### Practical length limits

- **`topics`** - 3 to 6 reads best. The colour palette cycles past 6, so more still renders but stops being visually distinct.
- **`topics[].bullets`** - 3 to 5 per topic. These are what the student has to be able to do, not a summary of the topic.
- **`footnote`** - One to two lines.

### Example `data`

```json
{
  "title": "Readiness Check",
  "key_message": "Four things to be able to do without notes before the exam.",
  "topics": [
    {
      "topic_name": "Characteristic polynomial",
      "status": "Confident",
      "bullets": [
        "Expand det(A - lambda I) for a 3x3 without error",
        "Factor the resulting cubic"
      ]
    },
    {
      "topic_name": "Eigenspaces",
      "status": "In progress",
      "bullets": [
        "Solve (A - lambda I)v = 0 and give a basis",
        "State the geometric multiplicity from that basis"
      ]
    },
    {
      "topic_name": "Diagonalization",
      "status": "In progress",
      "bullets": [
        "Assemble P and D in the right order",
        "Use A = PDP^-1 to compute a high power"
      ]
    },
    {
      "topic_name": "Symmetric matrices",
      "status": "Not started",
      "bullets": [
        "State the spectral theorem",
        "Orthogonally diagonalize a symmetric 2x2"
      ]
    }
  ],
  "footnote": "Status reflects the self-check on 02 March."
}
```

---

## `mastery_heatmap`

- **`slide_role` tag:** `mastery_heatmap`
- **Template:** `templates/mastery-heatmap.html`
- **Data model:** `MasteryHeatmapData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `key_message` | `str` | required |  |
| `course_name` | `str` | required |  |
| `assessment_name` | `str` | required |  |
| `assessment_date` | `str` | required |  |
| `last_review` | `MasteryLastReview` | required |  |
| `topics` | `List[MasteryTopic]` | optional | `[]` |
| `footnote` | `Optional[str]` | optional | `null` |

### Nested models

**`MasteryLastReview`**

| Field | Type | Required | Default |
|---|---|---|---|
| `reviewed_by` | `str` | required |  |
| `last_reviewed` | `str` | required |  |
| `next_review` | `str` | required |  |

**`MasteryTopic`**

| Field | Type | Required | Default |
|---|---|---|---|
| `topic` | `str` | required |  |
| `id` | `Union[str, int]` | required |  |
| `source` | `str` | required |  |
| `status` | `Literal['Not started', 'Reviewing', 'Practiced', 'Confident', 'Struggling']` | required |  |
| `first_covered` | `str` | required |  |
| `last_reviewed` | `str` | required |  |
| `next_review` | `str` | required |  |
| `resource` | `str` | required |  |

### Practical length limits

- **`topics`** - 8 to 14 rows. Past 14 the row height compresses below comfortable reading; verify_render.py measures and flags it.
- **`topics[].topic`** - About 40 characters before it wraps.
- **`topics[].resource`** - Short - a lecture number, a chapter, a problem set. Not a sentence.
- **`footnote`** - One line.

### Example `data`

```json
{
  "title": "Topic Mastery and Review Schedule",
  "key_message": "Two topics are behind schedule with nine days to the exam.",
  "course_name": "Linear Algebra",
  "assessment_name": "Midterm 2",
  "assessment_date": "13 March 2026",
  "last_review": {
    "reviewed_by": "Self-check",
    "last_reviewed": "02 March 2026",
    "next_review": "06 March 2026"
  },
  "topics": [
    {
      "topic": "Characteristic polynomial",
      "id": 1,
      "source": "L6",
      "status": "Confident",
      "first_covered": "10 Feb 2026",
      "last_reviewed": "01 Mar 2026",
      "next_review": "08 Mar 2026",
      "resource": "5.1"
    },
    {
      "topic": "Eigenspaces and bases",
      "id": 2,
      "source": "L7",
      "status": "Practiced",
      "first_covered": "12 Feb 2026",
      "last_reviewed": "02 Mar 2026",
      "next_review": "06 Mar 2026",
      "resource": "5.1-5.2"
    },
    {
      "topic": "Diagonalization criterion",
      "id": 3,
      "source": "L8",
      "status": "Struggling",
      "first_covered": "17 Feb 2026",
      "last_reviewed": "28 Feb 2026",
      "next_review": "05 Mar 2026",
      "resource": "PS4"
    },
    {
      "topic": "Spectral theorem",
      "id": 4,
      "source": "L9",
      "status": "Not started",
      "first_covered": "19 Feb 2026",
      "last_reviewed": "-",
      "next_review": "05 Mar 2026",
      "resource": "5.5"
    }
  ],
  "footnote": "Review dates follow the spacing the syllabus recommends."
}
```

---

## `process_flow`

- **`slide_role` tag:** `process_flow`
- **Template:** `templates/process-flow.html`
- **Data model:** `ProcessFlowData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `key_message` | `str` | required |  |
| `sections` | `List[ProcessSection]` | required |  |
| `footnotes` | `Optional[List[str]]` | optional | `null` |

### Nested models

**`ProcessSection`**

| Field | Type | Required | Default |
|---|---|---|---|
| `section_title` | `str` | required |  |
| `start_label` | `str` | required |  |
| `end_label` | `str` | required |  |
| `marker_style` | `Literal['numeric', 'alpha']` | optional | `"numeric"` |
| `steps` | `List[ProcessStep]` | required |  |

**`ProcessStep`**

| Field | Type | Required | Default |
|---|---|---|---|
| `name` | `str` | required |  |
| `detail` | `Optional[str]` | optional | `null` |
| `kind` | `Literal['given', 'step', 'result']` | optional | `"step"` |
| `starts_subsection` | `bool` | optional | `false` |

### Practical length limits

- **`sections`** - 1 or 2. Two sections halve the vertical budget for each.
- **`sections[].steps`** - 5 to 9 steps in a single-section layout, 4 to 6 each when there are two. A derivation longer than that belongs on two slides.
- **`sections[].steps[].detail`** - One short line - the justification for the step, not a re-derivation of it.
- **`footnotes`** - Up to 4.

### Example `data`

```json
{
  "title": "Diagonalizing a Matrix, Step by Step",
  "key_message": "Five steps, and step 3 is where the method can fail.",
  "sections": [
    {
      "section_title": "From A to PDP^-1",
      "start_label": "Given A (n x n)",
      "end_label": "A = PDP^-1",
      "marker_style": "numeric",
      "steps": [
        {
          "name": "Form A - lambda I",
          "kind": "given",
          "detail": "Subtract lambda from each diagonal entry"
        },
        {
          "name": "Solve det(A - lambda I) = 0",
          "kind": "step",
          "detail": "Roots are the eigenvalues, with algebraic multiplicity"
        },
        {
          "name": "Find each eigenspace",
          "kind": "step",
          "detail": "Null space of (A - lambda I); its dimension is the geometric multiplicity"
        },
        {
          "name": "Check total dimension",
          "kind": "step",
          "detail": "If the eigenspace dimensions do not sum to n, stop: A is not diagonalizable"
        },
        {
          "name": "Assemble P and D",
          "kind": "result",
          "detail": "Eigenvectors as columns of P, eigenvalues in the matching order down D"
        }
      ]
    }
  ],
  "footnotes": [
    "Step 4 is the only place the method can fail.",
    "The order of columns in P must match the order of entries in D."
  ]
}
```

---

## `quiz_recap`

- **`slide_role` tag:** `quiz_recap`
- **Template:** `templates/quiz-recap.html`
- **Data model:** `QuizRecapData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `key_message` | `str` | required |  |
| `columns` | `List[str]` | required |  |
| `rows` | `List[QuizRow]` | required |  |
| `summary_label` | `Optional[str]` | optional | `null` |
| `summary_values` | `Optional[List[str]]` | optional | `null` |
| `footnotes` | `Optional[List[str]]` | optional | `null` |

### Nested models

**`QuizRow`**

| Field | Type | Required | Default |
|---|---|---|---|
| `question` | `str` | required |  |
| `values` | `List[str]` | required |  |

### Practical length limits

- **`columns`** - 2 to 4. These are the ANSWER columns only - the question column is rendered from `rows[].question` and is not listed here.
- **`rows`** - 6 to 10 at a 3-column layout. Long question text is the binding constraint, not row count.
- **`rows[].values`** - One entry per column, always.
- **`summary_values`** - Same length as `columns` when present.

### Example `data`

```json
{
  "title": "Practice Set 4 Recap",
  "key_message": "Both misses were the same error: multiplicity confusion.",
  "columns": [
    "Your answer",
    "Correct answer",
    "Covered in"
  ],
  "rows": [
    {
      "question": "Eigenvalues of the given 2x2",
      "values": [
        "1 and 4",
        "1 and 4",
        "L6"
      ]
    },
    {
      "question": "Is the repeated-root matrix diagonalizable?",
      "values": [
        "Yes",
        "No - geometric multiplicity is 1",
        "L8"
      ]
    },
    {
      "question": "Geometric multiplicity of lambda = 2",
      "values": [
        "2",
        "1",
        "L7"
      ]
    },
    {
      "question": "Compute A^5 by diagonalization",
      "values": [
        "Correct",
        "Correct",
        "L8"
      ]
    }
  ],
  "summary_label": "Score",
  "summary_values": [
    "2 of 4",
    "-",
    "-"
  ],
  "footnotes": [
    "Both misses trace to the same confusion between algebraic and geometric multiplicity."
  ]
}
```

---

## `flashcard_grid`

- **`slide_role` tag:** `flashcard_grid`
- **Template:** `templates/flashcard-grid.html`
- **Data model:** `FlashcardGridData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `key_message` | `str` | required |  |
| `sections` | `List[FlashcardSection]` | required |  |
| `footnotes` | `Optional[List[str]]` | optional | `null` |

### Nested models

**`FlashcardSection`**

| Field | Type | Required | Default |
|---|---|---|---|
| `section_title` | `Optional[str]` | optional | `null` |
| `cards` | `List[Flashcard]` | required |  |

**`Flashcard`**

| Field | Type | Required | Default |
|---|---|---|---|
| `front` | `str` | required |  |
| `back` | `str` | required |  |
| `source` | `Optional[str]` | optional | `null` |
| `tag` | `Optional[str]` | optional | `null` |

### Practical length limits

- **`sections`** - 1 to 3.
- **`sections[].cards`** - 6 to 9 cards in a single-section layout, 4 to 6 per section at 2 sections.
- **`sections[].cards[].front`** - A question or a term. Under about 60 characters.
- **`sections[].cards[].back`** - The answer. Under about 120 characters - a flashcard that needs a paragraph is a slide, not a card.

### Example `data`

```json
{
  "title": "Definitions to Know Cold",
  "key_message": "Exam questions assume these without restating them.",
  "sections": [
    {
      "section_title": "Core",
      "cards": [
        {
          "front": "Eigenvector",
          "back": "A nonzero vector v with Av = lambda v for some scalar lambda",
          "source": "L6",
          "tag": "definition"
        },
        {
          "front": "Characteristic polynomial",
          "back": "det(A - lambda I), whose roots are the eigenvalues",
          "source": "L6",
          "tag": "definition"
        },
        {
          "front": "Algebraic multiplicity",
          "back": "The multiplicity of lambda as a root of the characteristic polynomial",
          "source": "L7",
          "tag": "definition"
        },
        {
          "front": "Geometric multiplicity",
          "back": "The dimension of the eigenspace for lambda",
          "source": "L7",
          "tag": "definition"
        },
        {
          "front": "Diagonalizable",
          "back": "A = PDP^-1 for some invertible P and diagonal D",
          "source": "L8",
          "tag": "definition"
        },
        {
          "front": "Spectral theorem",
          "back": "Every real symmetric matrix is orthogonally diagonalizable",
          "source": "L9",
          "tag": "theorem"
        }
      ]
    }
  ],
  "footnotes": [
    "Wording follows the course's definitions, which differ slightly from the textbook's."
  ]
}
```

---

## `contents`

- **`slide_role` tag:** `contents`
- **Template:** `templates/contents.html`
- **Data model:** `ContentsData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `content_html` | `str` | required |  |
| `footnote` | `Optional[str]` | optional | `null` |

### Practical length limits

- **`content_html`** - Use only ol.agenda / ol.sub markup. About 10 top-level items, or 6 with sub-items.

### Example `data`

```json
{
  "title": "Contents",
  "content_html": "<ol class=\"agenda\"><li>What this unit covers</li><li>Diagonalization<ol class=\"sub\"><li>The criterion</li><li>Worked example</li></ol></li><li>Definitions to know</li><li>Practice recap</li></ol>",
  "footnote": "Nine days to the exam."
}
```

---

## `two_section`

- **`slide_role` tag:** `two_section`
- **Template:** `templates/two-section.html`
- **Data model:** `TwoSectionData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `key_message` | `str` | required |  |
| `left_title` | `str` | required |  |
| `right_title` | `str` | required |  |
| `left_content` | `str` | required |  |
| `right_content` | `Optional[str]` | optional | `null` |
| `right_image` | `Optional[TwoSectionImage]` | optional | `null` |
| `footnote` | `Optional[str]` | optional | `null` |

### Nested models

**`TwoSectionImage`**

| Field | Type | Required | Default |
|---|---|---|---|
| `src` | `Optional[str]` | optional | `null` |
| `alt` | `Optional[str]` | optional | `null` |
| `placeholder` | `Optional[str]` | optional | `null` |

### Practical length limits

- **`left_content`** - Raw HTML. About 300 words per side before the type drops below comfortable reading.
- **`right_content`** - Same budget as left. Omit to use `right_image` instead.

### Example `data`

```json
{
  "title": "Course Notation vs Textbook Notation",
  "key_message": "The course writes the eigenvalue equation the other way round; use the course's form.",
  "left_title": "As lectures write it",
  "right_title": "As the textbook writes it",
  "left_content": "<p>Av = <em>lambda</em> v, with eigenvalues indexed lambda_1 to lambda_n in the order they appear down D.</p>",
  "right_content": "<p>(A - lambda I)v = 0, with eigenvalues indexed by decreasing magnitude.</p>",
  "footnote": "Exams are graded against the lecture convention."
}
```

---

## `freeform`

- **`slide_role` tag:** `freeform`
- **Template:** `templates/freeform.html`
- **Data model:** `FreeformData`

### Fields

| Field | Type | Required | Default |
|---|---|---|---|
| `title` | `str` | required |  |
| `key_message` | `str` | required |  |
| `content_html` | `str` | required |  |
| `footnote` | `Optional[str]` | optional | `null` |

### Practical length limits

- **`content_html`** - single-col / two-col / three-col wrappers, per the template. This role exists for content the other twelve genuinely do not fit - reach for it last, not first.

### Example `data`

```json
{
  "title": "One-Page Summary",
  "key_message": "Everything above, compressed to what fits on a permitted note sheet.",
  "content_html": "<div class=\"two-col\"><div><h4>Method</h4><p>Characteristic polynomial, eigenspaces, dimension check, assemble.</p></div><div><h4>Failure case</h4><p>Geometric multiplicity below algebraic multiplicity for any eigenvalue.</p></div></div>",
  "footnote": "One page of notes is permitted for this exam."
}
```
