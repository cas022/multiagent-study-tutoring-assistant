# Research decompose rules (Study Manager owned)

The Study Manager reads this file when entering a standard or thorough research
flow, and not otherwise. It is not loaded on every session.

Decomposition belongs to the Study Manager, not to `concept-researcher`, so that
the pipeline's human checkpoint can sit immediately after it: before any search
call, any scrape, or any synthesis is paid for. `concept-researcher` receives the
sub-queries already approved and does not generate or reword them.

---

## What the Study Manager produces

Between 1 and 5 targeted search queries, plus a one-line note on why that count
was chosen. Nothing else. These go to the student for approval before
`concept-researcher` is called.

## How to judge the count

The count is a judgment call about the question's actual complexity, not a fixed
number:

- A single well-defined concept with a standard treatment ("what is the
  chain rule for partial derivatives") typically needs 1-2.
- A concept plus its application, or a concept the student is confused about in a
  specific way ("why does backpropagation need the activation function to be
  differentiable"), needs 2-3.
- A question spanning several genuinely distinct sub-questions, comparing
  competing approaches, or asking how a field's treatment of something has
  changed, needs 4-5.

When in doubt between two counts, prefer the higher one. The count directly sets
the scrape ceiling downstream (`min(30, 5 * num_subqueries)`), so a padded count
is not free: it buys the run permission to scrape more.

## Rules for the queries themselves

- Each query targets a distinct sub-question, not the same question rephrased.
- **Use the field's own technical vocabulary, not the student's paraphrase.** A
  student asking "that thing where the matrix doesn't change direction" is asking
  about eigenvectors, and the query should say eigenvectors. Searching the
  colloquial phrasing reliably surfaces tutorial content of unknown quality;
  searching the technical term surfaces the literature.
- **Pair the concept with the kind of source that would actually settle it.** At
  least one query should combine the concept name with a term that targets
  authoritative treatment rather than general explanation: "original paper",
  "proof", "derivation", "lecture notes", "survey", the name of a standard
  textbook in the field, or the name of the researcher associated with the
  result. Generic topic queries reliably surface content farms and SEO blog
  posts; they do not reliably surface the primary treatment.
- Ground queries in whatever specific details `context` actually provides —
  the course's level, the notation in use, the specific point of confusion,
  what the lecture already covered — **when those details are relevant to the
  query as asked.**
- Do not exclude any file type or source type. Course notes, published papers and
  primary references are often published only as PDFs and are frequently the most
  authoritative sources available. Do not steer away from them.
- Where a concept has a known name collision across fields (a "kernel" in linear
  algebra, in statistics, and in operating systems), at least one query must
  disambiguate explicitly by naming the field.

## The rule that matters most

**`context` sharpens the query. It never narrows it.**

The pairing requirement above is conditional on relevance, not on whether
`context` merely mentions a course somewhere. A query asking a broad conceptual
question does not get forced into one course's frame just because `context`
happens to reference that course. The failure this prevents is a research run
that quietly becomes about whatever the student's syllabus said, rather than
about what was actually asked.

The test: would a query pairing *the query's own actual subject* with an
authoritative source type surface more relevant results than a generic topic
search? If yes, do it. If the query's subject and `context`'s course material are
different things, do not force the pairing.

Treat `context` as evidence that can inform how the research is aimed, never as a
frame that overrides or substitutes for what was actually asked. The query, not
`context`, is the primary object of this research.

## Validation

Confirm the count is between 1 and 5 before showing them. That is the whole
check, and the Study Manager does it by eye — there is no script to run.

The count check is the only mechanical part. Whether the count matches the
question's real complexity is exactly what the human checkpoint is for.

## The checkpoint

**Open with this preamble, verbatim, with `N` replaced by the actual count.**
Do not reword it per run and do not add to it.

> Your question has been split into N sub-queries. Each is run as its own
> search, so between them they decide what evidence this brief can be built on.
> Approve them if they aim at what you want explained, or tell me what to change.

When the count is 1, use this instead, so the sentence reads correctly:

> Your question is being run as a single targeted search, which decides what
> evidence this brief can be built on. Approve it if it aims at what you want
> explained, or tell me what to change.

Then print, as an ordinary chat message:

1. The sub-queries, numbered. **Any sub-query not written in English is shown
   with an English rendering directly beneath it**, so the student can review
   what it actually asks. The original string is what gets searched; the English
   line is there to be read. Show both, never the English alone.
2. The one-line rationale for the count.
3. The `context` blob being used, shown once, in full. It is shared across all
   sub-queries — there is no per-sub-query context in this system, and what
   reaches the search API is the sub-query string alone.

Then ask, as a separate multiple-choice question, whether to approve or revise.
Never put the sub-queries inside the question tool's option labels.

On revision: rewrite the sub-queries here, in the Study Manager, from the
student's feedback and show them again. This loop costs nothing but a few hundred
tokens, which is the entire point of moving the checkpoint here. Feedback may
target the queries, the count, or the context blob; a change to the context blob
means rewriting it and re-deriving the queries from it.

After 2 revision cycles without approval, say plainly that the next attempt is
final, matching the revision-cap discipline used everywhere else in this project.
