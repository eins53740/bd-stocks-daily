# Prompt — Industry customer operations

Second section of `_industry/<slug>.md`. Runs only on refresh. Assumes the
macro section has just been generated.

Substitutions: `{INDUSTRY}`, `{MACRO_OUTPUT}`

```
ROLE: Senior sector analyst continuing an in-depth industry analysis.

INDUSTRY: {INDUSTRY}

CONTEXT: Already mapped (do not repeat):
{MACRO_OUTPUT}

OBJECTIVE: Explain how this industry operates at the customer and execution level.
Focus on real-world behaviour, incentives, and power dynamics. No financial
data needed unless essential.

COVER:
1. Final customers — who they are, outcomes they want, frustrations.
2. Decision-making process — stakeholders, influencers vs signers, buying-cycle length.
3. Discovery and evaluation — how buyers find vendors, what builds trust.
4. Channels — distribution channels that dominate, what matters most at purchase.
5. Negotiating power — who has leverage in the chain and why; switching costs.
6. Bottlenecks and dependencies — what breaks the system; fragility points.
7. Operational workflows — how the product/service is actually delivered;
   non-obvious practices insiders rely on.

OUTPUT REQUIREMENTS:
- Buyer-journey diagram (stages + key decision criteria).
- Table: "Stakeholder | Goals | Influence | Pain points".
- Section: "Where AI can disrupt this workflow" — concrete workflow steps, not platitudes.
- Split each answer into: (A) Operator lens (execution, bottlenecks, workflows),
  (B) Investor lens (profit pools, market structure, moats).
- End with 10 key insights.

{STYLE_RULES}
```
