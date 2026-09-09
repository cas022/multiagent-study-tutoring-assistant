#!/usr/bin/env python3
"""
verify_citations.py

This guards a specific failure: a report citing URLs that do not match what
retrieval actually returned and scraping actually read - a subagent
re-typing or
"recalling" a URL from training knowledge rather than copying it verbatim
from the real source material, especially for well-known organizations
where a plausible-looking but wrong URL is easy to produce without anyone
noticing. This is exactly the class of thing CLAUDE.md's house rule already
warns about ("no invented facts, figures, or citations, ever") applied to
URLs specifically, and it is exactly the kind of accuracy-critical step this
build's own design principle says should never be left to model self-report
(see clean_and_format.py, source_selection.py, report_utils.py - floor/
ceiling selection, dedupe, truncation, and completeness checks are all real
code, not the model grading its own homework). URL fidelity gets the same
treatment here.

This script is the deterministic ground truth check: it does NOT try to
judge whether a citation is well-formed or well-supported (that is
`check-report-complete`'s job in report_utils.py) - it only asks "does this
URL, byte for byte after trivial normalization, actually match a URL that
was really retrieved this run." A URL that fails this check was not
verified as real by anything in this pipeline; it must be treated as a
hallucination candidate, not a formatting nitpick.

Ground truth is built from two real, deterministic sources:
1. `sources_block_path` - the file `clean_and_format.py` wrote. Every
   surviving source is on its own "SOURCE N [LABEL]: <url>" line - these are
   the URLs actually scraped (or, for PDFs, passed through) this run.
2. `restricted_sources` - the 403/paywalled URLs `relevance_and_scraping`
   set aside (see agents/concept-researcher.md's Part 3). These are legitimately
   citable in the report's Section 7 appendix even though they were never
   scraped, so they count as ground truth too, just for that one section.

Any URL found anywhere in the report text that does not canonically match
either list is flagged as unmatched - the report stage (or report_formatter,
if it introduced the drift during reformatting) must not have invented it,
and whoever produced it must fix it before returning, using the real URL
from sources_index/sources_block_path or restricted_sources, never a
retyped or "close enough" substitute.

Usage:
    python3 verify_citations.py < input.json

Input JSON shape:
{
  "report_markdown": "...",
  "sources_block_path": "<absolute path to sources_block.md>",
  "restricted_sources": [{"url": "...", "title": "...", "reason": "..."}]
}

`restricted_sources` may be omitted or an empty list.

Output JSON shape (stdout):
{
  "valid": true|false,
  "cited_url_count": N,
  "matched_count": N,
  "unmatched_urls": ["..."],
  "ground_truth_count": N
}

A `false` result means at least one URL in the report does not match
anything this pipeline actually retrieved this run - treat this as a failed
stage, the same way `check-report-complete: false` is treated, not as a
minor formatting issue to wave through.

Known limitation, disclose if asked: canonicalization here is intentionally
simple (trim whitespace, strip a single trailing slash) to match
`clean_and_format.py`'s own `canonical_url()`. A URL that is the same source
but differs only by a query string, tracking parameter, or protocol
(http vs https) will be flagged as unmatched even though a human would call
it the same source. Treat every `false` result as "look at this," the same
posture `check-report-complete`'s heuristic already asks for - not as
automatic proof the model fabricated something out of nothing.
"""

import json
import re
import sys

SOURCE_LINE_RE = re.compile(r"^SOURCE\s+\d+\s+\[[^\]]*\]:\s*(\S+)", re.MULTILINE)
URL_RE = re.compile(r"https?://[^\s\)\]\"'<>,]+")


def canonical_url(raw_url: str) -> str:
    return raw_url.strip().rstrip("/")


def ground_truth_urls(sources_block_path: str, restricted_sources: list) -> set:
    urls = set()

    try:
        with open(sources_block_path, "r", encoding="utf-8") as f:
            block_text = f.read()
        for match in SOURCE_LINE_RE.finditer(block_text):
            urls.add(canonical_url(match.group(1)))
    except (FileNotFoundError, OSError) as e:
        print(
            json.dumps(
                {
                    "valid": False,
                    "error": f"could not read sources_block_path: {e}",
                    "cited_url_count": 0,
                    "matched_count": 0,
                    "unmatched_urls": [],
                    "ground_truth_count": 0,
                }
            )
        )
        sys.exit(1)

    for restricted in restricted_sources or []:
        url = restricted.get("url")
        if url:
            urls.add(canonical_url(url))

    return urls


def cited_urls(report_markdown: str) -> list:
    # Preserve original (uncanonicalized) form for reporting, dedupe by
    # canonical form so the same citation appearing twice isn't double-counted.
    seen_canonical = set()
    ordered_originals = []
    for match in URL_RE.finditer(report_markdown):
        raw = match.group(0)
        key = canonical_url(raw)
        if key in seen_canonical:
            continue
        seen_canonical.add(key)
        ordered_originals.append(raw)
    return ordered_originals


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

    # Same idea as report_utils' text_path: let a caller point at the report
    # file it already wrote instead of inlining the whole document.
    if "report_markdown_path" in payload and "report_markdown" not in payload:
        with open(payload["report_markdown_path"], "r", encoding="utf-8") as fh:
            payload["report_markdown"] = fh.read()
    report_markdown = payload.get("report_markdown", "")
    sources_block_path = payload.get("sources_block_path")
    restricted_sources = payload.get("restricted_sources", [])

    if not sources_block_path:
        json.dump(
            {
                "valid": False,
                "error": "sources_block_path is required",
                "cited_url_count": 0,
                "matched_count": 0,
                "unmatched_urls": [],
                "ground_truth_count": 0,
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        sys.exit(1)

    truth = ground_truth_urls(sources_block_path, restricted_sources)
    cited = cited_urls(report_markdown)

    unmatched = [u for u in cited if canonical_url(u) not in truth]
    matched_count = len(cited) - len(unmatched)

    json.dump(
        {
            "valid": len(unmatched) == 0,
            "cited_url_count": len(cited),
            "matched_count": matched_count,
            "unmatched_urls": unmatched,
            "ground_truth_count": len(truth),
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
