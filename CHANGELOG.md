# Changelog

All notable changes to AppFlow Ops are documented here.

## 3.5.5 — 2026-08-13

### Fixed

- **Platform-bound diagnoses are no longer globally vetoed by another
  platform's measurement or maturity state**: `converge()` now resolves
  Safety from the SELECTED evaluation's scope
  (`resolve_evaluation_safety`) — Meta measurement invalid never turns a
  supported `auction_pressure@google_ads` into a run-wide
  `investigate_measurement`, and Meta immaturity never turns the whole
  run into a wait.
- **Convergence now resolves Safety from the selected evaluation
  scope**: platform-bound tops use that platform's own
  measurement/maturity (missing platform safety → `unknown`, never an
  aggregate fallback); shared and run-level tops use aggregate Safety
  (conservative).
- **Final hypothesis/platform attribution cannot diverge**: `top_hypothesis`,
  `top_platform` and `top_evaluation_scope` always derive from ONE
  `selected_evaluation` (hard invariant, asserted for every eval fixture
  and enforced in the result builder).
- **Safety investigation actions no longer replace the ranked diagnosis
  identity**: `investigate_measurement` is expressed as
  `safety_block=measurement_invalid` beside the unchanged diagnosis,
  never as `top_hypothesis=measurement_instability` unless that is the
  real ranking.
- **Shared conclusions remain conservatively gated by aggregate Safety**:
  Meta pay↓ invalid + Google pay↓ stable can rank
  `shared_product_funnel_issue`, but one invalid platform still blocks a
  confident cross-platform product conclusion.
- **Persisted Decision attribution matches the selected evaluation**: a
  platform-bound diagnosis persists with `platform=google_ads` (validated
  with Google's own Safety); a blocked shared diagnosis stays
  `platform=cross_platform` + scope — a safety action never rewrites
  diagnostic attribution.

### Changed

- **Decision Intelligence result now preserves selected evaluation scope
  through convergence and persistence**: `selected_evaluation`,
  `top_evaluation_scope`, `safety_block`, and `platform_warnings` (e.g.
  `{"meta": ("measurement_invalid",)}` — a warning on one platform is
  never a veto on an independent diagnosis for another).
- `converge()` accepts an optional `SafetyContext` (runtime-native path
  always passes it); legacy `measurement_state`/`maturity_state` remain
  for library callers.

Eval set expanded 68 → 74 real scenarios (platform-bound convergence
surviving other-platform invalid/insufficient, shared diagnosis blocked
by aggregate invalid, single-platform invalid unchanged, run-level
aggregate invalid, supported-rival behavior unchanged under
provenance).

## 3.5.4 — 2026-08-13

### Added

- **Explicit hypothesis evaluation scopes**: `HypothesisSpec.evaluation_scope` (platform / shared / run). `applicable_platforms="*"` now means "evaluate separately on every applicable platform" — a wildcard hypothesis is NEVER a flat union of all platforms; `conversion_funnel_degradation@meta` and `@google_ads` are independent evaluations consuming only their own platform's signals.
- **Per-platform Safety provenance**: platform-bound evaluations use that platform's `measurement_by_platform` / `maturity_by_platform` — Meta measurement invalid never caps Google's auction diagnosis, and aggregate invalid never creates measurement instability on a stable platform; aggregate Safety is reserved for shared/run-level conclusions.
- **Platform-bound Change confounders**: a Change is a confounder ONLY for the platform it affected (event platform / target_platform); temporal relevance uses THAT platform's baseline/current window; Meta budget+30% never becomes Google's recent budget interference.
- **Newest-comparable historical selection**: the runtime walks the bounded per-platform history and picks the newest COMPARABLE baseline — a newer incomparable record (Campaign B) never blocks an older comparable one (Campaign A).
- **Explicit unknown-vs-account identity semantics**: missing entity identity is NEVER evidence of account-level aggregation (no derived trend); explicit `entity_level=account` + `aggregate_scope=account` (or explicit entity + entity_key) enables comparison.
- **Privacy-safe comparable entity identity**: `entity_key` (workspace-local opaque identifier) replaces raw `entity_id` on the write path — raw external campaign/ad IDs are never persisted; legacy `entity_id` records stay readable for comparability.
- **Run-level evidence**: `platform_divergence` (≥ 1 platform declining while ≥ 1 stable on the same metric) is the explicit run-level fact for `platform_specific_independent_issues` — never assembled from a flat union.

### Fixed

- **Wildcard hypothesis cross-platform signal splicing**: Meta CVR↓ + Google multi_creative_impacted can no longer be combined into one funnel evaluation.
- **Aggregate Safety suppressing healthy-platform diagnosis**: Google auction stays evaluable while Meta is invalid.
- **Aggregate measurement signals supporting wrong platform**: measurement_instability is supported only where that platform is actually invalid.
- **Meta Change contaminating Google/TikTok hypotheses**: change signals are platform-scoped (legacy unscoped Changes keep broadcast for backward compatibility).
- **Newest-but-incomparable history hiding valid older baseline**: bounded search continues past incomparable records.
- **Missing entity identity treated as account aggregate**: identity unknown → no derived trend (explicit markers required).
- **Measurement conflict supporting shared measurement issue**: `measurement_conflict` (Meta invalid + Google stable) signals "investigate consistency", never "shared measurement problem confirmed"; `cross_measurement_invalid` (≥ 2 platforms invalid) is the shared evidence.

Eval set expanded 60 → 68 real scenarios (wildcard splicing, Safety isolation, Change isolation, unknown identity, account-aggregate comparability, entity_key comparability, conflict-vs-shared-issue).

### Added

- **Provenance-aware hypothesis evaluation**: `evaluate_hypotheses()` consumes an `EvidenceResult` instead of a flat dict; platform-bound hypotheses are evaluated PER PLATFORM against that platform's own `signals_by_platform` (e.g. `auction_pressure@meta` vs `auction_pressure@google_ads`); every evaluation carries `platform` attribution; `DecisionIntelligenceResult.top_platform` tells the user output whether the conclusion is Meta-side or shared.
- **Shared-only cross-platform evidence**: `market_wide_event` requires `cross_cpm_up` (≥ 2 platforms rising) instead of a single platform's `cpm_trend_up`; `shared_measurement_issue` requires `cross_measurement_invalid` (≥ 2 platforms invalid) or a real conflict — a single platform's aggregate invalid no longer promotes it.
- **Historical comparable-identity checks**: derived trends require the same (entity_level, entity_id, breakdown_scope) — same platform alone never implies comparable observations; different entity/level/breakdown fails conservative (no trend).
- **Temporal Change relevance**: a stored Change is a confounder only when `baseline_observed_at < effective_at <= current_observed_at` (intervening); changes before the baseline or very old changes are never `recent_*`; age metadata (`last_budget_change_effective_at` etc.) retained for audit.
- **Distinct creative/audience/campaign change context**: `recent_creative_change` / `recent_audience_change` / `recent_campaign_change` / `recent_campaign_restart` replace the merged semantics.
- **Global temporal context ordering**: latest previous Decision/Outcome chosen by canonical timestamp (effective_at / observed_at) with deterministic event_id tie-break; per-platform latest retained (`decisions_by_platform` / `outcomes_by_platform`).

### Fixed

- **Cross-platform signal splicing**: Meta pay↓ + TikTok stable can no longer support TikTok `pay_funnel_degradation`; a platform-bound evaluation never consumes another platform's signals.
- **Single-platform evidence supporting shared hypotheses**: one-platform CPM↑ no longer supports `market_wide_event`; one-platform pay↓ never promotes `shared_product_funnel_issue`.
- **False market-wide evidence**: `market_wide_event` needs true cross-platform CPM evidence.
- **Non-comparable historical trend derivation**: Campaign A → Campaign B no longer derives `ctr_trend_down`.
- **Stale Change permanently treated as recent**: two-month-old budget changes are no longer confounders.
- **invalid+unknown misclassified as measurement conflict**: only explicit invalid+stable is a conflict; incomplete coverage stays conservative.
- **Cross-platform context latest-event ordering**: tuple order no longer decides the latest Decision/Outcome.

Eval set expanded 52 → 60 real scenarios (splicing regression, market-wide FP, comparability, temporal confounder, change types, invalid+unknown vs invalid+stable).

### Added

- **Historical State → DI evidence projection**: `evaluate_decision_intelligence()` now consumes current observations + comparable previous observations (same platform, same metric family) + recent confirmed changes + prior decisions/outcomes + canonical SafetyContext via a thin `build_evidence()` layer; evidence carries provenance (`signals_by_platform` / `shared_signals` / `historical_comparisons`).
- **Current-vs-previous automatic trend derivation**: with no caller-supplied `change_pct`, the runtime derives trends from raw current + previous values using the SAME ±10%/±5% thresholds as explicit trends; explicit canonical trends always win; a single value without comparable history never invents a trend.
- **Recent Decision / Change / Outcome operational context**: confirmed budget/bid changes become `recent_budget_change` / `recent_bid_change` confounder signals (a CTR drop right after budget+30% is not instantly creative fatigue); prior Decision is context (decision_class / review_condition / review_after), never factual support; Outcome is evidence, never causal proof.
- **Per-platform and shared cross-platform signal provenance**: `signals_by_platform` preserves which platform produced which signal; `shared_signals` exist ONLY when ≥ 2 distinct platforms agree (cross_pay_rate_drop / cross_cvr_drop / cross_registration_drop / cross_install_drop / cross_platform_comparison_available / measurement_conflict); a divergent pair (Meta down + Google stable) is the single-platform decline case, not shared evidence.
- **Explicit operator override semantics**: `record_decision_override(action, reason, result)` persists a human override with `origin="operator_override"` + the original DI action in the reason; it never masquerades as a DI recommendation and still passes all Safety gates.

### Fixed

- **Current-only DI behavior**: “现在呢？” now genuinely uses the previous State (E2E proves derived `ctr_trend_down` + `recent_budget_change` come from history, not hand-fed values).
- **Silent DI action override**: `record_decision_from_intelligence()` no longer accepts an `action` parameter — the persisted action always equals `DecisionIntelligenceResult.recommended_action` (supported-rival investigate stays investigate).
- **Single-platform evidence supporting shared funnel diagnosis**: `shared_product_funnel_issue` / `shared_measurement_issue` are supported ONLY by cross-level signals; a plain `pay_rate_trend_down` on one platform never promotes them; `cross_platform_comparison` evidence can no longer be satisfied by creative-level signals.
- **Flattened cross-platform signal ambiguity**: flat `dict.update()` merge replaced by provenance-preserving `signals_by_platform` + `shared_signals`.
- **cross_platform bool contradicting platform_scope**: explicit `cross_platform=False` with a multi-platform scope (or `True` with a single-platform scope) now raises ContractError — `platform_scope` is the single source of truth; the eval runner derives semantics from scope.
- **Misleading library integration E2E naming**: `test_runtime_integration.py` renamed to `test_library_integration.py` with the pipeline-assembly test renamed; runtime E2E uses only public operational entries.

Eval set expanded 42 → 52 real scenarios (historical follow-up, recent-change confounders, one-platform-only decline, shared-drop, measurement conflict, previous-decision wait, ambiguous band).

### Added

- **Runtime-native Decision Intelligence evaluation**: `PlatformOperationalRun.evaluate_decision_intelligence()` assembles the full pipeline internally (current observations → raw evidence → signals → hypotheses → evaluation → ranking → convergence) — callers never wire `build_hypothesis_set` / `signals_from_metrics` / `evaluate` / `rank` / `converge` manually; `record_decision_from_intelligence()` persists the DI recommendation through the existing Safety validator (Decision ≠ Change preserved; canonical SafetyContext flows unchanged into evaluation and persistence).
- **Raw evidence → signal → hypothesis E2E**: `*_change_pct` numeric relative movement generates trend signals via material thresholds (±10% down/up, ±5% stable, ambiguous band emits nothing); `signals_from_platforms()` adds per-platform extraction with cross-level aggregations (`cross_pay_rate_drop` / `cross_cvr_drop` when ≥ 2 platforms share a drop); `measurement_stable` is positive evidence (stable is evidence, not absence).
- **Strict ranked-top eval integrity**: `acceptable_top` is judged on RANKED results only (first non-weakened/non-excluded hypothesis) — registry order can never rescue a wrong top; `forbidden_top` rejects hypotheses that must never rank first; eval fixtures may start from raw `metrics` / `per_platform_metrics`; eval set expanded 30 → 42 real scenarios.
- **Runtime SafetyContext propagation**: operational DI never defaults to `stable`/`sufficient` — measurement/maturity/policy/permission come from the same canonical resolvers used by `record_decision()`; measurement invalid blocks confident diagnosis (`investigate_measurement` first).
- **`summarize_decision_intelligence(result)`**: short user-facing answer (conclusion → strongest evidence → material exclusion/alternative → next action → review condition); insufficient evidence answers “先别动” plus the most needed data.

### Fixed

- **Unreachable stable funnel signals**: `registration_rate_trend_stable` and `pay_rate_trend_stable` are now producible via both string-trend and numeric-change paths; signal registry consistency is asserted by tests (no declared-but-unreachable trend signal).
- **Cross-platform hypothesis builder footgun**: multi-platform scopes automatically enable cross-platform logic (`platform_scope` is the source of truth; explicit bool is backward-compat only) and never fall back to ALL_HYPOTHESES — `applicable_platforms` really filters (Meta+Google never evaluates TikTok-only hypotheses; shared hypotheses like auction_pressure stay candidates).
- **Supported-rival premature convergence**: a materially supported runner-up (status=supported with material score) is a MAJOR ALTERNATIVE — score gap alone no longer eliminates it; convergence answers `investigate` + `next_discriminating_evidence` instead of a confident action.
- **Eval false-positive top-hypothesis acceptance**: removed the un-ranked `live` rescue; eval now fails loudly when the ranked top is wrong.

### Added

- **Ads Decision Intelligence Foundation**: AppFlow enters the product
  phase — real ad problems get candidate causes, verification,
  elimination, ranking, and convergence to the smallest useful action.
  - **Operational domains**: `detect_operational_domain()` distinguishes
    creative / funnel / measurement / bid_budget / delivery / auction /
    audience / cross_platform / general; platform scope and domain are
    separated ("Meta 素材是不是衰减" → scope=[meta] + domain=creative).
  - **Structured HypothesisSpecs** (not name lists): supporting /
    contradicting signals, required evidence, exclusion conditions,
    smallest-first possible actions. Meta 14 families, TikTok 8 funnel
    hypotheses, Cross-platform 4 families.
  - **Evidence evaluation**: deterministic scoring (+2 support, -2
    contradiction, 0 missing); missing evidence is never evidence for
    another hypothesis; safety caps (invalid measurement → only the
    measurement hypothesis may be supported; insufficient maturity →
    nothing may be supported).
  - **Ranking & convergence**: status-priority deterministic ranking;
    convergence requires a strong top hypothesis with weakened/excluded
    rivals — otherwise an honest "wait" naming the decisive missing
    evidence. Budget/bid actions only when justified; recent changes
    confound creative diagnosis (exclusion conditions).
  - **Eval set**: 30 real scenario fixtures
    (`evals/decision-intelligence-cases.yaml`) with acceptable_top /
    acceptable_actions / forbidden_actions / required_considerations /
    convergence_blocked assertions, covering Meta, TikTok, cross-platform,
    vague queries, measurement conflict and maturity gaps.
  - **Facade**: `appflow_ops.runtime` re-exports
    detect_operational_domain / build_hypothesis_set /
    evaluate_hypotheses / rank_hypotheses / converge.
  - **Docs**: `docs/ads-decision-intelligence.md` (platform vs domain,
    hypothesis specs, evidence semantics, elimination/ranking,
    convergence, answer contract).

### Fixed

- **Late-bound scope now rebinds historical state**: an empty-scope run
  that preloaded multi-platform history rebinds `state_context` to the
  bound platform the moment its first observation binds the scope (bind →
  rebind → persist), so a Meta-bound run never exposes TikTok history.

### Changed

- **Core is frozen**: Runtime / State / Safety / Platform Scope
  infrastructure is stable; AGENTS.md forbids expansion without a
  concrete correctness, security, or product requirement.

## 3.4.6 — 2026-08-12

### Fixed

- **Observations can no longer escape the active run platform scope**: a
  scoped run rejects out-of-scope observations
  (`observation_platform_outside_run_scope`) before anything is persisted
  or enters current context — a Meta run can never absorb TikTok
  evidence, and cross-platform runs reject third platforms.
- **Explicit platform scopes are canonicalized and bounded at begin**: one
  `canonicalize_platform_scope()` for explicit and router-detected scopes
  alike — registered platforms only (adapter registry), duplicates
  removed (("meta", "meta") is ONE platform, never cross-platform),
  deterministic sorted order, and > MAX_PLATFORM_SCOPE rejected (never
  silently truncated). Unknown platforms fail at the run boundary.
- **Empty runs bind consistently to the first valid platform
  observation**: begin() with no scope binds (meta,); safety, decision
  attribution and persistence all use the same bound boundary; a bound
  single-platform run never silently expands to another platform
  (multi-platform requires an explicit scope).
- **Single-platform current observation no longer falls back to another
  platform**: `current_observation` is the run platform's own evidence or
  None — the arbitrary "last observation" substitution is gone; the
  `_decision_platform` observation-only inference fallback was removed as
  unreachable.

### Changed

- **Documented distinction between media platform scope and operational
  domain routing**: creative/funnel/measurement keywords produce a
  lightweight `operational_domain_hint` (context-only); the creative
  adapter stays registered and backward compatible — the domain
  separation migration belongs to Ads Decision Intelligence.

## 3.4.5 — 2026-08-12

### Fixed

- **Explicit current unknown safety state no longer falls back to stale
  historical certainty**: absent ≠ unknown — a current Observation
  missing `measurement_state`/`maturity_state` may use history, but an
  explicit `unknown` is new safety evidence that overrides yesterday's
  `stable`/`sufficient` (freshness: current field wins, history only when
  the field is absent).
- **Cross-platform missing safety evidence now aggregates conservatively
  as unknown**: aggregation covers the full scope — an in-scope platform
  with no safety state counts as `unknown`, so `stable + missing →
  unknown` (never silently `stable`); conservative precedence preserved
  (`invalid`/`insufficient` > `unknown` > `stable`/`sufficient`).
- **Invalid `platform=None + platform_scope` future writes rejected**: a
  scoped-but-unattributable ghost event can no longer be created;
  `platform=None` requires an empty scope; legacy unscoped events remain
  readable (no history migration).
- **Direct State decision path validates canonical policy/permission
  states**: `policy_constraints` carrying malformed `policy_state` /
  `permission_state` fails closed; unrelated policy metadata keys are
  still allowed; runtime decision path unaffected.

### Changed

- **Roadmap now points to Ads Decision Intelligence** (Meta auction
  pressure vs creative fatigue vs audience saturation; TikTok
  click→install and deep-funnel diagnosis; Creative continue/replace/
  retest/scale; Bid & Budget when/how-much/when-to-wait; Cross-platform
  media vs product vs measurement diagnosis) instead of Platform
  Adoption.

## 3.4.4 — 2026-08-12

### Fixed

- **Decision safety context preserved**: the runtime now persists the
  exact canonical measurement/maturity states its validator consumed — a
  Decision audited as `stable/sufficient` is stored as `stable/sufficient`
  (never `unknown`); the semantic digest uses the same real values.
- **Malformed safety enums fail closed everywhere**: typos like
  `"invlaid"`, `"STABLE"`, `"forbid_numeric "`, `"full_acess"` raise a
  ContractError in the validator, in the runtime policy resolver (a typo'd
  policy can no longer silently become `none` and disable the gate), and
  in StateStore; canonical `unknown`/`none` remain valid states.
- **Outcome scope membership**: a single-platform Change may narrow a
  cross-platform Decision's Outcome only when the Change platform belongs
  to the Decision's scope — otherwise rejected.
- **Explicit cross_platform Outcome keeps scope**: `platform="cross_platform"`
  no longer erases the inherited `platform_scope`; explicit incompatible
  single platforms are rejected.
- **StateStore platform attribution defense-in-depth**: new events with
  contradictory attribution (single platform + scope, or cross_platform
  without a ≥2-platform scope) are rejected; scope order canonicalized
  (sorted unique); legacy events without platform stay readable.

## 3.4.3 — 2026-08-12

### Fixed

- **Run identity per begin()**: `PlatformOperationalRun` is reusable but
  every `begin()` now creates a NEW `StateSession` — fresh random run_id
  and an empty run-local dedupe set. Cross-run dedupe regression: two runs
  with identical payloads produce two events; run-local verdicts/warnings/
  observations never leak into the next run.
- **Semantic event identity includes platform**: Decision digest now
  includes `platform`, canonicalized (sorted unique) `platform_scope` and
  `diagnosis_confidence`; Change digest includes `platform`; Outcome
  digest includes `platform`/`platform_scope`. Identical content on
  different platforms is never deduped accidentally; reversed scope order
  is one identity.
- **diagnosis_confidence fails closed**: malformed values (e.g. `"confirmed
  "`, `"very_high"`) raise ContractError in the validator AND in
  StateStore (defense-in-depth) — never silently normalized to `none`;
  validation and persistence consume the same canonical value.
- **Outcome mixed-reference attribution**: precedence is confirmed
  Change > Decision — an Outcome linked to a single-platform Change
  answers "what happened after that change" (its cross-platform Decision
  scope is dropped, no contradictory attribution); a cross-platform
  Decision alone keeps its scope; conflicting refs are rejected.
- **Execution-claim detection precision**: structured `execution_status`
  stays the primary signal; the natural-language pass is now conservative
  (action verb + operational object patterns). Harmless performance
  language ("CTR changed after the audience expanded") is allowed; true
  claims ("预算已经从 100 调到 80", "We changed the bid to $25") still
  rejected in Decisions.
- **SafetyVerdict semantics**: `accepted`/`is_allowed` now mean
  `outcome == "allowed"` only — constrained without a rewritten candidate
  is never persistable; stale "persist (allowed/constrained only)"
  comments removed.

## 3.4.2 — 2026-08-12

### Fixed

- **Cross-platform Change requires an explicit target platform**: a
  cross-platform run without `target_platform` is rejected
  (`cross_platform_change_requires_target`) — a real Change acts on one
  platform; unscoped Changes are never written. Invalid targets outside
  the run's scope are rejected too.
- **Cross-platform Outcome inherits scope**: an Outcome linked to a
  cross-platform Decision inherits `platform = cross_platform` +
  `platform_scope`; platform-filtered Outcome retrieval works for all
  four event types; conflicting refs or explicit platforms are rejected.
- **Decision ≠ Change invariant under every permission**: execution
  claims ("已暂停/已经暂停/executed/applied/…") in a Decision are ALWAYS
  rejected (`execution_claim_in_decision`), even with `full` permission;
  the correct path is Decision = recommendation, Change = confirmed
  execution. Structured `execution_status` is checked first; natural
  language detection is defense-in-depth.
- **Constrained candidates are never persisted verbatim**: the
  persistence contract is now `allowed → persist`; `rejected → no`;
  `constrained WITHOUT a validated compliant candidate → no`. The runtime
  performs no numeric rewriting, so cap_20pct / staged_required
  candidates return None + `last_verdict` with re-decision guidance.
- **Diagnostic claim safety**: candidates carry structured
  `diagnosis_confidence` (none / tentative / probable / confirmed),
  persisted with the Decision. Invalid measurement rejects
  probable/confirmed measurement-dependent diagnoses;
  insufficient maturity rejects confirmed diagnoses; tentative hypotheses
  stay allowed. Safety now constrains claims as well as actions.
- **Run-local reset**: `PlatformOperationalRun` is reusable-but-reset —
  `begin()` clears current observations, persistence warnings, last
  verdict, platform scope, and the state snapshot, so a second run never
  inherits residue from the first.

## 3.4.1 — 2026-08-12

### Fixed

- **Same-run current observation**: a recorded Observation now immediately
  becomes the run's `current_observations` (per platform) and is visible in
  `OperationalContext` — no full state reload; persistence failure keeps
  reasoning going with the in-memory observation and a warning, never
  pretending persistence.
- **Event platform attribution**: Decision / Change / Outcome now carry
  `platform` (or `cross_platform` + `platform_scope`); platform-filtered
  retrieval matches exact platform and cross-platform scope for all four
  event types, and legacy unscoped events remain readable but are never
  broadcast into a platform filter.
- **Platform-scoped safety**: measurement/maturity are derived per platform
  (current observation first, then platform-filtered history) — a Meta
  request can never inherit TikTok's safety state, even when TikTok's
  events are newer. Multi-platform runs keep
  `measurement_by_platform` / `maturity_by_platform` and expose a
  conservative aggregate (any invalid → invalid) instead of flattening to
  one scalar.
- **Safety enum canonicalization**: the runtime now consumes
  Measurement/Maturity/Policy/Permission enums from the canonical safety
  module; permission tiers are capability-based (read_only /
  recommend_only / budget_bid_creative / full); policy comes from real
  policy context (explicit or workspace policy file), never a hardcoded
  default.
- **Runtime safety enforcement**: every candidate Decision runs through
  the shared validator (measurement / maturity / policy / permission +
  execution-claim check) before persistence; rejected candidates return
  None with `last_verdict` (short reason_code + allowed next actions)
  instead of being persisted or raised as internal exceptions. The safety
  result is persisted with the decision; Decision != Change stays
  enforced.
- **Unknown platform raw passthrough removed**: unregistered platforms are
  rejected; the `generic` adapter is allowlist-only and requires explicit
  opt-in; `google_ads` uses a safe projection; UAC CLI decisions are now
  attributed to google_ads.

## 3.4.0 — 2026-08-12

### Added

- **Platform Operational Runtime** (`PlatformOperationalRun`,
  `operational_runtime.py`): the canonical operational lifecycle for Meta /
  TikTok / Creative / cross-platform — begin → platform scope → state
  access → platform-aware bounded state load → evidence projection →
  Observation persistence → hypotheses + safety envelope → Decision
  persistence → `OperationalResult`. Callers no longer manage
  `StateSession` manually for normal operational runs.
- **Platform-aware state retrieval**: `StateStore.get_recent*` supports a
  `platform` filter; the runtime fetches per-platform bounded budgets (3
  observations / 2 changes / 2 decisions / 1 outcome per platform, scope
  capped at 4) so one platform's recent history can never starve another
  platform out of context.
- **Platform-specific evidence projection**: adapters now preserve
  platform-owned fields — Meta (frequency, purchase_cpa, learning_state,
  cost_cap, placement_mix, funnel rates), TikTok (creative_delivery_state,
  install_to_purchase_rate, cost_per_result), Creative (creative_id_local,
  creative_age_bucket, delivery_change, spend_share, downstream_conversion,
  recent budget/bid changes) — plus a common envelope; funnel fields are
  truly projected; unknown raw fields never persist.
- **Public facade** `appflow_ops.runtime`: re-exports `AppFlowRuntime`,
  `PlatformOperationalRun`, `RunContext`, adapters so platform code stops
  reaching into `uac.*`.
- **Shared action vocabulary**: `retest` added to the shared decision
  classes; adapters declare `actions` + platform `action_subtypes`
  (replace_creative, change_bid, change_budget).
- **Platform safety integration**: `PlatformSafetyContext`
  (measurement/maturity/policy/permission) is supplied to every operational
  run; permission state is persisted with decisions; the four gates are
  tested on non-Google platforms.
- Vague-query eval: +7 synthetic cases (Meta/TikTok/Creative/cross-platform
  incl. measurement-invalid and maturity-pending safety cases), 35 total.

### Changed

- `_COMMON_METRIC_KEYS` split into common envelope + per-platform specific
  keys (no more shared mega-allowlist).
- Platform scope detection (Router may pass `platform_scope` explicitly;
  fallback keyword detection handles CJK boundaries, e.g. "TT还是没量").
- Cross-platform reasoning is now an operational run with its own
  hypothesis families; still strictly same-workspace.
- docs/appflow-core.md documents the four layers (Core / Platform
  Operational Runtime / Platform Adapters / Deterministic Specialization);
  main router documents the operational runtime entry.

### Not Included

- deterministic Meta/TikTok engines (still Agent + shared runtime)
- Ads APIs / background monitoring / GUI / Computer Use
- cross-client learning / global creative benchmark store

## 3.3.4 — 2026-08-12

### Fixed

- **Release Privacy Gate**: the gate ran `release_check.py --full` without
  installing dependencies, so its eval-fixture validation path
  (`appflow_ops.evals.vague_query`) failed with `ModuleNotFoundError:
  PyYAML` on every tag since v3.2.x. The gate now installs PyYAML (minimal,
  pinned range) before the preflight.
- **Windows metadata migration race**: `RunContext.from_workspace` read the
  project context OUTSIDE the metadata lock, so on Windows a concurrent
  locked writer's atomic `os.replace` could collide with another thread's
  open read handle (`PermissionError`). The whole read-and-maybe-bind
  sequence now runs under the workspace-local metadata lock;
  `_bind_workspace_id` no longer takes the lock itself (re-locking the same
  file would deadlock) and keeps the double-check.
- **Cross-platform formatting/type-check regression**: `privacy_doctor`
  `_finding` annotation (`dict[str, str]` vs `list[str]`) fixed; top-level
  scripts mypy is green again. `account_state.py` re-formatted after the
  lock change.
- **Release artifact alignment**: README/QUICKSTART install pins,
  manifest, runtime version strings, and version tests all aligned to
  3.3.4; `docs/releasing.md` no longer carries the stale v1.9.2 candidate
  status.

## 3.3.3 — 2026-08-12

### Release recovery (P0)

- Fixed the CI Foundation-contracts failure that had been red since v3.3.1:
  `privacy_doctor._finding` was annotated `dict[str, str]` but assigns a
  `list[str]` (`value_sha256s`); the annotation is now `dict[str, Any]` and
  the top-level-scripts mypy check passes again.
- Fixed the Windows test-suite failure (Python 3.10 and 3.13): `clear()`
  deleted the state directory including the open `.write.lock` file, which
  raises PermissionError on Windows. `clear()` now removes everything
  except the held lock file inside the lock, then removes the lock file and
  the empty state directory after the lock is released.
- Fixed the Windows migration-race failure: the lock's NUL-byte
  initialization wrote inside a byte range another thread had already
  locked (Access denied). The lock file is now initialized via
  exclusive-create (`O_CREAT|O_EXCL`) before any handle opens, so no
  thread ever writes into a locked byte range.

### Semantic deduplication

- Dedupe now follows: **deduplicate technical duplicates, never collapse
  distinct business observations.**
- `observed_at` participates in Observation identity (same value on two
  days = two observations: "CPA stayed 100 for three days" is a fact);
  `review_condition`/`review_after` participate in Decision identity
  (wait+tomorrow vs wait+7 days are different); `effective_at`
  participates in Change identity. Volatile fields (recorded_at, event_id,
  run_id) remain excluded; dict key order is canonicalized away.

### State access minimization

- New `StateAccess` tri-state (required / not_needed / uncertain). The
  Router / skill layer can pass `state_access` explicitly to
  `AppFlowRuntime.begin_run`; the runtime enforces it.
- The fallback classifier detects non-operational intents first (news,
  translation, brief writing, client-message drafting, terminology) and
  **unknown requests default to NO state access** — never unlock
  production business state on a guess.

### UAC state persistence completeness

- New `state_adapters.py`: `project_analysis_observation` keeps business
  metrics (spend/installs/registrations/payments/CTR/CPI/CPA/budget/…),
  measurement/maturity, and engine funnel rates/drop; `project_quick_decision`
  keeps maturity (from derived_signals), policy version identifiers (never
  contents), and review_after (from review_condition.after_days). Pure
  projections — no engine logic is recomputed.
- CLI `decide` now persists measurement/maturity, policy_constraints,
  evidence_refs (linked to the most recent observation), and review_after.

### Integrity and payload hygiene

- Current-state freshness now uses exact equality on BOTH
  `derived_through_sequence` and `event_count` (999 vs max 100 is
  corrupted, not fresh).
- Payload guard adds `MAX_PAYLOAD_BYTES`, `MAX_COLLECTION_ITEMS`, and
  `MAX_MAPPING_KEYS`; embedded email detection (boundary search, not
  whole-string); credential/token string detection (Authorization=Bearer,
  access_token=, ?token=, api_key=) while plain URLs and normal ad metrics
  stay accepted.

### Documentation and phase closure

- Wording corrected: "canonical runtime lifecycle + supported entry points
  use it" instead of universal runtime enforcement; no claim of host-level
  bypass-proof enforcement.
- AGENTS.md adds the phase-closure principle: Continuous Account State is
  a stable foundation; do not expand State infrastructure without a
  concrete requirement or correctness defect. README adds the next-phase
  roadmap (Meta / TikTok / creative / cross-platform adoption), not
  implemented.

## 3.3.2 — 2026-08-12

### Runtime-enforced State Lifecycle

- New `AppFlowRuntime` (`scripts/appflow_ops/uac/run_lifecycle.py`) is the
  canonical runtime entry: `begin_run(request_text)` classifies the request
  and conditionally loads state; `state_context()` returns one bounded
  StateContext (current state + last observation/change/decision/outcome +
  pending review + bounded recent history); `record_*` + `finish_run` close
  the run. The lifecycle is executed by the runtime, not merely promised in
  skill prompts.
- Lightweight request classification (no LLM classifier):
  `direct_informational` ("CTR 是什么？") never reads or writes state;
  `follow_up` / `operational_diagnosis` / `decision_request` auto-load
  bounded state. Deterministic tool paths (`begin_run(None)`) skip
  classification and loading.
- Deterministic CLI paths now reuse the same lifecycle: `analyze
  --workspace` records one Observation (metrics + measurement/maturity
  state, `observed_at` = case end date, source `deterministic_engine`);
  `decide --workspace` records one Decision (origin `deterministic`,
  decision class mapped from the verdict + bid action, review condition
  rendered from the engine mapping). `normalize` and `replay` never write
  state. State write failures print a stderr warning and never alter the
  advertising result.

### Integrity and hygiene

- Legacy `workspace_id` migration is now concurrency-safe: a workspace-local
  `.workspace.lock` (metadata lock) with double-check guarantees 50
  concurrent first-opens yield exactly one id. Lock ordering is fixed
  (metadata lock before state write lock, never held together).
- Current-state freshness validates both `derived_through_sequence` AND
  `event_count`; the event log must be one continuous sequence 1..max —
  gaps and duplicates fail loudly (rebuild/append raise; `state verify` /
  `state doctor` report them without fixing).
- Runtime-owned deduplication: an explicit `source_digest` is still honored;
  when absent the runtime derives a stable digest from the canonical
  structured payload (type, platform, facts, source/evidence state) — never
  from timestamps, event ids, or run ids.
- New state payload guard (fail closed, `StatePayloadError`): credential
  keys, raw conversations, email addresses, and strings over 2000 characters
  are rejected, including in nested payloads; key matching is normalized and
  exact (`email_ctr` is not a false positive). Documented as defense-in-depth,
  not DLP.
- Provenance cleanup: decision envelope `source_type` maps from `origin` —
  `deterministic` → `deterministic_engine`, `agent_constrained` → `agent`
  (new source type), `operator` → `manual`; `evidence_status` stays
  separate.
- `state doctor` added as an alias of `state verify`.

## 3.3.1 — 2026-08-12

### State integrity (P0)

- **Concurrency**: every append / rebuild / clear now takes the
  workspace-local `state/.write.lock` (POSIX flock / Windows msvcrt) for
  the critical section (allocate sequence → persist event → derive current
  state). 100 concurrent writers produce 100 unique events with zero
  overwrites; A/B concurrent writes never block or mix.
- **Workspace identity is proven**: workspaces carry a random opaque
  `workspace_id` (project-context metadata); the state schema stores it and
  opening a store verifies it. A copied foreign state tree is rejected;
  legacy v3.3.0 fingerprint-only stores migrate when the fingerprint
  matches and are rejected otherwise; moving a workspace directory keeps
  its identity.
- **Reference integrity**: refs now validate existence AND type inside the
  current workspace (decision refs → observation/change; outcome refs →
  decision/change/observation per field). Same-named events in another
  workspace can never satisfy a reference.
- **Time semantics**: `observed_at` lives only in the envelope (payload
  double-write removed); `recorded_at` vs `observed_at` are canonical;
  `effective_at` only on changes. Derived state follows event-log order,
  so out-of-order imports cannot corrupt the latest business knowledge.
- **Full-log derivation**: current-state rebuild scans the FULL event log
  (streaming, bounded memory) and records `derived_through_sequence`;
  stale/missing derived files are detected and rebuilt on read (crash
  consistency). Pending review is derived from the full log — an old
  pending decision survives hundreds of later events.
- **Event integrity**: filename must match `event_id`/type inside the
  file; `state verify` (state doctor) reports identity/schema/sequence/
  reference/freshness problems without fixing them.

### Provenance

- Decisions carry `origin` (deterministic / agent_constrained / operator),
  default `agent_constrained`, with `evidence_status: inferred` — no more
  hardcoded deterministic_engine/confirmed claims. Observations keep
  confirmed/reported/inferred + source_type. Every event records a local
  random `run_id`.

### Runtime integration (product loop)

- New `StateSession` runtime layer (single integration point):
  `load_context_summary()` before reasoning, `record_observation` /
  `record_decision` / `record_confirmed_change` / `record_outcome` after
  each stage; run-local dedupe by source_digest. Ambiguous follow-ups
  ("现在呢?", "Google 怎么又不行了?") auto-load current workspace state;
  terminology questions skip state entirely.
- A recommendation alone never records a Change (only confirmed execution
  does); outcomes are never written at decision time; full assistant
  answers are never stored (structured summaries only).
- Main router gains the canonical State Lifecycle section; skills must not
  implement their own lifecycle.

### Docs

- README (zh/en): Continuous Account State moved out of the not-implemented
  list; explicitly "session-persistent, not background monitoring".
- docs/account-state.md updated to v3.3.1 semantics (identity, lock, time,
  provenance, freshness, runtime API); AGENTS.md adds the runtime-API-only
  state rule.

### Tests

- New: concurrency (100 writers, A/B isolation), identity (copy rejection,
  move keeps identity, legacy migration match/mismatch), ref type
  validation, time semantics, >100-event derivation, old pending review,
  freshness, event integrity, verify, provenance, run_id, and the 8
  runtime lifecycle tests plus the "现在呢?" / "又不行了?" scenarios.

## 3.3.0 — 2026-08-11

### Continuous Account State (isolation-first)

- **Isolation architecture before state**: one workspace = one state store,
  physically under `workspaces/<client>/<project>/state/`; no global
  business memory, no global index, no cross-client database, no vector
  store. All state access is workspace-bound through a frozen `RunContext`;
  no API accepts an arbitrary filesystem path.
- Five object types, append-only JSON events with a derived, rebuildable
  `current-state.json`: Observation (facts, not explanations, common
  envelope + platform payload), Change (confirmed operations only;
  unconfirmed user statements stay `reported` observations), Decision
  (concise rationale, evidence refs, policy/measurement/maturity state,
  confidence, review condition; no hidden chain-of-thought), Outcome
  (linked to decision/change/observation), Current State (derived summary
  with pending review).
- Pending review: a decision with a review condition stays pending until an
  outcome links to it — a marker for the next conversation, never a
  background job (no daemon/cron/polling).
- Bounded retrieval (`get_recent(limit=…)`, capped at 100); current-state
  derivation consumes only recent events while counting the full log.
- Workspace containment enforced everywhere via the existing
  `Workspace.require_contained_path`: traversal, absolute external paths,
  symlink escapes (including symlinks planted inside the events directory),
  and cross-workspace source references are contract errors. Corrupted
  current state rebuilds from events; corrupted events fail loudly.
- CLI (internal/debug): `state init|status|show|rebuild|clear` under
  `uac_experiment.py`; clear is destructive, workspace-scoped, requires
  `--yes`.
- Reasoning Contract: workspace state is an additional Verify-stage
  evidence source (bounded, current workspace only; never borrow another
  workspace's history).
- Docs: new `docs/account-state.md` (stores / does not store / isolation /
  cross-workspace / privacy); README (zh/en) capability line; AGENTS.md
  non-negotiable principles (no global business memory; every persistent
  business state has an explicit workspace owner).
- New tests: storage, lifecycle, pending review, reasoning integration,
  privacy, and the cross-workspace isolation suite (A–H: read/write/
  traversal/symlink/delete/rebuild/retrieval/identifier leakage) plus
  adversarial path variants.

## 3.2.1 — 2026-08-11

### Privacy: scoped allowlist replaces kind-wide waivers

- `privacy_doctor.py` findings now carry stable `value_sha256s` digests
  (email/identity values, bytecode paths) so an exception can accept one
  exact known finding instead of a whole finding kind.
- New `privacy-allowlist.json`: human-readable, reviewable, deterministic
  scoped exceptions. Every exception must pin `value_sha256s` and/or
  `references`; a kind-only exception is rejected at load time (it would
  silently become a kind-wide waiver).
- The GitHub release gate no longer uses `--waive`; it runs
  `release_check.py --full --allowlist privacy-allowlist.json`, the same
  preflight the maintainer runs locally before tagging.
- `--waive` stays on the CLI but is marked legacy and prints a warning; it
  must not be used for releases.
- Accepted exceptions are auditable: the report lists `waiver_usage`
  (exception ids used) and each accepted finding carries `waiver_id` +
  `waiver_reason`; status flips to PASS only when every finding was accepted
  by a scoped exception.
- Regression cases (Part 16) cover: known maintainer email passes, a new
  email of the same kind fails, known historical bytecode fingerprint
  passes, new bytecode fails, known maintainer identity passes, new
  unrelated identity fails.

### Eval privacy boundary unified (synthetic-only repository)

- Repository benchmark is synthetic only: the default eval runner now
  refuses `sanitized` cases alongside `production` (`ProductionDataError`),
  so a locally sanitized replay cannot silently enter CI.
- `docs/eval-privacy.md` and README (zh/en) now describe sanitized replay as
  a local transformation boundary, not a committed fixture type.
- `identity_markers()` extended (UUID, long numeric ids, labeled
  token-like strings) as defense-in-depth; the sanitizer whitelist remains
  the primary boundary.

### Reasoning safety contract completed

- `policy_state` (none / staged_required / cap_20pct / forbid_numeric) now
  participates in expected behavior; the layer consumes simplified policy
  state and never re-implements the UAC policy engine.
- `permission_state` (recommend_only / read_only) forbids
  `claim_execution`; a recommend-only operator's answer must never be
  phrased as executed.
- Measurement and maturity decision classes are fully split: each gate
  forbids its own rules (`recommend_numeric_change_when_measurement_invalid`
  vs `recommend_numeric_change_without_maturity`), so an eval failure names
  exactly which gate was broken. Fixture `meas_cpa_spike_003` and the other
  measurement-invalid fixtures now declare measurement-specific rules.
- New tests: measurement/maturity/policy/permission gate behavior,
  gate-distinctness, fixture compatibility, and state validation.

### Release preflight

- `release_check.py --full --allowlist privacy-allowlist.json` runs the
  full reachable-history privacy scan before tagging (worktree scan remains
  the default; `--full` adds history).

## 3.2.0 — 2026-08-11

### Release health (P0)

- Fixed CI foundation-contracts failure: ruff was unpinned (`>=0.12,<1.0`)
  and 0.16 widened its default rule set. ruff is now pinned to 0.16.2 and
  the lint contract is explicit in `pyproject.toml` (rules disabled with
  documented reasons); scripts gained executable bits, and a private
  test re-export lost by an auto-fix was restored.
- Fixed installer smoke failure: `check_install_layout.py` still expected
  the pre-rebrand `ads/` layout; required files and reference/agent paths
  now check `appflow/`. Verified with a real local install.
- Fixed Release Privacy Gate: annotated tags v3.0.0/v3.1.0 carry the
  owner's personal email as tagger identity; the owner accepted this on
  2026-08-11, so `non-placeholder-email` joins the waiver list (kept
  visible as waived INFO).
- New `scripts/release_check.py` preflight: version consistency, reasoning
  contract presence, eval fixture schema/privacy, worktree privacy scan.

### Privacy-safe evaluation (P1)

- Eval fixtures now declare `data_class` (`synthetic`/`sanitized`/
  `production`) and `source_type` provenance; all 24 vague-query cases are
  `synthetic`/`authored`.
- The default evaluation runner refuses `production` data with
  `ProductionDataError`; no silent degradation.
- New one-way replay sanitizer (`appflow_ops.evals.sanitize`): drops
  identity/free text/URLs/paths, normalizes money to indexes, buckets
  time, never creates reversible mappings.
- New deterministic safety derivation (`appflow_ops.evals.safety`):
  measurement=invalid forbids aggressive numeric optimization and
  confident deep-event diagnosis; maturity=insufficient forbids premature
  bid changes.
- New `docs/eval-privacy.md` threat model and README Evaluation Privacy
  principles (synthetic-first; production stays local).
- CI: eval schema/privacy checks and release preflight added to
  foundation contracts.

## 3.1.0 — 2026-08-11

### Added

- **AppFlow Reasoning Contract** (`skills/appflow/references/reasoning-contract.md`):
  single canonical definition of Diverge → Verify → Eliminate → Rank →
  Converge, with trigger conditions, evidence priority, elimination states,
  ranking dimensions, convergence output shape, ask-only-when-material, and
  the no-chain-of-thought rule.
- **Vague Query Eval Suite** (`evals/vague-query-evals.json`): 24 fixture
  cases across Google/UAC, Meta, TikTok, cross-platform, and measurement,
  with a thin `Evaluator` interface for future model benchmarks and
  deterministic schema/consistency checks.
- Reasoning Contract inheritance in 12 diagnosis skills (one-line reference;
  no prompt duplication).
- Version alignment guard: README/QUICKSTART pinned install version must
  equal VERSION; all version sources are checked in CI.

### Changed

- Main router behavior: `Reasoning Loop` section replaced by a reference to
  the canonical contract; ambiguous diagnosis now inherits the contract
  across skills instead of duplicating prompt text.
- Release/version alignment: README install target moved from v3.0.0 to
  v3.1.0 so documented behavior matches the released artifact.

## 3.0.0 — 2026-08-11 (breaking)

### Rebrand and repositioning

- Renamed the product from Kimi Ads to **AppFlow Ops**; repository, plugin
  manifest (`appflow.plugin.json`), installers, Python package
  (`scripts/appflow_ops/`), and docs follow.
- Repositioned to overseas **app-promotion agency operations** (乙方视角).
  Removed non-app or non-core skills: `ads-amazon`, `ads-linkedin`,
  `ads-microsoft`, `ads-landing`, `ads-dna`, `ads-photoshoot`, their audit
  references, and non-app plan templates.
- Main router renamed `skills/ads/` -> `skills/appflow/` (mirror `ads/` ->
  `appflow/`); routing shorthand is now `/appflow ...`.

### Agency workflows

- New question discipline (`client-questions-policy.md`): ask only
  decision-changing questions, batched; infer and mark the rest.
- New rapid-response workflow for urgent client demands
  (`ads-ops/references/rapid-response.md`): bounded quick levers, rollback
  values, dual output (client explanation + internal action ticket), audit
  trail; numeric safety caps are never waived.
- Client/account/business isolation: `init-workspace --client <label>`
  creates `workspaces/<client>/<project>/`; project context records
  `client_label` and `business_line`; workspaces reject cross-workspace
  references and keep client deliverables under `reports/client/`.

### Funnel diagnosis dashboard

- New `funnel-dashboard` CLI subcommand (and `scripts/funnel_dashboard.py`):
  renders a self-contained HTML funnel (spend -> installs -> registrations ->
  payments), highlights the bottleneck layer, separates observed /
  calculated / inferred, and reports missing layers as data gaps.

### Install changes

- Default install target is now host-agnostic `~/.appflow/skills`
  (overridable via `APPFLOW_HOME`); removed vendor-specific desktop targets.
  Repo URL plumbing env var renamed to `APPFLOW_OPS_REPO_URL`.
- Browser-bridge live inspection is now optional; exports/pasted tables/
  screenshots are the default data path.
- Optimizer profile file renamed to `APPFLOW_OPTIMIZER.md` (legacy
  `KIMI_ADS_OPTIMIZER.md` still read for backward compatibility).

## 2.2.0 — 2026-07-20

### Desktop install target

- Added a desktop-app target to `install.sh` / `install.ps1` (and the
  uninstallers): installs the bundle into the desktop app's skill
  directory (`~/Library/Application Support/kimi-desktop/daimon-share/daimon/skills`
  on macOS, `%APPDATA%\kimi-desktop\daimon-share\daimon\skills` on Windows,
  overridable via `KIMI_WORK_HOME` or `--skill-dir`). Previously only
  the agent CLI (`~/.appflow/skills`) was covered, so the desktop app never saw
  the skills.

### Release plumbing

- `privacy_doctor.py` gained `--waive KIND[,KIND...]`: waived finding kinds
  stay in the report as INFO with `waived=true` but no longer fail the audit.
  The release gate waives the pre-migration identity findings (personal
  email, local hostname) and historical `.pyc` files accepted by the repo
  owner; real secret/private-data kinds still fail.
- Fixed the release gate's annotated-tag check to re-fetch the real tag
  object (actions/checkout re-points the local tag ref at the commit).
- Fixed `scripts/ci/*.py` console output on Windows (forced UTF-8; the
  check markers crashed the cp1252 console).
- Bumped dev pytest to >=9.0.3 (PYSEC-2026-1845) and made the top-level
  scripts mypy override tolerate third-party stub drift.

## 2.1.0 — 2026-07-20

### Playwright removal and WebBridge-only browser work

- Removed Playwright entirely: deleted `scripts/capture_screenshot.py` and
  `scripts/analyze_landing.py`. All browser work now goes through the assistant
  WebBridge in the user's real, fully visible logged-in browser; the bundle
  ships no headless browser tooling.
- Reworded the Live Dashboard Tool Gate in `skills/appflow/SKILL.md` and the
  `webbridge-live-audit.md` / `orchestrator.md` references (plus the `ads/`
  mirror) to state the WebBridge-only rule without referencing the deleted
  scripts.
- Added a 10 MB hard cap on `scripts/fetch_page.py` response bodies so a
  hostile or misconfigured server cannot exhaust memory.

### Skill prompts and packaging

- Added Chinese trigger phrases across all sub-skill descriptions so
  natural-language routing works in Chinese as well as English.
- Deduplicated the template-adapter guidance shared by `ads-ops` and
  `ads-report`; `ads-report` now owns it.
- Added plugin-layout fallback chains for agent persona briefs and scripts so
  skills resolve correctly from both manual and plugin installs.

### CI and release hardening

- Extracted inline `python -c` assertions from `ci.yml` into
  `scripts/ci/check_install_layout.py`, `check_uac_decide_output.py`,
  `check_uac_policies.py`, and `check_numeric_cap.py`; the installer smoke now
  verifies the installed layout through `check_install_layout.py`.
- Added `shellcheck` (installer scripts) and `pip-audit` (runtime and
  development dependencies) jobs, and SHA-pinned all GitHub Actions.

### UAC core modularization

- Split the UAC modules under `scripts/kimi_ads/uac/` into focused submodules
  with facade re-exports, so existing imports keep working.
- Extended mypy coverage from `scripts/kimi_ads/uac` to the top-level scripts
  via pyproject overrides, and wired the new check into CI.

## 2.0.0 — 2026-07-20

### Migration to the agent CLI

- Migrated the skill bundle from OpenAI Codex CLI to the agent CLI; the product
  is now AppFlow Ops and the new repository home is
  `github.com/taotao135791-bit/appflow-ops`.
- Changed the default install target to `kimi`: skills now install to
  `~/.appflow/skills` (honoring `$KIMI_CODE_HOME`), and the agent persona
  briefs ship inside the main skill at `~/.appflow/skills/appflow/agents`,
  dispatched to the assistant's built-in `coder` subagent.
- Replaced Computer Use with WebBridge (Chrome/Edge extension plus local
  daemon driving the user's real logged-in browser) for logged-in ad-dashboard
  inspection; public landing-page fetches still use `scripts/fetch_page.py`
  and `scripts/capture_screenshot.py`.
- Renamed the Python package `codex_ads` to `kimi_ads`, the repository URL
  environment variable to `KIMI_ADS_REPO_URL`, and the optimizer profile files
  to `APPFLOW_OPTIMIZER.md` / `.appflow-ops-optimizer.md`.
- Replaced `.codex-plugin/plugin.json` with the root `kimi.plugin.json`
  (`"skills": "./skills/"`), installable via
  `/plugins install https://github.com/taotao135791-bit/appflow-ops`.
- Renamed the project instruction file `CODEX.md` to `AGENTS.md`, which the assistant
  reads as the project instruction file.

### Compatibility and release status

- Routing shorthand (`/appflow audit`, `/appflow uac`, ...) is unchanged and can also
  be reached through the `/skill:appflow` invocation; all skill, ledger, replay,
  and workspace contracts from 1.9.x remain readable.
- The `v2.0.0` tag and GitHub Release were published together with this
  entry; 2.1.0 is now the current stable pin.

## 1.9.2 — 2026-07-14

### Numeric Safety Guardrails and Release Stabilization

- Added versioned normal-change caps for tCPA, tROAS, and daily budget in both
  directions. The bundled `uac-numeric-policy-v1` uses a 20% heuristic default,
  while the final value must still satisfy account evidence, business bounds,
  permissions, and the read-only confirmation contract.
- Added staged optimization output for candidates beyond the active cap. Only
  stage one is immediately proposed; every later stage requires fresh mature
  evidence and is never executed automatically.
- Added strict default, project, and private Workspace policy loading for
  calibratable numeric and signal heuristics, with version chaining, schema and
  runtime validation, effective-policy provenance, and a zero-change fallback
  when a bundled numeric default is unavailable.
- Separated `NORMAL_OPTIMIZATION`, `STAGED_OPTIMIZATION`, confirmed
  `OPERATIONAL_CORRECTION`, and non-attributable `EMERGENCY_INTERVENTION` so an
  ordinary scale action cannot use an incident-response exception.
- Added the human-reviewed `evaluation.yaml.numeric_evaluation` Replay contract
  and direction, median magnitude error, policy-cap, aggressive/conservative,
  rollback, staged-plan, and correct-no-action aggregates. Replay never changes
  a policy automatically.
- Removed one exact historical synthetic refresh-token fixture false positive
  with a digest-only allowlist, without weakening detection for real tokens.
  The current tree passes its redacted scan, while legacy identity metadata and
  tracked bytecode still block the `v1.9.2` tag and GitHub Release. No history
  rewrite, tag, or Release is claimed by this entry.

### Deterministic Numeric Quick Decisions

- Added deterministic derivation for maturity, multi-day budget delivery,
  event-volume stability, target constraints, value readiness, creative
  quality, candidate events, and campaign-split feasibility.
- Added bounded tCPA, tROAS, and daily-budget candidates based on supplied
  account evidence and explicit business limits, with conservative,
  recommended, and aggressive views where the evidence supports them.
- Added fail-closed numeric safety gates for immature or unreliable data,
  recent changes, one-day volatility, missing business limits, restricted
  permissions, and ordinary multi-variable changes.
- Kept AC2.0/AC2.5/AC3.0 as campaign-level labels rather than bid values, and
  kept every numeric decision read-only with evidence, review, and rollback
  fields visible to the operator.
- Added an anonymous numeric Quick Decision example, extended schema and Doctor
  coverage, and cross-platform installed-package smoke tests for the numeric
  modules and deterministic output.
- Added private numeric Replay calibration for direction, magnitude, unsafe
  recommendations, correct no-action, rollback, acceptance, and confounding;
  excluded unexecuted, immature, or confounded cases from invalid denominators.
- Made compact cards expose per-Campaign split budgets, missing candidate
  targets, hard business-boundary corrections, localized data gaps, and
  Campaign-level rollback without enabling any account or ledger write.

### Compatibility and release status

- Existing `decide`, `analyze`, Workspace, Report, Experiment, Replay, and
  Ledger 1.0/1.1 paths remain compatible; legacy caller-supplied numeric hints
  cannot bypass the new evidence and permission gates.
- This entry prepares `v1.9.2`; it does not claim that a remote tag or GitHub
  Release exists. The known full-history privacy block still prohibits tags and
  releases even when the current tree and ordinary CI pass.

## 1.9.1 — 2026-07-13

### Quick Ops and Campaign Level Decision Mode

- Added a read-only `decide` entry that returns one compact campaign operation
  card instead of a full report or automatic experiment.
- Added configurable AC2.0/AC2.5/AC3.0 terminology resolution with explicit
  protection against treating internal level labels as tCPA/tROAS numbers.
- Added deterministic keep, create, parallel, move, wait, and rollback gates
  for AC2.0 → AC2.5 and AC2.5 → AC3.0 decisions.
- Added strict payment/value, currency, deduplication, refund/subscription,
  amount-reconciliation, delay, volume, stability, and split-capacity checks
  before AC3.0 admission.
- Added same-level campaign, creative maturity/value, bid/budget separation,
  permission transformation, and operational-intervention classification.
- Added a private Workspace output, standalone Quick Decision schema, synthetic
  input example, progressive-disclosure Skill reference, and 42-scenario
  no-model behavior fixture.

### Compatibility and release status

- Existing `analyze`, Doctor, normalization, Report, Experiment, Ledger 1.0/1.1,
  Workspace, and Replay contracts remain compatible; Quick Decision never
  appends an experiment or edits Google Ads.
- This entry prepares `v1.9.1`; it does not claim that a remote tag or GitHub
  Release exists. The known full-history privacy block must be cleared before
  any tag or release is created.

## 1.9.0 — 2026-07-13

### Productization, Release and Real-World Validation

- Added a private, cross-platform UAC workspace with natural-language Agent
  workflow guidance while preserving every legacy path and CLI command.
- Made normalization, Doctor, analysis, reports, experiment drafts, and replays
  work together without requiring operators to author schemas by hand.
- Upgraded historical replay to a preferred six-stage evidence trail while
  retaining the legacy five-file contract and separating confounded outcomes.
- Expanded redacted privacy checks for advertising identifiers, API/OAuth/MMP
  credentials, local workspaces, environment files, and unsafe public replays.
- Defined the real UAC package coverage, typing, schema, compatibility,
  workspace, installer, reporting, and release-history gates in CI.
- Documented platform maturity honestly: UAC is deterministic; other platform
  skills remain structured Agent workflows or advisory support.

### Compatibility and release status

- Ledger schemas `1.0` and `1.1`, the historical UAC entry point, legacy replay
  cases, and direct file-based commands remain supported.
- This entry prepares `v1.9.0`; it does not claim that a remote tag or GitHub
  Release already exists. Publishing still requires the release checklist and
  a clean full-history privacy gate.

## 1.8.3 — 2026-07-13

### Stabilization and Real-World Validation Foundation

- Split the deterministic UAC engine into testable internal modules while
  preserving the existing entry point, CLI commands, output fields, and report.
- Added a read-only project Doctor, explicit ledger schema migration,
  lightweight input normalization, and anonymized historical replay metrics.
- Established a canonical Ads router with a deterministic mirror sync check and
  introduced lightweight knowledge-freshness metadata and diagnostics.
- Extended CI with typing, schema migration, Doctor, normalization, replay,
  router-sync, installed-package, and cross-platform compatibility checks.
- Added fixed-version release preparation, rollback guidance, and clearer
  documentation of deterministic guarantees, Agent inference, and limitations.

### Privacy

- Added repository safeguards for private replay data and future generated
  caches. Public examples remain anonymous and contain no live account data.

## 1.8.2 — 2026-07-13

### CI Reliability

- Added the `requests` runtime package to the development test environment so
  redirect and SSRF regression tests run in clean GitHub Actions workers.

## 1.8.1 — 2026-07-13

### UAC Safety Hardening

- Enforced ledger status, approval, execution, review-snapshot, maturity,
  guardrail, confounder, result, and learning consistency.
- Added deep-goal measurement completeness checks for event definitions,
  payment/trial/refund distinctions, attribution windows, and OS differences.
- Normalized operator-friendly goal names while preserving their raw values.
- Prevented unexecuted proposals from publishing learnings and blocked CLI
  outputs from overwriting source inputs or experiment ledgers.
- Added automatic single-ledger discovery, duplicate-ID prevention, and an
  auditable `cancel-proposal` transition for declined unexecuted proposals.
- Added fail-closed UAC scope, date-window, segmentation, signal, and evidence
  validation plus safe investigation-only degradation for incomplete policies.
- Required terminal metrics, evidence quality, mutually consistent result and
  decision outcomes, and an explicit next action before publishing learnings.
- Made the full ledger scaffold safely valid outside the active experiment
  array and aligned the offline JSON Schema with runtime validation.

## 1.8.0 — 2026-07-13

### UAC Experiment Loop

- Added the dedicated `ads-google-app` route for Google App campaigns/UAC.
- Added deterministic measurement, learning-eligibility, optimization-
  feasibility, permission, and single-variable experiment decisions.
- Added a local `ADS-EXPERIMENTS` ledger contract with minimal, full, and
  worked examples plus JSON Schema validation.
- Added structured UAC analysis and Markdown report generation from one source
  of truth.
- Added experiment readback for maturity, low volume, guardrails, concurrent
  changes, and win/loss/inconclusive outcomes.
- Hardened permission blocking, conversion-volume maturity, offline schema
  validation, atomic ledger writes, malformed-input handling, and completed
  experiment learning readback.
- Added behavior fixtures for common limited-permission UAC scenarios.
- Added cross-platform CI, lint, schema, installer, fixture-replay, and report
  smoke checks.

### Compatibility

- Existing routes, report tools, read-only defaults, and other ad-platform
  skills remain available.
- The new Python helper is optional. YAML input uses the lightweight PyYAML
  dependency already used by the development harness.
- Generated experiments remain unapproved proposals until a human confirms an
  exact platform edit.
