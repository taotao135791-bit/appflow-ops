# Rapid Response: Urgent Client Demands (客户急单响应)

Use this workflow when the client demands fast metric movement — "今天就要把
CPA 降下来", "这周 ROAS 必须回去", "消耗太慢马上给我起量". The goal is to
respond fast, move the metrics that can safely move, and protect the operator
with a complete audit trail. Speed never waives safety caps.

## Step 0 — Fixed First Move (提问纪律必问项)

Before recommending anything, confirm in one batched message:

1. KPI definition and the exact number the client wants (and by when).
2. Permission boundary: which levers the operator may touch today without
   another approval.
3. Business ceiling: max CPA / min ROAS / budget cap.

If the client refuses to answer, state the assumption, mark conclusions as
reversible, and proceed read-only (see `client-questions-policy.md`).

## Step 1 — Read-Only Triage

Separate the symptom into observed facts, calculations, and inferences:

- Is the metric really broken, or is it conversion delay / immature data?
- If data is immature, the honest rapid answer is "hold + explanation";
  do not manufacture action to look busy.

## Step 2 — Safe Quick Levers (only what evidence supports)

Propose from this list, each item with current value, proposed value,
rollback value, and review condition:

1. **Stop clear anomalies**: ads/creatives rejected or mis-serving, spend
   concentrated in obviously broken segments.
2. **Exclude bad segments**: geo / placement / device slices with mature
   evidence of CPA far above ceiling.
3. **Tighten targets within policy caps**: tCPA / tROAS changes stay inside
   the numeric policy single-change limits (see
   `docs/numeric-safety-policy.md`). Large gaps become staged plans, never
   one jump.
4. **Rebalance budget** inside the current total budget: move spend from
   proven-bad to proven-good units; do not raise the total without approval.
5. **Creative rotation**: pause fatigued creatives, activate approved
   replacements already in the library.

Never combine these into a multi-variable "experiment". Record urgent
multi-lever moves under the `EMERGENCY_INTERVENTION` contract (marked
`NOT_A_VALID_EXPERIMENT`, attribution confounded) or
`OPERATIONAL_CORRECTION` when it is a confirmed configuration error — both
require explicit human confirmation.

## Step 3 — Dual Output (固定双输出)

Every rapid response produces exactly two deliverables, both written into
the client workspace for traceability:

1. **Client-facing explanation** (reports/client/): observation → likely
   causes → what was done today → what needs client cooperation → next check
   time. No platform jargon, no blame, no causal overclaims.
2. **Internal action ticket**: lever, from → to, rollback value, rollback
   condition, review date, who approved. This is the operator's protection.

## Step 4 — Ledger And Self-Protection

- Write the urgent action into the workspace ledger/ops log with
  `urgent: true` and the client confirmation state.
- If the client demands something beyond safe caps, record the demand, the
  safe alternative offered, and the client's decision. The operator never
  silently exceeds policy limits; the client's override is their recorded
  choice.
- Set the first review checkpoint (days or mature events, whichever first)
  and state the rollback trigger in writing.

## What Rapid Response Must Never Do

- Exceed numeric policy single-change caps, even under pressure.
- Claim causation from a same-day metric move.
- Touch product, paywall, tracking, or anything outside the declared
  permission boundary.
- Skip the written trail to save time — the trail is the deliverable.
