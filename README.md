# APC UPS Modbus Integration for Home Assistant

A Home Assistant integration for monitoring and controlling APC UPS devices via Modbus/TCP protocol.

## Features

- **Real-time Monitoring**: Track UPS status, battery level, voltage, and power
- **39 Sensors**: Comprehensive sensor coverage including:
  - Input/output voltage and current
  - Battery charge percentage and runtime
  - Load percentage and transfer switch status
  - Temperature and firmware information
  - Input/output frequency
  - And more...

- **SNMP Device Metadata**: Optional SNMP queries to retrieve device model, serial number, and firmware information
- **Easy Configuration**: Simple config flow UI for setup
- **Local Communication**: Direct TCP/Modbus protocol (no cloud dependency)

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
4. Fill in the configuration:
   - **IP Address**: Modbus/TCP host address of the UPS
   - **Port**: TCP port (default: 502)
   - **Device Name**: Friendly name for the UPS (optional)
   - **Unit ID**: Modbus unit ID (default: 0)
   - **SNMP Community**: SNMP community string for metadata (default: public, optional)

## Supported Models

This integration works with any APC UPS that supports:
- **Modbus/TCP** protocol on port 502 (configurable)
- All Smart-UPS models with Modbus capability

## Requirements

- Home Assistant 2024.1 or later
- APC UPS with Modbus/TCP enabled
- Network connectivity to the UPS

## Troubleshooting

### Connection Issues
- Verify the UPS IP address and port are correct
- Check network connectivity: `ping <ups-ip>`
- Ensure Modbus/TCP is enabled on the UPS

### Missing Sensors
- Some sensors may not be available on all UPS models
- Check UPS logs for Modbus communication errors

### SNMP Metadata Not Loading
- Verify SNMP is enabled on the UPS
- Check the community string (usually "public" by default)
- SNMP is optional - sensors work without it

## Support

- **Issues**: Report bugs on [GitHub Issues](https://github.com/aburow/apc-modbus-snmp-ha/issues)

## License

See LICENSE file for details.

## Credits

Developed for Home Assistant integration with APC UPS devices via Modbus/TCP protocol.
