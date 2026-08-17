"""Platform adapters: thin, projection-only bridges between non-Google
platforms and AppFlow Core (docs/appflow-core.md).

Every adapter:

- owns ONE platform's hypothesis families (never the reasoning loop — the
  Reasoning Contract is canonical and shared);
- projects sparse observation facts for future reasoning through a COMMON
  envelope plus PLATFORM-SPECIFIC keys (never a shared mega-allowlist,
  never raw exports, account/ad IDs, or full creative text);
- declares its supported action vocabulary (shared decision classes +
  platform subtype hints);
- leaves decisions to the shared DECISION_CLASSES + StateSession.

No adapter recomputes diagnosis, policy, maturity, or measurement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .account_state import DECISION_CLASSES

# ── shared decision classes (all platforms) ──────────────────────────────

SHARED_ACTIONS = DECISION_CLASSES

# ── hypothesis families (platform-specific, shared reasoning loop) ───────

META_HYPOTHESES = (
    "creative_fatigue",
    "auction_pressure",
    "audience_saturation",
    "placement_mix",
    "learning_state",
    "budget_constraint",
    "bid_cost_cap_constraint",
    "delivery_fragmentation",
    "funnel_degradation",
    "measurement",
    "recent_operator_changes",
)

TIKTOK_HYPOTHESES = (
    "creative_delivery_decay",
    "creative_freshness",
    "auction",
    "audience",
    "budget",
    "bid",
    "delivery",
    "click_to_install_degradation",
    "install_to_deep_event_degradation",
    "measurement",
    "recent_changes",
)

CREATIVE_HYPOTHESES = (
    "fatigue",
    "audience_shift",
    "delivery_shift",
    "bid_budget_interference",
    "funnel_change",
    "measurement_issue",
)

CROSS_PLATFORM_HYPOTHESES = (
    "shared_funnel_degradation",
    "product_or_store_issue",
    "measurement_conflict",
    "market_wide_shift",
    "coincidence",
)

# ── metric projection ────────────────────────────────────────────────────

# Truly common envelope: every platform may carry these.
_COMMON_METRIC_KEYS = (
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "cpm",
    "installs",
    "registrations",
    "purchases",
    "payments",
    # v3.6.2: canonical outcome volume is common envelope — KPI-matched
    # scale eligibility (generic CPA → conversions) needs it on every
    # platform, not only Google.
    "conversions",
    "cpi",
    "cpa",
    # v3.6.0: KPI targets are common envelope — action eligibility
    # (scale decisions) consumes them on every platform, not only Google.
    "target_cpa",
    "target_cpi",
    "target_roas",
    "roas",
    # v3.6.2: KPI-aligned eligibility — the full primary-KPI envelope
    # (declaration + family targets/actuals + revenue for ROAS) is common
    # on every platform: the correct KPI, not a hardcoded CPA-first
    # precedence, drives target/actual comparison and outcome volume.
    "primary_kpi",
    "optimization_goal",
    "conversion_event",
    "target_pay_cpa",
    "target_registration_cpa",
    "target_purchase_cpa",
    "pay_cpa",
    "registration_cpa",
    "purchase_cpa",
    "revenue",
    # v3.6.0: recent-change confounders are common envelope — a declared
    # recent budget/bid change gates scale eligibility on every platform.
    "recent_budget_change",
    "recent_bid_change",
    "budget",
    "daily_budget",
    "measurement_state",
    "maturity_state",
    # v3.6.1: a reporting anomaly (event loss / tracking break /
    # platform-vs-source discrepancy) is REAL measurement evidence —
    # common envelope on every platform.
    "reporting_anomaly",
    # v3.6.4: post-change window outcome count — how many KPI-matched
    # outcomes were observed SINCE the last material Change. Lifetime
    # totals never prove post-change readiness (action readiness uses
    # this, not the cumulative outcome).
    "window_outcomes",
    # v3.5.2: rate fields participate in current-vs-history trend
    # derivation (same platform, same metric family).
    "install_rate",
    "registration_rate",
    "pay_rate",
    # v3.5.3/4: comparability provenance — same entity scope is required
    # for derived trends; entity_key is a workspace-local OPAQUE
    # identifier (raw external campaign/ad IDs are never persisted —
    # privacy contract).
    "entity_level",
    "entity_key",
    "aggregate_scope",
    "breakdown_scope",
    # v3.6.6: outcome count semantics — a number is not automatically a
    # cumulative counter. ``count_mode`` (cumulative | interval | unknown)
    # declares the shared semantic; per-metric ``<metric>_count_mode``
    # overrides for observations whose counters have different periods.
    # Missing semantics are treated as unknown, never assumed cumulative.
    "count_mode",
    "payments_count_mode",
    "installs_count_mode",
    "registrations_count_mode",
    "purchases_count_mode",
    "conversions_count_mode",
    # Decision Intelligence evidence bridge (v3.5.1): explicit trend
    # strings, numeric relative movement, and boolean operational facts
    # pass through observation projection so raw evidence can reach the
    # DI signal layer. Absent fields stay absent (never invented).
    "ctr_trend",
    "ctr_change_pct",
    "cpm_trend",
    "cpm_change_pct",
    "cvr_trend",
    "cvr_change_pct",
    "frequency_trend",
    "frequency_change_pct",
    "click_volume_trend",
    "click_volume_change_pct",
    "install_rate_trend",
    "install_rate_change_pct",
    "registration_rate_trend",
    "registration_rate_change_pct",
    "pay_rate_trend",
    "pay_rate_change_pct",
    "old_creative_worse",
    "new_creative_also_dropping",
    "multi_creative_impacted",
    "only_one_creative_declines",
    # v3.6.5: creative-age evidence is a real optimizer fact ("I have
    # creative age data") — common envelope so the fatigue hypothesis's
    # required evidence can be satisfied from observations.
    "creative_age_data",
    "reach_growth_slowing",
    "delivery_concentrated",
    "audience_expansion",
    "delivery_mix_shifted",
    "learning_reset",
    "recent_budget_change",
    "recent_bid_change",
    "budget_utilization_high",
    "spend_hit_cap",
    "store_loading_issue",
    "downstream_conversion_down",
    "traffic_quality_signal",
    "click_quality_signal",
    "no_recent_change",
)

# Platform-specific keys: preserved ONLY by the owning platform's adapter.
META_SPECIFIC_KEYS = (
    "frequency",
    "purchase_cpa",
    "cost_per_result",
    "learning_state",
    "delivery_state",
    "bid_strategy",
    "cost_cap",
    "placement_mix",
    "audience_state",
    "creative_age",
    "click_to_install_rate",
    "install_to_purchase_rate",
)

TIKTOK_SPECIFIC_KEYS = (
    "creative_delivery_state",
    "creative_age",
    "click_to_install_rate",
    "install_to_registration_rate",
    "install_to_purchase_rate",
    "cost_per_result",
    "bid",
    "delivery_state",
)

CREATIVE_SPECIFIC_KEYS = (
    "creative_id_local",
    "creative_age_bucket",
    "frequency",
    "delivery_change",
    "spend_share",
    "conversion_rate",
    "downstream_conversion",
    "recent_budget_change",
    "recent_bid_change",
    "click_to_install_rate",
    "install_to_purchase_rate",
)

# Google safe projection: the deterministic UAC path owns Google analysis;
# this thin adapter only allows the common envelope for operational runs.
GOOGLE_SPECIFIC_KEYS = (
    "target_cpa",
    "daily_budget",
    "cvr",
    "conversions",
    "impressions",
    "clicks",
)

# Generic adapter: explicit allowlist ONLY. Unknown platforms must opt into
# this adapter; raw passthrough never happens.
GENERIC_SPECIFIC_KEYS = ()

_FUNNEL_KEYS = (
    "click_to_install_rate",
    "install_to_registration_rate",
    "registration_to_purchase_rate",
    "install_to_purchase_rate",
)


@dataclass(frozen=True)
class PlatformAdapter:
    """Thin contract: one platform's projection + hypotheses + actions."""

    platform: str
    hypothesis_families: tuple[str, ...]
    specific_keys: tuple[str, ...] = ()
    actions: tuple[str, ...] = SHARED_ACTIONS
    action_subtypes: Mapping[str, tuple[str, ...]] | None = None

    def project_observation(self, metrics: Mapping[str, Any]) -> dict[str, Any]:
        """Project one structured metrics mapping into sparse observation
        facts: common envelope + THIS platform's specific keys. Missing keys
        are omitted; unknown raw fields never pass; identity and raw text
        never pass."""
        return {
            key: metrics[key]
            for key in (*_COMMON_METRIC_KEYS, *self.specific_keys)
            if key in metrics and metrics[key] is not None
        }

    def project_funnel(self, metrics: Mapping[str, Any]) -> dict[str, Any]:
        """Project funnel fields that exist in the input (sparse)."""
        return {
            key: metrics[key]
            for key in _FUNNEL_KEYS
            if key in metrics and metrics[key] is not None
        }

    def supported_actions(self) -> tuple[str, ...]:
        return self.actions


META = PlatformAdapter(
    platform="meta",
    hypothesis_families=META_HYPOTHESES,
    specific_keys=META_SPECIFIC_KEYS,
    action_subtypes={
        "replace": ("replace_creative",),
        "decrease": ("change_bid", "change_budget"),
    },
)
TIKTOK = PlatformAdapter(
    platform="tiktok",
    hypothesis_families=TIKTOK_HYPOTHESES,
    specific_keys=TIKTOK_SPECIFIC_KEYS,
    action_subtypes={"decrease": ("change_bid", "change_budget")},
)
CREATIVE = PlatformAdapter(
    platform="creative",
    hypothesis_families=CREATIVE_HYPOTHESES,
    specific_keys=CREATIVE_SPECIFIC_KEYS,
    actions=(
        "keep",
        "increase",
        "decrease",
        "pause",
        "replace",
        "retest",
        "wait",
        "observe",
        "investigate",
    ),
    action_subtypes={"replace": ("replace_creative",)},
)
GOOGLE = PlatformAdapter(
    platform="google_ads",
    hypothesis_families=(),
    specific_keys=GOOGLE_SPECIFIC_KEYS,
)
GENERIC = PlatformAdapter(
    platform="generic",
    hypothesis_families=(),
    specific_keys=GENERIC_SPECIFIC_KEYS,
)

PLATFORM_ADAPTERS: Mapping[str, PlatformAdapter] = {
    META.platform: META,
    TIKTOK.platform: TIKTOK,
    CREATIVE.platform: CREATIVE,
    GOOGLE.platform: GOOGLE,
    GENERIC.platform: GENERIC,
}


def adapter_for(platform: str) -> PlatformAdapter | None:
    return PLATFORM_ADAPTERS.get(platform)
