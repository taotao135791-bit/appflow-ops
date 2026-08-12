# AppFlow Core

Short engineering document. Defines the boundary between **AppFlow-level**
capabilities (shared by every platform) and **platform-specific** behavior
(owned by one platform's adapter).

## Boundary

### AppFlow-level (shared core)

- **Reasoning Contract** — `skills/appflow/references/reasoning-contract.md`:
  Diverge → Verify → Eliminate → Rank → Converge is the ONLY reasoning loop.
  Platforms add hypothesis families and evidence sources; they never copy
  the loop.
- **Workspace binding** — `RunContext` / `Workspace`: every run is bound to
  exactly one workspace; cross-workspace access is denied by default.
- **Run lifecycle** — `AppFlowRuntime` (`run_lifecycle.py`): begin_run →
  classify → bounded state context → record_* → finish_run. Router/skill
  layers may pass `state_access` explicitly; unknown requests default to NO
  state access.
- **Continuous operational state** — `StateStore` / `StateSession`
  (append-only Observation / Change / Decision / Outcome + derived current
  state). State belongs to the current workspace only.
- **State access policy** — `classify_state_access`: non-operational
  intents never read state; operational follow-ups do; unknown stays closed.
- **Safety envelope** — measurement / maturity / policy / permission gates
  (`evals/safety.py` semantics; deterministic numeric bounds in the UAC
  policy kernel). Platforms consume the same four gates; they do not
  re-implement them.
- **Payload hygiene** — `state_guard.py` applies to every platform's state
  writes (credentials, raw chat, oversized payloads are rejected).

### Platform-specific (adapter-owned)

- Google UAC normalization, numeric recommendation, experiment ledger, and
  the deterministic quick-decision engine (the only fully deterministic
  decision runtime today).
- Meta auction/learning/audience concepts, Meta metric projection
  (frequency, CPM, cost cap), Meta hypothesis families.
- TikTok delivery/creative-freshness concepts, TikTok metric projection,
  TikTok hypothesis families.
- Creative diagnosis hypothesis families and action vocabulary.
- Platform-specific policy and permission vocabulary.

## Current layout

AppFlow-level code historically lives under `scripts/appflow_ops/uac/`
(`account_state.py`, `state_store.py`, `state_runtime.py`,
`run_lifecycle.py`, `state_guard.py`, `state_adapters.py`). The directory
name is historical; no urgent migration. New platform code must CONSUME
these modules through their public contracts and must not copy them.

## PlatformAdapter (thin contract)

Until at least two platforms actually reuse a shape, keep the contract
minimal — three projections, no framework:

```python
class PlatformAdapter:
    platform: str                          # e.g. "meta"
    hypothesis_families: tuple[str, ...]   # platform-specific, ordered
    project_observation(metrics: dict) -> dict   # sparse facts projection
    # decisions reuse the shared DECISION_CLASSES + StateSession; platform
    # detail goes in the payload
```

Rules:

- Adapters are projections only: no diagnosis, no policy, no maturity
  recomputation. The deterministic engine (Google UAC) or the Agent +
  shared reasoning loop is the source of truth.
- No new state types (no CreativeMemory, no AssetHistory): creative state
  uses Observation / Change / Decision / Outcome like everything else.
- No global platform state: all production business state stays inside the
  workspace.
- Cross-platform means multiple platforms INSIDE ONE workspace. It never
  means cross-client: another workspace's evidence is denied by default.
