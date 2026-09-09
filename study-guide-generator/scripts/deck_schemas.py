# study-guide-generator/scripts/deck_schemas.py
#
# The active Pydantic model tree for this plugin, built against the 13 real
# template files bundled in templates/. This module is also the source of
# docs/role_field_reference.md, which is generated from it by
# `python3 deck_schemas.py --markdown` and must never be hand-edited.
#
# The model here is a DECK of slides, not one flat document. Each slide has
# a `slide_role` (one of the 13 keys in ROLE_MODEL_MAP below, one per real
# template) and a `data` dict that validates against that role's own model.
# The per-role models below are a field-for-field mirror of each template's
# actual Jinja variables, read directly from the template files in
# templates/. If a template's Jinja variables ever change, this file has
# drifted and needs to be re-derived from the template, not hand-patched to
# match old assumptions.
#
# Every slide renders through this pipeline. There is no second track and no
# external design step: `build` goes outline -> validate -> render -> HTML
# preview -> .pptx in one pass.

import json
import sys
import typing
from typing import List, Optional, Union, Literal, get_args, get_origin

from pydantic import BaseModel


# ─── cover.html ──────────────────────────────────────────────────────────
class CoverData(BaseModel):
    title: str
    subtitle: str
    course_line: str
    scope_line: str
    prepared_for_line: str
    date_line: str


# ─── section-divider.html ────────────────────────────────────────────────
class SectionDividerData(BaseModel):
    section_number: int
    eyebrow: str
    title: str
    lede: Optional[str] = None


# ─── content-grid.html ───────────────────────────────────────────────────
class DefinitionPair(BaseModel):
    term: str
    meaning: str


class ContentGridQuad(BaseModel):
    title: str
    content_type: Literal["bullets", "table", "definitions"]
    bullets: Optional[List[str]] = None
    table_headers: Optional[List[str]] = None
    table_rows: Optional[List[List[str]]] = None
    table_total: Optional[List[str]] = None
    definitions: Optional[List[DefinitionPair]] = None


class ContentGridData(BaseModel):
    title: str
    key_message: str
    quads: List[ContentGridQuad]
    footnote: Optional[str] = None


# ─── comparison-matrix.html ──────────────────────────────────────────────
class ComparisonSubBullet(BaseModel):
    text: str
    sub_bullets: Optional[List[str]] = None


class ComparisonCell(BaseModel):
    bullets: List[ComparisonSubBullet]


class ComparisonRow(BaseModel):
    cells: List[Union[str, ComparisonCell]]


class ComparisonGroup(BaseModel):
    group_label: Optional[str] = None
    rows: List[ComparisonRow]


class ComparisonMatrixData(BaseModel):
    title: str
    key_message: str
    columns: List[str]
    column_widths: Optional[List[float]] = None
    show_letter_header: bool = False
    groups: List[ComparisonGroup]
    footnotes: Optional[List[str]] = None


# ─── multi-panel.html ────────────────────────────────────────────────────
class MultiPanelChartBar(BaseModel):
    label: str
    value: float


class MultiPanelSection(BaseModel):
    section_title: str
    content_type: Literal["table", "bullets", "chart", "image-placeholder"]
    table_headers: Optional[List[str]] = None
    table_rows: Optional[List[List[str]]] = None
    table_total: Optional[List[str]] = None
    bullets: Optional[List[str]] = None
    chart_bars: Optional[List[MultiPanelChartBar]] = None
    chart_unit_prefix: Optional[str] = None
    chart_unit_suffix: Optional[str] = None
    image_placeholder_text: Optional[str] = None


class MultiPanelData(BaseModel):
    title: str
    key_message: str
    sections: List[MultiPanelSection]  # 2, 3, 4, or 6 is the documented range
    footnote: Optional[str] = None


# ─── topic-checklist.html ────────────────────────────────────────────────
class ChecklistTopic(BaseModel):
    topic_name: str
    bullets: List[str]
    status: Optional[Literal["Not started", "In progress", "Confident"]] = None


class TopicChecklistData(BaseModel):
    title: str
    key_message: str
    topics: List[ChecklistTopic]  # palette cycles past 6
    footnote: Optional[str] = None


# ─── mastery-heatmap.html ────────────────────────────────────────────────
class MasteryLastReview(BaseModel):
    reviewed_by: str
    last_reviewed: str
    next_review: str


class MasteryTopic(BaseModel):
    topic: str
    id: Union[str, int]
    source: str  # which lecture, chapter or problem set this comes from
    status: Literal["Not started", "Reviewing", "Practiced", "Confident", "Struggling"]
    first_covered: str
    last_reviewed: str
    next_review: str
    resource: str


class MasteryHeatmapData(BaseModel):
    title: str
    key_message: str
    course_name: str
    assessment_name: str
    assessment_date: str
    last_review: MasteryLastReview
    topics: List[MasteryTopic] = []  # template shows one TBD row if empty
    footnote: Optional[str] = None


# ─── process-flow.html ───────────────────────────────────────────────────
class ProcessStep(BaseModel):
    name: str
    detail: Optional[str] = None
    kind: Literal["given", "step", "result"] = "step"
    starts_subsection: bool = False


class ProcessSection(BaseModel):
    section_title: str
    start_label: str
    end_label: str
    marker_style: Literal["numeric", "alpha"] = "numeric"
    steps: List[ProcessStep]


class ProcessFlowData(BaseModel):
    title: str
    key_message: str
    sections: List[ProcessSection]  # 1 or 2 is the practical ceiling
    footnotes: Optional[List[str]] = None


# ─── quiz-recap.html ─────────────────────────────────────────────────────
class QuizRow(BaseModel):
    question: str
    values: List[str]  # one entry per column


class QuizRecapData(BaseModel):
    title: str
    key_message: str
    columns: List[str]
    rows: List[QuizRow]
    summary_label: Optional[str] = None
    summary_values: Optional[List[str]] = None
    footnotes: Optional[List[str]] = None


# ─── flashcard-grid.html ─────────────────────────────────────────────────
class Flashcard(BaseModel):
    front: str
    back: str
    source: Optional[str] = None
    tag: Optional[str] = None


class FlashcardSection(BaseModel):
    section_title: Optional[str] = None
    cards: List[Flashcard]


class FlashcardGridData(BaseModel):
    title: str
    key_message: str
    sections: List[FlashcardSection]
    footnotes: Optional[List[str]] = None


# ─── contents.html ──────────────────────────────────────────────
class ContentsData(BaseModel):
    title: str
    content_html: str  # expected to use only ol.agenda / ol.sub markup
    footnote: Optional[str] = None


# ─── two-section.html ────────────────────────────────────────────────────
class TwoSectionImage(BaseModel):
    src: Optional[str] = None
    alt: Optional[str] = None
    placeholder: Optional[str] = None


class TwoSectionData(BaseModel):
    title: str
    key_message: str
    left_title: str
    right_title: str
    left_content: str  # raw HTML
    right_content: Optional[str] = None  # raw HTML; omit to use right_image
    right_image: Optional[TwoSectionImage] = None
    footnote: Optional[str] = None


# ─── freeform.html ───────────────────────────────────────────────────────
class FreeformData(BaseModel):
    title: str
    key_message: str
    content_html: str  # single-col / two-col / three-col, per the template
    footnote: Optional[str] = None


# ─── Role → model registry ───────────────────────────────────────────────
# The role key is the contract between the outline, the renderer and the
# handoff object. The outline's printed label says "Template" while these
# internal keys and fields keep the word role - a deliberate split, not a
# leftover. Do not add a role here without a real template backing it in
# templates/.
ROLE_MODEL_MAP = {
    "cover": CoverData,
    "section_divider": SectionDividerData,
    "content_grid": ContentGridData,
    "comparison_matrix": ComparisonMatrixData,
    "multi_panel": MultiPanelData,
    "topic_checklist": TopicChecklistData,
    "mastery_heatmap": MasteryHeatmapData,
    "process_flow": ProcessFlowData,
    "quiz_recap": QuizRecapData,
    "flashcard_grid": FlashcardGridData,
    "contents": ContentsData,
    "two_section": TwoSectionData,
    "freeform": FreeformData,
}

# Role → real template filename in templates/. Kept as a separate map (not
# folded into ROLE_MODEL_MAP) because render_slide.py needs this without
# importing every Pydantic model.
ROLE_TEMPLATE_FILE = {
    "cover": "cover.html",
    "section_divider": "section-divider.html",
    "content_grid": "content-grid.html",
    "comparison_matrix": "comparison-matrix.html",
    "multi_panel": "multi-panel.html",
    "topic_checklist": "topic-checklist.html",
    "mastery_heatmap": "mastery-heatmap.html",
    "process_flow": "process-flow.html",
    "quiz_recap": "quiz-recap.html",
    "flashcard_grid": "flashcard-grid.html",
    "contents": "contents.html",
    "two_section": "two-section.html",
    "freeform": "freeform.html",
}


class Slide(BaseModel):
    slide_number: int
    slide_role: str  # must be a key in ROLE_MODEL_MAP
    data: dict  # validated against ROLE_MODEL_MAP[slide_role] separately
    flags: List[str] = []
    key_message: Optional[str] = None  # one sentence: what the student takes away


class StudyDeckOutline(BaseModel):
    subject: str
    guide_title: str
    guide_date: str
    prepared_for: Optional[str] = None
    slides: List[Slide]


# ═══════════════════════════════════════════════════════════════════════
# Field reference: introspection + CLI
# ═══════════════════════════════════════════════════════════════════════
#
# This module used to be library-only, which meant the one way to find out
# what fields a role takes was to read the models above, and the one way
# to find out how MUCH a role holds was to read its template. That is
# roughly fourteen file reads at the start of every build run, for
# information that does not change between runs.
#
# Everything below turns that into one command. The field lists are
# derived from the Pydantic models via model_fields, never transcribed, so
# they cannot drift from the models the pipeline actually validates
# against. The two things that genuinely cannot be derived - how many rows
# a template holds at 1280x720, and what realistic data looks like - are
# curated constants, marked as such, with the examples validated against
# their own models every time the reference is generated.


def _type_str(ann) -> str:
    """A readable one-line spelling of a type annotation.

    Produces the source-level spelling a reader recognises (`Optional[str]`,
    `List[TableRow]`, `Literal['bullets', 'table']`) rather than
    typing's own repr.
    """
    if ann is None or ann is type(None):
        return "None"

    origin = get_origin(ann)

    if origin is None:
        if isinstance(ann, type):
            return ann.__name__
        return str(ann)

    if origin is Literal:
        return "Literal[" + ", ".join(repr(a) for a in get_args(ann)) + "]"

    # Union covers both typing.Union and PEP 604's `X | None`.
    if origin is Union or origin is getattr(typing, "UnionType", None) or (
        getattr(ann, "__class__", None).__name__ == "UnionType"
    ):
        args = list(get_args(ann))
        non_none = [a for a in args if a is not type(None)]
        inner = ", ".join(_type_str(a) for a in non_none)
        optional = len(non_none) < len(args)
        if len(non_none) == 1:
            return f"Optional[{inner}]" if optional else inner
        return f"Optional[Union[{inner}]]" if optional else f"Union[{inner}]"

    if origin in (list, set, tuple, frozenset):
        args = get_args(ann)
        name = origin.__name__.capitalize() if origin is not list else "List"
        return f"{name}[{', '.join(_type_str(a) for a in args)}]" if args else name

    if origin is dict:
        args = get_args(ann)
        return f"Dict[{', '.join(_type_str(a) for a in args)}]" if args else "dict"

    return str(ann)


def _nested_models(ann) -> list:
    """Every BaseModel subclass reachable inside one annotation, in order."""
    found = []

    def walk(a):
        if isinstance(a, type) and issubclass(a, BaseModel):
            if a not in found:
                found.append(a)
            return
        for sub in get_args(a):
            walk(sub)

    walk(ann)
    return found


def _fields_of(model_cls, _stack=()) -> list:
    """Field descriptors for one model, recursing into nested models.

    `_stack` guards against a self-referential model. None of the 13 role
    models is recursive today, and this keeps that from becoming a hang if
    one ever is.
    """
    out = []
    for name, info in model_cls.model_fields.items():
        entry = {
            "name": name,
            "type": _type_str(info.annotation),
            "required": info.is_required(),
        }
        if not info.is_required():
            default = info.default
            if info.default_factory is not None:
                try:
                    default = info.default_factory()
                except TypeError:
                    default = None
            try:
                json.dumps(default)
                entry["default"] = default
            except (TypeError, ValueError):
                entry["default"] = repr(default)

        nested = []
        for sub in _nested_models(info.annotation):
            if sub.__name__ in _stack:
                nested.append({"model": sub.__name__, "fields": "(recursive)"})
                continue
            nested.append({
                "model": sub.__name__,
                "fields": _fields_of(sub, _stack + (sub.__name__,)),
            })
        if nested:
            entry["nested"] = nested
        out.append(entry)
    return out


def role_fields(role: str) -> dict:
    if role not in ROLE_MODEL_MAP:
        raise KeyError(role)
    model_cls = ROLE_MODEL_MAP[role]
    return {
        "slide_role": role,
        "model": model_cls.__name__,
        "template": ROLE_TEMPLATE_FILE[role],
        "fields": _fields_of(model_cls, (model_cls.__name__,)),
        "capacity_notes": CAPACITY_NOTES.get(role, {}),
    }


def all_role_fields() -> dict:
    return {"roles": [role_fields(r) for r in ROLE_MODEL_MAP]}


# ─── Curated, not derived ────────────────────────────────────────────────
# Practical length limits for the list-shaped fields, read off each
# template's own layout maths at the 1280x720 canvas. These are NOT
# enforced by the models - a longer list validates fine and then gets
# caught downstream by verify_render.py, which measures the real render
# and shrinks or flags it. They are here so a deck is authored at a length
# that fits in the first place rather than discovered to be over at the
# gate.
#
# Anything quoted as a font size or a row budget below comes from the
# template named in ROLE_TEMPLATE_FILE, not from an estimate made here. If
# a template's layout maths changes, this dict has drifted and needs
# re-reading from the template.
CAPACITY_NOTES = {
    "cover": {},
    "section_divider": {},
    "content_grid": {
        "quads": "Exactly 4. The grid is a fixed 2x2; fewer quads render but leave visible gaps.",
        "quads[].bullets": "5 to 6 single-line bullets per quad (13px type, 1.5 line-height, ~180px of quad body). 3 to 4 if they wrap.",
        "quads[].table_rows": "5 to 6 rows per quad including the header (12px type, ~26px per row).",
        "quads[].definitions": "4 to 5 term/meaning pairs per quad. A meaning longer than about 90 characters wraps to a second line and costs a pair.",
        "footnote": "One line. The lane is capped at 74px, which is about 5 lines at 10px, but the layout reads best at 1 to 2.",
    },
    "comparison_matrix": {
        "columns": "2 to 6. Column widths are proportional shares; 4 to 5 is the usual shape. The first column is the thing being compared, the rest are the dimensions of comparison.",
        "column_widths": "Must be the same length as `columns`, or it is ignored and equal widths are used.",
        "groups[].rows": "About 15 single-line rows at the 12px ceiling, up to about 24 at the 8px floor. The template solves type size against a 480px budget less the footnote lane, then verify_render.py measures the result.",
        "groups[].rows[].cells": "One cell per entry in `columns`, always.",
        "footnotes": "Up to 8 to 10 short notes. The lane is capped at 130px and sets itself in 2 columns from 3 notes and 3 columns from 6.",
    },
    "multi_panel": {
        "sections": "2, 3, 4 or 6. The grid solves for these counts; 5 renders with a gap.",
        "sections[].bullets": "4 to 6 single-line bullets per panel at a 3-panel layout, fewer as panel count rises.",
        "sections[].table_rows": "6 to 8 rows including the header at 2 panels, 4 to 5 at 4 panels.",
        "sections[].chart_bars": "3 to 7 bars. Labels longer than about 14 characters truncate.",
    },
    "topic_checklist": {
        "topics": "3 to 6 reads best. The colour palette cycles past 6, so more still renders but stops being visually distinct.",
        "topics[].bullets": "3 to 5 per topic. These are what the student has to be able to do, not a summary of the topic.",
        "footnote": "One to two lines.",
    },
    "mastery_heatmap": {
        "topics": "8 to 14 rows. Past 14 the row height compresses below comfortable reading; verify_render.py measures and flags it.",
        "topics[].topic": "About 40 characters before it wraps.",
        "topics[].resource": "Short - a lecture number, a chapter, a problem set. Not a sentence.",
        "footnote": "One line.",
    },
    "process_flow": {
        "sections": "1 or 2. Two sections halve the vertical budget for each.",
        "sections[].steps": "5 to 9 steps in a single-section layout, 4 to 6 each when there are two. A derivation longer than that belongs on two slides.",
        "sections[].steps[].detail": "One short line - the justification for the step, not a re-derivation of it.",
        "footnotes": "Up to 4.",
    },
    "quiz_recap": {
        "columns": "2 to 4. These are the ANSWER columns only - the question column is rendered from `rows[].question` and is not listed here.",
        "rows": "6 to 10 at a 3-column layout. Long question text is the binding constraint, not row count.",
        "rows[].values": "One entry per column, always.",
        "summary_values": "Same length as `columns` when present.",
    },
    "flashcard_grid": {
        "sections": "1 to 3.",
        "sections[].cards": "6 to 9 cards in a single-section layout, 4 to 6 per section at 2 sections.",
        "sections[].cards[].front": "A question or a term. Under about 60 characters.",
        "sections[].cards[].back": "The answer. Under about 120 characters - a flashcard that needs a paragraph is a slide, not a card.",
    },
    "contents": {
        "content_html": "Use only ol.agenda / ol.sub markup. About 10 top-level items, or 6 with sub-items.",
    },
    "two_section": {
        "left_content": "Raw HTML. About 300 words per side before the type drops below comfortable reading.",
        "right_content": "Same budget as left. Omit to use `right_image` instead.",
    },
    "freeform": {
        "content_html": "single-col / two-col / three-col wrappers, per the template. This role exists for content the other twelve genuinely do not fit - reach for it last, not first.",
    },
}

EXAMPLES = {
    "cover": {
        "title": "Eigenvalues and Diagonalization",
        "subtitle": "Midterm 2 Review Guide",
        "course_line": "Course: Linear Algebra",
        "scope_line": "Scope: Lectures 6 to 9, textbook chapter 5",
        "prepared_for_line": "Prepared for: Midterm 2",
        "date_line": "04 March 2026",
    },
    "section_divider": {
        "section_number": 2,
        "eyebrow": "Section 2",
        "title": "Diagonalization",
        "lede": "When a matrix is diagonalizable, and what to do when it is not.",
    },
    "content_grid": {
        "title": "What This Unit Covers",
        "key_message": "Four ideas, and every exam question is a combination of them.",
        "quads": [
            {"title": "Core definitions", "content_type": "definitions", "definitions": [
                {"term": "Eigenvector", "meaning": "A nonzero v with Av = lambda v"},
                {"term": "Eigenvalue", "meaning": "The scalar lambda in that relation"},
                {"term": "Characteristic polynomial", "meaning": "det(A - lambda I)"},
                {"term": "Algebraic multiplicity", "meaning": "Multiplicity of lambda as a root"},
            ]},
            {"title": "What you must be able to do", "content_type": "bullets", "bullets": [
                "Compute the characteristic polynomial of a 2x2 and 3x3",
                "Find eigenvalues and a basis for each eigenspace",
                "Decide whether a given matrix is diagonalizable",
                "Write A = PDP^-1 and use it to compute A^k",
            ]},
            {"title": "Where each topic is covered", "content_type": "table",
             "table_headers": ["Topic", "Lecture", "Reading"],
             "table_rows": [
                 ["Characteristic polynomial", "L6", "5.1"],
                 ["Eigenspaces", "L7", "5.1 to 5.2"],
                 ["Diagonalization", "L8", "5.3"],
                 ["Symmetric case", "L9", "5.5"],
             ]},
            {"title": "Common traps", "content_type": "bullets", "bullets": [
                "Forgetting that eigenvectors must be nonzero",
                "Assuming distinct eigenvalues are necessary, not just sufficient",
                "Mixing up algebraic and geometric multiplicity",
                "Dropping the order of P and D in A = PDP^-1",
            ]},
        ],
        "footnote": "Lecture references are to the Winter 2026 offering.",
    },
    "comparison_matrix": {
        "title": "Diagonalizable or Not",
        "key_message": "Geometric multiplicity is the only test that always decides it.",
        "columns": ["Case", "Characteristic polynomial", "Geometric multiplicity", "Diagonalizable?"],
        "groups": [
            {"group_label": "Distinct eigenvalues", "rows": [
                {"cells": ["n distinct roots", "n simple roots", "1 for each", "Always"]},
            ]},
            {"group_label": "Repeated eigenvalues", "rows": [
                {"cells": ["Repeated root, full eigenspace", "Root of multiplicity k", "Equals k", "Yes"]},
                {"cells": ["Repeated root, deficient eigenspace", "Root of multiplicity k", "Less than k", "No"]},
            ]},
        ],
        "footnotes": ["Distinct eigenvalues are sufficient but not necessary for diagonalizability."],
    },
    "multi_panel": {
        "title": "Worked Example: A 3x3 Case",
        "key_message": "The whole method in one pass, with the arithmetic shown.",
        "sections": [
            {"section_title": "The matrix", "content_type": "bullets", "bullets": [
                "A has rows (2,1,0), (0,2,0), (0,0,3)",
                "Upper triangular, so eigenvalues read off the diagonal",
            ]},
            {"section_title": "Eigenvalues", "content_type": "table",
             "table_headers": ["lambda", "Algebraic mult.", "Geometric mult."],
             "table_rows": [["2", "2", "1"], ["3", "1", "1"]]},
            {"section_title": "Conclusion", "content_type": "bullets", "bullets": [
                "Geometric multiplicity of lambda = 2 is 1, less than 2",
                "So A is not diagonalizable",
            ]},
        ],
        "footnote": "Worked in lecture 8; the same matrix appears on problem set 4.",
    },
    "topic_checklist": {
        "title": "Readiness Check",
        "key_message": "Four things to be able to do without notes before the exam.",
        "topics": [
            {"topic_name": "Characteristic polynomial", "status": "Confident", "bullets": [
                "Expand det(A - lambda I) for a 3x3 without error",
                "Factor the resulting cubic",
            ]},
            {"topic_name": "Eigenspaces", "status": "In progress", "bullets": [
                "Solve (A - lambda I)v = 0 and give a basis",
                "State the geometric multiplicity from that basis",
            ]},
            {"topic_name": "Diagonalization", "status": "In progress", "bullets": [
                "Assemble P and D in the right order",
                "Use A = PDP^-1 to compute a high power",
            ]},
            {"topic_name": "Symmetric matrices", "status": "Not started", "bullets": [
                "State the spectral theorem",
                "Orthogonally diagonalize a symmetric 2x2",
            ]},
        ],
        "footnote": "Status reflects the self-check on 02 March.",
    },
    "mastery_heatmap": {
        "title": "Topic Mastery and Review Schedule",
        "key_message": "Two topics are behind schedule with nine days to the exam.",
        "course_name": "Linear Algebra",
        "assessment_name": "Midterm 2",
        "assessment_date": "13 March 2026",
        "last_review": {"reviewed_by": "Self-check", "last_reviewed": "02 March 2026",
                        "next_review": "06 March 2026"},
        "topics": [
            {"topic": "Characteristic polynomial", "id": 1, "source": "L6", "status": "Confident",
             "first_covered": "10 Feb 2026", "last_reviewed": "01 Mar 2026",
             "next_review": "08 Mar 2026", "resource": "5.1"},
            {"topic": "Eigenspaces and bases", "id": 2, "source": "L7", "status": "Practiced",
             "first_covered": "12 Feb 2026", "last_reviewed": "02 Mar 2026",
             "next_review": "06 Mar 2026", "resource": "5.1-5.2"},
            {"topic": "Diagonalization criterion", "id": 3, "source": "L8", "status": "Struggling",
             "first_covered": "17 Feb 2026", "last_reviewed": "28 Feb 2026",
             "next_review": "05 Mar 2026", "resource": "PS4"},
            {"topic": "Spectral theorem", "id": 4, "source": "L9", "status": "Not started",
             "first_covered": "19 Feb 2026", "last_reviewed": "-",
             "next_review": "05 Mar 2026", "resource": "5.5"},
        ],
        "footnote": "Review dates follow the spacing the syllabus recommends.",
    },
    "process_flow": {
        "title": "Diagonalizing a Matrix, Step by Step",
        "key_message": "Five steps, and step 3 is where the method can fail.",
        "sections": [
            {"section_title": "From A to PDP^-1",
             "start_label": "Given A (n x n)",
             "end_label": "A = PDP^-1",
             "marker_style": "numeric",
             "steps": [
                 {"name": "Form A - lambda I", "kind": "given",
                  "detail": "Subtract lambda from each diagonal entry"},
                 {"name": "Solve det(A - lambda I) = 0", "kind": "step",
                  "detail": "Roots are the eigenvalues, with algebraic multiplicity"},
                 {"name": "Find each eigenspace", "kind": "step",
                  "detail": "Null space of (A - lambda I); its dimension is the geometric multiplicity"},
                 {"name": "Check total dimension", "kind": "step",
                  "detail": "If the eigenspace dimensions do not sum to n, stop: A is not diagonalizable"},
                 {"name": "Assemble P and D", "kind": "result",
                  "detail": "Eigenvectors as columns of P, eigenvalues in the matching order down D"},
             ]},
        ],
        "footnotes": ["Step 4 is the only place the method can fail.",
                      "The order of columns in P must match the order of entries in D."],
    },
    "quiz_recap": {
        "title": "Practice Set 4 Recap",
        "key_message": "Both misses were the same error: multiplicity confusion.",
        "columns": ["Your answer", "Correct answer", "Covered in"],
        "rows": [
            {"question": "Eigenvalues of the given 2x2",
             "values": ["1 and 4", "1 and 4", "L6"]},
            {"question": "Is the repeated-root matrix diagonalizable?",
             "values": ["Yes", "No - geometric multiplicity is 1", "L8"]},
            {"question": "Geometric multiplicity of lambda = 2",
             "values": ["2", "1", "L7"]},
            {"question": "Compute A^5 by diagonalization",
             "values": ["Correct", "Correct", "L8"]},
        ],
        "summary_label": "Score",
        "summary_values": ["2 of 4", "-", "-"],
        "footnotes": ["Both misses trace to the same confusion between algebraic and geometric multiplicity."],
    },
    "flashcard_grid": {
        "title": "Definitions to Know Cold",
        "key_message": "Exam questions assume these without restating them.",
        "sections": [
            {"section_title": "Core", "cards": [
                {"front": "Eigenvector", "back": "A nonzero vector v with Av = lambda v for some scalar lambda",
                 "source": "L6", "tag": "definition"},
                {"front": "Characteristic polynomial", "back": "det(A - lambda I), whose roots are the eigenvalues",
                 "source": "L6", "tag": "definition"},
                {"front": "Algebraic multiplicity", "back": "The multiplicity of lambda as a root of the characteristic polynomial",
                 "source": "L7", "tag": "definition"},
                {"front": "Geometric multiplicity", "back": "The dimension of the eigenspace for lambda",
                 "source": "L7", "tag": "definition"},
                {"front": "Diagonalizable", "back": "A = PDP^-1 for some invertible P and diagonal D",
                 "source": "L8", "tag": "definition"},
                {"front": "Spectral theorem", "back": "Every real symmetric matrix is orthogonally diagonalizable",
                 "source": "L9", "tag": "theorem"},
            ]},
        ],
        "footnotes": ["Wording follows the course's definitions, which differ slightly from the textbook's."],
    },
    "contents": {
        "title": "Contents",
        "content_html": "<ol class=\"agenda\"><li>What this unit covers</li><li>Diagonalization<ol class=\"sub\"><li>The criterion</li><li>Worked example</li></ol></li><li>Definitions to know</li><li>Practice recap</li></ol>",
        "footnote": "Nine days to the exam.",
    },
    "two_section": {
        "title": "Course Notation vs Textbook Notation",
        "key_message": "The course writes the eigenvalue equation the other way round; use the course's form.",
        "left_title": "As lectures write it",
        "right_title": "As the textbook writes it",
        "left_content": "<p>Av = <em>lambda</em> v, with eigenvalues indexed lambda_1 to lambda_n in the order they appear down D.</p>",
        "right_content": "<p>(A - lambda I)v = 0, with eigenvalues indexed by decreasing magnitude.</p>",
        "footnote": "Exams are graded against the lecture convention.",
    },
    "freeform": {
        "title": "One-Page Summary",
        "key_message": "Everything above, compressed to what fits on a permitted note sheet.",
        "content_html": "<div class=\"two-col\"><div><h4>Method</h4><p>Characteristic polynomial, eigenspaces, dimension check, assemble.</p></div><div><h4>Failure case</h4><p>Geometric multiplicity below algebraic multiplicity for any eigenvalue.</p></div></div>",
        "footnote": "One page of notes is permitted for this exam.",
    },
}


def _validated_examples() -> dict:
    """Every example, validated against its own role model. Raises on a bad one."""
    for role, data in EXAMPLES.items():
        if role not in ROLE_MODEL_MAP:
            raise ValueError(f"EXAMPLES has role {role!r}, which is not in ROLE_MODEL_MAP")
        ROLE_MODEL_MAP[role].model_validate(data)
    missing = [r for r in ROLE_MODEL_MAP if r not in EXAMPLES]
    if missing:
        raise ValueError(f"No example for role(s): {missing}")
    return EXAMPLES


_MD_PREAMBLE = """# Slide role field reference

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
"""


def _fields_table(fields, indent="") -> list:
    lines = [
        indent + "| Field | Type | Required | Default |",
        indent + "|---|---|---|---|",
    ]
    for f in fields:
        if f["required"]:
            required, default = "required", ""
        else:
            required = "optional"
            default = "`" + json.dumps(f.get("default")) + "`" if "default" in f else ""
        lines.append(
            f"{indent}| `{f['name']}` | `{f['type']}` | {required} | {default} |"
        )
    return lines


def _collect_nested(fields, acc=None, seen=None):
    """Flatten every nested model reachable from a field list, in first-use order."""
    acc = [] if acc is None else acc
    seen = set() if seen is None else seen
    for f in fields:
        for n in f.get("nested", []):
            if n["model"] in seen or n["fields"] == "(recursive)":
                continue
            seen.add(n["model"])
            acc.append(n)
            _collect_nested(n["fields"], acc, seen)
    return acc


def build_markdown() -> str:
    examples = _validated_examples()

    out = [_MD_PREAMBLE, "", "## Roles at a glance", "",
           "| `slide_role` | Template | Data model |",
           "|---|---|---|"]
    for role in ROLE_MODEL_MAP:
        out.append(
            f"| `{role}` | `templates/{ROLE_TEMPLATE_FILE[role]}` | "
            f"`{ROLE_MODEL_MAP[role].__name__}` |"
        )
    out.append("")

    for role in ROLE_MODEL_MAP:
        spec = role_fields(role)
        out.append("---")
        out.append("")
        out.append(f"## `{role}`")
        out.append("")
        out.append(f"- **`slide_role` tag:** `{role}`")
        out.append(f"- **Template:** `templates/{spec['template']}`")
        out.append(f"- **Data model:** `{spec['model']}`")
        out.append("")
        out.append("### Fields")
        out.append("")
        out.extend(_fields_table(spec["fields"]))
        out.append("")

        nested = _collect_nested(spec["fields"])
        if nested:
            out.append("### Nested models")
            out.append("")
            for n in nested:
                out.append(f"**`{n['model']}`**")
                out.append("")
                out.extend(_fields_table(n["fields"]))
                out.append("")

        notes = spec["capacity_notes"]
        if notes:
            out.append("### Practical length limits")
            out.append("")
            for field, note in notes.items():
                out.append(f"- **`{field}`** - {note}")
            out.append("")

        out.append("### Example `data`")
        out.append("")
        out.append("```json")
        out.append(json.dumps(examples[role], indent=2))
        out.append("```")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


_CLI_USAGE = (
    "Usage:\n"
    "  python3 deck_schemas.py --fields            JSON field reference, all 13 roles\n"
    "  python3 deck_schemas.py --fields <role>     JSON field reference, one role\n"
    "  python3 deck_schemas.py --markdown          the generated docs/role_field_reference.md\n"
)


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h"):
        print(_CLI_USAGE)
        sys.exit(0 if args else 2)

    if args[0] == "--markdown":
        if len(args) != 1:
            print(_CLI_USAGE, file=sys.stderr)
            sys.exit(2)
        try:
            sys.stdout.write(build_markdown())
        except Exception as e:
            print(f"Could not generate the reference: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args[0] == "--fields":
        if len(args) == 1:
            print(json.dumps(all_role_fields(), indent=2))
            return
        if len(args) == 2:
            try:
                print(json.dumps(role_fields(args[1]), indent=2))
            except KeyError:
                print(
                    f"Unknown slide_role {args[1]!r}. Known roles: "
                    f"{', '.join(ROLE_MODEL_MAP)}",
                    file=sys.stderr,
                )
                sys.exit(1)
            return
        print(_CLI_USAGE, file=sys.stderr)
        sys.exit(2)

    print(f"Unknown option {args[0]!r}\n\n{_CLI_USAGE}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
