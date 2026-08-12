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
curl -fsSL https://raw.githubusercontent.com/taotao135791-bit/appflow-ops/v3.3.1/install.sh | bash -s -- --ref=v3.3.1
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
