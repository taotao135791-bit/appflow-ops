# Client Question Discipline (乙方提问纪律)

Agency principle: 该问的问，不该问的不问。Every question costs client
patience; only spend it when the answer changes the next decision. Ask the
must-ask items in one batched message, infer the rest, and mark inferences
explicitly instead of asking.

## Must Ask (only these, batched into one message)

Ask an item only if it is still unknown AND it changes the next decision:

1. **KPI and acceptance definition** — which metric the client judges by
   (install / registration / payment / ROAS), and what "good" means
   (target CPA/ROAS, acceptable range, measurement source).
2. **Permission boundary** — what the operator may change directly
   (budget, bid/target, creative, geo, structure) versus what requires
   client approval or client-side action (product, paywall, SDK, MMP,
   backend events, store page).
3. **Business ceiling** — hard business limits: max CPA / min ROAS, total
   budget cap, spend pacing constraints.
4. **Urgency and deadline** — when the client expects results, whether this
   is a routine review or an urgent demand, and any fixed dates (report day,
   review meeting, promotion window).
5. **Available data** — what evidence exists right now: exports, date range,
   granularity, MMP/backend reconciliation status, conversion delay.

If an item was already answered earlier in the project (project context
docs, prior conversation), do not ask it again — read the record first.

## Do Not Ask (infer, derive, or skip)

- Client's internal cost structure, margins, unit economics details — infer
  from the stated business ceiling; mark assumptions as inference.
- Product roadmap and release plans — irrelevant unless the client raises
  it; note it only if volunteered.
- Other vendors' prices, bids, or performance — never ask.
- Organizational details (who approves what internally) beyond the single
  approval contact needed for writes.
- Anything derivable from provided data: date ranges present in exports,
  country/OS splits inside reports, platform settings visible in the
  dashboard.

## How To Ask

- One message, numbered, short. No more than five questions, ideally fewer.
- Attach a reason to each question: what decision it unlocks.
- Offer defaults: "如果没有特别说明，我按 CPA 上限 X、只读分析处理".
- Never interrogate: if the answer would only refine wording rather than
  change an action, skip it and state the assumption.

## When The Client Pushes Back On Questions

If the client refuses to answer a must-ask item, do not keep pressing:

1. State the assumption being made in its absence.
2. Flag which conclusions become weaker or reversible under that assumption.
3. Proceed with the read-only analysis and record the gap in the workspace
   ops log so it is traceable later.

This protects both sides: the operator never blocks on nice-to-have
information, and every inference is on record.
