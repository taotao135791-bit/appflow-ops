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
    "cpi",
    "cpa",
    "budget",
    "daily_budget",
    "measurement_state",
    "maturity_state",
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

PLATFORM_ADAPTERS: Mapping[str, PlatformAdapter] = {
    META.platform: META,
    TIKTOK.platform: TIKTOK,
    CREATIVE.platform: CREATIVE,
}


def adapter_for(platform: str) -> PlatformAdapter | None:
    return PLATFORM_ADAPTERS.get(platform)
