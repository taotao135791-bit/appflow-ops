# Changelog

All notable changes to AppFlow Ops are documented here.

## 3.3.0 — 2026-08-11

### Continuous Account State (isolation-first)

- **Isolation architecture before state**: one workspace = one state store,
  physically under `workspaces/<client>/<project>/state/`; no global
  business memory, no global index, no cross-client database, no vector
  store. All state access is workspace-bound through a frozen `RunContext`;
  no API accepts an arbitrary filesystem path.
- Five object types, append-only JSON events with a derived, rebuildable
  `current-state.json`: Observation (facts, not explanations, common
  envelope + platform payload), Change (confirmed operations only;
  unconfirmed user statements stay `reported` observations), Decision
  (concise rationale, evidence refs, policy/measurement/maturity state,
  confidence, review condition; no hidden chain-of-thought), Outcome
  (linked to decision/change/observation), Current State (derived summary
  with pending review).
- Pending review: a decision with a review condition stays pending until an
  outcome links to it — a marker for the next conversation, never a
  background job (no daemon/cron/polling).
- Bounded retrieval (`get_recent(limit=…)`, capped at 100); current-state
  derivation consumes only recent events while counting the full log.
- Workspace containment enforced everywhere via the existing
  `Workspace.require_contained_path`: traversal, absolute external paths,
  symlink escapes (including symlinks planted inside the events directory),
  and cross-workspace source references are contract errors. Corrupted
  current state rebuilds from events; corrupted events fail loudly.
- CLI (internal/debug): `state init|status|show|rebuild|clear` under
  `uac_experiment.py`; clear is destructive, workspace-scoped, requires
  `--yes`.
- Reasoning Contract: workspace state is an additional Verify-stage
  evidence source (bounded, current workspace only; never borrow another
  workspace's history).
- Docs: new `docs/account-state.md` (stores / does not store / isolation /
  cross-workspace / privacy); README (zh/en) capability line; AGENTS.md
  non-negotiable principles (no global business memory; every persistent
  business state has an explicit workspace owner).
- New tests: storage, lifecycle, pending review, reasoning integration,
  privacy, and the cross-workspace isolation suite (A–H: read/write/
  traversal/symlink/delete/rebuild/retrieval/identifier leakage) plus
  adversarial path variants.

## 3.2.1 — 2026-08-11

### Privacy: scoped allowlist replaces kind-wide waivers

- `privacy_doctor.py` findings now carry stable `value_sha256s` digests
  (email/identity values, bytecode paths) so an exception can accept one
  exact known finding instead of a whole finding kind.
- New `privacy-allowlist.json`: human-readable, reviewable, deterministic
  scoped exceptions. Every exception must pin `value_sha256s` and/or
  `references`; a kind-only exception is rejected at load time (it would
  silently become a kind-wide waiver).
- The GitHub release gate no longer uses `--waive`; it runs
  `release_check.py --full --allowlist privacy-allowlist.json`, the same
  preflight the maintainer runs locally before tagging.
- `--waive` stays on the CLI but is marked legacy and prints a warning; it
  must not be used for releases.
- Accepted exceptions are auditable: the report lists `waiver_usage`
  (exception ids used) and each accepted finding carries `waiver_id` +
  `waiver_reason`; status flips to PASS only when every finding was accepted
  by a scoped exception.
- Regression cases (Part 16) cover: known maintainer email passes, a new
  email of the same kind fails, known historical bytecode fingerprint
  passes, new bytecode fails, known maintainer identity passes, new
  unrelated identity fails.

### Eval privacy boundary unified (synthetic-only repository)

- Repository benchmark is synthetic only: the default eval runner now
  refuses `sanitized` cases alongside `production` (`ProductionDataError`),
  so a locally sanitized replay cannot silently enter CI.
- `docs/eval-privacy.md` and README (zh/en) now describe sanitized replay as
  a local transformation boundary, not a committed fixture type.
- `identity_markers()` extended (UUID, long numeric ids, labeled
  token-like strings) as defense-in-depth; the sanitizer whitelist remains
  the primary boundary.

### Reasoning safety contract completed

- `policy_state` (none / staged_required / cap_20pct / forbid_numeric) now
  participates in expected behavior; the layer consumes simplified policy
  state and never re-implements the UAC policy engine.
- `permission_state` (recommend_only / read_only) forbids
  `claim_execution`; a recommend-only operator's answer must never be
  phrased as executed.
- Measurement and maturity decision classes are fully split: each gate
  forbids its own rules (`recommend_numeric_change_when_measurement_invalid`
  vs `recommend_numeric_change_without_maturity`), so an eval failure names
  exactly which gate was broken. Fixture `meas_cpa_spike_003` and the other
  measurement-invalid fixtures now declare measurement-specific rules.
- New tests: measurement/maturity/policy/permission gate behavior,
  gate-distinctness, fixture compatibility, and state validation.

### Release preflight

- `release_check.py --full --allowlist privacy-allowlist.json` runs the
  full reachable-history privacy scan before tagging (worktree scan remains
  the default; `--full` adds history).

## 3.2.0 — 2026-08-11

### Release health (P0)

- Fixed CI foundation-contracts failure: ruff was unpinned (`>=0.12,<1.0`)
  and 0.16 widened its default rule set. ruff is now pinned to 0.16.2 and
  the lint contract is explicit in `pyproject.toml` (rules disabled with
  documented reasons); scripts gained executable bits, and a private
  test re-export lost by an auto-fix was restored.
- Fixed installer smoke failure: `check_install_layout.py` still expected
  the pre-rebrand `ads/` layout; required files and reference/agent paths
  now check `appflow/`. Verified with a real local install.
- Fixed Release Privacy Gate: annotated tags v3.0.0/v3.1.0 carry the
  owner's personal email as tagger identity; the owner accepted this on
  2026-08-11, so `non-placeholder-email` joins the waiver list (kept
  visible as waived INFO).
- New `scripts/release_check.py` preflight: version consistency, reasoning
  contract presence, eval fixture schema/privacy, worktree privacy scan.

### Privacy-safe evaluation (P1)

- Eval fixtures now declare `data_class` (`synthetic`/`sanitized`/
  `production`) and `source_type` provenance; all 24 vague-query cases are
  `synthetic`/`authored`.
- The default evaluation runner refuses `production` data with
  `ProductionDataError`; no silent degradation.
- New one-way replay sanitizer (`appflow_ops.evals.sanitize`): drops
  identity/free text/URLs/paths, normalizes money to indexes, buckets
  time, never creates reversible mappings.
- New deterministic safety derivation (`appflow_ops.evals.safety`):
  measurement=invalid forbids aggressive numeric optimization and
  confident deep-event diagnosis; maturity=insufficient forbids premature
  bid changes.
- New `docs/eval-privacy.md` threat model and README Evaluation Privacy
  principles (synthetic-first; production stays local).
- CI: eval schema/privacy checks and release preflight added to
  foundation contracts.

## 3.1.0 — 2026-08-11

### Added

- **AppFlow Reasoning Contract** (`skills/appflow/references/reasoning-contract.md`):
  single canonical definition of Diverge → Verify → Eliminate → Rank →
  Converge, with trigger conditions, evidence priority, elimination states,
  ranking dimensions, convergence output shape, ask-only-when-material, and
  the no-chain-of-thought rule.
- **Vague Query Eval Suite** (`evals/vague-query-evals.json`): 24 fixture
  cases across Google/UAC, Meta, TikTok, cross-platform, and measurement,
  with a thin `Evaluator` interface for future model benchmarks and
  deterministic schema/consistency checks.
- Reasoning Contract inheritance in 12 diagnosis skills (one-line reference;
  no prompt duplication).
- Version alignment guard: README/QUICKSTART pinned install version must
  equal VERSION; all version sources are checked in CI.

### Changed

- Main router behavior: `Reasoning Loop` section replaced by a reference to
  the canonical contract; ambiguous diagnosis now inherits the contract
  across skills instead of duplicating prompt text.
- Release/version alignment: README install target moved from v3.0.0 to
  v3.1.0 so documented behavior matches the released artifact.

## 3.0.0 — 2026-08-11 (breaking)

### Rebrand and repositioning

- Renamed the product from Kimi Ads to **AppFlow Ops**; repository, plugin
  manifest (`appflow.plugin.json`), installers, Python package
  (`scripts/appflow_ops/`), and docs follow.
- Repositioned to overseas **app-promotion agency operations** (乙方视角).
  Removed non-app or non-core skills: `ads-amazon`, `ads-linkedin`,
  `ads-microsoft`, `ads-landing`, `ads-dna`, `ads-photoshoot`, their audit
  references, and non-app plan templates.
- Main router renamed `skills/ads/` -> `skills/appflow/` (mirror `ads/` ->
  `appflow/`); routing shorthand is now `/appflow ...`.

### Agency workflows

- New question discipline (`client-questions-policy.md`): ask only
  decision-changing questions, batched; infer and mark the rest.
- New rapid-response workflow for urgent client demands
  (`ads-ops/references/rapid-response.md`): bounded quick levers, rollback
  values, dual output (client explanation + internal action ticket), audit
  trail; numeric safety caps are never waived.
- Client/account/business isolation: `init-workspace --client <label>`
  creates `workspaces/<client>/<project>/`; project context records
  `client_label` and `business_line`; workspaces reject cross-workspace
  references and keep client deliverables under `reports/client/`.

### Funnel diagnosis dashboard

- New `funnel-dashboard` CLI subcommand (and `scripts/funnel_dashboard.py`):
  renders a self-contained HTML funnel (spend -> installs -> registrations ->
  payments), highlights the bottleneck layer, separates observed /
  calculated / inferred, and reports missing layers as data gaps.

### Install changes

- Default install target is now host-agnostic `~/.appflow/skills`
  (overridable via `APPFLOW_HOME`); removed vendor-specific desktop targets.
  Repo URL plumbing env var renamed to `APPFLOW_OPS_REPO_URL`.
- Browser-bridge live inspection is now optional; exports/pasted tables/
  screenshots are the default data path.
- Optimizer profile file renamed to `APPFLOW_OPTIMIZER.md` (legacy
  `KIMI_ADS_OPTIMIZER.md` still read for backward compatibility).

## 2.2.0 — 2026-07-20

### Desktop install target

- Added a desktop-app target to `install.sh` / `install.ps1` (and the
  uninstallers): installs the bundle into the desktop app's skill
  directory (`~/Library/Application Support/kimi-desktop/daimon-share/daimon/skills`
  on macOS, `%APPDATA%\kimi-desktop\daimon-share\daimon\skills` on Windows,
  overridable via `KIMI_WORK_HOME` or `--skill-dir`). Previously only
  the agent CLI (`~/.appflow/skills`) was covered, so the desktop app never saw
  the skills.

### Release plumbing

- `privacy_doctor.py` gained `--waive KIND[,KIND...]`: waived finding kinds
  stay in the report as INFO with `waived=true` but no longer fail the audit.
  The release gate waives the pre-migration identity findings (personal
  email, local hostname) and historical `.pyc` files accepted by the repo
  owner; real secret/private-data kinds still fail.
- Fixed the release gate's annotated-tag check to re-fetch the real tag
  object (actions/checkout re-points the local tag ref at the commit).
- Fixed `scripts/ci/*.py` console output on Windows (forced UTF-8; the
  check markers crashed the cp1252 console).
- Bumped dev pytest to >=9.0.3 (PYSEC-2026-1845) and made the top-level
  scripts mypy override tolerate third-party stub drift.

## 2.1.0 — 2026-07-20

### Playwright removal and WebBridge-only browser work

- Removed Playwright entirely: deleted `scripts/capture_screenshot.py` and
  `scripts/analyze_landing.py`. All browser work now goes through the assistant
  WebBridge in the user's real, fully visible logged-in browser; the bundle
  ships no headless browser tooling.
- Reworded the Live Dashboard Tool Gate in `skills/appflow/SKILL.md` and the
  `webbridge-live-audit.md` / `orchestrator.md` references (plus the `ads/`
  mirror) to state the WebBridge-only rule without referencing the deleted
  scripts.
- Added a 10 MB hard cap on `scripts/fetch_page.py` response bodies so a
  hostile or misconfigured server cannot exhaust memory.

### Skill prompts and packaging

- Added Chinese trigger phrases across all sub-skill descriptions so
  natural-language routing works in Chinese as well as English.
- Deduplicated the template-adapter guidance shared by `ads-ops` and
  `ads-report`; `ads-report` now owns it.
- Added plugin-layout fallback chains for agent persona briefs and scripts so
  skills resolve correctly from both manual and plugin installs.

### CI and release hardening

- Extracted inline `python -c` assertions from `ci.yml` into
  `scripts/ci/check_install_layout.py`, `check_uac_decide_output.py`,
  `check_uac_policies.py`, and `check_numeric_cap.py`; the installer smoke now
  verifies the installed layout through `check_install_layout.py`.
- Added `shellcheck` (installer scripts) and `pip-audit` (runtime and
  development dependencies) jobs, and SHA-pinned all GitHub Actions.

### UAC core modularization

- Split the UAC modules under `scripts/kimi_ads/uac/` into focused submodules
  with facade re-exports, so existing imports keep working.
- Extended mypy coverage from `scripts/kimi_ads/uac` to the top-level scripts
  via pyproject overrides, and wired the new check into CI.

## 2.0.0 — 2026-07-20

### Migration to the agent CLI

- Migrated the skill bundle from OpenAI Codex CLI to the agent CLI; the product
  is now AppFlow Ops and the new repository home is
  `github.com/taotao135791-bit/appflow-ops`.
- Changed the default install target to `kimi`: skills now install to
  `~/.appflow/skills` (honoring `$KIMI_CODE_HOME`), and the agent persona
  briefs ship inside the main skill at `~/.appflow/skills/appflow/agents`,
  dispatched to the assistant's built-in `coder` subagent.
- Replaced Computer Use with WebBridge (Chrome/Edge extension plus local
  daemon driving the user's real logged-in browser) for logged-in ad-dashboard
  inspection; public landing-page fetches still use `scripts/fetch_page.py`
  and `scripts/capture_screenshot.py`.
- Renamed the Python package `codex_ads` to `kimi_ads`, the repository URL
  environment variable to `KIMI_ADS_REPO_URL`, and the optimizer profile files
  to `APPFLOW_OPTIMIZER.md` / `.appflow-ops-optimizer.md`.
- Replaced `.codex-plugin/plugin.json` with the root `kimi.plugin.json`
  (`"skills": "./skills/"`), installable via
  `/plugins install https://github.com/taotao135791-bit/appflow-ops`.
- Renamed the project instruction file `CODEX.md` to `AGENTS.md`, which the assistant
  reads as the project instruction file.

### Compatibility and release status

- Routing shorthand (`/appflow audit`, `/appflow uac`, ...) is unchanged and can also
  be reached through the `/skill:appflow` invocation; all skill, ledger, replay,
  and workspace contracts from 1.9.x remain readable.
- The `v2.0.0` tag and GitHub Release were published together with this
  entry; 2.1.0 is now the current stable pin.

## 1.9.2 — 2026-07-14

### Numeric Safety Guardrails and Release Stabilization

- Added versioned normal-change caps for tCPA, tROAS, and daily budget in both
  directions. The bundled `uac-numeric-policy-v1` uses a 20% heuristic default,
  while the final value must still satisfy account evidence, business bounds,
  permissions, and the read-only confirmation contract.
- Added staged optimization output for candidates beyond the active cap. Only
  stage one is immediately proposed; every later stage requires fresh mature
  evidence and is never executed automatically.
- Added strict default, project, and private Workspace policy loading for
  calibratable numeric and signal heuristics, with version chaining, schema and
  runtime validation, effective-policy provenance, and a zero-change fallback
  when a bundled numeric default is unavailable.
- Separated `NORMAL_OPTIMIZATION`, `STAGED_OPTIMIZATION`, confirmed
  `OPERATIONAL_CORRECTION`, and non-attributable `EMERGENCY_INTERVENTION` so an
  ordinary scale action cannot use an incident-response exception.
- Added the human-reviewed `evaluation.yaml.numeric_evaluation` Replay contract
  and direction, median magnitude error, policy-cap, aggressive/conservative,
  rollback, staged-plan, and correct-no-action aggregates. Replay never changes
  a policy automatically.
- Removed one exact historical synthetic refresh-token fixture false positive
  with a digest-only allowlist, without weakening detection for real tokens.
  The current tree passes its redacted scan, while legacy identity metadata and
  tracked bytecode still block the `v1.9.2` tag and GitHub Release. No history
  rewrite, tag, or Release is claimed by this entry.

### Deterministic Numeric Quick Decisions

- Added deterministic derivation for maturity, multi-day budget delivery,
  event-volume stability, target constraints, value readiness, creative
  quality, candidate events, and campaign-split feasibility.
- Added bounded tCPA, tROAS, and daily-budget candidates based on supplied
  account evidence and explicit business limits, with conservative,
  recommended, and aggressive views where the evidence supports them.
- Added fail-closed numeric safety gates for immature or unreliable data,
  recent changes, one-day volatility, missing business limits, restricted
  permissions, and ordinary multi-variable changes.
- Kept AC2.0/AC2.5/AC3.0 as campaign-level labels rather than bid values, and
  kept every numeric decision read-only with evidence, review, and rollback
  fields visible to the operator.
- Added an anonymous numeric Quick Decision example, extended schema and Doctor
  coverage, and cross-platform installed-package smoke tests for the numeric
  modules and deterministic output.
- Added private numeric Replay calibration for direction, magnitude, unsafe
  recommendations, correct no-action, rollback, acceptance, and confounding;
  excluded unexecuted, immature, or confounded cases from invalid denominators.
- Made compact cards expose per-Campaign split budgets, missing candidate
  targets, hard business-boundary corrections, localized data gaps, and
  Campaign-level rollback without enabling any account or ledger write.

### Compatibility and release status

- Existing `decide`, `analyze`, Workspace, Report, Experiment, Replay, and
  Ledger 1.0/1.1 paths remain compatible; legacy caller-supplied numeric hints
  cannot bypass the new evidence and permission gates.
- This entry prepares `v1.9.2`; it does not claim that a remote tag or GitHub
  Release exists. The known full-history privacy block still prohibits tags and
  releases even when the current tree and ordinary CI pass.

## 1.9.1 — 2026-07-13

### Quick Ops and Campaign Level Decision Mode

- Added a read-only `decide` entry that returns one compact campaign operation
  card instead of a full report or automatic experiment.
- Added configurable AC2.0/AC2.5/AC3.0 terminology resolution with explicit
  protection against treating internal level labels as tCPA/tROAS numbers.
- Added deterministic keep, create, parallel, move, wait, and rollback gates
  for AC2.0 → AC2.5 and AC2.5 → AC3.0 decisions.
- Added strict payment/value, currency, deduplication, refund/subscription,
  amount-reconciliation, delay, volume, stability, and split-capacity checks
  before AC3.0 admission.
- Added same-level campaign, creative maturity/value, bid/budget separation,
  permission transformation, and operational-intervention classification.
- Added a private Workspace output, standalone Quick Decision schema, synthetic
  input example, progressive-disclosure Skill reference, and 42-scenario
  no-model behavior fixture.

### Compatibility and release status

- Existing `analyze`, Doctor, normalization, Report, Experiment, Ledger 1.0/1.1,
  Workspace, and Replay contracts remain compatible; Quick Decision never
  appends an experiment or edits Google Ads.
- This entry prepares `v1.9.1`; it does not claim that a remote tag or GitHub
  Release exists. The known full-history privacy block must be cleared before
  any tag or release is created.

## 1.9.0 — 2026-07-13

### Productization, Release and Real-World Validation

- Added a private, cross-platform UAC workspace with natural-language Agent
  workflow guidance while preserving every legacy path and CLI command.
- Made normalization, Doctor, analysis, reports, experiment drafts, and replays
  work together without requiring operators to author schemas by hand.
- Upgraded historical replay to a preferred six-stage evidence trail while
  retaining the legacy five-file contract and separating confounded outcomes.
- Expanded redacted privacy checks for advertising identifiers, API/OAuth/MMP
  credentials, local workspaces, environment files, and unsafe public replays.
- Defined the real UAC package coverage, typing, schema, compatibility,
  workspace, installer, reporting, and release-history gates in CI.
- Documented platform maturity honestly: UAC is deterministic; other platform
  skills remain structured Agent workflows or advisory support.

### Compatibility and release status

- Ledger schemas `1.0` and `1.1`, the historical UAC entry point, legacy replay
  cases, and direct file-based commands remain supported.
- This entry prepares `v1.9.0`; it does not claim that a remote tag or GitHub
  Release already exists. Publishing still requires the release checklist and
  a clean full-history privacy gate.

## 1.8.3 — 2026-07-13

### Stabilization and Real-World Validation Foundation

- Split the deterministic UAC engine into testable internal modules while
  preserving the existing entry point, CLI commands, output fields, and report.
- Added a read-only project Doctor, explicit ledger schema migration,
  lightweight input normalization, and anonymized historical replay metrics.
- Established a canonical Ads router with a deterministic mirror sync check and
  introduced lightweight knowledge-freshness metadata and diagnostics.
- Extended CI with typing, schema migration, Doctor, normalization, replay,
  router-sync, installed-package, and cross-platform compatibility checks.
- Added fixed-version release preparation, rollback guidance, and clearer
  documentation of deterministic guarantees, Agent inference, and limitations.

### Privacy

- Added repository safeguards for private replay data and future generated
  caches. Public examples remain anonymous and contain no live account data.

## 1.8.2 — 2026-07-13

### CI Reliability

- Added the `requests` runtime package to the development test environment so
  redirect and SSRF regression tests run in clean GitHub Actions workers.

## 1.8.1 — 2026-07-13

### UAC Safety Hardening

- Enforced ledger status, approval, execution, review-snapshot, maturity,
  guardrail, confounder, result, and learning consistency.
- Added deep-goal measurement completeness checks for event definitions,
  payment/trial/refund distinctions, attribution windows, and OS differences.
- Normalized operator-friendly goal names while preserving their raw values.
- Prevented unexecuted proposals from publishing learnings and blocked CLI
  outputs from overwriting source inputs or experiment ledgers.
- Added automatic single-ledger discovery, duplicate-ID prevention, and an
  auditable `cancel-proposal` transition for declined unexecuted proposals.
- Added fail-closed UAC scope, date-window, segmentation, signal, and evidence
  validation plus safe investigation-only degradation for incomplete policies.
- Required terminal metrics, evidence quality, mutually consistent result and
  decision outcomes, and an explicit next action before publishing learnings.
- Made the full ledger scaffold safely valid outside the active experiment
  array and aligned the offline JSON Schema with runtime validation.

## 1.8.0 — 2026-07-13

### UAC Experiment Loop

- Added the dedicated `ads-google-app` route for Google App campaigns/UAC.
- Added deterministic measurement, learning-eligibility, optimization-
  feasibility, permission, and single-variable experiment decisions.
- Added a local `ADS-EXPERIMENTS` ledger contract with minimal, full, and
  worked examples plus JSON Schema validation.
- Added structured UAC analysis and Markdown report generation from one source
  of truth.
- Added experiment readback for maturity, low volume, guardrails, concurrent
  changes, and win/loss/inconclusive outcomes.
- Hardened permission blocking, conversion-volume maturity, offline schema
  validation, atomic ledger writes, malformed-input handling, and completed
  experiment learning readback.
- Added behavior fixtures for common limited-permission UAC scenarios.
- Added cross-platform CI, lint, schema, installer, fixture-replay, and report
  smoke checks.

### Compatibility

- Existing routes, report tools, read-only defaults, and other ad-platform
  skills remain available.
- The new Python helper is optional. YAML input uses the lightweight PyYAML
  dependency already used by the development harness.
- Generated experiments remain unapproved proposals until a human confirms an
  exact platform edit.
