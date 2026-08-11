# Eval Privacy Threat Model

Short engineering document. Not a legal privacy policy.

## Principle

> Evaluation must not require production advertising data to leave the
> operator's environment.

> AppFlow evaluates decision behavior, not customer identities.

Data tiers and their allowed uses:

| tier | allowed | forbidden |
| --- | --- | --- |
| `synthetic` | CI, repository, future external benchmarks | — |
| `sanitized` | repository (after privacy check), CI, future external benchmarks | retaining any identity |
| `production` | operator-controlled local environment only | commit, CI upload, external eval |

## What are we protecting?

- client identity
- account identity
- campaign strategy
- creative content
- financial performance
- local environment information

## What are the main leak paths?

- committed fixtures
- CI logs
- external model APIs
- screenshots
- raw replay
- absolute paths
- free-form notes

## What is the default?

```text
synthetic first
sanitized second
production local-only
```

## Enforced boundaries

- The default evaluation runner refuses `data_class: production` with
  `ProductionDataError`; no silent degradation.
- Sanitization is one-way: decision shape is preserved (metric indexes,
  time buckets, categorical states), identity is dropped. No reversible id
  mapping is created or committed.
- CI is offline-safe: no API keys, no production workspace access, only
  repository synthetic fixtures. An explicit future local-only mode is the
  only permitted path for real data.
- No implicit cloud fallback: if a local model runner were unavailable, the
  runner must fail explicitly, never switch to a remote model.
- Fixtures carry provenance (`data_class` + `source_type`) but never
  `source_client`, `original_path`, or original identifiers.

## Checks

- `python scripts/release_check.py` — preflight: version consistency,
  reasoning contract, eval fixture schema/privacy, worktree privacy scan.
- `python scripts/privacy_doctor.py` — repository privacy audit (worktree
  and full history).
