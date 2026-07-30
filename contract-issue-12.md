# Issue 12 delivery contract

## Outcome

Add five read-only, default-enabled Smart-UPS self-test sensors, refreshed in
the regular SNMP poll and backed by coordinator data.

| Entity | OID | Decoded form |
| --- | --- | --- |
| Automatic Self-Test Schedule | `.1.3.6.1.4.1.318.1.1.1.7.2.1.0` | Schedule enum |
| Last Self-Test Result | `.1.3.6.1.4.1.318.1.1.1.7.2.3.0` | `OK`, `Failed`, `Invalid Test`, or `Test In Progress` |
| Last Self-Test Date | `.1.3.6.1.4.1.318.1.1.1.7.2.4.0` | Home Assistant date from `mm/dd/yy` |
| Automatic Self-Test Time | `.1.3.6.1.4.1.318.1.1.1.7.2.8.0` | Validated device-local `HH:MM` string |
| Automatic Self-Test Day | `.1.3.6.1.4.1.318.1.1.1.7.2.9.0` | Weekday enum |

## Boundaries

- Apply to Smart-UPS and SMT/SMX/SRT families only; exclude Rack PDUs.
- Use the existing SNMP helper and executor-backed coordinator polling path.
  Fetch the five OIDs together on each regular update and merge successful
  values independently.
- Unsupported/invalid OIDs leave only that entity unavailable; they must not
  interrupt Modbus data, other SNMP data, setup, or entity registration.
- Keep values human-readable.  Preserve unknown enum codes as
  `Unknown (<value>)`.
- Do not query or write `.1.3.6.1.4.1.318.1.1.1.7.2.2.0`; do not add a control
  button, a next-test calculation, configuration options, or dependencies.
- Treat the scheduled time as timezone-free because the MIB supplies no
  timezone.  Do not convert it to a timestamp.  Let Home Assistant render the
  parsed last-test date in its configured locale.
- Preserve the existing `DeviceInfo.configuration_url` fallback; it already
  supplies an HTTP link from the configured host, including IPv6.

## Acceptance

- The five entities have stable config-entry-based IDs and are enabled by
  default for supported UPS families.
- No self-test entity is created for a Rack PDU.
- Tests cover the OID set (excluding `.7.2.2.0`), enum/date/time decoding,
  one partial SNMP failure, and supported-family entity setup.
- `./.venv/bin/pytest -q` and the repository lint workflow pass.

Use [requirements-issue-12.md](requirements-issue-12.md) as the detailed
reference; this contract controls scope when the two differ.
