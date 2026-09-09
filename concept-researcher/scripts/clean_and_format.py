#!/usr/bin/env python3
"""
clean_and_format.py

Dedupe scraped sources by
canonical URL, truncate at the first genuine stop-marker (boilerplate like
"related articles", "subscribe to our newsletter"), enforce a hard
per-source character cap, then format the surviving sources into the single
text block the Concept Researcher (in its synthesis stage) reads as its source
material - with a total character budget so one long page can't crowd out
the rest.

IMPORTANT: sources_block can
legitimately run up to MAX_TOTAL_SOURCES_CHARS (150,000) characters. An
Agent tool call returns exactly one message back to the caller - there is no
mechanism that makes a subagent paste 150K characters of scraped text into
that message, and in practice it won't (a model summarizes instead). If
sources_block is only ever handed back as an inline JSON field, it silently
never survives the handoff from relevance_and_scraping to synthesis/report -
which is exactly what happened: synthesis received category labels and
invented figures instead of real source text. This script now WRITES the
formatted sources_block to a file on disk and returns only a bounded
pointer + counts on stdout, matching the "only a bounded result comes back,
the full document persists on disk" principle CLAUDE.md already states for
every other role. Downstream stages must Read the file directly - never
expect sources_block to arrive as inline conversational text.

Usage:
    python3 clean_and_format.py <output_path> < input.json

<output_path> is REQUIRED - an absolute path (typically inside the
per-task scratch directory ORCH provides, e.g.
orch/cache_memory/<workflow_id>/sources_block.md) that this script writes the
full sources_block text to.

Input JSON shape:
{
  "sources": [
    {"url": "...", "content": "...", "file_type": "html"|"pdf", "title": "..."}
  ]
}

Output JSON shape (stdout - bounded, safe to echo in a chat message):
{
  "sources_block_path": "<output_path, absolute>",
  "sources_block_chars": 12345,
  "source_count": 9,
  "dropped_count": 0,
  "sources_index": [
    {"n": 1, "url": "...", "title": "...", "file_type": "html", "content_chars": 2851}
  ]
}

Note: "sources_index" is metadata only (no scraped content) - safe to
include inline since it stays small regardless of how much was scraped.
"""

import json
import re
import sys

STOP_MARKERS = [
    "share this article",
    "related articles",
    "you might also like",
    "sign up for our newsletter",
    "subscribe to our newsletter",
    "cookie policy",
    "we use cookies",
    "follow us on",
    "leave a comment",
]

# A stop marker in the first 20% of the document is almost certainly a false
# positive (e.g. a headline or early pull-quote), not the real end of content.
STOP_MARKER_SEARCH_START_RATIO = 0.20

# Roughly 500-700 words; enough for a substantive excerpt, not a full-page
# reproduction. Prevents one large page from dominating the synthesis prompt.
MAX_SOURCE_CONTENT_CHARS = 3_000

# ~35-40K tokens for the whole sources block, leaving room for system
# prompt, source documents, lecture notes, and the model's own output.
MAX_TOTAL_SOURCES_CHARS = 150_000


def truncate_at_stop_marker(content: str) -> str:
    lowered = content.lower()
    search_start = int(len(content) * STOP_MARKER_SEARCH_START_RATIO)

    earliest_cut = None
    for marker in STOP_MARKERS:
        idx = lowered.find(marker, search_start)
        if idx != -1 and (earliest_cut is None or idx < earliest_cut):
            earliest_cut = idx

    content = content[:earliest_cut].strip() if earliest_cut is not None else content.strip()

    if len(content) > MAX_SOURCE_CONTENT_CHARS:
        content = content[:MAX_SOURCE_CONTENT_CHARS].rstrip() + "\n\n[...truncated for length...]"

    return content


def canonical_url(raw_url: str, og_url: str = None) -> str:
    return (og_url or raw_url).strip().rstrip("/")


def dedupe_scraped_sources(sources):
    seen = set()
    deduped = []
    for source in sources:
        key = canonical_url(source["url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def clean_scraped_sources(sources):
    deduped = dedupe_scraped_sources(sources)
    cleaned = []
    for source in deduped:
        new_source = dict(source)
        new_source["content"] = truncate_at_stop_marker(source.get("content", ""))
        cleaned.append(new_source)
    return cleaned


def format_aggregated_sources(sources):
    blocks = []
    total_chars = 0
    dropped_count = 0

    for i, source in enumerate(sources, start=1):
        label = "PDF - PREVIEW ONLY, NOT FULL TEXT" if source.get("file_type") == "pdf" else "HTML - FULL TEXT SCRAPE"
        block = f"SOURCE {i} [{label}]: {source['url']}\n\n{source.get('content', '')}"

        if total_chars + len(block) > MAX_TOTAL_SOURCES_CHARS:
            dropped_count = len(sources) - i + 1
            break

        blocks.append(block)
        total_chars += len(block)

    result = "\n\n---\n\n".join(blocks)
    if dropped_count:
        result += (
            f"\n\n---\n\n[NOTE: {dropped_count} additional source(s) omitted - "
            f"total content exceeded budget. Consider narrowing sub-queries if this recurs.]"
        )
    return result, dropped_count


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
    if len(sys.argv) < 2:
        print(
            "usage: clean_and_format.py <output_path> < input.json\n"
            "<output_path> is required - this script writes the full "
            "sources_block text there and returns only a bounded pointer "
            "on stdout. See the module docstring for why.",
            file=sys.stderr,
        )
        sys.exit(1)

    argv = sys.argv[1:]
    payload = _load_payload(argv)
    if not argv:
        print("usage: clean_and_format.py <output-path> [--input <payload.json>]", file=sys.stderr)
        sys.exit(2)
    output_path = argv[0]
    sources = payload["sources"]

    cleaned = clean_scraped_sources(sources)
    sources_block, dropped_count = format_aggregated_sources(cleaned)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(sources_block)

    sources_index = [
        {
            "n": i,
            "url": s["url"],
            "title": s.get("title"),
            "file_type": s.get("file_type"),
            "content_chars": len(s.get("content", "")),
        }
        for i, s in enumerate(cleaned, start=1)
    ]

    json.dump(
        {
            "sources_block_path": output_path,
            "sources_block_chars": len(sources_block),
            "source_count": len(cleaned),
            "dropped_count": dropped_count,
            "sources_index": sources_index,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
