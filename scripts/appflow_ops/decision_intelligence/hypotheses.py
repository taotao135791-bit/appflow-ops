"""Structured hypothesis specifications for Ads Decision Intelligence.

A HypothesisSpec is business semantics: what evidence supports/weakens a
hypothesis, what excludes it, what actions follow. It is NOT a model
reasoning log — no chain-of-thought is stored or exposed; evaluation
outputs only supported-by / weakened-by / missing / status / rank.
"""

from __future__ import annotations

from dataclasses import dataclass

# Signal vocabulary (evidence.py extracts these from metrics/context).
# A signal id is present (True) when the phenomenon is observed.
SIGNAL_IDS = (
    "ctr_trend_down",
    "ctr_trend_stable",
    "ctr_trend_up",
    "cpm_trend_up",
    "cpm_trend_stable",
    "cpm_trend_down",
    "delivery_mix_stable",
    "cvr_trend_down",
    "cvr_trend_stable",
    "frequency_trend_up",
    "frequency_trend_stable",
    "click_volume_trend_stable",
    "click_volume_trend_down",
    "no_recent_change",
    "install_rate_trend_down",
    "install_rate_trend_stable",
    "registration_rate_trend_down",
    "registration_rate_trend_stable",
    "pay_rate_trend_down",
    "pay_rate_trend_stable",
    "old_creative_worse",
    "new_creative_also_dropping",
    "multi_creative_impacted",
    "only_one_creative_declines",
    "reach_growth_slowing",
    "delivery_concentrated",
    "audience_expansion",
    "delivery_mix_shifted",
    "learning_reset",
    "recent_budget_change",
    "recent_bid_change",
    "budget_utilization_high",
    "spend_hit_cap",
    "measurement_invalid",
    "maturity_insufficient",
    "store_loading_issue",
    "downstream_conversion_down",
    "traffic_quality_signal",
    "click_quality_signal",
)


@dataclass(frozen=True)
class HypothesisSpec:
    """One candidate cause with its evidence semantics."""

    id: str
    label: str
    domain: str
    applicable_platforms: tuple[str, ...]  # ("*",) = all media platforms
    # Signal ids that, when present, support this hypothesis (+2 each).
    supporting_signals: tuple[str, ...] = ()
    # Signal ids that, when present, weaken this hypothesis (-2 each).
    contradicting_signals: tuple[str, ...] = ()
    # Evidence that materially matters; when missing, confidence is capped.
    required_evidence: tuple[str, ...] = ()
    # Signal ids that, when present, EXCLUDE this hypothesis outright.
    exclusion_conditions: tuple[str, ...] = ()
    # Candidate actions, ordered smallest-first for convergence.
    possible_actions: tuple[str, ...] = ()


# ── Meta ─────────────────────────────────────────────────────────────────

META_HYPOTHESES: tuple[HypothesisSpec, ...] = (
    HypothesisSpec(
        id="creative_fatigue",
        label="素材疲劳",
        domain="creative",
        applicable_platforms=("meta", "tiktok"),
        supporting_signals=(
            "ctr_trend_down",
            "old_creative_worse",
            "frequency_trend_up",
        ),
        contradicting_signals=("ctr_trend_stable", "new_creative_also_dropping"),
        required_evidence=("ctr_trend", "creative_age_data"),
        exclusion_conditions=("recent_budget_change", "recent_bid_change"),
        possible_actions=("replace", "retest", "observe"),
    ),
    HypothesisSpec(
        id="creative_message_mismatch",
        label="素材信息与受众错配",
        domain="creative",
        applicable_platforms=("meta", "tiktok", "google_ads"),
        supporting_signals=(
            "ctr_trend_down",
            "multi_creative_impacted",
            "cpm_trend_up",
        ),
        contradicting_signals=("ctr_trend_stable",),
        required_evidence=("ctr_trend", "creative_mix"),
        exclusion_conditions=("recent_budget_change", "recent_bid_change"),
        possible_actions=("replace", "retest"),
    ),
    HypothesisSpec(
        id="creative_format_mismatch",
        label="素材形式与投放位置错配",
        domain="creative",
        applicable_platforms=("meta", "tiktok"),
        supporting_signals=("ctr_trend_down", "delivery_mix_shifted"),
        required_evidence=("placement_data",),
        possible_actions=("observe", "retest"),
    ),
    HypothesisSpec(
        id="auction_pressure",
        label="竞价压力上升",
        domain="auction",
        applicable_platforms=("meta", "tiktok", "google_ads"),
        supporting_signals=(
            "cpm_trend_up",
            "ctr_trend_stable",
            "multi_creative_impacted",
        ),
        contradicting_signals=("cpm_trend_stable",),
        required_evidence=("cpm_trend",),
        possible_actions=("wait", "observe"),
    ),
    HypothesisSpec(
        id="delivery_mix_shift",
        label="投放结构/位置迁移",
        domain="delivery",
        applicable_platforms=("meta", "tiktok"),
        supporting_signals=("delivery_mix_shifted", "cpm_trend_up", "ctr_trend_down"),
        contradicting_signals=("delivery_mix_stable",),
        required_evidence=("delivery_breakdown",),
        possible_actions=("observe", "wait"),
    ),
    HypothesisSpec(
        id="learning_or_relearning",
        label="学习期/重新学习",
        domain="delivery",
        applicable_platforms=("meta", "tiktok"),
        supporting_signals=("learning_reset", "ctr_trend_down", "cpm_trend_up"),
        required_evidence=("recent_change", "maturity_state"),
        possible_actions=("wait", "observe"),
    ),
    HypothesisSpec(
        id="audience_saturation",
        label="受众饱和",
        domain="audience",
        applicable_platforms=("meta", "tiktok"),
        supporting_signals=(
            "frequency_trend_up",
            "reach_growth_slowing",
            "delivery_concentrated",
        ),
        contradicting_signals=("frequency_trend_stable", "audience_expansion"),
        required_evidence=("frequency_trend", "reach_trend"),
        possible_actions=("refresh_variant", "observe"),
    ),
    HypothesisSpec(
        id="audience_quality_shift",
        label="受众质量迁移",
        domain="audience",
        applicable_platforms=("meta", "tiktok"),
        supporting_signals=("cvr_trend_down", "ctr_trend_stable", "cpm_trend_up"),
        contradicting_signals=("cvr_trend_stable",),
        required_evidence=("cvr_trend",),
        possible_actions=("observe", "investigate"),
    ),
    HypothesisSpec(
        id="post_click_friction",
        label="点击后摩擦（落地页/APP 内）",
        domain="funnel",
        applicable_platforms=("*",),
        supporting_signals=(
            "cvr_trend_down",
            "ctr_trend_stable",
            "click_volume_trend_stable",
        ),
        contradicting_signals=("cvr_trend_stable",),
        required_evidence=("cvr_trend",),
        possible_actions=("investigate", "observe"),
    ),
    HypothesisSpec(
        id="conversion_funnel_degradation",
        label="转化漏斗整体恶化",
        domain="funnel",
        applicable_platforms=("*",),
        supporting_signals=(
            "cvr_trend_down",
            "multi_creative_impacted",
            "downstream_conversion_down",
        ),
        required_evidence=("cvr_trend", "downstream_data"),
        possible_actions=("investigate", "observe"),
    ),
    HypothesisSpec(
        id="measurement_instability",
        label="数据/归因不稳定",
        domain="measurement",
        applicable_platforms=("*",),
        supporting_signals=(
            "measurement_invalid",
            "cvr_trend_down",
            "ctr_trend_stable",
        ),
        required_evidence=("measurement_health",),
        possible_actions=("investigate_measurement", "wait"),
    ),
    HypothesisSpec(
        id="bid_constraint",
        label="出价受限",
        domain="bid_budget",
        applicable_platforms=("meta", "tiktok", "google_ads"),
        supporting_signals=(
            "cpm_trend_up",
            "delivery_concentrated",
            "budget_utilization_high",
        ),
        required_evidence=("cpm_trend", "delivery_state"),
        possible_actions=("increase", "wait"),
    ),
    HypothesisSpec(
        id="budget_constraint",
        label="预算受限",
        domain="bid_budget",
        applicable_platforms=("meta", "tiktok", "google_ads"),
        supporting_signals=(
            "budget_utilization_high",
            "spend_hit_cap",
            "delivery_concentrated",
        ),
        required_evidence=("budget_utilization",),
        possible_actions=("increase", "wait"),
    ),
    HypothesisSpec(
        id="recent_budget_bid_interference",
        label="近期预算/出价调整干扰",
        domain="bid_budget",
        applicable_platforms=("meta", "tiktok", "google_ads"),
        supporting_signals=(
            "recent_budget_change",
            "recent_bid_change",
            "ctr_trend_down",
            "delivery_mix_shifted",
        ),
        contradicting_signals=("no_recent_change",),
        required_evidence=("recent_change",),
        possible_actions=("wait", "observe"),
    ),
)

# ── TikTok ───────────────────────────────────────────────────────────────

TIKTOK_HYPOTHESES: tuple[HypothesisSpec, ...] = (
    HypothesisSpec(
        id="hook_or_click_quality",
        label="钩子/点击质量下降",
        domain="creative",
        applicable_platforms=("tiktok",),
        supporting_signals=("ctr_trend_down", "click_volume_trend_down"),
        contradicting_signals=("ctr_trend_stable",),
        required_evidence=("ctr_trend",),
        possible_actions=("replace", "retest", "observe"),
    ),
    HypothesisSpec(
        id="traffic_quality_shift",
        label="流量质量迁移",
        domain="delivery",
        applicable_platforms=("tiktok",),
        supporting_signals=(
            "traffic_quality_signal",
            "ctr_trend_stable",
            "install_rate_trend_down",
        ),
        contradicting_signals=("cvr_trend_stable",),
        required_evidence=("traffic_quality",),
        possible_actions=("observe", "investigate"),
    ),
    HypothesisSpec(
        id="click_to_install_friction",
        label="点击→安装摩擦",
        domain="funnel",
        applicable_platforms=("tiktok",),
        supporting_signals=(
            "click_volume_trend_stable",
            "install_rate_trend_down",
            "ctr_trend_stable",
        ),
        contradicting_signals=("install_rate_trend_stable",),
        required_evidence=("install_rate_trend",),
        possible_actions=("investigate", "observe"),
    ),
    HypothesisSpec(
        id="store_page_friction",
        label="商店页摩擦",
        domain="funnel",
        applicable_platforms=("tiktok",),
        supporting_signals=(
            "install_rate_trend_down",
            "store_loading_issue",
            "click_volume_trend_stable",
        ),
        required_evidence=("store_health",),
        possible_actions=("investigate", "observe"),
    ),
    HypothesisSpec(
        id="install_measurement_issue",
        label="安装数据/回传问题",
        domain="measurement",
        applicable_platforms=("tiktok",),
        supporting_signals=(
            "measurement_invalid",
            "install_rate_trend_down",
            "click_volume_trend_stable",
        ),
        required_evidence=("measurement_health",),
        possible_actions=("investigate_measurement", "wait"),
    ),
    HypothesisSpec(
        id="registration_friction",
        label="注册摩擦",
        domain="funnel",
        applicable_platforms=("tiktok",),
        supporting_signals=(
            "registration_rate_trend_down",
            "install_rate_trend_stable",
            "click_volume_trend_stable",
        ),
        required_evidence=("registration_rate_trend",),
        possible_actions=("investigate", "observe"),
    ),
    HypothesisSpec(
        id="pay_funnel_degradation",
        label="付费漏斗恶化",
        domain="funnel",
        applicable_platforms=("tiktok",),
        supporting_signals=(
            "pay_rate_trend_down",
            "install_rate_trend_stable",
            "registration_rate_trend_stable",
        ),
        contradicting_signals=("pay_rate_trend_stable",),
        required_evidence=("pay_rate_trend", "downstream_data"),
        possible_actions=("investigate", "observe"),
    ),
    HypothesisSpec(
        id="delivery_shift",
        label="投放迁移",
        domain="delivery",
        applicable_platforms=("tiktok",),
        supporting_signals=("delivery_mix_shifted", "cpm_trend_up", "ctr_trend_stable"),
        required_evidence=("delivery_breakdown",),
        possible_actions=("observe", "wait"),
    ),
)

# ── Cross-platform ───────────────────────────────────────────────────────

CROSS_PLATFORM_HYPOTHESES: tuple[HypothesisSpec, ...] = (
    HypothesisSpec(
        id="shared_product_funnel_issue",
        label="共享产品/漏斗问题",
        domain="funnel",
        applicable_platforms=("cross_platform",),
        supporting_signals=(
            "pay_rate_trend_down",
            "cvr_trend_down",
            "multi_creative_impacted",
            "downstream_conversion_down",
        ),
        contradicting_signals=("cvr_trend_stable",),
        required_evidence=("cross_platform_comparison", "measurement_health"),
        possible_actions=("investigate", "observe"),
    ),
    HypothesisSpec(
        id="shared_measurement_issue",
        label="共享数据/归因问题",
        domain="measurement",
        applicable_platforms=("cross_platform",),
        supporting_signals=(
            "measurement_invalid",
            "pay_rate_trend_down",
            "cvr_trend_down",
        ),
        required_evidence=("measurement_health",),
        possible_actions=("investigate_measurement", "wait"),
    ),
    HypothesisSpec(
        id="platform_specific_independent_issues",
        label="平台各自独立问题",
        domain="general",
        applicable_platforms=("cross_platform",),
        supporting_signals=("delivery_mix_shifted", "only_one_creative_declines"),
        contradicting_signals=("multi_creative_impacted",),
        required_evidence=("per_platform_comparison",),
        possible_actions=("observe", "investigate"),
    ),
    HypothesisSpec(
        id="market_wide_event",
        label="市场级事件",
        domain="delivery",
        applicable_platforms=("cross_platform",),
        supporting_signals=(
            "cpm_trend_up",
            "multi_creative_impacted",
            "ctr_trend_stable",
        ),
        contradicting_signals=("cpm_trend_stable",),
        required_evidence=("market_context",),
        possible_actions=("wait", "observe"),
    ),
)

# ── Registry ─────────────────────────────────────────────────────────────

ALL_HYPOTHESES: tuple[HypothesisSpec, ...] = (
    META_HYPOTHESES + TIKTOK_HYPOTHESES + CROSS_PLATFORM_HYPOTHESES
)

_HYPOTHESIS_BY_ID: dict[str, HypothesisSpec] = {
    spec.id: spec for spec in ALL_HYPOTHESES
}


def hypothesis_by_id(hypothesis_id: str) -> HypothesisSpec | None:
    return _HYPOTHESIS_BY_ID.get(hypothesis_id)


def build_hypothesis_set(
    *,
    platform_scope: tuple[str, ...] = (),
    domain: str | None = None,
    cross_platform: bool = False,
) -> tuple[HypothesisSpec, ...]:
    """Candidate set for a run: platform-appropriate hypotheses, optionally
    narrowed by the operational domain (``None``/``general`` = all
    applicable). Cross-platform runs add the cross-platform families.
    """
    if cross_platform or "cross_platform" in platform_scope:
        platform_key: str | None = "cross_platform"
    elif len(platform_scope) == 1:
        platform_key = platform_scope[0]
    else:
        platform_key = None
    candidates = [
        spec
        for spec in ALL_HYPOTHESES
        if (
            platform_key is None
            or platform_key in spec.applicable_platforms
            or "*" in spec.applicable_platforms
        )
    ]
    # ``domain`` is a routing/context hint — it does NOT narrow the
    # evaluation set: competing hypotheses from other domains must be
    # compared (auction vs fatigue; funnel vs creative).
    return tuple(candidates)
