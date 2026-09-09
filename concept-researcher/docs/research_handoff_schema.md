# Concept Researcher agent handoff schema

Companion doc to `agents/concept-researcher.md`. Read this before calling `concept-researcher`
from the orchestrating chat (the Study Manager).

## Why this exists

`concept-researcher` is a Cowork subagent (Agent tool). Every invocation starts fresh
with no briefry of any other call, including its own prior stage. the Study Manager is
responsible for:

1. Deciding which stage runs next.
2. Passing that stage exactly the inputs it needs.
3. Holding the handoff object in briefry across calls and updating it after
   each call returns (see this project's CLAUDE.md, task state).
4. Running the thorough path's single human checkpoint (D1, sub-query approval, before `research` is called) and the standard path's F2
   itself - `concept-researcher` never blocks on human input internally; it returns
   and the Study Manager asks the person, then calls `concept-researcher` again with the decision.
5. Asking the person which of the 3 tiers they want, up front, with a time
   and usage estimate per tier, before calling `concept-researcher` at all.

## The 3 tiers, and where `concept-researcher` fits

the Study Manager presents this choice directly to the person before any subagent call:

1. **Quick search** - the Study Manager answers directly using its own WebSearch/WebFetch
   or bundled skills, no subagent call at all. Instant, no extra tool cost.
   This tier never touches `concept-researcher` or this schema.
2. **Standard search** - calls `concept-researcher` in `fast_search` stage. Under a
   minute, one Perplexity call.
3. **Thorough research** - calls `concept-researcher` starting at `research`. Several
   minutes, dozens of tool calls, one human checkpoint (D1, sub-query
   approval, which happens in the Study Manager before `research` is called at all).
   Once `research` starts, nothing pauses again. There is no checkpoint after
   the subsequent `report` call.

## Stages

This agent must be told explicitly which stage to run. Valid values:

| Stage | Real work done |
|---|---|
| `fast_search` | Standard path: single answer + citations, via Perplexity |
| `research` | Thorough path, call 1 of 2: receives the already-approved `sub_queries` (Part A is intake only, not decomposition), then internally runs retrieval (Part B), authority-tier ranking, floor/ceiling selection and scraping (Part C, itself C1-C3), and synthesis (Part D); returns the synthesis brief, an `index_description`, `sources_block_path`, and `restricted_sources` |
| ~~`report`~~ | Thorough path, call 2 of 2, runs immediately after `research` with no checkpoint between them: **merged into `research` as Parts E to G.** A separate call reloaded this agent's whole prompt for nothing; the source block is still read fresh in Part E, which is where the report's figures come from |

the Study Manager enters directly at `fast_search` (standard tier) or `research` (thorough
tier) based on the person's explicit choice from the 3-tier question above.

## Model

Every stage and every internal part runs on the same model (`inherit`, i.e.
whatever the Study Manager's own session is running under) - there is no per-part model
override.

## Request payload (the Study Manager -> RES)

Every first call on either tier needs:

```json
{
  "query": "the research question, exactly as the person asked it",
  "context": "a short summary the Study Manager wrote for this task, or empty string",
  "prepared_for": "who this research is for, or null if not yet known"
}
```

**`context` is a short, free-text summary the Study Manager writes itself**, not a fixed
document schema and not assumed to describe any particular kind of document.
It may draw on what's already been discussed in the conversation, what the Study Manager
has already read, or an earlier research task's findings - or be empty if
there's no supporting material. Do not fabricate placeholder context.

**`prepared_for`** is who the final report's header will name (e.g.
"CSE 151A midterm review", "personal study", "study group"). Only
relevant on the thorough tier, where `report` renders it into the brief
header. If it's not known when thorough tier is chosen, the Study Manager asks the person
directly before calling `research`.

## Handoff object

One JSON object per research task, held by the Study Manager in briefry for the life of
the task:

```json
{
  "current_stage": "research",
  "status": "in_progress",
  "tier": "thorough",
  "synthesis_revisions": 0,
  "source_revisions": 0,
  "fast_path_revisions": 0,
  "scratch_dir": "orch/cache_briefry/<task_id>/",
  "context": {
    "request": { "query": "...", "context": "...", "prepared_for": "..." },
    "sources_block_path": null,
    "sources_block_chars": null,
    "source_count": null,
    "dropped_count": null,
    "restricted_sources": null,
    "synthesis_brief": null,
    "index_description": null,
    "final_report": null,
    "sonar_result": null
  },
  "human_feedback": null
}
```

`tier` is set once by the Study Manager when the person picks "standard" or "thorough"
(quick tier never creates one of these objects at all, since it never calls
`concept-researcher`); `current_stage` starts at `fast_search` or `research`
accordingly.

**`scratch_dir` holds large intermediate text that must never travel
inline, and is a standing-permission scratch location** (see this project's
CLAUDE.md, task state and scratch space). the Study Manager sets this once at the start
of a thorough-tier task (e.g. `orch/cache_briefry/res_<slug>/`) and passes it
into the `research` call. This is scratch working data, not a project
deliverable - it does not get indexed. Both the Study Manager and `concept-researcher` may create,
overwrite, and delete files under this path without asking approval first.
`sources_block_path` (the file Part C3 of the `research` stage writes
inside `scratch_dir`) is what actually carries the scraped material forward,
both to Part D within that same call and to the later `report` call - see
"Why `sources_block` is a file, not a field" below.

Revision caps, enforced by the Study Manager, not the model itself:

- `MAX_SUBQUERY_REVISIONS = 2` (D1 "revise" -> the Study Manager rewrites the sub-queries
  itself and shows them again; no subagent call is involved, which is the
  whole point of putting the checkpoint here. Replaced the former
  `MAX_SYNTHESIS_REVISIONS` and `MAX_SOURCE_REVISIONS`, both of which looped
  back into a full `research` re-run.)

- `MAX_FAST_PATH_REVISIONS = 2` (F2 "revise" -> back to `fast_search`)

There is no cap for a post-`report` revision, because there is no checkpoint
after `report`. If a cap is hit, the Study Manager tells the agent in its next prompt
that this is the final attempt and says so plainly to the person.

## Thorough path call sequence

the Study Manager enters here directly once the person picks "thorough" and (if not
already known) has answered who the research is `prepared_for`.

0. **Human checkpoint (D1), in the Study Manager, before any subagent call.** the Study Manager writes
   1-5 sub-queries itself per the project's `orch/research_decompose_rules.md`,
   prints them with the count rationale and the `context` blob, and asks
   approve / revise as a separate question. A revise loop rewrites them in
   the Study Manager and shows them again; no subagent, no search, no scrape. Cap 2.
   **This is the thorough path's only checkpoint.** It sits here because
   everything after it is expensive and nothing after it is steerable.
1. `research` -> pass `request` (`query`, `context`, `prepared_for`), the
   approved `sub_queries` list, and `scratch_dir`. Internally, in one call,
   the agent runs:
   - **Part A (sub-query intake):** confirms the list is 1-5 non-empty
     strings and carries it forward unchanged. It does not decompose, and
     must not reword an approved sub-query.
   - **Part B (retrieval):** first writes the sub-queries as received to
     `<scratch_dir>/sub_queries.md` (kept for human review, not disposable
     scratch data), then calls
     `mcp__perplexity__perplexity_search` once per sub-query, all fired in
     parallel within one turn, collecting `retrieval_batches`. A failed
     sub-query search produces an empty batch, not an error.
   - **Part C (relevance and scraping):** ranks each sub-query's URLs by
     relevance (Part C1, title/snippet only, no fetching), runs
     `scripts/source_selection.py` for floor/ceiling selection (Part C2,
     passing `num_subqueries` so the ceiling scales as
     `min(30, 5 * num_subqueries)` rather than a flat 30; checking
     `ranking_issues` and redoing Part C1 for any query with
     `fabricated_urls` or `missing_urls` before proceeding), then scrapes
     selected HTML URLs via `mcp__firecrawl__firecrawl_scrape` (Part C3),
     paced roughly 5 seconds apart (the connected Firecrawl plan enforces a
     12-requests/minute limit), sorting each attempt into rate-limited/
     retry, 403-restricted (recorded as `restricted_sources`, never
     retried, never scraped, never cited), or dropped. PDF URLs pass
     through as title+snippet only. Writes the formatted result to
     `<scratch_dir>/sources_block.md` via `scripts/clean_and_format.py`.
   - **Part D (synthesis):** Reads `sources_block_path` itself (the file
     Part C3 just wrote), produces the analytical synthesis brief with full
     grounding/tagging discipline, and writes a short `index_description`
     for it.

   There are no revision inputs to this stage. `synthesis_feedback` and
   `source_feedback` were loops back from the removed D4 checkpoint and no
   longer exist; correction happens at D1, before the expense.

   Returns exactly one bounded response: `synthesis_brief`, `index_description`,
   `sources_block_path`, `sources_block_chars`, `source_count`,
   `dropped_count`, `restricted_sources`. If the agent reports it could not
   read `sources_block_path` in Part D, or was given no path, treat this as
   a failed stage - do not accept a brief built without it.
2. **No checkpoint here.** the Study Manager proceeds straight to `report`, and does not
   print `synthesis_brief` to the person - nothing gates on it, and printing
   it means a wall of text carrying no decision (CLAUDE.md Section 8).
3. `report` -> pass `request`, `synthesis_brief`, `scratch_dir`, `sources_block_path` (the
   same file from step 1's Part C3 - `report` must Read it itself to
   recover citation details the brief may have compressed), and
   `restricted_sources` from step 1 (carried straight through unchanged -
   `report` must not cite them or fold them into its main Sources section;
   they get their own appendix section instead). Internally, in one call,
   the agent runs exactly 2 parts:
   - **Part A (write):** writes the final report, runs
     `scripts/report_utils.py check-report-complete` and
     `extract-context-conflicts`, then `scripts/verify_citations.py` -
     correcting or dropping any unmatched URL and re-verifying before
     proceeding to Part B.
   - **Part B (format and tag verification):** checks the document against
     the structure/paragraph/table/tag rules and fixes only actual
     violations, and verifies every unsourced, inferred, or derived claim
     actually carries its `[INFERRED - VERIFY]`, `[DERIVED ESTIMATE]`, or
     `[PAYWALLED]` tag, adding one where it's missing. Then re-runs the same
     completeness/extraction/citation checks on the resulting markdown.
     Writes a short `index_description` for the finished report.

   Returns exactly one bounded response: `final_report` (markdown, plus
   `citation_count` and `context_conflicts`) and `index_description`.
4. **There is no checkpoint after this call.** the Study Manager saves the report to
   `ctx/documents/<project>/` as the deliverable and indexes it immediately,
   using the returned `index_description` for the index entry's
   `description` field.

## Standard path call sequence

the Study Manager enters here directly once the person picks "standard."

1. `fast_search` -> pass `request` (`query`, `context` - optional, may be
   empty), and `fast_path_feedback` on a revise loop. The agent calls
   `mcp__perplexity__perplexity_ask` and returns `sonar_result` (`answer`,
   `citations`).
2. **Human checkpoint (F2)** - the Study Manager presents the answer and citations in
   full as an ordinary chat message, then asks approve / revise as a
   separate question.
   - `revise` -> increment `fast_path_revisions`, call `fast_search` again
     with `fast_path_feedback` set.
   - `approve` -> done. There is no separate report/formatter pass on the
     standard tier.
3. If the standard-tier answer is itself worth persisting as a document
   (the Study Manager's judgment, not automatic), save and index it the same way as
   thorough path step 4.

## Why `sources_block` is a file, not a field

`sources_block` can legitimately run up to 150,000 characters. An Agent tool
call returns exactly one message back to whatever called it - there is no
mechanism that makes a subagent paste 150K characters of scraped text into
that message, and asking it to summarize what it scraped instead produces a
synthesis built on no real source material, which reliably yields
plausible-looking but fabricated figures. `clean_and_format.py` requires an
output path argument and writes `sources_block` there directly, returning
only a bounded pointer (`sources_block_path`) plus per-source metadata on
stdout. `synthesis` and `report` are given that path, not the text, and must
Read the file themselves. If either proceeds without a real, readable
`sources_block_path`, that is an explicit, documented failure condition, not
a silent degradation into invented content.

## Why URL citations are verified, not trusted

A model can re-type or "recall" a URL from training knowledge rather than
copying one forward from real scraped material - a fabricated citation that
can look entirely plausible. `scripts/verify_citations.py` is the
deterministic check: it builds a ground-truth URL set from
`sources_block_path` plus `restricted_sources`, then flags any URL in the
report text that does not match that set. A `false` result is a failed
stage that must be corrected (by copying the real URL back in, or dropping
the citation if no real source matches) before the report proceeds.

This is one of two checks covering the full path a URL travels:
`source_selection.py`'s `ranking_issues` output guards the `research`
stage's own Part C1 ranking step (catching a URL the model's ranking
fabricated or silently dropped), and `verify_citations.py` guards the
`report` stage's writing steps. Neither substitutes for the other.

## There is no fact-check stage

This pipeline does not run an independent verification pass over the
finished report's claims. `verify_citations.py` checks that every URL is
real and was actually retrieved this run, but nothing checks whether a
correctly cited URL has been attached to a wrong or invented figure. That is
a different failure class, and it is not covered.

What stands in its place is tag discipline (`[INFERRED - VERIFY]`,
`[DERIVED ESTIMATE]`, `[PAYWALLED]`) applied during writing and re-checked
in the report stage's Part B. If asked whether a delivered report has been
fact-checked, say plainly that it has not.

`scripts/fact_check_utils.py` ships with this plugin and is called by no
stage. Leave it in place. Do not wire it into a stage without being told to:
an always-on verification pass costs a full read-the-report pass plus up to
15 Perplexity calls on every thorough run, whether or not the person wanted
that level of checking.

## Known limitations

- **Perplexity/Firecrawl tool names are not assumed fixed.** A session may
  have these connectors wired through a proxy where the real tool name has
  an extra segment (e.g. `mcp__remote-devices__perplexity__perplexity_search`
  instead of `mcp__perplexity__perplexity_search`). This agent's `tools`
  frontmatter is unrestricted (`tools: "*"`) so no permissions allowlist
  blocks whichever name is real; its own instructions say to use
  `ToolSearch` to find that name before giving up, rather than assume the
  literal name works or fabricate a result if no working tool is found.
- **Sub-query sizing (1-5) is a judgment call, checked only for range
  compliance, not for whether the chosen count actually matches the
  query's complexity.** The reasoning behind the chosen count is written to
  `<scratch_dir>/sub_queries.md` before searching starts, specifically so a
  human can review it afterward.
- **The source ceiling's per-sub-query multiplier (5) is a judgment call**,
  not derived from measured retrieval-batch data. May need revisiting as
  real usage accumulates.
- **Prioritizing supplied `context` over the actual query is addressed but
  not mechanically guaranteed against.** `context` is meant to inform the
  research only where it's actually relevant to the query, never to
  narrow or substitute for it - this is prompt-level guidance, not something
  enforced by a script.
- **Content/numeric fabrication is addressed by grounding rules and two
  tags (`[INFERRED - VERIFY]`, `[DERIVED ESTIMATE]`), not fully closed.**
  Any claim attributed to `context` must carry an actual quoted fragment;
  any number calculated from a cited benchmark must show its arithmetic and
  carry `[DERIVED ESTIMATE]`. This is defense in depth, not a guarantee -
  the model could still fail to apply a tag it should have.
- **Citation count vs. report depth.** The scraped-source pool (up to the
  sub-query-scaled ceiling) is a candidate pool, not a citation quota -
  citing 8-15 sources in real depth is preferred over shallow coverage of
  every scraped source. This is a prompt-level instruction; nothing
  mechanically enforces a minimum depth per source.
- **Firecrawl rate limiting and paywalled sources.** The connected Firecrawl
  plan enforces a 12-requests/minute limit, so scrape calls are paced
  roughly 5 seconds apart with a bounded retry on 429s. 403-restricted
  sources are recorded separately, never scraped or cited, and surfaced to
  the reader as a distinct appendix rather than silently dropped.
- **Perplexity/Firecrawl endpoint substitution.** This agent uses the
  connected Perplexity and Firecrawl MCP tools (`perplexity_search`,
  `perplexity_ask`, `firecrawl_scrape`) rather than calling either vendor's
  raw HTTP API directly. Some tuning parameters available on the raw
  endpoints may not be independently configurable through the MCP tools.
- **No native interrupt/resume.** A checkpoint is implemented by the Study Manager
  simply not calling `concept-researcher` again until it has a human decision, not
  by any pause/resume mechanism inside the subagent call itself.
- **Truncation/completeness detection is heuristic, not exact.** A subagent
  generating its own output has no authoritative "was this truncated"
  signal to check, so `check-report-complete` substitutes a heuristic
  (missing Sources section, or text ending mid-sentence). This can produce
  false negatives on a report that is complete but happens to end oddly -
  treat a `complete: false` result as "look at this," not certain proof of
  truncation.
