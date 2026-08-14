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
        # v3.6.0: Diagnosis != Action — a correct diagnosis does not make
        # its most obvious intervention eligible. Say it explicitly when a
        # scale action was blocked by eligibility.
        if result.action_eligibility == "not_eligible" and (
            result.recommended_action in ("hold", "wait")
        ):
            if result.top_hypothesis in ("budget_constraint", "bid_constraint"):
                lines.append(
                    f"{_label(result.top_hypothesis or '')}是真的，但现在不建议加量"
                    "——先把效率拉回目标附近、等近期调整稳定后再考虑扩。"
                )
            else:
                lines.append(
                    "诊断成立，但当前条件不允许执行最直接的加量动作，先保持现状。"
                )
        elif result.action_eligibility == "needs_more_evidence":
            if result.eligibility_reason == "thin_kpi_headroom":
                lines.append(
                    "先别加。虽然 CPA/成本刚好低于目标，但余量太小，而且样本还不够，"
                    "暂时不能证明扩量后还能守住成本。先继续积累转化，再看。"
                )
            elif result.eligibility_reason == "low_conversion_volume":
                lines.append(
                    "先别加。转化量还太少，现在的成本水平可能只是少数转化的偶然，"
                    "继续积累转化后再判断是否值得扩。"
                )
            elif result.eligibility_reason == "weak_sample":
                lines.append("先别加。样本量还不足以支撑扩量判断，先观察一个完整窗口。")
            elif result.eligibility_reason == "material_rival":
                lines.append(
                    "先别加。素材/漏斗还有未解决的候选问题，先把这些风险排除再考虑扩。"
                )
            # v3.6.2: positive-evidence reasons — unknown volume/safety and
            # KPI ambiguity defer scale instead of guessing.
            elif result.eligibility_reason == "missing_outcome_volume":
                lines.append(
                    "先别加。成本看起来有空间，但我还不知道这个成本是建立在多少个转化上的"
                    "——先确认有效转化量，再决定是否扩量。"
                )
            elif result.eligibility_reason == "measurement_unknown":
                lines.append(
                    "先别加。数据可靠性（measurement）还没确认，先确认回传/归因状态，"
                    "再判断这个成本是否可信。"
                )
            elif result.eligibility_reason == "maturity_unknown":
                lines.append(
                    "先别加。样本成熟度（maturity）还没确认，先确认数据成熟度再判断。"
                )
            elif result.eligibility_reason == "ambiguous_primary_kpi":
                lines.append(
                    "先别加。同时存在多个目标 KPI（比如 CPI 与 Pay CPA），当前不知道主目标"
                    "是哪个——先明确 primary KPI，再决定按哪个指标判断扩量。"
                )
            else:
                lines.append("缺 KPI/效率数据，暂时不能判断是否值得加量，先观察。")
        elif result.action_eligibility == "eligible" and result.top_hypothesis in (
            "budget_constraint",
            "bid_constraint",
        ):
            lines.append(
                "可以考虑小幅加。预算/出价已经受限，CPA 明显低于目标，转化量和数据"
                "稳定性都够——建议分阶段加，不要一次放太多。"
            )
            # v3.6.1: cross-platform isolation — the selected platform scales
            # on its own evidence; other platforms' warnings are not vetoes.
            if result.top_platform and result.platform_warnings:
                warning_names = "、".join(result.platform_warnings)
                lines.append(
                    f"{result.top_platform} 可以按自己的效率和样本做判断；"
                    f"{warning_names} 的问题不影响它，那边继续观察。"
                )
            # v3.6.2: parallel issues — supported independent problems on
            # OTHER platforms are explained, never treated as rivals that
            # block this platform's scale.
            if result.parallel_issues:
                issue_names = "、".join(_label(h) for h in result.parallel_issues[:2])
                if result.top_platform and result.top_platform != "cross_platform":
                    lines.append(
                        f"{result.top_platform} 可以单独考虑小幅扩量；"
                        f"{issue_names}是另一条独立问题，不应该把 {result.top_platform} 一起卡住——"
                        f"{result.top_platform} 按自己的效率和样本走，那边单独处理。"
                    )
                else:
                    lines.append(
                        f"同时存在独立问题（{issue_names}），但那是另一条问题，"
                        "不影响当前判断。"
                    )
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
        # v3.6.1: measurement problem first — never touch creative/budget
        # while the data itself is untrustworthy.
        lines.append(
            "先查 tracking，不建议现在根据成本去调素材或预算——先把数据可信度恢复。"
        )
    elif result.convergence_status == "investigate":
        lines.append("候选原因并存，先别下结论——补充证据再收敛。")
    elif result.convergence_status == "wait" and result.safety_block:
        lines.append("样本/数据成熟度不足，先别调，观察一个完整窗口。")
    elif result.convergence_status == "wait":
        # v3.6.2: explicit-trend tiny-sample case — a small CTR dip on a
        # tiny sample never justifies a swap; name the sample problem.
        if result.top_hypothesis in (
            "creative_fatigue",
            "creative_message_mismatch",
        ) and (
            result.evidence is not None
            and result.evidence.signal_strength.get("ctr_trend_down") == "weak"
        ):
            lines.append(
                "CTR 看起来在掉，但样本还太小，现在不足以判素材疲劳。"
                "先继续积累曝光，不建议因为这一小段波动马上换素材。"
            )
        else:
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
        # v3.6.0: metric deterioration is not measurement evidence — when
        # measurement is explicitly stable and the top is a funnel
        # diagnosis, say it directly instead of implying tracking issues.
        if (
            result.top_hypothesis
            in (
                "conversion_funnel_degradation",
                "post_click_friction",
                "pay_funnel_degradation",
                "shared_product_funnel_issue",
            )
            and result.safety_context.get("measurement_state") == "stable"
        ):
            lines.append("更像漏斗/转化链路问题，不像 tracking；measurement 当前正常。")
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
        # v3.6.0: fatigue + recent-change coexistence — never a reckless
        # full swap or budget cut; smallest useful action.
        if result.top_hypothesis == "creative_fatigue" and any(
            h == "recent_budget_bid_interference" for h in result.material_alternatives
        ):
            lines.append(
                "素材有疲劳迹象，但你刚调过预算/出价，delivery 也可能在重新分配——"
                "预算先不动，只补一小组新素材，再看一个稳定窗口。"
            )

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
