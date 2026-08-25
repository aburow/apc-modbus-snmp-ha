# APC Modbus 2.1.x breaking changes

## Scope

This document compares the previous stable release, `v1.2.6`, with the current
stable release, `v2.1.0`.

`v2.1.0` is the HACS release line for the V2 architecture and opt-in write
testing controls.

## Summary

| Area | Breaking for a normal in-place upgrade? | Notes |
| --- | --- | --- |
| Existing configuration entry | No | Existing Modbus and SNMP-read settings continue to load. |
| Existing sensor and binary-sensor identities | No expected break | Runtime entity unique IDs retain the `apc_modbus_<entry_id>_<key>` format. |
| Existing diagnostic, re-detect, reset, and connection controls | No expected identity break | Their unique IDs are unchanged. **Run Diagnostics** is displayed as **Run plugin diagnostics**. |
| Automations and dashboards using existing entity IDs | No expected break | Review them after upgrade, especially if Home Assistant previously added numeric suffixes to entity IDs. |
| External Unified/bridge Python imports | **Yes** | The dependency-free bridge contract modules were removed. |
| Log-message parsers | **Yes** | Operational log wording and context were deliberately rewritten. |
| Legacy SNMP write setup | No | Configure the existing entry with a separate write community. |
| Write controls | No on upgrade | They are new and disabled by default. Enabling one opts that device into command testing. |

## Confirmed breaking changes

### Removed external Python bridge contracts

The following `v1.2.6` files and APIs are not present in 2.1.x:

- `custom_components.apc_modbus.capability_profiles_unified`
- `custom_components.apc_modbus.device_info_unified`
- `custom_components.apc_modbus.sensor_catalog_unified`
- `sensor_availability_unified.entity_enabled_default()`

This does not affect ordinary Home Assistant entities. It does break external
software that imports those modules, including any UPS Unified or
`ups-docker-ha` bridge code built against the published `v1.2.6` contracts.
Such consumers must remain on `v1.2.6` or be migrated to their own maintained
contract data before installing 2.1.x.

### Operational log text changed

2.1.x replaces many raw or entry-oriented messages with device-specific,
human-readable messages and aggregates repeated communication failures. Any
automation, scraper, alert, or test that matches exact `apc_modbus` log text
must be updated. Home Assistant entity state and availability should be used
instead of parsing log prose where possible.

### Legacy SNMP write community

2.1.x adds a separate **SNMP Write Community** field. Existing entries load it
as blank and never reuse the read community for writes. Open the integration's
**Configure** action to add or change it without re-adding the device. This
preserves the config-entry ID and existing entity identities.

## Intentional changes that are not upgrade breaks

### New write controls are opt-in

2.1.x adds fixed experimental command buttons:

- SMT/SMX/SRT and SmartConnect profiles: documented Modbus outlet, battery
  self-test, runtime-calibration, audible-alarm, and supported bypass commands.
- Legacy Smart-UPS profile: documented PowerNet SNMP `SET` commands when a
  separate write community is configured.
- Rack PDU profile: monitoring only; no write commands are exposed without a
  documented command map.

All write entities are disabled by default. Merely upgrading does not enable a
command or send a write. Modbus commands are sent once using function 16 and
are not automatically retried or replayed. SNMP commands use only the separate
write community.

### Reset Monitor Defaults has broader behavior

**Reset Monitor Defaults** still restores the basic sensor and binary-sensor
set for the detected device family. In 2.1.x it also disables all current write
controls and retained legacy `write_*` controls. If a tester enables commands,
pressing this reset button intentionally hides and disables them again.

### Display-only changes

- **Run Diagnostics** is renamed **Run plugin diagnostics** while retaining its
  existing unique ID.
- Device-type and operational notifications use clearer display labels.
- New command and operation-state entities may appear in the entity registry,
  disabled by default.

These changes may alter labels shown in the UI but should not change existing
entity IDs during an in-place upgrade.

## Recommended upgrade procedure

1. Create a Home Assistant backup.
2. Export or note APC entity IDs used by automations and dashboards.
3. Install `v2.1.0` through HACS and restart Home Assistant.
4. Confirm normal monitoring before enabling any write entity.
5. For legacy SNMP write testing only, set a distinct write-enabled community
   through **Configure**.
6. Run **Reset Monitor Defaults** to return a device to monitoring-only entity
   defaults after testing.

## Rollback

Downgrading to `v1.2.6` removes the 2.1.x command entities from the integration
runtime. Home Assistant may retain them as orphaned registry entries displaying
“This entity is no longer being provided by the apc_modbus integration.” Those
stale 2.1.x-only command entries can be deleted after verifying that no
automation or dashboard still references them.
