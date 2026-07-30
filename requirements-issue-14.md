# Issue 14: SMT output energy in kWh

## Goal

Expose the SMT/SMX/SRT `Output.Energy` Modbus counter in kWh and account for
its real, observed 32-bit rollover without corrupting the long-term statistics
recorded for the existing Wh entity.

## Scope

- Applies only to the SMT/SMX/SRT register at `0x0091` (`Output.Energy`).
- The register remains a two-register unsigned 32-bit hardware counter. Its
  raw value is Wh.
- Keep `output_energy` as the raw Wh coordinator/register key, so no polling,
  address, word order, or diagnostic collection changes are needed.
- Add a coordinator-derived `output_energy_kwh` value for the compensated,
  cumulative total. The sensor must read this value, not the raw counter.
- Create the sensor with entity-description key `output_energy_kwh`, name
  `Output Energy`, energy device class, `kWh` native unit, and
  `total_increasing` state class.  Its resulting unique ID must therefore be
  `apc_modbus_<config_entry_id>_output_energy_kwh`.
- Update the SMT entry in `sensor_catalog_unified.py` to use the new key and
  kWh unit.

## Initial rollover count

- Add an optional `Output Energy Completed Rollovers` integer to the initial
  configuration form, with a default of `0` and validation requiring a
  non-negative whole number. It is relevant only to SMT/SMX/SRT devices and
  may be ignored for other device families.
- The value is the number of complete `2**32` Wh cycles that occurred before
  this integration first observed the UPS. It is not a boolean.
- On the first successful raw energy reading, seed the persisted offset with
  `configured_rollovers * 2**32` Wh, then save the tracker state. This lets a
  user add an already-old UPS without waiting for another rollover.
- Treat the configured count as a one-time seed. Do not silently apply a
  later edit to an already-running entity: it would appear as a multi-GWh
  energy spike in its statistics. A correction after setup requires an
  explicit, documented statistics migration and is out of scope for this
  issue.

## Statistics migration

- Do not change the unit, scale, or unique ID of the existing
  `..._output_energy` entity.  It has Wh long-term statistics.
- Do not rewrite, convert, or delete recorder statistics.  The new entity
  starts a separate kWh statistics series; normal stale-entity cleanup may
  remove the old entity-registry entry without modifying its recorder data.

## Rollover

- Add one shared rollover tracker in the coordinator, immediately after the
  raw `output_energy` value is decoded. Do not implement compensation in the
  sensor entity or in Home Assistant statistics.
- Persist the tracker per config entry using Home Assistant storage. Its state
  is the previous raw Wh value, the accumulated Wh offset, and the UPS serial
  number when available. Restore it before the first energy update; reset it
  to a new baseline if the serial number changes.
- The compensated value is `(offset_wh + raw_wh) / 1000` and must never
  decrease for a continuing device.
- Treat a decrease as a wrap only when the previous raw value is at least 99%
  of `2**32` and the new raw value is at most 1% of `2**32`. On a wrap, add
  exactly `2**32` Wh to the offset.
- Treat every other decrease as a hardware meter reset. Increase the offset
  by the previous raw value so the exposed total stays continuous, log the
  reset once, and continue from the new raw value. Do not add `2**32` Wh for
  an unconfirmed reset.
- A sufficiently long outage that misses both sides of a wrap cannot be
  distinguished from a reset using this register alone. Log that ambiguous
  decrease and prefer the reset path; never fabricate a 4.295-GWh increment.

## Out of scope

- Do not change Rack PDU energy counters: they already report kWh and their
  32-bit, 0.1-kWh counters have no practical rollover horizon.
- Do not change instantaneous power units.  Device power already uses kW/kVA;
  phase and outlet values are bounded instantaneous W/VA measurements, not
  accumulating statistics.
- Do not change polling, register blocks, diagnostics, release metadata, or
  add dependencies.

## Tests and acceptance criteria

- Add focused tracker tests for ordinary increments, an exact wrap, a reset,
  restored state, and a changed serial number. A transition from `2**32 - 2`
  Wh to `3` Wh must expose `2**32 + 3` Wh before kWh scaling.
- Test an initial configured rollover count of one: the first raw reading of
  `3` Wh must expose `2**32 + 3` Wh before kWh scaling. Reject negative and
  fractional configuration values.
- Verify `0x0091` retains its `output_energy` raw register key and is decoded
  at a scale of 1.
- Verify the sensor description uses `output_energy_kwh`, reads the derived
  coordinator key, reports kWh, and is `total_increasing` with the energy
  device class.
- Verify the unified catalog advertises the same key and unit.
- Verify the legacy `output_energy` entity identity is not reused.
- Run `./.venv/bin/pytest -q` and `make lint`.
