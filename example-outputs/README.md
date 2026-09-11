# Example outputs

Real output from this system, not mocked up or edited. Each file here was
produced by running the pipeline described in the top-level README.

The subject matter is incidental. What these artifacts are meant to show is
whether the design decisions in the main README actually hold up in a real
run, so the notes below point at the evidence rather than at the content.

---

## Research brief — the P versus NP problem

| | |
|---|---|
| Produced by | `concept-researcher`, thorough path (`research`) |
| Files | `.md`, `.docx`, `.pdf` - the same brief in three formats |
| Connectors used | Perplexity (retrieval), Firecrawl (scraping) |

**Read the `.md`** - GitHub renders it inline, so it needs no download. The
`.docx` is the pipeline's actual deliverable, built by
`concept-researcher/scripts/build_docx.py`, and the `.pdf` is that same
document converted, since GitHub will not preview `.docx`.

**What to look at, if you only look at one thing:** section 4, Common
Misconceptions. It caught the two errors undergraduates actually make on this
topic — that NP stands for "non-polynomial", and that P != NP would by itself
secure public-key cryptography — and each row has to say *why* the confusion
arises, not just that the belief is wrong. A student who learns only that they
were wrong will make the same error again from the same cause.

**Three other things worth noticing:**

Section 2 is a definitions and notation table. It exists because a brief that a
student reads alongside their own course notes has to let them line the two up,
and because this field uses more than one convention for writing the negation.

Section 3.2 ends in a `REQUIRED ACTION` rather than an answer. The sources
describe more than one standard presentation of the Cook-Levin reduction, and
the system does not know which one the reader's course uses, so it says so
instead of picking one. Guessing there would produce a student who studied the
wrong construction.

Section 7 names the sources that were identified as useful but never read end
to end, ordered by authority tier. PDFs are carried as title-and-snippet
previews rather than scraped, so a tier 1 paper the run could not open is a
real limitation on the brief and is reported as one.

Every citation in the document resolves to a real source. The source ranking
that decided which of them got read is a deterministic script
(`concept-researcher/scripts/source_tiers.py`), not a model judgment.
