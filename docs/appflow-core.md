# AppFlow Core

Short engineering document. Defines the boundary between **AppFlow-level**
capabilities (shared by every platform) and **platform-specific** behavior
(owned by one platform's adapter), plus the operational runtime that
orchestrates them.

## Layers (v3.4.0)

```text
AppFlow Core
├── Reasoning Contract (the ONLY loop)
├── Workspace binding / isolation
├── AppFlowRuntime lifecycle
├── Continuous operational state
├── State access policy
├── Safety envelope (measurement/maturity/policy/permission)
└── Payload hygiene
        │
Platform Operational Runtime (PlatformOperationalRun)
├── platform-scope resolution (Router passes it; fallback detection)
├── platform-aware bounded state retrieval (no starvation)
├── evidence projection + Observation persistence
├── hypothesis families + safety context for the reasoning layer
└── Decision persistence + OperationalResult
        │
Platform Adapters (META / TIKTOK / CREATIVE)
├── hypothesis families
├── platform-specific metric projection
└── supported actions (shared classes + subtypes)
        │
Deterministic Specialization (Google UAC only)
└── normalization / numeric recommendation / policy / maturity /
    measurement / experiment ledger
```

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
`run_lifecycle.py`, `state_guard.py`, `state_adapters.py`,
`operational_runtime.py`, `platform_adapters.py`). The directory name is
historical; no urgent migration. `appflow_ops/runtime.py` is the public
facade: platform code imports `AppFlowRuntime`,
`PlatformOperationalRun`, `RunContext`, adapters from there instead of
reaching into `uac.*`.

## Platform Operational Runtime

`PlatformOperationalRun` (`operational_runtime.py`) is the canonical
operational lifecycle for Meta / TikTok / Creative / cross-platform:

```text
begin(request, platform_scope?, state_access?)
→ resolve workspace + platform scope
→ platform-aware bounded state load (per-platform budget, total capped)
→ record_observation(metrics)  # adapter projection + shared dedupe
→ operational_context()        # state + hypotheses + safety envelope
→ record_decision(...)         # shared decision classes + provenance
→ result() → OperationalResult
→ finish()
```

Callers no longer manage `StateSession` manually for normal operational
runs. Google UAC keeps its deterministic engine as a stronger decision
component; this runtime does not replace it.

## PlatformAdapter (thin contract)

Keep the contract minimal — projections and vocabulary, no framework:

```python
class PlatformAdapter:
    platform: str
    hypothesis_families: tuple[str, ...]
    specific_keys: tuple[str, ...]
    actions: tuple[str, ...]          # shared decision classes
    action_subtypes: Mapping[str, tuple[str, ...]] | None
    project_observation(metrics) -> facts   # common + platform-specific
    project_funnel(metrics) -> funnel facts
```

`PLATFORM_ADAPTERS` registry maps platform name → adapter (`adapter_for`).

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
- Platform-aware retrieval: state context is fetched per platform with a
  bounded budget (3 observations / 2 changes / 2 decisions / 1 outcome per
  platform, scope capped at 4 platforms), so one platform's recent history
  can never starve another platform out of context.
