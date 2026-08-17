# AppFlow Ops — Overseas App Ad-Buying Agency Operations

AppFlow Ops is an agency-side (乙方) operations system for overseas app
promotion. Its core interaction principle:

> **Users describe the problem. AppFlow decides how to investigate it.**

Users state business problems; AppFlow decides what to analyze. Read-only by
default; every real account write requires item-by-item human confirmation.

[中文 README](README.md) · [Quickstart](QUICKSTART.en.md)

## Core Product Principle: Diverge → Verify → Eliminate → Rank → Converge

The reasoning paradigm AppFlow Ops applies to vague natural-language ad
questions:

```text
Diverge → Verify → Eliminate → Rank → Converge
```

Users express a **Problem**, not a **Procedure**. They should not need to
say "please compare CTR, CPC, CVR, CPA across the last 7 days". They say:

- "Google 最近怎么跑不动了？" (Why is Google suddenly under-delivering?)
- "这个素材还能跑吗？" (Can this creative keep running?)
- "CPA 为什么突然高了？" (Why did CPA jump?)
- "现在该调预算还是调出价？" (Budget or bid first?)
- "为什么有点击但是没安装？" (Clicks but no installs?)
- "我现在应该先处理什么？" (What do I handle first?)

AppFlow's job is to answer: "what should this problem analyze?"

### The Reasoning Loop

```text
Natural-language problem
        ↓
Intent / problem interpretation
        ↓
Diverge      generate plausible, verifiable hypotheses
        ↓
Verify       seek evidence from what exists
        ↓
Eliminate    drop contradicted or inapplicable explanations
        ↓
Rank         prioritize by evidence strength and decision impact
        ↓
Converge     produce the smallest useful decision
        ↓
Action / watch / ask for missing evidence
```

### The Five Stages

**1. Diverge**

Do not jump to a conclusion on a vague question. First expand the set of
business-plausible, worth-verifying hypotheses. For "why is Google suddenly
under-delivering?" that includes: spend/delivery constraint, bid constraint,
budget constraint, learning/maturity, creative exhaustion, audience/geo
limitation, measurement instability, conversion-event quality, funnel
degradation, recent operator changes, product-side conversion changes, and
external market effects.

**Diverge is not unbounded brainstorming.** Generate only hypotheses that
are: relevant to the current platform; relevant to the current workspace;
relevant to the current question; verifiable with existing evidence; or, if
verified, materially change the decision.

**2. Verify**

Seek evidence for hypotheses actively. Plausibility is not proof:

> **Reasoning should be evidence-seeking, not imagination-driven.**

Evidence can come from: current observation, historical snapshots, campaign
metrics, creative metrics, funnel data, previous changes, previous
recommendations, the experiment ledger, replay history, workspace files,
screenshots/exports/pasted tables, declared policy, and measurement,
maturity, and permission state.

**3. Eliminate**

Classify every hypothesis explicitly: `supported` / `contradicted` /
`insufficient evidence` / `not applicable`. Do not keep every possibility
in the final answer.

- CTR stable → "creative totally lost its appeal" is not the first cause;
- click→install clearly degrading → narrow toward install, store page, and
  traffic quality;
- measurement unstable → lower confidence in deep-event conclusions.

The goal is not "list ten possible causes". It is **to minimize the number
of wrong explanations**.

**4. Rank**

Rank survivors instead of flattening them, using: evidence strength, causal
plausibility, timing correlation, magnitude, reversibility, operational
impact, measurement confidence, and decision risk. Converge toward:

```text
Most likely
Possible but secondary
Unresolved
Ruled out
```

...rather than an unprioritized list.

**5. Converge**

The final answer must converge from analysis to action — the smallest useful
operational decision:

```text
keep / increase / decrease / pause / reopen / replace
wait / observe / investigate / request missing evidence
```

With sufficient evidence, give the decision directly. Without it, do not
pretend to know: say what is most likely, what has been ruled out, which
single missing fact would change the decision, and whether getting it is
worth it. **Do not mechanically interrogate the user over non-critical
missing data.**

### Example: "Google 最近怎么跑不动了？"

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

This is a **product-behavior example**, not a claim that the current code
fully automates every step. Today, hypothesis generation and evidence
gathering are Agent work; numeric boundaries and gates are executed by the
deterministic engine.

### This Is Not Chain-of-Thought Display

The model describes the system's **working stages and verifiable decision
process** — not a requirement to dump the model's internal reasoning to the
user. Explore broadly inside; answer concisely outside:

> **Broad internally, concise externally.**

What the user sees is:

```text
Conclusion
Evidence
Ruled out
Risk / uncertainty
Next step
```

...not pages of AI self-talk.

The full behavior contract (trigger conditions, evidence priority, elimination
states, ranking dimensions, convergence output, question discipline) lives in
[`skills/appflow/references/reasoning-contract.md`](skills/appflow/references/reasoning-contract.md);
offline vague-query eval fixtures live in
[`evals/vague-query-evals.json`](evals/vague-query-evals.json).

### Design Principles

```text
Problem over procedure         Users state business problems, not analysis recipes.
Evidence over intuition        Plausible explanations must survive verification.
Elimination over enumeration   A useful agent removes possibilities instead of listing them forever.
Ranking over flat recommendations    Not every hypothesis deserves equal attention.
Action over reporting          Analysis converges into the smallest useful operational decision.
Ask only when it matters       Missing information interrupts the user only when it can change the decision.
Broad internally, concise externally    Explore widely inside; return a focused answer to the operator.
```

## How It Works Today (Implemented)

- **Account audits**: structure, budget, bidding, conversion, and creative
  health checks for Google / Meta / TikTok / Apple app campaigns, with a
  health score and prioritized fixes
- **UAC experiment loop**: deterministic decision engine for Google App
  campaigns — measurement reliability, learning eligibility, single-variable
  experiment admission (draft shown first, ledger written only after
  confirmation), and review
- **Continuous account state**: workspace-scoped operational state
  (Observation / Change / Decision / Outcome / Current State) so follow-up
  questions reuse prior observations, changes, decisions, and outcomes.
  State is isolated per workspace; AppFlow maintains no global cross-client
  business memory (see [docs/account-state.md](docs/account-state.md))

> AppFlow runtime automatically restores workspace-scoped operational
> context for relevant follow-up and diagnosis requests. Direct
> informational questions ("CTR 是什么？") do not need business-state
> retrieval.
- **Platform operational runtime (One AppFlow Core, multiple platform
  adapters)**: Meta / TikTok / Creative and cross-platform diagnosis run
  full workflows through the shared `PlatformOperationalRun` — platform
  scope resolution, platform-aware bounded state retrieval (no platform
  starvation), same-run current evidence, event platform attribution
  (retrievable Decisions/Changes/Outcomes), and the four safety gates
  enforced BEFORE persistence (rejected decisions never land, returning a
  reason code + allowed next actions). Platforms contribute only
  hypothesis families, metric projection, and terminology
  (`platform_adapters.py`); no copied reasoning loop, no new state types.
  Today they are **Agent + shared operational runtime**, not deterministic
  engines (see [docs/appflow-core.md](docs/appflow-core.md))
- **Funnel dashboard**: spend → installs → registrations → payments rendered
  as one self-contained HTML file with the bottleneck layer highlighted
- **Daily agency ops**: patrols, anomaly triage, creative request briefs,
  client template adaptation, client replies, change logs
- **Dual reporting**: client-facing explanations and internal action tickets
  are written separately
- **Question discipline**: only decision-changing questions, batched into
  one message (see `references/client-questions-policy.md`)
- **Rapid response**: bounded quick levers for urgent client demands, each
  with a rollback value and a dual audit trail (see
  `references/rapid-response.md`)
- **Default data path**: exports / pasted tables / screenshots; browser
  bridge is an optional read-only channel

## Architecture: Agent Exploration + Deterministic Constraints

```text
The model explores.
Evidence narrows.
Policy constrains.
The runtime decides.
```

| Agent / LLM owns | Deterministic components own |
| --- | --- |
| interpreting ambiguous language | normalization |
| hypothesis generation | measurement state |
| evidence discovery | maturity |
| workflow routing | numeric boundaries |
|  | policy enforcement |
|  | permissions |
|  | recommendation constraints |
|  | replay evaluation |

The existing Google UAC deterministic engine is the **foundation** of this
model: it hardens the deterministic parts of verify / eliminate / converge
(measurement state, maturity, numeric caps, permissions, gates, replay) into
reproducible code and tests. The reasoning loop runs on top of it, not
instead of it.

## Skills And Platforms

The main router `skills/appflow/` owns intent interpretation and dispatch;
sub-skills cover Google App / UAC (`ads-google-app`), Google, Meta, TikTok,
Apple, attribution, server-side tracking, creative, budget, constrained-lever
diagnosis (`ads-levers`), daily agency ops (`ads-ops`), reporting, planning,
PPC math, and test design. See `skills/appflow/SKILL.md` for the full route
table.

## Usage

### Three Steps To Start

```bash
curl -fsSL https://raw.githubusercontent.com/taotao135791-bit/appflow-ops/v3.6.5/install.sh | bash -s -- --ref=v3.6.5
```

Then talk to your AI coding assistant in natural language:

```text
Read-only review this Google App account. Check data reliability and
conversion delay first, then tell me whether to run an experiment, wait,
or leave the account unchanged.
```

### Isolation And Deterministic Commands

One client gets one private workspace: `workspaces/<client>/<project>/`.
Data, ledgers, and reports never mix; client deliverables are anonymized by
default and kept under `reports/client/`.

```bash
python3 scripts/uac_experiment.py init-workspace my-project --client acme
python3 scripts/uac_experiment.py normalize --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py doctor --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py analyze --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py funnel-dashboard --workspace "workspaces/acme/my-project"
```

## Isolation And Safety

- Client / account / business isolation: one workspace belongs to one
  client; cross-workspace references are rejected
- Numeric safety caps: single changes default to ≤20%, larger moves become
  staged plans; urgency never waives them
- Privacy: real data lives only in private workspaces; reports are
  anonymized by default; client-facing deliverables are stored separately

## Evaluation Privacy

> AppFlow does not require production advertising data to leave the
> operator's environment in order to evaluate its decision behavior.

> Repository evals are synthetic by default.
> Sanitized replay is a local transformation boundary.
> Production data stays local.

Evaluation defaults to fully synthetic fixtures (`evals/`, all marked
`synthetic`); the default runner refuses `production` **and** `sanitized`
data loudly (`ProductionDataError`) instead of degrading silently — a
locally sanitized replay must not silently enter CI. Sanitized replays keep
only decision shape (metric indexes, time buckets, categorical states) and
are one-way: no identity, no reversible mapping; they are a local
inspection tool, not a committed fixture type. Public maintainer contact
information may be explicitly allowlisted (`privacy-allowlist.json`, scoped
to exact values/commits) without relaxing protection for customer or
production identities. See
[docs/eval-privacy.md](docs/eval-privacy.md).

## Boundaries (What It Will Not Do)

- Only Google UAC has a deterministic experiment engine (schema validation,
  measurement/learning states, experiment admission, ledger, replay); other
  platforms are structured agent workflows with
  no deterministic experiment engine equivalent to UAC
- No growth / CPA / ROAS guarantees; one review is never treated as causal
  proof
- No automatic logins and no automatic account changes; real writes require
  item-by-item human confirmation
- When data is immature, measurement is unreliable, or conversion delay has
  not matured, the correct answer can be "wait or fix data, do not modify"

## Product Direction (Not Implemented — Not Current State)

The following are direction, **not** what the system does today:

- universal hypothesis engine: cross-platform hypothesis generation and
  lifecycle management
- automatic evidence retrieval across every platform
- complete Meta / TikTok deterministic decision runtime (only Google UAC
  has one today)
- background account ingestion / continuous polling / daemon monitoring
  (today Continuous Account State is session-persistent, not background
  watching)
- cloud sync / multi-device sync
- fully autonomous vague-query investigation (today it is Agent reasoning
  plus deterministic gates)

## Next Phase (Roadmap — Not Started)

Platform Operational Runtime and the Safety Kernel are closed as stable
foundations. The next phase is **Ads Decision Intelligence**: improving
judgment quality that actually moves campaign outcomes — not expanding
Runtime / State / Safety infrastructure.

- Meta: auction pressure vs creative fatigue vs audience saturation
- TikTok: click→install and deep-funnel breakpoint diagnosis
- Creative: continue / replace / retest / scale decisions
- Bid & Budget: when to change, how much, when to wait
- Cross-platform: media vs product vs measurement diagnosis

AppFlow ranks evidence-backed hypotheses and converges to the smallest
useful operational action — it does not promise AI can always identify
the true cause.

Ads Decision Intelligence will separate platform scope from operational
diagnosis domain, supporting cases such as Meta + Creative, TikTok +
Funnel, Google + Measurement.

v3.5.0 ships: operational-domain aware routing, evidence-backed hypothesis
evaluation (Meta 14 / TikTok 8 / Cross 4 hypothesis families), elimination /
ranking / convergence to the smallest useful action, and a 30-case real
scenario eval set.

From v3.5.1 Decision Intelligence is RUNTIME-NATIVE:
`run.evaluate_decision_intelligence()` automatically consumes current
observations + historical state + the canonical SafetyContext, and runs the
whole pipeline from raw metrics (e.g. `ctr_change_pct: -0.25`) to a
converged result — callers never assemble the pipeline manually; raw
evidence → signals → hypotheses → evaluation → ranking → convergence is
wired end to end; supported rivals are no longer dismissed by score gap;
eval judges strict ranked tops (42 real scenarios incl. raw-evidence and
cross-platform measurement conflict).

From v3.5.2 Decision Intelligence truly understands TIME and MULTIPLE
MEDIA: "现在呢？" really uses the previous State — current + comparable
previous observations derive trends automatically (no caller-supplied
change_pct); recent confirmed Changes are confounder evidence (CTR↓ right
after budget+30% is not instantly creative fatigue); prior
Decision/Outcome are context, never facts; per-platform provenance is
preserved (Meta pay↓ + Google stable is auditable, and a single-platform
decline never promotes a shared diagnosis); a DI recommendation cannot be
silently overridden (explicit operator overrides carry
origin=operator_override); platform_scope is the single source of truth
for cross-platform semantics.

From v3.5.3 evidence is truly ATTACHED to the platform, entity and time that
produced it: provenance-aware evaluation (auction_pressure@meta and
@google_ads are evaluated independently; Meta signals are never spliced
into Google conclusions); shared hypotheses consume shared evidence only
(a single-platform CPM rise never supports market_wide_event — it needs
cross_cpm_up from ≥ 2 platforms); derived trends require the same
entity/level/breakdown (Campaign A yesterday + Campaign B today is not a
CTR decline); "latest stored change" ≠ "current confounder" (only a
change intervening between baseline and current counts); invalid+unknown
is never mislabeled as measurement conflict; the user answer knows whether
the conclusion is "Meta-side" or "shared across both media".

From v3.5.4 Evaluation, Safety and Change all obey the SAME provenance
boundary: applicable_platforms="*" no longer means flat union — every
applicable platform is evaluated separately (Meta signals are never
spliced into Google conclusions); Safety matches evidence provenance
(Meta's invalid measurement never caps Google's diagnosis); a Meta Change
is a confounder only for Meta (platform-specific temporal windows);
historical selection picks the newest COMPARABLE baseline (a newer
incomparable record never blocks an older comparable one); missing
identity never implies account-level aggregation; comparability uses only
a workspace-local opaque entity_key — raw media IDs are never persisted;
measurement conflict signals "investigate consistency", never "shared
measurement problem confirmed".

From v3.5.5 CONVERGENCE obeys the same provenance boundary:
`converge()` resolves Safety from the SELECTED evaluation's scope (a
platform-bound top uses that platform's own measurement/maturity —
missing → unknown, never an aggregate fallback; shared/run tops use
aggregate Safety, staying conservative) — Meta's invalid measurement no
longer rewrites Google's supported `auction_pressure` into a run-wide
investigate measurement; `top_hypothesis` / `top_platform` /
`evaluation_scope` always derive from the SAME selected evaluation
(attribution can never diverge); a safety block changes the action, not
the diagnosis identity (`investigate_measurement` ≠
`top_hypothesis=measurement_instability`); persisted Decision
attribution matches the selected evaluation (`auction_pressure@google_ads`
→ `platform=google_ads`, shared stays `cross_platform`); other
platforms' safety problems survive as `platform_warnings`, never a
global veto.

From v3.6.0 the DI plumbing is FROZEN and the goal becomes Decision
Quality Calibration: measurement hypotheses require ACTUAL measurement
evidence (CVR down with explicitly stable measurement is a funnel
problem, never a tracking problem — stable measurement is a strong
contradiction); recent budget/bid changes are CONFOUNDERS, not logical
exclusions (real fatigue evidence + a recent budget change = two
supported candidates → investigate, never a reckless full swap);
**Diagnosis ≠ Action** (budget cap with CPA 110 vs target 50 →
`increase` is blocked by action eligibility → hold; CPA 32 vs target 50
with no recent change → small increase; a recent change → wait);
**sample size decides evidence strength** (-25% CTR on 150 impressions
is WEAK evidence that cannot support fatigue; the same movement on 100k
impressions is normal; pay count 5 → 3 with -40% is inconclusive,
500 → 300 is material); downstream rates use conservative 12%/15%
material bands with real conversion-count minimums.

From v3.6.1 the calibration itself is hardened (Calibration
Reliability): scale eligibility follows the SELECTED platform's
provenance (Meta's recent budget change never blocks Google's scale);
the invalid-measurement safety cap classifies by hypothesis DOMAIN, not
an ID whitelist — `install_measurement_issue` /
`shared_measurement_issue` stay evaluable (invalid measurement is often
their evidence) and a new `reporting_anomaly` signal carries real
measurement evidence; missing sample size is UNKNOWN, never sufficient
(a -25% CTR with no impressions fact is weak); rate evidence reads
numerator AND denominator (2000 clicks with 2 conversions is not a
strong CVR decline); KPI pass is necessary but not sufficient for scale
— marginal headroom (CPA 49 vs 50) → wait, 1-2 conversions → wait,
comfortable headroom + volume + settled changes → small staged
increase, with `eligibility_reason` codes explaining the deferral.

From v3.6.2 an action must be supported by the CORRECT KPI, correct
outcome evidence, correct platform scope, and sufficient confidence
(Action Confidence & KPI Alignment): missing outcome volume blocks
scale (`missing_outcome_volume` — CPA 30/50 with no conversion count
waits; impressions never stand in for conversions); `measurement=unknown`
and `maturity=unknown` are acceptable for investigation but not for
scale approval (positive safety: stable/sufficient required); the
PRIMARY KPI comes from `primary_kpi` (or a single present target) —
multiple targets without a declaration are `ambiguous_primary_kpi`
(never a hardcoded CPA-first precedence; CPI $3 with pay CPA $140
defers until the goal is clear); outcome volume is KPI-aligned (pay CPA
→ payments, purchase CPA → purchases, CPI → installs — 1000 installs
never justify pay-CPA scale); supported hypotheses on OTHER platforms
are parallel issues, not material rivals (Google may scale while Meta
fatigue is handled separately); explicit trend strings go through the
same sample calibration as numeric change_pct (`ctr_trend="down"` on
150 impressions is weak, never normal).

From v3.6.3 (Decision Attribution & Goal Semantics) a correct judgment
must also know exactly WHO it is about, WHAT goal governs it, WHICH
evidence belongs to it, and WHETHER another issue really invalidates
the action: the user-facing summary consumes result.selected_evaluation
(never rescanning evaluations by hypothesis ID — auction_pressure@google_ads
top can never cite auction_pressure@meta's CPM); parallel issues keep
platform attribution (creative_fatigue@meta != creative_fatigue@tiktok);
conversion_event / optimization_goal are EVENT semantics normalized to
their KPI family (conversion_event="pay" → pay_cpa, optimization_goal=
"purchase" → purchase_cpa; an explicit KPI/goal conflict is ambiguous,
never a guess); ROAS outcome volume requires revenue-generating events
(generic conversions without event semantics → missing_outcome_volume);
shared hypotheses are classified by ACTION RELEVANCE (shared
funnel/measurement issues block scale; market_wide_event is material
context — warn, stay small/staged, never veto); scale evidence minimums
are KPI-family aware (cpi 50 / pay_cpa 10 — 20 installs and 20 payments
are not the same scale readiness).

From v3.6.4 (Optimization Timing & Action Sequencing) AppFlow knows
that even a correct action is not necessarily the right action NOW:
ACTION ELIGIBILITY != ACTION READINESS — a second material action needs
enough NEW evidence since the last confirmed Change (elapsed time +
KPI-matched window_outcomes; lifetime totals never prove post-change
readiness; a temporary KPI dip right after a change is a window
problem, never an automatic descale); the decision window starts at the
last material Change; ONE material lever at a time (budget first when
budget-constrained, bid first when bid-constrained, investigate when
both — never change both); scale carries small/normal magnitude (deep
KPIs and market context scale small; numeric Safety remains the final
cap); descale is small and requires stable measurement + mature sample
+ persistent negative trend + no recent change (no ping-pong); creative
fatigue is refresh/retest/pause/hold (refresh with acceptable overall
KPI, retest on weak/confounded evidence, pause on a specific consistent
loser with sufficient sample, hold inside a new creative's test
window); wait must name its next review trigger (more_pay_outcomes /
more_installs / ...); goal sources are validated TOGETHER
(optimization_goal=install + conversion_event=pay → ambiguous, never a
guess; purchase event + ROAS target → ambiguous_primary_kpi unless a
goal disambiguates).

The project knows what it is building: **the reasoning paradigm is defined,
the deterministic foundation is in place, and the rest is being built toward
this direction.**

## Install And Layout

Installs to `~/.appflow/skills` by default; supports
`--target=codex|cursor|windsurf|gemini|goose` and `--skill-dir` overrides.
Windows: `install.ps1`. Uninstall: `bash uninstall.sh`.

```text
skills/appflow/      main router (reasoning loop, question discipline, isolation, routing)
skills/ads-*/        platform and workflow sub-skills (Google/Meta/TikTok/Apple + agency ops)
agents/              audit and creative persona briefs
scripts/             local deterministic tools (UAC engine, funnel dashboard, PDF reports)
docs/                numeric safety policy, Quick Ops, release process
```

## Going Deeper

- UAC experiment loop and Quick Ops numeric decisions:
  [docs/quick-ops-numeric-decisions.md](docs/quick-ops-numeric-decisions.md)
- Numeric safety policy (change caps, staged plans, correction/emergency
  contracts): [docs/numeric-safety-policy.md](docs/numeric-safety-policy.md)
- Releases: [docs/releasing.md](docs/releasing.md)
- Copy-paste prompts: [QUICKSTART.en.md](QUICKSTART.en.md)

## License

MIT. See [LICENSE](LICENSE).
