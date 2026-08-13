"""Public runtime facade (v3.4.0).

Re-exports the shared operational runtime contracts so platform code can
import from ``appflow_ops.runtime`` instead of reaching into the historical
``appflow_ops.uac.*`` layout. The implementation stays in place; no file
migration until at least Meta + TikTok operational runtimes are stable.
"""

from __future__ import annotations

from .decision_intelligence import (
    DecisionIntelligenceResult,
    build_hypothesis_set,
    converge,
    detect_operational_domain,
    evaluate_hypotheses,
    rank_hypotheses,
    summarize_decision_intelligence,
)
from .uac.account_state import RunContext
from .uac.operational_runtime import (
    PER_PLATFORM_CHANGES,
    PER_PLATFORM_DECISIONS,
    PER_PLATFORM_OBSERVATIONS,
    PER_PLATFORM_OUTCOMES,
    OperationalContext,
    OperationalResult,
    PlatformOperationalRun,
    PlatformSafetyContext,
    build_operational_context,
    detect_domain,
    detect_platforms,
)
from .uac.platform_adapters import (
    CREATIVE,
    META,
    PLATFORM_ADAPTERS,
    TIKTOK,
    PlatformAdapter,
    adapter_for,
)
from .uac.run_lifecycle import (
    AppFlowRuntime,
    StateAccess,
    build_state_context,
    classify_request,
    classify_state_access,
)
from .uac.state_runtime import StateSession

__all__ = [
    "CREATIVE",
    "META",
    "PER_PLATFORM_CHANGES",
    "PER_PLATFORM_DECISIONS",
    "PER_PLATFORM_OBSERVATIONS",
    "PER_PLATFORM_OUTCOMES",
    "PLATFORM_ADAPTERS",
    "TIKTOK",
    "AppFlowRuntime",
    "DecisionIntelligenceResult",
    "OperationalContext",
    "OperationalResult",
    "PlatformAdapter",
    "PlatformOperationalRun",
    "PlatformSafetyContext",
    "RunContext",
    "StateAccess",
    "StateSession",
    "adapter_for",
    "build_hypothesis_set",
    "build_operational_context",
    "build_state_context",
    "classify_request",
    "classify_state_access",
    "converge",
    "detect_domain",
    "detect_operational_domain",
    "detect_platforms",
    "evaluate_hypotheses",
    "rank_hypotheses",
    "summarize_decision_intelligence",
]
