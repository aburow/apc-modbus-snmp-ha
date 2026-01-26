# APC UPS Modbus Integration for Home Assistant

A Home Assistant integration for monitoring APC UPS and Rack PDU devices via Modbus/TCP protocol with SNMP device metadata.

## Features

### Multi-Device Support
- **Smart-UPS**: Traditional APC Smart-UPS devices
  - 39 comprehensive sensors
  - 12 binary sensors for status monitoring
  - Full battery and load monitoring

- **NetShelter Rack PDU**: APC power distribution units
  - Dynamic entity creation based on device capabilities
  - Device-level power measurements (kW, kVA, kWh)
  - Per-phase measurements (L1, L2, L3) with current, voltage, power
  - Per-outlet monitoring (up to 64 metered outlets)
  - Per-bank monitoring (up to 12 banks)

### Smart-UPS Sensors (39 total)
- Input/output voltage and current
- Battery charge percentage and runtime
- Load percentage and transfer switch status
- Temperature and firmware information
- Input/output frequency
- Real-time power measurements
- Status bits and fault indicators
- And more...

### Core Features
- **SNMP Required**: SNMP queries retrieve device model, serial number, firmware information
- **Dynamic Entity Generation**: Rack PDU creates only sensors for present hardware (no placeholder entities)
- **Easy Configuration**: Dropdown to select device type during setup
- **Local Communication**: Direct TCP/Modbus protocol (no cloud dependency)
- **Block Read Optimization**: Efficient register polling with fallback to individual reads

## Installation

### Using HACS (Recommended)

1. Go to HACS in Home Assistant
2. Click the three-dot menu and select "Custom repositories"
3. Add repository: `https://github.com/aburow/apc-modbus-snmp-ha`
4. Select "Integration" category
5. Install "APC UPS Modbus"
6. Restart Home Assistant

### Manual Installation

1. Copy `custom_components/apc_modbus/` to `config/custom_components/` on your Home Assistant instance
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Integrations
4. Click "Create Integration"
5. Search for "APC UPS Modbus"

## Configuration

After installation, set up the integration through the UI:

1. Go to **Settings → Devices & Services → Integrations**
2. Click **Create Integration**
3. Search for and select **APC UPS Modbus**
4. Fill in the required configuration:
   - **IP Address**: Modbus/TCP host address of the device
   - **SNMP Community**: SNMP community string (default: "public")
   - **Device Type**: Select from dropdown:
     - **Smart-UPS** - for APC Smart-UPS devices
     - **NetShelter Rack PDU** - for APC Rack PDU devices
5. Optional advanced settings:
   - **Device Name**: Friendly name for the device (default: "APC UPS")
   - **Port**: Modbus/TCP port (default: 502)
   - **Unit ID**: Modbus unit ID (default: 1)
   - **Scan Interval**: Update interval in seconds (default: 10)

### SNMP Requirement

SNMP is **mandatory** for all device types. The integration requires SNMP access to:
- Retrieve device model and identification
- Get firmware version information
- Obtain serial number
- Gather device-specific metadata for proper configuration

**Requirements:**
- SNMP service enabled on the device (port 161)
- Correct SNMP community string (usually "public")
- Network access to SNMP port from Home Assistant

## Supported Devices

### Smart-UPS
- Smart-UPS 500 / 750 / 1000 / 1500 / 2200 / 3000 VA and larger
- Smart-UPS VT series
- Smart-UPS C series
- Any Smart-UPS model with Modbus/TCP support

**Tested on:**
- Smart-UPS 1500
- Smart-UPS 3000

### NetShelter Rack PDU
- AP8xxx series (e.g., AP8652, AP8861)
- APDU models (e.g., APDU4-XM)
- Any NetShelter Rack PDU with Modbus/TCP support

**Capabilities:**
- 1 or 3 phase power distribution
- Up to 64 metered outlets
- Up to 12 branch circuits/banks
- Per-phase and per-outlet energy monitoring

**Tested on:**
- NetShelter Rack PDU AP8XXX series

## Requirements

- Home Assistant 2024.1 or later
- APC UPS or Rack PDU with:
  - **Modbus/TCP** enabled (port 502, configurable)
  - **SNMP** enabled (port 161)
- Network connectivity to the device
- Python 3.11+ (built into Home Assistant)

## Entity Discovery

### Smart-UPS
All 51 entities (39 sensors + 12 binary sensors) are created automatically upon setup.

### NetShelter Rack PDU
Entity creation is dynamic based on device capabilities:
- **Device-level sensors**: Always created (1 set)
  - Real Power, Apparent Power, Power Factor, Energy, Load State
- **Phase sensors**: Created based on number of phases (×1 or ×3)
  - Phase Current, Voltage, Power, Apparent Power, Power Factor, State
- **Outlet sensors**: Created for each metered outlet (×0-64)
  - Outlet Current, Power, Energy, Alarm State
- **Bank sensors**: Created for each bank (×0-12)
  - Bank Current, State

**Example:** A 3-phase Rack PDU with 24 metered outlets and 6 banks creates:
- 5 device-level sensors
- 18 phase sensors (6 per phase × 3 phases)
- 96 outlet sensors (4 per outlet × 24 outlets)
- 12 bank sensors (2 per bank × 6 banks)
- **Total: 131 entities**

## Troubleshooting

### SNMP Connection Failed
- **Error**: "Failed to query SNMP metadata"
- **Solution**:
  - Verify SNMP is enabled on the device
  - Check SNMP community string (usually "public" by default)
  - Verify network connectivity: `ping <device-ip>`
  - Check firewall rules allow port 161 (UDP)
  - Test SNMP manually: `snmpget -v 2c -c public <device-ip> 1.3.6.1.4.1.318.1.1.1.1.1.1.0`

### Modbus Connection Issues
- **Error**: "Unable to connect to APC device"
- **Solution**:
  - Verify device IP address and port are correct
  - Check network connectivity: `ping <device-ip>`
  - Ensure Modbus/TCP is enabled on the device
  - Check firewall rules allow port 502 (TCP)
  - Verify Home Assistant can reach port 502: `telnet <device-ip> 502`

### Missing Rack PDU Sensors
- **Issue**: Fewer outlet/bank sensors than expected
- **Solution**:
  - This is expected behavior! Only metered outlets/banks are monitored
  - Check device configuration for number of metered outlets/banks
  - Read capability registers to verify device configuration

### Slow Updates
- **Issue**: Long update cycle time (> 15 seconds)
- **Solution**:
  - Reduce scan interval setting if too frequent
  - Check Home Assistant system performance
  - For Rack PDU with many outlets, expect longer update cycles
  - Verify network latency to device: `ping <device-ip>`

### Device Type Not Detected
- **Issue**: Setup asks for device type instead of auto-detecting
- **Solution**:
  - This is now the expected behavior (manual selection required)
  - Select "Smart-UPS" or "NetShelter Rack PDU" from dropdown
  - Device type can be changed by removing and re-adding the integration

## Version History

### v0.2.0 (Current)
- ✨ Added multi-device-type support (Smart-UPS + Rack PDU)
- ✨ Added device type selection in config flow
- ✨ Made SNMP mandatory for all device types
- ✨ Added dynamic entity creation for Rack PDU
- ✨ Added capability discovery for Rack PDU
- 🔧 Refactored register management with factory pattern
- 📝 Comprehensive documentation updates

### v0.1.0
- Initial release with Smart-UPS support only
- Optional SNMP metadata

## Support

- **Issues**: Report bugs on [GitHub Issues](https://github.com/aburow/apc-modbus-snmp-ha/issues)
- **Documentation**: See [docs/testing/](docs/testing/) for implementation details

## License

See LICENSE file for details.

## Credits

Developed for Home Assistant integration with APC UPS and Rack PDU devices via Modbus/TCP protocol.
