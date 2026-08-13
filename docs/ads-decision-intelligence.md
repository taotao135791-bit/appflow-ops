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
