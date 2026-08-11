# AppFlow Ops 快速启动

海外 App 代投运维工作流。**不用背命令，也不用先学 YAML**：把导出表、粘贴表格或截图交给你的 AI 助手，再复制一句自然语言。

## 安装

```bash
curl -fsSL https://raw.githubusercontent.com/taotao135791-bit/appflow-ops/v3.2.0/install.sh | bash -s -- --ref=v3.2.0
```

Windows：

```powershell
irm https://raw.githubusercontent.com/taotao135791-bit/appflow-ops/v3.2.0/install.ps1 -OutFile install.ps1
.\install.ps1 -Ref v3.2.0
```

## 第一次使用

```text
我要用 AppFlow Ops 做海外 App 投放运维。默认只读看数，不修改广告后台；
需要日报、周报或甲方汇报时，先问我模板在哪里。
```

## 边界（先记住）

- 不保证增长、降 CPA 或提 ROAS；不替代产品、支付墙、SDK/埋点、MMP 或后端回传
- 不自动登录或改账户；真实写入需要对那一项操作明确确认
- 数据不足时，正确建议可以是不修改账户
- 单账户经验默认不能全局推广

## 乙方三件套

### 1. 提问纪律（该问的问，不该问的不问）

只会一次性追问会改变决策的问题：KPI 口径、权限边界、业务上限、急迫程度、可用数据。其余能推断的就推断并标注。

### 2. 客户隔离

每个客户一个私有 workspace，数据、台账、报告互不串用：

```text
帮我为客户 acme 初始化 UAC 项目，项目名 ios-main。
```

（对应命令：`python3 scripts/uac_experiment.py init-workspace ios-main --client acme`）

### 3. 客户急了（rapid response）

```text
客户今天就要把 CPA 降下来。请先确认 KPI 口径和权限，再给我有边界的快速杠杆，
每项带回滚值和复查条件，并同时写给甲方的解释稿和内部操作票。
```

## 日常话术（复制即用）

账户体检：

```text
只读看一下这个广告账户，判断预算消耗、转化质量、目标设置和下一步动作。不要修改任何设置。
```

每日巡检：

```text
只读看一下昨天的数据，找今天必须处理的 3 件事。
重点看消耗、支付、CPA、素材拒审、追踪异常和国家/设备异常。
```

代投窄权限诊断：

```text
我们是代投，KPI 和产品都不能改。现在安装多支付少，请只读判断：
投放侧还能动哪些杠杆，哪些要甲方配合，以及怎么跟甲方解释。
```

UAC 日常决策（保持/调整/并行/切换/等待）：

```text
我现在跑 AC2.5，直接告诉我继续、调整、并行、切换还是等待。
```

漏斗看板：

```text
给这个客户生成漏斗诊断看板，标出瓶颈层，缺哪层数据就告诉我缺哪层。
```

导出日报：

```text
按甲方日报模板整理今天的数据。模板我已打开或会给你路径，只读识别，不要写回。
```

甲方沟通稿：

```text
把刚才的结论改成给甲方看的版本：讲原因、风险、下一步和预期影响，少用平台术语。
```

异常排查：

```text
支付突然掉了。先不要建议改预算，按数据延迟、追踪、审核、消耗、国家/素材结构逐步排查。
```

## UAC 项目五句话闭环

```text
1. 帮我为这个 UAC 账户初始化项目（说明客户名）。
2. 分析本周 UAC 数据，告诉我该不该动。（附数据）
3. 根据这次分析创建一个实验草案（draft，先展示，不写台账）。
4. 我已在今天 <时间和时区> 执行了 <改动>，没有其他改动，请记录。
5. 复盘当前实验。（附同口径最新数据）
```

真实资料会放进默认忽略的私有 workspace；草案确认后才写本地台账；写台账不等于授权修改 Google Ads。

## 优化师定制

在项目目录放 `APPFLOW_OPTIMIZER.md`，写你的判断习惯、加/降预算规则、甲方汇报口径：

```text
帮我创建 APPFLOW_OPTIMIZER.md。我的风格：先看转化目标，再看预算消耗，
再看国家和素材；给甲方汇报直接但不激进。
```

可以开启投手风格学习模式（style_learning_mode），默认用 `suggest_only`：只提建议，
确认后才写入；只有你明确要求时才改成 `auto_append_anonymized`。安全边界：

- 手动填写的规则永远优先，学习到的规则不能覆盖我手动填写的规则
- 不保存客户名、账号 ID、campaign 名、具体消耗、CPA/ROAS、邮箱或带 token 的链接

## 高级命令（源码 checkout）

```bash
python3 scripts/uac_experiment.py init-workspace my-project --client acme
python3 scripts/uac_experiment.py normalize --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py doctor --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py analyze --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py decide --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py funnel-dashboard --workspace "workspaces/acme/my-project"
```

台账迁移（1.0 → 1.1）先预览再写新文件，见 [README](README.md) 与 `docs/`。
