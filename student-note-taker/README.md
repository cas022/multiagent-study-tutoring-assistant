# Student Note Taker Plugin

The Student Note Taker agent for the Multiagent Study & Tutoring Assistant.

## Overview

The Note Taker converts lecture content (a Zoom AI summary, the student's own notes, a pasted transcript, or an uploaded file) into structured lecture notes, ready for the Study Manager to save and index.

**Architecture note (important):** this plugin is transform-only. It does not search Zoom, does not call any meeting connector, and does not resolve ambiguous recording matches. All of that is the Study Manager's (main conversation's) job — see "Why the split" below. The subagent's only responsibility is turning already-fetched content into the structured notes schema.

**Output:** structured notes in the required schema (LECTURE / DOCUMENT TYPE / SUMMARY / KEY FACTS / FLAGS), plus a short index description. No separate human-readable document is authored by this agent — Zoom's own summary (or the student's manual input) already serves that role and is saved verbatim by the Study Manager.

## What the schema is built for

The KEY FACTS block is shaped around what a student actually needs later, not around what a generic summarizer would produce:

- **Definitions and Results Introduced** captures things verbatim, in the course's own notation, because that is what the student is graded on.
- **Instructor Emphasis** captures the offhand "this will be on the midterm" that is often the single most useful line in an hour of recording and is trivially easy to lose in a generic summary.
- **Open Questions** captures what was deferred, which is where the next lecture usually starts.
- **FLAGS** captures transcription damage. Automated transcripts mangle technical vocabulary constantly, and a silently "corrected" formula is worse than a flagged one.

## Why the split

Personal MCP connectors (like a student's own Zoom connection) are not reliably inherited by an Agent-tool subagent's execution environment, unlike connectors a plugin can bundle directly. Rather than have `note-taker` fail on a missing tool, the responsibilities are split: the Study Manager (the main conversation, which has real, working connector access) does the recording search and fetch itself, then hands the raw fetched content to `note-taker` purely for the transformation into structured notes.

## Plugin Structure

```
student-note-taker/
├── .claude-plugin/
│   └── plugin.json             # Plugin metadata (name, version, author, keywords)
├── agents/
│   └── note-taker.md           # Complete agent definition: transform-only process, output schema, error handling
├── docs/
│   └── note_handoff_schema.md  # Task state specification, handoff object shape, and the Study Manager's fetch responsibilities
└── README.md                   # This file
```

## Workflow

```
Student provides lecture description (or meeting ID / pasted transcript / file)
    ↓
Study Manager searches for the recording using its OWN connector access
    ↓
[Ambiguous search?] → Study Manager itself asks the student which recording they meant
    [No]  → Study Manager fetches recording content directly
    [Yes] → Study Manager asks, then fetches once resolved
    ↓
Study Manager packages fetched content into task_spec.fetched_content
    ↓
Study Manager calls note-taker in "transform" stage
    ↓
note-taker transforms content into structured notes per agents/note-taker.md
    ↓
Returns structured notes + lecture_data + index_description + flags
    ↓
Study Manager saves BOTH the verbatim fetched content and the structured notes
to ctx/documents/<subject>/, indexes the entry
```

## Integration with the Study Manager

Per this project's CLAUDE.md, the Study Manager's job is:

1. Ask which lecture to process (natural language description, meeting ID, or pasted input).
2. If a description was given, search for the recording **using the Study Manager's own connector tools** — not the subagent's.
   - Multiple matches → the Study Manager prints them and asks the student which one, as an ordinary multiple-choice question.
   - No match → ask for a meeting ID, transcript, or file.
3. Fetch the recording's content directly (the Study Manager's own tools), handling permission/not-found/no-summary cases itself, falling back to asking for manual input as needed.
4. Package the fetched content (or the student's pasted input) into `task_spec.fetched_content` and call `note-taker` in `transform` stage.
5. Once `status` is `done`, save the lecture's document into `ctx/documents/<subject>/` (the verbatim fetched content plus the structured notes) and index it, using the returned `index_description`. Ask "What next?" and route accordingly.

## Error Handling

| Scenario | Who handles it | Action |
|---|---|---|
| Recording search returns no matches | Study Manager | Asks for meeting ID / transcript / file |
| Recording search ambiguous (multiple matches) | Study Manager | Prints candidates, asks student which, then fetches |
| Permission denied (403) | Study Manager | Asks for manual input, records a `fetch_flags` entry to pass to note-taker |
| Not found (404) | Study Manager | Asks for clarification or manual input |
| No AI summary available | Study Manager | Asks for manual input, or proceeds with the student's own notes only (flagged) |
| No content at all reaches the subagent | note-taker | `status: "failed"`, flags it, uses the "no content" template |
| Conflicting facts within given content | note-taker | Reports both, flags the conflict |
| Garbled technical vocabulary in a transcript | note-taker | Corrects and flags where unambiguous, transcribes and flags where not |

## Known Limitations

- **Subagents don't reliably reach personal connectors.** This is the core limitation that shaped this plugin's design — see "Why the split" above.
- **No custom Zoom summary templates.** Uses Zoom's default AI-generated summaries; custom templates require Zoom account admin configuration, outside this agent's scope.
- **Automated transcripts are lossy on notation.** Anything written on a board and not spoken aloud does not reach the transcript at all. The agent flags what it can detect as missing, but a transcript-only lecture record is structurally weaker than one paired with the slides, which is why slides get indexed as their own documents.
- **The student's own notes are a supplement, never a silent fallback.** If the AI summary is missing or inaccessible, the Study Manager is expected to ask for manual input rather than quietly substituting partial personal notes as if they were complete — and to flag that gap explicitly when it does fall back.

## See Also

- This project's `CLAUDE.md` — full routing logic for the notes flow in the Study Manager
- `docs/note_handoff_schema.md` — task state shape and the Study Manager's fetch responsibilities
