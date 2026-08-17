# AppFlow Ops Quickstart

Overseas app-promotion agency operations. **No commands to memorize, no YAML
required**: hand exports, pasted tables, or screenshots to your AI assistant,
then copy one natural-language prompt.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/taotao135791-bit/appflow-ops/v3.6.5/install.sh | bash -s -- --ref=v3.6.5
```

Windows:

```powershell
irm https://raw.githubusercontent.com/taotao135791-bit/appflow-ops/v3.6.5/install.ps1 -OutFile install.ps1
.\install.ps1 -Ref v3.6.5
```

## First Use

```text
I want to use AppFlow Ops for overseas app ad operations. Stay read-only by
default; before client reports, ask me where the template lives.
```

## Boundaries (Read First)

- No growth / CPA / ROAS guarantees; does not replace product, paywall,
  SDK/tracking, MMP, or backend events
- No automatic logins or account changes; real writes require explicit
  confirmation for that exact action
- With insufficient data, the right advice can be "do not modify the account"
- One account's experience does not generalize automatically

## The Agency Trio

### 1. Question Discipline

Only decision-changing questions get asked, batched into one message: KPI
definition, permission boundary, business ceiling, urgency, available data.
Everything else is inferred and labeled as inference.

### 2. Client Isolation

One private workspace per client — data, ledgers, and reports never mix:

```text
Initialize a UAC project for client acme, project name ios-main.
```

(Command: `python3 scripts/uac_experiment.py init-workspace ios-main --client acme`)

### 3. Rapid Response (Urgent Clients)

```text
The client wants CPA down today. Confirm KPI semantics and permissions first,
then give me bounded quick levers with rollback values and review conditions,
plus both the client-facing explanation and the internal action ticket.
```

## Daily Prompts (Copy-Paste)

Account checkup:

```text
Read-only review this ad account: spend pacing, conversion quality, goal
setup, and next actions. Do not change any settings.
```

Daily patrol:

```text
Read-only look at yesterday and find the 3 things I must handle today:
spend, payments, CPA, rejected creatives, tracking issues, geo/device anomalies.
```

Constrained agency diagnosis:

```text
We are the agency; KPI and product are fixed. Installs are high but payments
low. Read-only: which media levers can still move, what needs client help,
and how do I explain it to the client.
```

UAC quick decision (hold / adjust / parallel / switch / wait):

```text
I'm running AC2.5. Tell me directly: hold, adjust, run parallel, switch, or wait.
```

Funnel dashboard:

```text
Generate the funnel diagnosis dashboard for this client, mark the bottleneck
layer, and tell me exactly which layer's data is missing if any.
```

Daily report:

```text
Fill today's numbers into the client's daily template. I'll open the template
or give you the path; read-only, do not write back.
```

Client reply:

```text
Rewrite this conclusion for the client: causes, risks, next steps, expected
impact; fewer platform terms.
```

Anomaly triage:

```text
Payments dropped suddenly. Don't suggest budget changes yet; triage by data
delay, tracking, review status, spend, geo, and creative structure.
```

## UAC Loop In Five Lines

```text
1. Initialize a UAC project for this account (state the client name).
2. Analyze this week's UAC data and tell me whether to act. (attach data)
3. Draft one experiment from this analysis. (show first, don't write the ledger)
4. I executed <change> today at <time, timezone>, no other changes; record it.
5. Review the current experiment. (attach same-scope latest data)
```

Real data stays in a private, git-ignored workspace; drafts enter the local
ledger only after confirmation; a ledger write is not permission to edit
Google Ads.

## Optimizer Profile

Keep `APPFLOW_OPTIMIZER.md` in your project directory with your judgment
habits, scale/kill rules, and client tone:

```text
Create APPFLOW_OPTIMIZER.md. My style: check the conversion goal first, then
spend pacing, then geo and creative; direct with clients but not aggressive.
```

## Advanced Commands (Source Checkout)

```bash
python3 scripts/uac_experiment.py init-workspace my-project --client acme
python3 scripts/uac_experiment.py normalize --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py doctor --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py analyze --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py decide --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py funnel-dashboard --workspace "workspaces/acme/my-project"
```

Ledger migration (1.0 → 1.1) previews first, then writes a new file; see the
[README](README.en.md) and `docs/`.
