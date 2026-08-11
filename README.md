# AppFlow Ops — 海外 App 代投运维工作流

AppFlow Ops 是给**乙方投手**用的海外 App 投放运维技能包：账户审计、UAC 实验闭环、漏斗诊断看板、甲方日报/周报、急单响应。默认只读，任何真实账户写入都要逐项人工确认。

[English README](README.en.md) · [快速启动](QUICKSTART.zh-CN.md)

## 它能干什么

- **账户审计**：Google / Meta / TikTok / Apple 的 App 投放结构、预算、出价、转化、素材体检，输出健康分和整改清单
- **UAC 实验闭环**：Google App campaigns 的确定性决策引擎——测量可靠性、学习资格、单变量实验准入（草案 draft 先展示、确认后才写台账）与复盘
- **漏斗诊断看板**：把花费→安装→注册→支付生成一张单文件 HTML 看板，自动标红瓶颈层
- **乙方日常**：每日巡检、异常排查、素材需求单、甲方模板适配、客户回复、操作变更记录
- **甲方/内部双份报告**：给甲方的解释稿和给内部的操作票分开写

## 三步开始

```bash
curl -fsSL https://raw.githubusercontent.com/taotao135791-bit/appflow-ops/v3.0.0/install.sh | bash -s -- --ref=v3.0.0
```

然后在你的 AI 编程助手里直接说自然语言，不用背命令：

```text
只读看一下这个 Google App 账户，先检查数据可靠性和转化延迟，
再判断现在该做实验、等待，还是不修改账户。
```

## 乙方工作流（核心）

### 提问纪律：该问的问，不该问的不问

只问会改变下一步决策的问题，并且一次问完：甲方 KPI 与验收口径、权限边界、业务 CPA/ROAS 上限、急迫程度、可用数据。客户成本结构、产品路线图、其他供应商报价一律不问——能推断的就推断并标注。见 `references/client-questions-policy.md`。

### 客户急了：快速响应但不越界

客户要求"今天就把 CPA 降下来"时走 rapid-response 流程：先确认 KPI 口径和权限，再输出有边界的快速杠杆（停异常、排差量、策略幅度内收紧目标、预算内部再分配），每一项带回滚值和复查条件；同时固定产出两份东西——给甲方的解释稿和内部操作票，全部写入该客户 workspace 留痕。证据不足时，诚实的答案是"保持 + 解释"，不硬凑数字。

### 客户隔离 / 账户隔离 / 业务隔离

一个客户一个私有 workspace：`workspaces/<客户>/<项目>/`。数据、台账、报告互不串用；甲方交付物默认匿名化，单独放 `reports/client/`。

```bash
python3 scripts/uac_experiment.py init-workspace my-project --client acme
python3 scripts/uac_experiment.py normalize --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py doctor --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py analyze --workspace "workspaces/acme/my-project"
```

### 漏斗看板（必要时现生成）

```bash
python3 scripts/uac_experiment.py funnel-dashboard --workspace workspaces/acme/my-project
```

输出自包含 HTML（无外部依赖），浏览器直接打开；缺哪层数据就明确提示缺哪层，不画假图。

## 边界（不会做的事）

- 只有 Google UAC 拥有确定性实验引擎（Schema 校验、测量/学习状态、实验准入、台账与 replay）；其他平台是结构化 Agent 工作流，没有与 UAC 等价的确定性实验引擎
- 不保证增长、降 CPA 或提 ROAS；不把一次复盘当因果证明
- 不自动登录、不自动改账户；真实写入必须逐项人工确认
- 数据不足、口径不可信、转化延迟未成熟时，正确结论可以是"不修改，先等待或补数据"
- 急单也不能突破数值安全上限（默认单次变化 ≤20%），超限走分阶段计划

## 安装与目录

安装默认落到 `~/.appflow/skills`，支持 `--target=codex|cursor|windsurf|gemini|goose` 和 `--skill-dir` 覆盖。Windows 用 `install.ps1`。卸载：`bash uninstall.sh`。

```text
skills/appflow/      主路由（提问纪律、隔离、路由表）
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
