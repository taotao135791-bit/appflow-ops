# AppFlow Ops Project Notes

AppFlow Ops is a local skill bundle for overseas app-promotion agency
operations: paid media audits, UAC experiment loops, funnel diagnosis
dashboards, creative review, PPC calculators, attribution checks, client
reporting, and rapid response to urgent client demands.

Its core reasoning principle is Diverge → Verify → Eliminate → Rank →
Converge (see README): users state business problems, AppFlow decides how to
investigate them; explore broadly internally, answer concisely externally.

## Non-negotiable design principles

- **No global business memory.** Every persistent business state must have
  an explicit workspace owner (`docs/account-state.md`). Never create a
  global index, global cache, cross-client database, or cross-workspace
  vector store holding business data.
- **One workspace = one state store.** State lives physically under the
  workspace root (`state/`); all state access is workspace-bound through
  `RunContext`. Cross-workspace reads/writes/references are denied by
  default; workspace A's history never becomes workspace B's context.
- **State is written through the runtime API only.** Agent workflows use
  `AppFlowRuntime` (canonical entry: begin_run → state_context → record_* →
  finish_run) or the lower-level `StateSession`; never write state files
  directly. The runtime classifies requests: direct informational questions
  never read or write state; follow-up/diagnosis/decision requests
  auto-load bounded context (unknown requests default to NO state access;
  the Router may pass `state_access` explicitly). A recommendation alone
  never records a Change; outcomes need later evidence; decisions carry
  real provenance (origin, not a hardcoded deterministic claim).
- **Continuous Account State is a stable foundation.** Do not expand State
  infrastructure unless a concrete product requirement or correctness
  defect requires it: no new event types, no search engine, no vector
  memory, no scheduler, no analytics on state. The next phase is platform
  adoption — reuse the shared reasoning + state runtime across Meta,
  TikTok, creative diagnosis, and cross-platform operations — not more
  StateStore work.
- **New platform integrations must adopt the shared operational runtime
  before introducing platform-specific infrastructure.** Do not create
  platform-local copies of State, Reasoning, or Safety infrastructure:
  `PlatformOperationalRun` + the platform adapters are the only sanctioned
  operational path for non-Google platforms, and platform-specific
  evidence goes through the adapters' projection (never raw dumps).
- **Platform-scoped events must remain attributable to their platform or
  explicit platform scope.** Decisions / Changes / Outcomes carry
  `platform` (or `cross_platform` + `platform_scope`); platform-filtered
  retrieval must never broadcast legacy unscoped events, and safety state
  must be derived per platform — one platform's measurement/maturity can
  never pollute another platform's context.
- **Safety expectations in tests are insufficient; supported operational
  decision paths must run through the runtime safety validator.**
  Candidate decisions go through `validate_decision_action` before
  persistence (measurement / maturity / policy / permission +
  execution-claim check); rejected candidates are never persisted and are
  reported via reason codes with allowed next actions.
- **Never persist a constrained candidate unless the runtime has produced
  a concrete compliant candidate.** `allowed → persist`; `rejected → no`;
  `constrained without a validated candidate → no`. The runtime performs
  no numeric rewriting.
- **Cross-platform runs require explicit target attribution for confirmed
  platform changes.** A Decision may be cross-platform; a Change acts on
  one explicit platform; an Outcome inherits scope from its linked
  Decision/Change. Execution claims are never valid Decision content,
  regardless of permission level.
- **Never remove platform attribution from semantic event identity.**
  Platform and canonicalized platform scope are part of deduplication
  identity; identical content on different platforms is different events.
- **Validation and persistence must consume the same canonical decision
  candidate.** Unknown structured enum values (e.g. malformed
  `diagnosis_confidence`) fail closed with a ContractError in both the
  validator and StateStore.
- **Run-local caches must never survive a new operational `begin()`.**
  Every begin() creates a fresh StateSession (new run_id, empty dedupe
  set); dedupe is run-local only.

## Layout

- `skills/appflow/SKILL.md`: main `/appflow` router skill (question
  discipline, client isolation, routing table).
- `appflow/SKILL.md`: byte-for-byte legacy mirror of the router, kept in sync
  by `scripts/sync_skill_layout.py`.
- `skills/ads-*`: focused sub-skills for app platforms (Google, Meta,
  TikTok, Apple) and agency workflows.
- `skills/ads-google-app`: UAC feasibility, structured analysis, quick
  numeric decisions, and local experiment-ledger contracts.
- `agents/*.md`: reusable audit and creative persona briefs, installed inside
  the main skill at `agents/` and dispatched to the host's built-in subagent
  mechanism.
- `skills/appflow/references/*.md`: scoring, platform specs, compliance,
  benchmarks, client question discipline, and implementation references.
- `scripts/*.py`: local deterministic tools.
- `scripts/uac_experiment.py`: deterministic UAC CLI (workspace, normalize,
  doctor, analyze, decide, ledger review, replay, funnel-dashboard, state).
- `scripts/appflow_ops/uac/account_state.py` + `state_store.py`:
  workspace-scoped continuous account state (append-only events + derived
  current state; bounded retrieval; pending review).
- `scripts/funnel_dashboard.py`: standalone funnel dashboard entry point.
- `scripts/appflow_ops/uac/`: the typed deterministic engine package.
- `appflow.plugin.json`: plugin manifest (`"skills": "./skills/"`).
- `tests/`: pytest coverage for routing, scoring, check catalogs, isolation,
  and URL safety.

## Install

Default install target is host-agnostic (`~/.appflow/skills`):

```bash
bash install.sh
```

This installs skills to `~/.appflow/skills` and agent persona briefs to
`~/.appflow/skills/appflow/agents`. Host-specific targets: `--target=codex`,
`cursor`, `windsurf`, `gemini`, `goose`.

## Development

Run the test suite with:

```bash
pytest -q
ruff check scripts tests
mypy scripts/appflow_ops/uac
python3 scripts/sync_skill_layout.py --check
```
