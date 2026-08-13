"""Unit tests for Ads Decision Intelligence domain detection."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.decision_intelligence import (
    detect_operational_domain,
    is_cross_platform_request,
)


def test_meta_creative_query() -> None:
    assert detect_operational_domain("Meta 这个素材是不是衰减了？") == "creative"
    assert detect_operational_domain("这个素材还能跑吗？") == "creative"


def test_tiktok_funnel_query() -> None:
    assert detect_operational_domain("TikTok 点击还行，为什么安装掉了？") == "funnel"
    assert detect_operational_domain("注册转化为什么掉了") == "funnel"
    assert detect_operational_domain("付费为什么降了") == "funnel"


def test_bid_budget_query() -> None:
    assert detect_operational_domain("这个广告现在预算要不要加？") == "bid_budget"
    assert detect_operational_domain("出价要不要调") == "bid_budget"
    assert detect_operational_domain("要不要加量") == "bid_budget"


def test_measurement_query() -> None:
    assert detect_operational_domain("是不是数据不准？") == "measurement"
    assert detect_operational_domain("归因是不是有问题") == "measurement"


def test_delivery_query() -> None:
    assert detect_operational_domain("为什么掉量了") == "delivery"
    assert detect_operational_domain("没量了") == "delivery"


def test_general_fallback() -> None:
    assert detect_operational_domain("这个还能不能跑？") == "general"
    assert detect_operational_domain("现在呢？") == "general"
    assert detect_operational_domain("帮我看看") == "general"


def test_cross_platform_detection() -> None:
    assert is_cross_platform_request("Google 和 Meta 都开始掉付费，是产品问题吗？")
    assert is_cross_platform_request("跨平台对比一下")
    assert not is_cross_platform_request("Meta 素材是不是衰减了？")
