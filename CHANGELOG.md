# Changelog

All notable changes to the APC UPS Modbus integration will be documented in this file.

## [1.1.0-dev.2] - 2026-03-05
### Added
- Support for Smart-UPS SMT/SMX/SRT models via a dedicated register map and entity set.

### Changed
- Config flow now offers separate Smart-UPS legacy vs SMT/SMX/SRT device type options.
- Device type detection and register selection updated for SMT/SMX/SRT model families.

### Credits
- Initial SMT/SMX/SRT contribution by @brentavery.

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
