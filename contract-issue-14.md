# Issue 14 delivery contract

## Outcome

Expose SMT/SMX/SRT `Output.Energy` (`0x0091`) as a new, statistics-safe kWh
sensor and preserve its cumulative total through observed 32-bit rollovers.

## Required implementation

- Retain `output_energy` as the raw two-register uint32 Wh Modbus value
  (scale `1`). Do not change its address, polling, word order, diagnostics, or
  existing unique ID.
- Add coordinator-derived `output_energy_kwh` and make the new sensor use it.
  Its description key and unique-ID suffix are `output_energy_kwh`; its name
  is `Output Energy`; its unit is kWh; it has the energy device class and
  `total_increasing` state class.
- Add a non-negative integer `Output Energy Completed Rollovers` initial
  configuration field (default `0`). It seeds the first persisted offset as
  `configured_rollovers * 2**32` Wh and is only applied when no persisted
  tracker state exists.
- Persist the tracker per config entry with Home Assistant storage. Persist
  prior raw Wh, accumulated Wh offset, and UPS serial number when available.
  Restore it before processing the first energy value. A serial-number change
  starts a fresh baseline.
- A decrease is a confirmed wrap only when the preceding raw value is at
  least 99% of `2**32` and the new raw value is at most 1%. Add exactly
  `2**32` Wh to the offset in that case.
- Any other decrease is a meter reset: add the preceding raw Wh to the offset
  so the exposed cumulative total remains continuous, log it once, and do not
  add `2**32` Wh. Ambiguous long-outage decreases take this reset path.
- Update the SMT record in `sensor_catalog_unified.py` to the new key and
  kWh unit.

## Boundaries

- Do not rewrite, convert, or delete existing recorder statistics. The old Wh
  entity and the new kWh entity must have distinct unique IDs.
- Do not alter Rack PDU counters, instantaneous power units, Modbus blocks,
  polling behavior, diagnostics, manifests, or dependencies.
- Keep the solution small: one coordinator-owned tracker and Home Assistant's
  native storage; no dashboard entity, helper integration, or custom database
  access.

## Acceptance

- Tests cover ordinary increments, exact rollover (`2**32 - 2` to `3`), reset,
  restored state, serial change, and initial configured rollover count.
- Tests verify the raw register, derived sensor key/unit/state class, catalog,
  configuration validation, and distinct legacy identity.
- `./.venv/bin/pytest -q` and `make lint` pass.

The detailed requirements are in [requirements-issue-14.md](requirements-issue-14.md);
this contract controls scope if they differ.
