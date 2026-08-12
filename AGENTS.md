# AppFlow Ops Project Notes

AppFlow Ops is a local skill bundle for overseas app-promotion agency
operations: paid media audits, UAC experiment loops, funnel diagnosis
dashboards, creative review, PPC calculators, attribution checks, client
reporting, and rapid response to urgent client demands.

Its core reasoning principle is Diverge → Verify → Eliminate → Rank →
Converge (see README): users state business problems, AppFlow decides how to
investigate them; explore broadly internally, answer concisely externally.

## Non-negotiable design principles

- **No global business memory.** Every persistent business state must have
  an explicit workspace owner (`docs/account-state.md`). Never create a
  global index, global cache, cross-client database, or cross-workspace
  vector store holding business data.
- **One workspace = one state store.** State lives physically under the
  workspace root (`state/`); all state access is workspace-bound through
  `RunContext`. Cross-workspace reads/writes/references are denied by
  default; workspace A's history never becomes workspace B's context.
- **State is written through the runtime API only.** Agent workflows use
  `StateSession` (record_observation / record_decision /
  record_confirmed_change / record_outcome); never write state files
  directly. A recommendation alone never records a Change; outcomes need
  later evidence; decisions carry real provenance (origin, not a hardcoded
  deterministic claim).

## Layout

- `skills/appflow/SKILL.md`: main `/appflow` router skill (question
  discipline, client isolation, routing table).
- `appflow/SKILL.md`: byte-for-byte legacy mirror of the router, kept in sync
  by `scripts/sync_skill_layout.py`.
- `skills/ads-*`: focused sub-skills for app platforms (Google, Meta,
  TikTok, Apple) and agency workflows.
- `skills/ads-google-app`: UAC feasibility, structured analysis, quick
  numeric decisions, and local experiment-ledger contracts.
- `agents/*.md`: reusable audit and creative persona briefs, installed inside
  the main skill at `agents/` and dispatched to the host's built-in subagent
  mechanism.
- `skills/appflow/references/*.md`: scoring, platform specs, compliance,
  benchmarks, client question discipline, and implementation references.
- `scripts/*.py`: local deterministic tools.
- `scripts/uac_experiment.py`: deterministic UAC CLI (workspace, normalize,
  doctor, analyze, decide, ledger review, replay, funnel-dashboard, state).
- `scripts/appflow_ops/uac/account_state.py` + `state_store.py`:
  workspace-scoped continuous account state (append-only events + derived
  current state; bounded retrieval; pending review).
- `scripts/funnel_dashboard.py`: standalone funnel dashboard entry point.
- `scripts/appflow_ops/uac/`: the typed deterministic engine package.
- `appflow.plugin.json`: plugin manifest (`"skills": "./skills/"`).
- `tests/`: pytest coverage for routing, scoring, check catalogs, isolation,
  and URL safety.

## Install

Default install target is host-agnostic (`~/.appflow/skills`):

```bash
bash install.sh
```

This installs skills to `~/.appflow/skills` and agent persona briefs to
`~/.appflow/skills/appflow/agents`. Host-specific targets: `--target=codex`,
`cursor`, `windsurf`, `gemini`, `goose`.

## Development

Run the test suite with:

```bash
pytest -q
ruff check scripts tests
mypy scripts/appflow_ops/uac
python3 scripts/sync_skill_layout.py --check
```
