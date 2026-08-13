"""User-facing summary builder for Decision Intelligence (v3.5.5).

Produces the DEFAULT short answer — a few sentences, never the full
ranking table. Structure: conclusion, strongest evidence, material
exclusion/alternative, next action, review condition; when evidence is
insufficient the answer is honestly "先别动" plus the most needed data.

Diagnosis vs safety block (v3.5.5): a safety problem on one platform
never vetoes an independent diagnosis for another — the summary keeps
the ranked diagnosis AND names the platform whose data cannot be
judged yet ("Google 侧可以判断，Meta 侧暂不判断").
"""

from __future__ import annotations

from .result import DecisionIntelligenceResult

# Signal id → short Chinese phrase for user-facing evidence lines.
SIGNAL_LABELS: dict[str, str] = {
    "ctr_trend_down": "CTR 连续下降",
    "ctr_trend_stable": "CTR 基本稳定",
    "ctr_trend_up": "CTR 上升",
    "cpm_trend_up": "CPM 明显上涨",
    "cpm_trend_stable": "CPM 基本稳定",
    "cpm_trend_down": "CPM 下降",
    "delivery_mix_stable": "投放结构稳定",
    "cvr_trend_down": "CVR 下降",
    "cvr_trend_stable": "CVR 基本稳定",
    "frequency_trend_up": "频次上升",
    "frequency_trend_stable": "频次基本稳定",
    "click_volume_trend_stable": "点击量稳定",
    "click_volume_trend_down": "点击量下降",
    "no_recent_change": "近期无预算/出价变动",
    "install_rate_trend_down": "安装率下降",
    "install_rate_trend_stable": "安装率稳定",
    "registration_rate_trend_down": "注册率下降",
    "registration_rate_trend_stable": "注册率稳定",
    "pay_rate_trend_down": "付费率下降",
    "pay_rate_trend_stable": "付费率稳定",
    "old_creative_worse": "老素材比新素材衰减更快",
    "new_creative_also_dropping": "新素材也同步下跌",
    "multi_creative_impacted": "多素材同时受影响",
    "only_one_creative_declines": "只有单一素材下跌",
    "reach_growth_slowing": "触达增长放缓",
    "delivery_concentrated": "投放集中",
    "audience_expansion": "人群扩展",
    "delivery_mix_shifted": "投放结构发生变化",
    "learning_reset": "学习期重置",
    "recent_budget_change": "近期改过预算",
    "recent_bid_change": "近期改过出价",
    "budget_utilization_high": "预算利用率高",
    "spend_hit_cap": "花费触顶",
    "measurement_invalid": "数据/归因不可信",
    "maturity_insufficient": "样本成熟度不足",
    "store_loading_issue": "商店页加载异常",
    "downstream_conversion_down": "下游转化下降",
    "traffic_quality_signal": "流量质量异常",
    "click_quality_signal": "点击质量异常",
}

# Hypothesis id → short Chinese label for conclusions.
_HYPOTHESIS_LABELS: dict[str, str] = {
    "creative_fatigue": "素材疲劳",
    "creative_message_mismatch": "素材信息与受众错配",
    "creative_format_mismatch": "素材格式问题",
    "auction_pressure": "竞价压力",
    "delivery_mix_shift": "投放结构变化",
    "learning_or_relearning": "学习期波动",
    "audience_saturation": "人群饱和",
    "audience_quality_shift": "人群质量变化",
    "post_click_friction": "落地页转化摩擦",
    "conversion_funnel_degradation": "转化漏斗恶化",
    "measurement_instability": "数据/归因不稳定",
    "bid_constraint": "出价受限",
    "budget_constraint": "预算受限",
    "recent_budget_bid_interference": "近期预算/出价调整干扰",
    "hook_or_click_quality": "素材钩子/点击质量问题",
    "traffic_quality_shift": "流量质量变化",
    "click_to_install_friction": "点击到安装的转化摩擦",
    "store_page_friction": "商店页转化摩擦",
    "install_measurement_issue": "安装数据测量问题",
    "registration_friction": "注册环节摩擦",
    "pay_funnel_degradation": "付费漏斗恶化",
    "delivery_shift": "投放交付变化",
    "shared_product_funnel_issue": "共享产品/漏斗问题",
    "shared_measurement_issue": "共享测量问题",
    "platform_specific_independent_issues": "平台独立问题",
    "market_wide_event": "市场级事件",
}

_ACTION_LABELS: dict[str, str] = {
    "investigate": "先调查",
    "investigate_measurement": "先查数据/归因",
    "wait": "先观察",
    "observe": "保持观察",
    "replace": "替换最弱的素材",
    "retest": "小规模重测",
    "refresh_variant": "刷新变体",
    "increase": "小幅加量",
    "decrease": "小幅降量",
    "hold": "预算/出价不动",
    "keep": "保持现状",
    "pause": "暂停",
    "scale": "扩量",
}


def _label(signal_or_hypothesis: str) -> str:
    return SIGNAL_LABELS.get(
        signal_or_hypothesis,
        _HYPOTHESIS_LABELS.get(signal_or_hypothesis, signal_or_hypothesis),
    )


def summarize_decision_intelligence(result: DecisionIntelligenceResult) -> str:
    """Short default answer (a few sentences). Long ranking tables are
    only for debug/eval, never the product default."""
    lines: list[str] = []

    if result.convergence_status == "converged":
        # v3.5.3: the top evaluation carries platform attribution — the
        # answer says WHICH platform the conclusion applies to.
        if result.top_platform and result.top_platform != "cross_platform":
            lines.append(
                f"更像 {result.top_platform} 侧的{_label(result.top_hypothesis or '')}，"
                "先做最小动作。"
            )
        elif result.top_platform == "cross_platform":
            lines.append(
                f"更像两个媒体共同的{_label(result.top_hypothesis or '')}，先做最小动作。"
            )
        else:
            lines.append(f"更像{_label(result.top_hypothesis or '')}，先做最小动作。")
    elif (
        result.convergence_status == "investigate"
        and result.safety_block == "measurement_invalid"
    ):
        # v3.5.5: a safety block changes the action, never the ranked
        # diagnosis identity — keep BOTH the diagnosis and the block.
        if result.top_platform and result.top_platform != "cross_platform":
            lines.append(
                f"{result.top_platform} 侧更像{_label(result.top_hypothesis or '')}，"
                "但数据/归因不可信，先查 tracking 再下结论。"
            )
        elif result.top_platform == "cross_platform":
            lines.append(
                f"更可能是{_label(result.top_hypothesis or '')}，但现在还不能直接判定"
                "——measurement 不可信，会影响跨平台结论。"
            )
        else:
            lines.append(
                f"更像{_label(result.top_hypothesis or '')}，但数据/归因不可信，"
                "先查清楚再判断。"
            )
        if result.platform_warnings:
            names = "、".join(result.platform_warnings)
            lines.append(f"{names} 的数据暂不可信，那边先不下结论。")
    elif result.convergence_status == "investigate":
        lines.append("候选原因并存，先别下结论——补充证据再收敛。")
    elif result.convergence_status == "wait" and result.safety_block:
        lines.append("样本/数据成熟度不足，先别调，观察一个完整窗口。")
    elif result.convergence_status == "wait":
        lines.append("现在证据还不够，先别调。")
    else:
        lines.append("证据不足以收敛到单一原因，先保持观察。")

    # Strongest evidence: signals supporting the top hypothesis.
    evidence_lines: list[str] = []
    for ev in result.evaluations:
        if ev.hypothesis.id != result.top_hypothesis:
            continue
        for signal_id in ev.supporting:
            if signal_id in SIGNAL_LABELS:
                evidence_lines.append(f"- {SIGNAL_LABELS[signal_id]}")
        break
    if evidence_lines:
        lines.append("\n依据：")
        lines.extend(evidence_lines[:4])

    if result.material_alternatives:
        names = "、".join(_label(h) for h in result.material_alternatives)
        lines.append(f"候选原因并存（{names}），不能仅凭分差收敛。")
        if result.next_discriminating_evidence:
            needed = "、".join(
                _label(e) for e in result.next_discriminating_evidence[:2]
            )
            lines.append(f"最需要补的是：{needed}。")

    # Material exclusions (weak evidence vs excluded).
    excluded = [
        _label(ev.hypothesis.id) for ev in result.evaluations if ev.status == "excluded"
    ]
    if excluded:
        lines.append(f"已排除：{'、'.join(excluded[:2])}。")

    action = result.recommended_action
    if action is not None:
        lines.append(f"下一步：{_ACTION_LABELS.get(action, action)}。")
    if result.review_condition:
        lines.append(result.review_condition)

    return "\n".join(lines)
