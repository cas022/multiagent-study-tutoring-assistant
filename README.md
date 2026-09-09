# Multiagent Study & Tutoring Assistant

A multiagent system that turns a student's own course material into study output: structured lecture notes, researched explanations of the concepts a course assumes but never teaches, and finished study guide decks.

You give it your lectures, slides and readings. It indexes them, keeps track of what it knows per subject, and builds on top of that material rather than on top of whatever the model happens to remember about the topic.

---

## The idea it is built around

**Study material that is wrong is worse than no study material, because the student memorises it.**

Every rule in this system exists to serve that. Every claim in every output traces to either an indexed document or a cited external source. Nothing is filled in from general knowledge without being labelled. A gap in the source material is reported as a gap, not smoothed over. Where a course states something differently from how the field usually states it, the course's version wins, because that is what the student is graded on.

That single constraint is why the architecture looks the way it does: a deterministic document index rather than a vibe, source ranking by script rather than by judgment, and a build stage that would rather ship a slide reading `[not found in the sources]` than a confident invention.

---

## Architecture

```
                        ┌──────────────────────┐
                        │    STUDY MANAGER     │   the Cowork conversation
                        │  indexing · reading  │   owns all retrieval
                        │  routing · handoffs  │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
    ┌───────────────────┐ ┌──────────────────┐ ┌────────────────────┐
    │ STUDENT NOTE      │ │ CONCEPT          │ │ STUDY GUIDE        │
    │ TAKER             │ │ RESEARCHER       │ │ GENERATOR          │
    │ Zoom or pasted    │ │ tiered academic  │ │ outline → build    │
    │ transcript →      │ │ sources → cited  │ │ → preview + .pptx  │
    │ structured notes  │ │ .docx brief      │ │                    │
    └───────────────────┘ └──────────────────┘ └────────────────────┘
                                   │
                        ┌──────────┴───────────┐
                        │   ctx/index.json     │  every document, hashed
                        │   ctx/documents/     │  one folder per subject
                        └──────────────────────┘
```

The Study Manager is the conversation itself, not a separate program. It does the indexing, the document reading and every retrieval, and hands off to a subagent only when that role's work benefits from running in an isolated context.

**Subagents never retrieve.** None of the three can read `ctx/index.json` or `ctx/documents/`. If they could, every call would drag hundreds of source pages into the context the isolation exists to protect. The cost of that boundary is that a gap the Study Manager did not close cannot be closed later, which is deliberate: the build stage flags it instead.

---

## What each piece does

### Study Manager (`CLAUDE.md`)

Owns the index. Before every read of `ctx/index.json` it reconciles: the index's content hashes against what is actually on disk. New file, changed file, missing file - all resolved before the index is trusted for an answer. This is hash equality, not a judgment call about whether two documents are "the same."

It is also the tutor. Most requests are not one of the three flows below: explaining a concept, walking a worked example, checking reasoning on a practice problem, and answering "what did lecture 9 say about X" are all direct work, not subagent calls.

### Student Note Taker

Converts a Zoom recording summary, a pasted transcript, or an uploaded file into structured lecture notes. The schema is shaped around what a student needs later rather than what a generic summariser produces:

- **Definitions and Results Introduced** captures things verbatim, in the course's notation.
- **Instructor Emphasis** hunts specifically for the offhand "this will be on the midterm" - often the single most useful line in an hour of recording, and trivially lost in a generic summary.
- **Open Questions** captures what was deferred, which is where the next lecture usually starts.
- **FLAGS** captures transcription damage. Automated transcripts mangle technical vocabulary constantly, and a silently "corrected" formula is worse than a flagged one.

### Concept Researcher

Researches what the course material assumes but never explains, at a depth the student chooses. **Sources are ranked by a deterministic script, not by the model**, because "which sources look best to me" is exactly the latitude that produces a study guide resting on a homework-answers site:

| Tier | |
|---|---|
| 1 | Peer-reviewed literature - journals, proceedings, publishers, DOI, PubMed |
| 2 | University and course material - `.edu` / `.ac.uk`, open courseware |
| 3 | Preprints and scholarly indexes - arXiv, bioRxiv, SSRN, Semantic Scholar |
| 4 | Official technical documentation and standards - library docs, RFCs, W3C, NIST |
| 5 | Established reference works - subject encyclopedias, technical publishers of record |
| 6 | General and user-generated web - never the sole basis for a claim |

Budget is spent strictly top-down, and recency sorts *within* a tier and never across one, so a recent blog post never outranks an older published paper. **Chegg, Course Hero, Quizlet and Studocu sit in tier 6 deliberately** and are never scraped: unattributed, unverified, and a well-documented way to propagate other students' mistakes.

The brief it produces has a **Common Misconceptions** section that has to name *why* each confusion arises, not just that the belief is wrong - a student who knows only that they were wrong will make the same error from the same cause again.

### Study Guide Generator

Two stages with one human checkpoint. The `outline` stage builds the deck as far as the supplied content reaches **and returns a list of what it could not fill, where that likely lives, and why each slide needs it**. That list is what the Study Manager then fetches against - grouped by source document rather than walked slide by slide.

The `build` stage validates every slide against its model, renders real Jinja templates, measures the actual rendered geometry in headless Chromium, and exports both a self-contained HTML preview and an editable `.pptx`.

Thirteen slide roles, each a real template with a Pydantic model behind it. See `study-guide-generator/docs/role_field_reference.md`, which is generated from the models so it cannot drift.

---

## Setup

### 1. Add the skill

Copy `pptx-native-tables/` into your Claude skills directory. It handles PowerPoint table and slide-layout work for the deck export.

### 2. Add the plugins

Install the three plugin folders so Claude can call them as subagents:

- `student-note-taker/`
- `concept-researcher/`
- `study-guide-generator/`

Each has a `.claude-plugin/plugin.json` and an `agents/` definition.

### 3. Connect the MCP connectors

**Zoom** is already built into the Claude desktop app. You only need to sign in and connect it - no config file editing.

**Perplexity** and **Firecrawl** have to be added yourself. Go to **Settings → Developer → Edit Config**, and add each server to the config file with your own API key. Both run through Node, so you need Node.js installed:

```json
{
  "mcpServers": {
    "perplexity": {
      "command": "npx",
      "args": ["-y", "server-perplexity-ask"],
      "env": { "PERPLEXITY_API_KEY": "your-key-here" }
    },
    "firecrawl": {
      "command": "npx",
      "args": ["-y", "firecrawl-mcp"],
      "env": { "FIRECRAWL_API_KEY": "your-key-here" }
    }
  }
}
```

Get the keys from each service's own dashboard. Restart Claude after saving the config.

### 4. Python dependencies

```
pip install pydantic jinja2 python-pptx python-docx playwright
playwright install chromium
```

Chromium is what measures whether a slide's content actually fits. Without it the deck still builds, no fit report is produced, and that is reported rather than passed off as a clean run.

### 5. Use it

Open a **Claude Cowork session and connect it to this folder.** The Study Manager reads `CLAUDE.md` at the start of the session and takes it from there.

Drop your course material into `ctx/documents/<subject>/`, or just attach files in the conversation - either way it gets hashed, read and indexed before anything else continues.

---

## Repository layout

```
multiagent-study-tutoring-assistant/
├── CLAUDE.md                    # Study Manager operating rules
├── ctx/
│   ├── index.json               # every document, hashed
│   └── documents/<subject>/     # your course material (gitignored)
├── orch/
│   ├── cache_memory/            # scratch, never indexed
│   └── research_decompose_rules.md
├── student-note-taker/
├── concept-researcher/
├── study-guide-generator/
└── pptx-native-tables/          # skill
```

Your own course material is gitignored. The structure ships; the documents do not.

---

## A note on the deterministic steps

Source tier ranking, selection, dedupe, citation verification, schema validation, render-fit measurement and the document builds all run as real bundled Python via Bash, never as model self-report.

The render-fit check is the clearest case for why. A model asked "does this slide fit?" answers confidently and is wrong, because the question is about a layout it cannot see. The script loads each rendered slide in headless Chromium, measures real geometry, steps the slide down to a legibility floor to try to fit it, and raises a blocking flag if it still clips - rather than dropping content to make the problem disappear.

Same reasoning for source ranking: a model asked to rank URLs by authority and report what it did can fabricate one into the list or silently drop one, and nothing downstream catches it. A script cannot. That removes an entire class of failure instead of detecting it after the fact.
