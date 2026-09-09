#!/usr/bin/env python3
"""
source_tiers.py - deterministic source-authority classification and scrape
selection.

The model supplies candidate URLs. This script decides which of them are
worth spending scrape budget on, and in what order. That decision is a rule,
not a judgment call: source quality is the whole point of a research brief a
student will study from, and "which sources look best to me" is exactly the
kind of latitude that produces a brief resting its central claim on a
homework-answers site.

The ladder, highest authority first:

  1  Peer-reviewed literature       journals, conference proceedings,
                                    publishers, DOI resolvers, PubMed
  2  University and course material .edu / .ac.uk departments, official
                                    course pages, open courseware
  3  Preprints and scholarly index  arXiv, bioRxiv, SSRN, Semantic Scholar
  4  Official technical docs and    language/library documentation, RFCs,
     standards bodies               W3C, NIST, ISO
  5  Established reference works    subject encyclopedias, technical
                                    publishers of record
  6  General and user-generated web never the sole basis for a claim

Selection spends budget strictly top-down. Recency sorts WITHIN a tier and
never across one, so a recent blog post never outranks an older published
paper. Tier 6 is never scraped: it can still be cited from a search answer,
but it does not consume budget and it cannot carry a claim alone.

Homework-answer and note-selling sites (Chegg, Course Hero, Quizlet and
similar) sit in tier 6 deliberately. Their content is unattributed, of
unverified accuracy, and frequently reproduces other students' errors. A
study guide built on them is exactly the failure this ladder exists to
prevent.

An unknown domain lands in tier 6 and is reported in `unclassified_domains`,
so the ladder grows deliberately rather than silently mis-ranking a journal
nobody has added yet.

Usage:
    python3 source_tiers.py --rank --input batches.json     <- this pipeline
    python3 source_tiers.py --input candidates.json
    python3 source_tiers.py --self-test

`--rank` is the mode this pipeline uses. It takes the raw retrieval batches
and returns `rankings` in exactly the shape `source_selection.py` expects,
with each sub-query's URLs ordered by authority tier rather than by a model's
sense of relevance. Every URL given is returned, none dropped and none
invented, which is why replacing the model's ranking step with this removes
the whole class of fabricated-or-missing-URL failures that ranking-drift
detection existed to catch.

    Input:  {"batches": [{"query": "...", "results": [{"url","title","snippet"}]}],
             "author_domains": ["..."]}
    Output: {"rankings": [{"query": "...", "ranked_urls": [...]}],
             "tiers": {"<url>": 1, ...},
             "tier_counts", "unclassified_domains", "author_promoted"}

`tiers` matters downstream as much as the ordering: a PDF that is carried as
a title-and-snippet preview rather than scraped still needs its tier, so the
brief can say which of the papers it could not read actually mattered.

`--write-list` writes the selected URLs, one per line, to a file. That file
is the scrape allowlist: the scrape loop iterates it and nothing else, and
`clean_and_format.py --allowlist` refuses to build the sources block from
any URL that is not on it. Selection being deterministic is worth nothing if
the caller can quietly scrape past it, so the decision leaves this script as
an artifact rather than as advice.

Input (JSON, stdin or --input <path>):
    {
      "candidates": [
        {"url": "...", "title": "...", "date": "2026-04-15"},   # date optional
        ...
      ],
      "cap": 10,         # optional, default 10
      "author_domains": ["<lab-or-author-site.edu>"]  # optional; the authors
                                        # or labs behind the work under
                                        # study, promoted to tier 2 for
                                        # their own publications
    }

Output (JSON to stdout):
    {
      "selected":              [ {url, title, tier, tier_name, date}, ... ],
      "not_selected":          [ ... same shape, with "reason" ],
      "unclassified_domains":  ["example.com", ...],
      "tier_counts":           {"1": 3, "2": 2, ...},
      "cap_used":              10
    }
"""
import json
import re
import sys

DEFAULT_CAP = 10

TIER_NAMES = {
    1: "peer-reviewed literature",
    2: "university/course material",
    3: "preprint/scholarly index",
    4: "official technical docs/standards",
    5: "established reference work",
    6: "general/user-generated web",
}

# Tier 6 is the deliberate default for anything unrecognised: treat an
# unknown domain as general web, never as authority.
UNKNOWN_TIER = 6

# Only tiers at or above this threshold are worth scrape budget.
MAX_SCRAPED_TIER = 5

# Suffix patterns, matched against the registrable domain. Order does not
# matter; the lowest tier number wins if several match.
TIER_PATTERNS = {
    1: [
        r"(^|\.)doi\.org$", r"(^|\.)nature\.com$", r"(^|\.)science\.org$",
        r"(^|\.)sciencedirect\.com$", r"(^|\.)springer\.com$",
        r"(^|\.)springeropen\.com$", r"(^|\.)link\.springer\.com$",
        r"(^|\.)wiley\.com$", r"(^|\.)onlinelibrary\.wiley\.com$",
        r"(^|\.)tandfonline\.com$", r"(^|\.)sagepub\.com$",
        r"(^|\.)cambridge\.org$", r"(^|\.)oup\.com$",
        r"(^|\.)academic\.oup\.com$", r"(^|\.)jstor\.org$",
        r"(^|\.)acm\.org$", r"(^|\.)dl\.acm\.org$", r"(^|\.)ieee\.org$",
        r"(^|\.)ieeexplore\.ieee\.org$", r"(^|\.)aps\.org$",
        r"(^|\.)journals\.aps\.org$", r"(^|\.)ams\.org$",
        r"(^|\.)siam\.org$", r"(^|\.)plos\.org$", r"(^|\.)mdpi\.com$",
        r"(^|\.)frontiersin\.org$", r"(^|\.)elifesciences\.org$",
        r"(^|\.)pnas\.org$", r"(^|\.)pubmed\.ncbi\.nlm\.nih\.gov$",
        r"(^|\.)ncbi\.nlm\.nih\.gov$", r"(^|\.)nih\.gov$",
        r"(^|\.)jmlr\.org$", r"(^|\.)neurips\.cc$", r"(^|\.)mlr\.press$",
        r"(^|\.)aclanthology\.org$", r"(^|\.)openreview\.net$",
    ],
    2: [
        r"(^|\.)edu$", r"(^|\.)edu\.[a-z]{2,3}$",
        r"(^|\.)ac\.[a-z]{2,3}$",
        r"(^|\.)ocw\.mit\.edu$", r"(^|\.)oyc\.yale\.edu$",
        r"(^|\.)ethz\.ch$", r"(^|\.)epfl\.ch$",
        r"(^|\.)uni-[a-z]+\.de$", r"(^|\.)sorbonne-universite\.fr$",
    ],
    3: [
        r"(^|\.)arxiv\.org$", r"(^|\.)biorxiv\.org$",
        r"(^|\.)medrxiv\.org$", r"(^|\.)chemrxiv\.org$",
        r"(^|\.)ssrn\.com$", r"(^|\.)papers\.ssrn\.com$",
        r"(^|\.)semanticscholar\.org$", r"(^|\.)scholar\.google\.com$",
        r"(^|\.)core\.ac\.uk$", r"(^|\.)zenodo\.org$",
        r"(^|\.)osf\.io$", r"(^|\.)hal\.science$",
    ],
    4: [
        r"(^|\.)python\.org$", r"(^|\.)docs\.python\.org$",
        r"(^|\.)developer\.mozilla\.org$", r"(^|\.)w3\.org$",
        r"(^|\.)whatwg\.org$", r"(^|\.)rfc-editor\.org$",
        r"(^|\.)ietf\.org$", r"(^|\.)iso\.org$", r"(^|\.)nist\.gov$",
        r"(^|\.)numpy\.org$", r"(^|\.)scipy\.org$",
        r"(^|\.)pytorch\.org$", r"(^|\.)tensorflow\.org$",
        r"(^|\.)scikit-learn\.org$", r"(^|\.)postgresql\.org$",
        r"(^|\.)kernel\.org$", r"(^|\.)gnu\.org$",
        r"(^|\.)isocpp\.org$", r"(^|\.)open-std\.org$",
        r"(^|\.)unicode\.org$", r"(^|\.)khronos\.org$",
    ],
    5: [
        r"(^|\.)plato\.stanford\.edu$", r"(^|\.)mathworld\.wolfram\.com$",
        r"(^|\.)britannica\.com$", r"(^|\.)oeis\.org$",
        r"(^|\.)encyclopediaofmath\.org$", r"(^|\.)nlab\.mathforge\.org$",
        r"(^|\.)ncatlab\.org$", r"(^|\.)oreilly\.com$",
        r"(^|\.)manning\.com$", r"(^|\.)nostarch\.com$",
        r"(^|\.)distill\.pub$", r"(^|\.)projecteuclid\.org$",
    ],
    6: [
        r"(^|\.)wikipedia\.org$", r"(^|\.)wikimedia\.org$",
        r"(^|\.)wikiwand\.com$", r"(^|\.)fandom\.com$",
        r"(^|\.)stackexchange\.com$", r"(^|\.)stackoverflow\.com$",
        r"(^|\.)quora\.com$", r"(^|\.)reddit\.com$",
        r"(^|\.)medium\.com$", r"(^|\.)substack\.com$",
        r"(^|\.)researchgate\.net$", r"(^|\.)academia\.edu$",
        r"(^|\.)scribd\.com$", r"(^|\.)slideshare\.net$",
        r"(^|\.)studylib\.net$", r"(^|\.)docslib\.org$",
        # Homework-answer and note-selling sites: unattributed, unverified,
        # and a well-documented vector for propagating other students'
        # mistakes. Never scraped, never the sole basis for a claim.
        r"(^|\.)chegg\.com$", r"(^|\.)coursehero\.com$",
        r"(^|\.)quizlet\.com$", r"(^|\.)studocu\.com$",
        r"(^|\.)numerade\.com$", r"(^|\.)bartleby\.com$",
        r"(^|\.)brainly\.com$", r"(^|\.)symbolab\.com$",
        r"(^|\.)coursepaper\.com$", r"(^|\.)studymode\.com$",
    ],
}

_COMPILED = {t: [re.compile(p) for p in pats] for t, pats in TIER_PATTERNS.items()}


def domain_of(url: str) -> str:
    d = re.sub(r"^[a-z]+://", "", (url or "").strip().lower())
    d = d.split("/")[0].split("?")[0].split("#")[0]
    d = d.split("@")[-1].split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def classify(url: str, author_domains=None):
    """Return (tier, matched) for a URL. `matched` is False for a default.

    `author_domains` promotes a researcher's, lab's, or group's own site to
    tier 2. Authors publishing about their own work are primary evidence for
    that work: the domain list cannot tell that a given lab produced the
    result under study, so the caller names those domains explicitly. This is
    a checkable fact, not a preference, and every promotion is reported in
    `author_promoted`.
    """
    d = domain_of(url)
    if not d:
        return UNKNOWN_TIER, False
    for od in (author_domains or []):
        od = domain_of(od) or od.strip().lower()
        if od and (d == od or d.endswith("." + od)):
            return 2, True
    for tier in sorted(_COMPILED):
        for pat in _COMPILED[tier]:
            if pat.search(d):
                return tier, True
    return UNKNOWN_TIER, False


def select(candidates: list, cap: int = DEFAULT_CAP, author_domains=None) -> dict:
    seen, enriched, unclassified, author_promoted = set(), [], [], []

    for c in candidates:
        url = (c.get("url") or "").strip()
        if not url:
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        tier, matched = classify(url, author_domains=author_domains)
        if matched and tier == 2 and author_domains and _is_author(url, author_domains):
            dom = domain_of(url)
            if dom not in author_promoted:
                author_promoted.append(dom)
        if not matched:
            dom = domain_of(url)
            if dom and dom not in unclassified:
                unclassified.append(dom)
        enriched.append({
            "url": url,
            "title": c.get("title", ""),
            "date": c.get("date", ""),
            "tier": tier,
            "tier_name": TIER_NAMES[tier],
        })

    # Tier ascending, then most recent first WITHIN the tier. A missing date
    # sorts last inside its own tier and never promotes across one.
    enriched.sort(key=lambda e: (e["tier"], _date_key(e["date"])))

    selected, not_selected = [], []
    for e in enriched:
        if e["tier"] > MAX_SCRAPED_TIER:
            not_selected.append({**e, "reason": f"tier {e['tier']} is never scraped"})
        elif len(selected) < cap:
            selected.append(e)
        else:
            not_selected.append({**e, "reason": "identified but over cap - report by name"})

    counts = {}
    for e in enriched:
        counts[str(e["tier"])] = counts.get(str(e["tier"]), 0) + 1

    return {
        "selected": selected,
        "not_selected": not_selected,
        "unclassified_domains": unclassified,
        "author_promoted": author_promoted,
        "tier_counts": counts,
        "cap_used": cap,
    }


def _is_author(url, author_domains):
    d = domain_of(url)
    for od in author_domains:
        od = domain_of(od) or od.strip().lower()
        if od and (d == od or d.endswith("." + od)):
            return True
    return False


def _date_key(d: str):
    """Descending by date inside a tier; undated sorts last."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", (d or "").strip())
    if not m:
        return (1, "")
    return (0, "".join(str(9 - int(ch)) if ch.isdigit() else ch for ch in m.group(0)))


def _load_payload(argv):
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


def rank_batches(batches: list, author_domains=None) -> dict:
    """Order each sub-query's URLs by authority tier, keeping every URL.

    Ordering inside a sub-query: tier ascending, then the order retrieval
    returned them (which approximates the engine's own relevance). Recency is
    not available per-result here, so it is not used; the tier is the ruler.
    """
    rankings, tiers, unclassified, author_promoted = [], {}, [], []

    for batch in batches or []:
        scored = []
        for i, r in enumerate(batch.get("results", []) or []):
            url = (r.get("url") or "").strip()
            if not url:
                continue
            tier, matched = classify(url, author_domains=author_domains)
            if not matched:
                dom = domain_of(url)
                if dom and dom not in unclassified:
                    unclassified.append(dom)
            elif tier == 2 and author_domains and _is_author(url, author_domains):
                dom = domain_of(url)
                if dom not in author_promoted:
                    author_promoted.append(dom)
            tiers[url] = tier
            scored.append((tier, i, url))
        scored.sort()
        rankings.append({
            "query": batch.get("query", ""),
            "ranked_urls": [u for _, _, u in scored],
        })

    counts = {}
    for t in tiers.values():
        counts[str(t)] = counts.get(str(t), 0) + 1

    return {
        "rankings": rankings,
        "tiers": tiers,
        "tier_counts": counts,
        "unclassified_domains": unclassified,
        "author_promoted": author_promoted,
    }


def _self_test():
    """Classify a representative spread of academic and general sources."""
    sample = [
        "arxiv.org", "doi.org", "nature.com", "dl.acm.org", "jstor.org",
        "ocw.mit.edu", "stanford.edu", "cam.ac.uk", "semanticscholar.org",
        "docs.python.org", "rfc-editor.org", "nist.gov",
        "plato.stanford.edu", "mathworld.wolfram.com", "distill.pub",
        "wikipedia.org", "stackoverflow.com", "medium.com",
        "chegg.com", "coursehero.com", "quizlet.com",
        "some-unknown-lab-blog.net",
    ]
    rows = []
    for d in sample:
        t, matched = classify("https://" + d + "/x")
        rows.append((t, d, TIER_NAMES[t], "" if matched else "  (default)"))
    rows.sort()
    print(f"{'tier':<5} {'domain':<26} classification")
    print("-" * 74)
    for t, d, name, note in rows:
        print(f"{t:<5} {d:<26} {name}{note}")
    return rows


def main():
    argv = sys.argv[1:]
    rank_mode = "--rank" in argv
    if rank_mode:
        argv.remove("--rank")
    write_list = None
    if "--write-list" in argv:
        i = argv.index("--write-list")
        if i + 1 >= len(argv):
            print("--write-list requires a path", file=sys.stderr)
            sys.exit(2)
        write_list = argv[i + 1]
        del argv[i:i + 2]
    if "--self-test" in argv:
        _self_test()
        return
    payload = _load_payload(argv)

    if rank_mode:
        print(json.dumps(rank_batches(
            payload.get("batches", []),
            author_domains=payload.get("author_domains", []),
        ), indent=2))
        return

    cap = int(payload.get("cap", DEFAULT_CAP))
    result = select(
        payload.get("candidates", []),
        cap=cap,
        author_domains=payload.get("author_domains", []),
    )
    if write_list:
        with open(write_list, "w", encoding="utf-8") as fh:
            for e in result["selected"]:
                fh.write(e["url"].strip() + "\n")
        result["selected_urls_path"] = write_list
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
