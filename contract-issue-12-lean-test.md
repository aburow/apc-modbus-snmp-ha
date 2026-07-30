# Issue 12 lean-test follow-up contract

## Outcome

Remove the hand-built Home Assistant test harness in
`tests/test_self_test_sensor_setup.py` without reducing coverage of the five
self-test keys or their default availability.

## Required change

- Delete `tests/test_self_test_sensor_setup.py` in full.
- Keep the existing self-test availability test and extend it, if needed, so
  all five keys are asserted enabled for a UPS family and disabled for a Rack
  PDU.
- Add at most one small, direct assertion of the five self-test sensor
  description keys if the current tests do not otherwise pin that list.
- Do not fake Home Assistant modules, dynamically load `sensor.py`, or add
  replacement fixtures/helpers.

## Boundaries

- Do not alter runtime integration code or self-test behavior.
- Do not change the Issue 12 requirements or delivery contract.
- Keep existing focused SNMP decoding coverage.

## Acceptance

- The test harness file is deleted.
- The remaining tests directly cover the five keys and their UPS/Rack-PDU
  availability policy.
- `./.venv/bin/pytest -q` and `make lint` pass.
