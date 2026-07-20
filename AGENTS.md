# Kimi Ads Project Notes

Kimi Ads is a local skill bundle for paid media audits, planning, creative review, PPC calculators, attribution checks, and PDF reporting.

## Layout

- `ads/SKILL.md`: main `/ads` orchestrator skill.
- `skills/ads-*`: focused sub-skills for platforms and workflows.
- `skills/ads-google-app`: UAC feasibility, structured analysis, and local
  experiment-ledger contracts.
- `agents/*.md`: reusable audit and creative persona briefs, installed inside
  the main skill at `agents/` and dispatched to Kimi's built-in `coder`
  subagent (Kimi has no custom subagent directory).
- `ads/references/*.md`: scoring, platform specs, compliance, benchmarks, and implementation references.
- `scripts/*.py`: optional local utilities for page fetches, screenshots, landing-page analysis, image generation, and PDF reports.
- `scripts/uac_experiment.py`: deterministic UAC fixture replay, ledger review,
  structured analysis, and Markdown report helper.
- `kimi.plugin.json`: Kimi plugin manifest (`"skills": "./skills/"`).
- `tests/`: pytest coverage for routing, scoring, check catalogs, and URL safety.

## Kimi Runtime

Default install target is Kimi Code CLI:

```bash
bash install.sh
```

This installs skills to `~/.kimi-code/skills` and agent persona briefs to
`~/.kimi-code/skills/ads/agents`.

Alternatively, install the whole repository as a Kimi plugin from inside Kimi
Code CLI:

```text
/plugins install https://github.com/taotao135791-bit/kimi-ads
```

## Development

Run the test suite with:

```bash
pytest -q
ruff check scripts tests
mypy scripts/kimi_ads/uac
```
