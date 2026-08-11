# AppFlow Ops — 海外 App 代投运维工作流

AppFlow Ops 是给**乙方投手**用的海外 App 投放运维系统。它的核心交互原则：

> **Users describe the problem. AppFlow decides how to investigate it.**

用户说业务问题，AppFlow 自己决定该分析什么。默认只读，任何真实账户写入都要逐项人工确认。

[English README](README.en.md) · [快速启动](QUICKSTART.zh-CN.md)

## 核心产品原则：发散 → 验证 → 排除 → 排序 → 收敛

AppFlow Ops 处理模糊自然语言问题的推理范式：

```text
Diverge → Verify → Eliminate → Rank → Converge
```

用户表达的是 **Problem**，不是 **Procedure**。用户不需要说"请比较 CTR、CPC、CVR、CPA 并查看过去 7 天数据"，只需要说：

- "Google 最近怎么跑不动了？"
- "这个素材还能跑吗？"
- "CPA 为什么突然高了？"
- "现在该调预算还是调出价？"
- "为什么有点击但是没安装？"
- "我现在应该先处理什么？"

AppFlow 的责任是自己回答："这个问题应该分析什么。"

### 推理循环

```text
Natural-language problem
        ↓
Intent / problem interpretation
        ↓
Diverge      生成可验证的候选假设
        ↓
Verify       用现有证据主动验证
        ↓
Eliminate    排除被证伪与不适用的解释
        ↓
Rank         按证据强度与决策影响排序
        ↓
Converge     收敛为最小有用决策
        ↓
Action / watch / ask for missing evidence
```

### 五个阶段

**1. Diverge — 发散**

收到模糊问题后不立刻给结论，先展开业务上合理且值得验证的假设。例如"Google 最近怎么跑不动了？"可能涉及：spend/delivery constraint、bid constraint、budget constraint、learning/maturity、creative exhaustion、audience/geo limitation、measurement instability、conversion-event quality、funnel degradation、recent operator changes、product-side conversion changes、external market effects。

**发散不是无限脑暴。** 只生成同时满足以下条件的假设：与当前平台有关；与当前 workspace 有关；与当前问题有关；能用现有证据验证，或验证后会显著改变决策。

**2. Verify — 验证**

对假设主动寻找证据，而不是凭"听起来合理"下结论：

> **Reasoning should be evidence-seeking, not imagination-driven.**

证据来源包括：当前观察、历史快照、campaign/creative 指标、漏斗数据、先前改动与建议、实验台账、replay 历史、workspace 文件、导出表/截图/粘贴数据、已声明策略、measurement/maturity/permission 状态。

**3. Eliminate — 排除**

把每个假设明确归类：`supported` / `contradicted` / `insufficient evidence` / `not applicable`。不要把全部可能性留在最终回答里。

- CTR 稳定 → "素材完全失去吸引力"不应继续作为第一原因；
- click→install 明显恶化 → 向安装环节、商店页、流量质量方向收缩；
- measurement 不稳定 → 降低对深层事件结论的置信度。

目标不是"列出十个可能原因"，而是**尽可能减少错误解释的数量**。

**4. Rank — 排序**

剩余假设按重要性排序，参考：evidence strength、causal plausibility、timing correlation、magnitude、reversibility、operational impact、measurement confidence、decision risk。输出尽量收敛为：

```text
Most likely
Possible but secondary
Unresolved
Ruled out
```

而不是一串没有优先级的建议。

**5. Converge — 收敛**

最终回答从"分析"收敛到"行动"，输出最小有用结论：

```text
keep / increase / decrease / pause / reopen / replace
wait / observe / investigate / request missing evidence
```

证据足够就直接给决策。证据不足时不装作知道答案，而是指出：当前最可能是什么；哪些已经排除；缺少哪一个最关键的信息；获取这个信息是否值得。**不要因为缺少非关键数据就机械追问用户。**

### 示例："Google 最近怎么跑不动了？"

```text
Question
↓
"跑不动" = delivery issue or efficiency issue?

Diverge
├─ bid constraint
├─ budget constraint
├─ creative fatigue
├─ funnel degradation
├─ measurement issue
├─ recent operator change
└─ external/product-side change

Verify
├─ spend trend
├─ bid history
├─ budget history
├─ CTR
├─ click→install
├─ install→pay
├─ measurement health
└─ recent changes

Eliminate
├─ CTR stable → severe top-funnel fatigue less likely
├─ measurement stable → attribution issue less likely
└─ volume dropped immediately after bid reduction

Rank
1. bid constraint
2. downstream CVR weakness
3. creative fatigue — low confidence

Converge
→ Do not open a new campaign yet.
→ Restore bid within policy bounds.
→ Observe one decision window.
```

这是**产品行为示例**，不是对当前代码已完整自动完成所有步骤的声明。当前实现中，假设生成与证据整理由 Agent 完成，数值边界与门禁由确定性引擎执行。

### 这不是 Chain-of-Thought 展示

该模型描述系统的**工作阶段与可验证决策过程**，不要求向用户输出模型内部完整思维过程。内部可以发散，外部必须收敛：

> **Broad internally, concise externally.**

用户最终看到的应该是：

```text
结论
证据
排除项
风险 / 不确定性
下一步
```

而不是几十段 AI 自言自语。

完整的行为合同（触发条件、证据优先级、排除状态、排序维度、收敛输出、提问纪律）见 [`skills/appflow/references/reasoning-contract.md`](skills/appflow/references/reasoning-contract.md)；模糊问题的离线评测用例见 [`evals/vague-query-evals.json`](evals/vague-query-evals.json)。

### Design Principles

```text
Problem over procedure     用户陈述业务问题，而不是分析配方。
Evidence over intuition    再合理的假设也要经过验证才能成为结论。
Elimination over enumeration   有用的 agent 减少可能性，而不是无限罗列。
Ranking over flat recommendations   不是每个假设都值得同等关注。
Action over reporting      分析收敛为最小的可用操作决策。
Ask only when it matters   只有缺失信息会改变结论时才打扰用户。
Broad internally, concise externally   系统内广泛探索，对外给出聚焦答案。
```

## 它怎么工作（今天已实现）

- **账户审计**：Google / Meta / TikTok / Apple 的 App 投放结构、预算、出价、转化、素材体检，输出健康分和整改清单
- **UAC 实验闭环**：Google App campaigns 的确定性决策引擎——测量可靠性、学习资格、单变量实验准入（草案 draft 先展示、确认后才写台账）与复盘
- **漏斗诊断看板**：把花费→安装→注册→支付生成一张单文件 HTML 看板，自动标红瓶颈层
- **乙方日常**：每日巡检、异常排查、素材需求单、甲方模板适配、客户回复、操作变更记录
- **甲方/内部双份报告**：给甲方的解释稿和给内部的操作票分开写
- **提问纪律**：只问会改变下一步决策的问题，一次问完（见 `references/client-questions-policy.md`）
- **急单响应**：客户要求快速降指标时输出有边界的杠杆清单，每项带回滚值，双份留痕（见 `references/rapid-response.md`）
- **默认数据路径**：导出表 / 粘贴数据 / 截图；浏览器桥仅作为可选的只读通道

## 架构：Agent 探索 + 确定性约束

```text
The model explores.
Evidence narrows.
Policy constrains.
The runtime decides.
```

| Agent / LLM 负责 | 确定性组件负责 |
| --- | --- |
| interpreting ambiguous language | normalization |
| hypothesis generation | measurement state |
| evidence discovery | maturity |
| workflow routing | numeric boundaries |
|  | policy enforcement |
|  | permissions |
|  | recommendation constraints |
|  | replay evaluation |

现有 Google UAC deterministic engine 是这套理念的**基础**：它把验证、排除、收敛中适合确定性处理的部分（测量状态、成熟度、数值上限、权限、门禁、replay）固化成了可复现的代码与测试。推理循环跑在它之上，而不是替代它。

## Skills 与平台

主路由 `skills/appflow/` 负责意图理解与分发；子技能覆盖 Google App / UAC（`ads-google-app`）、Google、Meta、TikTok、Apple、归因、服务端追踪、素材、预算、受限杠杆诊断（`ads-levers`）、乙方日常（`ads-ops`）、报告、计划、数学与测试设计等。完整路由表见 `skills/appflow/SKILL.md`。

## 使用

### 三步开始

```bash
curl -fsSL https://raw.githubusercontent.com/taotao135791-bit/appflow-ops/v3.1.0/install.sh | bash -s -- --ref=v3.1.0
```

然后在你的 AI 编程助手里直接说自然语言：

```text
只读看一下这个 Google App 账户，先检查数据可靠性和转化延迟，
再判断现在该做实验、等待，还是不修改账户。
```

### 客户隔离与确定性命令

一个客户一个私有 workspace：`workspaces/<客户>/<项目>/`。数据、台账、报告互不串用；甲方交付物默认匿名化，单独放 `reports/client/`。

```bash
python3 scripts/uac_experiment.py init-workspace my-project --client acme
python3 scripts/uac_experiment.py normalize --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py doctor --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py analyze --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py funnel-dashboard --workspace "workspaces/acme/my-project"
```

## 隔离与安全

- 客户/账户/业务三隔离：一个 workspace 只属于一个客户，跨 workspace 引用被拒绝
- 数值安全上限：单次变化默认 ≤20%，超限走分阶段计划；急单也不能突破
- 隐私：真实数据只进私有 workspace，报告默认匿名化，甲方版交付物单独存放

## 边界（不会做的事）

- 只有 Google UAC 拥有确定性实验引擎（Schema 校验、测量/学习状态、实验准入、台账与 replay）；其他平台是结构化 Agent 工作流，没有与 UAC 等价的确定性实验引擎
- 不保证增长、降 CPA 或提 ROAS；不把一次复盘当因果证明
- 不自动登录、不自动改账户；真实写入必须逐项人工确认
- 数据不足、口径不可信、转化延迟未成熟时，正确结论可以是"不修改，先等待或补数据"

## 产品方向（尚未实现，勿当现状）

以下能力是产品方向，当前**没有**完整实现：

- universal hypothesis engine：跨平台的通用假设生成与假设生命周期管理
- automatic evidence retrieval across every platform：全平台的自动证据收集
- complete Meta / TikTok deterministic decision runtime：Meta/TikTok 的确定性决策运行时（当前只有 Google UAC 具备）
- continuous account state：持续账户状态，而非按需快照
- fully autonomous vague-query investigation：完全自主的模糊问题调查（当前依赖 Agent 推理 + 确定性门禁的组合）

这个项目知道自己在构建什么：**推理范式已经定义，确定性基础已经就位，其余部分按此方向逐步实现。**

## 安装与目录

安装默认落到 `~/.appflow/skills`，支持 `--target=codex|cursor|windsurf|gemini|goose` 和 `--skill-dir` 覆盖。Windows 用 `install.ps1`。卸载：`bash uninstall.sh`。

```text
skills/appflow/      主路由（推理循环、提问纪律、隔离、路由表）
skills/ads-*/        平台与工作流子技能（Google/Meta/TikTok/Apple + 乙方运维）
agents/              审计与创意 persona briefs
scripts/             本地确定性工具（UAC 引擎、漏斗看板、PDF 报告）
docs/                数值安全策略、Quick Ops、发布流程等进阶文档
```

## 进阶

- UAC 实验闭环与 Quick Ops 数值决策：[docs/quick-ops-numeric-decisions.md](docs/quick-ops-numeric-decisions.md)
- 数值安全策略（幅度上限、分阶段计划、纠错/紧急合同）：[docs/numeric-safety-policy.md](docs/numeric-safety-policy.md)
- 发布与版本管理：[docs/releasing.md](docs/releasing.md)
- 完整话术样例：[QUICKSTART.zh-CN.md](QUICKSTART.zh-CN.md)

## 许可证

MIT。详见 [LICENSE](LICENSE)。
