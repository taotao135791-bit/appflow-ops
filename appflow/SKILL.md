---
name: appflow
description: >-
  Route overseas app-promotion agency work: /appflow decide, UAC Quick Decision,
  AC2.0/2.5/3.0, 广告账户审计, 只读看后台, 日报/周报, 甲方模板, 每日巡检, 客户回复,
  素材需求, 漏斗诊断看板, 客户急单响应, Google/Meta/TikTok App 投放, KPI受限诊断.
---

# AppFlow Ops Router

AppFlow Ops is a router for overseas app-promotion agency (乙方) work. Keep
this file lean: route the task, load only the needed sub-skill, and use
references on demand.

## Always Do First

1. Read optimizer profile files in the current working directory if present:
   `APPFLOW_OPTIMIZER.md`, `optimizer-profile.md` (legacy
   `KIMI_ADS_OPTIMIZER.md` is still read for backward compatibility).
2. Stay read-only in ad platforms unless the user confirms an exact edit.
3. Keep real account names, IDs, campaign names, emails, payment details, and
   live metrics out of reusable skill files, examples, tests, and templates.
4. Follow the question discipline in
   `references/client-questions-policy.md`: ask only what changes the next
   decision, batch the questions, and never ask what can be inferred.
5. Resolve the current client workspace before any data work; never mix two
   clients' data, ledgers, or deliverables (see Client & Account Isolation).
6. For global protocols, quality gates, and style learning details, load
   `references/orchestrator.md`.
7. Investigate vague questions with the reasoning loop below; users state
   problems, not analysis procedures.

## Reasoning Contract

Ambiguous operational diagnosis follows the **AppFlow Reasoning Contract** —
`references/reasoning-contract.md` is the single canonical definition:

```text
Diverge → Verify → Eliminate → Rank → Converge
```

- Triggers on symptoms, vague business problems, decision requests,
  unexplained performance changes, and prioritization questions; direct
  lookups and fully specified procedures skip the loop.
- Diverge only relevant, plausible, decision-material, evidence-addressable
  hypotheses. No unbounded brainstorming.
- Verify with observed facts and deterministic state before inferred
  explanations; never override deterministic safety gates.
- Eliminate contradicted explanations explicitly; rank survivors; converge
  on the smallest useful operational decision.
- Ask for missing data only when it can change the decision.

Report broad internally, concise externally: conclusion, evidence, ruled-out
items, risks, and next step. Never dump the internal chain of thought to the
user.

## Data Access (Exports First, Browser Bridge Optional)

Default data path: exported tables (CSV/XLSX), pasted tables, local files, or
user-provided screenshots. This always works and needs no extra tooling.

Optional upgrade: if the user is already logged into an ad dashboard and has
installed a browser bridge (for example Kimi WebBridge,
https://www.kimi.com/zh-cn/features/webbridge), use it for read-only live UI
inspection; load `references/webbridge-live-audit.md` first. Never block a
task because the bridge is missing — fall back to exports without complaint.

Hard safety rules for live dashboards:

- MUST NOT use any headless or scripted browser automation, screenshot
  scripts, page HTML extraction, or network scraping against logged-in
  dashboards.
- MUST NOT take screenshots of private dashboards unless the user explicitly
  asks for a current-work deliverable that requires screenshots.
- Raw HTTP fetching of public pages with `scripts/fetch_page.py` is fine.

## Client & Account Isolation

Every client account lives in its own private workspace:
`workspaces/<client>/<project>/`. One workspace = one client = one business
line.

- Never read, reference, or copy another client's workspace, ledger, input,
  or report while working on the current client.
- Client-facing deliverables go to the workspace `reports/client/` area and
  default to anonymized labels; internal diagnosis stays in `reports/`.
- Project memory docs (`ADS-PROJECT-CONTEXT.md`, `ADS-OPS-LOG.md`,
  `ADS-REPORT-FORMAT.md`) are per client; do not cross-reference them.

## Path Resolution

This router may run from a manual install or from a plugin/source tree.

- Manual install: router at `~/.appflow/skills/appflow/SKILL.md`, sub-skills
  at `~/.appflow/skills/ads-*/SKILL.md`.
- Plugin/source layout: router at `skills/appflow/SKILL.md`, sub-skills as
  `${APPFLOW_SKILL_DIR}` sibling directories under `skills/`.
- When the route table says load `ads-google`, read that sub-skill's
  `SKILL.md` from the first existing path:
  `${APPFLOW_SKILL_DIR}/../ads-google/SKILL.md`,
  `~/.appflow/skills/ads-google/SKILL.md`,
  `~/.agents/skills/ads-google/SKILL.md`, then `../skills/ads-google/SKILL.md`.
- For UAC/App campaigns, resolve `ads-google-app` from the equivalent sibling
  paths before loading the generic Google skill.

## Natural Language Routing

Users do not need slash commands. Treat natural-language requests such as
"只读看一下这个广告账户", "帮我出日报", "按甲方模板做素材周报",
"安装很多支付很少但 KPI 不能改", "帮我做每日巡检", "整理素材需求单",
"适配这个甲方日报模板", "客户急了今天就要把 CPA 降下来",
"review this Google Ads account", or "prepare a client update" as valid
AppFlow skill invocations.

Route `/appflow decide`, UAC daily-operation questions, and AC2.0/2.5/3.0
choices to `ads-google-app` Quick Decision and its
`references/quick-ops.md`. Route UAC diagnosis, explicit experiments,
reports, and lifecycle recording to the same sub-skill's
`references/agent-workflow.md`. Do not ask ordinary operators to translate
these intents into YAML.

## Route Table

| User intent | Load this sub-skill |
| --- | --- |
| full audit, account health, PPC audit | `ads-audit` |
| /appflow decide, AC2.0/2.5/3.0, UAC quick action | `ads-google-app` |
| UAC, Google App campaigns, 应用安装/应用内行为广告, App tCPA/tROAS | `ads-google-app` |
| funnel diagnosis, 漏斗诊断, generate dashboard, 生成看板 | `ads-google-app` + `references/funnel-dashboard.md` |
| client urgent, 客户急了, 今天就要降 CPA, rapid response | `ads-ops` + `references/rapid-response.md` |
| Google Ads, Search, PMax, AI Max, broad match | `ads-google` |
| Meta, Facebook, Instagram, Threads, Advantage+ (app objective) | `ads-meta` |
| YouTube, Demand Gen, Shorts (app install creative) | `ads-youtube` |
| TikTok, Spark Ads, Smart+, app promotion | `ads-tiktok` |
| Apple Ads / ASA / iOS app ads | `ads-apple` |
| attribution, GA4, MMP, AdAttributionKit | `ads-attribution` |
| server-side tracking, sGTM, CAPI, dedup | `ads-server-side-tracking` |
| creative audit, fatigue, copy/design review | `ads-creative` |
| budget allocation, bidding, scale/kill | `ads-budget` |
| KPI/product fixed, install-heavy/pay-light | `ads-levers` |
| patrol, anomaly, client reply, changelog | `ads-ops` |
| daily report, weekly creative report, template | `ads-report` |
| strategic media plan (app promotion) | `ads-plan` |
| competitor ads / ad library research | `ads-competitor` |
| CPA, ROAS, LTV:CAC, forecast math | `ads-math` |
| A/B test design and sample size | `ads-test` |
| campaign brief / copy concepts | `ads-create` |
| AI image generation | `ads-generate` |

When a request spans multiple rows, load the narrowest primary sub-skill
first, then load supporting sub-skills only when needed.

For UAC analysis, resolve the initialized private workspace and read its
`experiments/ADS-EXPERIMENTS.yaml` before proposing another change. Fall back
to a project-root ledger only for a legacy project and recommend migration
after the current task; do not move live data automatically.

## New Operator Intake

For broad first-time requests like "我刚接了一个项目", "帮我看看这个账户",
"不知道从哪里下手", or "first time reviewing this account", apply the
question discipline: ask only the must-ask items from
`references/client-questions-policy.md` (client KPI and acceptance
definition, permission boundary, business CPA/ROAS ceiling, urgency and
deadline, available data) in one concise message, then route:

- Constraint/KPI/product boundary problems -> `ads-levers`
- Daily operations or client communication -> `ads-ops`
- Platform diagnosis -> the relevant platform sub-skill
- Reporting/template work -> `ads-report`

## Project Memory

For repetitive client work, use `ads-ops` to create or update three local
working documents inside the current client's project directory:

1. `ADS-PROJECT-CONTEXT.md` for long-term background, KPI, client
   requirements, current status, and daily-report expectations.
2. `ADS-OPS-LOG.md` for daily actions, reasons, observed results, and review.
3. `ADS-REPORT-FORMAT.md` for fixed client daily/weekly report formats.

Use the first existing template directory:
`~/.appflow/skills/ads-ops/assets/`, `../ads-ops/assets/`, or
`../skills/ads-ops/assets/`. Ask before storing real client identifiers;
anonymize by default. Each client keeps its own set; never merge or
cross-reference between clients.

## Style Learning

Optimizer profiles may include:

```yaml
style_learning_mode: suggest_only
# off | suggest_only | auto_append_anonymized
```

Manual rules win over learned rules. In `suggest_only`, propose generalized
learned style rules and ask before writing. In `auto_append_anonymized`,
append only anonymized, generalized behavior rules to a learned-rules
section. Never store real client names, account IDs, campaign names, ad
names, exact spend, exact CPA/ROAS, emails, phone numbers, payment details,
screenshots, URLs with tokens, or backend cohort values.

## Non-Negotiable Gates

- Google: do not make pause/scale/geo recommendations from country totals
  alone; break results back to campaign, bid strategy, ad group / asset
  group, device, conversion action, and geo.
- Learning phase: do not recommend disruptive edits during active learning.
- Tracking: verify conversion tracking and attribution before optimization.
- Compliance: check special categories for housing, employment, credit,
  finance, healthcare, and other regulated verticals.
- Reporting: separate observed facts, calculated metrics, and inferences.
- Experiments: require one variable, maturity rules, success/rollback/
  inconclusive criteria, and human approval; otherwise classify as an
  investigation, client request, monitoring item, or non-actionable finding.
- Urgent client demands never waive numeric safety caps; rapid response
  stays inside policy limits and leaves an audit trail.
