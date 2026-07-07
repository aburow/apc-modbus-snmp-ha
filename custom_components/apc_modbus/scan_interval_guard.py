# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Helpers for fleet-aware scan interval protection."""

from __future__ import annotations


def compute_effective_scan_interval(configured_seconds: int, total_entries: int) -> int:
    """Return a safe effective scan interval for the current fleet size.

    Small deployments keep their configured value. For larger fleets, enforce
    a floor that grows with entry count to avoid overloading recorder/database
    writes during continuous polling.
    """
    configured = max(int(configured_seconds), 1)
    entries = max(int(total_entries), 1)

    if entries <= 8:
        return configured

    # Scale roughly with fleet size while capping at a practical upper bound.
    fleet_floor = min(max(entries * 2, 20), 120)
    return max(configured, fleet_floor)
