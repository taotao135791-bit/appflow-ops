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
- **Never silently downgrade malformed safety enums into a less
  restrictive valid state.** Canonical `unknown` is valid; a typo'd
  measurement/maturity/policy/permission value fails closed with a
  ContractError in the validator, the policy resolver, and StateStore.
- **Decision safety metadata must match the canonical values actually
  used by the runtime validator.** What was validated must be what was
  persisted.
- **A single-platform Change may narrow a cross-platform Decision's
  Outcome only when the Change platform belongs to the Decision's
  scope.** Explicit cross_platform Outcomes keep the inherited scope.
- **Explicit `unknown` is current safety information and must not be
  replaced by stale historical certainty.** An absent field may fall back
  to history; an explicit `unknown` is itself new evidence that overrides
  it.
- **Cross-platform aggregation must treat missing safety state for an
  in-scope platform as `unknown`, not silently ignore that platform.**
- **A run's platform scope is a hard operational boundary.**
  Platform-bound observations outside that scope must be rejected
  (never persisted, never entering current context).
- **An empty run may bind to its first valid platform observation, but a
  bound single-platform run must never silently expand to another
  platform.** Explicit scopes are canonicalized at begin (registered-only,
  unique, sorted, ≤ MAX_PLATFORM_SCOPE).

- **Operational domains are not media platforms.** Creative/funnel/
  measurement keywords shape the diagnosis domain hint, never the
  platform scope (a "Meta 素材" request is platform_scope=[meta] with
  domain_hint=creative). Creative adapter stays registered for
  backward compatibility; the domain separation migration belongs to
  Ads Decision Intelligence.
- **Runtime / State / Safety / Platform Scope infrastructure is
  considered stable. Do not expand it without a concrete correctness,
  security, or product requirement.**
- **Do not conclude from a metric movement alone. Always consider
  plausible confounders and competing hypotheses before convergence.**
- **A hypothesis may be supported, weakened, excluded, or remain
  unverified. Missing evidence is not evidence for another hypothesis.**
- **The default product output is a decision, not a diagnostic report.**
  Ads Decision Intelligence may explore broadly internally, but the
  default user-facing answer should contain only the conclusion,
  strongest evidence, material exclusions, uncertainty if necessary,
  and next action.
- **Decision Intelligence must be exercised through the operational
  runtime in end-to-end tests.** Manually wiring signals and evaluators
  is not sufficient evidence of product integration.
- **A materially supported competing hypothesis prevents confident
  convergence unless it is weakened, excluded, or the chosen action is
  explicitly reversible and information-gathering.** Score gap alone is
  never enough to eliminate a supported rival.
- **Operational Decision Intelligence must never assume stable
  measurement or sufficient maturity when runtime safety context is
  unavailable.** The canonical SafetyContext flows unchanged into
  evaluation and persistence.
- **Historical State should affect Decision Intelligence only through
  evidence with clear provenance.** Prior recommendations are context,
  not factual proof; confirmed changes are confounders; outcomes are
  evidence, never causal proof.
- **Cross-platform hypotheses require cross-platform evidence.** Never
  promote a single-platform signal into a shared diagnosis — shared
  signals exist only when >= 2 distinct platforms agree; per-platform
  provenance is preserved in every evidence projection.
- **A normal Decision Intelligence persistence path must preserve the
  action produced by convergence.** Human overrides must be explicit and
  attributable (origin=operator_override with the original DI action).
- **Never combine supporting signals from different platforms into a
  single platform-specific hypothesis.** Platform-bound evaluations
  consume only their platform's signals; shared hypotheses consume
  shared signals only.
- **Never derive a time trend across different entities, levels, or
  incompatible breakdown scopes.** Same platform alone never implies
  comparable observations.
- **“Latest stored change” and “recent causal confounder” are not
  synonyms.** A Change is a confounder only when it intervened between
  the comparable baseline and the current observation.
- **“Applicable to all platforms” means evaluate separately on each
  platform** unless a hypothesis is explicitly shared or run-level.
  Wildcard hypotheses are never a flat union of all platforms.
- **Safety provenance must match evidence provenance.** Platform-bound
  hypotheses use that platform's measurement/maturity state; aggregate
  Safety is reserved for shared/run-level conclusions.
- **A Change from one media platform must never become another
  platform's confounder.**
- **Missing identity is not evidence of account-level aggregation.**
  Comparable identity uses workspace-local opaque entity_key — raw
  external IDs are never persisted.
- **Convergence must preserve the same provenance boundary used by
  evidence evaluation.** Platform-bound tops use that platform's
  measurement/maturity (missing platform safety → unknown, never an
  aggregate fallback); shared and run-level tops use aggregate Safety.
- **Do not replace a ranked diagnosis with a safety action.** A safety
  block changes convergence/action, not historical evidence or
  hypothesis identity — `investigate_measurement` is not the same as
  `top_hypothesis = measurement_instability`.
- **`top_hypothesis`, `top_platform`, and evaluation scope must always
  come from the same selected evaluation.** A safety block cannot
  silently rewrite attribution, and a persisted Decision's platform
  attribution must match the selected evaluation (a safety problem on
  one platform is never a veto on an independent diagnosis for another,
  but it can still block a shared cross-platform conclusion).

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
- **Prefer false negatives over high-confidence false positives when
  evidence volume is weak.** A -25% CTR on 150 impressions is not the
  same evidence as the same movement on 100k impressions; metric-level
  sample sufficiency is separate from campaign maturity.
- **Budget or bid constraint does not imply scale eligibility.** A
  scaling action (increase/scale) requires measurement reliability,
  sufficient maturity, settled recent changes, and acceptable efficiency
  against the KPI target — otherwise hold/wait.
- **Do not use downstream performance decline as evidence of measurement
  failure when measurement health is explicitly stable.** Stable
  measurement is a strong contradiction to measurement instability.
- **A confounder should usually weaken confidence or create a competing
  hypothesis, not automatically exclude a plausible diagnosis.** Recent
  budget/bid changes weaken creative fatigue; they never prove it
  impossible.
- **Unknown sample volume should reduce confidence rather than inherit
  full evidence weight.** Missing base population / success-event facts
  are uncertainty (weak), never proof of sufficiency.
- **Do not scale merely because current CPA/CPI is marginally below
  target or ROAS marginally above target.** KPI headroom, outcome
  volume, sample strength and settled recent changes all gate a scaling
  action; a marginal pass defers to wait/needs-more-evidence.
- **A measurement-domain diagnosis must not be suppressed merely
  because measurement is invalid; invalid measurement is often the
  evidence for that diagnosis.** The invalid-measurement cap classifies
  by hypothesis domain, never an ID whitelist.
- **Action eligibility for one platform must never inherit another
  platform's recent changes.** Platform-bound action context comes from
  the selected platform's own facts, signals and safety.
- **Never use install volume to justify scaling against a pay or
  purchase KPI.** Outcome evidence must match the KPI being optimized
  (pay CPA → payments, purchase CPA → purchases, ROAS → purchases/
  conversions); missing KPI-matched volume defers scale
  (missing_outcome_volume) — impressions never stand in for
  conversions.
- **If multiple KPI targets exist and no primary KPI is known, do not
  guess.** Explicit primary_kpi (or a single present target) drives the
  target/actual comparison and the outcome-volume check; multiple
  targets without a declaration are ambiguous_primary_kpi → defer.
- **`measurement=unknown` and `maturity=unknown` are acceptable for
  investigation but not for scale approval.** Scale requires
  measurement==stable and maturity==sufficient — unknown safety defers
  the action while the diagnosis may still be ranked.
- **A supported hypothesis on another media platform is not
  automatically a rival to the selected platform's diagnosis.** Same-
  platform supported candidates and shared/run-level candidates are
  material rivals; different-platform independent issues are parallel
  issues that never block the selected platform's action.
- **Explicit trend labels do not bypass sample sufficiency.** ctr_trend=
  "down" on 150 impressions is weak evidence, exactly like
  ctr_change_pct=-25% on 150 impressions; a trend string with no sample
  facts is weak too.
- **Never reconstruct top evidence by hypothesis ID alone when multiple
  platform-bound evaluations share that ID.** The summary consumes
  result.selected_evaluation — auction_pressure@google_ads as top never
  cites auction_pressure@meta's evidence.
- **conversion_event=pay is an event semantic, not the literal KPI enum
  pay_cpa.** Normalize events/goals to KPI types (normalize_goal_to_kpi)
  with a matching target; an explicit primary_kpi that contradicts an
  explicit goal is ambiguous, never a guess.
- **Parallel issues must retain their platform attribution.**
  creative_fatigue@meta is not creative_fatigue@tiktok; user output
  names the platform.
- **A supported shared hypothesis is not automatically a veto; determine
  whether it materially invalidates the selected action.** Shared
  funnel/measurement issues block scale actions; market-wide context
  warns (material context) but does not block.
- **Generic conversions must not be treated as ROAS outcome volume
  unless the conversion event is known to be revenue-generating.**
- **KPI-specific action evidence must remain semantically aligned from
  target → actual → outcome volume.** The minimum outcome evidence for
  scale is KPI-family aware (KPI_SCALE_MINIMUMS) — 20 installs and 20
  payments are not the same scale evidence; unknown families never
  fall back to a universal count.
- **Never recommend a second material adjustment before the previous
  confirmed change has accumulated enough new evidence.** Action
  readiness (elapsed time + KPI-matched window outcomes since the
  change) gates scale/descale — eligibility is not readiness.
- **Total historical conversions are not equivalent to conversions
  observed after the latest material change.** Use window_outcomes
  (post-change), never lifetime totals, for post-change readiness.
- **One material lever at a time is the default. Do not change budget
  and bid together unless a platform-specific deterministic contract
  explicitly requires it.** Diagnose the constraint (budget vs bid)
  before choosing the lever.
- **A temporary KPI deterioration immediately after a change is a
  reason to inspect the evidence window, not automatic proof that the
  change failed.** Never decrease right after an increase without new
  material evidence (no ping-pong).
- **`wait` must specify what evidence or condition should trigger the
  next review.** wait_reason + next_review_trigger are part of the
  decision, never a bare "wait".
- **Creative refresh, retest, pause, and hold are distinct operational
  decisions.** Fatigue with acceptable overall KPI → refresh; weak or
  confounded evidence → retest; a specific consistent loser with
  sufficient sample → pause; a new creative in its test window → hold.
- **Never ask the caller to provide a derived post-change outcome count
  when the runtime can reconstruct it from persisted state.** `window_outcomes`
  is derived state, not primary observation input.
- **Timing provenance follows the selected evaluation.** Do not use
  another platform's latest change or observation timestamp for a
  platform-bound action.
- **Never subtract cumulative counters across entity changes or detected
  counter resets.** A decreased counter is `not_comparable`, never a
  negative outcome count.
- **Lifetime maturity does not prove that the current post-change
  decision window is mature.** Reverse actions need enough new evidence
  after the latest material change.
- **A reverse action must be justified by evidence accumulated after the
  previous material change** (no budget/bid ping-pong).
- **Confirmed creative changes must influence creative test readiness
  through state, not caller-supplied booleans.**
- **Never subtract two outcome values unless their counter semantics are
  explicitly comparable** (both declared cumulative).
- **A platform match is not enough for change attribution when entity
  identity is available.**
- **Do not let a change on Campaign A reset Campaign B's decision window.**
- **Creative changes do not automatically reset budget scale/descale
  windows.**
- **Relevant change types depend on the action family being evaluated.**
- **Compare parsed timezone-aware instants, not ISO strings.**
- **Interval outcome values may inform diagnosis but must not be treated
  as cumulative counters.**
