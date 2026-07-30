# Issue 12: Smart-UPS automatic self-test telemetry

## Goal

Expose APC Smart-UPS automatic self-test status and schedule through normal
Home Assistant sensor entities.  Read the values through the integration's
existing SNMP v2c path; do not add a YAML SNMP platform or a new dependency.

## Scope

- Create the entities for Smart-UPS and SMT/SMX/SRT UPS device families.
  Devices that do not implement an OID report that entity as unavailable.
- Do not create these entities for Rack PDUs.
- These are read-only telemetry entities.  Do **not** query, expose, or write
  `1.3.6.1.4.1.318.1.1.1.7.2.2.0` (`upsAdvTestDiagnostics`), the command used
  to start a self-test.

## SNMP polling

Add the following OIDs to the regular SNMP state polling path, alongside the
existing per-update SNMP-backed state values.  They must be fetched without
blocking the Home Assistant event loop and merged into the coordinator data
for the same refresh cycle.

| Coordinator key | Entity name | OID | Raw type |
| --- | --- | --- | --- |
| `snmp_self_test_schedule` | Automatic Self-Test Schedule | `1.3.6.1.4.1.318.1.1.1.7.2.1.0` | Integer enum |
| `snmp_self_test_result` | Last Self-Test Result | `1.3.6.1.4.1.318.1.1.1.7.2.3.0` | Integer enum |
| `snmp_last_self_test_date` | Last Self-Test Date | `1.3.6.1.4.1.318.1.1.1.7.2.4.0` | `mm/dd/yy` date string |
| `snmp_self_test_time` | Automatic Self-Test Time | `1.3.6.1.4.1.318.1.1.1.7.2.8.0` | `hh:mm` time string |
| `snmp_self_test_day` | Automatic Self-Test Day | `1.3.6.1.4.1.318.1.1.1.7.2.9.0` | Integer enum |

- Fetch the OIDs together, deduplicate requests, and tolerate an unsupported
  OID independently: a failed or absent value must not prevent other Modbus or
  SNMP values from updating.
- Avoid a separate hourly-only metadata cache for these values.  The values
  are state/schedule telemetry and must be refreshed by the regular update
  cycle.
- An unsupported OID must produce an unavailable entity state, not setup
  failure, repeated warning-level log noise, or entity removal.

## Decoding and Home Assistant representation

Present human-readable values, not SNMP integer codes.

| Key | Required decoded values |
| --- | --- |
| `snmp_self_test_schedule` | `Unknown` (1), `Biweekly` (2), `Weekly` (3), `At Turn On` (4), `Never` (5), `Every 4 Weeks` (6), `Every 12 Weeks` (7), `Biweekly Since Last Test` (8), `Weekly Since Last Test` (9), `Every 8 Weeks` (10), `Every 26 Weeks` (11), `Every 52 Weeks` (12) |
| `snmp_self_test_result` | `OK` (1), `Failed` (2), `Invalid Test` (3), `Test In Progress` (4) |
| `snmp_self_test_day` | `Monday` (1) through `Sunday` (7) |

- Unknown numeric values must remain visible as `Unknown (<value>)` rather
  than being silently converted to a known state.
- Model schedule, result, and day as enum sensors.
- Parse the last-test value strictly as the MIB's `mm/dd/yy` date.  Expose it
  as a Home Assistant date, allowing Home Assistant's configured locale to
  render it; do not add a locale or time-zone option.  Invalid, blank, or
  unsupported values are unavailable.
- Validate the scheduled time as `HH:MM` and expose it as the device's local
  wall-clock string.  The MIB provides no time zone, so it must not be
  converted or represented as a timestamp.
- Do not add a `Next Self-Test` timestamp.  The MIB has no such value, and a
  reliable timestamp cannot be derived for `At Turn On` or the
  `... Since Last Test` schedules.

## Entity behavior

- Create all five entities for supported UPS families during setup and enable
  them by default.  If a device lacks an OID, retain the entity as unavailable
  so it can become available after a device/NMC change.
- Use stable unique IDs based on the config-entry ID and coordinator keys.
- Preserve existing entity IDs and existing Modbus/SNMP entity semantics.

## Device information link

No implementation work is required: the coordinator already derives
`http://<hostname-or-IPv4>` and `http://[<IPv6>]` from the configured host for
Home Assistant `DeviceInfo.configuration_url`.  Preserve this behavior.

## Tests and acceptance criteria

- Unit-test request selection and deduplication for the five OIDs; assert that
  the command OID `.7.2.2.0` is absent.
- Unit-test the enum maps, unknown values, date parsing, and time validation.
- Unit-test a regular coordinator refresh: successful values are merged and a
  failed OID leaves only its corresponding entity unavailable.
- Unit-test one supported UPS setup: all five entities have stable unique IDs
  and are enabled by default.
- Run `./.venv/bin/pytest -q` and the repository lint workflow before merge.
