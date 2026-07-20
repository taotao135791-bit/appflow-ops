#!/usr/bin/env python3
"""Verify the bundled UAC policy set loads intact and pinned.

The numeric Quick Decision path depends on two versioned policy documents.
This check loads the policy set through the repo package and asserts the
expected versions are present and no policy fell back to a degraded
(heuristic-only) state.

Usage:
    python scripts/ci/check_uac_policies.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from kimi_ads.uac.policy_loader import load_policy_set  # noqa: E402

EXPECTED_VERSIONS = {
    "uac_numeric": "uac-numeric-policy-v1",
    "uac_signal": "uac-signal-policy-v1",
}


def main() -> int:
    policies = load_policy_set()
    failures: list[str] = []
    for name, expected_version in EXPECTED_VERSIONS.items():
        policy = policies.get(name)
        if policy is None:
            failures.append(f"policy '{name}' is missing from the loaded policy set")
            continue
        if policy.policy_version != expected_version:
            failures.append(
                f"policy '{name}': expected version {expected_version!r}, "
                f"got {policy.policy_version!r}"
            )
    for name, policy in policies.items():
        if policy.degraded:
            failures.append(f"policy '{name}' loaded in a degraded state")
    if failures:
        for failure in failures:
            print(f"✗ {failure}", file=sys.stderr)
        return 1
    loaded = ", ".join(
        f"{name}={policy.policy_version}" for name, policy in sorted(policies.items())
    )
    print(f"✓ UAC policy set intact: {loaded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
