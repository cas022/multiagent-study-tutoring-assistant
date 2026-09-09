#!/usr/bin/env python3
"""
report_utils.py

Deterministic checks that run against the Concept Researcher's own generated text (the
final report, the persisted sub-query list), rather than against fetched
source material. These stay real code, not model self-report, matching the
"checked against the actual file or a real test run" discipline this whole
agent follows.

Subcommands (all read JSON from stdin, write JSON to stdout):

  count-citations
    input:  {"text": "...report markdown..."}
    output: {"citation_count": N}

  extract-context-conflicts
    input:  {"text": "...report markdown..."}
    output: {"context_conflicts": ["...", ...]}

  validate-subqueries
    input:  {"queries": ["q1", ...], "min_count": 1, "max_count": 5}
    output: {"valid": true|false, "count": N, "min_count": 1, "max_count": 5}
    The number of sub-queries is the model's own judgment call based on the
    query's complexity (a narrow, single-entity factual question may only
    need 1-2; a broad multi-jurisdiction or multi-entity policy question may
    need the full 5), not a fixed constant. This script only validates the
    count falls in range - it cannot and does not judge whether the chosen
    count actually matches the query's complexity, that remains the model's
    call, made visible for review via the persisted sub_queries.md file (see
    the research stage's Part A/B in agents/concept-researcher.md).

  check-report-complete
    input:  {"text": "...report markdown..."}
    output: {"complete": true|false, "has_sources_section": bool,
              "ends_mid_sentence": bool, "citation_count": N}
    Heuristic completeness check standing in for the original's LangChain
    stop_reason == "max_tokens" check, which relied on API metadata not
    available to a subagent generating its own output directly. Flags the
    two symptoms that check was catching: a missing numbered Sources
    section, or the text ending mid-sentence (no terminal punctuation).
"""

import json
import re
import sys


def count_citations(report_markdown: str) -> int:
    return len(set(re.findall(r"\[(\d+)\]", report_markdown)))


def extract_context_conflicts(report_markdown: str):
    return re.findall(r"CONTEXT CONFLICT[:\s]+(.{0,200})", report_markdown)


def check_report_complete(text: str):
    has_sources_section = bool(re.search(r"^\**\s*6\.?\s*Sources", text, re.IGNORECASE | re.MULTILINE)) or \
        bool(re.search(r"##\s*Sources", text, re.IGNORECASE))
    stripped = text.rstrip()
    ends_mid_sentence = bool(stripped) and stripped[-1] not in ".!?\"')]}`"
    citation_count = count_citations(text)
    complete = has_sources_section and not ends_mid_sentence
    return {
        "complete": complete,
        "has_sources_section": has_sources_section,
        "ends_mid_sentence": ends_mid_sentence,
        "citation_count": citation_count,
    }


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
        print("usage: report_utils.py <subcommand> < input.json", file=sys.stderr)
        sys.exit(1)

    argv = sys.argv[1:]
    payload = _load_payload(argv)
    subcommand = argv[0]

    # `text_path` is accepted anywhere `text` is, so a caller holding a large
    # document (a full report) can point at the file it already wrote rather
    # than emitting the whole thing again inside a JSON payload.
    if "text_path" in payload and "text" not in payload:
        with open(payload["text_path"], "r", encoding="utf-8") as fh:
            payload["text"] = fh.read()

    if subcommand == "count-citations":
        out = {"citation_count": count_citations(payload["text"])}
    elif subcommand == "extract-context-conflicts":
        out = {"context_conflicts": extract_context_conflicts(payload["text"])}
    elif subcommand == "validate-subqueries":
        queries = payload["queries"]
        min_count = payload.get("min_count", 1)
        max_count = payload.get("max_count", 5)
        count = len(queries)
        out = {
            "valid": min_count <= count <= max_count,
            "count": count,
            "min_count": min_count,
            "max_count": max_count,
        }
    elif subcommand == "check-report-complete":
        out = check_report_complete(payload["text"])
    else:
        print(f"unknown subcommand: {subcommand}", file=sys.stderr)
        sys.exit(1)

    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
