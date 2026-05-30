# Changelog

All notable changes to the APC UPS Modbus integration will be documented in this file.

## [1.2.4-dev.1] - 2026-05-30
### Added
- Added dynamic SNMP external probe entity creation so newly detected AP9335T/AP9335TH temperature or humidity probes can be added after the hourly SNMP detection refresh without requiring a Home Assistant restart.
- Added diagnostics for Modbus TCP idle socket reuse. The diagnostics now test both a short 3-second idle interval and the configured Home Assistant polling interval, then report whether Keep Connection Open is likely to hit stale sockets.

### Fixed
- Fixed SNMP external probe entities being skipped when probe OID detection succeeded but no current probe value had been merged into coordinator data yet.

### Changed
- Synchronized authoritative integration/package version metadata to `1.2.4-dev.1`.

## [1.2.3] - 2026-05-13
### Added
- Added SNMP fallback/probe request hardening so candidate OIDs are pre-collected, deduplicated, fetched once per helper pass, and resolved locally in declared order.
- Added regression tests to guard SNMP fallback/probe request count, candidate order, and duplicate OID mapping behavior.

### Changed
- Updated release documentation for the `1.2.3` stable release.
- Synchronized authoritative integration/package version metadata to `1.2.3`.

## [1.2.3-dev.20] - 2026-04-20
### Added
- Added dependency-free `sensor_catalog_unified.py` with `ALL_SENSORS_UNIFIED` for exhaustive per-profile sensor picklists (`apc_modbus_smart`, `apc_modbus_smt`, `apc_modbus_rack_pdu`) without changing unified contract/profile membership semantics.

### Changed
- Synchronized authoritative integration/package version metadata to `1.2.3-dev.20`.

## [1.2.3-dev.19] - 2026-04-18
### Added
- Added `configuration_url` to Home Assistant device-info blocks so APC device pages include a direct management URL derived from the configured host (with IPv6-safe URL formatting).

### Changed
- Synchronized authoritative integration/package version metadata to `1.2.3-dev.19`.

## [1.2.3-dev.18] - 2026-04-18
### Fixed
- UPS phase-specific non-primary sensors (for example `_l2` and `_l3` variants) are now disabled by default in Entity Registry so single-phase SMT devices no longer surface Phase 2/3 zero-value placeholders by default.

### Changed
- Synchronized authoritative integration/package version metadata to `1.2.3-dev.18`.

## [1.2.3-dev.17] - 2026-04-17
### Added
- Hourly SNMP metadata refresh now also detects which external temperature/humidity probe OIDs are available, and selects the best SNMP input-frequency OID for the device.

### Changed
- External temperature/humidity probes are no longer polled unless they were detected during the hourly SNMP metadata refresh.
- SNMP input-frequency polling now runs in the same cycle as Modbus and only when Modbus did not provide `input_frequency` (covers SMT devices where line frequency is not available via Modbus).
- Modbus reconnect/recreate no longer forces an SNMP metadata refresh; metadata/probe detection remain on the hourly cadence.

## [1.2.3-dev.16] - 2026-04-17
### Added
- Added config-flow option `keep_connection_open` to optionally reuse Modbus TCP sessions across poll cycles.
- Added per-device `Keep Connection Open` switch entity on the device page to toggle open-session mode at runtime.

### Changed
- Added lock-safe reconnect helper flow shared across ensure/read/block retry paths.
- Added idle-session reconnect guard before polling when open-session mode is enabled.
- Poll timing breakdown now reports per-cycle reconnect/recreate counts.

## [1.2.3-dev.15] - 2026-04-17
### Changed
- Promoted coordinator poll timing breakdown logs to `INFO` level so full phase timing is visible without enabling integration debug logging.
- Updated troubleshooting docs to state that `Poll timing breakdown` is emitted at `info` level.

## [1.2.3-dev.14] - 2026-04-17
### Changed
- Added fleet-aware scan interval guarding so larger APC deployments automatically use a safer effective polling floor at runtime to reduce recorder/database pressure.
- Added coordinator info-level poll-phase timing breakdown (`total`, `lock_wait`, `modbus`, `connect`, `block_reads`, `individual_reads`, `close`, `snmp_metadata`, `snmp_external`) for faster hotspot identification.
- Documented the new poll timing breakdown log line in troubleshooting guidance.

### Added
- Added unit tests covering fleet-aware effective scan interval behavior across small, large, and capped-fleet scenarios.

## [1.2.3-dev.13] - 2026-04-14
### Added
- Added SNMP fallback for `input_frequency` on SMT/AP9640-class devices (APC enterprise OID first, UPS-MIB fallback), while keeping Modbus values as primary when available.
- Added diagnostics `snmp_decode` interpretation for input frequency source/value so customer reports clearly show which SNMP path is active.

### Changed
- Added debug-level source tracing for `input_frequency` resolution (Modbus retained, SNMP fallback, or output-frequency alias fallback), visible only when debug logging is enabled.
- Added SMT compatibility alias sensor exposure for `input_frequency` so entities appear consistently across Smart-UPS families.
- Added fleet-aware scan interval guarding: for larger APC fleets, runtime polling now applies a safe minimum interval to reduce Home Assistant recorder/database pressure.
- Added debug-level poll phase instrumentation in coordinator updates (`total`, `lock_wait`, `modbus`, `connect`, `block_reads`, `individual_reads`, `close`, `snmp_metadata`, `snmp_external`) to speed bottleneck isolation.

### Fixed
- Filled missing `input_frequency` for AP9640-backed SMT deployments where Modbus register map does not expose a dedicated numeric input-frequency register.
- Added regression tests to ensure fallback logic remains scoped correctly and does not affect Rack PDU profiles.

## [1.2.3-dev.12] - 2026-04-13
### Fixed
- Corrected Smart-UPS unified profile mappings for `input_voltage` and `input_frequency` to match the legacy APC register table used by Home Assistant.
- Corrected SMT unified profile mapping for `output_frequency` to the canonical register address.
- Added regression tests to lock Smart-UPS/SMT unified core register mappings and prevent future drift.

## [1.2.3-dev.11] - 2026-04-13
### Fixed
- Aligned UPS Unified Rack PDU defaults to the six core operational sensor keys (`device_apparent_power`, `device_energy`, `phase_l1_current`, `phase_l1_voltage`, `device_power_factor`, `device_real_power`).
- Metadata keys (`model`, `serial_number`, `sw_version`, `hw_version`) are no longer default-enabled as bridge sensor entities; they remain handled via device-info mapping.
- Updated Rack PDU unified capability profile defaults to include L1 current/voltage and exclude `num_*` keys from default-visible metrics.

## [1.2.3-dev.10] - 2026-04-13
### Fixed
- Updated `entity_enabled_default()` bridge behavior so Rack PDU core metrics are default-enabled without device-family context.
- Added explicit bridge metadata default policy (`model`, `serial_number`, `sw_version`, `hw_version` enabled-by-default) for deterministic UPS Unified behavior.
- Added `test_sensor_availability_unified_bridge_contract.py` to lock the bridge contract behavior.

## [1.2.3-dev.9] - 2026-04-13
### Changed
- Added a dedicated Rack PDU default monitor profile: core device + L1 metrics are now enabled by default, while dynamic outlet/bank/extra metrics remain opt-in.

## [1.2.3-dev.8] - 2026-04-13
### Added
- Added dependency-free `capability_profiles_unified.py` implementing UPS Unified interop contract version `2.0.0` with `apc_modbus_smart`, `apc_modbus_smt`, and `apc_modbus_rack_pdu` hybrid profiles.
- Added contract validation tests for unified interface import safety, deterministic no-raise behavior, profile key uniqueness, poll-group integrity, and hybrid key precedence.

## [1.2.3-dev.7] - 2026-04-12
### Added
- Coordinator data now injects bridge-consumable metadata keys each cycle (`manufacturer`, `model`, `serial_number`, `firmware_version`/`firmware`, `firmware_date`/`hw_version`) for Smart-UPS, SMT/SMX/SRT, and Rack PDU profiles.

### Changed
- SNMP metadata refresh is now cached on coordinator fields and refreshed on first cycle, reconnect, and periodic interval.
- Expanded `device_info_unified` tests with explicit smart/smt/rack_pdu source samples and unknown-marker filtering coverage.

## [1.2.3-dev.6] - 2026-04-12
### Added
- Added dependency-free `device_info_unified.py` with `resolve_device_info(values, source)` for ups-docker-ha bridge compatibility.
- Added acceptance tests covering import safety, canonical-key output constraints, malformed input handling, and deterministic metadata mapping.

## [1.2.3-dev.5] - 2026-04-12
### Added
- Added a per-device `Reset Monitor Defaults` button that reapplies integration default sensor/binary-sensor enablement in Home Assistant Entity Registry.

## [1.2.3-dev.4] - 2026-04-11
### Fixed
- Restored full block-read polling behavior for UPS families while keeping core-first entity availability defaults. Disabled-by-default sensors now affect visibility/opt-in only, not block polling strategy.

## [1.2.3-dev.3] - 2026-04-11
### Fixed
- Restored coordinator block-read compatibility for UPS core polling profiles by emitting core blocks with `name` and `start_address`, preventing `KeyError: 'name'` during refresh.

## [1.2.3-dev.2] - 2026-04-11
### Changed
- Added a dependency-free unified sensor availability policy module (`sensor_availability_unified.py`) to standardize default-enabled UPS core sensors.
- Updated sensor/binary entities so UPS extras are disabled by default via Entity Registry while keeping entities available for manual opt-in.
- Added setup-time UPS core polling profile selection to reduce register reads when only core entities are enabled.

## [1.2.3-dev.1] - 2026-04-11
### Changed
- Replaced local sensor/binary icon logic with the shared canonical `icons_unified.py` mapping module copied from `ups_unified_mqtt`, so icon behavior now aligns across projects.

## [1.2.2] - 2026-04-11
### Changed
- Improved startup stability for larger fleets with deterministic startup staggering to avoid synchronized first-run polling spikes.
- Switched startup device-family probing to a gated model (first add, strong SNMP/type conflict, or manual re-detect), avoiding unnecessary rediscovery work.
- Added a manual `Re-detect Device Type` button that updates stored type metadata and reloads only when detection state actually changes.
- Promoted coordinator update-cycle boundary timing logs to `INFO` for easier runtime visibility without full debug logging.
- Added explicit `mdi:` icon mapping for APC sensors and binary sensors (including dynamic Rack PDU entities) to avoid generic frontend fallback icons.

## [1.2.2-dev.7] - 2026-04-11
### Changed
- Added explicit `mdi:` icon mapping for APC sensors and binary sensors (including dynamic Rack PDU entities) so Home Assistant UI no longer relies on generic fallback icons.

## [1.2.2-dev.6] - 2026-04-10
### Changed
- Promoted coordinator update-cycle boundary logs (`Starting update cycle`, `Update cycle complete`) from `DEBUG` to `INFO` for easier poll-timing visibility in normal troubleshooting logs.

## [1.2.2-dev.5] - 2026-04-09
### Changed
- Switched startup device-family probing to a gated model: probe on first add, strong SNMP/type conflict, or manual re-detect instead of re-probing every startup.
- Automatic family rediscovery no longer runs for already classified devices just because of transient connection loss or detection-version drift.
- Added a manual `Re-detect Device Type` button that updates the stored family and reloads the entry only when the resolved detection state changes.

## [1.2.2-dev.4] - 2026-04-09
### Changed
- Added deterministic startup staggering across APC config entries so SNMP metadata reads, Modbus detection, capability discovery, and first refresh do not all run simultaneously in larger fleets.

## [1.2.2-dev.3] - 2026-04-08
### Fixed
- Device info model fallback now uses a family-aware label, so Rack PDU devices no longer show the generic `APC Device` label when SNMP model metadata is missing.

## [1.2.2-dev.2] - 2026-04-08
### Changed
- Startup Modbus revalidation now rechecks persisted concrete device types so improved probing logic can correct stale stored classifications without requiring re-add.
- Diagnostic collector now records the exact runtime probe calls and includes a derived detection summary based on those same probe results.

### Fixed
- Collector/runtime detection parity for the legacy UPS probe path so diagnostics now reflect the same count and decision inputs used by Home Assistant.

## [1.2.2-dev.1] - 2026-04-08
### Changed
- Improved Modbus family detection to classify UPS families from probe-success patterns using stronger discriminators (`0x0080` and `0x0021`) instead of requiring all probe blocks to succeed.

### Fixed
- Reduced false-ambiguous startup classification cases for devices where `0x0000` probe behavior is non-discriminative.

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
