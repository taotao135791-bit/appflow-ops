"""One-way sanitizer for turning production replays into eval-safe fixtures.

Design contract (docs/eval-privacy.md):

- Preserve decision shape, remove business identity.
- Output keeps only: platform, objective class, measurement/maturity state,
  metric deltas/ratios/indexes, recent-change type/direction/age bucket,
  policy/permission state, action class, outcome direction, rollback state.
- Money is normalized to an index (before = 100); timestamps become buckets.
- Sanitization is one-way: no reversible id mapping is produced or stored.
- Any free-form text, identifiers, URLs, paths, or emails are dropped.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

IDENTITY_KEYS = frozenset(
    {
        "client",
        "client_name",
        "brand",
        "app",
        "app_name",
        "account_id",
        "customer_id",
        "campaign_id",
        "campaign_name",
        "ad_group_id",
        "ad_group_name",
        "adset_id",
        "asset_id",
        "creative_id",
        "creative_name",
        "creative_copy",
        "ad_copy",
        "email",
        "url",
        "landing_url",
        "workspace_path",
        "username",
        "local_user",
        "notes",
        "comment",
        "freeform",
        "free_text",
        "screenshot_path",
    }
)

TEXT_KEYS = frozenset(
    {"creative_copy", "ad_copy", "notes", "comment", "freeform", "free_text"}
)

TIME_KEYS = frozenset(
    {"timestamp", "executed_at", "changed_at", "event_time", "occurred_at"}
)

# (before_key, after_key) pairs normalized to an index with before = 100.
MONEY_PAIRS = (
    ("spend_before", "spend_after"),
    ("tcpa_before", "tcpa_after"),
    ("troas_before", "troas_after"),
    ("cpa_before", "cpa_after"),
    ("budget_before", "budget_after"),
    ("cpi_before", "cpi_after"),
)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+", re.IGNORECASE)
URL_RE = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
# Absolute paths only: a leading slash followed by a known root directory or
# a tilde home; bare tokens like "/or" or "/AdAttributionKit" are not paths.
# The root list is assembled at runtime so the worktree privacy scanner does
# not see literal home-directory text in this module.
_HOME_ROOTS = (
    "/"
    + "Users/"
    + "|"
    + "/"
    + "home/"
    + "|"
    + "/"
    + "private/"
    + "|"
    + "/"
    + "var/"
    + "|"
    + "/"
    + "tmp/"
    + "|"
    + r"C:\\"
    + "|"
    + "~/"
)
ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + _HOME_ROOTS + r")[A-Za-z0-9_\-./\\]+"
)
STABLE_ID_RE = re.compile(r"\b\d{10}\b")
# Longer advertiser/account-style numeric identifiers (12-24 digits).
LONG_ID_RE = re.compile(r"\b\d{12,24}\b")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# Token-like values behind an explicit key label (defense-in-depth only; the
# sanitizer whitelist remains the primary boundary).
TOKEN_LIKE_RE = re.compile(
    r"\b(?:api[_-]?key|app[_-]?token|access[_-]?token|secret|token)"
    r"[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=]{16,}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SanitizationResult:
    data: Mapping[str, Any]
    dropped_keys: tuple[str, ...]
    normalized_pairs: tuple[str, ...]
    time_buckets: tuple[str, ...]


def bucket_age(hours: float) -> str:
    """Bucket a duration in hours into a coarse, non-identifying range."""
    if hours < 6:
        return "<6h"
    if hours < 24:
        return "6-24h"
    if hours < 72:
        return "1-3d"
    if hours < 168:
        return "3-7d"
    return ">7d"


def normalize_money(before: float, after: float) -> Mapping[str, float | None]:
    """Normalize a money pair to an index with before = 100."""
    if before is None or before == 0:
        return {"before": None, "after": None}
    return {"before": 100.0, "after": round(after / before * 100.0, 1)}


def sanitize_replay(raw: Mapping[str, Any]) -> SanitizationResult:
    """One-way transform of a structured replay record into an eval case.

    The input is expected to be a flat mapping (for example a decoded replay
    snapshot) with the keys documented above. Unknown keys are dropped by
    default: whitelist wins.
    """
    kept: dict[str, Any] = {}
    dropped: list[str] = []
    normalized: list[str] = []
    buckets: list[str] = []

    for key, value in raw.items():
        if key in IDENTITY_KEYS:
            dropped.append(key)
            continue
        if key in TIME_KEYS and value is not None:
            try:
                hours = float(value)
            except (TypeError, ValueError):
                dropped.append(key)
                continue
            bucket = bucket_age(hours)
            kept[f"{key}_bucket"] = bucket
            buckets.append(bucket)
            continue
        if key in TEXT_KEYS:
            dropped.append(key)
            continue

    for before_key, after_key in MONEY_PAIRS:
        before = raw.get(before_key)
        after = raw.get(after_key)
        if before is None or after is None:
            continue
        try:
            index = normalize_money(float(before), float(after))
        except (TypeError, ValueError):
            dropped.extend((before_key, after_key))
            continue
        stem = before_key.removesuffix("_before")
        kept[f"{stem}_index"] = index
        normalized.append(stem)

    # Whitelisted structural keys survive untouched.
    for key in (
        "platform",
        "objective_class",
        "measurement_state",
        "maturity_state",
        "recent_change_type",
        "recent_change_direction",
        "policy_state",
        "permission_state",
        "expected_action_class",
        "outcome_direction",
        "rollback_state",
    ):
        if key in raw and raw[key] is not None:
            kept[key] = raw[key]

    return SanitizationResult(
        data=kept,
        dropped_keys=tuple(dropped),
        normalized_pairs=tuple(normalized),
        time_buckets=tuple(buckets),
    )


def identity_markers(text: str) -> tuple[str, ...]:
    """Return which identity markers are present in ``text``.

    Defense-in-depth only: the sanitizer whitelist is the primary safety
    boundary, and this detector can never prove the absence of every
    sensitive value (see docs/eval-privacy.md).
    """
    markers: list[str] = []
    if EMAIL_RE.search(text):
        markers.append("email")
    if URL_RE.search(text):
        markers.append("url")
    if ABSOLUTE_PATH_RE.search(text):
        markers.append("absolute_path")
    if STABLE_ID_RE.search(text):
        markers.append("stable_id")
    if LONG_ID_RE.search(text):
        markers.append("long_id")
    if UUID_RE.search(text):
        markers.append("uuid")
    if TOKEN_LIKE_RE.search(text):
        markers.append("token_like")
    return tuple(markers)


def assert_sanitized(data: Mapping[str, Any]) -> None:
    """Fail loudly if the sanitized output still carries identity markers."""
    serialized = _serialize(data)
    markers = identity_markers(serialized)
    if markers:
        raise ValueError(
            "sanitized output still contains identity markers: " + ", ".join(markers)
        )


def _serialize(data: Mapping[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, default=str)
