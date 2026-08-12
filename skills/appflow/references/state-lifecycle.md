# State Lifecycle (workspace-scoped, canonical runtime)

AppFlow provides a canonical runtime lifecycle for workspace-scoped state,
and supported operational entry points use it instead of relying only on
prompt instructions (`docs/account-state.md`). Host integrations should
route operational work through this runtime lifecycle. The single entry
point is `AppFlowRuntime` (`scripts/appflow_ops/uac/run_lifecycle.py`):

```text
AppFlowRuntime(workspace).begin_run(request_text)
  → classify_request (follow-up / diagnosis / decision / direct informational)
  → state_context() only when the request needs business state
→ reason / deterministic tools
→ record_observation / record_decision / record_confirmed_change / record_outcome
→ finish_run()
```

Platform skills may provide platform-specific observation mapping but must
never implement their own state lifecycle; skills never write state files
directly. This is not a claim of universal host enforcement: host
integrations choose whether to route through the runtime (for example via
`state_access`), and only supported entry points are guaranteed to use it.

## before_reasoning

For ambiguous follow-ups ("现在呢?", "昨天那个呢?", "Google 怎么又不行了?",
"还是没量。", "这个还能继续跑吗?"), the runtime loads the workspace's
continuous state through `AppFlowRuntime.state_context()` (bounded):

```text
current state (derived, freshness-checked)
+ last observation / last change / last decision / last outcome
+ pending review
+ bounded recent history
```

Terminology questions ("CTR 是什么?") classify as direct informational:
no state read, no state write. Loading state never writes business events.

## after_observation

Record ONE observation when reliable new facts arrive (normalized export,
screenshot interpretation, pasted table, deterministic engine, structured
workspace evidence). `evidence_status`: confirmed / reported / inferred.
Deduplicated by a stable digest — the caller may pass `source_digest`, and
when absent the runtime derives one from the canonical structured payload
(never from timestamps or random ids). Do not record speculative
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
- Envelope `source_type` maps from origin: deterministic →
  `deterministic_engine`, agent_constrained → `agent`, operator → `manual`.

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

## Payload guard

State payloads are checked before every write (fail closed): credential
keys, raw conversations, emails, and oversized free text are rejected with
`StatePayloadError`; the guard is defense-in-depth, not DLP. Workspace
isolation protects business boundaries; the guard reduces accidental
persistence of content that does not belong in structured state.
