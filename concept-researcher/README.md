# Concept Researcher Plugin

The Concept Researcher agent for the Multiagent Study & Tutoring Assistant.

## Overview

Course material assumes things it never teaches. A lecture invokes a result from a prerequisite course, a textbook skips a derivation, a problem set expects a technique nobody demonstrated. This agent researches those gaps externally and returns something the student can actually study from: a cited brief that says plainly which claims rest on a peer-reviewed source, which rest on a course page, and which could not be verified at all.

Two paths, chosen by the student, never by the agent:

- **`fast_search`** — a single search-backed answer with citations. Minutes.
- **`research`** — the entire pipeline in one call: retrieval, authority ranking, selection, scraping, synthesis, writing, citation verification, and document build, ending in a finished `.docx`. Twenty to thirty minutes.

## The design decision that matters: sources are ranked by script, not by judgment

The model supplies candidate URLs. It does not decide which are worth reading.

That decision runs in `scripts/source_tiers.py` as a deterministic rule, because "which sources look best to me" is exactly the latitude that produces a study guide resting its central claim on a homework-answers site. The ladder, highest first:

| Tier | What it is |
|---|---|
| 1 | Peer-reviewed literature — journals, conference proceedings, publishers, DOI, PubMed |
| 2 | University and course material — `.edu` / `.ac.uk` departments, official course pages, open courseware |
| 3 | Preprints and scholarly indexes — arXiv, bioRxiv, SSRN, Semantic Scholar |
| 4 | Official technical documentation and standards — language and library docs, RFCs, W3C, NIST, ISO |
| 5 | Established reference works — subject encyclopedias, technical publishers of record |
| 6 | General and user-generated web — never the sole basis for a claim |

Budget is spent strictly top-down. Recency sorts *within* a tier and never across one, so a recent blog post never outranks an older published paper. Tier 6 is never scraped: it can still be cited from a search answer, but it does not consume budget and it cannot carry a claim alone.

**Homework-answer and note-selling sites (Chegg, Course Hero, Quizlet, Studocu and similar) sit in tier 6 deliberately.** Their content is unattributed, of unverified accuracy, and reproduces other students' errors at scale. A study guide built on them is precisely the failure this ladder exists to prevent.

An unrecognized domain defaults to tier 6 and is reported back in `unclassified_domains`, so the ladder gets extended on purpose rather than drifting.

`author_domains` promotes a researcher's or lab's own site to tier 2 for their own work — authors publishing about their own result are primary evidence for it, and no domain pattern can infer that relationship. The Study Manager names those domains explicitly when the query concerns a specific paper or group.

## What the brief contains

| Section | Why it is there |
|---|---|
| 1. Short Answer | A student who reads only this should already be less stuck |
| 2. Definitions and Notation | So the brief can be lined up against the student's own course notation |
| 3. Explanation by Topic | The substance, with inline citations |
| 4. Common Misconceptions | Names *why* each confusion arises, not just that the belief is wrong |
| 5. Open Questions and What to Ask | What is genuinely unsettled, and the question worth putting to an instructor |
| 6. Method, Scope and Source Basis | Deliberately late: findings first, method available when interrogating them |
| 7. Sources | Full citations, plus everything identified but never read end to end, ordered by tier |
| 8. Access-Restricted, Not Reviewed | Only when non-empty |

Section 7's "identified but not retrieved in full" list is not boilerplate. PDFs are carried as title-and-snippet previews rather than scraped, so a tier 1 paper the run could not open is a real limitation on the brief, and it is named as one.

## Plugin Structure

```
concept-researcher/
├── .claude-plugin/
│   └── plugin.json
├── agents/
│   └── concept-researcher.md          # Full agent definition, parts A-G
├── docs/
│   └── research_handoff_schema.md     # Task state shape and call sequence
├── scripts/
│   ├── source_tiers.py                # Authority ladder + ranking (deterministic)
│   ├── source_selection.py            # Floor/ceiling selection (deterministic)
│   ├── clean_and_format.py            # Dedupe, truncate, build sources block
│   ├── verify_citations.py            # Citation/link verification
│   ├── report_utils.py                # Shared helpers
│   ├── fact_check_utils.py            # Ships unused; see note below
│   └── build_docx.py                  # Renders the final brief
└── README.md
```

## Why every deterministic step is a real script

Tier ranking, selection, dedupe, truncation, citation verification and the document build all run as bundled Python via Bash, not as model self-report. A model asked to "rank these by authority and report what you did" can fabricate a URL into the ranking or silently drop one, and nothing downstream catches it. A script cannot: every URL given is returned, none invented, none lost. That removes an entire class of failure rather than detecting it after the fact.

`fact_check_utils.py` ships unused on purpose. It is not wired into the pipeline; leave it in place and do not connect it without a deliberate decision to do so.

## Checkpoints

**None inside this agent.** The only checkpoint in the research flow is the sub-query approval, which happens in the Study Manager *before* this agent is called — deliberately, because it sits before any search, scrape or synthesis is paid for. Redirecting the research there costs a few hundred tokens instead of a full run.

This agent never decomposes a query. It receives the approved `sub_queries` list and must not reword it.

## Connectors Required

- **Perplexity** — retrieval
- **Firecrawl** — scraping

Both are configured through Claude's developer settings; see the project README for setup.

## See Also

- This project's `CLAUDE.md` — full routing logic for the research flow
- `orch/research_decompose_rules.md` — how sub-queries are written and approved
- `docs/research_handoff_schema.md` — task state shape and call sequence
