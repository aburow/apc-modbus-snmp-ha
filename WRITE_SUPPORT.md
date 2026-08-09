# Modbus write support status

The `2.0.0-dev` code contains the safety-gated implementation for APC Modbus
commands for SMT/SMX and SmartConnect SMT devices. SKU `SMT750IC` with UPS
firmware `18.0` is temporarily allowlisted for controlled physical acceptance
on a noncritical load. This is not yet a release-support claim.

## Capability matrix

Every conditional cell also requires an exact hardware-accepted SKU/UPS-firmware pair,
the documented protocol constants, zero client retries, and valid companion
status evidence.

| Resolved device | Outlet actions | Battery self-test | Runtime calibration | Alarm mute | Timing configuration |
| --- | --- | --- | --- | --- | --- |
| Eligible `SMT_UPS` SMT 9.0+ | Conditional | Conditional | Conditional | Conditional | Blocked |
| SmartConnect `SMT750IC` firmware `18.0` candidate | Conditional | Conditional | Conditional | Conditional | Blocked |
| Eligible `SMT_UPS` SMX 10.0+ | Conditional | Conditional | Conditional | Conditional | Blocked |
| SRT, SRC, SURTD, or SMT Rack Mount 1U | No | No | No | No | No |
| Other SmartConnect, legacy Smart-UPS, Rack PDU, unknown | No | No | No | No | No |

`Conditional` is not a support claim. At present, only the exact `SMT750IC`
SKU with UPS firmware `18.0` may proceed to per-feature discovery for manual
acceptance testing. The identity gate reads SKU from `0x0224`; the descriptive
model name at `0x0214` is not used as an allowlist key.

## Implemented safety model

- Only fixed outlet, battery-test, calibration, and alarm commands exist; there
  is no raw-register service.
- Capabilities are discovered per feature from readable companion registers.
  Command addresses are never read as probes.
- All Modbus clients use zero internal retries. Once a write function is
  invoked, no exception path replays it.
- Commands are serialized, conflicts are rechecked under the I/O lock, and
  results are reconciled through status registers after releasing the lock.
- Unknown outcomes block another command for the same target until later status
  evidence resolves them or the integration is reloaded.
- Native Home Assistant switches, buttons, and diagnostic enum sensors are
  disabled by default. Unsupported features create no entity.
- Battery self-test and runtime calibration are asynchronous. Calibration
  intentionally discharges the battery and is not an instantaneous self-test.

## Write audit messages

The coordinator records one concise lifecycle trail for every allowlisted
write. A rejected command is reported as **not sent**. Once Modbus invocation
has occurred, it is reported as **sent once**; a validated Modbus response does
not itself prove the physical operation completed. Reconciliation reports the
existing operation status. If the outcome is ambiguous, the message states
that it **may have been applied**, was **not retried**, and requires device
state verification. The integration never automatically replays a write after
invocation.

## Open release gates

1. Run and archive the contract's noncritical-load physical acceptance record
   for the candidate SKU `SMT750IC`/`18.0` pair. Remove it from the allowlist if it
   fails; no physical acceptance has yet been claimed.
2. Obtain authoritative per-model minimum, maximum, and step values for every
   `0x0405`--`0x0418` timing field. No `NumberEntity` exists until that evidence
   is tracked and tested.
3. Record the project owner's review of APC Application Notes #176 and #177
   publication/commercial-use terms. Vendor PDFs are not included in Git.

The first release must advertise only exact SKU/firmware combinations with a
passing acceptance record. Family prefixes alone are never sufficient.
