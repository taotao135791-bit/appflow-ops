# Continuous Account State

Short engineering document. Isolation-first: **workspace isolation is a
runtime property before any state is stored.**

## Core principles

```text
State belongs to a workspace, never to AppFlow globally.
One workspace = one state store (physical isolation, no tenant column).
No global business memory, no global index, no cross-client vector store.
All state access is workspace-bound through RunContext.
Cross-workspace access is denied by default.
```

AppFlow can maintain workspace-scoped operational state so follow-up
questions reuse prior observations, changes, decisions, and outcomes — but
workspace A's history can never automatically become workspace B's context.

**Continuous means session-persistent, not background monitoring.** State
persists across AppFlow sessions; AppFlow does not watch ad platforms in the
background (no daemon, cron, polling, or automatic ingestion).

## What it stores

Five object types, append-only:

- **Observation** — what was actually known at a point in time (facts, not
  explanations): spend, delivery, CTR, CPC, CPI, CPA, CVR, measurement
  state, maturity, campaign/creative/funnel state. Common envelope +
  platform-specific payload. Observations are facts; explanations belong to
  decisions.
- **Change** — a confirmed account/operation change: what changed, direction,
  magnitude, time, source, operator/system origin. An unconfirmed user
  statement ("我好像昨天收了点价") is a `reported` observation, never a
  change.
- **Decision** — what AppFlow recommended (keep/increase/decrease/pause/
  reopen/replace/wait/observe/investigate) with minimal context: decision
  class, concise reason, evidence refs, policy constraints, measurement and
  maturity state, confidence, review condition. Hidden chain-of-thought is
  never persisted (Broad internally, concise persistently).
- **Outcome** — what happened after a decision/change: improved/worsened/
  neutral/inconclusive/rolled_back/not_executed, linked to decision/change/
  observation ids.
- **Current State** — the derived summary AppFlow needs for the next answer:
  last event ids per type, measurement/maturity state, pending review, open
  questions, latest facts. It is **derived and rebuildable** from the event
  log; deleting it only forces a rebuild.

Layout (per workspace, physical isolation):

```text
workspaces/<client>/<project>/state/
├── schema.json              # schema version + workspace_id
├── .write.lock              # workspace-local write lock
├── events/
│   ├── 00000001-observation.json
│   ├── 00000002-change.json
│   ├── 00000003-decision.json
│   └── 00000004-outcome.json
└── current-state.json       # derived, rebuildable, freshness-tracked
```

## What it does not store

- full conversation history, client chat, emails
- creative full text, raw screenshots, tokens, cookies, browser state
- arbitrary free-form memory, operator personal notes, unrelated tasks,
  system prompts, hidden chain-of-thought
- any cross-client data

State is not a chat log. Only structured, decision-relevant facts are kept.

## Isolation model

- **Workspace** — the existing private directory (`workspaces/<client>/<project>/`)
  with its own `.gitignore`; already the security boundary for real data.
- **RunContext** — frozen runtime scope created once per run from the
  resolved workspace (workspace_id + client/project scope read from
  `project-context.yaml`). Every state read/write resolves paths through
  `Workspace.require_contained_path`; no API accepts an arbitrary filesystem
  path.
- **StateStore** — one per workspace; paths are always derived from the
  bound RunContext.

**Workspace identity is proven, not assumed.** The state schema stores
`workspace_id` (a random opaque UUID from the workspace metadata). Opening
a store compares it against the bound RunContext; a copied foreign state
tree (`cp -R B/state A/state`) is rejected. Legacy v3.3.0 stores (path
fingerprint only) migrate automatically when the fingerprint matches, and
are rejected otherwise. Moving a workspace directory is legal because the
identity lives in metadata, not the path.

**Concurrent writes are serialized per workspace.** Every append, rebuild,
and clear takes the workspace-local `state/.write.lock` (POSIX flock /
Windows msvcrt) for the critical section: allocate sequence → persist event
→ derive current state. Two runs cannot allocate the same sequence, and
workspaces A and B never block each other.

```text
Client A / Project A → State Store A → Reasoning A
Client B / Project B → State Store B → Reasoning B
```

Never:

```text
Global Memory → Client A / Client B
```

## Cross-workspace

Denied by default: A cannot read, search, compare, copy, or index B's state,
even if the user's natural language asks for it. Traversal (`../`), absolute
external paths, symlink escapes (including symlinks planted inside the
events directory), and cross-workspace source references are contract
errors. References resolve only inside the bound workspace, so a same-named
event in B can never satisfy a reference from A. Deleting A's state never
touches B, and there is no global store to leave a copy behind.

Explicit cross-workspace comparison (read-only, per-operation authorization,
normalized output) is a future capability; it is intentionally not
implemented yet.

## Privacy

- Production state stays inside the workspace; workspaces are git-ignored
  and never enter CI, evals, or the release artifact.
- The eval boundary is unchanged: synthetic/sanitized/production fixtures
  never read workspace state; tests use tmp workspaces with synthetic events.
- State keeps structured facts and normalized data, minimizes identity and
  free-form text; event ids are local sequence ids, never account/campaign
  ids or client names.

## Time model

`recorded_at` (when the event was written) and `observed_at` (when the fact
was true, observations only) both live in the event envelope; payloads never
repeat them. `effective_at` exists only on changes with a real
execution-time difference. Derived state follows event-log order — the
latest written observation is the latest business knowledge even when its
`observed_at` is earlier (out-of-order imports).

## Provenance

- Decision `origin`: `deterministic` | `agent_constrained` | `operator`.
  The common real case is `agent_constrained` (LLM hypothesis/interpretation
  constrained by measurement/maturity/policy/permission/numeric gates) —
  decisions never claim a purely deterministic origin by default, and their
  event `evidence_status` is `inferred` (a decision is a recommendation, not
  a business fact). Confidence is separate (`high`/`medium`/`low`).
- Observation `evidence_status`: confirmed (deterministic/imported) /
  reported (user statement) / inferred (derived); `source_type` is recorded.
- Every event carries the run's `run_id` (local random UUID, never business
  identifying) for association and debugging.

## Pending review

A decision with `review_condition` stays pending until an outcome links to
it — derived from the FULL event log, not a recent window, so an old pending
decision survives hundreds of later events. The next run can answer "现在呢?"
by reading current state. Pending review is a marker for the next
conversation, not a background job (no daemon, cron, polling, or
notifications).

## Bounded retrieval

Retrieval for the model is bounded (`get_recent(limit=…)`, capped at 100).
Current state derivation is separate: it scans the FULL event log (streaming,
bounded memory) and records `derived_through_sequence`. On read, a stale or
missing derived file (e.g. a crash between event write and rebuild) is
detected and rebuilt from the full log; the derived file is never the
single source of truth.

## Corruption behavior

- Corrupted `current-state.json` → rebuilt from events.
- Corrupted event file → explicit error; history is never silently cleared.
- Unexpected symlink anywhere in the state tree → explicit error.
- Event filename must match `event_id`/type inside the file; mismatch is an
  explicit error. `state verify` reports all integrity problems (identity,
  schema, sequence uniqueness, references, freshness) without fixing them.

## CLI (internal/debug)

Normal user workflows never manage state manually. Developer/debug commands:

```bash
python3 scripts/uac_experiment.py state init --workspace "workspaces/<client>/<project>"
python3 scripts/uac_experiment.py state status --workspace "..." [--json]
python3 scripts/uac_experiment.py state show --workspace "..." [--limit N] [--type observation|change|decision|outcome] [--json]
python3 scripts/uac_experiment.py state rebuild --workspace "..."
python3 scripts/uac_experiment.py state verify --workspace "..." [--json]
python3 scripts/uac_experiment.py state clear --workspace "..." --yes
```

`clear` is destructive and workspace-scoped; it requires `--yes` and only
touches the current workspace. `verify` is the state doctor: it reports
identity/schema/sequence/reference/freshness problems without fixing them.

## Python API

The runtime integration point for Agent workflows is `StateSession` (the
canonical lifecycle — skills never write state files directly):

```python
from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.state_runtime import StateSession

session = StateSession(RunContext.from_workspace(workspace))

# before_reasoning: ambiguous follow-up loads current state + bounded history
summary = session.load_context_summary()

# after_observation: reliable new facts (deduped per run by source_digest)
observation_id = session.record_observation(
    observed_at="2026-08-10T09:00:00Z",
    platform="google",
    facts={"ctr": 0.02, "spend": 62.0, "measurement_state": "stable"},
    source_type="export",
    source_digest="export-2026-08-10",
)

# after_decision: origin-aware recommendation (default agent_constrained)
decision_id = session.record_decision(
    decision_class="wait",
    reason="delivery dropped after bid reduction while CTR stable",
    evidence_refs=(observation_id,),
    origin="agent_constrained",
    review_condition="maturity sufficient",
)

# after_confirmed_change: ONLY after execution is confirmed
session.record_confirmed_change(
    change_type="tCPA", direction="decrease", magnitude=10.0
)

# after_outcome: only with later evidence
session.record_outcome(outcome_class="neutral", decision_id=decision_id)
```

Lower-level access (tests, migration tooling) uses `StateStore` directly:
`get_recent_changes(limit=5)`, `get_pending_review()`, `current_state()`,
`rebuild_current_state()`, `verify()`.

## Reasoning integration

The Reasoning Contract is unchanged; workspace state is an additional
**evidence source** for the Verify stage. Before entering the loop for a
vague question like "Google 怎么又不行了?", the run resolves the workspace,
creates a `StateSession`, and reads the current-workspace summary (bounded):
latest observation facts, recent changes, previous decision, previous
outcome, pending review — then Diverge → Verify → Eliminate → Rank →
Converge, and records the new Decision afterwards. History is evidence, not
an answer: an old causal explanation is never automatically treated as the
new cause. When the workspace has no history, the answer says so plainly;
AppFlow never borrows a similar case from another workspace.
