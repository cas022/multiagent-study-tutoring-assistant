# Study Guide Generator Plugin

The Study Guide Generator agent for the Multiagent Study & Tutoring Assistant. Turns course material into a finished study guide deck: a rendered HTML preview and an editable `.pptx`.

## Two stages, one checkpoint

```
Study Manager builds handoff_content from what it already has
    ↓
guide-generator [outline]
    → a conceptual outline, filled in as far as the content reaches
    → AND a per-slide list of what it could NOT fill, and where that lives
    ↓
Student approves or gives feedback        ← the only checkpoint
    ↓
Study Manager resolves the content requests
   (index first, then group by SOURCE not by slide, fan out in parallel)
    ↓
guide-generator [build]
    → detailed outline → validate → render → measure fit → preview → .pptx
    ↓
preview.html + guide.pptx
```

The outline stage naming its own gaps is the load-bearing idea. It is why the stage is allowed to fill slides in as far as it can, and why the fetch that follows is a short, targeted read instead of a guess at what a deck might need.

## What comes out, and why there are two of them

| | |
|---|---|
| `preview.html` | **Exact.** Jinja-rendered at 1280x720 and measured in headless Chromium, so what is on screen is what fits. The reading and printing view. |
| `guide.pptx` | **Editable.** Real PowerPoint text frames, tables and shapes built natively from the same validated outline. |

An image-per-slide export would have matched the HTML pixel for pixel and been a fraction of the code. It was rejected deliberately: a deck of flat pictures cannot be corrected, and the most likely thing a student does with a study guide is fix something in it. Where the two disagree visually, the HTML is correct.

## The thirteen roles

Each is a real template in `templates/`, a Pydantic model in `scripts/deck_schemas.py`, and an entry in `docs/role_field_reference.md` (generated, never hand-edited).

| Role | For |
|---|---|
| `cover` | Course, scope, assessment. Always slide 1. |
| `contents` | Guides longer than about 8 slides. |
| `section_divider` | Genuine sections only. |
| `content_grid` | 2x2 overview: coverage, required skills, where topics live, common traps. |
| `comparison_matrix` | Cases against dimensions - when a theorem applies, competing methods. |
| `multi_panel` | A worked example in stages, or several short related blocks. |
| `topic_checklist` | Readiness per topic, with optional status. |
| `mastery_heatmap` | Review scheduling across topics, with a review-gap column that flags what is overdue. |
| `process_flow` | A derivation or algorithm as ordered steps, with the failure point marked. |
| `quiz_recap` | Practice results: question, your answer, correct answer, where it is covered. |
| `flashcard_grid` | Definitions to memorise, front over back so the answer can be covered. |
| `two_section` | Exactly two things side by side - course vs textbook notation. |
| `freeform` | Last resort. Reach for it last, not first. |

## Why so much of this is a script, not a prompt

Schema validation, Jinja rendering, render-fit measurement and `.pptx` construction all run as real bundled Python via Bash, never as model self-report.

The render-fit check is the clearest case. `verify_render.py` loads each rendered slide in headless Chromium and measures actual geometry: what is clipped, what runs off the canvas, how much of the content zone is used. A model asked "does this slide fit?" will answer confidently and be wrong, because the question is about a layout it cannot see. The script steps a slide's zoom down to a floor to try to fit it, and if it still clips, raises a BLOCKING flag rather than dropping content to make the problem disappear.

It also distinguishes `under_fill` from a defect. A cover, a divider, a short summary are correctly sparse, and reporting empty space as a fault would train the pipeline to pad slides.

## Structure

```
study-guide-generator/
├── .claude-plugin/plugin.json
├── agents/
│   └── guide-generator.md          # Both stages, in full
├── docs/
│   ├── guide_handoff_schema.md     # The contract with the Study Manager
│   └── role_field_reference.md     # GENERATED from deck_schemas.py
├── scripts/
│   ├── deck_schemas.py             # 13 models + registries; source of the reference
│   ├── validate_deck_outline.py    # Per-slide validation against the models
│   ├── build_deck.py               # Render orchestration
│   ├── render_slide.py             # Jinja rendering, one slide
│   ├── verify_render.py            # Real geometry measurement in Chromium
│   ├── build_html_preview.py       # Self-contained deck preview
│   ├── build_pptx.py               # Native .pptx export
│   ├── outline_from_json.py        # Human-readable outline markdown
│   ├── extract_deck_roles.py       # Passive required-role check
│   └── html_tables_to_md.py        # HTML table flattening for the outline
├── templates/                      # 13 Jinja templates, 1280x720
└── README.md
```

## Regenerating the role reference

```
python3 scripts/deck_schemas.py --markdown > docs/role_field_reference.md
```

It is generated from the models so it cannot drift from what actually validates. Hand-editing it would only make it lie until the next regeneration.

## Requirements

`pydantic`, `jinja2`, `python-pptx`, and Playwright with Chromium for the fit measurement. Without Chromium the slides and preview still build, no fit report is produced, and that is reported rather than passed off as a clean run.

## See Also

- The project `CLAUDE.md` - routing for the guide flow in the Study Manager
- `docs/guide_handoff_schema.md` - task state shape and stage contract
- `docs/role_field_reference.md` - every field of every role
