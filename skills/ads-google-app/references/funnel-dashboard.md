# Funnel Diagnosis Dashboard (漏斗诊断看板)

Generate one self-contained HTML dashboard from a normalized UAC case when
the user asks for funnel diagnosis or says "生成看板 / 漏斗诊断". The
dashboard is an internal diagnosis deliverable, not a client promise.

## When To Generate

- The user asks where users are leaking between install → registration →
  payment, or asks for a visual funnel.
- Before proposing any funnel-related lever (bid change, creative change),
  to anchor the discussion in observed stage conversions.

## Command

```bash
python3 scripts/uac_experiment.py funnel-dashboard \
  --workspace workspaces/<client>/<project>
```

Or with an explicit normalized input:

```bash
python3 scripts/uac_experiment.py funnel-dashboard \
  skills/ads-google-app/assets/UAC-INPUT.example.yaml --output funnel.html
```

Inside a workspace the HTML is written to `reports/funnel-dashboard.html`
with private permissions. It has no external assets and opens in any
browser.

## Reading The Dashboard

- **Funnel bars**: count layers (install / registration / payment). Missing
  layers are shown as data gaps, never invented.
- **Bottleneck layer (red)**: the stage transition with the lowest observed
  conversion rate. It is a starting hypothesis, not a proven cause.
- **Observed / Calculated / Inference panels**: keep these three categories
  separate when explaining the dashboard to anyone.

## Rules

- Do not send the raw dashboard to the client as an effect promise; if the
  client needs it, rebuild the narrative via the report workflow
  (`ads-report`) with anonymized labels.
- If a layer is missing (for example no payment data), the correct
  conclusion is "补齐数据再诊断", not a bid or creative change.
- The dashboard never writes the ledger and never changes any account.
