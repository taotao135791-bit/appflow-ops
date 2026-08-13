# Ads Decision Intelligence (v3.5.0)

AppFlow 从 Operational Runtime 正式进入 Ads Decision Intelligence：
面对真实广告问题，提出候选原因、验证、排除、排序、收敛到最小可用动作。

## Platform vs Domain

- **Platform Scope** = 数据属于哪个媒体：`google_ads` / `meta` / `tiktok`
- **Operational Domain** = 用户在问什么类型的问题：`creative` / `funnel` /
  `measurement` / `bid_budget` / `delivery` / `auction` / `audience` /
  `cross_platform` / `general`

Routing 示例：

| 请求 | platform_scope | domain |
| --- | --- | --- |
| Meta 这个素材是不是衰减了？ | `[meta]` | creative |
| TikTok 点击还行，为什么安装掉了？ | `[tiktok]` | funnel |
| 这个广告现在预算要不要加？ | 上下文/显式 | bid_budget |
| Google 和 Meta 都开始掉付费，是产品问题吗？ | `[google_ads, meta]` | funnel（cross_platform=true） |
| 这个还能不能跑？ | 上下文 | general |

domain 是 routing hint，**不缩小评估集合**——auction vs fatigue 等竞争假设
必须同时评估。

## Hypothesis Specs

结构化假设（`HypothesisSpec`），不是名字列表：

```text
id / label / domain / applicable_platforms
supporting_signals      → 出现时支持（+2）
contradicting_signals   → 出现时削弱（-2）
required_evidence       → 缺失时置信度受限
exclusion_conditions    → 出现时直接排除
possible_actions        → 最小优先的候选动作
```

第一批：Meta 14 个家族（creative_fatigue / auction_pressure /
audience_saturation / delivery_mix_shift / learning_or_relearning /
post_click_friction / conversion_funnel_degradation /
measurement_instability / bid_constraint / budget_constraint /
recent_budget_bid_interference / ...）、TikTok 8 个漏斗假设
（click_to_install_friction / pay_funnel_degradation / ...）、
Cross-platform 4 个（shared_product_funnel_issue /
shared_measurement_issue / platform_specific_independent_issues /
market_wide_event）。

## Evidence Semantics

- 证据必须可引用 Observation / Decision / Change / Outcome / current
  metrics（不新增 event 类型）
- 缺数据 = `missing`，**不是**另一个假设的证据
- `measurement invalid` → 只有 measurement 假设可被支持（其余 capped）
- `maturity insufficient` → 任何假设都不可被支持
- 无伪概率：排序可重复（status > score > id）

## Elimination / Ranking

```text
excluded      ← exclusion 条件命中（如刚调预算 → 不能判 fatigue）
supported     ← score ≥ 6（强支持）或 score ≥ 4 且无 required 缺失
unverified    ← 证据不足
weakened      ← 有反驳证据
insufficient_evidence ← required 缺失过半
```

## Convergence

满足以下才收敛到具体动作：

```text
top hypothesis 有实质支持（supported + score 达标）
主要替代被削弱/排除
runner-up 不是强竞争（score 差距）
safety 允许动作（measurement/maturity/policy/permission）
```

否则诚实回答：**先别动**，并说出最缺的证据；measurement invalid →
先查数据；maturity insufficient → 等待完整窗口。

Smallest useful action：例如素材衰减 → 先替换最弱 1-2 组旧素材、预算
不动、约定复查条件；而不是重建 campaign。

## User-facing Answer Contract

> Broad internally. Concise externally.

默认输出：结论（1 句）→ 最强证据（2-4 条）→ 实质性排除（需要时）→
下一步动作 → 复查条件。不是诊断报告；不展示隐藏 CoT。

## Runtime-Native Integration (v3.5.1)

Decision Intelligence is no longer a library you may call — it is part of
the normal AppFlow run:

```text
run.begin(...)
run.record_observation(...)
result = run.evaluate_decision_intelligence()   # native pipeline
run.record_decision_from_intelligence()         # optional: persist via Safety
```

### Library API vs Operational Runtime API

| | Library API | Operational Runtime API |
| --- | --- | --- |
| Entry | build_hypothesis_set / signals_from_metrics / evaluate / rank / converge (manual assembly) | `run.evaluate_decision_intelligence()` (assembled by the runtime) |
| Evidence | caller-provided signals or raw metrics | current observations only (same platform-scope boundary) |
| Safety context | explicit arguments (defaults are unit-test convenience) | canonical context from the same resolvers used by record_decision — NEVER optimistic defaults |
| Cross-platform | explicit bool optional; platform_scope is source of truth | automatic from multi-platform scope |
| Output | Convergence | DecisionIntelligenceResult (light, product-shaped) |

### Raw Evidence → Signals → Hypotheses → Evaluation → Ranking → Convergence

1. **Raw evidence**: current observation facts per platform (trend strings
   like `ctr_trend: "down"`, or numeric relative movement like
   `ctr_change_pct: -0.25` — material ≥ 10%, stable band ≤ 5%, ambiguous
   band emits nothing).
2. **Signals**: `signals_from_platforms()` per-platform extraction +
   cross-level aggregations (`cross_pay_rate_drop` when ≥ 2 platforms show
   the same drop) + canonical safety signals (invalid measurement /
   insufficient maturity / stable measurement).
3. **Hypotheses**: platform-appropriate set; multi-platform scopes
   AUTOMATICALLY enable cross-platform families and never fall back to
   ALL_HYPOTHESES (`applicable_platforms` really filters).
4. **Evaluation**: +2 support / -2 contradiction / 0 missing; stable IS
   evidence (CPM stable weakens auction); missing stays missing.
5. **Ranking**: deterministic (status priority, score, id).
6. **Convergence**: a materially supported runner-up (status=supported,
   score ≥ threshold) is a MAJOR ALTERNATIVE — score gap alone never
   eliminates it; the runtime answers `investigate` + the next
   discriminating evidence instead of a confident action.

### Safety Contract

- Operational DI never defaults to `stable`/`sufficient`; the canonical
  SafetyContext (measurement / maturity / policy / permission) flows from
  the runtime into signals, evaluation, and (when persisting) into
  `record_decision` — one context, never two.
- measurement invalid → hypotheses may still be generated but confident
  diagnosis is blocked (`investigate_measurement` first).
- DI only RECOMMENDS; execution claims stay in Change (Decision ≠ Change).

### User-facing Output (v3.5.1)

`summarize_decision_intelligence(result)` produces the default short
answer: conclusion → strongest evidence → material exclusion/alternative →
next action → review condition; insufficient evidence answers honestly
"先别动" plus the most needed data. Full ranking tables are debug/eval
only.

## Historical Evidence (v3.5.2)

Evidence is CONTINUOUS, not a current snapshot:

```text
Current fact
+ Comparable previous fact (same platform, same metric family)
= derived trend
```

- Trend precedence: explicit canonical current trend (`ctr_trend` /
  `ctr_change_pct`) > derived current-vs-history trend > missing.
- A single current value WITHOUT comparable history produces NO trend
  (0.7% CTR alone never invents `ctr_trend_down`).
- The same ±10%/±5% thresholds drive explicit and derived trends (no
  second hand-rolled threshold set).
- "现在呢？" really uses the previous State: the runtime reads the
  bounded per-platform history loaded at begin(), picks the most recent
  comparable observation, and derives trends itself — callers never
  pre-compute change_pct.

### Decision / Change / Outcome Context

- **Recent confirmed Change = confounder evidence**: a budget/bid change
  in State becomes `recent_budget_change` / `recent_bid_change` signals —
  "CTR↓ right after budget+30%" is not immediately creative fatigue.
- **Previous Decision = context, not fact**: `decision_context`
  (decision_class / review_condition / review_after) informs wait/recheck
  behavior but NEVER becomes supporting evidence for today's diagnosis.
- **Outcome = evidence, not causal proof**: `outcome_context` records
  what happened (improved / worsened / neutral / inconclusive) and may
  shift retest/continue/investigate carefully — never "fatigue proven".

## Cross-platform Evidence (v3.5.2)

A shared hypothesis requires shared evidence from MULTIPLE distinct media
platforms. A decline on one platform is not evidence of a shared product
problem.

- `signals_by_platform`: per-platform signals preserved (Meta pay down +
  Google pay stable is auditable, not a flat `pay_down=true`).
- `shared_signals`: ONLY signals true on >= 2 distinct platforms
  (`cross_pay_rate_drop` / `cross_cvr_drop` / `cross_registration_drop` /
  `cross_install_drop` / `cross_platform_comparison_available`).
- `cross_platform_comparison_available` requires the SAME direction on
  both platforms (both down, or both stable) — a divergent pair is the
  single-platform decline case, not shared evidence.
- `shared_product_funnel_issue` is supported ONLY by cross-level signals;
  a plain `pay_rate_trend_down` on one platform never promotes it.
- Measurement conflict (one platform invalid, another stable) stays
  material: no confident shared product conclusion.

## Evidence Attribution (v3.5.3)

> Evidence is only valid for the platform, entity scope, and time
> comparison that produced it.

- **Provenance-aware evaluation**: `evaluate_hypotheses()` consumes an
  `EvidenceResult`, not a flat dict. Platform-bound hypotheses
  (applicable_platforms lists concrete media) are evaluated PER PLATFORM
  against that platform's own `signals_by_platform` — Meta signals can
  never be spliced into a Google evaluation (or vice versa); the result
  carries `platform` attribution (`auction_pressure@meta`).
- **Shared hypotheses require shared evidence**: `shared_product_funnel_issue`
  / `market_wide_event` / `shared_measurement_issue` consume
  `shared_signals` only — a single-platform `pay_rate_trend_down` or
  `cpm_trend_up` never promotes them. `market_wide_event` needs
  `cross_cpm_up` (≥ 2 platforms rising); `shared_measurement_issue` needs
  `cross_measurement_invalid` (≥ 2 platforms invalid) or a real conflict.
- **Measurement conflict**: exactly `invalid + stable` is a conflict;
  `invalid + unknown` is incomplete coverage (conservative via aggregate
  invalid), never a conflict.

> Shared hypotheses require shared evidence. Platform-specific signals
> from different media must never be stitched together to simulate one
> platform or a shared condition.

## Historical Comparability (v3.5.3)

> Same platform does not imply comparable observations. Derived trends
> require compatible entity and aggregation scope.

- Comparable identity = (platform, entity_level, entity_key,
  breakdown_scope, aggregate_scope). Three explicit states (v3.5.4):
  explicit account aggregate (entity_level=account + aggregate_scope),
  explicit entity (entity_level + entity_key), or identity UNKNOWN —
  missing identity is NEVER evidence of account-level aggregation and
  produces NO derived trend. A mismatch (Campaign A vs Campaign B,
  account vs campaign, gender vs all) fails conservative.
- entity_key is a workspace-local OPAQUE identifier: raw external
  campaign/ad IDs are never persisted (privacy contract); legacy
  entity_id records stay readable for comparability.
- Explicit canonical trends still override derived trends.

## Change Temporal Semantics (v3.5.3)

> A stored Change is not automatically recent. A Change is a current
> confounder only when its timing is relevant to the comparison window
> or review condition.

- Intervening confounder: `baseline_observed_at < change_effective_at
  <= current_observed_at`. Changes before the baseline were already part
  of the baseline state; a two-month-old budget change is never
  `recent_budget_change` (age metadata is retained for audit).
- Change types are separated: `recent_budget_change` / `recent_bid_change`
  / `recent_creative_change` / `recent_audience_change` /
  `recent_campaign_change` / `recent_campaign_restart` — an audience
  change never masquerades as a creative change.
- Latest Decision/Outcome context is chosen by canonical timestamp
  (effective_at / observed_at, deterministic event_id tie-break), with
  per-platform latest retained alongside.

## Evaluation Scope (v3.5.4)

> Applicable platform != evaluation scope.

- `evaluation_scope="platform"` (default; INCLUDING applicable_platforms
  "*"): evaluated separately on EVERY applicable platform — Meta signals
  can never be spliced into a Google evaluation, and a wildcard
  hypothesis is never a flat union of all platforms.
- `evaluation_scope="shared"`: `shared_product_funnel_issue` /
  `market_wide_event` / `shared_measurement_issue` consume
  `shared_signals` + aggregate Safety only.
- `evaluation_scope="run"`: run-level facts (e.g. `platform_divergence` —
  one platform declining while another is stable) only; never assembled
  from a flat union.

> A platform-bound hypothesis must use that platform's measurement and
> maturity state. Aggregate safety is reserved for shared/run-level
> conclusions.

Meta measurement invalid never caps Google's diagnosis; aggregate invalid
never creates measurement instability on a stable platform.

> A confirmed Change is a confounder only for the platform it affected
> and only when it falls inside the relevant comparison/review window.

Meta budget+30% is `recent_budget_change@meta` only; Google stays clean.
Temporal relevance uses the affected platform's own baseline/current.

> Missing entity identity does not imply account-level comparability.

Comparable identity never requires real media IDs — a workspace-local
opaque `entity_key` (stable within workspace, non-reversible, not
globally meaningful) is enough to tell "same entity" from "different
entity".

## Convergence Safety Provenance (v3.5.5)

> Platform-bound conclusions use platform-bound safety. Shared and
> run-level conclusions use aggregate safety.

The evaluator has consumed provenance-aware Safety since v3.5.4; the last
correctness gap was CONVERGENCE: it could still re-consume the whole run's
aggregate Safety and let one platform's problem veto an independent
diagnosis for another platform.

- `converge()` resolves Safety from the SELECTED evaluation's scope via
  `resolve_evaluation_safety(evaluation, safety_context)` — never by
  guessing scope from hypothesis names or string matching. The ranked
  evaluation already carries `platform` and `evaluation_scope`; use them
  directly.
  - `evaluation_scope="platform"` + a media platform → that platform's own
    measurement/maturity; a platform with NO safety evidence resolves to
    `unknown` — never borrowed from another platform or from the
    aggregate (no pretending "stable").
  - `evaluation_scope="shared"` → aggregate/shared Safety (conservative).
  - `evaluation_scope="run"` → aggregate/run Safety (never a randomly
    picked platform's state).
- A safety block changes convergence/action, NEVER the ranked diagnosis
  identity: `top_hypothesis`, `top_platform`, `top_evaluation_scope`
  always derive from ONE `selected_evaluation` (hard invariant). The
  result carries `safety_block` (`measurement_invalid` /
  `maturity_insufficient`) separately from the diagnosis.
- `platform_warnings` (e.g. `{"meta": ("measurement_invalid",)}`) keep
  non-selected platforms' safety problems visible WITHOUT making them a
  global veto.

> A safety problem on one media platform is not automatically a veto on an
> independent diagnosis for another media platform.

> A safety problem on one platform can still block a shared cross-platform
> conclusion.

### Diagnosis vs Safety Block

```text
Top diagnosis        = shared_product_funnel_issue   (ranked, unchanged)
safety_block         = measurement_invalid           (which gate blocked)
recommended_action   = investigate_measurement       (what to do now)
```

`investigate_measurement` does NOT mean `top_hypothesis` becomes
`measurement_instability` — unless measurement instability itself really
ranked first. Persisted Decision attribution follows the selected
evaluation: `auction_pressure@google_ads` persists with
`platform=google_ads`; a blocked shared diagnosis still persists with
`platform=cross_platform` + its scope — a safety action never rewrites the
diagnostic attribution.
