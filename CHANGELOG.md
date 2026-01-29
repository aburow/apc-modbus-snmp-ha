# Changelog

All notable changes to the APC UPS Modbus integration will be documented in this file.

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
