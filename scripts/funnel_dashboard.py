#!/usr/bin/env python3
"""Standalone entry point for the funnel diagnosis dashboard.

Equivalent to: python3 scripts/uac_experiment.py funnel-dashboard ...
"""

from __future__ import annotations

from appflow_ops.uac.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
