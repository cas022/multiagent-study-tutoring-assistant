# Study Guide Generator Handoff Schema

Two stages, one human checkpoint, and a hard boundary: **the agent never retrieves anything.** The Study Manager owns every read, before each stage. This document is the contract between them.

## Why the boundary exists

`guide-generator` runs in an isolated context. If it could reach `ctx/index.json` and `ctx/documents/`, every build would pull hundreds of source pages into that context, and the isolation would buy nothing. Keeping retrieval on the Study Manager's side means the agent receives a small, already-selected, already-cited payload, and the expensive reading happens once, in the place that can fan it out across parallel helpers.

The cost of that boundary is that a gap the Study Manager did not close cannot be closed later. That is deliberate: `build` flags the gap rather than papering over it, and a flagged gap is a correct outcome, not a failure.

## Task State Shape

```json
{
  "task_id": "guide_<subject>_<date>",
  "agent": "guide-generator",
  "stage": "outline | build",
  "task_state": { "status": "in_progress | done | failed", "revision": 0 },
  "task_spec": {
    "subject": "<slug>",
    "guide_scope": "<what it covers and what it is for>",
    "handoff_content": "<string>",
    "scratch_dir": "<absolute path>",

    "previous_outline": null,
    "human_feedback": null,

    "approved_outline": null,
    "fetched_content": null,
    "resolved_requests": null,
    "checkpoint_directives": []
  },
  "context": {},
  "flags_summary": []
}
```

## Stage Definitions

| Stage | Input | Output | Checkpoint |
|---|---|---|---|
| `outline` | `handoff_content`, `guide_scope` (+ `previous_outline`, `human_feedback` on a revision) | `outline`, `content_requests`, `content_requests_by_source`, `roles_used`, `slide_count` | **Yes** - the pipeline's only one |
| `build` | `approved_outline`, `fetched_content`, `resolved_requests`, `checkpoint_directives` | `preview_path`, `pptx_path`, `blocking_flags`, `non_blocking_flags`, `index_description` | No |

## The Study Manager's Responsibilities

**Before `outline`:** build `handoff_content` from this conversation's memory and whatever has already been read. **No new fetching at this point.** The outline stage exists to find out what is missing; fetching first means guessing at that answer.

**Between the stages:** resolve the `content_requests` the outline returned. Index descriptions first, then group the remainder **by source document rather than by slide**, open each source once, and fan out across parallel general-purpose helpers where the groups are independent. `fetched_content`'s per-slide shape is an output format, not a read order.

Precedence when more than one source could answer: course-produced material, then textbook and assigned reading, then external research - each labelled for what it is, never blended.

**Before `build`:** mark every request answered or unanswered. An unanswered request is passed through as-is. Never invent a plausible value to close one, and never drop it.

## `content_requests` entry

| Field | Required | Notes |
|---|---|---|
| `slide_number` | yes | Which slide needs it. |
| `missing` | yes | Specific enough to fetch. "More detail on slide 4" is not; "the three worked steps for the 3x3 case from lecture 8" is. |
| `likely_source` | yes | Where the agent thinks it lives. A guess, not an instruction. |
| `why` | yes | What the slide cannot do without it. This is what lets the Study Manager judge whether a failed fetch actually matters. |

## `checkpoint_directives`

Recorded verbatim at the outline checkpoint, passed into `build`, and **highest precedence of any input**. Two kinds:

- **Facts about the course** - "the exam only covers through chapter 6", "she said the proof won't be tested", "one page of notes is allowed". A student stating a fact about their own course is a better source than a document, and these are what stop a bracketed placeholder appearing where the answer was known.
- **Image placements** - "put the phase diagram from lecture 5 on slide 3", with the source document named.

Never solicited by asking about scope, depth, or priorities. Only written down when volunteered.

## Revision Caps

`outline` accepts 2 revision cycles. After the second, the Study Manager says plainly that the next attempt is final. `build` has no revisions: it runs to completion and reports.

## Outputs and what happens to them

| Output | Indexed? |
|---|---|
| `guide.pptx` | **Yes** - `doc_type: "study_guide"`, saved into `ctx/documents/<subject>/` |
| `preview.html` | Delivered, not indexed separately - it is a rendering of the same content |
| `scratch_dir` intermediates | Never. Deleted when the task reaches a terminal state. |

## BLOCKING flags

Returned verbatim, printed by the Study Manager ahead of the files, every time. A BLOCKING flag means one of:

- Something the guide needed is absent from every source, and the slide carries a bracketed placeholder.
- Two sources contradict each other on the same definition.
- A slide still clips at the render-fit floor, so content is present in the markup but not visible.
- A role reached the `.pptx` export with no layout for it.

Never a count. Never a paraphrase. Never suppressed because the deck otherwise looks finished - that is exactly when suppressing one does the most damage.
