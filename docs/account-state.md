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
├── schema.json              # schema version + workspace fingerprint
├── events/
│   ├── 00000001-observation.json
│   ├── 00000002-change.json
│   ├── 00000003-decision.json
│   └── 00000004-outcome.json
└── current-state.json       # derived, rebuildable
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
  resolved workspace (client/project scope read from `project-context.yaml`).
  Every state read/write resolves paths through
  `Workspace.require_contained_path`; no API accepts an arbitrary filesystem
  path.
- **StateStore** — one per workspace; paths are always derived from the
  bound RunContext.

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
errors. Deleting A's state never touches B, and there is no global store to
leave a copy behind.

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
was true) are kept; `effective_at` is only added when truly necessary.

## Pending review

A decision with `review_condition` stays pending until an outcome links to
it. The next run can answer "现在呢?" by reading current state — pending
review is a marker for the next conversation, not a background job (no
daemon, cron, polling, or notifications).

## Bounded retrieval

Retrieval defaults are bounded (`get_recent(limit=…)`, capped at 100): the
store never loads the whole history into the model context. Current state
derivation consumes only the most recent events while counting the full log.

## Corruption behavior

- Corrupted `current-state.json` → rebuilt from events.
- Corrupted event file → explicit error; history is never silently cleared.
- Unexpected symlink anywhere in the state tree → explicit error.

## CLI (internal/debug)

Normal user workflows never manage state manually. Developer/debug commands:

```bash
python3 scripts/uac_experiment.py state init --workspace "workspaces/<client>/<project>"
python3 scripts/uac_experiment.py state status --workspace "..." [--json]
python3 scripts/uac_experiment.py state show --workspace "..." [--limit N] [--type observation|change|decision|outcome] [--json]
python3 scripts/uac_experiment.py state rebuild --workspace "..."
python3 scripts/uac_experiment.py state clear --workspace "..." --yes
```

`clear` is destructive and workspace-scoped; it requires `--yes` and only
touches the current workspace.

## Python API

```python
from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.state_store import StateStore

store = StateStore(RunContext.from_workspace(workspace))
observation_id = store.append_observation(
    observed_at="2026-08-10T09:00:00Z",
    platform="google",
    facts={"ctr": 0.02, "spend": 62.0, "measurement_state": "stable"},
    source_type="export",
    evidence_status="confirmed",
)
store.append_change(change_type="bid", direction="decrease", magnitude=12.0)
store.append_decision(
    decision_class="wait",
    reason="delivery dropped after bid reduction while CTR stable",
    evidence_refs=(observation_id,),
    review_condition="maturity sufficient",
)
store.append_outcome(outcome_class="neutral", decision_id=decision_id)

recent = store.get_recent_changes(limit=5)  # bounded
pending = store.get_pending_review()  # None until an outcome links
current = store.current_state()  # derived, rebuildable
```

## Reasoning integration

The Reasoning Contract is unchanged; workspace state is an additional
**evidence source** for the Verify stage. Before entering the loop for a
vague question like "Google 怎么又不行了?", the run reads current-workspace
history (bounded): latest observation facts, recent changes, previous
decision, pending review — then Diverge → Verify → Eliminate → Rank →
Converge. When the workspace has no history, the answer says so plainly;
AppFlow never borrows a similar case from another workspace.
