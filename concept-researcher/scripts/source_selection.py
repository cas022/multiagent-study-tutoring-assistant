#!/usr/bin/env python3
"""
source_selection.py

Deterministic floor/ceiling source selection. The model (the Concept Researcher
itself, in the relevance part) only RANKS each sub-query's URLs
best-to-worst using title/snippet text. This script decides what actually
gets scraped, and that decision is deterministic Python, not a model call.

**The ceiling scales with sub-query count:** `min(30, 5 * num_subqueries)`,
unless the caller explicitly passes its own `ceiling` (supported for testing
or a deliberate one-off). Five sources per sub-query, hard-capped at 30, so
a genuinely complex 5-sub-query question can still reach 30 while a narrow
1-sub-query question tops out at 5. A flat cap regardless of sub-query count
would let a simple query spend the pipeline's serial Firecrawl scraping time,
and synthesis's input-processing time, on breadth it never asked for.

The floor (default 2) guarantees every sub-query keeps at least its own top
2 URLs, so one weak sub-query cannot be shut out entirely by stronger
candidates elsewhere.

`ranking_issues` flags per-query problems with
the model's own Part-1 ranking, before selection even runs:

- `fabricated_urls`: URLs the ranking listed for that query that do not
  actually appear in `retrieval`'s real results for it. These were NEVER a
  selection risk - `select_sources_for_scraping` below only ever pulls from
  `result_by_url`, which is built strictly from `batches` (the real
  retrieval output), so a fabricated URL in a ranking silently never gets
  selected or scraped. They are reported here purely as a signal that the
  ranking step itself produced unreliable output worth flagging, not because
  anything downstream was actually put at risk by it.
- `missing_urls`: real URLs from that query's retrieval results that the
  ranking dropped entirely (contrary to the "do not exclude any URL"
  instruction in the agent's own ranking rules). Unlike fabricated URLs,
  this IS a real risk - a genuinely relevant source can be silently lost if
  it never appears anywhere in `remaining_by_query`, since nothing outside
  the ranking currently re-adds a dropped URL. If `ranking_issues` reports
  missing URLs, the caller should re-run ranking (Part 1) before proceeding
  to selection, the same way a failed `validate-subqueries` check requires
  redoing `decompose`.
"""

import json
import sys

# Mirrors source_tiers.MAX_SCRAPED_TIER. Kept as a literal rather than an
# import so this script stays runnable on its own; if the ladder's cutoff
# moves, both places change.
_MAX_SCRAPED_TIER = 5

DEFAULT_FLOOR = 2
DEFAULT_CEILING = 30
CEILING_PER_SUBQUERY = 5


def compute_default_ceiling(num_subqueries, hard_cap=DEFAULT_CEILING, per_subquery=CEILING_PER_SUBQUERY):
    """min(hard_cap, per_subquery * num_subqueries), with num_subqueries
    floored at 1 so a caller passing 0 (should not happen - decompose always
    produces at least 1 sub-query) does not zero out the ceiling entirely."""
    return min(hard_cap, per_subquery * max(int(num_subqueries), 1))


def is_pdf(url: str) -> bool:
    return url.lower().endswith(".pdf")


def diagnose_ranking_issues(batches, rankings):
    ranking_by_query = {rk["query"]: rk.get("ranked_urls", []) for rk in rankings}
    issues = []
    for batch in batches:
        query = batch["query"]
        real_urls = {r["url"] for r in batch.get("results", [])}
        ranked_urls = set(ranking_by_query.get(query, []))

        fabricated = sorted(ranked_urls - real_urls)
        missing = sorted(real_urls - ranked_urls)

        if fabricated or missing:
            issues.append(
                {
                    "query": query,
                    "fabricated_urls": fabricated,
                    "missing_urls": missing,
                }
            )
    return issues


def select_sources_for_scraping(batches, rankings, floor=DEFAULT_FLOOR,
                                ceiling=DEFAULT_CEILING, tiers=None,
                                max_scraped_tier=None):
    """Floor/ceiling selection, restricted to tiers worth scrape budget.

    **The tier gate is applied BEFORE the floor, and that ordering is the
    whole point.** Ranking already sorts tier 6 to the back, so on a healthy
    sub-query those URLs never reach the ceiling anyway. The dangerous case
    is a sub-query whose results are ALL tier 6: the floor guarantees each
    sub-query its own top `floor` URLs unconditionally, so without this gate
    it would force homework-answer pages into the scrape set - in exactly
    the situation where scraping them is least defensible.

    Filtering first makes the floor mean "top N *eligible* URLs". A
    sub-query with no eligible candidates contributes none and is named in
    `tier_excluded`, rather than quietly lowering the evidence bar.

    `tiers` is the `{url: tier}` map `source_tiers.py --rank` returns. When
    it is absent, no gate is applied and every URL stays eligible: callers
    that never ranked have nothing to gate on, and silently dropping their
    sources would be worse than passing them through.
    """
    if max_scraped_tier is None:
        max_scraped_tier = _MAX_SCRAPED_TIER

    result_by_url = {}
    for batch in batches:
        for r in batch.get("results", []):
            result_by_url.setdefault(r["url"], r)

    ranking_by_query = {rk["query"]: rk["ranked_urls"] for rk in rankings}

    def _eligible(url):
        if not tiers:
            return True
        return tiers.get(url, max_scraped_tier + 1) <= max_scraped_tier

    tier_excluded = []

    selected = []
    selected_urls = set()

    # Step 1: floor - top `floor` ELIGIBLE URLs per sub-query.
    remaining_by_query = {}
    for batch in batches:
        query = batch["query"]
        ranked = ranking_by_query.get(query) or [r["url"] for r in batch.get("results", [])]
        gated = []
        for url in ranked:
            if _eligible(url):
                gated.append(url)
            else:
                tier_excluded.append(url)
        ranked = gated
        floor_urls = ranked[:floor]
        remaining_by_query[query] = ranked[floor:]

        for url in floor_urls:
            if url in selected_urls or url not in result_by_url:
                continue
            selected.append(result_by_url[url])
            selected_urls.add(url)

    # Step 2: round-robin the remainder until the ceiling is hit or the
    # shared pool is exhausted.
    active_queries = [q for q, urls in remaining_by_query.items() if urls]
    while active_queries and len(selected) < ceiling:
        for query in list(active_queries):
            if len(selected) >= ceiling:
                break
            remaining = remaining_by_query[query]
            while remaining:
                url = remaining.pop(0)
                if url in selected_urls or url not in result_by_url:
                    continue
                selected.append(result_by_url[url])
                selected_urls.add(url)
                break
            if not remaining:
                active_queries.remove(query)

    return selected[:ceiling], sorted(set(tier_excluded))


def _load_payload(argv):
    """Read the JSON payload from --input <path> if given, else stdin.

    Callers write the payload with the Write tool and pass a path rather than
    piping it in via `echo '<json>' | python3 ...`. Piping costs the caller a
    full re-emission of the payload as output tokens - for scraped pages and
    report prose, tens to hundreds of thousands of characters - and any
    apostrophe in the content breaks the single-quoted shell string outright.
    stdin remains accepted.
    """
    if "--input" in argv:
        i = argv.index("--input")
        if i + 1 >= len(argv):
            print("--input requires a path", file=sys.stderr)
            sys.exit(2)
        path = argv[i + 1]
        del argv[i:i + 2]
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return json.load(sys.stdin)


def main():
    argv = sys.argv[1:]
    payload = _load_payload(argv)
    batches = payload["batches"]
    rankings = payload.get("rankings", [])
    floor = payload.get("floor", DEFAULT_FLOOR)

    if "ceiling" in payload:
        ceiling = payload["ceiling"]
    else:
        num_subqueries = payload.get("num_subqueries")
        if num_subqueries is None:
            # Back-compat fallback if a caller omits both - preserves the
            # old flat-30 behavior rather than erroring, but callers should
            # pass num_subqueries going forward.
            ceiling = DEFAULT_CEILING
        else:
            ceiling = compute_default_ceiling(num_subqueries)

    # `tiers` comes straight from source_tiers.py --rank. Passing it is what
    # arms the tier gate; omitting it leaves every URL eligible.
    selected, tier_excluded = select_sources_for_scraping(
        batches, rankings, floor=floor, ceiling=ceiling,
        tiers=payload.get("tiers"),
    )
    ranking_issues = diagnose_ranking_issues(batches, rankings)

    html_urls = [r["url"] for r in selected if not is_pdf(r["url"])]
    pdf_urls = [r["url"] for r in selected if is_pdf(r["url"])]

    json.dump(
        {
            "selected": selected,
            "selected_count": len(selected),
            "html_urls": html_urls,
            "pdf_urls": pdf_urls,
            "ranking_issues": ranking_issues,
            "tier_excluded": tier_excluded,
            "tier_excluded_count": len(tier_excluded),
            "ceiling_used": ceiling,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
