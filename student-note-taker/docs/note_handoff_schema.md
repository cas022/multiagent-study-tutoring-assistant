# Note Taker Handoff Schema

The Note Taker is a single-stage, stateless **transform-only** agent. It does not search Zoom or call any meeting connector — it receives already-fetched lecture content and returns structured notes. Discovery and fetching are the Study Manager's responsibility (the main conversation, which has actual access to the student's Zoom connection); the subagent's job is purely to structure whatever content it is handed.

## Why the split

Agent-tool subagents do not reliably inherit a user's personal MCP connectors the way the main conversation does. Connectors bundled with a plugin (for example the search and scraping tools used by `concept-researcher`) can be granted directly to a subagent; a user's own OAuth-connected personal tools cannot be assumed to propagate the same way. So the search and fetch step happens in the main conversation (the Study Manager), which has proven connector access, and the subagent is scoped down to only the part that benefits from isolation: turning raw content into the structured notes schema.

## Task State Shape

```json
{
  "task_id": "notes_<slug>_<date>",
  "agent": "note-taker",
  "task_state": {
    "current_stage": "transform",
    "status": "in_progress | done | failed"
  },
  "task_spec": {
    "fetched_content": {
      "source_type": "zoom | pasted | file",
      "lecture_topic": "<string or null>",
      "lecture_date": "<string or null>",
      "ai_summary": "<string or null>",
      "my_notes": "<string or null>",
      "participants": "<string or null>",
      "duration": "<string or null>",
      "raw_text": "<string or null>",
      "fetch_flags": ["<string>", "..."]
    }
  },
  "context": {
    "lecture_notes": null,
    "lecture_data": null,
    "index_description": null
  },
  "flags_summary": [],
  "human_feedback": null
}
```

## Stage Definition

| Stage | Purpose | Input | Output | Checkpoints |
|-------|---------|-------|--------|-------------|
| `transform` | Turn already-fetched lecture content into structured notes | `task_spec.fetched_content` | `context.lecture_notes`, `context.lecture_data`, `context.index_description`, `flags_summary` | None |

## The Study Manager's Responsibilities (before calling note-taker)

1. **Ask the student** for a lecture description, meeting ID, or pasted content.
2. **If a description was given:** use the Study Manager's own Zoom connector tools (available directly in the main conversation) to search for the recording.
   - Exactly one match → fetch it directly.
   - Multiple matches → the Study Manager itself prints the candidates (topic, date, host, duration) and asks the student which one they meant, as a plain multiple-choice question.
   - No match → ask the student for a meeting ID, pasted transcript, or file.
3. **Fetch the recording's content** using the Study Manager's own connector tools once a specific recording is identified:
   - 403 (permission denied) → flag it, ask the student to paste the transcript or upload a file instead.
   - 404 (not found) → flag it, ask for clarification or manual input.
   - No summary available → flag it, ask for manual input, or proceed with the student's own notes only if available, flagging that the AI summary was missing.
4. **Package the result** into `task_spec.fetched_content` exactly as shown above, including any `fetch_flags` from step 3, and call `note-taker` in `transform` stage.

## Task Spec — `fetched_content` Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `source_type` | string | yes | `"zoom"`, `"pasted"`, or `"file"`. |
| `lecture_topic` | string or null | no | Title/subject, if known. |
| `lecture_date` | string or null | no | When it happened, if known. |
| `ai_summary` | string or null | no | Zoom AI-generated summary text, if fetched. |
| `my_notes` | string or null | no | The student's own annotations, if available. |
| `participants` | string or null | no | Attendee info, if fetched. Rarely study-relevant. |
| `duration` | string or null | no | Length, if known. |
| `raw_text` | string or null | no | Pasted transcript or file content, when `source_type` is `pasted` or `file`. |
| `fetch_flags` | array of strings | no | Anything the Study Manager already flagged during its own fetch attempt. Carried forward into the agent's own `flags_summary`. |

At least one of `ai_summary`, `my_notes`, or `raw_text` must be populated, or the agent has nothing to transform and will return `status: "failed"`.

## Context Output

| Field | Type | Required | Notes |
|--------|------|----------|-------|
| `lecture_notes` | string | yes | The complete structured notes in the required schema (LECTURE / DOCUMENT TYPE / SUMMARY / KEY FACTS / FLAGS). |
| `lecture_data` | object | yes | Metadata echoed back: `{ "topic", "date", "source_type" }`. |
| `index_description` | string | yes | 1-2 plain-language sentences for the Study Manager to use as the index entry's `description`. |

## Checkpoints

**None inside the subagent.** The only checkpoint in the notes flow — resolving an ambiguous recording search — happens entirely in the Study Manager, before `note-taker` is ever called. By the time the subagent runs, the recording is already unambiguous and its content is already fetched.

## Error Paths (inside the subagent)

| Condition | Action |
|-----------|--------|
| No content at all in `fetched_content` | `status: "failed"`, flag "No content was available to summarize for this lecture." |
| `fetch_flags` indicates a permission failure with no fallback content | Use the "Access-blocked notes" template, carry the flag forward. |
| Conflicting facts within given content | Report both, flag the conflict. |
| Garbled technical term | Correct it and flag the correction where unambiguous; transcribe and flag where not. |

All connector-side error handling (403, 404, ambiguous search, no summary available) happens in the Study Manager before the subagent is called — see "The Study Manager's Responsibilities" above.

## Outputs

The subagent itself returns the structured notes in `context.lecture_notes`, plus `context.lecture_data` and `context.index_description` for indexing.

The Study Manager is responsible for saving the lecture's record into `ctx/documents/<subject>/`:

1. The verbatim fetched content — `task_spec.fetched_content`'s `ai_summary` (plus `my_notes` if both exist) or `raw_text`, saved exactly as fetched or pasted, with no restructuring. This is a copy-over, never a rewrite — if the source already formatted it, that formatting is preserved unchanged.
2. `context.lecture_notes` from the subagent, saved as the structured half of the same record.

Both get indexed immediately, using `context.index_description` for the index entry's `description` field.

## Revision Caps

None. Single-pass transform, no loop, no checkpoint.

## Duration and Model Tier

- Expected runtime: under 5 seconds (pure text transformation, no tool calls)
- Model: configured via the agent's `model` frontmatter field, currently `inherit`.
