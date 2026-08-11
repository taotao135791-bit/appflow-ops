"""Single-file HTML funnel diagnosis dashboard for one UAC case.

The dashboard is deterministic in the same sense as the rest of the UAC
tooling: given one normalized case it renders a self-contained HTML file
(no external assets, no server) that separates observed facts, calculated
metrics, and inferences. It never invents missing funnel layers; missing
data is reported as a data gap instead of a fake bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Mapping

from .contracts import _validate_case
from .io import _load
from .types import ContractError
from .workspace import Workspace

_COUNT_STAGES: tuple[tuple[str, str], ...] = (
    ("installs", "安装 Installs"),
    ("registrations", "注册 Registrations"),
    ("payments", "支付 Payments"),
)

DEFAULT_OUTPUT_NAME = "funnel-dashboard.html"


@dataclass(frozen=True)
class FunnelStage:
    key: str
    label: str
    value: float | None


@dataclass(frozen=True)
class FunnelConversion:
    from_key: str
    to_key: str
    label: str
    rate_percent: float | None


@dataclass(frozen=True)
class FunnelDiagnosis:
    scope: Mapping[str, Any]
    spend: float | None
    value: float | None
    stages: tuple[FunnelStage, ...]
    conversions: tuple[FunnelConversion, ...]
    costs: Mapping[str, float | None]
    bottleneck_key: str | None
    missing: tuple[str, ...]


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def build_funnel(case: dict[str, Any]) -> FunnelDiagnosis:
    """Derive funnel stages and diagnosis from one normalized UAC case."""

    _validate_case(case)
    scope = case.get("scope", {})
    facts = case.get("facts", {})
    metrics = facts.get("metrics", {}) if isinstance(facts, Mapping) else {}

    spend = _number(metrics.get("spend"))
    value = _number(metrics.get("revenue"))

    stages: list[FunnelStage] = []
    missing: list[str] = []
    for key, label in _COUNT_STAGES:
        amount = _number(metrics.get(key))
        if amount is None:
            missing.append(key)
        stages.append(FunnelStage(key=key, label=label, value=amount))
    if spend is None:
        missing.insert(0, "spend")

    conversions: list[FunnelConversion] = []
    previous: FunnelStage | None = None
    for stage in stages:
        if previous is not None:
            rate: float | None = None
            if (
                previous.value is not None
                and stage.value is not None
                and previous.value > 0
            ):
                rate = stage.value / previous.value * 100.0
            conversions.append(
                FunnelConversion(
                    from_key=previous.key,
                    to_key=stage.key,
                    label=f"{previous.label} → {stage.label}",
                    rate_percent=rate,
                )
            )
        previous = stage

    costs: dict[str, float | None] = {
        "cpi": spend / installs.value
        if spend is not None and (installs := stages[0]).value
        else None,
        "cost_per_registration": spend / registrations.value
        if spend is not None and (registrations := stages[1]).value
        else None,
        "cost_per_payment": spend / payments.value
        if spend is not None and (payments := stages[2]).value
        else None,
    }

    bottleneck_key: str | None = None
    rates = [c.rate_percent for c in conversions if c.rate_percent is not None]
    if rates:
        worst_rate = min(rates)
        bottleneck_key = next(
            c.to_key for c in conversions if c.rate_percent == worst_rate
        )

    return FunnelDiagnosis(
        scope=scope if isinstance(scope, Mapping) else {},
        spend=spend,
        value=value,
        stages=tuple(stages),
        conversions=tuple(conversions),
        costs=costs,
        bottleneck_key=bottleneck_key,
        missing=tuple(missing),
    )


def _format_number(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 10:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def _scope_line(scope: Mapping[str, Any]) -> str:
    parts = [
        str(scope.get("campaign", "")),
        str(scope.get("os", "")),
        str(scope.get("country", "")),
    ]
    dates = " ~ ".join(
        str(scope[key]) for key in ("start_date", "end_date") if scope.get(key)
    )
    if dates:
        parts.append(dates)
    return " · ".join(part for part in parts if part and part != "None")


def render_funnel_html(
    diagnosis: FunnelDiagnosis, *, source_label: str, generated_at: str
) -> str:
    """Render one self-contained HTML dashboard (inline CSS, no scripts)."""

    max_value = max(
        (stage.value for stage in diagnosis.stages if stage.value), default=None
    )
    rows: list[str] = []
    for stage in diagnosis.stages:
        is_bottleneck = stage.key == diagnosis.bottleneck_key
        if stage.value is None:
            rows.append(
                f'<div class="row missing"><div class="name">{escape(stage.label)}</div>'
                f'<div class="bar-wrap"><div class="bar empty">数据缺失</div></div>'
                f'<div class="num">—</div></div>'
            )
            continue
        width = (
            max(4.0, (stage.value / max_value) ** 0.5 * 100.0)
            if max_value
            else 4.0
        )
        css_class = "bar bottleneck" if is_bottleneck else "bar"
        badge = '<span class="badge">瓶颈层</span>' if is_bottleneck else ""
        rows.append(
            f'<div class="row"><div class="name">{escape(stage.label)}{badge}</div>'
            f'<div class="bar-wrap"><div class="{css_class}" style="width:{width:.1f}%"></div></div>'
            f'<div class="num">{_format_number(stage.value)}</div></div>'
        )

    conversion_rows = "".join(
        f"<tr><td>{escape(conversion.label)}</td>"
        f"<td>{'—' if conversion.rate_percent is None else f'{conversion.rate_percent:.1f}%'}</td></tr>"
        for conversion in diagnosis.conversions
    )
    cost_labels = {
        "cpi": "CPI（花费/安装）",
        "cost_per_registration": "单注册成本",
        "cost_per_payment": "单支付成本",
    }
    cost_rows = "".join(
        f"<tr><td>{escape(label)}</td><td>{_format_number(diagnosis.costs.get(key))}</td></tr>"
        for key, label in cost_labels.items()
    )

    observed = [
        f"日期范围：{_scope_line(diagnosis.scope) or '未提供'}",
        f"花费：{_format_number(diagnosis.spend)}"
        + (
            f"；回传价值：{_format_number(diagnosis.value)}"
            if diagnosis.value is not None
            else ""
        ),
    ]
    observed.extend(
        f"{stage.label}：{_format_number(stage.value)}"
        for stage in diagnosis.stages
    )
    calculated = [
        f"{conversion.label} 转化率："
        + ("—" if conversion.rate_percent is None else f"{conversion.rate_percent:.1f}%")
        for conversion in diagnosis.conversions
    ]
    inferences: list[str] = []
    if diagnosis.bottleneck_key is not None:
        worst = next(
            c for c in diagnosis.conversions if c.to_key == diagnosis.bottleneck_key
        )
        inferences.append(
            f"当前转化率最低的一环是 {worst.label}"
            f"（{worst.rate_percent:.1f}%），优先核查该层的口径、延迟与质量，"
            "再考虑投放侧动作。这是推断，不是因果结论。"
        )
    if diagnosis.missing:
        inferences.append(
            "缺失层级：" + "、".join(diagnosis.missing) +
            "。补齐这些数据前，漏斗诊断不完整，不要据此修改账户。"
        )
    if not inferences:
        inferences.append("现有层级未见明显瓶颈；保持观察，不修改账户。")

    def section(title: str, items: list[str]) -> str:
        body = "".join(f"<li>{escape(item)}</li>" for item in items)
        return f'<div class="panel"><h2>{escape(title)}</h2><ul>{body}</ul></div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>漏斗诊断看板 · AppFlow Ops</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background:#0f1420; color:#e8ecf4; margin:0; padding:32px; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .sub {{ color:#8b96ad; font-size:13px; margin-bottom:24px; }}
  .grid {{ display:grid; grid-template-columns: 3fr 2fr; gap:24px; }}
  .panel {{ background:#171e2e; border:1px solid #232c42; border-radius:10px;
            padding:18px 20px; margin-bottom:18px; }}
  .panel h2 {{ font-size:14px; color:#9fb0d0; margin:0 0 12px; }}
  .panel ul {{ margin:0; padding-left:18px; line-height:1.8; font-size:13px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  td {{ padding:6px 4px; border-bottom:1px solid #232c42; }}
  td:last-child {{ text-align:right; color:#cdd7ea; }}
  .row {{ display:grid; grid-template-columns: 170px 1fr 90px; align-items:center;
          gap:10px; margin:10px 0; }}
  .name {{ font-size:13px; color:#cdd7ea; }}
  .bar-wrap {{ background:#111827; border-radius:6px; height:26px; }}
  .bar {{ background:linear-gradient(90deg,#2f6df6,#59a7ff); height:26px;
          border-radius:6px; }}
  .bar.bottleneck {{ background:linear-gradient(90deg,#d64545,#ff7a6b); }}
  .bar.empty {{ background:none; color:#8b96ad; font-size:12px; line-height:26px;
                padding-left:8px; }}
  .num {{ text-align:right; font-size:13px; color:#e8ecf4; }}
  .badge {{ display:inline-block; margin-left:6px; padding:1px 6px; font-size:11px;
            color:#fff; background:#d64545; border-radius:4px; }}
  .missing .name {{ color:#8b96ad; }}
  footer {{ margin-top:28px; color:#67718a; font-size:12px; line-height:1.7; }}
</style>
</head>
<body>
<h1>漏斗诊断看板</h1>
<div class="sub">{escape(_scope_line(diagnosis.scope)) or "未提供账户范围"}</div>
<div class="grid">
  <div class="panel">
    <h2>转化漏斗（数量层）</h2>
    {''.join(rows)}
  </div>
  <div>
    <div class="panel"><h2>相邻层转化率</h2>
      <table>{conversion_rows or '<tr><td>—</td></tr>'}</table></div>
    <div class="panel"><h2>成本</h2>
      <table>{cost_rows}</table></div>
  </div>
</div>
{section("观察（输入事实）", observed)}
{section("计算（派生指标）", calculated)}
{section("推断（诊断结论）", inferences)}
<footer>
  数据来源：{escape(source_label)} · 生成时间：{escape(generated_at)} ·
  AppFlow Ops 漏斗诊断<br>
  本看板仅供内部诊断使用，不作为对甲方的效果承诺，也不构成因果结论。
</footer>
</body>
</html>
"""


def write_funnel_dashboard(
    *,
    workspace: Workspace | None = None,
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Generate the dashboard HTML and return the written file path."""

    if workspace is not None:
        workspace.require_initialized()
        case_path = input_path or workspace.require_case()
        case_path = workspace.require_contained_path(case_path, "funnel input")
    elif input_path is not None:
        case_path = input_path.expanduser()
        if not case_path.is_file():
            raise ContractError(f"funnel input not found: {case_path}")
    else:
        raise ContractError("funnel dashboard requires --workspace or an input file")

    case = _load(case_path)
    diagnosis = build_funnel(case)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = render_funnel_html(
        diagnosis, source_label=case_path.name, generated_at=generated_at
    )

    if output_path is None:
        if workspace is not None:
            output_path = workspace.reports_dir / DEFAULT_OUTPUT_NAME
        else:
            output_path = Path(DEFAULT_OUTPUT_NAME)
    if workspace is not None:
        output_path = workspace.require_contained_path(
            output_path, "funnel dashboard output"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    if workspace is not None:
        workspace.protect_file(output_path)
    return output_path
