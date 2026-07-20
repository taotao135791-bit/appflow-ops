---
name: ads-audit
description: >-
  Full multi-platform paid advertising audit with parallel subagent delegation. Analyzes
  Google Ads, Meta Ads, LinkedIn Ads, TikTok Ads, Microsoft Ads, and Apple Ads accounts
  via 6 parallel audit agents. Amazon Ads, cross-platform attribution, and server-side
  tracking are covered by their standalone sub-skills (ads-amazon, ads-attribution,
  ads-server-side-tracking). Generates health score per platform and aggregate score
  (0-100). Use when user says audit, full ad check, analyze my ads, account health check,
  paid media audit, paid advertising audit, ad spend audit, advertising audit, or PPC
  audit. 中文触发: 广告账户审计, 账户体检, 全平台广告诊断, 广告健康度评分.
---

# Full Multi-Platform Ads Audit

## Reference Resolution

For any `ads/references/<file>.md` path below, read the first existing path:
`${KIMI_SKILL_DIR}/../ads/references/<file>.md`,
`~/.kimi-code/skills/ads/references/<file>.md`,
`~/.agents/skills/ads/references/<file>.md`,
`skills/ads/references/<file>.md`, then `ads/references/<file>.md`.

This audit operates under the **10-Principle Thinking Framework** (see
`ads/references/thinking-framework.md`). OBSERVE (External + Internal)
dominates data collection, THINK + CONNECT (Lateral) dominate analysis,
CONNECT (System) + ACCEPT dominate synthesis and prioritization. If the
audit feels mechanical, you are skipping a principle.

## Process

1. **Collect account data**: prefer Kimi WebBridge read-only inspection of
   live ad dashboards when the user is logged in or asks you to look directly.
   If WebBridge is unavailable, request exports, screenshots, pasted metrics,
   or API/MCP access.
2. **Validate**: confirm at least one platform's data is available before proceeding
3. **Detect business type**: analyze account signals per ads orchestrator
4. **Identify active platforms**: determine which platforms are in use
5. **Delegate to subagents** (if delegation is available, otherwise run inline
   sequentially). Kimi Code CLI has no custom subagent registry: dispatch the
   built-in `coder` subagent for each specialist. The persona briefs ship
   inside the installed ads skill — read the persona file first (resolve
   `agents/<name>.md` as `${KIMI_SKILL_DIR}/agents/<name>.md` when running as
   the ads skill, then `${KIMI_SKILL_DIR}/../../agents/<name>.md` in a plugin
   install, then `~/.kimi-code/skills/ads/agents/<name>.md`, or the repo
   `agents/<name>.md`) and pass its full content as the subagent's brief:
   - `ads-google-app` sub-skill: UAC measurement, learning eligibility,
     optimization feasibility, permission boundary, and one experiment loop
   - `agents/audit-google.md`: Conversion tracking, wasted spend, structure, keywords, ads, settings (80 checks; G01-G61 + 19 hyphenated v1.5+ IDs incl. AI Max)
   - `agents/audit-meta.md`: Pixel/CAPI health, creative fatigue, structure, audience (50 checks; M01-M40 + 10 hyphenated v1.5+ IDs incl. Andromeda)
   - `agents/audit-creative.md`: LinkedIn, TikTok, Microsoft creative checks + cross-platform synthesis
   - `agents/audit-tracking.md`: LinkedIn, TikTok, Microsoft tracking + cross-platform tracking health
   - `agents/audit-budget.md`: LinkedIn, TikTok, Microsoft budget/bidding + cross-platform allocation
   - `agents/audit-compliance.md`: All-platform compliance, settings, performance benchmarks
6. **Validate**: verify each subagent returned valid scores with required fields before aggregating
7. **Score**: calculate per-platform and aggregate Ads Health Score (0-100)
8. **Report**: generate prioritized action plan with Quick Wins

For Google App campaigns, the UAC structured result is the source of truth.
Do not let the generic health score override a `TRACKING_BLOCKED`,
`LEARNING_BLOCKED`, or `NO_ACTION_RECOMMENDED` UAC decision.

## Data Collection

Ask the user for available data. Accept any combination:
- Google Ads: account export, Change History, Search Terms Report
- Meta Ads: Ads Manager export, Events Manager screenshot, EMQ scores
- LinkedIn Ads: Campaign Manager export, Insight Tag status
- TikTok Ads: Ads Manager export, Pixel/Events API status
- Microsoft Ads: account export, UET tag status, import validation results

If live dashboard access is available through Kimi WebBridge, inspect it first
using `ads/references/webbridge-live-audit.md`. If no live access or exports
are available, audit from screenshots or manual data entry.

## Scoring

Read `ads/references/scoring-system.md` for full algorithm.

### Per-Platform Weights

| Platform | Category Weights |
|----------|-----------------|
| Google | Conversion 25%, Waste 20%, Structure 15%, Keywords 15%, Ads 15%, Settings 10% |
| Meta | Pixel/CAPI 30%, Creative 30%, Structure 20%, Audience 20% |
| LinkedIn | Tech 25%, Audience 25%, Creative 20%, Lead Gen 15%, Budget 15% |
| TikTok | Creative 30%, Tech 25%, Bidding 20%, Structure 15%, Performance 10% |
| Microsoft | Tech 25%, Syndication 20%, Structure 20%, Creative 20%, Settings 15% |

### Aggregate Score

```
Aggregate = Sum(Platform_Score x Platform_Budget_Share)
Grade: A (90-100), B (75-89), C (60-74), D (40-59), F (<40)
```

## Output Files

- `ADS-AUDIT-REPORT.md`: Comprehensive multi-platform findings
- `ADS-ACTION-PLAN.md`: Prioritized recommendations (Critical > High > Medium > Low)
- `ADS-QUICK-WINS.md`: Items fixable in <15 minutes with high impact

## Report Structure

### Executive Summary
- Aggregate Ads Health Score (0-100) with grade
- Per-platform scores
- Business type detected
- Active platforms identified
- Top 5 critical issues across all platforms
- Top 5 quick wins across all platforms

### Per-Platform Sections
Each platform section includes:
- Platform Health Score with grade
- Category breakdown with pass/warning/fail per check
- Platform-specific Quick Wins
- Detailed findings with remediation steps

### Cross-Platform Analysis
- Budget allocation assessment (actual vs recommended)
- Tracking consistency (are all platforms tracking the same events?)
- Creative consistency (is messaging aligned across platforms?)
- Attribution overlap (are platforms double-counting conversions?)

### Strategic Recommendations
- Platform prioritization based on business type
- Budget reallocation recommendations
- Scaling opportunities (platforms/campaigns ready to scale)
- Kill list (campaigns/ad groups to pause immediately)

## Priority Definitions

- **Critical**: Revenue/data loss risk (fix immediately)
- **High**: Significant performance drag (fix within 7 days)
- **Medium**: Optimization opportunity (fix within 30 days)
- **Low**: Best practice, minor impact (backlog)

## Quick Wins Criteria

```
IF severity == "Critical" OR severity == "High"
AND estimated_fix_time < 15 minutes
THEN flag as Quick Win
SORT BY (severity_multiplier x estimated_impact) DESC
```
