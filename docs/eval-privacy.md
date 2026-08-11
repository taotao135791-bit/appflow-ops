# Eval Privacy Threat Model

Short engineering document. Not a legal privacy policy.

## Principle

> Evaluation must not require production advertising data to leave the
> operator's environment.

> AppFlow evaluates decision behavior, not customer identities.

## Data tiers and their allowed uses

| tier | allowed | forbidden |
| --- | --- | --- |
| `synthetic` | repository, CI, default eval, future external benchmarks | — |
| `sanitized` | local optional analysis; may be generated locally; NOT committed by default | being treated as zero-risk |
| `production` | operator-controlled local environment only | commit, CI upload, external eval |

**Repository benchmark = synthetic only.** Sanitized replay is a *local
transformation boundary*, not a committed fixture type. The pipeline for real
data is:

```text
production replay
↓
local sanitizer
↓
sanitized structural case
↓
local inspection / pattern extraction
↓
if needed, author a NEW synthetic fixture (never commit the sanitized case
directly)
```

Sanitization reduces identity and business-data exposure by preserving only
the decision-relevant structure allowed by the sanitizer schema. It cannot
prove the absence of every sensitive value: `identity_markers()` is
defense-in-depth, and the sanitizer whitelist remains the primary boundary.
Sanitized output may still carry re-identification risk (geo + date + amount
combinations), so it stays local-first, reviewable, and minimal.

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
sanitized local-only
production stays local
```

## Public maintainer identity

Public maintainer contact information (for example the owner's personal email
used as git commit / release-tag identity) is intentionally not treated as a
violation. Such exceptions are recorded in `privacy-allowlist.json` as
**scoped exceptions**: an exact value digest and/or exact commit reference,
never a whole finding kind. This allowlist does not relax protection for
customer, client, or other personal identities — a new email of the same
kind still fails the gate.

## Enforced boundaries

- The default evaluation runner refuses `data_class: production` **and**
  `data_class: sanitized` with `ProductionDataError`; no silent degradation,
  no committed sanitized fixtures by default.
- Sanitization is one-way: decision shape is preserved (metric indexes,
  time buckets, categorical states), identity is dropped. No reversible id
  mapping is created or committed.
- CI is offline-safe: no API keys, no production workspace access, only
  repository synthetic fixtures.
- No implicit cloud fallback: if a local model runner were unavailable, the
  runner must fail explicitly, never switch to a remote model.
- Fixtures carry provenance (`data_class` + `source_type`) but never
  `source_client`, `original_path`, or original identifiers.

## Checks

- `python scripts/release_check.py` — preflight: version consistency,
  reasoning contract, eval fixture schema/privacy (synthetic-only), worktree
  privacy scan.
- `python scripts/release_check.py --full --allowlist privacy-allowlist.json`
  — pre-tag run including the full reachable-history scan; identical logic to
  the GitHub release gate.
- `python scripts/privacy_doctor.py --history --allowlist privacy-allowlist.json`
  — full-history audit with scoped exceptions only.
