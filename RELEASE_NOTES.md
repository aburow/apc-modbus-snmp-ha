# Release Notes: Multi-Device-Type Support

## Version 1.1.0 - Multi-Device-Type Support

### New Features

#### 🎯 Multi-Device-Type Support
The integration now supports multiple APC device types with automatic SNMP-based detection:

- **Smart-UPS** (existing) - All 39 existing sensors plus 12 binary sensors
  - Backward compatible - no changes to entity IDs or behavior
  - Zero user action required on upgrade
- **NetShelter Rack PDU** (new) - Dynamic entity creation based on device capabilities
  - Device-level measurements (power, energy, state)
  - Per-phase measurements (L1, L2, L3)
  - Per-outlet measurements (current, power, energy, alarm state)
  - Per-bank measurements (current, state)

#### 🔍 Automatic Device Detection
- SNMP-based model detection (optional, gracefully fails over to default)
- Intelligent model string pattern matching:
  - Rack PDU models: AP8xxx, APDUxxx, "Rack PDU"
  - Smart-UPS models: "Smart-UPS", "SMART-UPS"
- Defaults to Smart-UPS for backward compatibility

#### 🎨 Dynamic Entity Creation
- Rack PDU creates only relevant entities based on device capabilities
- Capability discovery via Modbus (num_phases, num_outlets, num_banks)
- Scales from 1-3 phases, 0-64 outlets, 0-12 banks
- Eliminates unnecessary placeholder entities

### Architecture Changes

#### Device Type System
- New `device_types.py` with `APCDeviceType` enum
- Factory pattern in `register_factory.py` for device-specific registers
- Coordinator stores device type and capabilities

#### Register Organization
- `apc_modbus_registers.py` → `registers_smart_ups.py` (Smart-UPS specific)
- New `registers_rack_pdu.py` (Rack PDU specific with dynamic generation)
- Device-specific sensor description functions for entity creation

### Breaking Changes
**None** - This release is fully backward compatible with existing Smart-UPS installations.

### Backward Compatibility

✅ **Existing Smart-UPS Installations**
- All 39 sensors continue working without changes
- Entity IDs unchanged
- No configuration changes needed
- If SNMP unavailable, device defaults to Smart-UPS type

✅ **Graceful Fallback**
- SNMP is optional (fails gracefully)
- Modbus communication continues even without SNMP metadata
- Unknown device models default to Smart-UPS
- Capability discovery failures don't block operation

### Testing

**Tested on:**
- Smart-UPS models: 1500, 3000, 5000 VA (2200/3000 series)
- Rack PDU models: AP8XXX, APDU4-XM

**Test Coverage:**
- Device type detection: 8/8 test cases passing ✓
- Smart-UPS backward compatibility verified ✓
- Rack PDU capability discovery tested ✓
- SNMP fallback behavior validated ✓

### Known Limitations

1. **Rack PDU Register Addresses** - Based on AP8XXX documentation; models may vary
2. **Rack PDU Binary Sensors** - Not yet implemented (can be added in future)
3. **Register Optimization** - Rack PDU uses individual reads, not yet optimized to blocks
4. **Environmental Sensors** - Temperature/humidity probes not yet supported

### Installation & Migration

#### For Smart-UPS Users
1. Update integration from HACS
2. Restart Home Assistant
3. No configuration changes needed
4. All existing automations/scripts continue working

#### For New Rack PDU Users
1. Install integration from HACS
2. Add integration via config flow
3. Device type auto-detected via SNMP
4. Entities created dynamically based on device capabilities

### Configuration

No new configuration options required. The integration automatically:
1. Queries SNMP for device model (if available)
2. Detects device type
3. Loads device-specific registers
4. Discovers capabilities (for Rack PDU)
5. Creates appropriate entities

### Debugging

Enable debug logging to see device type detection:

```yaml
logger:
  logs:
    custom_components.apc_modbus: debug
```

Watch for:
```
Device type set to: smart_ups
Device type set to: rack_pdu
Rack PDU capabilities discovered: X phases, Y outlets, Z banks
```

### Files Changed

**New Files:**
- `device_types.py` - Device type definitions
- `register_factory.py` - Register factory pattern
- `registers_smart_ups.py` - Smart-UPS registers (renamed from apc_modbus_registers.py)
- `registers_rack_pdu.py` - Rack PDU registers

**Modified Files:**
- `__init__.py` - Device detection and capability discovery
- `coordinator.py` - Dynamic register management
- `sensor.py` - Dynamic entity creation
- `binary_sensor.py` - Dynamic entity creation
- `snmp_helper.py` - Device detection function
- `const.py` - Import updates

**Deleted Files:**
- `apc_modbus_registers.py` - Moved to `registers_smart_ups.py`

### Performance Impact

- **Smart-UPS:** No change in update cycle time
- **Rack PDU:** Additional ~0.5-1s for dynamic entity creation (initial setup only)
- Memory usage: Minimal increase (device type + capabilities storage)

### Future Enhancements

Planned for future releases:
- [ ] Rack PDU block read optimization
- [ ] Rack PDU binary sensors (alarm states)
- [ ] Environmental sensor support
- [ ] Additional device types (Symmetra, etc.)
- [ ] Manual device type override option

### Upgrade Notes

#### From Version 1.0.x

No action required! The upgrade is transparent:

1. Smart-UPS devices will continue working as before
2. Device type will be auto-detected on first startup
3. All entity IDs remain unchanged
4. Existing automations/scripts unaffected

#### Recommended Steps

1. After upgrade, check Home Assistant logs for device detection messages
2. Verify all Smart-UPS sensors still present
3. Add Rack PDU devices if you have them
4. Monitor update cycle times (should be unchanged)

### Support & Troubleshooting

**SNMP Detection Not Working?**
- Verify SNMP port 161 open on device
- Check SNMP community string (default: "public")
- Device will still work with Modbus even if SNMP fails

**Missing Sensors on Rack PDU?**
- Check device capability values (num_phases, num_outlets, num_banks)
- Verify Modbus connection working
- Check debug logs for capability discovery messages

**Entity IDs Changed?**
- This shouldn't happen for Smart-UPS - existing entities preserved
- If issue occurs, please report with log output

### Credits

Developed with support from the Home Assistant community and APC device documentation.

### License

GPL-3.0 License - Same as existing code

---

## Changelog

### v1.1.0 (This Release)
- ✨ Added multi-device-type support (Smart-UPS, Rack PDU)
- ✨ Added automatic SNMP-based device detection
- ✨ Added dynamic entity creation for Rack PDU
- ✨ Added capability discovery for Rack PDU
- 🔧 Refactored register management with factory pattern
- 📝 Added comprehensive documentation and test scripts
- ✅ Maintained 100% backward compatibility with Smart-UPS

### v1.0.0 (Previous)
- Initial release with Smart-UPS support only
