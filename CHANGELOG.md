# Changelog

All notable changes to the APC UPS Modbus integration will be documented in this file.

## [1.2.1] - 2026-04-05
### Fixed
- Redacted sensitive diagnostics output before display: IP addresses, serial-like values, and SNMP community values.
- Removed direct serial-number OIDs from diagnostic SNMP collection.
- Removed host address from diagnostics completion log line.

## [1.2.0] - 2026-04-05
### Added
- External temperature and humidity sensor support via APC SNMP Universal I/O probe OIDs.
- Manual per-device diagnostics button with on-demand SNMP + Modbus dump output in Home Assistant.

### Changed
- Improved external probe compatibility across APC/NMC OID instance indexing variants and value scaling formats.
- Optional external probe entities are only created when probe values are present.

## [1.2.0-dev.4] - 2026-04-04
### Changed
- Optional external SNMP probe entities (temperature/humidity) are now only created when probe values are actually returned.
- Core UPS/PDU entities remain unchanged; only optional probe entities are suppressed when no probe is connected.

## [1.2.0-dev.3] - 2026-04-03
### Fixed
- External SNMP probe OID indexing now supports APC table layouts that require `.X.1` instance suffixes (with fallback for legacy suffixing).
- External probe scaling now handles devices that report whole-number temperature/humidity values instead of tenths.

### Changed
- Marked external probe sensors as Home Assistant `temperature` / `humidity` device classes for correct unit handling.

## [1.2.0-dev.2] - 2026-04-02
### Added
- New per-device `Run Diagnostics` button entity in Home Assistant.
- On-demand diagnostic collector output (SNMP + Modbus raw and decoded blocks) shown via persistent-notification modal for fast troubleshooting.

### Changed
- Added `button` platform to supported integration platforms.
- Updated README feature documentation for the manual diagnostics flow.

## [1.1.0] - 2026-03-28
### Added
- Automatic first-run device type detection for legacy Smart-UPS, SMT/SMX/SRT, and Rack PDU families.

### Changed
- Improved Rack PDU/UPS classification behavior and startup resilience across ambiguous probe results.
- Expanded compatibility across common `pymodbus` unit-id call signatures used by Home Assistant environments.
- Updated documentation for current Home Assistant runtime expectations and troubleshooting workflows.

### Fixed
- Stale entity cleanup when resolved device type/capabilities change.
- Multiple detection and metadata edge cases observed during mixed UPS/PDU deployments.

## [1.1.0-dev.13] - 2026-03-27
### Fixed
- Remove stale sensor and binary sensor entities when the resolved device type/capabilities change, preventing mixed UPS + Rack PDU entity sets on a single device entry.

## [1.1.0-dev.12] - 2026-03-27
### Fixed
- Revalidate stored `smart_ups` config entries at startup and auto-correct them to `smt_ups` when Modbus probe results indicate SMT/SMX/SRT behavior.
- Persist corrected concrete device type back into the config entry to avoid recurring misclassification on future restarts.

## [1.1.0-dev.11] - 2026-03-24
### Fixed
- SNMP metadata lookup now uses auto OID selection when device type is unknown, so device info model/serial/firmware fields are populated correctly for both UPS and Rack PDU during auto-detect setup.

## [1.1.0-dev.10] - 2026-03-24
### Fixed
- Improved first-run device classification for Rack PDU by treating Modbus exception responses as errors and requiring expected register counts in probe responses.
- Fixed Rack PDU false-ambiguous detection cases that previously defaulted to `smart_ups`.

### Changed
- Added broader `pymodbus` API compatibility in Modbus read calls to tolerate unit-id argument variants (`device_id`, `slave`, `unit`, positional) across environments.
- Auto-detection fallback now uses a strong SNMP Rack PDU model hint when Modbus probe results are ambiguous.
- Updated display precision for `load_percent` and `input_frequency` sensors to one decimal place.

## [1.1.0-dev.9] - 2026-03-24
### Fixed
- Avoid crashing SNMP metadata lookup when device type is not yet known during auto-detection setup.

### Changed
- Track repo lint/security tooling and ignore local artifacts so git, pre-commit, Semgrep, and CodeQL operate on source files instead of local caches.
- Keep Home Assistant runtime dependencies unchanged; no new integration libraries were added.

## [1.1.0-dev.8] - 2026-03-24
### Changed
- Config flow now auto-detects device type instead of asking the user to choose UPS vs Rack PDU.
- Setup now probes Modbus on first run to distinguish Rack PDU, legacy Smart-UPS, and SMT/SMX/SRT Smart-UPS families.
- Updated README documentation for auto-detection and current Python requirements.

## [1.1.0-dev.7] - 2026-03-18
### Changed
- Documented how to enable Home Assistant debug logging for this integration.
- Added a link to the standalone `apc_modbus_debug` data collection repository.

## [1.1.0-dev.6] - 2026-03-18
### Changed
- Added compatibility for both older and newer PyModbus client read APIs (`slave` and `device_id`).
- Kept local lint and scan tooling out of version control while retaining a clean manual check flow.

## [1.1.0-dev.2] - 2026-03-05
### Added
- Support for Smart-UPS SMT/SMX/SRT models via a dedicated register map and entity set.

### Changed
- Config flow now offers separate Smart-UPS legacy vs SMT/SMX/SRT device type options.
- Device type detection and register selection updated for SMT/SMX/SRT model families.

### Credits
- Initial SMT/SMX/SRT contribution by @brentavery.

## [1.1.0-dev.3] - 2026-03-06
### Added
- Expanded SMT/SMX/SRT register coverage: apparent power, phase 2/3 readings, and bypass metrics.

### Changed
- Updated SMT/SMX/SRT device detection documentation to reflect the supported model prefixes.

## [1.1.0-dev.4] - 2026-03-07
### Changed
- Treat "Smart-UPS X" model strings as SMX for device detection.

## [1.0.0] - 2026-02-08
### Changed
- Administrative updates and APC icon/logo refresh.

### Notes
- First stable 1.0.0 release.

## [0.4.2a] - 2026-02-06
### Changed
- Administrative updates and APC icon/logo refresh.

## [0.4.2] - 2026-01-29

### Fixed
- Avoid accessing device_type before it is set during coordinator init

## [0.4.1] - 2026-01-29

### Fixed
- Add small pacing delays between block reads; longer delays for Rack PDU

## [0.4.0] - 2026-01-29

### Added
- Architecture overview and diagram in README

### Changed
- Modbus I/O is serialized per host:port and connects/closes per update cycle
- SNMP metadata queries run in an executor to avoid event loop blocking

### Fixed
- Recreate Modbus client on socket errors; add reconnect and backoff handling
- Added detailed timing logs for connect/close and block reads

## [0.3.6-dev.6] - 2026-01-29

### Fixed
- Connect/close per update cycle to avoid stale sockets; log connect/close timing

## [0.3.6-dev.5] - 2026-01-29

### Fixed
- Recreate Modbus client immediately after broken pipe/reset errors

## [0.3.6-dev.4] - 2026-01-29

### Added
- Extra debug logging for I/O lock acquisition and per-block timing

## [0.3.6-dev.3] - 2026-01-29

### Fixed
- Run SNMP metadata queries in an executor to avoid blocking the main event loop

## [0.3.6-dev.2] - 2026-01-29

### Fixed
- Serialize Modbus access per host:port to prevent overlapping reads across entries

## [0.3.6-dev.1] - 2026-01-29

### Fixed
- Serialize Modbus socket access to prevent concurrent reads causing disconnects/broken pipe

## [0.3.4] - 2026-01-26

### Added
- APC Modbus branded icons for the integration
- Rack PDU SNMP OIDs and phase sensor block reads for improved coverage

### Changed
- Integration icon updated to `mdi:uninterruptible-power-supply`

### Fixed
- SNMP async API usage updated for pysnmp v3arch compatibility (PySnmp 7.1.22)
- Removed invalid manifest icon reference

## [0.1.0] - 2026-01-25

### Added
- Initial release of APC UPS Modbus integration
- 39 sensors for comprehensive UPS monitoring
- Modbus/TCP protocol support
- Optional SNMP device metadata retrieval
- Configuration UI for easy setup
- Support for multiple APC UPS devices
- Battery status, load, voltage, and temperature monitoring
- Transfer switch and power failure detection
- Firmware and device information via SNMP

### Features
- Real-time UPS status monitoring
- Input/output voltage and current sensors
- Battery charge percentage and runtime estimation
- Load percentage and power distribution
- Device model, serial number, and firmware version (via SNMP)
- Graceful fallback if SNMP is unavailable

### Fixed
- Resolved SNMP dependency conflict with Home Assistant core
- Improved error handling for connection timeouts
- Fixed block read optimization for Modbus queries

---

For detailed information about each release, visit the [releases page](https://github.com/aburow/apc-modbus-snmp-ha/releases).
