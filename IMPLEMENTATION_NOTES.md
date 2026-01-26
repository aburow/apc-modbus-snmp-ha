# Multi-Device-Type Support Implementation

## Overview

This document tracks the implementation of multi-device-type support for the APC Modbus/SNMP Home Assistant integration. The integration now supports both Smart-UPS and NetShelter Rack PDU devices with automatic SNMP-based device detection.

## Implementation Status

### ✅ Phase 1: Foundation (Complete)

**Files created:**
- `custom_components/apc_modbus/device_types.py` - Device type enumeration

**Files renamed:**
- `apc_modbus_registers.py` → `registers_smart_ups.py`

**Files modified:**
- `const.py` - Updated imports to use `registers_smart_ups`
- `coordinator.py` - Updated imports to use `registers_smart_ups`
- `snmp_helper.py` - Added `detect_device_type()` function

**Key changes:**
- Device type abstraction with `APCDeviceType` enum (SMART_UPS, RACK_PDU, UNKNOWN)
- SNMP-based device detection using model string pattern matching
- Backward-compatible default to SMART_UPS when SNMP unavailable

### ✅ Phase 2: Factory Pattern (Complete)

**Files created:**
- `custom_components/apc_modbus/register_factory.py` - Factory pattern for device-specific registers

**Files modified:**
- `coordinator.py` - Added device type and capabilities attributes, methods to set them
- `__init__.py` - Device type detection and capability discovery integration

**Key changes:**
- `APCModbusCoordinator` now stores:
  - `device_type` - Detected device type
  - `device_capabilities` - Device-specific capabilities (for Rack PDU)
  - `registers`, `register_blocks`, `register_map` - Dynamically loaded from factory
- Methods added:
  - `set_device_type()` - Set device type
  - `set_capabilities()` - Set device capabilities
  - `set_registers()` - Set registers for device type
  - `async_discover_capabilities()` - Discover Rack PDU capabilities via Modbus

### ✅ Phase 3: Rack PDU Register Definitions (Complete)

**Files created:**
- `custom_components/apc_modbus/registers_rack_pdu.py` - Rack PDU register definitions and functions

**Key features:**
- Capability registers for reading device configuration
- Device-level measurement registers (power, energy, state)
- Dynamic register generation functions:
  - `generate_phase_registers(num_phases)` - Phase L1/L2/L3 measurements
  - `generate_outlet_registers(num_outlets)` - Per-outlet measurements
  - `generate_bank_registers(num_banks)` - Per-bank measurements
- Sensor description functions for dynamic entity creation

### ✅ Phase 4: Dynamic Sensor Generation (Complete)

**Files modified:**
- `sensor.py` - Dynamic entity creation based on device type
- `binary_sensor.py` - Dynamic entity creation based on device type
- `registers_smart_ups.py` - Added `get_sensor_descriptions()` and `get_binary_sensor_descriptions()` functions
- `registers_rack_pdu.py` - Added `get_sensor_descriptions()` and `get_binary_sensor_descriptions()` functions

**Key changes:**
- Sensor platform now calls device-specific sensor description functions
- Smart-UPS uses static descriptions from `const.py` (39 sensors)
- Rack PDU generates dynamic descriptions based on discovered capabilities
- Binary sensors similarly support both static (Smart-UPS) and dynamic (Rack PDU) generation

### ⏳ Phase 5: Integration Testing (In Progress)

**Test scripts created:**
- `localonly/test_device_detection.py` - Tests device type detection logic ✅ PASSING
- `localonly/test_rack_pdu_capabilities.py` - Tests Rack PDU capability register reading

**Verification checklist:**
- [ ] Device Detection - Rack PDU vs Smart-UPS detection via SNMP
- [ ] Rack PDU Functionality - Capability discovery and dynamic entity creation
- [ ] Smart-UPS Backward Compatibility - All 39 entities present, unchanged IDs
- [ ] Error Handling - Graceful fallback when SNMP unavailable

## Architecture Changes

### Register Management

**Before (Static):**
```
const.py imports REGISTERS from apc_modbus_registers.py
├── coordinator.py imports from const.py
├── sensor.py uses static SENSOR_DESCRIPTIONS
└── binary_sensor.py uses static BINARY_SENSOR_DESCRIPTIONS
```

**After (Dynamic):**
```
Device Type Detection (SNMP)
├── Smart-UPS
│   ├── registers_smart_ups.py (REGISTERS, REGISTER_BLOCKS, REGISTER_MAP)
│   └── get_sensor_descriptions() → 39 sensors (static)
│
├── Rack PDU
│   ├── registers_rack_pdu.py (dynamic register generation)
│   ├── async_discover_capabilities() → read capability registers
│   └── get_sensor_descriptions(capabilities) → N sensors (dynamic)
│
└── register_factory.py (selects device-specific registers)
    └── APCModbusCoordinator (stores dynamic registers)
```

### Key Coordinator Attributes

```python
class APCModbusCoordinator:
    device_type: APCDeviceType  # SMART_UPS or RACK_PDU
    device_capabilities: dict   # {num_phases, num_outlets, num_banks, ...}
    registers: list             # Device-specific register definitions
    register_blocks: list       # Device-specific block read configuration
    register_map: dict          # Device-specific address → descriptor map
```

## Backward Compatibility

✅ **Smart-UPS installations unaffected:**
- Device type defaults to SMART_UPS if SNMP unavailable
- Same 39 sensors with unchanged entity IDs
- No changes to register definitions
- Zero user action required on upgrade

✅ **Graceful fallback:**
- If SNMP query fails, defaults to SMART_UPS
- If Rack PDU capability discovery fails, creates entities with default capabilities
- Modbus communication continues even if SNMP unavailable

## Testing Notes

### Device Detection Test
```
$ python3 localonly/test_device_detection.py

Testing device type detection:
✓ NetShelter Rack PDU AP8652 → rack_pdu
✓ AP8861 → rack_pdu
✓ APDU4-XM → rack_pdu
✓ Smart-UPS 1500 → smart_ups
✓ SMART-UPS VT → smart_ups
✓ Smart UPS 3000 → smart_ups
✓ None → smart_ups (default)
✓ Unknown Device → smart_ups (default)
```

### Model String Patterns
- **Rack PDU**: Contains "AP8", "APDU", or "RACK PDU"
- **Smart-UPS**: Contains "SMART-UPS" or "SMART UPS"
- **Default**: SMART_UPS (backward compatible)

## Known Limitations

1. **Rack PDU register addresses** - Based on limited documentation; may need adjustment for specific models
2. **Register blocks** - Rack PDU block read optimization not yet optimized (uses capability block only)
3. **Binary sensors** - Rack PDU currently has no binary sensors (can be added later)
4. **Environmental sensors** - Not yet implemented for Rack PDU

## Future Enhancements

1. Add more Rack PDU register blocks for optimized polling
2. Implement Rack PDU binary sensors (alarm states, etc.)
3. Add environmental sensor support (temp, humidity, smoke)
4. Support additional device types (Symmetra, Symmetra LX, etc.)
5. Add configuration option to manually override device type detection

## Files Summary

### Created
- `device_types.py` (349 B) - Device type enumeration
- `register_factory.py` (1.9 KB) - Factory pattern for device registers
- `registers_smart_ups.py` (17 KB) - Smart-UPS register definitions + functions
- `registers_rack_pdu.py` (17 KB) - Rack PDU register definitions + functions

### Modified
- `__init__.py` - Device type detection and capability discovery
- `const.py` - Import updates
- `coordinator.py` - Dynamic register management
- `sensor.py` - Dynamic entity creation
- `binary_sensor.py` - Dynamic entity creation
- `snmp_helper.py` - Device type detection function

### Deleted
- `apc_modbus_registers.py` - Renamed to `registers_smart_ups.py`

## Testing Hardware

**Available for testing:**
- Rack PDU: 192.168.100.117 (SNMP community: "public")
- Smart-UPS: 192.168.100.7, 192.168.100.8 (SNMP community: "public")

## Next Steps

1. **Manual testing** - Add devices to Home Assistant test instance
2. **Verify Smart-UPS** - Confirm all 39 entities, entity IDs unchanged
3. **Verify Rack PDU** - Confirm capability discovery, dynamic entity count
4. **Test SNMP fallback** - Block SNMP and verify Smart-UPS default
5. **Performance testing** - Monitor update cycle times
6. **Documentation** - Update README with device type support info
