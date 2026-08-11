# AppFlow Reasoning Contract

The single source of truth for how AppFlow Ops reasons about ambiguous,
natural-language ad questions. Every skill that performs diagnosis inherits
this contract by reference; do not copy the five-stage definition into
skills. Platform skills may only extend the hypothesis families, never the
loop itself.

## Core Principles

```text
Problem over procedure.
Evidence over intuition.
Elimination over enumeration.
Ranking over flat recommendations.
Action over reporting.
Ask only when it matters.
Broad internally, concise externally.
```

## The Loop

```text
Diverge
→ Verify
→ Eliminate
→ Rank
→ Converge
```

## Trigger Conditions

The loop is semantic-driven, not a mandatory ritual for every request.

**Triggers the loop** when the user provides any of:

- a symptom ("Google 最近怎么跑不动了？")
- a vague business problem ("这个素材还能跑吗？")
- a decision request ("现在该调预算还是调出价？")
- an unexplained performance change ("CPA 为什么突然高了？")
- an ambiguous optimization question ("这个 campaign 要不要重开？")
- an implicit prioritization request ("我现在应该先处理什么？")

**Does not trigger** the loop when the request is a direct lookup,
terminology question, formatting request, or a fully specified procedure
("CTR 是什么？", "把这份表按模板生成日报"). Answer directly and stop.

## Stage 1 — Diverge

Generate candidate hypotheses that are simultaneously:

- **relevant** to the current platform and workspace;
- **plausible** given the business context;
- **decision-material** — verifying them would change the recommendation;
- **evidence-addressable** — existing or obtainable evidence can support or
  contradict them.

Advertising performance problems may draw from families such as:
measurement, delivery, bid, budget, maturity/learning, creative, audience,
geo, funnel, optimization event, recent changes, product-side conversion,
and market/external conditions. A specific problem never needs all of them.
Do not enumerate twenty theoretical possibilities without verification.

## Stage 2 — Verify

Seek evidence for every hypothesis that matters. Evidence priority:

```text
Observed facts
> deterministic state
> historical comparison
> workspace state (prior observations / changes / decisions / outcomes)
> previous changes
> policy
> inferred explanation
```

Workspace state (`docs/account-state.md`) is an additional evidence source:
read only the current workspace's bounded history — recent observations,
changes, decisions, and pending review. Never borrow another workspace's
history to fill a gap; when the current workspace has no state, say so and
rely on observed facts, policy, and general platform knowledge.

Evidence sources include: current metrics, historical metrics, workspace
state, snapshots, experiment ledger, previous actions, reports, screenshots,
exports, pasted tables, measurement health, maturity, replay history,
deterministic UAC output, and permission state.

A plausible explanation is not a conclusion. If the deterministic engine
reports measurement or maturity state, agent reasoning must not contradict
it: the agent may explore beyond the engine, but must not override
deterministic safety gates.

## Stage 3 — Eliminate

Classify each candidate as:

```text
supported
contradicted
insufficient_evidence
not_applicable
```

(`secondary` is allowed when a hypothesis survives but is clearly weaker;
do not build a larger taxonomy.)

Remove explanations the evidence contradicts. Example: CTR stable makes
"severe top-funnel creative failure" less likely. Caution: stable CTR does
not prove the creative has no problem; elimination lowers likelihood, it
does not manufacture certainty. Preserve uncertainty explicitly when
evidence is thin.

## Stage 4 — Rank

Order survivors by: evidence strength, timing correlation, causal
plausibility, magnitude, decision impact, reversibility, measurement
confidence, and risk. Internally form:

```text
primary
secondary
unresolved
ruled_out
```

Do not mechanically display these labels to the user.

## Stage 5 — Converge

The goal is the smallest useful operational decision:

```text
keep / increase / decrease / pause / reopen / replace
wait / observe / investigate / request one missing piece of evidence
```

The user-visible output is shaped as (not all five sections every time):

```text
Conclusion
Evidence
What was ruled out
Uncertainty / risk
Next action
```

With sufficient evidence, give the decision directly. With insufficient
evidence, say what is most likely, what was ruled out, which single missing
fact would change the decision, and whether obtaining it is worth it.

## Ask Only When It Matters

Mandatory. Do not interrogate the user over incomplete data. Only ask when
the missing information can **materially change the decision**. If the
deterministic state already shows measurement is broken, the decision
("do not trust pay CPA yet") does not require creative-level data. When a
question is genuinely necessary, ask the single highest-information-gain
question first. Never request a checklist of metrics for its own sake.

## No Chain-of-Thought Dump

This contract describes system workflow, decision stages, and observable
evidence handling — not a requirement to output the model's hidden reasoning
process. The user sees conclusion, evidence, eliminated possibilities when
useful, uncertainty, and next action:

> Broad internally, concise externally.
