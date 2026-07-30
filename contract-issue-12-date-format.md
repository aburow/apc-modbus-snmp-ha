# Issue 12 live-device date-format fix contract

## Outcome

Make `Last Self-Test Date` available for APC devices that return the valid
PowerNet date as `mm/dd/yyyy` as well as `mm/dd/yy`.

## Required change

- Update only the self-test date parser in `snmp_helper.py`.
- Accept exactly `mm/dd/yy` and `mm/dd/yyyy`, returning a Python `date`.
- Preserve current behavior for blank, malformed, and impossible dates: return
  `None`, so Home Assistant reports the entity as unavailable.
- Do not change the queried OIDs, polling cadence, enum decoding, entity
  registration, time/day handling, or device URL behavior.

## Regression coverage

- Extend the existing self-test parser test with `07/31/2026` mapping to
  `date(2026, 7, 31)`.
- Retain coverage for `07/31/26` and invalid dates.

## Acceptance

- The live response from `192.168.100.7` (`07/31/2026`) parses to
  `date(2026, 7, 31)`.
- `./.venv/bin/pytest -q` and `make lint` pass.
