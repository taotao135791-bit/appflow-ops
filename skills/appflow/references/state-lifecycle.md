# State Lifecycle (workspace-scoped, automatic)

Canonical runtime lifecycle for Continuous Account State
(`docs/account-state.md`). The main router owns this lifecycle; platform
skills may provide platform-specific observation mapping but must never
implement their own state lifecycle.

## before_reasoning

For ambiguous follow-ups ("现在呢?", "昨天那个呢?", "Google 怎么又不行了?",
"还是没量。", "这个还能继续跑吗?"), after workspace resolution load the
workspace's continuous state through the State Runtime API
(`StateSession.load_context_summary()`), never by reading state files
directly:

```text
current state (derived, freshness-checked)
+ bounded recent history
  → last observation facts
  → recent changes
  → previous decision
  → previous outcome
  → pending review
```

Terminology questions ("CTR 是什么?") and fully specified procedures skip
state entirely — retrieval is semantic + bounded, never a history dump.

## after_observation

Record ONE observation when reliable new facts arrive (normalized export,
screenshot interpretation, pasted table, deterministic engine, structured
workspace evidence). `evidence_status`: confirmed / reported / inferred.
Deduplicate by source digest within the run. Do not record speculative
interpretations as observations.

## after_decision

Record ONE decision when a clear operational recommendation forms
(keep / increase / decrease / pause / reopen / replace / wait / observe /
investigate). Provenance:

- `origin`: deterministic | agent_constrained | operator (default
  agent_constrained — LLM interpretation constrained by measurement /
  maturity / policy / permission / numeric gates).
- `confidence`: high / medium / low.
- Event `evidence_status` is `inferred` (a decision is a recommendation,
  not a business fact).

Never store the full assistant answer — only the structured summary
(decision class, concise reason, evidence refs, uncertainty, review
condition). Hidden chain-of-thought is never persisted.

## after_confirmed_change

Record a change ONLY after execution is confirmed — operator confirmation,
deterministic evidence, or a trusted execution layer. A recommendation
alone ("建议 tCPA 从 100 调到 90") never becomes a Change.

## after_outcome

Record an outcome only when later evidence justifies it (improved /
worsened / neutral / inconclusive / rolled_back / not_executed). Never
write an outcome at decision time.

## Isolation

State is per-workspace and physically isolated. Never read, write, or
reference another workspace's state; never borrow its history to fill a
missing gap. When the current workspace has no history, say so plainly and
rely on observed facts, policy, and general platform knowledge.
