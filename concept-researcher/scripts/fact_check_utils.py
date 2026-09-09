#!/usr/bin/env python3
"""
fact_check_utils.py

**NOT CURRENTLY CALLED, as of 2026-08-04.** `agents/concept-researcher.md`'s `report`
stage no longer has a `fact_check` part - it was removed entirely (not just
disabled) after a live timing test showed the consolidation and
parallelization work already done did not bring thorough-tier runtime down
enough on its own, and fact-check's own cost (a full read-the-report pass,
up to 15 Perplexity calls even parallelized, a render step) was a real,
avoidable chunk of that. This file is kept, unused, reserved for a planned
future redesign where fact-checking becomes a separate, opt-in step offered
to the person after the base report is already delivered, rather than an
embedded part of every thorough-tier run. Do not wire this back into
`agents/concept-researcher.md` without being told to.

Bundled deterministic helpers for the (currently unused) `fact_check` part,
added after a source-quality review pass (Perplexity, run by
hand against a finished report, 2026-07-30) caught fabricated figures and a
wrong source attribution that the pipeline's own citation checks
(verify_citations.py) could not have caught, because they were real URLs
sitting next to numbers those URLs never actually stated. This is the
deterministic half of that fix: the model identifies which claims are worth
independently verifying and judges Perplexity's answer for each one; this
script only bounds the list (so a report doesn't trigger 40 Perplexity calls)
and renders the results into a consistent report section - it never decides
what is true or false itself.

Usage:
    python3 fact_check_utils.py dedupe-claims < input.json
    python3 fact_check_utils.py render-fact-check-section < input.json

--- dedupe-claims ---

Input JSON shape:
{
  "claims": [
    {"claim": "...", "attributed_source": "...", "verification_query": "..."}
  ],
  "cap": 15
}

Dedupes by a normalized form of "claim" (case-insensitive, whitespace
collapsed) so the same fact identified twice isn't checked twice, then caps
the list at `cap` (default 15) to bound Perplexity call volume and latency.
If more than `cap` candidates survive dedup, keeps the first `cap` in the
order given - the model should already have put its highest-priority claims
first (anything with no [INFERRED - VERIFY] or [DERIVED ESTIMATE] tag, i.e.
presented with full confidence, is highest priority, since that is exactly
the category the 2026-07-30 fabrications fell into).

Output JSON shape:
{
  "claims": [...capped list...],
  "total_candidates": N,
  "deduped_count": N,
  "checked_count": N,
  "dropped_for_cap": N
}

--- render-fact-check-section ---

Input JSON shape:
{
  "results": [
    {"claim": "...", "attributed_source": "...", "status": "confirmed"|"contradicted"|"unverifiable", "note": "..."}
  ]
}

Renders a compact "Fact-Check Findings" report section: a one-line summary
(N/M confirmed) plus a short list naming only the claims that came back
contradicted or unverifiable, each with a one-line reason. Changed
2026-08-03 from a full table listing every checked claim (confirmed
included): the `[]` tags already inline throughout the report (PAYWALLED,
INFERRED - VERIFY, DERIVED ESTIMATE) are the primary signal of what is
unverified, and a full re-listing of every confirmed claim added length
without adding information a reviewer needs - the claims that actually
require attention are the ones that did NOT confirm. This section is
APPENDED to the report (now before the format/tag-verification pass runs,
so it gets covered by that pass too - see Part C of the report stage in
agents/concept-researcher.md), and is deliberately short enough not to need one.

Output JSON shape:
{
  "section_markdown": "...",
  "checked_count": N,
  "confirmed_count": N,
  "contradicted_count": N,
  "unverifiable_count": N
}
"""

import json
import re
import sys

DEFAULT_CAP = 15

STATUS_ORDER = {"contradicted": 0, "unverifiable": 1, "confirmed": 2}
STATUS_LABEL = {
    "contradicted": "CONTRADICTED",
    "unverifiable": "UNVERIFIABLE",
    "confirmed": "Confirmed",
}


def normalize_claim(claim: str) -> str:
    return re.sub(r"\s+", " ", claim.strip().lower())


def dedupe_claims(claims: list, cap: int = DEFAULT_CAP) -> dict:
    seen = set()
    deduped = []
    for c in claims:
        key = normalize_claim(c.get("claim", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    total_candidates = len(claims)
    deduped_count = len(deduped)
    capped = deduped[:cap]
    dropped_for_cap = max(0, deduped_count - len(capped))

    return {
        "claims": capped,
        "total_candidates": total_candidates,
        "deduped_count": deduped_count,
        "checked_count": len(capped),
        "dropped_for_cap": dropped_for_cap,
    }


def render_fact_check_section(results: list) -> dict:
    confirmed = [r for r in results if r.get("status") == "confirmed"]
    contradicted = [r for r in results if r.get("status") == "contradicted"]
    unverifiable = [r for r in results if r.get("status") == "unverifiable"]
    needs_review = sorted(
        contradicted + unverifiable,
        key=lambda r: STATUS_ORDER.get(r.get("status"), 99),
    )

    lines = []
    lines.append("**8. Fact-Check Findings**")
    lines.append("")
    lines.append(
        "An independent verification pass checked this report's highest-risk "
        "claims (figures and attributions presented with full confidence, no "
        "`[INFERRED - VERIFY]` or `[DERIVED ESTIMATE]` tag) against external "
        "search. This is a second opinion on top of the `[]` tags already "
        "inline throughout the report above, not a replacement for them - "
        "those tags remain the primary signal of what is unverified or "
        "inferred in this document."
    )
    lines.append("")

    if not results:
        lines.append(
            "No claims were selected for independent fact-checking this run."
        )
    elif not needs_review:
        lines.append(
            f"**{len(confirmed)}/{len(results)} checked claims were "
            f"confirmed.** None were contradicted or left unverifiable."
        )
    else:
        lines.append(
            f"**{len(confirmed)}/{len(results)} checked claims were "
            f"confirmed.** {len(needs_review)} need review:"
        )
        lines.append("")
        for r in needs_review:
            status = r.get("status", "unverifiable")
            label = STATUS_LABEL.get(status, status)
            claim = (r.get("claim") or "").strip()
            note = (r.get("note") or "").strip()
            lines.append(f"- **{label}**: {claim} - {note}")

    section_markdown = "\n".join(lines)

    return {
        "section_markdown": section_markdown,
        "checked_count": len(results),
        "confirmed_count": len(confirmed),
        "contradicted_count": len(contradicted),
        "unverifiable_count": len(unverifiable),
    }


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("dedupe-claims", "render-fact-check-section"):
        print(
            "usage: fact_check_utils.py <dedupe-claims|render-fact-check-section> < input.json",
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]
    payload = json.load(sys.stdin)

    if command == "dedupe-claims":
        claims = payload.get("claims", [])
        cap = payload.get("cap", DEFAULT_CAP)
        result = dedupe_claims(claims, cap=cap)
    else:
        results = payload.get("results", [])
        result = render_fact_check_section(results)

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
