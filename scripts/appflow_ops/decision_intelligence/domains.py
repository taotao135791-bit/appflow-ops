"""Operational domains for Ads Decision Intelligence (v3.5.0).

A domain is WHAT the user is asking about; a platform scope is WHERE the
data belongs. Domains are lightweight routing/context semantics — never
platform scope entries, never new state events.
"""

from __future__ import annotations

import re

# Canonical operational domains (keep small; general is the fallback).
OPERATIONAL_DOMAINS = (
    "creative",
    "funnel",
    "measurement",
    "bid_budget",
    "delivery",
    "auction",
    "audience",
    "cross_platform",
    "general",
)

# High-precision hints only; ordering defines primary-domain precedence.
# Cross-platform is detected separately (a request can be funnel + cross).
_DOMAIN_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "creative",
        re.compile(r"素材|创意|creative|广告创意|疲劳|衰减|换素材", re.IGNORECASE),
    ),
    (
        "funnel",
        re.compile(
            r"漏斗|funnel|转化|安装|install|注册|registration|付费|支付|购买|pay|conversion|cvr",
            re.IGNORECASE,
        ),
    ),
    (
        "measurement",
        re.compile(
            r"数据不准|归因|attribution|measurement|埋点|回传|统计|事件不准|没数据",
            re.IGNORECASE,
        ),
    ),
    (
        "bid_budget",
        re.compile(
            r"预算|出价|budget|bid|加不加|加量|减量|降预算|提价|降价|调价",
            re.IGNORECASE,
        ),
    ),
    (
        "delivery",
        re.compile(
            r"投放|delivery|消耗|花费|起量|掉量|没量|跑量|不跑了", re.IGNORECASE
        ),
    ),
    ("auction", re.compile(r"竞价|auction|竞争变|cpm 涨", re.IGNORECASE)),
    (
        "audience",
        re.compile(r"受众|人群|audience|频次|frequency|扩量人群", re.IGNORECASE),
    ),
)

_CROSS_PLATFORM_RE = re.compile(
    r"跨平台|cross[- ]platform|全渠道|Google 和 Meta|Meta 和 Google|Google.*Meta|Meta.*Google",
    re.IGNORECASE,
)


def detect_operational_domain(request: str) -> str:
    """Primary operational domain for a request. Returns ``general`` when
    no high-precision hint matches — never forces a specific domain.
    ``bid_budget``/``funnel``/... are hints for routing; the evaluator
    still converges from real evidence, not from this label alone.
    """
    for domain, pattern in _DOMAIN_HINTS:
        if pattern.search(request):
            return domain
    return "general"


def is_cross_platform_request(request: str) -> bool:
    """Whether the request explicitly spans multiple platforms (used as a
    routing signal; the platform scope itself still comes from explicit
    scope or platform detection)."""
    return bool(_CROSS_PLATFORM_RE.search(request))


def primary_domain(request: str) -> str:
    """Alias kept for readability: same as detect_operational_domain."""
    return detect_operational_domain(request)
