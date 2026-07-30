# Enhanced runtime-calibration state delivery contract

## Outcome

Add one default-enabled, read-only Home Assistant enum sensor that reports an
APC UPS runtime calibration’s current/result state in human-readable terms.

## Required implementation

- For Smart-UPS and SMT/SMX/SRT families, query
  `upsAdvTestCalibrationResults` (`1.3.6.1.4.1.318.1.1.1.7.2.6.0`) in the
  existing regular self-test SNMP batch.
- Use coordinator key, sensor key, and register key
  `snmp_runtime_calibration_status`; name the entity `Runtime Calibration
  Status`.
- Model it as a default-enabled enum sensor with a normal config-entry-based
  unique ID. Do not create it for Rack PDUs.
- Decode the read-only OID values exactly as follows:

  | Value | State |
  | ---: | --- |
  | 1 | Calibration Complete |
  | 2 | Cannot Calibrate — Battery Not Fully Charged |
  | 3 | Calibration In Progress |
  | 4 | Calibration Refused |
  | 5 | Calibration Aborted |
  | 6 | Calibration Pending |

- Preserve any unknown numeric value as `Unknown (<value>)`. An unavailable,
  unsupported, or invalid OID leaves only this entity unavailable.

## Boundaries

- Reuse the existing self-test helper, SNMP OID deduplication, coordinator
  merge, and sensor setup patterns. Do not add a separate poll, dependency,
  config option, service, button, or write access.
- Do not query or expose an OID that starts/cancels calibration.
- Do not change existing self-test sensors, energy handling, polling cadence,
  Rack PDU behavior, or release metadata.

## Acceptance

- Tests cover the OID batch, integer parsing, each human-readable state, an
  unknown code, and an independently failed OID.
- Tests verify supported UPS entity setup and confirm Rack PDUs do not get the
  entity.
- `./.venv/bin/pytest -q` and `make lint` pass.

The detailed requirements are in [enhanced_state_calibration.nd](enhanced_state_calibration.nd);
this contract controls scope if they differ.
