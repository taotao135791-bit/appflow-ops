"""Shared internal helpers for the deterministic UAC modules.

These helpers were historically copy-pasted between quick_ops, numeric_decision,
and signals. They live here exactly once; behavior is unchanged.

Note: signals keeps its own OverflowError-safe ``_finite_number``/``_number``
variants (huge ints such as ``10**10000`` must degrade to None instead of
raising), so only the identical implementations are shared here.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _number(value: Any) -> float | None:
    return float(value) if _finite_number(value) else None
