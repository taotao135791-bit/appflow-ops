# AppFlow Ops — Overseas App Ad-Buying Agency Operations

AppFlow Ops is an agency-side (乙方) skill bundle for overseas app promotion:
account audits, the UAC experiment loop, funnel diagnosis dashboards, client
daily/weekly reports, and rapid response to urgent client demands. Read-only
by default; every real account write requires item-by-item human confirmation.

[中文 README](README.md) · [Quickstart](QUICKSTART.en.md)

## What It Does

- **Account audits**: structure, budget, bidding, conversion, and creative
  health checks for Google / Meta / TikTok / Apple app campaigns, with a
  health score and prioritized fixes
- **UAC experiment loop**: deterministic decision engine for Google App
  campaigns — measurement reliability, learning eligibility, single-variable
  experiment admission (draft shown first, ledger written only after
  confirmation), and review
- **Funnel dashboard**: spend → installs → registrations → payments rendered
  as one self-contained HTML file with the bottleneck layer highlighted
- **Daily agency ops**: patrols, anomaly triage, creative request briefs,
  client template adaptation, client replies, change logs
- **Dual reporting**: client-facing explanations and internal action tickets
  are written separately

## Three Steps To Start

```bash
curl -fsSL https://raw.githubusercontent.com/taotao135791-bit/appflow-ops/v3.0.0/install.sh | bash -s -- --ref=v3.0.0
```

Then talk to your AI coding assistant in natural language — no commands to
memorize:

```text
Read-only review this Google App account. Check data reliability and
conversion delay first, then tell me whether to run an experiment, wait,
or leave the account unchanged.
```

## Agency Workflows (Core)

### Question Discipline: ask what matters, skip the rest

Ask only questions that change the next decision, batched into one message:
client KPI and acceptance definition, permission boundary, business CPA/ROAS
ceiling, urgency, available data. Never ask about client margins, roadmap,
or other vendors — infer and mark the inference instead. See
`references/client-questions-policy.md`.

### Urgent Client Demands: respond fast, stay inside the guardrails

When the client demands "get CPA down today", the rapid-response flow
confirms KPI semantics and permissions first, then proposes bounded quick
levers (stop anomalies, exclude bad segments, tighten targets within policy
caps, rebalance budget internally), each with a rollback value and review
condition. It always produces two artifacts: the client-facing explanation
and the internal action ticket, both recorded in that client's workspace.
With weak evidence, the honest answer is "hold + explain", never fabricated
numbers.

### Client / Account / Business Isolation

One client gets one private workspace: `workspaces/<client>/<project>/`.
Data, ledgers, and reports never mix between clients; client deliverables
are anonymized by default and kept under `reports/client/`.

```bash
python3 scripts/uac_experiment.py init-workspace my-project --client acme
python3 scripts/uac_experiment.py normalize --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py doctor --workspace "workspaces/acme/my-project"
python3 scripts/uac_experiment.py analyze --workspace "workspaces/acme/my-project"
```

### Funnel Dashboard (generated on demand)

```bash
python3 scripts/uac_experiment.py funnel-dashboard --workspace workspaces/acme/my-project
```

Outputs self-contained HTML (no external dependencies); missing funnel
layers are reported as data gaps, never invented.

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
- Urgency never waives numeric safety caps (default single change ≤20%);
  larger moves become staged plans

## Install And Layout

Installs to `~/.appflow/skills` by default; supports
`--target=codex|cursor|windsurf|gemini|goose` and `--skill-dir` overrides.
Windows: `install.ps1`. Uninstall: `bash uninstall.sh`.

```text
skills/appflow/      main router (question discipline, isolation, routing)
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
