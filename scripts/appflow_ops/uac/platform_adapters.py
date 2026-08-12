"""Platform adapters: thin, projection-only bridges between non-Google
platforms and AppFlow Core (docs/appflow-core.md).

Every adapter:

- owns ONE platform's hypothesis families (never the reasoning loop — the
  Reasoning Contract is canonical and shared);
- projects sparse observation facts for future reasoning (never raw
  exports, account/ad IDs, or full creative text);
- leaves decisions to the shared DECISION_CLASSES + StateSession; platform
  detail goes in the payload.

No adapter recomputes diagnosis, policy, maturity, or measurement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class PlatformAdapter:
    """Thin contract: one platform's projection + hypothesis families.

    Deliberately minimal — no framework. The shape is only frozen after at
    least two platforms actually reuse it.
    """

    platform: str
    hypothesis_families: tuple[str, ...]

    def project_observation(self, metrics: Mapping[str, Any]) -> dict[str, Any]:
        """Project one structured metrics mapping into sparse observation
        facts. Missing keys are omitted; identity and raw text never pass."""
        return _project_common_metrics(metrics)


# ── metric projection (shared shape, platform-specific fields stay) ──────

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
    "cpa",
    "cpi",
    "frequency",
    "budget",
    "daily_budget",
    "bid",
    "cost_cap",
    "measurement_state",
    "maturity_state",
    "learning_state",
    "delivery_state",
)

META = PlatformAdapter(
    platform="meta",
    hypothesis_families=META_HYPOTHESES,
)
TIKTOK = PlatformAdapter(
    platform="tiktok",
    hypothesis_families=TIKTOK_HYPOTHESES,
)
CREATIVE = PlatformAdapter(
    platform="creative",
    hypothesis_families=CREATIVE_HYPOTHESES,
)


def _project_common_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: metrics[key]
        for key in _COMMON_METRIC_KEYS
        if key in metrics and metrics[key] is not None
    }


def funnel_rates(metrics: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project one optional funnel structure: click→install, install→pay.

    Adapters only; the values come from the caller's structured evidence.
    """

    projected: dict[str, Any] = {}
    click_to_install = metrics.get("click_to_install_rate")
    if click_to_install is not None:
        projected["click_to_install_rate"] = click_to_install
    install_to_pay = metrics.get("install_to_pay_rate")
    if install_to_pay is not None:
        projected["install_to_pay_rate"] = install_to_pay
    return projected or None
