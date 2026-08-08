# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow

"""Continuity tracking for the SMT output-energy hardware counter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

OUTPUT_ENERGY_WRAP_WH = 2**32
_WRAP_HIGH_WATERMARK = OUTPUT_ENERGY_WRAP_WH * 99 // 100
_WRAP_LOW_WATERMARK = OUTPUT_ENERGY_WRAP_WH // 100
_RESET_CONFIRMATION_MAX_ADVANCE_WH = 50


@dataclass
class OutputEnergyTracker:
    """Track a uint32 Wh counter across resets and confirmed wraps."""

    offset_wh: int = 0
    previous_raw_wh: int | None = None
    serial_number: str | None = None
    pending_reset_raw_wh: int | None = None

    @classmethod
    def from_storage(
        cls, state: dict[str, Any] | None, initial_rollovers: int
    ) -> "OutputEnergyTracker":
        """Restore valid state, or seed the first observed counter value."""
        if not isinstance(state, dict):
            return cls(offset_wh=initial_rollovers * OUTPUT_ENERGY_WRAP_WH)
        offset = state.get("offset_wh")
        previous = state.get("previous_raw_wh")
        if not isinstance(offset, int) or offset < 0:
            return cls(offset_wh=initial_rollovers * OUTPUT_ENERGY_WRAP_WH)
        if previous is not None and (
            not isinstance(previous, int) or not 0 <= previous < OUTPUT_ENERGY_WRAP_WH
        ):
            return cls(offset_wh=initial_rollovers * OUTPUT_ENERGY_WRAP_WH)
        serial = state.get("serial_number")
        return cls(
            offset_wh=offset,
            previous_raw_wh=previous,
            serial_number=serial if isinstance(serial, str) and serial else None,
        )

    def update(self, raw_wh: int, serial_number: str | None) -> tuple[int, str | None]:
        """Return continuous Wh and a decrease reason, if one was observed."""
        if self.serial_number and serial_number and self.serial_number != serial_number:
            self.offset_wh = 0
            self.previous_raw_wh = None
            self.pending_reset_raw_wh = None

        if self.previous_raw_wh is not None and raw_wh < self.previous_raw_wh:
            if (
                self.previous_raw_wh >= _WRAP_HIGH_WATERMARK
                and raw_wh <= _WRAP_LOW_WATERMARK
            ):
                self.offset_wh += OUTPUT_ENERGY_WRAP_WH
                reason = "wrap"
            elif (
                self.pending_reset_raw_wh is not None
                and self.pending_reset_raw_wh
                <= raw_wh
                <= self.pending_reset_raw_wh + _RESET_CONFIRMATION_MAX_ADVANCE_WH
            ):
                self.offset_wh += self.previous_raw_wh
                reason = "reset"
            else:
                self.pending_reset_raw_wh = raw_wh
                return self.offset_wh + self.previous_raw_wh, "pending_reset"
        else:
            reason = None

        self.previous_raw_wh = raw_wh
        self.pending_reset_raw_wh = None
        if serial_number:
            self.serial_number = serial_number
        return self.offset_wh + raw_wh, reason

    def as_dict(self) -> dict[str, int | str | None]:
        """Serialize the tracker state for Home Assistant storage."""
        return {
            "offset_wh": self.offset_wh,
            "previous_raw_wh": self.previous_raw_wh,
            "serial_number": self.serial_number,
        }
