# Style rules (shared appendix)

Append this block to every qualitative LLM call in Phase 2.5 and to industry
generation in Phase 1.5 refresh.

```
OUTPUT STYLE RULES (apply to every section below)
- UK English (colour, organisation, analyse, behaviour)
- Short paragraphs, maximum four sentences each
- No fluff, no hedging without evidence
- Label any inferred claim with "(inferred)" or "(assumption — evidence gap)"
- Numbers come from the analyse_ticker JSON provided below. Do NOT invent figures.
  If a figure is not in the JSON, say "not available" rather than guessing.
- When relevant, include an AI disruption callout (1–2 lines): which workflow steps
  could be automated, which roles shrink, which new entrants become possible.
- Separate Operator lens (execution, bottlenecks, workflows) from Investor lens
  (profit pools, market structure, moats) where both are relevant.
- Cite sources (annual report page, quarterly report, IR deck, filings URL) whenever
  a claim is not derivable from the JSON.
- CITATION DISCIPLINE:
  * Any factual claim that is neither in the JSON nor tied to a cited source gets an
    "[UNSOURCED]" tag at the end of its sentence. Prefer dropping the claim over tagging it.
  * Source-quality order — cite the highest tier available for the claim:
    10-K/annual report > 10-Q/earnings-call transcript > IR deck/page > reputable
    financial press > aggregators. Never cite an aggregator when a filing covers it.
  * Freshness: when a cited filing/news item is older than 3 months, state its date
    next to the citation (e.g. "(10-K FY2025, filed 2026-02)"); older than 12 months
    additionally flag "(may be stale)".
```
