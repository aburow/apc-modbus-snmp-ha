# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Helpers for spreading startup polling load across many entries."""

from __future__ import annotations


def compute_startup_stagger_delay(
    entry_ids: list[str],
    current_entry_id: str,
    scan_interval: int,
) -> float:
    """Compute a deterministic startup delay for one entry.

    The delay spreads entry setup work across a bounded window so large fleets
    do not all perform SNMP metadata, Modbus probing, capability discovery, and
    first refresh at the same instant.
    """
    ordered_entry_ids = sorted(entry_ids)
    total_entries = len(ordered_entry_ids)
    if total_entries <= 1:
        return 0.0

    try:
        slot_index = ordered_entry_ids.index(current_entry_id)
    except ValueError:
        return 0.0

    # Spread startup work over a bounded window. For small fleets, use at least
    # one scan interval; for larger fleets, widen the window up to 60 seconds.
    window_seconds = min(max(float(scan_interval), float(total_entries)), 60.0)
    return (slot_index * window_seconds) / float(total_entries)
